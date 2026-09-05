"""
A customer or vendor delete says WHICH LAW and UNTIL WHEN — and says when the
reason stops being the law.

WHAT WAS WRONG

Both refused with one sentence: "this customer has linked accounting records and
cannot be permanently deleted". It names no statute, gives no date, and NEVER
LAPSES — it would refuse identically in 2050, long after every statute released
the record. From 13 May 2027 that is a standing failure to erase under DPDP
s. 8(7), and nobody reading it could tell whether the refusal was right.

TWO REASONS UNDER ONE SENTENCE

The guard was doing two jobs, and they come apart:

  RETENTION is a duty with an END, computable from the financial year of the
  record.
  REFERENTIAL is other rows pointing at this one, and does NOT end while the
  documents exist — the customer FKs are ON DELETE CASCADE and two vendor tables
  carry a vendor_id with no FK at all.

The tests below are mostly about that seam: which reason is given, and that the
answer CHANGES on a date, which is the whole difference from the sentence it
replaces.

THE QUESTION #126 LEFT OPEN, ANSWERED

A lapsed duty still does not permit the delete. Retention lapsing means the law
no longer REQUIRES the record kept; it does not mean nothing else needs it — the
invoices are still referenced by posted journal entries and by returns already
filed. So the refusal stands and the MESSAGE changes, which
test_a_lapsed_duty_changes_the_reason_but_not_the_answer pins.

NEGATIVE CONTROLS — each applied, then reverted:

  | control                                              | tests that fail |
  |------------------------------------------------------|-----------------|
  | go back to the old one-line message                  | 7               |
  | date the duty from a recurring template's start_date | 2               |
  | anchor retention to the earliest record, not latest  | 1               |
  | drop the date column from the dependency query       | 1               |
  | let a lapsed duty permit the delete                  | 1               |

The last two failed NOTHING at first. Every test above them hands refusal() a
date, which left the part that FINDS the date untested — the same unwired gap as
a helper whose caller can be reverted for free. The block at the bottom drives
the real dependency loop, and it is why those two are on the list at all.
"""
from __future__ import annotations

from datetime import date

import pytest

from services import party_erasure
from services.party_erasure import CUSTOMER, VENDOR, refusal

TODAY = date(2026, 9, 5)


# ── the refusal names a statute and a date ───────────────────────────────────

@pytest.mark.parametrize("party", [CUSTOMER, VENDOR])
def test_a_dated_record_gets_the_statute_and_the_lapse_date(party):
    text = refusal(party, latest_record_date="2025-07-14", today=TODAY)
    assert "Companies Act 2013" in text
    assert "s. 128(5)" in text
    assert "31 March 2034" in text
    assert "has linked accounting records" not in text, "the old sentence survived"


@pytest.mark.parametrize("party", [CUSTOMER, VENDOR])
def test_the_refusal_still_says_what_to_do_instead(party):
    assert "eactivate" in refusal(party, latest_record_date="2025-07-14", today=TODAY)


def test_the_party_is_named_in_its_own_words():
    assert "customer" in refusal(CUSTOMER, latest_record_date="2025-07-14", today=TODAY)
    assert "vendor" in refusal(VENDOR, latest_record_date="2025-07-14", today=TODAY)


# ── the answer changes on a date, which the old sentence could not ───────────

def test_the_latest_record_decides_not_the_earliest():
    """Retention runs from the financial year of the record, so the NEWEST one
    is held longest. Anchoring to the oldest would release the party while a
    later record is still under duty."""
    early = refusal(CUSTOMER, latest_record_date="2019-05-01", today=TODAY)
    late = refusal(CUSTOMER, latest_record_date="2025-07-14", today=TODAY)
    assert "31 March 2028" in early
    assert "31 March 2034" in late


def test_a_lapsed_duty_changes_the_reason_but_not_the_answer():
    """The question #126 left open. Retention lapsing means the law no longer
    requires the record kept — not that nothing else needs it."""
    text = refusal(CUSTOMER, latest_record_date="2000-04-02", today=TODAY)
    assert "has lapsed" in text
    assert "no law now requires them kept" in text
    assert "still cannot be permanently deleted" in text, (
        "a lapsed duty was allowed to authorise the delete")
    assert "cascade" in text


def test_a_live_duty_and_a_lapsed_one_do_not_read_the_same():
    live = refusal(CUSTOMER, latest_record_date="2025-07-14", today=TODAY)
    lapsed = refusal(CUSTOMER, latest_record_date="2000-04-02", today=TODAY)
    assert live != lapsed


# ── undated blockers get the true reason, not an invented statute ────────────

def test_an_undated_blocker_is_reported_as_referential():
    """A recurring template is a SCHEDULE, not an accounting record. Dating a
    statutory duty from it would anchor retention to a diary entry."""
    text = refusal(CUSTOMER, latest_record_date=None, today=TODAY)
    assert "no accounting date" in text
    assert "Companies Act" not in text, "a statute was invoked with no date behind it"


def test_an_unparseable_date_is_treated_as_undated_rather_than_guessed():
    for bad in ("not-a-date", "", "2025-13-45"):
        text = refusal(CUSTOMER, latest_record_date=bad, today=TODAY)
        assert "no accounting date" in text, f"{bad!r} was parsed into something"


# ── the dependency tables carry the right date column ────────────────────────

def test_every_dated_dependency_table_names_a_real_date_column():
    """The columns differ per table (invoice_date, receipt_date, bill_date...)
    and reading the wrong one anchors retention to the wrong year. The names are
    checked against the live schema by test_backend_columns_exist_pg; this
    checks the pairing has not been shuffled."""
    from routers.customers import _DEPENDENCY_TABLES
    from routers.vendors import _VENDOR_DEPENDENCY_TABLES

    expected = {
        "client_sales_invoices": "invoice_date",
        "receipts": "receipt_date",
        "credit_notes": "credit_note_date",
        "recurring_invoice_templates": None,
        "purchase_bills": "bill_date",
        "purchase_payments": "payment_date",
        "debit_notes": "debit_note_date",
        "purchase_credit_notes": "credit_note_date",
    }
    for _label, table, date_col in [*_DEPENDENCY_TABLES, *_VENDOR_DEPENDENCY_TABLES]:
        assert table in expected, f"{table} is a new dependency with no date decision"
        assert date_col == expected[table], f"{table} is dated from {date_col!r}"


def test_the_recurring_template_is_deliberately_undated():
    """Not an oversight. Its start_date is when billing begins, not when a
    transaction happened."""
    from routers.customers import _DEPENDENCY_TABLES
    dates = {t: d for _l, t, d in _DEPENDENCY_TABLES}
    assert dates["recurring_invoice_templates"] is None


# ── the client delete is NOT an erasure path, and must not claim to be ───────

def test_the_client_delete_is_a_soft_delete_and_gets_no_retention_refusal():
    """#129 asked for all three. The client delete only sets deleted_at — it
    hides a client and destroys nothing — so a retention refusal there would
    tell a CA they may not HIDE a client until 2034, which is false. Erasure
    refusals belong on paths that erase."""
    import inspect
    from repositories.client_repository import ClientRepository

    source = inspect.getsource(ClientRepository.soft_delete)
    assert "deleted_at" in source
    assert ".delete()" not in source, (
        "client soft_delete now destroys rows — it has become an erasure path "
        "and needs the retention refusal after all")

    import routers.clients as clients
    assert "party_erasure" not in inspect.getsource(clients), (
        "a retention refusal was added to a path that does not erase")


# ── the dependency loop itself, not just the sentence ────────────────────────
#
# Everything above tests refusal() with a date handed to it. That left the part
# that FINDS the date untested: reverting the query to select("id") alone, or
# taking the earliest record instead of the latest, failed nothing. These drive
# the real loop.

class _Result:
    def __init__(self, data): self.data = data


class _Query:
    def __init__(self, rows, seen, table):
        self._rows, self._seen, self._table = rows, seen, table
    def select(self, columns, *a, **k):
        self._seen[self._table] = columns
        return self
    def eq(self, *a, **k): return self
    def is_(self, *a, **k): return self
    def execute(self): return _Result(self._rows)


class _DB:
    def __init__(self, tables, seen): self._tables, self._seen = tables, seen
    def table(self, name):
        return _Query(self._tables.get(name, []), self._seen, name)


def test_the_dependency_query_actually_asks_for_the_date_column():
    """Reverting the select to "id" alone leaves every sentence test passing and
    the refusal permanently undated."""
    from routers.customers import _customer_dependencies
    seen: dict[str, str] = {}
    _customer_dependencies(_DB({}, seen), "c1", 0)
    assert seen["client_sales_invoices"] == "id, invoice_date"
    assert seen["receipts"] == "id, receipt_date"
    assert seen["credit_notes"] == "id, credit_note_date"
    assert seen["recurring_invoice_templates"] == "id", (
        "the undated table started asking for a date")


def test_the_vendor_dependency_query_asks_for_its_own_date_columns():
    from routers.vendors import _vendor_dependencies
    seen: dict[str, str] = {}
    _vendor_dependencies(_DB({}, seen), "v1", 0)
    assert seen["purchase_bills"] == "id, bill_date"
    assert seen["purchase_payments"] == "id, payment_date"
    assert seen["debit_notes"] == "id, debit_note_date"
    assert seen["purchase_credit_notes"] == "id, credit_note_date"


def test_the_loop_keeps_the_latest_date_across_every_table():
    """Across tables, not just within one — the newest record may be a receipt
    while the oldest is an invoice."""
    from routers.customers import _customer_dependencies
    deps = _customer_dependencies(_DB({
        "client_sales_invoices": [{"id": "1", "invoice_date": "2019-05-01"},
                                  {"id": "2", "invoice_date": "2021-08-09"}],
        "receipts": [{"id": "3", "receipt_date": "2025-07-14"}],
        "credit_notes": [{"id": "4", "credit_note_date": "2020-01-01"}],
    }, {}), "c1", 0)
    assert deps["latest_record_date"] == "2025-07-14"
    assert deps["has_any"] is True


def test_an_undated_row_does_not_become_the_anchor():
    from routers.customers import _customer_dependencies
    deps = _customer_dependencies(_DB({
        "client_sales_invoices": [{"id": "1", "invoice_date": None},
                                  {"id": "2", "invoice_date": "2021-08-09"}],
        "recurring_invoice_templates": [{"id": "9"}],
    }, {}), "c1", 0)
    assert deps["latest_record_date"] == "2021-08-09"


def test_a_template_only_blocker_leaves_the_date_unset():
    """It still blocks — but referentially, with no statutory clock."""
    from routers.customers import _customer_dependencies
    deps = _customer_dependencies(
        _DB({"recurring_invoice_templates": [{"id": "9"}]}, {}), "c1", 0)
    assert deps["has_any"] is True
    assert deps["latest_record_date"] is None


def test_an_opening_balance_alone_blocks_with_no_date():
    from routers.vendors import _vendor_dependencies
    deps = _vendor_dependencies(_DB({}, {}), "v1", 50_000)
    assert deps["has_any"] is True
    assert deps["latest_record_date"] is None
