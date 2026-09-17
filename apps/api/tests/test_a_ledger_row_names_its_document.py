"""
ACC-22 — a ledger row carries the DOCUMENT behind it, so it can be opened.

WHAT WAS WRONG
    `journal_entries.source_type` / `source_id` have existed since migration 104
    and have been filled in by all twenty-six posting paths since commit
    99ac94b5 — whose own message says "This commit is the missing premise; the
    drill-through itself is a separate change." The ledger was the half that
    never read them: neither `domain/reporting/builders.ledger` nor the SQL twin
    `public.account_ledger_page` selected either column, so a CA reading
    "Trade Receivables 1,18,000 Dr" had a narration, a reference and nothing to
    open. Tally has trained them to expect one keystroke to the invoice.

WHAT THIS FILE HOLDS
    The MOCK-mode half: that the two keys reach the row, unconditionally, with
    the right values, and that they change nothing else. The SQL twin is held
    identical by tests/test_account_ledger_sql_parity_pg.py, which also carries
    the three document scenarios and the floor that stops them from being a
    comparison of two silences. And
    tests/test_the_browser_can_open_the_document_the_ledger_names.py holds the
    third side: that every value the backend can stamp has an answer in the
    browser's route map.

WHY "ALWAYS PRESENT" IS ITS OWN ASSERTION
    An ABSENT key and a null key read the same to `line.source_type ?? null`,
    and they are different bugs: null is "this entry has no document", absent is
    "this build did not send it". The screen renders the first and cannot detect
    the second.
"""
from __future__ import annotations

import pytest

from domain.accounting import journal_source as JS
from domain.reporting import (
    Account, JournalEntry, JournalLine, InMemoryLedgerSource, ReportingService,
)

FIRM, CLIENT = "firm-1", "client-1"
START, END = "2025-04-01", "2026-03-31"

ACCOUNTS = [
    Account("ar", "1100", "Trade Receivables", "Asset", "Receivable", system_key="ar"),
    Account("rev", "4000", "Sales", "Revenue"),
    Account("bank", "1000", "Bank", "Asset", "Bank", system_key="bank"),
]


def je(jid, date, lines, *, source_type=None, source_id=None):
    return JournalEntry(
        id=jid, entry_date=date, client_id=CLIENT, firm_id=FIRM, entry_type="x",
        lines=tuple(JournalLine(*l) for l in lines),
        created_at=f"{date}T00:00:00", reference_no=f"REF-{jid}", narration=f"narr {jid}",
        source_type=source_type, source_id=source_id,
    )


def ledger(entries, account_id="ar"):
    svc = ReportingService(InMemoryLedgerSource(accounts=ACCOUNTS, entries=entries))
    return svc.ledger(FIRM, CLIENT, account_id, START, END)


def test_a_row_names_the_invoice_behind_it():
    out = ledger([je("a", "2025-06-01", [("ar", 118000, 0), ("rev", 0, 118000)],
                     source_type=JS.SALES_INVOICE, source_id="inv-9")])
    line = out["lines"][0]
    assert line["source_type"] == "sales_invoice"
    assert line["source_id"] == "inv-9"


def test_both_keys_are_present_even_when_the_entry_carries_none():
    out = ledger([je("a", "2025-06-01", [("ar", 500, 0), ("rev", 0, 500)])])
    line = out["lines"][0]
    assert "source_type" in line and "source_id" in line, (
        "an absent key and a null key are different bugs and the screen can "
        "only see one of them")
    assert line["source_type"] is None and line["source_id"] is None


def test_a_source_whose_entry_is_the_record_keeps_its_type():
    # journal_source.ENTRY_IS_THE_RECORD — a manual journal, an opening balance
    # and a trial-balance import name no row to open, so the id is null and the
    # TYPE is what tells the browser to send the CA to the entry itself.
    for st in sorted(JS.ENTRY_IS_THE_RECORD):
        out = ledger([je("a", "2025-06-01", [("ar", 500, 0), ("rev", 0, 500)],
                         source_type=st, source_id=None)])
        line = out["lines"][0]
        assert line["source_type"] == st
        assert line["source_id"] is None


def test_each_row_carries_its_own_entry_s_document():
    out = ledger([
        je("a", "2025-05-01", [("ar", 118000, 0), ("rev", 0, 118000)],
           source_type=JS.SALES_INVOICE, source_id="inv-1"),
        je("b", "2025-06-01", [("bank", 118000, 0), ("ar", 0, 118000)],
           source_type=JS.RECEIPT, source_id="rcpt-1"),
        je("c", "2025-07-01", [("ar", 900, 0), ("rev", 0, 900)]),
    ])
    assert [l["source_type"] for l in out["lines"]] == ["sales_invoice", "receipt", None]
    assert [l["source_id"] for l in out["lines"]] == ["inv-1", "rcpt-1", None]


def test_two_lines_of_one_entry_both_carry_it():
    # One journal, two legs on the same account. Both rows open the same
    # document, because both came from the same entry.
    out = ledger([je("d", "2025-06-01", [("ar", 500, 0), ("ar", 0, 200), ("rev", 0, 300)],
                     source_type=JS.SALES_INVOICE, source_id="inv-2")])
    assert len(out["lines"]) == 2
    assert {l["source_id"] for l in out["lines"]} == {"inv-2"}


def test_the_document_changes_no_figure():
    # The drill-through is display only. Same entries with and without a source
    # must produce identical money.
    lines = [("ar", 118000, 0), ("rev", 0, 118000)]
    plain = ledger([je("a", "2025-06-01", lines)])
    stamped = ledger([je("a", "2025-06-01", lines,
                         source_type=JS.SALES_INVOICE, source_id="inv-9")])
    for key in ("opening_balance_paise", "closing_balance_paise",
                "total_debit_paise", "total_credit_paise"):
        assert plain[key] == stamped[key]
    for a, b in zip(plain["lines"], stamped["lines"]):
        for key in ("debit_paise", "credit_paise", "running_balance_paise", "is_debit"):
            assert a[key] == b[key]


@pytest.mark.parametrize("report", ["trial_balance", "profit_loss", "balance_sheet"])
def test_no_aggregation_report_grew_a_document_key(report):
    # The two columns are read by the ledger and by nothing else. A report that
    # started carrying them would be a second place to keep them in step, and
    # they mean nothing once rows are summed.
    svc = ReportingService(InMemoryLedgerSource(accounts=ACCOUNTS, entries=[
        je("a", "2025-06-01", [("ar", 118000, 0), ("rev", 0, 118000)],
           source_type=JS.SALES_INVOICE, source_id="inv-9")]))
    out = getattr(svc, report)(FIRM, CLIENT, START, END)
    blob = repr(out)
    assert "source_id" not in blob and "inv-9" not in blob
