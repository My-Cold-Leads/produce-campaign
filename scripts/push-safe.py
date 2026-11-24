#!/usr/bin/env python3
"""Push leads into a Smartlead campaign through the gates the raw endpoint skips.

Dry run is the DEFAULT. Nothing is sent and nothing is logged until you pass --apply.

Gates, in order. Every skipped lead is printed with its reason:
  1. Email syntax, and repeats of the same person (case-insensitive email).
  2. Personal mailbox domains (gmail.com and similar), only when --exclude-personal-emails
     is set. This is a per-client choice; put it in the client config.
  3. Suppression / do-not-contact, at contact AND company-domain level (subdomains included).
     Database mode reads contacts.do_not_contact and companies.do_not_contact.
     File mode REQUIRES --suppression FILE (emails and domains, one per line or a JSON list).
  4. Email status: only verified statuses pass (valid, verified, deliverable_catchall by default;
     change with --allow-status). Database mode reads contacts.email_status and skips anyone
     with no contacts row. File mode reads the email_status column of the lead file.
  5. Prior reply outcome (database mode): anyone who already answered interested, booked a
     meeting, asked for information, or said wrong person / left the company is never
     cold-emailed again for this client, however old the reply.
  6. Cooldown: anyone in your outreach log for this client whose
     COALESCE(first_sent_date, loaded_date) is inside the window (90 days by default) is skipped.
     A queued-but-unsent lead counts as contacted.
  7. Merge fields, when --template FILE is given: a lead missing any {{variable}} the template
     uses is skipped, because an empty field renders as a blank.
  8. Approval fingerprint (required with --apply): --approval FILE must name this campaign and
     client, carry approved_by and approved_at, and list the hash of every lead being pushed.
     The approved set may shrink. A new or edited lead, or an edited template, stops the push.
  9. Campaign / client match (needs SMARTLEAD_API_KEY): the campaign is read back from the
     platform. Its name must equal --campaign-name, or contain the --client string when no name
     is given. A client name with no history in a non-empty outreach log is refused unless you
     pass --first-push-for-client, because a mistyped client silently disables the cooldown.
 10. Live platform membership (always on --apply, or --live-check on a dry run): each address is
     looked up on the platform. Skipped when it was sent from another campaign of the same
     platform client inside the cooldown window, sits unsent in another unfinished campaign, or
     is unsubscribed. A lookup that fails skips that lead: unverifiable is not safe.

Then it forces the three platform settings to false on every request, whatever the input says
(ignore_global_block_list, ignore_unsubscribe_list, ignore_duplicate_leads_in_other_campaign),
POSTs in batches of up to 1,000, reconciles each batch against total_leads (not upload_count),
writes one outreach log row per lead at push time, and persists a state line per batch.

What it cannot prove: that a human wrote the approval file. It proves the push set is the set
that was reviewed. Keep the approval step with a person.

Typical flow:
  # 1. dry run, and write the approval request for the reviewer
  python3 scripts/push-safe.py --campaign 12345 --client ACME --leads leads.csv \\
      --outreach-log outreach_log.json --suppression suppression.txt \\
      --template e1.html --write-approval-request approval.json
  # 2. the reviewer fills approved_by / approved_at in approval.json
  # 3. push
  SMARTLEAD_API_KEY=... python3 scripts/push-safe.py --campaign 12345 --client ACME \\
      --campaign-name "ACME E1" --leads leads.csv --outreach-log outreach_log.json \\
      --suppression suppression.txt --template e1.html --approval approval.json --apply

Sources, pick one: DATABASE_URL / --database-url (tables from setup/schema.sql, needs psycopg or
psycopg2), or --outreach-log FILE.json plus --suppression FILE.

Lead file columns: email (required), first_name, last_name, company_name, phone_number, website,
location, linkedin_profile, company_url. contact_id and email_status are read by the gates and
never sent. Any other column becomes a custom field. In JSON, a lead may also carry a
custom_fields object. Python 3 standard library only, plus the optional database driver.
"""
import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://server.smartlead.ai/api/v1"
MAX_BATCH = 1000
DEFAULT_COOLDOWN_DAYS = 90
DEFAULT_OK_STATUSES = ("valid", "verified", "deliverable_catchall")
FORCED_SETTINGS = {
    "ignore_global_block_list": False,
    "ignore_unsubscribe_list": False,
    "ignore_duplicate_leads_in_other_campaign": False,
}
STANDARD_FIELDS = ("email", "first_name", "last_name", "company_name", "phone_number",
                   "website", "location", "linkedin_profile", "company_url")
LOG_ONLY_FIELDS = ("contact_id", "email_status")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MERGE_VAR_RE = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")
REJECTION_KEYS = ("block_count", "duplicate_count", "invalid_email_count", "already_added_to_campaign",
                  "bounce_count", "lead_import_stopped_count")
# Common personal mailbox providers. Extend per market with --freemail-domains FILE.
FREEMAIL_DOMAINS = frozenset("""gmail.com googlemail.com outlook.com outlook.es hotmail.com hotmail.es
hotmail.co.uk hotmail.fr live.com live.co.uk msn.com yahoo.com yahoo.es yahoo.co.uk yahoo.fr ymail.com
icloud.com me.com mac.com aol.com gmx.com gmx.de gmx.net web.de mail.com proton.me protonmail.com
zoho.com yandex.com yandex.ru telefonica.net terra.es orange.fr wanadoo.fr free.fr libero.it
t-online.de btinternet.com comcast.net""".split())
# Reply categories that end cold outreach to that person for this client for good.
PERMANENT_OUTCOMES = ("interested", "meeting_booked", "meeting_request", "information_request",
                      "forwarded_internally", "wrong_person", "left_company", "unsubscribe")
FINISHED_STATUSES = frozenset(("COMPLETED", "STOPPED", "ARCHIVED"))


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def parse_time(value):
    when = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)


def domain_of(email):
    return email.rsplit("@", 1)[-1].strip().lower()


def domain_and_parents(domain):
    """mail.bigcorp.com -> mail.bigcorp.com, bigcorp.com (never the bare TLD)."""
    parts = domain.split(".")
    return [".".join(parts[i:]) for i in range(0, max(1, len(parts) - 1))]


# ---------------------------------------------------------------- lead input

def read_rows(path):
    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            # Anything else at the top level, including a "settings" object, is ignored on purpose.
            data = data.get("leads") or data.get("lead_list") or []
        return [r for r in data if isinstance(r, dict)]
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def to_lead(row):
    """Split a raw row into (lead payload, contact_id)."""
    lead, custom = {}, {}
    for key, value in row.items():
        if key is None or value is None:
            continue
        if key == "custom_fields" and isinstance(value, dict):
            custom.update({str(k): "" if v is None else str(v) for k, v in value.items()})
        elif key in STANDARD_FIELDS:
            lead[key] = str(value).strip()
        elif key in LOG_ONLY_FIELDS or key == "settings":
            continue
        else:
            custom[str(key)] = str(value)
    if custom:
        lead["custom_fields"] = custom
    contact_id = str(row.get("contact_id") or "").strip() or None
    return lead, contact_id


# ---------------------------------------------------------------- suppression file

def read_suppression(path):
    """Emails and domains to never contact. Text (one per line, # comments) or a JSON list of
    strings / {"email": ..} / {"domain": ..} objects. Returns (emails, domains)."""
    with open(path, encoding="utf-8-sig") as fh:
        text = fh.read()
    items = []
    if text.lstrip().startswith("["):
        for entry in json.loads(text):
            if isinstance(entry, dict):
                items.extend(str(entry.get(k) or "") for k in ("email", "domain"))
            else:
                items.append(str(entry))
    else:
        items = [line.split("#", 1)[0] for line in text.splitlines()]
    emails, domains = set(), set()
    for item in items:
        item = item.strip().lower()
        if not item:
            continue
        if "@" in item and not item.startswith("@"):
            emails.add(item)
        else:
            domains.add(item.lstrip("@"))
    return emails, domains


# ---------------------------------------------------------------- sources

class FileLog:
    """Outreach log kept as a JSON list, for installs without direct database access."""
    mode = "file"

    def __init__(self, path):
        self.path = path
        self.rows = []
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                self.rows = json.load(fh)

    def client_known(self, client):
        """(log has rows, log has rows for this client)."""
        return bool(self.rows), any(r.get("client_name") == client for r in self.rows)

    def recent(self, client, emails, days):
        cutoff = now_utc() - dt.timedelta(days=days)
        wanted = set(emails)
        hit = set()
        for r in self.rows:
            email = str(r.get("email") or "").strip().lower()
            if email not in wanted:
                continue
            if r.get("client_name") not in (None, "", client):
                continue
            stamp = r.get("first_sent_date") or r.get("loaded_date")
            if not stamp:
                continue
            if parse_time(stamp) > cutoff:
                hit.add(email)
        return hit

    def write(self, rows):
        """Append rows and rewrite atomically. Returns (written, failures)."""
        self.rows.extend(rows)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.rows, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)
        return len(rows), []


class DbLog:
    """The tables from setup/schema.sql."""
    mode = "database"

    def __init__(self, url):
        try:
            import psycopg  # type: ignore
            self.conn = psycopg.connect(url, autocommit=True)
        except ImportError:
            try:
                import psycopg2  # type: ignore
            except ImportError:
                sys.exit("DATABASE_URL is set but neither psycopg nor psycopg2 is installed.\n"
                         "Install one (pip install psycopg), or use --outreach-log with a JSON export.")
            self.conn = psycopg2.connect(url)
            self.conn.autocommit = True

    def _rows(self, sql, params):
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def client_known(self, client):
        any_rows = bool(self._rows("SELECT 1 FROM outreach_log LIMIT 1", ()))
        mine = bool(self._rows("SELECT 1 FROM outreach_log WHERE client_name = %s LIMIT 1", (client,)))
        return any_rows, mine

    def recent(self, client, emails, days):
        if not emails:
            return set()
        return {r[0] for r in self._rows(
            "SELECT DISTINCT LOWER(email) FROM outreach_log "
            "WHERE client_name = %s AND LOWER(email) = ANY(%s) "
            "AND COALESCE(first_sent_date, loaded_date) > NOW() - make_interval(days => %s)",
            (client, list(emails), int(days)))}

    def contact_state(self, client, emails):
        """{email: (email_status, do_not_contact)}. A DNC flag on any row for the address wins."""
        state = {}
        for email, status, dnc in self._rows(
                "SELECT LOWER(email), email_status, COALESCE(do_not_contact, false) FROM contacts "
                "WHERE client_name = %s AND LOWER(email) = ANY(%s)", (client, list(emails))):
            old = state.get(email)
            state[email] = (status if not old or old[0] is None else old[0], bool(dnc) or bool(old and old[1]))
        return state

    def dnc_domains(self, client, domains):
        return {r[0] for r in self._rows(
            "SELECT LOWER(domain) FROM companies WHERE client_name = %s AND do_not_contact = true "
            "AND LOWER(domain) = ANY(%s)", (client, list(domains)))}

    def prior_outcomes(self, client, emails):
        return {r[0]: r[1] for r in self._rows(
            "SELECT LOWER(lead_email), reply_category FROM campaign_responses "
            "WHERE client_name = %s AND LOWER(lead_email) = ANY(%s) AND reply_category = ANY(%s)",
            (client, list(emails), list(PERMANENT_OUTCOMES)))}

    def write(self, rows):
        """One INSERT per row, each on its own, so one bad row costs one row."""
        written, failures = 0, []
        with self.conn.cursor() as cur:
            for r in rows:
                try:
                    cur.execute(
                        "INSERT INTO outreach_log (client_name, contact_id, email, campaign_id, campaign_name, loaded_date) "
                        "VALUES (%s, %s, %s, %s, %s, %s)",
                        (r["client_name"], r["contact_id"], r["email"], r["campaign_id"],
                         r["campaign_name"], r["loaded_date"]))
                    written += 1
                except Exception as exc:  # keep going, report every failure
                    failures.append((r["email"], str(exc)[:300]))
        return written, failures


# ---------------------------------------------------------------- gates

class Facts:
    """Everything the gates need to know about the push set, gathered once before prepare()."""

    def __init__(self):
        self.recent = set()            # emails inside the cooldown
        self.dnc_emails = set()
        self.dnc_domains = set()
        self.status = None             # {email: status} from the database, or None = read the lead file
        self.outcomes = {}             # {email: reply_category}
        self.ok_statuses = set(DEFAULT_OK_STATUSES)
        self.freemail = None           # set of domains when the personal-email rule is on
        self.template_vars = ()


def lead_hash(lead):
    """Stable hash of exactly what one recipient would be loaded with."""
    doc = dict(lead)
    doc["email"] = str(doc.get("email") or "").strip().lower()
    return hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def prepare(rows, facts, cooldown_days):
    """Returns (ready, skipped). ready = [(lead, contact_id)], skipped = [(row_no, email, reason)]."""
    ready, skipped, seen = [], [], set()
    for n, row in enumerate(rows, start=1):
        lead, contact_id = to_lead(row)
        email = (lead.get("email") or "").strip()
        key = email.lower()
        if not EMAIL_RE.match(email):
            skipped.append((n, email, "invalid_or_missing_email"))
            continue
        if key in seen:
            skipped.append((n, email, "duplicate_in_push_set"))
            continue
        seen.add(key)
        domains = domain_and_parents(domain_of(key))
        if facts.freemail is not None and domains[0] in facts.freemail:
            skipped.append((n, email, "personal_email_excluded"))
            continue
        if key in facts.dnc_emails:
            skipped.append((n, email, "dnc_contact"))
            continue
        if any(d in facts.dnc_domains for d in domains):
            skipped.append((n, email, "dnc_company_domain"))
            continue
        if facts.status is None:
            status = str(row.get("email_status") or "").strip().lower()
        elif key not in facts.status:
            skipped.append((n, email, "not_in_contacts_table"))
            continue
        else:
            status = str(facts.status[key] or "").strip().lower()
        if status not in facts.ok_statuses:
            skipped.append((n, email, "email_status_%s" % (re.sub(r"[^a-z0-9_]", "_", status) or "missing")))
            continue
        if key in facts.outcomes:
            skipped.append((n, email, "prior_reply_%s" % facts.outcomes[key]))
            continue
        if key in facts.recent:
            skipped.append((n, email, "cooldown_%dd" % cooldown_days))
            continue
        lead["email"] = email
        if facts.template_vars:
            values = dict(lead.get("custom_fields") or {})
            values.update({k: v for k, v in lead.items() if k != "custom_fields"})
            if any(not str(values.get(v) or "").strip() for v in facts.template_vars):
                skipped.append((n, email, "missing_merge_field"))
                continue
        ready.append((lead, contact_id))
    return ready, skipped


def check_approval(path, campaign, client, template_sha, ready):
    """Returns a list of problems. Empty list = the push set is the approved set (or a subset)."""
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        return ["approval file unreadable: %s" % exc]
    if not isinstance(doc, dict):
        return ["approval file is not a JSON object"]
    problems = []
    if str(doc.get("campaign_id") or "") != str(campaign):
        problems.append("approval is for campaign %r, this push is for %r" % (doc.get("campaign_id"), str(campaign)))
    if str(doc.get("client") or "") != str(client):
        problems.append("approval is for client %r, this push is for %r" % (doc.get("client"), client))
    if not str(doc.get("approved_by") or "").strip():
        problems.append("approved_by is empty: nobody has signed this approval")
    try:
        if parse_time(doc.get("approved_at")) > now_utc() + dt.timedelta(minutes=5):
            problems.append("approved_at is in the future")
    except (TypeError, ValueError):
        problems.append("approved_at is missing or not an ISO timestamp")
    if (doc.get("template_sha256") or None) != (template_sha or None):
        problems.append("the template changed since approval (or --template does not match the approval)")
    approved = set(doc.get("lead_hashes") or [])
    changed = [lead["email"] for lead, _ in ready if lead_hash(lead) not in approved]
    if changed:
        problems.append("%d lead(s) are new or edited since approval, e.g. %s" % (len(changed), ", ".join(changed[:5])))
    return problems


def request_body(batch):
    """The exact body sent to the platform. Settings are forced here and nowhere else."""
    return {"lead_list": [lead for lead, _ in batch], "settings": dict(FORCED_SETTINGS)}


# ---------------------------------------------------------------- platform

RETRY_PAUSE = 2.0


def api_get(path, api_key, params=None, timeout=30, attempts=3):
    """GET a JSON document. Returns (ok, body_or_error). Never returns or logs the URL (it holds the key)."""
    query = urllib.parse.urlencode(dict(params or {}, api_key=api_key))
    last = ""
    for attempt in range(attempts):
        try:
            req = urllib.request.Request("%s%s?%s" % (API_BASE, path, query), method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                text = resp.read().decode("utf-8", "replace")
            return True, (json.loads(text) if text.strip() else {})
        except urllib.error.HTTPError as exc:
            last = "HTTP %s" % exc.code
            if exc.code != 429 and exc.code < 500:
                return False, last
        except Exception as exc:
            last = type(exc).__name__
        if attempt < attempts - 1:
            time.sleep(RETRY_PAUSE)
    return False, "retries exhausted (%s)" % last


def campaign_mismatch(live, client, campaign_name):
    """Why the live campaign is not the one this push says it is, or None."""
    if not isinstance(live, dict) or live.get("id") is None:
        return "the platform returned no campaign for this id under this API key"
    name = str(live.get("name") or "").strip()
    if campaign_name:
        if name.lower() != campaign_name.strip().lower():
            return "live campaign is named %r, --campaign-name says %r" % (name, campaign_name)
    elif client.strip().lower() not in name.lower():
        return ("live campaign is named %r, which does not contain the client %r. "
                "Pass the exact name with --campaign-name if that is expected" % (name, client))
    return None


def live_verdict(found, target, target_client, cutoff, campaign_status):
    """Given the platform's record for one address, return a skip reason or None."""
    if not isinstance(found, dict) or not found.get("id"):
        return None  # the platform has never seen this address
    unsub = found.get("unsubscribed_client_id_map") or {}
    if found.get("is_unsubscribed") is True or (target_client is not None and unsub.get(str(target_client))):
        return "live_unsubscribed"
    for m in found.get("lead_campaign_data") or []:
        if str(m.get("campaign_id")) == str(target):
            continue
        if (None if m.get("client_id") is None else str(m.get("client_id"))) != target_client:
            continue
        sent = None
        if m.get("last_sent_at"):
            try:
                sent = parse_time(m["last_sent_at"])
            except ValueError:
                sent = None
        if sent is not None:
            if sent >= cutoff:
                return "live_sent_recently_in_campaign_%s" % m.get("campaign_id")
        elif campaign_status(m.get("campaign_id")) not in FINISHED_STATUSES:
            return "live_queued_unsent_in_campaign_%s" % m.get("campaign_id")
    return None


def live_membership(ready, campaign, live_campaign, api_key, cooldown_days, pace):
    """Ask the platform where each address already is. Returns (kept, skipped)."""
    target_client = None if live_campaign.get("client_id") is None else str(live_campaign.get("client_id"))
    cutoff = now_utc() - dt.timedelta(days=cooldown_days)
    cache = {}

    def campaign_status(cid):
        if cid not in cache:
            ok, body = api_get("/campaigns/%s" % cid, api_key)
            cache[cid] = str(body.get("status") or "UNKNOWN").upper() if ok and isinstance(body, dict) else "UNKNOWN"
        return cache[cid]

    kept, skipped = [], []
    for lead, cid in ready:
        if pace:
            time.sleep(pace)
        ok, body = api_get("/leads/", api_key, {"email": lead["email"].lower()})
        reason = live_verdict(body, campaign, target_client, cutoff, campaign_status) if ok else "live_check_failed"
        if reason:
            skipped.append((0, lead["email"], reason))
        else:
            kept.append((lead, cid))
    return kept, skipped


def post_batch(campaign, api_key, body, timeout=60):
    # Smartlead authenticates with the key in the query string. Never log or persist `url`.
    url = "%s/campaigns/%s/leads?api_key=%s" % (API_BASE, campaign, api_key)
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:  # network error: report it as a failed batch
        return 0, str(exc)


# ---------------------------------------------------------------- main

def refuse(message):
    print("PUSH-SAFE REFUSED: %s" % message, file=sys.stderr)
    return 2


def main(argv=None):
    p = argparse.ArgumentParser(description="Gated lead push for Smartlead. Dry run unless --apply.")
    p.add_argument("--campaign", required=True, help="Smartlead campaign id")
    p.add_argument("--leads", required=True, help="CSV or JSON file of leads")
    p.add_argument("--client", required=True, help="client_name in your outreach log (must match how rows were logged)")
    p.add_argument("--campaign-name", default="", help="exact live campaign name; checked against the platform and written to the log")
    p.add_argument("--outreach-log", help="JSON outreach log (file mode); appended to on --apply")
    p.add_argument("--database-url", default=os.environ.get("DATABASE_URL"),
                   help="Postgres URL (defaults to DATABASE_URL)")
    p.add_argument("--suppression", help="file of emails and domains never to contact; required in file mode")
    p.add_argument("--allow-status", action="append", default=[],
                   help="replace the allowed email statuses (repeatable). Default: %s" % ", ".join(DEFAULT_OK_STATUSES))
    p.add_argument("--exclude-personal-emails", action="store_true",
                   help="skip gmail.com-style personal mailboxes (a per-client rule)")
    p.add_argument("--freemail-domains", help="extra personal mailbox domains, one per line")
    p.add_argument("--template", help="the email template; hashed into the approval and used for the merge-field check")
    p.add_argument("--approval", help="signed approval JSON; required with --apply")
    p.add_argument("--write-approval-request", metavar="FILE",
                   help="dry run only: write the unsigned approval for the reviewer to sign")
    p.add_argument("--first-push-for-client", action="store_true",
                   help="confirm this client really has no outreach history yet")
    p.add_argument("--live-check", action="store_true", help="run the live membership check on a dry run too")
    p.add_argument("--live-pace", type=float, default=0.4, help="seconds between live lookups")
    p.add_argument("--cooldown-days", type=int, default=DEFAULT_COOLDOWN_DAYS)
    p.add_argument("--cooldown-reason", default="", help="required when --cooldown-days is below %d" % DEFAULT_COOLDOWN_DAYS)
    p.add_argument("--batch-size", type=int, default=MAX_BATCH)
    p.add_argument("--delay", type=float, default=0.5, help="seconds between batches")
    p.add_argument("--state-dir", default=".push-safe", help="per-batch state lines are written here")
    p.add_argument("--plan-out", help="write the exact request bodies to this JSON file")
    p.add_argument("--apply", action="store_true", help="actually push and log. Without it: dry run")
    args = p.parse_args(argv)

    if args.cooldown_days < 1:
        p.error("--cooldown-days must be at least 1; the cooldown gate cannot be switched off")
    if args.cooldown_days < DEFAULT_COOLDOWN_DAYS and not args.cooldown_reason.strip():
        p.error("--cooldown-days below %d needs --cooldown-reason; it is printed and saved with the run" % DEFAULT_COOLDOWN_DAYS)
    if not 1 <= args.batch_size <= MAX_BATCH:
        p.error("--batch-size must be between 1 and %d" % MAX_BATCH)
    if bool(args.outreach_log) == bool(args.database_url):
        p.error("give exactly one source: --outreach-log FILE, or DATABASE_URL / --database-url")
    if args.outreach_log and not args.suppression:
        p.error("file mode needs --suppression FILE (your do-not-contact emails and domains). "
                "An empty file is accepted, a missing one is not.")
    if args.apply and args.write_approval_request:
        p.error("--write-approval-request is for the dry run; sign the file, then pass it with --approval")
    if args.apply and not args.approval:
        p.error("--apply needs --approval FILE. Create it with a dry run and --write-approval-request.")
    api_key = os.environ.get("SMARTLEAD_API_KEY", "")
    if args.apply and not api_key:
        p.error("--apply needs SMARTLEAD_API_KEY in the environment")

    log = FileLog(args.outreach_log) if args.outreach_log else DbLog(args.database_url)
    rows = read_rows(args.leads)
    emails = {str(r.get("email") or "").strip().lower() for r in rows} - {""}

    any_rows, mine = log.client_known(args.client)
    if any_rows and not mine and not args.first_push_for_client:
        return refuse("the outreach log has history, but none for client %r. A mistyped client name "
                      "switches the cooldown off without any error. Fix --client, or pass "
                      "--first-push-for-client if this client is new." % args.client)

    facts = Facts()
    if args.allow_status:
        facts.ok_statuses = {x.strip().lower() for x in args.allow_status if x.strip()}
    facts.recent = log.recent(args.client, emails, args.cooldown_days)
    if args.suppression:
        facts.dnc_emails, facts.dnc_domains = read_suppression(args.suppression)
    if log.mode == "database":
        state = log.contact_state(args.client, emails)
        facts.status = {e: s for e, (s, _) in state.items()}
        facts.dnc_emails |= {e for e, (_, dnc) in state.items() if dnc}
        all_domains = {d for e in emails if "@" in e for d in domain_and_parents(domain_of(e))}
        facts.dnc_domains |= log.dnc_domains(args.client, all_domains)
        facts.outcomes = log.prior_outcomes(args.client, emails)
    if args.exclude_personal_emails:
        facts.freemail = set(FREEMAIL_DOMAINS)
        if args.freemail_domains:
            with open(args.freemail_domains, encoding="utf-8") as fh:
                facts.freemail |= {x.strip().lower().lstrip("@") for x in fh if x.strip() and not x.startswith("#")}
    template_sha = None
    if args.template:
        with open(args.template, encoding="utf-8") as fh:
            template_text = fh.read()
        template_sha = hashlib.sha256(template_text.encode("utf-8")).hexdigest()
        facts.template_vars = tuple(sorted(set(MERGE_VAR_RE.findall(template_text))))

    ready, skipped = prepare(rows, facts, args.cooldown_days)

    mode = "APPLY" if args.apply else "DRY RUN (nothing sent, nothing logged; add --apply)"
    print("PUSH-SAFE %s - campaign %s, client %s" % (mode, args.campaign, args.client))
    print("attempted: %d rows" % len(rows))
    print("allowed email statuses: %s" % ", ".join(sorted(facts.ok_statuses)))
    if args.cooldown_days < DEFAULT_COOLDOWN_DAYS:
        print("cooldown shortened to %d days. Reason given: %s" % (args.cooldown_days, args.cooldown_reason.strip()))

    # Campaign / client match, then live membership. Both read the platform, neither writes.
    live_campaign = None
    if api_key and (args.apply or args.live_check):
        ok, body = api_get("/campaigns/%s" % args.campaign, api_key)
        problem = campaign_mismatch(body, args.client, args.campaign_name) if ok else "could not read the campaign (%s)" % body
        if problem:
            return refuse("campaign/client match failed: %s. Nothing was pushed." % problem)
        live_campaign = body
        print("campaign match: OK (live name %r)" % str(body.get("name") or ""))
        ready, live_skipped = live_membership(ready, args.campaign, live_campaign, api_key, args.cooldown_days, args.live_pace)
        skipped.extend(live_skipped)
        print("live membership: checked %d, skipped %d" % (len(ready) + len(live_skipped), len(live_skipped)))
    else:
        print("campaign match: NOT RUN on this dry run (runs on --apply, or with --live-check and an API key)")
        print("live membership: NOT RUN on this dry run")

    if args.write_approval_request:
        with open(args.write_approval_request, "w", encoding="utf-8") as fh:
            json.dump({"campaign_id": str(args.campaign), "client": args.client, "template_sha256": template_sha,
                       "lead_count": len(ready), "lead_hashes": sorted(lead_hash(lead) for lead, _ in ready),
                       "approved_by": "", "approved_at": "",
                       "note": "The reviewer fills approved_by and approved_at (ISO time) after reading the real rendered emails."},
                      fh, ensure_ascii=False, indent=1)
        print("approval request written: %s (unsigned)" % args.write_approval_request)
    if args.approval:
        problems = check_approval(args.approval, args.campaign, args.client, template_sha, ready)
        if problems:
            return refuse("approval check failed. Nothing was pushed.\n  - " + "\n  - ".join(problems)
                          + "\nRe-run the review on the current set and get it approved again.")
        print("approval: OK (every lead to push is in the approved set)")
    else:
        print("approval: NOT CHECKED (no --approval given; --apply requires it)")

    batches = [ready[i:i + args.batch_size] for i in range(0, len(ready), args.batch_size)]
    if args.plan_out:
        with open(args.plan_out, "w", encoding="utf-8") as fh:
            json.dump([request_body(b) for b in batches], fh, ensure_ascii=False, indent=1)

    reasons = {}
    for _, _, reason in skipped:
        reasons[reason] = reasons.get(reason, 0) + 1
    print("skipped: %d" % len(skipped))
    for reason, count in sorted(reasons.items()):
        print("  %s: %d" % (reason, count))
    for n, email, reason in skipped[:20]:
        print("    %s %s (%s)" % ("row %d" % n if n else "live", email or "<empty>", reason))
    print("ready to push: %d in %d batch(es)" % (len(ready), len(batches)))
    print("settings forced on every request: %s" % json.dumps(FORCED_SETTINGS))

    if not args.apply:
        print("succeeded: 0 (dry run)\nfailed: 0 (dry run)")
        return 0

    os.makedirs(args.state_dir, exist_ok=True)
    stamp_name = "%s-%s" % (re.sub(r"[^A-Za-z0-9_-]", "_", args.campaign), now_utc().strftime("%Y%m%dT%H%M%SZ"))
    state_path = os.path.join(args.state_dir, "push-%s.jsonl" % stamp_name)
    with open(os.path.join(args.state_dir, "skipped-%s.json" % stamp_name), "w", encoding="utf-8") as fh:
        json.dump({"cooldown_days": args.cooldown_days, "cooldown_reason": args.cooldown_reason,
                   "skipped": [{"row": n, "email": e, "reason": r} for n, e, r in skipped]}, fh, ensure_ascii=False, indent=1)
    succeeded, failed, logged = 0, [], 0
    log_failures, not_accepted = [], {}
    consecutive_failures = 0

    for i, batch in enumerate(batches, start=1):
        status, text = post_batch(args.campaign, api_key, request_body(batch))
        entry = {"batch": i, "at": now_utc().isoformat(), "http_status": status,
                 "emails": [lead["email"] for lead, _ in batch], "response": text[:2000]}
        if 200 <= status < 300:
            consecutive_failures = 0
            try:
                resp = json.loads(text)
            except ValueError:
                resp = {}
            total = resp.get("total_leads") if isinstance(resp, dict) else None
            if isinstance(total, int):
                accepted = max(0, min(total, len(batch)))
            else:
                accepted = 0
                failed.append((i, "response had no total_leads - check the campaign lead count by hand"))
            succeeded += accepted
            if accepted < len(batch) and isinstance(total, int):
                failed.append((i, "%d lead(s) not accepted by the platform" % (len(batch) - accepted)))
                for k in REJECTION_KEYS:
                    if isinstance(resp.get(k), int) and resp[k]:
                        not_accepted[k] = not_accepted.get(k, 0) + resp[k]
                if isinstance(resp.get("unsubscribed_leads"), list) and resp["unsubscribed_leads"]:
                    not_accepted["unsubscribed_leads"] = not_accepted.get("unsubscribed_leads", 0) + len(resp["unsubscribed_leads"])
            # The platform received this batch. Log every lead in it now: the response does
            # not say which ones it dropped, and over-logging only delays a re-push, while
            # under-logging lets the same person be pushed twice.
            stamp = now_utc().isoformat()
            rows_to_log = [{"client_name": args.client, "contact_id": cid, "email": lead["email"],
                            "campaign_id": str(args.campaign), "campaign_name": args.campaign_name,
                            "loaded_date": stamp, "first_sent_date": None} for lead, cid in batch]
            try:
                written, fails = log.write(rows_to_log)
            except Exception as exc:
                written, fails = 0, [("<batch %d>" % i, str(exc)[:300])]
            logged += written
            log_failures.extend(fails)
            entry.update({"accepted": accepted, "total_leads": total, "logged": written, "log_failures": len(fails)})
        else:
            consecutive_failures += 1
            failed.append((i, "HTTP %s: %s" % (status, text[:300])))
            entry.update({"accepted": 0, "logged": 0})
        with open(state_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        if consecutive_failures >= 2:
            failed.append((i, "two consecutive batch failures - stopped; no further batches sent"))
            break
        if i < len(batches):
            time.sleep(args.delay)

    print("succeeded: %d (from total_leads in each response)" % succeeded)
    print("failed: %d batch issue(s)" % len(failed))
    for i, reason in failed:
        print("  batch %d: %s" % (i, reason))
    if not_accepted:
        print("  not accepted, by platform reason: %s" % json.dumps(not_accepted))
    print("outreach log rows written: %d, failed: %d" % (logged, len(log_failures)))
    for email, err in log_failures[:20]:
        print("  %s: %s" % (email, err))
    print("state: %s" % state_path)
    print("Next: read the campaign lead count back from the API and compare it to succeeded.")
    return 1 if (failed or log_failures) else 0


if __name__ == "__main__":
    sys.exit(main())
