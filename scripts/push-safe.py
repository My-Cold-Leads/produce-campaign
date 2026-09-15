#!/usr/bin/env python3
"""Push leads into a Smartlead campaign through the gates the raw endpoint skips.

Dry run is the DEFAULT. Nothing is sent and nothing is logged until you pass --apply.

What it does, in order:
  1. Reads your leads from a CSV or JSON file.
  2. Drops invalid emails and repeats of the same person (case-insensitive email).
  3. Applies the cooldown: anyone in your outreach log for this client whose
     COALESCE(first_sent_date, loaded_date) is inside the window (90 days by default)
     is skipped. A queued-but-unsent lead counts as contacted.
  4. Forces the three platform settings to false on every request, whatever the input says:
     ignore_global_block_list, ignore_unsubscribe_list, ignore_duplicate_leads_in_other_campaign.
  5. POSTs in batches of up to 1,000 and reconciles each batch against the response's
     total_leads (not upload_count).
  6. Writes one outreach log row per lead at push time, as each batch is accepted.
  7. Prints attempted / succeeded / failed / skipped with reasons, and persists a line per
     batch to a state file so a killed run can be reconstructed.

Cooldown source, pick one:
  DATABASE_URL (or --database-url)  reads and writes the outreach_log table from setup/schema.sql.
                                     Needs psycopg (3) or psycopg2 installed.
  --outreach-log FILE.json          a JSON list exported from your outreach log. The wrapper
                                     reads it for the cooldown and appends new rows to it.

Examples:
  python3 scripts/push-safe.py --campaign 1234567 --client ACME --leads leads.csv --outreach-log outreach_log.json
  SMARTLEAD_API_KEY=... DATABASE_URL=... python3 scripts/push-safe.py --campaign 1234567 --client ACME \\
      --campaign-name acme-e1 --leads leads.csv --apply

Lead file columns: email (required), first_name, last_name, company_name, phone_number, website,
location, linkedin_profile, company_url, contact_id (optional, written to the log, never sent).
Any other column becomes a custom field. In JSON, a lead may also carry a custom_fields object.
Python 3 standard library only, plus the optional database driver.
"""
import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

API_BASE = "https://server.smartlead.ai/api/v1"
MAX_BATCH = 1000
DEFAULT_COOLDOWN_DAYS = 90
FORCED_SETTINGS = {
    "ignore_global_block_list": False,
    "ignore_unsubscribe_list": False,
    "ignore_duplicate_leads_in_other_campaign": False,
}
STANDARD_FIELDS = ("email", "first_name", "last_name", "company_name", "phone_number",
                   "website", "location", "linkedin_profile", "company_url")
LOG_ONLY_FIELDS = ("contact_id",)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
REJECTION_KEYS = ("block_count", "duplicate_count", "invalid_email_count", "already_added_to_campaign",
                  "bounce_count", "lead_import_stopped_count")


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


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


# ---------------------------------------------------------------- cooldown sources

class FileLog:
    """Outreach log kept as a JSON list, for installs without direct database access."""

    def __init__(self, path):
        self.path = path
        self.rows = []
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                self.rows = json.load(fh)

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
            when = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=dt.timezone.utc)
            if when > cutoff:
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
    """The outreach_log table from setup/schema.sql."""

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

    def recent(self, client, emails, days):
        if not emails:
            return set()
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT LOWER(email) FROM outreach_log "
                "WHERE client_name = %s AND LOWER(email) = ANY(%s) "
                "AND COALESCE(first_sent_date, loaded_date) > NOW() - make_interval(days => %s)",
                (client, list(emails), int(days)))
            return {r[0] for r in cur.fetchall()}

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

def prepare(rows, recent_emails, cooldown_days):
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
        if key in recent_emails:
            skipped.append((n, email, "cooldown_%dd" % cooldown_days))
            continue
        lead["email"] = email
        ready.append((lead, contact_id))
    return ready, skipped


def request_body(batch):
    """The exact body sent to the platform. Settings are forced here and nowhere else."""
    return {"lead_list": [lead for lead, _ in batch], "settings": dict(FORCED_SETTINGS)}


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

def main(argv=None):
    p = argparse.ArgumentParser(description="Gated lead push for Smartlead. Dry run unless --apply.")
    p.add_argument("--campaign", required=True, help="Smartlead campaign id")
    p.add_argument("--leads", required=True, help="CSV or JSON file of leads")
    p.add_argument("--client", required=True, help="client_name in your outreach log (must match how rows were logged)")
    p.add_argument("--campaign-name", default="", help="written to the outreach log")
    p.add_argument("--outreach-log", help="JSON outreach log (file mode); appended to on --apply")
    p.add_argument("--database-url", default=os.environ.get("DATABASE_URL"),
                   help="Postgres URL (defaults to DATABASE_URL)")
    p.add_argument("--cooldown-days", type=int, default=DEFAULT_COOLDOWN_DAYS)
    p.add_argument("--batch-size", type=int, default=MAX_BATCH)
    p.add_argument("--delay", type=float, default=0.5, help="seconds between batches")
    p.add_argument("--state-dir", default=".push-safe", help="per-batch state lines are written here")
    p.add_argument("--plan-out", help="write the exact request bodies to this JSON file")
    p.add_argument("--apply", action="store_true", help="actually push and log. Without it: dry run")
    args = p.parse_args(argv)

    if args.cooldown_days < 1:
        p.error("--cooldown-days must be at least 1; the cooldown gate cannot be switched off")
    if not 1 <= args.batch_size <= MAX_BATCH:
        p.error("--batch-size must be between 1 and %d" % MAX_BATCH)
    if bool(args.outreach_log) == bool(args.database_url):
        p.error("give exactly one cooldown source: --outreach-log FILE, or DATABASE_URL / --database-url")
    api_key = os.environ.get("SMARTLEAD_API_KEY", "")
    if args.apply and not api_key:
        p.error("--apply needs SMARTLEAD_API_KEY in the environment")

    log = FileLog(args.outreach_log) if args.outreach_log else DbLog(args.database_url)
    rows = read_rows(args.leads)
    emails = {str(r.get("email") or "").strip().lower() for r in rows}
    recent = log.recent(args.client, emails, args.cooldown_days)
    ready, skipped = prepare(rows, recent, args.cooldown_days)
    batches = [ready[i:i + args.batch_size] for i in range(0, len(ready), args.batch_size)]

    if args.plan_out:
        with open(args.plan_out, "w", encoding="utf-8") as fh:
            json.dump([request_body(b) for b in batches], fh, ensure_ascii=False, indent=1)

    mode = "APPLY" if args.apply else "DRY RUN (nothing sent, nothing logged; add --apply)"
    print("PUSH-SAFE %s - campaign %s, client %s" % (mode, args.campaign, args.client))
    print("attempted: %d rows" % len(rows))
    reasons = {}
    for _, _, reason in skipped:
        reasons[reason] = reasons.get(reason, 0) + 1
    print("skipped: %d" % len(skipped))
    for reason, count in sorted(reasons.items()):
        print("  %s: %d" % (reason, count))
    for n, email, reason in skipped[:20]:
        print("    row %d %s (%s)" % (n, email or "<empty>", reason))
    print("ready to push: %d in %d batch(es)" % (len(ready), len(batches)))
    print("settings forced on every request: %s" % json.dumps(FORCED_SETTINGS))

    if not args.apply:
        print("succeeded: 0 (dry run)\nfailed: 0 (dry run)")
        return 0

    os.makedirs(args.state_dir, exist_ok=True)
    state_path = os.path.join(args.state_dir, "push-%s-%s.jsonl" % (
        re.sub(r"[^A-Za-z0-9_-]", "_", args.campaign), now_utc().strftime("%Y%m%dT%H%M%SZ")))
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
