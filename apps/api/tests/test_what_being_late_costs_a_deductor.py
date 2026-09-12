"""
IT Act §201(1A) interest and the §234E fee, and the worksheet that uses them.

TDS-08 — nothing in the product computed either. §201(1A) appeared in a dozen
comments and no function; §234E existed only inside the filing walk-through,
which transmits nothing. A CA worked both out on paper.

TDS-30 — every deduction was already a row in `tds_deductions` and nothing
added them up, so on the 5th of the month the CA exported to Excel to find out
what to pay by the 7th. And the challan they then recorded booked ONE typed
number as pure tax, leaving migration 037's `interest_paise`, `penalty_paise`
and `surcharge_paise` untouched and `minor_head` unsettable.

The arithmetic assertions here are the worked examples a CA would check by
hand, not round numbers chosen to make the code pass.
"""
from __future__ import annotations

import inspect
import io
import re
import tokenize
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from domain.tds import deposit_due, interest

pytestmark = pytest.mark.usefixtures("dev_header_auth")

_HEADERS = {"X-User-Email": "partner@test.com", "X-User-Role": "partner",
            "X-Firm-ID": "firm-1"}
_CLIENT_ID = "client-123"


def _code_only(path: Path) -> str:
    """The file with comments and string literals removed.

    Both guards below scan for a SPELLING, and this file's own explanations
    quote the very spellings they forbid — so a raw text scan fails on the
    comment that says why the code is right. Tokenising drops comments and
    docstrings and leaves the code, which is what the rules are about.
    """
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(path.read_text()).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        out.append(tok.string)
    return " ".join(out)


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_mock_stores():
    from routers.tds_workspace import _MOCK_CHALLANS, _MOCK_DEDUCTIONS
    _MOCK_CHALLANS.clear()
    _MOCK_DEDUCTIONS.clear()
    yield


# ── The month convention, which is the whole reason this module exists ───────

def test_a_part_month_counts_as_a_whole_one():
    """§201(1A) charges "for every month or part of a month"."""
    assert interest.months_or_part(date(2025, 6, 15), date(2025, 6, 16)) == 1


def test_one_day_across_a_month_boundary_is_two_months():
    """The §201(1A) surprise, and the reason this does not reuse the §234A
    helper: an anniversary count would call 30 June → 1 July one month."""
    assert interest.months_or_part(date(2025, 6, 30), date(2025, 7, 1)) == 2


def test_the_advance_tax_helper_would_have_given_a_different_answer():
    """Negative control on the choice itself. If someone 'simplifies' this by
    delegating to advance_tax_interest_engine._months_or_part, this fails."""
    from domain.income_tax.advance_tax_interest_engine import _months_or_part
    anniversary = _months_or_part(date(2025, 6, 30), date(2025, 7, 1))
    calendar = interest.months_or_part(date(2025, 6, 30), date(2025, 7, 1))
    assert anniversary == 1 and calendar == 2, (
        "the two conventions must stay distinct — §234A counts a PERIOD, "
        "§201(1A) counts calendar months")


def test_the_calendar_count_is_never_smaller_than_the_anniversary_one():
    """The error direction is deliberate: a figure computed this way cannot
    tell a deductor they owe LESS interest than they do."""
    from domain.income_tax.advance_tax_interest_engine import _months_or_part
    start = date(2024, 1, 1)
    for offset in range(0, 800, 7):
        end = date.fromordinal(start.toordinal() + offset)
        assert interest.months_or_part(start, end) >= _months_or_part(start, end)


def test_a_clock_that_has_not_started_does_not_run_backwards():
    assert interest.months_or_part(date(2025, 7, 1), date(2025, 6, 30)) == 0


# ── §201(1A)(ii): deducted and paid over late ────────────────────────────────

def test_the_findings_own_worked_example():
    """₹80,000 deducted in June, deposited 20 August — June, July and August
    are three part-months at 1.5%, so ₹3,600."""
    r = interest.interest_on_late_deposit(
        tax_paise=80000_00, deducted_on=date(2025, 6, 15),
        due_date=date(2025, 7, 7), deposited_on=date(2025, 8, 20))
    assert r.applies
    assert r.months == 3
    assert r.interest_paise == 3600_00


def test_the_clock_starts_at_the_deduction_not_the_due_date():
    """One day late costs 3%, because June and July are both part-months of
    the period running from the DATE OF DEDUCTION."""
    r = interest.interest_on_late_deposit(
        tax_paise=100000_00, deducted_on=date(2025, 6, 25),
        due_date=date(2025, 7, 7), deposited_on=date(2025, 7, 8))
    assert r.months == 2
    assert r.interest_paise == 3000_00
    # If the clock started at the due date it would be one month, ₹1,500.
    assert r.interest_paise != 1500_00


def test_a_deposit_on_the_due_date_is_not_a_default():
    r = interest.interest_on_late_deposit(
        tax_paise=100000_00, deducted_on=date(2025, 6, 1),
        due_date=date(2025, 7, 7), deposited_on=date(2025, 7, 7))
    assert not r.applies and r.interest_paise == 0
    assert "on or before" in r.reason


def test_march_takes_the_thirtieth_of_april_from_the_one_authority():
    """Rule 30(2)'s March exception is not restated in this module."""
    from services.compliance_engine import tds_deposit_due_date
    due = tds_deposit_due_date(2026, 3)
    assert due == date(2026, 4, 30)
    r = interest.interest_on_late_deposit(
        tax_paise=50000_00, deducted_on=date(2026, 3, 20),
        due_date=due, deposited_on=date(2026, 4, 25))
    assert not r.applies, "25 April is inside the March window, not late"


def test_unpaid_tax_keeps_running_to_the_as_at_date():
    r = interest.interest_on_late_deposit(
        tax_paise=10000_00, deducted_on=date(2025, 6, 4),
        due_date=date(2025, 7, 7), deposited_on=None, as_at=date(2025, 9, 12))
    assert r.applies
    assert r.months == 4          # June, July, August, September
    assert r.interest_paise == 600_00


def test_an_unpaid_deduction_with_no_as_at_date_is_refused_not_guessed():
    r = interest.interest_on_late_deposit(
        tax_paise=10000_00, deducted_on=date(2025, 6, 4),
        due_date=date(2025, 7, 7), deposited_on=None)
    assert not r.applies and r.interest_paise == 0
    assert "no date was given" in r.reason


# ── §201(1A)(i): deducted late ───────────────────────────────────────────────

def test_late_deduction_runs_at_one_percent_not_one_and_a_half():
    r = interest.interest_on_late_deduction(
        tax_paise=100000_00, deductible_on=date(2025, 5, 10),
        deducted_on=date(2025, 7, 2))
    assert r.applies
    assert r.months == 3                    # May, June, July
    assert r.interest_paise == 3000_00      # 1% x 3
    assert r.rate_bps_per_month == 100


def test_the_two_limbs_are_not_collapsed():
    """Same tax, same span, different limb — the rates must differ."""
    late_deduct = interest.interest_on_late_deduction(
        tax_paise=100000_00, deductible_on=date(2025, 5, 10),
        deducted_on=date(2025, 7, 2))
    late_deposit = interest.interest_on_late_deposit(
        tax_paise=100000_00, deducted_on=date(2025, 5, 10),
        due_date=date(2025, 6, 7), deposited_on=date(2025, 7, 2))
    assert late_deduct.months == late_deposit.months == 3
    assert late_deposit.interest_paise == late_deduct.interest_paise * 3 // 2
    assert late_deduct.limb == "201(1A)(i)"
    assert late_deposit.limb == "201(1A)(ii)"


def test_tax_never_deducted_is_refused_because_the_end_date_is_the_payees():
    r = interest.interest_on_late_deduction(
        tax_paise=100000_00, deductible_on=date(2025, 5, 10), deducted_on=None)
    assert not r.applies and r.interest_paise == 0
    assert "PAYEE furnished their return" in r.reason


def test_deducting_on_time_is_not_a_default():
    r = interest.interest_on_late_deduction(
        tax_paise=100000_00, deductible_on=date(2025, 5, 10),
        deducted_on=date(2025, 5, 10))
    assert not r.applies and r.interest_paise == 0


# ── §234E: days, and the cap ─────────────────────────────────────────────────

def test_the_fee_is_two_hundred_rupees_a_day():
    f = interest.fee_234e(due_date=date(2025, 7, 31), filed_on=date(2025, 8, 10),
                          tax_deductible_paise=50000_00)
    assert f.applies and f.days_late == 10
    assert f.fee_paise == 2000_00
    assert f.as_dict()["capped"] is False


def test_the_fee_is_counted_in_days_and_not_in_months():
    """Ten days is ₹2,000. A month-or-part reading of §234E would give ₹200 —
    thirty times too small, and the two sections are next to each other."""
    f = interest.fee_234e(due_date=date(2025, 7, 31), filed_on=date(2025, 8, 10),
                          tax_deductible_paise=50000_00)
    assert f.fee_paise == 10 * interest.FEE_234E_PER_DAY_PAISE


def test_the_fee_is_capped_at_the_statements_own_tax():
    f = interest.fee_234e(due_date=date(2025, 7, 31), filed_on=date(2026, 8, 10),
                          tax_deductible_paise=50000_00)
    assert f.days_late == 375
    assert f.uncapped_paise == 375 * 200_00
    assert f.fee_paise == 50000_00
    assert f.as_dict()["capped"] is True
    assert "shall not exceed" in f.reason


def test_a_statement_filed_on_time_carries_no_fee():
    f = interest.fee_234e(due_date=date(2025, 7, 31), filed_on=date(2025, 7, 31),
                          tax_deductible_paise=50000_00)
    assert not f.applies and f.fee_paise == 0


def test_a_nil_statement_cannot_carry_a_fee_because_the_cap_is_nil():
    f = interest.fee_234e(due_date=date(2025, 7, 31), filed_on=date(2026, 1, 1),
                          tax_deductible_paise=0)
    assert f.fee_paise == 0


# ── The filing demo stopped being the only place that knows §234E ────────────

def test_the_filing_demo_has_no_private_fee_constant_left():
    src = Path("services/filing_demo/tds_return.py").read_text()
    assert "_S234E_FEE_PER_DAY_PAISE" not in src, (
        "the demo used to be the only place in the product that computed the "
        "§234E fee; it must now read domain/tds/interest.py")
    assert "tds_interest.fee_234e(" in src


def test_the_filing_demo_measures_lateness_in_ist():
    """`date.today()` is UTC in this container, so a statement due today read
    as one day late for the first five and a half hours of every Indian day."""
    src = _code_only(Path("services/filing_demo/tds_return.py"))
    assert "ist_today" in src
    assert not re.search(r"\bdate \. today \(", src)


# ── The deposit-due worksheet ────────────────────────────────────────────────

def _rows():
    return [
        {"id": "d1", "section": "194J", "transaction_date": "2025-06-04",
         "payment_amount_paise": 100000_00, "tds_paise": 10000_00,
         "status": "deducted", "deductee_name": "Alpha"},
        {"id": "d2", "section": "194J", "transaction_date": "2025-06-20",
         "payment_amount_paise": 50000_00, "tds_paise": 5000_00,
         "challan_date": "2025-07-07", "status": "deposited",
         "deductee_name": "Beta"},
        {"id": "d3", "section": "194C", "transaction_date": "2025-06-10",
         "payment_amount_paise": 200000_00, "tds_paise": 2000_00,
         "challan_date": "2025-08-20", "status": "deposited",
         "deductee_name": "Gamma"},
    ]


def test_the_worksheet_is_one_line_per_section_because_a_challan_is():
    w = deposit_due.build(_rows(), month="2025-06", due_date=date(2025, 7, 7),
                          as_at=date(2025, 9, 12))
    assert [s.section for s in w.sections] == ["194C", "194J"]


def test_a_deposited_deduction_is_not_still_outstanding():
    w = deposit_due.build(_rows(), month="2025-06", due_date=date(2025, 7, 7),
                          as_at=date(2025, 9, 12))
    j = next(s for s in w.sections if s.section == "194J")
    assert j.tax_paise == 15000_00
    assert j.deposited_paise == 5000_00
    assert j.outstanding_paise == 10000_00


def test_interest_is_computed_per_row_not_on_the_section_total():
    """Two deductions in one month, days apart: one on time, one still unpaid.
    A section-level clock would charge both or neither."""
    w = deposit_due.build(_rows(), month="2025-06", due_date=date(2025, 7, 7),
                          as_at=date(2025, 9, 12))
    j = next(s for s in w.sections if s.section == "194J")
    # Only d1 is late: ₹10,000 x 1.5% x 4 months (June-September) = ₹600.
    assert j.late_row_count == 1
    assert j.interest_paise == 600_00


def test_a_late_deposit_carries_interest_even_though_nothing_is_outstanding():
    w = deposit_due.build(_rows(), month="2025-06", due_date=date(2025, 7, 7),
                          as_at=date(2025, 9, 12))
    c = next(s for s in w.sections if s.section == "194C")
    assert c.outstanding_paise == 0
    # ₹2,000 x 1.5% x 3 months (June, July, August) = ₹90.
    assert c.interest_paise == 90_00
    assert c.as_dict()["payable_paise"] == 90_00


def test_surcharge_and_cess_are_part_of_what_must_be_deposited():
    """On a §195 remittance they are not zero, and they are as much due by the
    7th as the base rate is."""
    rows = [{"id": "x", "section": "195", "transaction_date": "2025-06-02",
             "payment_amount_paise": 100000_00, "tds_paise": 20000_00,
             "surcharge_paise": 2000_00, "cess_paise": 880_00,
             "status": "deducted"}]
    w = deposit_due.build(rows, month="2025-06", due_date=date(2025, 7, 7),
                          as_at=date(2025, 7, 8))
    assert w.sections[0].tax_paise == 22880_00
    # One month (June and July are two — 2 June to 8 July): 1.5% x 2.
    assert w.sections[0].interest_paise == 22880_00 * 150 * 2 // 10_000


def test_a_row_with_no_deduction_date_is_skipped_rather_than_dated():
    rows = [{"id": "x", "section": "194C", "transaction_date": None,
             "tds_paise": 5000_00}]
    w = deposit_due.build(rows, month="2025-06", due_date=date(2025, 7, 7),
                          as_at=date(2025, 9, 12))
    assert w.sections == ()


def test_a_deposited_row_with_no_challan_date_is_named_and_counted_unpaid():
    rows = [{"id": "x", "section": "194C", "transaction_date": "2025-06-02",
             "tds_paise": 5000_00, "status": "deposited",
             "deductee_name": "Delta"}]
    w = deposit_due.build(rows, month="2025-06", due_date=date(2025, 7, 7),
                          as_at=date(2025, 9, 12))
    kinds = [g["kind"] for g in w.statutory_gaps]
    assert deposit_due.GAP_DEPOSITED_WITH_NO_CHALLAN_DATE in kinds
    assert w.sections[0].outstanding_paise == 5000_00


def test_a_salary_row_in_this_register_is_named():
    rows = [{"id": "x", "section": "192", "transaction_date": "2025-06-02",
             "tds_paise": 1000_00, "status": "deducted", "deductee_name": "Eps"}]
    w = deposit_due.build(rows, month="2025-06", due_date=date(2025, 7, 7),
                          as_at=date(2025, 9, 12))
    kinds = [g["kind"] for g in w.statutory_gaps]
    assert deposit_due.GAP_SALARY_ROW_IN_THIS_REGISTER in kinds


def test_every_worksheet_says_what_it_does_not_cover():
    """A total that looks like "the month's TDS" and is only part of it is the
    thing this must not be read as — so the note is unconditional."""
    for rows in ([], _rows()):
        w = deposit_due.build(rows, month="2025-06", due_date=date(2025, 7, 7),
                              as_at=date(2025, 9, 12))
        assert "§192" in w.as_dict()["covers"]


def test_the_totals_are_the_sum_of_the_lines():
    w = deposit_due.build(_rows(), month="2025-06", due_date=date(2025, 7, 7),
                          as_at=date(2025, 9, 12))
    t = w.totals
    assert t["tax_paise"] == sum(s.tax_paise for s in w.sections)
    assert t["payable_paise"] == t["outstanding_paise"] + t["interest_paise"]


# ── The endpoint ─────────────────────────────────────────────────────────────

def test_the_endpoint_answers_the_worksheet(client):
    from routers.tds_workspace import _MOCK_DEDUCTIONS
    for row in _rows():
        _MOCK_DEDUCTIONS[row["id"]] = {**row, "client_id": _CLIENT_ID,
                                       "firm_id": "firm-1"}
    resp = client.get(
        f"/api/tds-workspace/deposit-due?client_id={_CLIENT_ID}&month=2025-06",
        headers=_HEADERS)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["due_date"] == "2025-07-07"
    assert data["due_date_rule"] == "IT Act Rule 30(2)"
    assert {s["section"] for s in data["sections"]} == {"194C", "194J"}


def test_the_endpoint_reads_only_the_month_asked_for(client):
    from routers.tds_workspace import _MOCK_DEDUCTIONS
    _MOCK_DEDUCTIONS["in"] = {"id": "in", "client_id": _CLIENT_ID,
                              "firm_id": "firm-1", "section": "194C",
                              "transaction_date": "2025-06-30",
                              "tds_paise": 100_00, "status": "deducted"}
    _MOCK_DEDUCTIONS["out"] = {"id": "out", "client_id": _CLIENT_ID,
                               "firm_id": "firm-1", "section": "194J",
                               "transaction_date": "2025-07-01",
                               "tds_paise": 900_00, "status": "deducted"}
    resp = client.get(
        f"/api/tds-workspace/deposit-due?client_id={_CLIENT_ID}&month=2025-06",
        headers=_HEADERS)
    data = resp.json()["data"]
    assert [s["section"] for s in data["sections"]] == ["194C"]
    assert data["totals"]["tax_paise"] == 100_00


def test_a_malformed_month_is_refused_with_a_sentence(client):
    resp = client.get(
        f"/api/tds-workspace/deposit-due?client_id={_CLIENT_ID}&month=Q1",
        headers=_HEADERS)
    assert resp.status_code == 422
    assert "YYYY-MM" in str(resp.json())


def test_a_december_month_rolls_into_the_next_year(client):
    from routers.tds_workspace import _MOCK_DEDUCTIONS
    _MOCK_DEDUCTIONS["d"] = {"id": "d", "client_id": _CLIENT_ID,
                             "firm_id": "firm-1", "section": "194C",
                             "transaction_date": "2025-12-31",
                             "tds_paise": 100_00, "status": "deducted"}
    resp = client.get(
        f"/api/tds-workspace/deposit-due?client_id={_CLIENT_ID}&month=2025-12",
        headers=_HEADERS)
    data = resp.json()["data"]
    assert data["due_date"] == "2026-01-07"
    assert data["totals"]["tax_paise"] == 100_00


# ── The challan split ────────────────────────────────────────────────────────

def _challan_body(**over):
    body = {"client_id": _CLIENT_ID, "bsr_code": "1234567",
            "challan_date": "2025-08-20", "amount_paise": 83600_00,
            "challan_no": "CHL-9", "section": "194J",
            "financial_year": "2025-26", "quarter": "Q1"}
    body.update(over)
    return body


def test_the_split_is_stored_and_the_tax_is_the_remainder(client):
    resp = client.post("/api/tds-workspace/challans",
                       json=_challan_body(interest_paise=3600_00),
                       headers=_HEADERS)
    assert resp.status_code == 200
    d = resp.json()["data"]
    assert d["total_paise"] == 83600_00
    assert d["interest_paise"] == 3600_00
    assert d["tds_paise"] == 80000_00, (
        "the whole amount used to be booked as tax, so a challan that paid "
        "§201(1A) interest made the section read as over-deposited")


def test_sending_no_components_keeps_the_old_behaviour_exactly(client):
    resp = client.post("/api/tds-workspace/challans", json=_challan_body(),
                       headers=_HEADERS)
    d = resp.json()["data"]
    assert d["tds_paise"] == d["total_paise"] == 83600_00
    assert d["surcharge_paise"] == d["interest_paise"] == d["penalty_paise"] == 0


def test_components_larger_than_the_total_are_refused(client):
    resp = client.post(
        "/api/tds-workspace/challans",
        json=_challan_body(amount_paise=1000_00, interest_paise=900_00,
                           penalty_paise=900_00),
        headers=_HEADERS)
    assert resp.status_code == 422
    assert "more than" in str(resp.json())


def test_a_negative_component_is_refused_by_the_model(client):
    resp = client.post("/api/tds-workspace/challans",
                       json=_challan_body(interest_paise=-1), headers=_HEADERS)
    assert resp.status_code == 422


def test_the_minor_head_can_finally_be_a_four_hundred(client):
    resp = client.post("/api/tds-workspace/challans",
                       json=_challan_body(minor_head="400"), headers=_HEADERS)
    assert resp.json()["data"]["minor_head"] == "400"


def test_an_unknown_minor_head_is_refused(client):
    resp = client.post("/api/tds-workspace/challans",
                       json=_challan_body(minor_head="300"), headers=_HEADERS)
    assert resp.status_code == 422


def test_the_fee_head_takes_the_two_thirty_four_e_fee(client):
    """§234E is a FEE, not tax, and it goes on the same challan under its own
    head — which is why penalty_paise had to become settable."""
    resp = client.post("/api/tds-workspace/challans",
                       json=_challan_body(penalty_paise=2000_00),
                       headers=_HEADERS)
    d = resp.json()["data"]
    assert d["penalty_paise"] == 2000_00
    assert d["tds_paise"] == 81600_00


# ── One implementation, not two ──────────────────────────────────────────────

def test_the_deposit_due_module_does_no_io():
    """It is a pure function over rows the router fetched, so mock mode and
    Postgres give the same answer by construction rather than by a parity
    test."""
    src = inspect.getsource(deposit_due)
    for forbidden in ("get_supabase", ".table(", "requests.", "httpx"):
        assert forbidden not in src


def test_nothing_else_states_the_two_hundred_rupees_a_day():
    """§234E's rate lives in one place. A second literal is how the filing
    demo came to be the only thing that knew it."""
    hits = []
    for path in sorted(Path(".").rglob("*.py")):
        text = str(path)
        if text.startswith("tests/") or path.name == "interest.py":
            continue
        raw = path.read_text(errors="ignore")
        if "234E" not in raw:
            continue
        try:
            code = _code_only(path)
        except (tokenize.TokenError, IndentationError, SyntaxError):
            continue
        if "200_00" in code or "20000" in code.split():
            hits.append(text)
    assert hits == [], f"§234E's ₹200 a day is stated outside the module: {hits}"
