"""
POST /api/vendors/bulk — collapses the CSV-import UI's N-sequential-POST loop
(one HTTP round-trip per vendor row) into a single request.

vendors.py now has the SAME proactive app-level duplicate pre-check as
customers.py's bulk_create_customers (GSTIN, then PAN — CGST Act §25 / IT Act
§139A), added after discovering vendors previously had NO duplicate
protection at any layer: no app-level check, and no real DB unique
constraint either (confirmed against live migrations), so a retried/
re-uploaded vendor CSV silently created full duplicate vendor rows —
mirroring the purchase-bills bulk-import incident this fix was modeled on.
The insert-error classifier further down (_classify_db_error) is now a
pure defense-in-depth backstop for a constraint that doesn't currently
exist; this harness no longer needs to simulate one for the app-level-dedup
scenarios below.
"""
import routers.vendors as ven
import services.opening_balance_service as obs
from models.parties import VendorIn
from tests import e2e_harness as eh
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa, coa_id, account_balance

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firma.test", "role": "Partner"}

GSTIN_A = "27AAAAA0000A1Z2"   # Maharashtra
GSTIN_B = "29ABCDE1234F1ZW"   # Karnataka — different registration

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
    assert dup["existing_id"]  # matched against the pre-existing "Existing Co" row
    assert res["data"]["errors"] == []
    # Existing row untouched; only the one non-colliding vendor was added.
    assert len(db.rows("vendors")) == 2
    assert any(v["name"] == "Existing Co" for v in db.rows("vendors"))
    assert not any(v["name"] == "Duplicate Co" for v in db.rows("vendors"))


# ── retry / resubmit safety — the actual production incident this mirrors ────

def test_resubmitting_the_same_batch_creates_no_duplicates(monkeypatch):
    """Reproduces the real incident: a large CSV import gets resubmitted
    (browser timeout, ambiguous failure, user re-uploading the same file)
    after the first submission already succeeded. Without app-level dedup,
    the retry silently doubles every vendor. GSTIN is required here — like
    customers.py, a vendor with neither GSTIN nor PAN has no reliable match
    key and is a known, pre-existing gap shared with the customers importer,
    not something this fix introduces."""
    db = _setup(monkeypatch)
    batch = [
        dict(client_id="CLI", name="Alpha Supplies", gstin=GSTIN_B),
        dict(client_id="CLI", name="Bravo Traders", gstin=GSTIN_A),
    ]
    first = _bulk(batch)
    assert len(first["data"]["created"]) == 2

    retry = _bulk(batch)
    assert retry["success"] is True
    assert retry["data"]["created"] == []
    assert len(retry["data"]["duplicates"]) == 2
    assert len(db.rows("vendors")) == 2  # not 4


def test_same_gstin_twice_within_one_batch_only_creates_one(monkeypatch):
    db = _setup(monkeypatch)
    batch = [
        dict(client_id="CLI", name="Duplicate Row One", gstin=GSTIN_A),
        dict(client_id="CLI", name="Duplicate Row Two", gstin=GSTIN_A),
    ]
    res = _bulk(batch)
    assert len(res["data"]["created"]) == 1
    assert len(res["data"]["duplicates"]) == 1
    assert len(db.rows("vendors")) == 1


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

def test_single_create_vendor_returns_existing_on_gstin_collision(monkeypatch):
    """Same guard on the single-row POST /api/vendors/ endpoint, not just
    /bulk — a duplicate GSTIN silently returns the existing vendor (marked
    duplicate=True) instead of creating a second row."""
    db = _setup(monkeypatch)
    db.seed("vendors", {"firm_id": FIRM, "client_id": "CLI", "name": "Existing Co",
                        "gstin": GSTIN_A, "is_active": True, "opening_balance_paise": 0})
    res = ven.create_vendor(VendorIn(client_id="CLI", name="Duplicate Co", gstin=GSTIN_A), CALLER)
    assert res["success"] is True
    assert res["data"]["duplicate"] is True
    assert res["data"]["name"] == "Existing Co"
    assert len(db.rows("vendors")) == 1


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
