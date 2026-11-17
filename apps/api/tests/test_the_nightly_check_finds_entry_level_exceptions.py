"""The nightly books check finds four entry-level exceptions, and stays quiet on
the ordinary case (POST-A-090).

`domain/accounting/journal_exceptions` is the rule; `services/
reconciliation_service` files what it finds as WARNINGS that carry the innocent
reading. Each test below has a firing case and at least one ordinary case that
must not fire, because a check that fires on ordinary books is a check a CA
turns off.
"""
from __future__ import annotations

from datetime import date

import pytest

from domain.accounting import journal_exceptions as jx
from domain.gst import tax_control_accounts
from domain.reporting.model import JournalEntry, JournalLine
from tests.e2e_harness import FakeDB

import services.reconciliation_service as rs

FIRM, CLIENT = "FIRM-A", "CLI-A"
AS_OF = date(2026, 11, 16)
LAKH = 1_00_000_00


def _e(id_, d, source="manual", *, amount=LAKH, accounts=("exp", "cap"), narration="adj",
       reversal_of=None, lines=None):
    if lines is None:
        lines = (JournalLine(accounts[0], amount, 0), JournalLine(accounts[1], 0, amount))
    return JournalEntry(id=id_, entry_date=d, client_id=CLIENT, firm_id=FIRM,
                        entry_type="Journal", lines=tuple(lines), narration=narration,
                        source_type=source, reversal_of=reversal_of, reference_no=f"R-{id_}")


# ── round figure ─────────────────────────────────────────────────────────────

def test_a_one_off_round_manual_journal_is_found():
    got = jx.round_figure_journals([_e("a", "2026-09-30", amount=5 * LAKH)], as_of=AS_OF)
    assert [x.kind for x in got] == [jx.ROUND_FIGURE_JOURNAL]
    assert got[0].amount_paise == 5 * LAKH and got[0].also_could_be


@pytest.mark.parametrize("entries", [
    [_e("a", "2026-09-30", amount=5 * LAKH + 1)],                          # not round
    [_e("a", "2026-09-30", amount=50_000_00)],                              # round, below the floor
    [_e("a", "2026-09-30", source="sales_invoice", amount=5 * LAKH)],       # a document
    [_e("a", "2024-09-30", amount=5 * LAKH)],                               # outside the year
    [_e("a", "2026-09-30", amount=5 * LAKH), _e("b", "2026-08-31", amount=5 * LAKH)],  # recurs
    [_e("a", "2026-09-30", amount=5 * LAKH),
     _e("b", "2026-09-30", amount=5 * LAKH, narration="rev", reversal_of="a")],        # a reversed pair
])
def test_the_ordinary_round_journal_is_left_alone(entries):
    assert jx.round_figure_journals(entries, as_of=AS_OF) == []


# ── Sunday ───────────────────────────────────────────────────────────────────

def _weekday_documents(n):
    # 2026-10-05 is a Monday; spread over weekdays only.
    days = ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]
    return [_e(f"d{i}", days[i % 5], source="sales_invoice", amount=1000 + i,
               narration=f"inv {i}") for i in range(n)]


def test_a_sunday_journal_is_found_for_a_client_that_does_not_trade_on_sundays():
    entries = _weekday_documents(25) + [_e("s", "2026-10-11", amount=1234)]  # a Sunday
    got = jx.sunday_journals(entries, as_of=AS_OF)
    assert [x.entry_id for x in got] == ["s"]


def test_a_client_that_trades_on_sundays_is_left_alone():
    docs = _weekday_documents(20) + [
        _e(f"sun{i}", "2026-10-18", source="sales_invoice", amount=500 + i, narration=f"s{i}")
        for i in range(2)]
    entries = docs + [_e("s", "2026-10-11", amount=1234)]
    assert jx.sunday_journals(entries, as_of=AS_OF) == []


def test_too_few_documents_to_judge_the_week_is_left_alone():
    entries = _weekday_documents(5) + [_e("s", "2026-10-11", amount=1234)]
    assert jx.sunday_journals(entries, as_of=AS_OF) == []


def test_a_saturday_journal_is_not_tested():
    entries = _weekday_documents(25) + [_e("s", "2026-10-10", amount=1234)]  # a Saturday
    assert jx.sunday_journals(entries, as_of=AS_OF) == []


@pytest.mark.parametrize("day", [
    "2026-05-31",   # a Sunday that is a month's LAST day: the month-end provision is dated on it
    "2026-03-01",   # a Sunday that is a month's FIRST day: the accrual's reversal is dated on it
])
def test_a_journal_dated_on_a_months_first_or_last_day_is_not_tested(day):
    # The date is the period's, not the day the entry was keyed, so the Sunday says
    # nothing; the same client's mid-month Sunday journal is still found.
    entries = _weekday_documents(25) + [_e("edge", day, amount=1234),
                                        _e("mid", "2026-10-11", amount=4321)]
    assert [x.entry_id for x in jx.sunday_journals(entries, as_of=AS_OF)] == ["mid"]


# ── a suspended maker ────────────────────────────────────────────────────────

MEMBERS = [
    {"id": "gone", "is_active": False, "sessions_revoked_at": "2026-10-01T10:00:00+00:00"},
    {"id": "here", "is_active": True, "sessions_revoked_at": "2026-10-01T10:00:00+00:00"},
    {"id": "nodate", "is_active": False, "sessions_revoked_at": None},
]


def test_an_entry_made_after_its_maker_was_suspended_is_found():
    rows = [
        {"id": "after", "created_by": "gone", "created_at": "2026-10-02T09:00:00Z", "amount_paise": 500},
        {"id": "before", "created_by": "gone", "created_at": "2026-09-30T09:00:00Z"},
        {"id": "active", "created_by": "here", "created_at": "2026-10-02T09:00:00Z"},
        {"id": "unknown", "created_by": "nodate", "created_at": "2026-10-02T09:00:00Z"},
    ]
    got = jx.departed_member_entries(rows, MEMBERS)
    assert [x.entry_id for x in got] == ["after"]


def test_the_service_reads_only_suspended_members_and_their_later_entries():
    db = FakeDB()
    db.seed("users", {"id": "gone", "firm_id": FIRM, "is_active": False,
                      "sessions_revoked_at": "2026-10-01T10:00:00+00:00"})
    db.seed("users", {"id": "other-firm", "firm_id": "FIRM-B", "is_active": False,
                      "sessions_revoked_at": "2026-10-01T10:00:00+00:00"})
    db.seed("journal_entries", {"id": "j1", "firm_id": FIRM, "client_id": CLIENT,
                                "is_posted": True, "deleted_at": None, "entry_date": "2026-10-02",
                                "created_at": "2026-10-02T09:00:00+00:00", "created_by": "gone",
                                "reference_no": "R1"})
    db.seed("journal_entries", {"id": "j2", "firm_id": FIRM, "client_id": CLIENT,
                                "is_posted": True, "deleted_at": None, "entry_date": "2026-10-02",
                                "created_at": "2026-10-02T09:00:00+00:00", "created_by": "other-firm",
                                "reference_no": "R2"})
    entries = {"j1": _e("j1", "2026-10-02", amount=777)}
    got = rs.check_entries_after_their_maker_was_suspended(db, FIRM, CLIENT, entries)
    assert [f["details"]["entry_id"] for f in got] == ["j1"]
    assert got[0]["check_name"] == "entry_made_after_its_maker_was_suspended"
    assert got[0]["severity"] == "warning" and got[0]["amount_paise"] == 777


# ── receipts up, output tax down ─────────────────────────────────────────────

def _sale(id_, d, tax):
    return _e(id_, d, source="sales_invoice", lines=(
        JournalLine("ar", 10 * tax, 0), JournalLine("sales", 0, 9 * tax),
        JournalLine("out", 0, tax)))


def _receipt(id_, d, amount, source="receipt"):
    return _e(id_, d, source=source, lines=(
        JournalLine("bank", amount, 0), JournalLine("ar", 0, amount)))


def _months(entries):
    return jx.monthly_receipts_and_output_tax(entries, money_accounts={"bank", "cash"},
                                              output_accounts={"out"})


PRIOR = ["2026-05-15", "2026-06-15", "2026-07-15"]
RECENT = ["2026-08-15", "2026-09-15", "2026-10-15"]


def test_receipts_rising_while_output_tax_falls_is_found():
    entries = ([_sale(f"p{i}", d, 1 * LAKH) for i, d in enumerate(PRIOR)]
               + [_sale(f"r{i}", d, 50_000_00) for i, d in enumerate(RECENT)]
               + [_receipt(f"pr{i}", d, 5 * LAKH) for i, d in enumerate(PRIOR)]
               + [_receipt(f"rr{i}", d, 10 * LAKH) for i, d in enumerate(RECENT)])
    got = jx.receipts_against_output_tax(*_months(entries), as_of=AS_OF)
    assert [x.kind for x in got] == [jx.RECEIPTS_RISE_OUTPUT_TAX_FALLS]
    assert got[0].amount_paise == 15 * LAKH
    assert got[0].details["months"] == ["2026-08", "2026-09", "2026-10"]


def test_steady_books_are_left_alone():
    entries = ([_sale(f"s{i}", d, LAKH) for i, d in enumerate(PRIOR + RECENT)]
               + [_receipt(f"r{i}", d, 10 * LAKH) for i, d in enumerate(PRIOR + RECENT)])
    assert jx.receipts_against_output_tax(*_months(entries), as_of=AS_OF) == []


def test_a_transfer_between_own_accounts_is_not_a_receipt():
    transfer = _e("t", "2026-09-15", source="bank_transaction", lines=(
        JournalLine("bank", 50 * LAKH, 0), JournalLine("cash", 0, 50 * LAKH)))
    receipts, _ = _months([transfer])
    assert receipts == {}


def test_reverse_charge_output_tax_is_not_a_sale():
    rcm = _e("rc", "2026-09-15", source="purchase_bill", lines=(
        JournalLine("exp", LAKH, 0), JournalLine("in", 18_000_00, 0),
        JournalLine("ap", 0, LAKH), JournalLine("out", 0, 18_000_00)))
    _, output = _months([rcm])
    assert output == {}


def test_a_client_with_no_output_tax_to_fall_from_is_left_alone():
    entries = [_receipt(f"rr{i}", d, 10 * LAKH) for i, d in enumerate(RECENT)]
    assert jx.receipts_against_output_tax(*_months(entries), as_of=AS_OF) == []


def test_the_service_reads_the_output_accounts_by_the_returns_rule(monkeypatch):
    db = FakeDB()
    db.seed("chart_of_accounts", {"id": "out", "firm_id": FIRM, "client_id": None,
                                  "system_account_key": None, "account_type": "Liability",
                                  "account_name": "GST Output Tax Payable", "account_subtype": None})
    db.seed("chart_of_accounts", {"id": "bank", "firm_id": FIRM, "client_id": CLIENT,
                                  "system_account_key": None, "account_type": "Asset",
                                  "account_name": "HDFC", "account_subtype": "Bank"})
    entries = ([_sale(f"p{i}", d, 1 * LAKH) for i, d in enumerate(PRIOR)]
               + [_sale(f"r{i}", d, 50_000_00) for i, d in enumerate(RECENT)]
               + [_receipt(f"pr{i}", d, 5 * LAKH) for i, d in enumerate(PRIOR)]
               + [_receipt(f"rr{i}", d, 10 * LAKH) for i, d in enumerate(RECENT)])
    import core.ist_clock as clock
    monkeypatch.setattr(clock, "ist_today", lambda: AS_OF)
    got = rs.check_receipts_against_output_tax(db, FIRM, CLIENT, {e.id: e for e in entries})
    assert [f["check_name"] for f in got] == ["receipts_rise_while_output_tax_falls"]
    assert "innocent_reading" in got[0]["details"]


# ── the vocabulary ───────────────────────────────────────────────────────────

def test_the_four_literals_are_the_modules_kinds_and_all_are_heuristic():
    assert set(jx.ALL_KINDS) <= set(rs.CHECK_CATALOGUE)
    assert set(jx.ALL_KINDS) <= rs.HEURISTIC_CHECKS
    names = {c.__name__ for c in rs._CHECKS}
    assert {"check_round_figure_journals", "check_sunday_journals",
            "check_entries_after_their_maker_was_suspended",
            "check_receipts_against_output_tax"} <= names


def test_what_the_new_checks_cannot_see_is_served():
    served = rs.check_catalogue()["not_checked"]
    for sentence in jx.NOT_CHECKED:
        assert sentence in served


def test_the_tax_control_rule_prefers_the_key_and_falls_back_to_the_name():
    keyed = [{"id": "k", "system_account_key": "gst_cgst"},
             {"id": "n", "account_type": "Liability", "account_name": "GST Output"}]
    assert tax_control_accounts.output_and_input_ids(keyed)[0] == {"k"}
    named = [{"id": "n", "account_type": "Liability", "account_name": "GST Output Tax"},
             {"id": "i", "account_type": "Asset", "account_name": "GST Input Credit"},
             {"id": "x", "account_type": "Asset", "account_name": "GST Output Wrong Side"}]
    assert tax_control_accounts.output_and_input_ids(named) == ({"n"}, {"i"})
