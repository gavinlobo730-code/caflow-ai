"""What counts as a CAPABILITY or SECURITY sentence on the marketing site.

This is the RULE half of the claims ledger (`_marketing_claims.py` is the data half,
`test_every_capability_sentence_on_the_marketing_site_is_in_the_claims_ledger.py`
the guard). It answers one question — "is this sentence promising something about
what the product does, how it protects data, or what the vendor will do?" — and the
answer is a vocabulary rather than a list of sentences, so a sentence nobody has
written yet is caught the day it is written (market_and_trust-09).

TWO TIERS, because a label and a claim are not the same thing.

  STRONG terms are a promise in any length of string. "Single sign-on (SSO)" and
  "SLA & account manager" are two- and three-word plan bullets and they are exactly
  where the unbuilt capabilities lived, so a strong term counts in a bullet.

  WEAK terms are ordinary product vocabulary — import, upload, portal, e-invoice —
  and a two-word label ("Client portal", "Export data") is a name, not a statement.
  They count only in a sentence of four or more words, where something is being
  said ABOUT the thing.

WHAT IS DELIBERATELY NOT HERE. Positioning ("AI-first", "replaces Tally, ClearTax,
Winman and WhatsApp"), due dates in a reference table (pinned to `compliance_engine`
by `test_the_marketing_site_does_not_claim_what_the_code_does_not_do.py`) and the
sample data inside the rendered product screens under `components/home/screens/`
(see `EXEMPT_PREFIXES`). The vocabulary is a visible, extendable list: adding a term
makes every sentence it newly reaches demand a ledger entry, which is the point.
"""
from __future__ import annotations

import re

# A rendered picture of the product's own screens: its text is sample data and UI
# labels ("146 transactions imported from HDFC Bank"), not a statement the site makes.
# What the page around it SAYS is where a claim is made. The filing and
# social-proof patterns in `test_the_marketing_site_does_not_claim_what_the_code_does_not_do.py`
# and `test_the_marketing_site_says_what_the_product_does.py` still read these files.
EXEMPT_PREFIXES: tuple[tuple[str, str], ...] = (
    ("components/home/screens/",
     "rendered product screens: sample data and UI labels, not statements the site makes"),
)

WEAK_MIN_WORDS = 4

_STRONG_SOURCE = {
    # who can get in, and how
    "access": r"""two-?factor|2-factor|\b2fa\b|\bmfa\b|\btotp\b|multi-?factor|\bsso\b|single\ sign-?on
                 |\bsaml\b|\boidc\b|role-based|row-level|access\ is\ (by|controlled)|by\ role\ and
                 |separate\ principals|secure\ (login|portal)|\bauthenticat""",
    # where the data is and what is done to it
    "data": r"""encrypt|\bmumbai\b|singapore|outside\ india|\bin\ india\b|in\ the\ country|stays\ in
               |data\ residency|\bhosted\b|\bhosting\b|\bdpdp\b|\bgdpr\b|retention|backups?\b
               |disaster\ recovery|sensitive\ data""",
    # what is kept, and whether it can be changed
    "audit": r"""audit[\ -](log|trail)|append-only|never\ (be\ )?(deleted|edited)|edited\ in\ place
                |everything\ is\ logged|who\ viewed|edit\ log|immutable|tamper""",
    # what the vendor promises to do, and certificates it holds
    "assurance": r"""\bsla\b|uptime|soc\ ?2|iso\ ?27001|certified|penetration\ test|\bvapt\b|bank-grade
                    |military-grade|priority\ support|account\ manager|24\ ?/\ ?7|guarantee|dedicated
                    |(email|phone|chat)\ support|support\ (team|line|hours)|real\ support""",
    # whether the software puts anything in front of a government portal
    "filing": r"""e-?fil(e|ing)|files?\ (it|returns?|for\ you)\b|files?\ (your|the|all)\ .{0,40}\breturns?\b
                 |transmit|auto-?(submit|file|post)
                 |ready\ to\ (file|submit)|file-ready|never\ acts|nothing\ filed|never\ files|sign\ every
                 |upload\ and\ sign|files?\ it\ on""",
    # where a model sits in the answer
    "ai": r"""\bai\ key|server-side|model\ call|vision\ model|text\ model|ai\ features|never\ files|proposes""",
    # what it connects to
    "integration": r"""integrates?\ with|integration\ with|connects?\ (to|with)|syncs?\ (with|live)
                      |webhooks?|public\ api|api\ access|zapier|razorpay
                      |whatsapp\ (reminders?|messages?|notifications?|integration)""",
}

_WEAK_SOURCE = {
    "import_export": r"""\bimport(s|ed)?\b|\bexport(s|ed)?\b|migrat\w*\ (from|your|my|existing)|data\ migration
                        |\bupload|\bdownload|\bxlsx\b|\bxml\b|\bbulk\b""",
    "statutory_output": r"""e-?invoice|e-?way|\birn\b|xbrl|\bfvu\b|schemas|computes?\ the\ return
                           |computed\ from\ (the|your|those)\ (books|ledgers)|2b\ reconciliation
                           |quarterly\ 2[467]q""",
    "portal": r"""client\ portal|employee\ portal|\bportal\b""",
    "money": r"""integer\ paise|floating\ point|by\ construction""",
}


def _compile(source: dict[str, str]) -> dict[str, re.Pattern[str]]:
    return {k: re.compile(v, re.I | re.X) for k, v in source.items()}


STRONG = _compile(_STRONG_SOURCE)
WEAK = _compile(_WEAK_SOURCE)
TOPICS = tuple(sorted(set(STRONG) | set(WEAK)))


def topics_of(sentence: str) -> tuple[str, ...]:
    """The topics a sentence speaks to; empty means it is not a capability claim.

    A QUESTION asserts nothing ("Does PracticeSync file returns for me?") — the answer
    underneath it is the sentence a visitor holds the product to, and it is read on its
    own."""
    if sentence.rstrip().endswith("?"):
        return ()
    found =[name for name, rx in STRONG.items() if rx.search(sentence)]
    if len(sentence.split()) >= WEAK_MIN_WORDS:
        found += [name for name, rx in WEAK.items() if rx.search(sentence)]
    return tuple(sorted(set(found)))


def is_exempt(rel_path: str) -> bool:
    return any(rel_path.startswith(prefix) for prefix, _ in EXEMPT_PREFIXES)
