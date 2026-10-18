"""A government notice a model read and nobody has checked is on the firm-wide risk register (POST-A-052).

WHAT WAS WRONG
    Notice extraction STAGES one `government_notices` row with `ca_approved = false` and, on purpose, creates no task, no timeline
    event and no alert until a CA approves it (ai-16: a model's reading may not put work in front of other people). So a
    pending notice alerted nobody: it was visible only on the one client's compliance tab with a "Pending review" mark. A
    notice has a response date. A staged one could sit unseen past it.

WHAT IS HELD
    * `notices_awaiting_review` raises a row for every staged notice still open, graded from the response date the model read:
      critical when it has passed or is within 7 days, high within 30 days, medium after that, and HIGH when no date could be
      read (an absent date is not a distant one). The grading is a practice convention and the answer carries a note saying so;
      the description says the date is a reading;
    * an approved notice, and one a CA has since answered or closed, is not a risk;
    * the service reads only unapproved, still-open notices of the caller's clients, firm-scoped, through the pager;
    * the Risks page lists the kind first and sends it to the client's compliance tab, where the Pending review mark and the
      approve button are, whatever the authority or reference says.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from domain.risk import register as rule
from services import risk_register_service as service
from tests.e2e_harness import FakeDB

AS_AT = date(2026, 10, 18)
FIRM = "firm-1"
API = Path(__file__).resolve().parents[1]
WEB = API.parent / "web"


def _notice(due="2026-11-30", **over):
    row = {"id": "n1", "client_id": "c1", "notice_type": "gst_scrutiny", "authority": "GSTN", "reference_no": "ASMT-10/2026",
           "issue_date": "2026-10-10", "response_due_date": due, "status": "open", "ca_approved": False}
    row.update(over)
    return row


def _rows(*notices):
    return rule.notices_awaiting_review(list(notices), {"c1": "Acme Ltd", "c2": "Beta LLP"}, as_at=AS_AT)


# ── the grading ─────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("due,severity", [
    ("2026-10-01", "critical"),     # passed
    ("2026-10-18", "critical"),     # today
    ("2026-10-25", "critical"),     # 7 days
    ("2026-10-26", "high"),         # 8 days
    ("2026-11-17", "high"),         # 30 days
    ("2026-11-18", "medium"),       # 31 days
    ("2027-03-31", "medium"),
])
def test_the_grade_follows_the_response_date_read(due, severity):
    [row] = _rows(_notice(due=due))
    assert row.severity == severity, (due, row.severity)


def test_a_notice_whose_date_could_not_be_read_is_high_and_says_so_not_distant():
    [row] = _rows(_notice(due=None))
    assert row.severity == "high" and row.on_date is None and row.days_overdue is None
    assert row.particulars["Response Due"] == "not read"
    assert "No response date could be read" in row.description


def test_a_passed_date_carries_the_days_overdue_and_says_how_long_ago():
    [row] = _rows(_notice(due="2026-10-10"))
    assert row.days_overdue == 8 and "passed 8 day(s) ago" in row.description


def test_the_row_says_the_date_is_a_reading_and_what_to_do():
    [row] = _rows(_notice())
    assert "no CA has checked it" in row.description and "response date read from it" in row.description
    assert "Check the details against the notice itself" in row.action and "may be wrong" in row.action
    assert row.risk_type == "Notice Awaiting Review"
    assert list(row.particulars) == ["Authority", "Reference", "Issued", "Response Due"]
    assert row.client_name == "Acme Ltd"


def test_a_missing_reference_and_issue_date_are_not_read_never_blank_values():
    [row] = _rows(_notice(reference_no=None, issue_date=None))
    assert row.particulars["Reference"] == "not read" and row.particulars["Issued"] == "not read"
    assert "(ref" not in row.description


# ── who is not a risk ───────────────────────────────────────────────────────────────────────────────

def test_an_approved_notice_is_not_a_risk():
    assert _rows(_notice(ca_approved=True)) == []


@pytest.mark.parametrize("status", ["responded", "closed"])
def test_a_notice_a_ca_has_answered_or_closed_is_not_a_risk(status):
    assert _rows(_notice(status=status)) == []


@pytest.mark.parametrize("status", ["open", "in_progress", None])
def test_a_notice_still_open_is_one(status):
    assert len(_rows(_notice(status=status))) == 1


def test_the_most_urgent_dates_come_first_and_unknown_ones_last():
    rows = _rows(_notice(id="a", due=None), _notice(id="b", due="2026-12-01"), _notice(id="c", due="2026-10-20"))
    assert [r.on_date for r in rows] == ["2026-10-20", "2026-12-01", None]


# ── the register ────────────────────────────────────────────────────────────────────────────────────

def _register(notices):
    return rule.build(
        calendar=[], clients=[{"id": "c1", "client_name": "Acme Ltd", "pan": "AABCU9603R"}],
        client_ids_with_recent_entries={"c1"}, advance_tax_installments=[], advance_tax_tracked_client_ids=set(),
        advance_tax_filed_keys=set(), dsc_rows=[], loans=[], deposits=[], notices=notices, as_at=AS_AT)


def test_the_register_carries_the_row_and_the_convention_note_only_when_there_is_one():
    with_notice = _register([_notice()])
    assert [r.risk_type for r in with_notice.rows] == ["Notice Awaiting Review"]
    assert rule.NOTICE_LADDER_NOTE in with_notice.notes
    without = _register([])
    assert without.rows == [] and rule.NOTICE_LADDER_NOTE not in without.notes


def test_a_caller_that_passes_no_notices_gets_the_register_it_always_got():
    assert rule.build(calendar=[], clients=[], client_ids_with_recent_entries=set(), advance_tax_installments=[],
                      advance_tax_tracked_client_ids=set(), advance_tax_filed_keys=set(), dsc_rows=[], loans=[],
                      deposits=[], as_at=AS_AT).rows == []


# ── the service ─────────────────────────────────────────────────────────────────────────────────────

def _seeded():
    db = FakeDB()
    db.seed("clients", {"id": "c1", "firm_id": FIRM, "client_name": "Acme Ltd", "gstin": "", "pan": "AABCU9603R"})
    db.seed("clients", {"id": "c2", "firm_id": FIRM, "client_name": "Beta LLP", "gstin": "", "pan": "AABCU9603R"})
    base = {"firm_id": FIRM, "notice_type": "income_tax", "authority": "Income Tax Dept", "reference_no": None,
            "issue_date": "2026-10-01", "response_due_date": "2026-10-30", "status": "open", "ca_approved": False}
    db.seed("government_notices", {**base, "id": "mine", "client_id": "c1"})
    db.seed("government_notices", {**base, "id": "theirs", "client_id": "c2"})
    db.seed("government_notices", {**base, "id": "approved", "client_id": "c1", "ca_approved": True})
    db.seed("government_notices", {**base, "id": "closed", "client_id": "c1", "status": "closed"})
    db.seed("government_notices", {**base, "id": "other-firm", "client_id": "c1", "firm_id": "firm-2"})
    return db


def _types(payload):
    return sorted((r["client_id"], r["risk_type"]) for r in payload["rows"] if r["risk_type"] == "Notice Awaiting Review")


def test_the_service_reads_only_unapproved_open_notices_of_this_firm():
    payload = service.build_register(_seeded(), FIRM, None)
    assert _types(payload) == [("c1", "Notice Awaiting Review"), ("c2", "Notice Awaiting Review")]


def test_an_assignment_scoped_caller_sees_only_their_clients_notices():
    payload = service.build_register(_seeded(), FIRM, {"c1"})
    assert _types(payload) == [("c1", "Notice Awaiting Review")]


def test_a_caller_with_no_clients_sees_none_and_is_told_it_is_not_a_clean_register():
    payload = service.build_register(_seeded(), FIRM, set())
    assert _types(payload) == [] and any("not the same as a clean register" in n for n in payload["notes"])


# ── the page ────────────────────────────────────────────────────────────────────────────────────────

def test_the_risks_page_lists_the_kind_first_and_sends_it_to_the_compliance_tab_before_any_substring_test():
    src = (WEB / "app/risks/page.tsx").read_text(encoding="utf-8")
    order = src[src.index("const CATEGORY_ORDER = ["):]
    assert order.index('"Notice Awaiting Review"') < order.index('"Overdue Filing"')
    href = src[src.index("function riskActionHref"):]
    assert href.index('r.risk_type === "Notice Awaiting Review"') < href.index("/GSTR/i.test(text)")
    assert "return `/clients/${r.client_id}/compliance`;" in href
