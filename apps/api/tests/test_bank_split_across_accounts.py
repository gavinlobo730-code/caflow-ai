"""
The queue can tell a SPLIT line from an uncoded one.

WHY THIS EXISTS
    Splitting one bank line across several GL accounts has been buildable since
    migration 256 — the table, an atomic replace RPC, domain validation, a
    service, both endpoints and even a frontend client method. Nothing in the
    UI ever called it. There were zero call sites.

    Wiring the screen to it needs one thing the queue did not report: whether a
    row is already split. A split row carries a NULL category and a NULL
    account_id, exactly like an untouched one, so without this the screen would
    offer a ledger picker over an allocation that was already made — and the
    first ledger picked would replace the split with a single account, silently.

WHAT IS ASSERTED
    1. A split row comes back with is_split, split_count and the legs
       themselves (account and amount), so the panel can show the allocation
       rather than a count. "Split 3 ways" is not something a reviewer can
       check.
    2. A row with no split is NOT marked — the negative half, without which
       assertion 1 is satisfied by marking everything.
    3. The lookup is ONE query for the page, not one per row. Fifty
       cross-region round trips to discover that forty-eight rows have no
       split is the read shape CLAUDE.md rules out, and it is invisible in any
       test that only checks the values.
    4. It survives a split table that cannot be read: the reader loses the
       allocation summary, not the queue.

NEGATIVE CONTROLS RUN
    * removing the _attach_splits call from queue() fails 1 and 3.
    * marking every row (`is_split = True`) fails 2.
    * moving the lookup inside the per-row loop fails 3 (5 queries, not 1).
    * removing the try/except fails 4.
"""
import pytest

import services.bank_matching_service as bms
from services.bank_matching_service import bank_matching_service as svc
from tests.test_bank_matching import FakeDB, FIRM, CLIENT, _seed_txn


@pytest.fixture(autouse=True)
def _silence(monkeypatch):
    monkeypatch.setattr(bms.timeline_service, "log", lambda *a, **k: None)
    yield


def _seed_split(db, txn_id, account_id, amount, seq):
    db.store.setdefault("bank_transaction_splits", []).append({
        "id": f"s-{txn_id}-{seq}", "firm_id": FIRM, "bank_transaction_id": txn_id,
        "account_id": account_id, "amount_paise": amount, "narration": None,
        "sequence_no": seq,
    })


class CountingDB(FakeDB):
    """FakeDB that counts reads of one table, so "one query for the page" is
    an assertion rather than a hope."""

    def __init__(self):
        super().__init__()
        self.reads: dict[str, int] = {}

    def table(self, name):
        self.reads[name] = self.reads.get(name, 0) + 1
        return super().table(name)


def _five_rows(db):
    for i in range(5):
        _seed_txn(db, id=f"t{i}", transaction_date=f"2026-04-1{i}",
                  debit_paise=472000, credit_paise=0)


def test_a_split_row_carries_its_legs():
    db = CountingDB()
    _five_rows(db)
    _seed_split(db, "t2", "acc-rent", 400000, 1)
    _seed_split(db, "t2", "acc-maint", 50000, 2)
    _seed_split(db, "t2", "acc-park", 22000, 3)

    rows = {r["id"]: r for r in svc.queue(db, FIRM, CLIENT, "for_review", limit=50)}
    split = rows["t2"]
    assert split["is_split"] is True
    assert split["split_count"] == 3
    assert [(s["account_id"], s["amount_paise"]) for s in split["splits"]] == [
        ("acc-rent", 400000), ("acc-maint", 50000), ("acc-park", 22000)]
    # And they still tie to what the bank moved — the whole invariant of a split.
    assert sum(s["amount_paise"] for s in split["splits"]) == split["debit_paise"]


def test_an_unsplit_row_is_not_marked():
    """The negative half. Marking every row satisfies the test above."""
    db = CountingDB()
    _five_rows(db)
    _seed_split(db, "t2", "acc-rent", 400000, 1)
    _seed_split(db, "t2", "acc-maint", 72000, 2)

    rows = {r["id"]: r for r in svc.queue(db, FIRM, CLIENT, "for_review", limit=50)}
    for rid in ("t0", "t1", "t3", "t4"):
        assert rows[rid]["is_split"] is False, rid
        assert rows[rid]["splits"] == []
        assert rows[rid]["split_count"] == 0


def test_the_page_costs_one_split_query_not_one_per_row():
    """CLAUDE.md's reporting rule applied to the queue: what crosses the wire
    is proportional to the ANSWER. Both apps run in Singapore against a Mumbai
    Postgres, so a per-row lookup is fifty round trips to learn that
    forty-eight rows have nothing."""
    db = CountingDB()
    _five_rows(db)
    _seed_split(db, "t0", "acc-rent", 400000, 1)
    _seed_split(db, "t0", "acc-maint", 72000, 2)

    svc.queue(db, FIRM, CLIENT, "for_review", limit=50)
    assert db.reads.get("bank_transaction_splits") == 1, (
        f"{db.reads.get('bank_transaction_splits')} split queries for a 5-row page")


def test_an_unreadable_split_table_costs_the_summary_not_the_queue():
    """Best effort by design. A CA whose splits cannot be read still has to be
    able to work the rest of the statement."""
    db = CountingDB()
    _five_rows(db)

    class _Boom:
        def __getattr__(self, _n):
            raise RuntimeError("bank_transaction_splits unavailable")

    real_table = db.table

    def table(name):
        if name == "bank_transaction_splits":
            db.reads[name] = db.reads.get(name, 0) + 1
            return _Boom()
        return real_table(name)

    db.table = table
    rows = svc.queue(db, FIRM, CLIENT, "for_review", limit=50)
    assert len(rows) == 5
    assert all(r["is_split"] is False for r in rows)


def test_the_fake_actually_reaches_the_split_table():
    """Guard against the test above passing for the wrong reason.

    _attach_splits swallows everything the split lookup raises. If the double
    did not support `.in_` or `.order` at all, every assertion here would still
    pass with is_split False everywhere — including, silently,
    test_an_unsplit_row_is_not_marked. So: prove the query runs and returns.
    """
    db = CountingDB()
    _five_rows(db)
    _seed_split(db, "t1", "acc-rent", 472000, 1)
    _seed_split(db, "t1", "acc-maint", 0, 2)
    rows = {r["id"]: r for r in svc.queue(db, FIRM, CLIENT, "for_review", limit=50)}
    assert rows["t1"]["split_count"] == 2, (
        "the split query returned nothing — the double is not modelling in_/order, "
        "and _attach_splits' except is hiding it")
