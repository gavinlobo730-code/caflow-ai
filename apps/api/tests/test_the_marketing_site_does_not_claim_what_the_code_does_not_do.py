"""MARKET-AND-TRUST-06/07/08 — the marketing copy says what the code does.

Three findings, one rule: a sentence on the public site is a claim somebody can
check, and the first person to check a security or capability sentence is the
IT-minded partner of the firm deciding whether to trust the product with its
clients' books.

  06  Two-factor on EVERY sign-in; an audit log of who VIEWED; data HOSTED IN
      INDIA. The guard covers Partner and Manager (`mfa_required_roles`), only on
      the routers that carry it; the audit log records writes, not reads; the
      database is in Mumbai and the API in Singapore, with AI calls leaving India.
  07  Tally import of ledgers and journals that "post through the same ledger"
      (it writes customers and vendors only); "the ITR JSON, 24Q and 26Q ready to
      file" (keying sheets only); "they upload it to the portal" (the portal
      upload is deliberately not built); "payslips to download" (the download is
      a staff-only route); "an assistant that already knows your practice"; and
      "100% of filings reviewed by a CA" (nothing can be filed, so it is true of
      everything and says nothing).
  08  TDS returns "due the 31st of the month following the quarter end" — Q4 is
      31 May, not 30 April.

The guard is on the PYTHON side — the Schedule III caption lesson: a test in
`apps/marketing` would assert the site against a copy of itself. The marketing
app has no test runner of its own, so this is also the only place the TDS dates
can be pinned to `compliance_engine`.
"""
import re
from pathlib import Path

import pytest

from services.compliance_engine import tds_return_due_dates_for_fy

MARKETING = Path(__file__).resolve().parents[2] / "marketing"
SOURCES = sorted(p for d in ("app", "components", "lib")
                 for p in (MARKETING / d).rglob("*") if p.suffix in (".tsx", ".ts"))


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _site() -> str:
    return "\n".join(_text(p) for p in SOURCES)


def test_the_sweep_reads_the_site():
    assert len(SOURCES) > 15, "marketing sources not found — the guard would be vacuous"
    assert "Database in Mumbai" in _site(), "premise: the corrected wording is present"


# ── 06: security and hosting ─────────────────────────────────────────────────

FORBIDDEN = [
    ("two-factor on every sign-in",
     re.compile(r"every firm sign-in|MFA and role-based access on every account|2-factor authentication ·", re.I)),
    ("an audit log of who VIEWED",
     re.compile(r"who viewed|every action is captured in a full audit log|Full audit logs", re.I)),
    ("hosting 'in India' without saying which part",
     re.compile(r"(?<!database )hosted in India|infrastructure (in|hosted in) (India|the Mumbai region)", re.I)),
    ("a Tally import that writes ledgers, journals or opening balances",
     re.compile(r"Imported entries post through the same ledger|Ledgers, journals, customers, vendors, masters and opening balances", re.I)),
    ("a ready-to-file ITR JSON, 24Q or 26Q",
     re.compile(r"the ITR JSON, 24Q and 26Q", re.I)),
    ("a client portal upload",
     re.compile(r"They upload it to the portal|portal to collect documents|portal for collecting documents", re.I)),
    ("a payslip download an employee cannot do",
     re.compile(r"payslips to download", re.I)),
    ("an assistant that already knows the practice",
     re.compile(r"already knows your practice", re.I)),
    ("a tautological CA-review statistic",
     re.compile(r"Filings reviewed by a CA before submit", re.I)),
]


@pytest.mark.parametrize("name,pattern", FORBIDDEN, ids=[n for n, _ in FORBIDDEN])
def test_the_site_does_not_make_this_claim(name, pattern):
    hits = [f"{p.relative_to(MARKETING)}: {m.group(0)!r}"
            for p in SOURCES for m in pattern.finditer(_text(p))]
    assert hits == [], f"the site claims {name}:\n" + "\n".join(hits)


@pytest.mark.parametrize("name,pattern", FORBIDDEN, ids=[n for n, _ in FORBIDDEN])
def test_each_pattern_detects_what_it_claims_to(name, pattern):
    """A pattern that matches nothing would make the test above pass for ever."""
    samples = {
        "two-factor on every sign-in": "Two-factor on every firm sign-in",
        "an audit log of who VIEWED": "a complete record of who viewed, edited",
        "hosting 'in India' without saying which part": "Data hosted in India",
        "a Tally import that writes ledgers, journals or opening balances":
            "Imported entries post through the same ledger as everything else",
        "a ready-to-file ITR JSON, 24Q or 26Q": "GSTR-9, the ITR JSON, 24Q and 26Q",
        "a client portal upload": "They upload it to the portal you invited them to",
        "a payslip download an employee cannot do": "payslips to download, leave balance",
        "an assistant that already knows the practice": "An assistant that already knows your practice",
        "a tautological CA-review statistic": "Filings reviewed by a CA before submit",
    }
    assert pattern.search(samples[name]), name


def test_the_hosting_sentence_names_the_database_and_the_rest():
    site = _site()
    assert "Database in Mumbai" in site
    # The API runs in Singapore (render.yaml) and the AI calls leave India; the
    # long forms of the claim must say so, not only the footer chip.
    assert "Singapore" in site
    assert "AI provider outside India" in site or "providers outside India" in site


def test_the_render_region_the_site_names_is_the_one_render_uses():
    yaml = (Path(__file__).resolve().parents[2] / ".." / "render.yaml").resolve().read_text()
    assert re.search(r"region:\s*singapore", yaml), "the site says Singapore; render.yaml must agree"


def test_the_mfa_sentence_names_who_is_asked():
    """`mfa_required_roles` decides; the copy must name the same two roles."""
    from core.security_config import mfa_required_roles
    assert mfa_required_roles() == {"Partner", "Manager"}
    site = _site()
    assert "Partners and Managers" in site
    assert "Executives and Reviewers are not asked for it today" in site


# ── 08: the TDS return dates ─────────────────────────────────────────────────

def _expected_tds_line() -> str:
    # Any FY: the quarters' day and month do not move with the year.
    rows = tds_return_due_dates_for_fy(2027)
    return " · ".join(f"{r['quarter']} {r['due_date'].day} {r['due_date']:%b}" for r in rows)


def test_the_engine_says_q4_is_31_may():
    """The premise the copy rests on, asserted rather than remembered."""
    assert _expected_tds_line() == "Q1 31 Jul · Q2 31 Oct · Q3 31 Jan · Q4 31 May"


def test_the_resources_page_quotes_every_quarter_from_the_engine():
    page = _text(MARKETING / "app" / "(site)" / "resources" / "page.tsx")
    expected = _expected_tds_line()
    assert page.count(expected) == 2, (
        f"the calendar row and the TDS guide must both carry {expected!r}")


def test_the_resources_page_no_longer_says_the_31st_of_the_following_month():
    page = _text(MARKETING / "app" / "(site)" / "resources" / "page.tsx")
    assert "31st of the month" not in page
