"""
Posted money out of the ledger with no document behind it must be found.

WHAT THIS IS FOR
    create_purchase_payment posts the journal FIRST and inserts the payment row
    second, compensating with an append-only reversal if the insert fails.
    routers/purchase_payments.py's own log line admits the residue when the
    compensation also fails: "manual reconciliation required, a phantom GL
    entry may remain."

    Driving a client through a full financial year produced eleven of them —
    Rs 2,00,000 each, all posted — and the bank read Rs 3,00,000 against a true
    Rs 25,00,000. The log said so eleven times and nothing else did.

    This check cannot prevent the gap. The ledger is written before the
    document, and closing that would need one transaction across two tables
    PostgREST cannot give. What it does is stop the books being quietly wrong
    until somebody reads a log.
"""
import ast
import inspect

import pytest

from domain.accounting import journal_source
from services import reconciliation_service as rs
from services.reconciliation_service import _CHECKS, check_orphan_money_journals


class Line:
    def __init__(self, debit=0, credit=0):
        self.debit_paise, self.credit_paise = debit, credit


class Entry:
    def __init__(self, eid, entry_type, debit=0, ref="VPMT-0001", when="2026-03-27",
                 source_type=None, reversal_of=None):
        self.id, self.entry_type = eid, entry_type
        self.reference_no, self.entry_date = ref, when
        self.source_type, self.reversal_of = source_type, reversal_of
        self.lines = [Line(debit=debit), Line(credit=debit)]


class DB:
    """Answers the three lookups the check makes."""

    def __init__(self, payments=(), receipts=(), reversals=()):
        self.payments = set(payments)
        self.receipts = set(receipts)
        self.reversals = set(reversals)
        self._t = None
        self._f = {}

    def table(self, name):
        self._t, self._f = name, {}
        return self

    def select(self, *_a):
        return self

    def eq(self, col, val):
        self._f[col] = val
        return self

    def limit(self, _n):
        return self

    def execute(self):
        je = self._f.get("journal_entry_id")
        rev = self._f.get("reversal_of")
        if self._t == "purchase_payments":
            hit = je in self.payments
        elif self._t == "receipts":
            hit = je in self.receipts
        else:
            hit = rev in self.reversals
        return type("R", (), {"data": [{"id": "x"}] if hit else []})()


def run(entries, db):
    return check_orphan_money_journals(db, "f1", "c1", {e.id: e for e in entries})


# ── What it finds ────────────────────────────────────────────────────────────

def test_a_posted_payment_with_no_document_is_critical():
    out = run([Entry("je1", "Payment", debit=2_00_000_00)], DB())
    assert len(out) == 1
    assert out[0]["check_name"] == "orphan_money_journals"
    assert out[0]["severity"] == "critical"
    assert out[0]["amount_paise"] == 2_00_000_00


def test_the_eleven_from_the_walkthrough_are_reported_as_one_finding():
    """One finding carrying all of them, not eleven findings — a Partner
    reviewing this needs the total and the list, not a wall."""
    entries = [Entry(f"je{i}", "Payment", debit=2_00_000_00) for i in range(11)]
    out = run(entries, DB())
    assert len(out) == 1
    assert out[0]["details"]["orphan_count"] == 11
    assert out[0]["amount_paise"] == 22_00_000_00
    assert len(out[0]["details"]["entries"]) == 11


def test_a_receipt_with_no_document_is_found_too():
    out = run([Entry("je1", "Receipt", debit=5_00_000_00)], DB())
    assert len(out) == 1


# ── What it must NOT flag ────────────────────────────────────────────────────

def test_a_payment_with_its_document_is_fine():
    assert run([Entry("je1", "Payment", debit=100)], DB(payments=["je1"])) == []


def test_a_receipt_with_its_document_is_fine():
    assert run([Entry("je1", "Receipt", debit=100)], DB(receipts=["je1"])) == []


def test_a_compensated_entry_is_not_an_orphan():
    """The compensation working is the mechanism doing its job. A reversed
    entry and its reversal net to zero; flagging those would bury the real
    ones in noise."""
    assert run([Entry("je1", "Payment", debit=100)], DB(reversals=["je1"])) == []


def test_other_entry_types_are_left_alone():
    """Sales, Purchase, Journal and Opening entries have their own subledger
    checks. This one is only about money that moved with no document."""
    for kind in ("Sales", "Purchase", "Journal", "Opening"):
        assert run([Entry("je1", kind, debit=100)], DB()) == []


def test_a_clean_ledger_reports_nothing():
    assert run([], DB()) == []


# ── It is actually wired in ──────────────────────────────────────────────────

def test_the_check_runs_as_part_of_the_reconciliation():
    """A check nothing calls is a check that never fires — which is how the
    phantom entries went unnoticed in the first place."""
    assert check_orphan_money_journals in _CHECKS


def test_the_summary_says_what_happened_and_what_to_do():
    out = run([Entry("je1", "Payment", debit=100)], DB())
    summary = out[0]["summary"]
    assert "no payment or receipt document behind them" in summary
    assert "Reverse them" in summary, "a Partner reading this needs the next step"


# ── Which entries it judges ──────────────────────────────────────────────────
#
# The check searches two tables, receipts and purchase_payments. A posting is
# worth searching for only if its source says one of them should hold it. The
# Payment / Receipt entries below have no row in either BY DESIGN, and each was
# reported as "most likely a document insert failed" on a healthy book:
#   payroll_disbursement  salary paid out of the bank (Sunrise 10, Vaibhav 10)
#   bank_transaction      every voucher passed from the bank queue
#   bill_of_entry         the import duty is paid to customs, not a supplier
#   bank_overpayment      a bank line larger than the document it settled
#   manual                a voucher typed or imported by a person

NOT_SEARCHABLE = sorted(journal_source.ALL_SOURCES - rs._JUDGED_SOURCES)


@pytest.mark.parametrize("source", NOT_SEARCHABLE)
@pytest.mark.parametrize("kind", ["Payment", "Receipt"])
def test_a_posting_whose_source_is_not_a_searched_table_is_not_an_orphan(source, kind):
    assert run([Entry("je1", kind, debit=100, source_type=source)], DB()) == []


@pytest.mark.parametrize("source", sorted(rs._JUDGED_SOURCES))
def test_a_posting_whose_document_should_exist_and_does_not_is_still_critical(source):
    out = run([Entry("je1", "Payment", debit=100, source_type=source)], DB())
    assert len(out) == 1 and out[0]["severity"] == "critical"


def test_an_unstamped_posting_is_still_judged():
    """It predates the source stamp (migration 104), so it cannot be told from
    an orphan; judging it is the safe side."""
    out = run([Entry("je1", "Receipt", debit=100, source_type=None)], DB())
    assert len(out) == 1


def test_a_reversal_entry_is_the_compensation_not_an_orphan():
    """reverse_entry copies the original's entry type and source onto the
    reversal, and no document row points at the reversal. The original has its
    row and a reversal against it; the reversal itself was reported as a
    critical orphan."""
    original = Entry("je1", "Receipt", debit=100, source_type="receipt")
    reversal = Entry("je2", "Receipt", debit=100, source_type="receipt", reversal_of="je1")
    assert run([original, reversal], DB(receipts=["je1"], reversals=["je1"])) == []


def test_a_reversal_of_a_phantom_does_not_hide_a_second_phantom():
    """Skipping reversal entries must not skip an ordinary orphan beside them."""
    phantom = Entry("je1", "Payment", debit=100, source_type="purchase_payment")
    reversed_ = Entry("je2", "Payment", debit=100, source_type="purchase_payment")
    reversal = Entry("je3", "Payment", debit=100, source_type="purchase_payment", reversal_of="je2")
    out = run([phantom, reversed_, reversal], DB(reversals=["je2"]))
    assert [e["journal_entry_id"] for e in out[0]["details"]["entries"]] == ["je1"]


def test_the_sources_judged_are_exactly_the_tables_searched():
    """The rule, not a list: the check may look for a document only in the
    tables it judges by, and may judge only by sources whose table it looks in.
    The pairing is written once (``_MONEY_DOCUMENT_TABLES``); the check names
    its tables as literals, which the firm-scope reader can see and a table
    chosen by a variable it cannot, so this test is what holds the two
    statements together: every table the check queries is a literal, and those
    literals are the pairing's tables plus the journal it asks about reversals."""
    assert rs._JUDGED_SOURCES == {src for _t, src in rs._MONEY_DOCUMENT_TABLES}
    assert rs._JUDGED_SOURCES <= journal_source.ALL_SOURCES
    tree = ast.parse(inspect.getsource(check_orphan_money_journals).lstrip())
    table_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr == "table"
    ]
    assert table_calls, "the check queries no table at all"
    assert all(c.args and isinstance(c.args[0], ast.Constant) for c in table_calls), (
        "a table chosen by a variable is a chain the firm-scope reader cannot read")
    named = {c.args[0].value for c in table_calls}
    assert named == {"journal_entries"} | {t for t, _src in rs._MONEY_DOCUMENT_TABLES}, named
