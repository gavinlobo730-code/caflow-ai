"""
POST /api/customers/bulk — batch customer import (CSV upload).

Replaces the frontend's N-sequential-POST loop (each of which re-ran
create_customer's whole active-customer dedup SELECT) with ONE dedup-snapshot
fetch and ONE batch insert. Covers:
  * N valid new customers -> all created via a SINGLE insert call (not N).
  * A customer that duplicate-matches an EXISTING DB row (by GSTIN) -> reported
    as a duplicate, not inserted.
  * Two customers that duplicate each other WITHIN the same batch (same GSTIN)
    -> only the first is created, the second reported as a duplicate.
  * A malformed item (missing a required field) -> reported in errors, the rest
    of the batch still succeeds.
  * Opening balance on a bulk-created customer triggers post_opening_balances,
    same as the single-row path, with per-row rollback isolation on failure.
"""
import routers.customers as cust
import services.opening_balance_service as obs
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa, coa_id, account_balance

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "id": "internal-uid",
          "email": "ca@firma.test", "role": "Partner"}
GSTIN_A = "27AAAAA0000A1Z5"
GSTIN_B = "27BBBBB0000B1Z5"


class CountingDB(FakeDB):
    """FakeDB that records every insert() call made against a given table, so
    tests can assert the batch endpoint issues ONE insert, not N."""

    def __init__(self):
        super().__init__()
        self.insert_calls: dict[str, list] = {}

    def table(self, name):
        q = super().table(name)
        orig_insert = q.insert

        def counting_insert(payload, **kw):
            self.insert_calls.setdefault(name, []).append(payload)
            return orig_insert(payload, **kw)

        q.insert = counting_insert
        return q


def _setup(monkeypatch, db=None, mods=None):
    db = db if db is not None else FakeDB()
    wire_e2e(monkeypatch, db, mods or [cust])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": GSTIN_A})
    return db


def _bulk(customers, caller=CALLER):
    return cust.bulk_create_customers(cust.CustomerBulkIn(customers=customers), caller)


# ── N valid rows -> one insert call ──────────────────────────────────────────

def test_bulk_all_valid_creates_all_with_single_insert_call(monkeypatch):
    db = _setup(monkeypatch, db=CountingDB())
    rows = [{"client_id": "CLI", "name": f"Customer {i}"} for i in range(5)]

    res = _bulk(rows)

    assert res["success"] is True
    assert len(res["data"]["created"]) == 5
    assert res["data"]["duplicates"] == []
    assert res["data"]["errors"] == []
    # Exactly one insert() call against "customers", carrying all 5 rows.
    assert len(db.insert_calls.get("customers", [])) == 1
    assert len(db.insert_calls["customers"][0]) == 5
    assert len(db.rows("customers")) == 5


# ── duplicate against an existing DB row (by GSTIN) ──────────────────────────

def test_bulk_duplicate_against_existing_db_row_not_inserted(monkeypatch):
    db = _setup(monkeypatch, db=CountingDB())
    existing = db.seed("customers", {
        "firm_id": FIRM, "client_id": "CLI", "name": "Acme Existing",
        "gstin": GSTIN_A, "is_active": True, "opening_balance_paise": 0,
    })

    res = _bulk([{"client_id": "CLI", "name": "Acme Reimport", "gstin": GSTIN_A}])

    assert res["success"] is True
    assert res["data"]["created"] == []
    assert len(res["data"]["duplicates"]) == 1
    dup = res["data"]["duplicates"][0]
    assert dup["index"] == 0
    assert dup["existing_id"] == existing["id"]
    # No insert was even attempted — the only row was a duplicate.
    assert db.insert_calls.get("customers", []) == []
    assert len(db.rows("customers")) == 1  # unchanged


# ── two duplicates within the same batch ─────────────────────────────────────

def test_bulk_within_batch_duplicates_only_first_created(monkeypatch):
    db = _setup(monkeypatch, db=CountingDB())

    res = _bulk([
        {"client_id": "CLI", "name": "Acme First", "gstin": GSTIN_A},
        {"client_id": "CLI", "name": "Acme Second", "gstin": GSTIN_A},
    ])

    assert res["success"] is True
    assert len(res["data"]["created"]) == 1
    assert res["data"]["created"][0]["name"] == "Acme First"
    assert len(res["data"]["duplicates"]) == 1
    dup = res["data"]["duplicates"][0]
    assert dup["index"] == 1
    assert dup["existing_id"] == res["data"]["created"][0]["id"]
    # Only the first row was ever inserted.
    assert len(db.insert_calls["customers"][0]) == 1
    assert len(db.rows("customers")) == 1


# ── malformed item reported as an error, rest of batch still succeeds ───────

def test_bulk_malformed_item_reported_as_error_rest_succeeds(monkeypatch):
    db = _setup(monkeypatch, db=CountingDB())

    res = _bulk([
        {"client_id": "CLI", "name": "Good One"},
        {"client_id": "CLI"},  # missing required "name" -> pydantic ValidationError
        {"client_id": "CLI", "name": "Good Two"},
    ])

    assert res["success"] is True
    assert len(res["data"]["errors"]) == 1
    assert res["data"]["errors"][0]["index"] == 1
    assert res["data"]["errors"][0]["error"]

    created_names = {c["name"] for c in res["data"]["created"]}
    assert created_names == {"Good One", "Good Two"}
    # The malformed item never reaches the insert payload.
    assert len(db.insert_calls["customers"][0]) == 2


# ── opening balance triggers post_opening_balances, same as single-row path ─

def _setup_with_coa(monkeypatch, db=None, include_obe=True):
    db = db if db is not None else FakeDB()
    wire_e2e(monkeypatch, db, [cust, obs])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "financial_year_start": "2025-04-01"})
    seed_standard_coa(db, FIRM, "CLI")
    if include_obe:
        db.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": "CLI",
                                       "account_name": "Opening Balance Equity", "is_active": True})
    return db


def test_bulk_opening_balance_autoposts_to_gl(monkeypatch):
    db = _setup_with_coa(monkeypatch)

    res = _bulk([{"client_id": "CLI", "name": "Acme", "opening_balance_paise": 500_000}])

    assert res["success"] is True
    assert len(res["data"]["created"]) == 1
    assert account_balance(db, coa_id(db, FIRM, "ar")) == 500_000
    assert obs.opening_balance_status(FIRM, "CLI")["needs_posting"] is False


def test_bulk_opening_balance_sync_failure_rolls_back_only_that_row(monkeypatch):
    # Opening Balance Equity contra account intentionally missing -> the
    # opening-balance sync for the row WITH an opening balance raises, and only
    # that row must be rolled back; the zero-opening-balance row is untouched.
    db = _setup_with_coa(monkeypatch, include_obe=False)

    res = _bulk([
        {"client_id": "CLI", "name": "BadOpeningBalance", "opening_balance_paise": 500_000},
        {"client_id": "CLI", "name": "GoodNoOpeningBalance", "opening_balance_paise": 0},
    ])

    assert res["success"] is True
    created_names = {c["name"] for c in res["data"]["created"]}
    assert created_names == {"GoodNoOpeningBalance"}
    assert len(res["data"]["errors"]) == 1
    assert res["data"]["errors"][0]["name"] == "BadOpeningBalance"

    remaining_names = {c["name"] for c in db.rows("customers")}
    assert "BadOpeningBalance" not in remaining_names
    assert "GoodNoOpeningBalance" in remaining_names
