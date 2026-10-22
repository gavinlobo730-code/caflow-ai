"""A stock movement whose ledger row is refused does not leave the item's cache, or the general ledger, ahead of the stock ledger
(ledger POST-A-321).

THE DEFECT
    `_insert_and_cache` claims `service_catalogue.stock_version` and writes the item's cached quantity and average cost FIRST
    (the compare-and-set that guards two concurrent movements) and only then inserts the ledger row. If the insert failed (a
    constraint, a refusal, a network error) the cache had moved and the ledger had not; every caller swallows the failure by
    design (an invoice must still issue), so the stock screen showed a movement the ledger never recorded, until the next
    successful movement happened to chain from the ledger's last row and overwrite it. And `seed_opening_balances_batch` posts
    its Dr Inventory / Cr Opening Balance Equity journal BEFORE its ledger insert (so each row can carry its journal's id), so a
    refused insert left the general ledger carrying inventory the stock ledger lacks: the tie-out the stock ledger exists to
    protect.

WHAT IS HELD (no database; the in-memory double)
    * a refused ledger insert puts the item's cache back to the ledger's last row (quantity and average cost), and the
      version moves forward, never back; an item with no ledger row has a cache of nothing;
    * the restore is a compare-and-set on the version the failed movement wrote: a movement that has since claimed the item has
      already rewritten the cache from the ledger and is left alone;
    * a restore that itself fails is reported (`_insert_and_cache.restore_cache`) and the original failure still reaches the
      caller;
    * a batch whose ledger insert is refused reverses the opening-stock journal it posted, for each client, dated the entry's
      own day, so the general ledger nets to nothing again; a client whose journal was never posted has nothing to reverse
      (nothing is attempted, so no reversal failure is reported for it); a reversal that fails is reported and does not stop
      the others;
    * a failure the client SAW is not always a failure the database HAD: an insert that committed and then failed on the way
      back leaves the journals standing (the ledger holds the rows) and the cache written, and a batch that cannot ask the
      ledger what landed reverses nothing and says so.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

import domain.inventory_service as inventory_service
from domain.inventory_service import record_stock_in, seed_opening_balances_batch
from tests.e2e_harness import FakeDB, account_balance

FIRM = "firm-inv-321"
CLIENT = "client-inv-321"
CLIENT_B = "client-inv-321-b"


class _Refused(Exception):
    pass


class _Proxy:
    """The request's client with the stock ledger's INSERT refused (and, optionally, a hook that runs just before the refusal,
    standing in for a concurrent movement, or an UPDATE of the catalogue that fails)."""

    def __init__(self, inner, *, before_refusal=None, fail_catalogue_version=None, commit_then_fail=False, fail_ledger_reads=False):
        self._inner, self._before, self._fail_version = inner, before_refusal, fail_catalogue_version
        self._commit_then_fail, self._fail_reads = commit_then_fail, fail_ledger_reads

    def table(self, name):
        if name == "inventory_stock_ledger":
            owner = self

            class Ledger:
                def __getattr__(self, attr):
                    if attr == "insert":
                        def refuse(*a, **k):
                            if owner._before:
                                owner._before()
                            if owner._commit_then_fail:                  # the database took the rows; the client never heard
                                owner._inner.table(name).insert(*a, **k).execute()
                                raise _Refused("connection lost after the insert committed")
                            raise _Refused("ledger insert refused")
                        return refuse
                    if attr == "select" and owner._fail_reads:
                        def unreadable(*a, **k):
                            raise _Refused("ledger unreadable")
                        return unreadable
                    return getattr(owner._inner.table(name), attr)
            return Ledger()
        if name == "service_catalogue" and self._fail_version is not None:
            owner = self
            query = self._inner.table(name)

            class Catalogue:
                def update(self, payload, *a, **k):
                    if payload.get("stock_version") == owner._fail_version:
                        raise _Refused("catalogue update refused")
                    return query.update(payload, *a, **k)

                def __getattr__(self, attr):
                    return getattr(query, attr)
            return Catalogue()
        return self._inner.table(name)

    def __getattr__(self, attr):
        return getattr(self._inner, attr)


@pytest.fixture()
def db(monkeypatch):
    fake = FakeDB()
    import core.supabase_client as sc
    monkeypatch.setattr(sc, "get_supabase", lambda: fake)
    return fake


def _item(db, item_id=None, client_id=CLIENT):
    item_id = item_id or str(uuid.uuid4())
    db.seed("service_catalogue", {"id": item_id, "firm_id": FIRM, "client_id": client_id, "name": f"Item {item_id[:6]}",
                                  "kind": "good", "stock_qty_units": "0", "avg_cost_paise": 0})
    return item_id


def _chart(db, client_id=CLIENT):
    inv = db.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": client_id, "system_account_key": "inventory",
                                        "account_name": "Inventory", "is_active": True})["id"]
    obe = db.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": client_id, "system_account_key": None,
                                        "account_name": "Opening Balance Equity", "is_active": True})["id"]
    return inv, obe


def _stock_in(client, item_id, qty, cost, date="2026-04-01"):
    return record_stock_in(client, firm_id=FIRM, client_id=CLIENT, service_catalogue_id=item_id, movement_date=date,
                           quantity=Decimal(qty), total_cost_paise=cost, movement_type="purchase",
                           source_type="purchase_bill", source_id=str(uuid.uuid4()), reference_no="B-1")


def _cache(db, item_id):
    row = next(r for r in db.rows("service_catalogue") if r["id"] == item_id)
    return row["stock_qty_units"], row["avg_cost_paise"], row.get("stock_version")


# ── the cache ────────────────────────────────────────────────────────────────────

def test_a_refused_insert_puts_the_cache_back_to_the_ledgers_last_row(db):
    item = _item(db)
    _stock_in(db, item, "10", 1_000_00)
    before = _cache(db, item)
    assert before[0] == "10"
    with pytest.raises(_Refused):
        _stock_in(_Proxy(db), item, "5", 750_00, date="2026-04-02")
    qty, avg, version = _cache(db, item)
    assert (qty, avg) == (before[0], before[1]), "the cache still carries the movement the ledger refused"
    assert len(db.rows("inventory_stock_ledger")) == 1
    assert version == before[2] + 2, (before, version)         # claimed (+1) then restored one further on (+2): only ever forward


def test_a_first_movement_that_is_refused_leaves_a_cache_of_nothing(db):
    item = _item(db)
    with pytest.raises(_Refused):
        _stock_in(_Proxy(db), item, "4", 400_00)
    qty, avg, _version = _cache(db, item)
    assert (qty, avg) == ("0", 0) and db.rows("inventory_stock_ledger") == []


def test_a_movement_that_claimed_the_item_meanwhile_is_not_overwritten(db):
    """The restore is a compare-and-set on the version the failed movement wrote. A concurrent movement that claimed the item
    after it has already rewritten the cache from the ledger, and a restore that wrote anyway would undo it."""
    item = _item(db)
    _stock_in(db, item, "10", 1_000_00)

    def concurrent_movement():
        row = next(r for r in db.rows("service_catalogue") if r["id"] == item)
        row.update({"stock_qty_units": "99", "avg_cost_paise": 12345, "stock_version": int(row["stock_version"]) + 1})

    with pytest.raises(_Refused):
        _stock_in(_Proxy(db, before_refusal=concurrent_movement), item, "5", 750_00, date="2026-04-02")
    qty, avg, _version = _cache(db, item)
    assert (qty, avg) == ("99", 12345)


def test_a_restore_that_fails_is_reported_and_the_original_failure_still_reaches_the_caller(db, monkeypatch):
    item = _item(db)
    _stock_in(db, item, "10", 1_000_00)
    claimed = _cache(db, item)[2] + 1
    reported = []
    monkeypatch.setattr(inventory_service, "capture_posting_failure", lambda exc, **ctx: reported.append((str(exc), ctx)))
    with pytest.raises(_Refused, match="ledger insert refused"):
        _stock_in(_Proxy(db, fail_catalogue_version=claimed + 1), item, "5", 750_00, date="2026-04-02")
    assert [ctx["operation"] for _msg, ctx in reported] == ["_insert_and_cache.restore_cache"], reported
    assert reported[0][1]["service_catalogue_id"] == item


def test_a_successful_movement_is_unchanged(db):
    item = _item(db)
    _stock_in(db, item, "10", 1_000_00)
    _stock_in(db, item, "5", 750_00, date="2026-04-02")
    qty, avg, version = _cache(db, item)
    assert qty == "15" and len(db.rows("inventory_stock_ledger")) == 2 and version == 2


# ── the opening-stock batch ──────────────────────────────────────────────────────

def _batch_rows(db, client_id, n=2):
    rows = []
    for _ in range(n):
        item = _item(db, client_id=client_id)
        rows.append({"id": item, "client_id": client_id, "kind": "good", "opening_qty_units": "10",
                     "opening_cost_paise": 100_00, "created_at": "2026-04-01T00:00:00Z"})
    return rows


def _entries(db, client_id):
    return [e for e in db.rows("journal_entries") if e.get("client_id") == client_id]


def test_a_refused_batch_insert_reverses_the_journal_it_posted_for_each_client(db, monkeypatch):
    reported = []
    monkeypatch.setattr(inventory_service, "capture_posting_failure", lambda exc, **ctx: reported.append(ctx.get("operation")))
    inv_a, obe_a = _chart(db, CLIENT)
    inv_b, obe_b = _chart(db, CLIENT_B)
    rows = _batch_rows(db, CLIENT) + _batch_rows(db, CLIENT_B)

    seed_opening_balances_batch(_Proxy(db), firm_id=FIRM, created_by="user-1", rows=rows)       # never raises

    for client_id, inv, obe in ((CLIENT, inv_a, obe_a), (CLIENT_B, inv_b, obe_b)):
        entries = _entries(db, client_id)
        assert len(entries) == 2, entries                                  # the opening entry and its reversal
        assert sorted(bool(e.get("reversal_of")) for e in entries) == [False, True]
        original = next(e for e in entries if not e.get("reversal_of"))
        reversal = next(e for e in entries if e.get("reversal_of"))
        assert reversal["reversal_of"] == original["id"]
        # dated the entry's own day (the rows are stamped 1 April 2026), not the day the failure happened
        assert original["entry_date"] == reversal["entry_date"] == "2026-04-01", (original["entry_date"], reversal["entry_date"])
        assert account_balance(db, inv) == 0 and account_balance(db, obe) == 0     # the general ledger carries nothing
    assert db.rows("inventory_stock_ledger") == []
    assert reported == ["seed_opening_balances_batch.ledger_insert"], reported


def test_a_client_whose_journal_was_never_posted_has_nothing_to_reverse(db, monkeypatch):
    reported = []
    monkeypatch.setattr(inventory_service, "capture_posting_failure", lambda exc, **ctx: reported.append(ctx.get("operation")))
    inv_a, obe_a = _chart(db, CLIENT)                 # CLIENT_B has no chart of accounts: its journal degrades to None
    rows = _batch_rows(db, CLIENT) + _batch_rows(db, CLIENT_B)
    seed_opening_balances_batch(_Proxy(db), firm_id=FIRM, created_by="user-1", rows=rows)
    assert len(_entries(db, CLIENT)) == 2 and _entries(db, CLIENT_B) == []
    assert account_balance(db, inv_a) == 0
    # nothing was ATTEMPTED for the client with no journal: a reversal of "no entry" would be reported as a failure. (The
    # missing chart is itself reported once, by the posting of the journal, which is the documented degrade.)
    assert "seed_opening_balances_batch.reverse_journal" not in reported, reported
    assert reported.count("seed_opening_balances_batch.ledger_insert") == 1 and reported.count("post_opening_stock_journal_entry") == 1, reported


def test_one_reversal_that_fails_is_reported_and_the_others_still_run(db, monkeypatch):
    reported = []
    monkeypatch.setattr(inventory_service, "capture_posting_failure", lambda exc, **ctx: reported.append(ctx.get("operation")))
    inv_a, _ = _chart(db, CLIENT)
    inv_b, _ = _chart(db, CLIENT_B)
    rows = _batch_rows(db, CLIENT) + _batch_rows(db, CLIENT_B)

    from services.phase2_journal_service import phase2_journal_service
    real = phase2_journal_service.reverse_entry
    calls = []

    def flaky(db_, firm_id, entry_id, reversal_date, **kwargs):
        calls.append(entry_id)
        if len(calls) == 1:
            raise _Refused("reversal refused")
        return real(db_, firm_id, entry_id, reversal_date, **kwargs)

    monkeypatch.setattr(phase2_journal_service, "reverse_entry", flaky)
    seed_opening_balances_batch(_Proxy(db), firm_id=FIRM, created_by="user-1", rows=rows)
    assert len(calls) == 2, calls                                          # both were attempted
    assert reported.count("seed_opening_balances_batch.reverse_journal") == 1, reported
    balances = sorted([account_balance(db, inv_a), account_balance(db, inv_b)])
    assert balances[0] == 0 and balances[1] == 200_00                      # one client reversed, the one that failed to reverse is reported


def test_a_batch_that_succeeds_keeps_its_journals(db):
    inv, obe = _chart(db, CLIENT)
    seed_opening_balances_batch(db, firm_id=FIRM, created_by="user-1", rows=_batch_rows(db, CLIENT, n=3))
    assert len(_entries(db, CLIENT)) == 1 and len(db.rows("inventory_stock_ledger")) == 3
    assert account_balance(db, inv) == 300_00 and account_balance(db, obe) == -300_00


def test_a_batch_whose_insert_committed_before_the_client_saw_it_fail_keeps_its_journals_and_writes_the_cache(db, monkeypatch):
    reported = []
    monkeypatch.setattr(inventory_service, "capture_posting_failure", lambda exc, **ctx: reported.append(ctx.get("operation")))
    inv, obe = _chart(db, CLIENT)
    rows = _batch_rows(db, CLIENT, n=2)
    seed_opening_balances_batch(_Proxy(db, commit_then_fail=True), firm_id=FIRM, created_by="user-1", rows=rows)
    assert len(db.rows("inventory_stock_ledger")) == 2                       # the database has the rows
    assert len(_entries(db, CLIENT)) == 1                                    # so the journal stands: no reversal
    assert account_balance(db, inv) == 200_00 and account_balance(db, obe) == -200_00
    assert [_cache(db, r["id"])[:2] for r in rows] == [("10", 10_00)] * 2   # and the cache is written, as after any insert
    assert reported == ["seed_opening_balances_batch.ledger_insert"], reported


def test_a_batch_that_cannot_ask_the_ledger_what_landed_reverses_nothing_and_says_so(db, monkeypatch):
    reported = []
    monkeypatch.setattr(inventory_service, "capture_posting_failure", lambda exc, **ctx: reported.append(ctx.get("operation")))
    inv, obe = _chart(db, CLIENT)
    rows = _batch_rows(db, CLIENT, n=2)
    seed_opening_balances_batch(_Proxy(db, fail_ledger_reads=True), firm_id=FIRM, created_by="user-1", rows=rows)
    assert len(_entries(db, CLIENT)) == 1 and account_balance(db, inv) == 200_00     # neither reversed nor left unreported
    assert reported == ["seed_opening_balances_batch.ledger_insert", "seed_opening_balances_batch.ledger_probe"], reported
    assert [_cache(db, r["id"])[0] for r in rows] == ["0", "0"]
