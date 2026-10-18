"""The related-party loans screen counts Section 185 loans from the server's report and makes no transfer-pricing claim.

WHAT WAS WRONG (POST-A-156, and a statutory claim found while closing it)
    `app/relationships/intelligence/page.tsx` filtered `section_185_flagged` itself while `GET
    /api/relationships/loans/section-185-report` had no caller. It also counted every "inter-company" loan of Rs 1 crore or
    more and printed "IT Act Sec 92: international related party transactions above Rs 1 crore require transfer pricing
    documentation", with a "TP Risk" badge on each. That asserts a legal consequence about a fact the loan record does not hold
    (whether the other party is a non-resident associated enterprise, so whether the transaction is an international one at
    all) on a threshold nobody had confirmed from the primary text. The standing rule is that a statutory figure is not built on
    until it has been read from the Act or the Rules, and that an unknown is never shown as a value.

THE SAME CLAIM LIVED IN THE AS 18 NOTE
    `domain/related_party/disclosure.py` held `TRANSFER_PRICING_THRESHOLD_PAISE` ("an international transaction ... above this
    value") and `services/related_party_service._transfer_pricing` queried every "inter_company" loan at or above it, so the
    client's relationships page showed "N inter-company loan(s) above the s.92 threshold". A loan row records no residence at
    all, so it was the same unknown shown as a value. It is gone from the note too, and the note says it does not assess it.

WHAT IS HELD (a source scan of the screen, so it runs without a browser)
    * the screen calls the server's section-185 report and does not filter the flag itself;
    * a failed report is said on the screen, never shown as "no loan is flagged";
    * the transfer-pricing banner, the badge and the Rs 1 crore constant are gone, and so is any "transfer pricing" wording;
    * the report route is no longer on the frozen list of computed answers nobody can open.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from domain.related_party import disclosure as d
from services.related_party_service import as_payload

API = Path(__file__).resolve().parents[1]
WEB = Path(__file__).resolve().parents[3] / "apps" / "web"
PAGE = WEB / "app" / "relationships" / "intelligence" / "page.tsx"
FROZEN = Path(__file__).resolve().parent / "test_a_computed_answer_nobody_can_open_is_named.py"

pytestmark = pytest.mark.skipif(not PAGE.is_file(), reason="frontend not in this checkout")


def _code() -> str:
    src = PAGE.read_text(encoding="utf-8")
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


def test_the_count_comes_from_the_servers_report_and_is_not_filtered_here():
    code = _code()
    assert "/api/relationships/loans/section-185-report" in code
    assert not re.search(r"\.filter\(\s*\(?\s*\w+\s*\)?\s*=>\s*\w+\.section_185_flagged", code), \
        "the screen filters section_185_flagged itself again"


def test_a_report_that_could_not_be_read_is_said_and_is_not_shown_as_none_flagged():
    code = _code()
    assert 'setSec185("error")' in code
    assert "could not be read" in code
    # the alert needs a count that was actually read: an unread report never draws "0 loans" or an alert
    assert re.search(r"sec185Count\s*!==\s*null\s*&&\s*sec185Count\s*>\s*0", code)


def test_the_screen_makes_no_transfer_pricing_claim():
    code = _code()
    assert "10_000_000_00" not in code
    assert "TP Risk" not in code
    assert not re.search(r"transfer\s*pricing", code, re.I), "a transfer-pricing statement is back on the screen"


def test_the_report_route_has_a_caller_now_and_left_the_frozen_list():
    assert "/api/relationships/loans/section-185-report" not in FROZEN.read_text(encoding="utf-8")


# ── the same claim in the AS 18 note ─────────────────────────────────────────

NOTE_FILES = (
    API / "domain" / "related_party" / "disclosure.py",
    API / "services" / "related_party_service.py",
    API / "routers" / "relationships.py",
)
NOTE_PAGE = WEB / "app" / "clients" / "[id]" / "relationships" / "page.tsx"
NOTE_TYPE = WEB / "lib" / "api" / "index.ts"


def _without_comments(path: Path) -> str:
    src = path.read_text(encoding="utf-8")
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    src = re.sub(r"^\s*(//|#).*$", "", src, flags=re.M)
    return src


@pytest.mark.parametrize("path", NOTE_FILES, ids=lambda p: p.name)
def test_the_note_builds_no_transfer_pricing_flag(path):
    code = _without_comments(path)
    assert "TRANSFER_PRICING_THRESHOLD" not in code
    assert "transfer_pricing" not in code


def test_the_served_note_has_no_transfer_pricing_key_and_says_it_is_not_assessed():
    note = d.build(client_id="c1", parties=[], section_185_loans=[], entity_relationships=[])
    payload = as_payload(note)
    assert not [k for k in payload if "transfer" in k]
    assert not hasattr(d, "TRANSFER_PRICING_THRESHOLD_PAISE")
    assert any("Transfer pricing is not assessed" in g for g in payload["gaps"])


@pytest.mark.skipif(not NOTE_PAGE.is_file(), reason="frontend not in this checkout")
def test_the_relationships_page_and_the_api_type_carry_no_transfer_pricing():
    for path in (NOTE_PAGE, NOTE_TYPE):
        code = _without_comments(path)
        assert "transfer_pricing_flags" not in code, path.name
        assert "transfer_pricing_count" not in code, path.name
        assert "s.92 threshold" not in code, path.name
