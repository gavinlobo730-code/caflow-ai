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
from services.reconciliation_service import _CHECKS, check_orphan_money_journals


class Line:
    def __init__(self, debit=0, credit=0):
        self.debit_paise, self.credit_paise = debit, credit


class Entry:
    def __init__(self, eid, entry_type, debit=0, ref="VPMT-0001", when="2026-03-27"):
        self.id, self.entry_type = eid, entry_type
        self.reference_no, self.entry_date = ref, when
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
