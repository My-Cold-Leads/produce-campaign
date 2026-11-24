import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import hookinput as H  # noqa: E402

MARKER = "CUSTOM_FIELD_OK:"
LOG = H.log_path("custom-field-bypass.log")

SPINTAX = re.compile(r"\{[^{}|]{1,80}\|[^{}]{1,200}\}")
PLATFORM_VAR = re.compile(r"%(signature|email|first_name|last_name|company_name)%", re.I)
FIELD_KEY = re.compile(r"custom_fields?\s*[\"\']?\s*[:=]\s*\{", re.I)


def field_blocks(text):
    """Yield each custom_fields value block, brace-balanced.

    A naive non-greedy regex stops at the FIRST closing brace, which is the
    spintax's own - so the very thing the gate exists to catch fell outside the
    extracted block and the gate silently passed. Found by the falsifiability
    harness; walk the braces instead.
    """
    for m in FIELD_KEY.finditer(text):
        i = text.index("{", m.start())
        depth = 0
        for k in range(i, min(len(text), i + 8000)):
            if text[k] == "{":
                depth += 1
            elif text[k] == "}":
                depth -= 1
                if depth == 0:
                    yield text[i + 1:k]
                    break


VAR_IN_SPINTAX = re.compile(r"\{[^{}]*\{\{[^}]+\}\}[^{}]*\|")


def main():
    payload = H.load()
    # Documentation explains these mistakes by showing them. A Write or Edit of a
    # markdown file is prose, not a payload, so it is never inspected. Commands
    # and code files still are.
    if H.file_path(payload).lower().endswith((".md", ".markdown", ".mdx")):
        H.allow()
    hay = H.haystack(payload)
    if not hay.strip():
        H.allow()

    findings = []

    m = VAR_IN_SPINTAX.search(hay)
    if m:
        findings.append(
            "  A {{variable}} is nested INSIDE spintax braces: " + m.group(0)[:70] + "\n"
            "  Most sending platforms process spintax and variables in separate passes,\n"
            "  so the nested one never resolves. Keep the variable outside:\n"
            "      {Hello|Hi} {{first_name}}   not   {Hello {{first_name}}|Hi {{first_name}}}"
        )

    for block in field_blocks(hay):
        s = SPINTAX.search(block)
        if s:
            findings.append(
                "  Spintax inside a custom field value: " + s.group(0)[:70] + "\n"
                "  Custom fields are plain data - substituted, not parsed. This ships to\n"
                "  the recipient with the braces and the pipe visible."
            )
        v = PLATFORM_VAR.search(block)
        if v:
            findings.append(
                "  Platform variable inside a custom field value: " + v.group(0) + "\n"
                "  It will not expand. Put it in the sequence template instead."
            )

    if not findings:
        H.allow()

    if H.bypass(payload, MARKER, LOG):
        H.allow()

    H.block(
        "BLOCKED: sending-platform syntax inside custom field values.\n\n"
        + "\n\n".join(findings[:4])
        + "\n\nThe split is: custom fields hold pre-computed plain text. Everything the\n"
        "platform has to interpret - spintax, signature tokens, greeting rotation -\n"
        "belongs in the sequence template.\n\n"
        "A human operator can authorise a one-off; see README, 'Bypass markers'."
    )


main()
