"""Three product rules that were prose, as tests (Track F, phase F6).

WHAT THEY PROTECT

This product PREPARES statutory returns and a human files them. That is not a
limitation being worked around — it is the only honest position available,
because there is no EPFO, ESIC, MCA or state professional-tax API a CA firm can
hold (docs/compliance/08-government-api-access-the-verified-position.md). A
product that appeared to file for you could only be doing it by logging in as
you, which breaches every portal's terms and is exactly what RBI moved bank data
onto the Account Aggregator framework to end.

So three things must never become true, and each is the kind of reasonable
feature request that arrives on a busy afternoon:

  1. No field anywhere collects a government-portal password, PIN or OTP.
  2. No column anywhere stores a portal credential or token.
  3. Nothing transmits to a government host.

Rule 1 is enforced on the other side, tree-wide, by
apps/web/scripts/no-screen-takes-a-portal-credential.test.ts. Rules 2 and 3 are
here.

RULES 2 AND 3 ARE BOTH TRUE TODAY, AND THAT IS THE POINT. Neither test fixes
anything. What they do is make the day somebody adds the first one a deliberate
decision with a review attached, rather than a line in a large diff that nobody
reads as a policy change — which is how this class of thing actually gets in.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

API = pathlib.Path(__file__).resolve().parents[1]
MIGRATIONS = API / "migrations"

# ── Rule 2: no column stores a portal credential ────────────────────────────
#
# Matched on a column name's SEGMENTS, not on its letters. "pincode",
# "mapping", "shipping_bill_no" and "is_pinned" all contain "pin", and a guard
# that fires on those is one somebody silences rather than reads.
CREDENTIAL_WORDS = frozenset({
    "password", "passwd", "passcode", "secret", "credential", "otp", "pin",
    "token", "apikey", "authkey",
})

#: Columns that MATCH the vocabulary and are not portal credentials, each with
#: the reason. An entry here is a claim somebody made on purpose.
NOT_A_PORTAL_CREDENTIAL: dict[str, str] = {
    "lock_pin":
        "the FIRM's own PIN, which authorises locking a financial year. It "
        "authenticates a partner to PracticeSync; no government portal has "
        "ever seen it",
    "token_no":
        "dsc_records — the SERIAL NUMBER printed on the USB crypto token the "
        "certificate lives on. An inventory label for a physical object, not a "
        "secret: knowing it lets nobody sign anything",
    "token":
        "pending_invites — a single-use invite this product mints for its own "
        "sign-up flow",
    "invite_token":
        "the same, for a firm user invite",
    "portal_invite_token_hash":
        "the employee PORTAL — PracticeSync's own portal, not a government "
        "one — and a HASH rather than the token, which is returned once and "
        "never stored",
    "sign_token":
        "the engagement-letter signing link this product mints and sends. The "
        "shape routers/engagement_sign_public.py is built on",
    "tokens_used":
        "an AI usage COUNT (an integer), on the copilot's own log",
    "token_estimate":
        "the same, estimated before a call",
}


def _segments(name: str) -> set[str]:
    """A column name's words, singularised, for matching against a vocabulary."""
    return {s[:-1] if s.endswith("s") and len(s) > 3 else s
            for s in name.lower().split("_")}


def _credentialish_columns() -> dict[str, set[str]]:
    column = re.compile(
        r"^\s*(?!--)([a-z_]+)\s+"
        r"(text|varchar|char|uuid|bytea|jsonb|boolean|int|bigint|date|timestamptz|numeric)",
        re.I)
    added = re.compile(r"ADD COLUMN(?:\s+IF NOT EXISTS)?\s+([a-z_]+)\b", re.I)

    found: dict[str, set[str]] = {}
    for path in sorted(MIGRATIONS.glob("*.sql")):
        for line in path.read_text(errors="ignore").splitlines():
            names = []
            m = column.match(line)
            if m:
                names.append(m.group(1))
            names += [a.group(1) for a in added.finditer(line)]
            for name in names:
                if _segments(name) & CREDENTIAL_WORDS:
                    found.setdefault(name.lower(), set()).add(path.name)
    return found


def test_the_column_scan_still_finds_things():
    """A scan that stops matching keeps passing while checking nothing."""
    found = _credentialish_columns()
    assert len(found) >= 5, (
        f"only {sorted(found)} matched — the migration parser has probably "
        "stopped reading column definitions")


def test_no_column_stores_a_government_portal_credential():
    undeclared = sorted(set(_credentialish_columns()) - set(NOT_A_PORTAL_CREDENTIAL))
    assert not undeclared, (
        f"new credential-shaped column(s): {undeclared}. This product never "
        f"holds a portal credential — it cannot sign in to a portal on "
        f"anybody's behalf and must not be able to. If the column is OURS "
        f"(our own invite, our own PIN), add it to NOT_A_PORTAL_CREDENTIAL "
        f"with the reason.")


def test_every_exemption_names_a_real_column_and_says_why():
    """An exemption that outlives its column is how a guard rots."""
    live = _credentialish_columns()
    for name, reason in NOT_A_PORTAL_CREDENTIAL.items():
        assert len(reason.strip()) > 25, f"{name} has no real reason"
        assert name in live, (
            f"{name} is exempted and no migration defines it — delete the entry")


def test_the_segment_rule_does_not_fire_on_ordinary_words():
    """pincode, mapping, is_pinned and shipping_bill_no all contain "pin". A
    guard that fires on those is one somebody silences rather than reads."""
    for benign in ("pincode", "mapping", "is_pinned", "shipping_bill_no",
                   "cpin", "schedule_iii_mapping", "shipping_bill_date"):
        assert not (_segments(benign) & CREDENTIAL_WORDS), benign


def test_the_segment_rule_does_fire_on_the_real_shapes():
    for real in ("portal_password", "gst_otp", "evc_pin", "api_secret",
                 "dsc_credential", "gstn_token", "apikey"):
        assert _segments(real) & CREDENTIAL_WORDS, real


# ── Rule 3: nothing transmits to a government host ──────────────────────────
#
# THE FIRST SHAPE OF THIS TEST WAS WRONG, and how is worth keeping.
#
# It began as "no backend file may name a government host", and 23 files failed
# it — every module whose docstring says the ECR is uploaded at
# unifiedportal-emp.epfindia.gov.in, or that the contribution file goes to
# esic.gov.in. Those are the RIGHT thing to write: the whole product is built
# on telling a CA exactly where to go. A guard that fires on them is one
# somebody silences, and an exemption list with 23 entries of "this is a
# comment" is not a policy, it is paperwork.
#
# Naming a portal is not the risk. TRANSMITTING to one is. So the rule is
# stated over the thing that can actually transmit: the modules that can make
# an outbound request at all. There are four, the list is stable, and "a new
# module imports an HTTP client" is exactly the moment the question is worth
# asking.

GOVERNMENT_HOSTS = (
    "gov.in", "nic.in", "gstn.org.in", "epfindia", "esic.in", "tdscpc",
    "incometax.gov.in", "einvoice1", "ewaybillgst",
)

#: Anything that can put bytes on the wire — raw clients AND the vendor SDKs
#: that wrap one. google.genai is imported lazily inside a function and would
#: be invisible to a scan that only read the top of a file.
OUTBOUND_IMPORTS = (
    "httpx", "requests", "aiohttp", "urllib.request", "http.client",
    "websockets", "google.genai", "google.generativeai", "openai", "groq",
    "boto3", "paramiko", "smtplib", "ftplib",
)

#: Every backend module that can make an outbound request, and where to.
#: An entry is a claim somebody made on purpose; the destinations are what the
#: next test checks against the government-host list.
OUTBOUND_MODULES: dict[str, str] = {
    # ── the AI providers, both backend-only (CLAUDE.md) ──────────────────────
    "routers/ai_copilot.py":
        "Groq, for the copilot's chat completions (api.groq.com)",
    "routers/assistant.py":
        "Groq, the same endpoint, for the assistant",
    "domain/ai_copilot_service.py":
        "Groq, the same endpoint, from the copilot's domain layer",
    "domain/financial_analysis_service.py":
        "Groq, the same endpoint, for the narrative analysis",
    "routers/document_intelligence_v1.py":
        "Gemini via google.genai, for IMAGE invoice extraction only — "
        "photographed and scanned bills. See CLAUDE.md on why two providers",
    "routers/document_intelligence_v2.py":
        "Groq via its own SDK, for the PDF/text invoice extraction path",
    "services/statement_vision.py":
        "Gemini via google.genai, for reading a scanned bank statement",
    # ── the firm's own operations ────────────────────────────────────────────
    "services/email_service.py":
        "Resend (api.resend.com), for the mail this product sends on the "
        "firm's behalf",
    "services/payments/razorpay.py":
        "Razorpay, for the firm's own fee collection from its clients",
    "scripts/smoke_api.py":
        "this product's OWN deployed API, over its public URL. A smoke test, "
        "and not part of the running service",
    # ── the one open destination, and it is worth knowing about ──────────────
    "services/invoice_pdf_service.py":
        "whatever URL the FIRM gave as its branding logo, fetched to embed on "
        "an invoice PDF. The only destination here that is not fixed in code — "
        "it is a firm-supplied URL, bounded by a timeout and a byte cap, and a "
        "firm that pointed it at a portal would be fetching an image, not "
        "filing anything",
}

_SKIP_DIRS = {"tests", "__pycache__", ".venv", "venv", "node_modules"}


def _python_files():
    for path in sorted(API.rglob("*.py")):
        rel = path.relative_to(API)
        if _SKIP_DIRS & set(rel.parts):
            continue
        yield rel, path.read_text(errors="ignore")


def _mentions_a_government_host(text: str) -> bool:
    return any(h in text.lower() for h in GOVERNMENT_HOSTS)


def _imports_an_http_client(text: str) -> bool:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            names = [base] + [f"{base}.{a.name}" for a in node.names]
        else:
            continue
        for name in names:
            if any(name == c or name.startswith(c + ".") for c in OUTBOUND_IMPORTS):
                return True
    return False


def test_the_outbound_scan_still_finds_things():
    """A scan that stops matching keeps passing while checking nothing."""
    found = [str(r) for r, t in _python_files() if _imports_an_http_client(t)]
    assert len(found) >= 4, (
        f"only {found} can reach the network — the import scan has probably "
        "stopped working, not the product stopped calling Groq")


def test_every_module_that_can_reach_the_network_is_declared():
    undeclared = sorted(str(rel) for rel, text in _python_files()
                        if _imports_an_http_client(text)
                        and str(rel) not in OUTBOUND_MODULES)
    assert not undeclared, (
        f"{undeclared} can now make an outbound request and says nothing about "
        f"where to. There is no EPFO, ESIC, MCA or state portal API a CA firm "
        f"can hold, so a call to one could only be signing in as the taxpayer. "
        f"Declare it in OUTBOUND_MODULES with its destination — that entry is "
        f"the review this test exists to force.")


def test_no_declared_destination_is_a_government_host():
    """The rule itself, read off the declarations. Groq, Gemini, Razorpay and
    our own API — and nothing with a portal on the other end."""
    offenders = sorted(path for path, where in OUTBOUND_MODULES.items()
                       if _mentions_a_government_host(where))
    assert not offenders, (
        f"{offenders} declares a government destination. This product prepares "
        f"and a human files; that is the only honest position available.")


def test_every_declared_module_still_exists_and_still_reaches_the_network():
    """A declaration that outlives its module is how a guard rots."""
    by_path = {str(rel): text for rel, text in _python_files()}
    for path, where in OUTBOUND_MODULES.items():
        assert len(where.strip()) > 20, f"{path} does not say where to"
        assert path in by_path, f"{path} is declared and does not exist"
        assert _imports_an_http_client(by_path[path]), (
            f"{path} no longer reaches the network — delete the entry")


def test_naming_a_portal_in_prose_is_allowed_and_common():
    """The property the first draft of this file got wrong, pinned so it is not
    re-broken: the product tells a CA exactly which portal to go to, in
    docstrings and in the handoff screen's own text. That is the product
    working, not a leak."""
    naming = [str(rel) for rel, text in _python_files()
              if _mentions_a_government_host(text)]
    assert len(naming) > 10, (
        "hardly any module names a portal — either the scan broke or the "
        "product stopped telling CAs where to file")
    assert not (set(naming) & set(OUTBOUND_MODULES)), (
        "a module that can reach the network also names a government host. "
        "That is the combination this whole rule is about — check it.")


HTTP_CALLERS = frozenset({"httpx", "requests", "aiohttp", "urllib"})


def test_no_http_call_anywhere_targets_a_government_host():
    """The direct form, caught directly rather than inferred from a file list.

    Reads the URL argument of every call on an HTTP client. A URL assembled
    from variables is invisible here — which is what the module declarations
    above are for, and why the two are separate tests rather than one.
    """
    offenders: list[str] = []
    for rel, text in _python_files():
        if not any(c in text for c in HTTP_CALLERS):
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for arg in list(node.args) + [k.value for k in node.keywords]:
                if (isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                        and _mentions_a_government_host(arg.value)):
                    offenders.append(f"{rel}:{node.lineno} -> {arg.value}")
    assert not offenders, (
        f"an HTTP call targets a government host: {offenders}")


@pytest.mark.parametrize("host", GOVERNMENT_HOSTS)
def test_the_host_list_is_matched_case_insensitively(host):
    assert _mentions_a_government_host(f"HTTPS://WWW.{host.upper()}/x")
