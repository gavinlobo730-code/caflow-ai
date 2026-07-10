"""
POST /api/vendors/bulk — collapses the CSV-import UI's N-sequential-POST loop
(one HTTP round-trip per vendor row) into a single request.

vendors.py has no proactive duplicate pre-check (unlike customers.py) — it
just attempts the insert and lets a DB-level unique-constraint violation
surface the friendly "A vendor with this GSTIN or PAN already exists for this
client." message. A batch insert is all-or-nothing in Postgres, so this
harness simulates that DB behaviour: an insert into "vendors" (batch or
single) raises a duplicate-key error if any row in the payload collides on
(firm_id, client_id, gstin) with an already-persisted row, and otherwise
inserts normally — same shape/semantics as test_tenant_isolation_phase4.py's
simulated duplicate-key error.
"""
import routers.vendors as ven
import services.opening_balance_service as obs
from models.parties import VendorIn
from tests import e2e_harness as eh
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa, coa_id, account_balance

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firma.test", "role": "Partner"}

GSTIN_A = "27AAAAA0000A1Z5"   # Maharashtra
GSTIN_B = "29ABCDE1234F1Z5"   # Karnataka — different registration

_real_execute = eh._Query.execute


def _execute_with_vendor_gstin_constraint(self):
    """Mirror a real Postgres unique-constraint violation for the harness:
    raise (persisting nothing from the offending call) if any row in this
    insert's payload collides on (firm_id, client_id, gstin) with an already
    -persisted vendor row. Applies to both batch and single-row inserts, so a
    batch insert containing one bad row fails whole, and the per-row fallback
    can isolate exactly that row."""
    if self.table == "vendors" and self._op == "insert":
        existing = self.db._tables.get("vendors", [])
        payload_list = self._payload if isinstance(self._payload, list) else [self._payload]
        for p in payload_list:
            gstin = p.get("gstin")
            if gstin and any(
                r.get("firm_id") == p.get("firm_id")
                and r.get("client_id") == p.get("client_id")
                and r.get("gstin") == gstin
                for r in existing
            ):
                raise RuntimeError(
                    'duplicate key value violates unique constraint "vendors_firm_client_gstin_key" (23505)'
                )
    return _real_execute(self)


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [ven, obs])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "financial_year_start": "2025-04-01"})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": "CLI",
                                  "account_name": "Opening Balance Equity", "is_active": True})
    monkeypatch.setattr(eh._Query, "execute", _execute_with_vendor_gstin_constraint)
    return db


def _bulk(vendors, caller=CALLER):
    return ven.create_vendors_bulk(ven.VendorBulkIn(vendors=vendors), caller)


# ── all-valid batch ───────────────────────────────────────────────────────────

def test_batch_of_valid_vendors_all_created(monkeypatch):
    db = _setup(monkeypatch)
    batch = [
        dict(client_id="CLI", name="Alpha Supplies"),
        dict(client_id="CLI", name="Bravo Traders", gstin=GSTIN_A),
        dict(client_id="CLI", name="Charlie & Co", gstin=GSTIN_B),
    ]
    res = _bulk(batch)
    assert res["success"] is True
    assert len(res["data"]["created"]) == 3
    assert res["data"]["duplicates"] == []
    assert res["data"]["errors"] == []
    assert len(db.rows("vendors")) == 3
    names = {v["name"] for v in res["data"]["created"]}
    assert names == {"Alpha Supplies", "Bravo Traders", "Charlie & Co"}


# ── GSTIN collision with an existing row ──────────────────────────────────────

def test_gstin_collision_with_existing_row_reported_as_duplicate(monkeypatch):
    db = _setup(monkeypatch)
    db.seed("vendors", {"firm_id": FIRM, "client_id": "CLI", "name": "Existing Co",
                        "gstin": GSTIN_A, "is_active": True, "opening_balance_paise": 0})
    assert len(db.rows("vendors")) == 1

    batch = [
        dict(client_id="CLI", name="Duplicate Co", gstin=GSTIN_A),   # collides
        dict(client_id="CLI", name="New Co", gstin=GSTIN_B),         # fine
    ]
    res = _bulk(batch)
    assert res["success"] is True
    assert len(res["data"]["created"]) == 1
    assert res["data"]["created"][0]["name"] == "New Co"
    assert len(res["data"]["duplicates"]) == 1
    dup = res["data"]["duplicates"][0]
    assert dup["index"] == 0
    assert dup["name"] == "Duplicate Co"
    assert dup["error"] == "A vendor with this GSTIN or PAN already exists for this client."
    assert res["data"]["errors"] == []
    # Existing row untouched; only the one non-colliding vendor was added.
    assert len(db.rows("vendors")) == 2
    assert any(v["name"] == "Existing Co" for v in db.rows("vendors"))
    assert not any(v["name"] == "Duplicate Co" for v in db.rows("vendors"))


# ── malformed item ────────────────────────────────────────────────────────────

def test_malformed_item_reported_as_error_rest_of_batch_succeeds(monkeypatch):
    db = _setup(monkeypatch)
    batch = [
        dict(client_id="CLI", name="Good Co"),
        dict(client_id="CLI"),          # missing required "name"
        dict(client_id="CLI", name="Also Good Co"),
    ]
    res = _bulk(batch)
    assert res["success"] is True
    assert len(res["data"]["created"]) == 2
    assert {v["name"] for v in res["data"]["created"]} == {"Good Co", "Also Good Co"}
    assert len(res["data"]["errors"]) == 1
    err = res["data"]["errors"][0]
    assert err["index"] == 1
    assert "name" in err["error"].lower()
    assert res["data"]["duplicates"] == []
    assert len(db.rows("vendors")) == 2


# ── opening balance auto-post ────────────────────────────────────────────────

def test_opening_balance_on_bulk_created_vendor_triggers_gl_post(monkeypatch):
    db = _setup(monkeypatch)
    batch = [
        dict(client_id="CLI", name="No Balance Co"),
        dict(client_id="CLI", name="Supplier Co", opening_balance_paise=200_000),
    ]
    res = _bulk(batch)
    assert res["success"] is True
    assert len(res["data"]["created"]) == 2
    # AP is a credit balance for a payable — post_opening_balances posts it negative.
    assert account_balance(db, coa_id(db, FIRM, "ap")) == -200_000
    assert obs.opening_balance_status(FIRM, "CLI")["needs_posting"] is False
