"""
Customer master-data duplicate detection (CAFLOW customer-module QA fix).

The reported bug: re-importing the same customer file created duplicate master
records (18 → import 19 → re-import the SAME file → 37 active). create_customer
must never silently create a duplicate.

Match priority (per spec):
  1) GSTIN — CGST Act §25, a GSTIN uniquely identifies a registration.
  2) PAN   — IT Act §139A, identifies the entity; used only when no GSTIN.

A duplicate is NOT inserted; the existing row is returned flagged duplicate=True
so the import flow can report it as "already exists / skipped". Only ACTIVE
customers block creation — a deactivated namesake can be recreated.
"""
import routers.customers as cust
from models.parties import CustomerIn
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firma.test", "role": "Partner"}

GSTIN_A = "27AAAAA0000A1Z2"   # Maharashtra
GSTIN_B = "29ABCDE1234F1ZW"   # Karnataka — different registration
PAN_A = "AAAAA0000A"
PAN_B = "ZZZZZ9999Z"


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [cust])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": GSTIN_A})
    return db


def _create(**over):
    kw = dict(client_id="CLI", name="Acme Traders")
    kw.update(over)
    return cust.create_customer(CustomerIn(**kw), CALLER)


# ── GSTIN match (primary key) ────────────────────────────────────────────────

def test_same_gstin_is_skipped_not_duplicated(monkeypatch):
    db = _setup(monkeypatch)
    first = _create(gstin=GSTIN_A, state_code="27")
    assert first["success"] and not first["data"].get("duplicate")

    # Exact same file re-imported: same GSTIN.
    again = _create(gstin=GSTIN_A, state_code="27")
    assert again["success"]
    assert again["data"]["duplicate"] is True
    assert again["data"]["id"] == first["data"]["id"]      # returns the EXISTING row
    assert len(db.rows("customers")) == 1                  # nothing inserted


def test_gstin_match_is_case_insensitive(monkeypatch):
    db = _setup(monkeypatch)
    _create(gstin=GSTIN_A, state_code="27")
    again = _create(gstin=GSTIN_A.lower(), state_code="27")
    assert again["data"]["duplicate"] is True
    assert len(db.rows("customers")) == 1


def test_different_gstin_creates_new(monkeypatch):
    db = _setup(monkeypatch)
    _create(gstin=GSTIN_A, state_code="27")
    other = _create(name="Other Co", gstin=GSTIN_B, state_code="29")
    assert not other["data"].get("duplicate")
    assert len(db.rows("customers")) == 2


# ── PAN fallback (only when no GSTIN) ────────────────────────────────────────

def test_same_pan_without_gstin_is_skipped(monkeypatch):
    db = _setup(monkeypatch)
    first = _create(pan=PAN_A)
    assert not first["data"].get("duplicate")

    again = _create(pan=PAN_A)
    assert again["data"]["duplicate"] is True
    assert len(db.rows("customers")) == 1


def test_gstin_takes_priority_over_pan(monkeypatch):
    # Same PAN but a DIFFERENT GSTIN = a different registration of the same
    # entity → NOT a duplicate (GSTIN is the primary key when present).
    db = _setup(monkeypatch)
    _create(gstin=GSTIN_A, state_code="27", pan=PAN_A)
    other = _create(name="Branch 2", gstin=GSTIN_B, state_code="29", pan=PAN_A)
    assert not other["data"].get("duplicate")
    assert len(db.rows("customers")) == 2


# ── name-only customers: backend does not dedup on name alone ────────────────

def test_name_only_customers_are_not_deduped(monkeypatch):
    # Without a GSTIN or PAN there is no reliable unique identifier; the backend
    # must not merge by name (two real "Cash Sales" could exist). The frontend
    # import handles same-file name dedup separately.
    db = _setup(monkeypatch)
    a = _create(name="Walk-in")
    b = _create(name="Walk-in")
    assert not a["data"].get("duplicate")
    assert not b["data"].get("duplicate")
    assert len(db.rows("customers")) == 2


# ── deactivated namesake must not block recreation ───────────────────────────

def test_deactivated_customer_does_not_block_recreation(monkeypatch):
    db = _setup(monkeypatch)
    first = _create(gstin=GSTIN_A, state_code="27")
    # Soft-delete it.
    for r in db.rows("customers"):
        if r["id"] == first["data"]["id"]:
            r["is_active"] = False

    again = _create(gstin=GSTIN_A, state_code="27")
    assert not again["data"].get("duplicate")               # re-created, not blocked
    assert len(db.rows("customers")) == 2


# ── the exact reported scenario: re-import the same file ─────────────────────

def test_reimport_same_file_does_not_grow_count(monkeypatch):
    db = _setup(monkeypatch)
    batch = [
        dict(name="Alpha Ltd", gstin="27AAAAA0000A1Z2", state_code="27"),
        dict(name="Bravo LLP", gstin="29ABCDE1234F1ZW", state_code="29"),
        dict(name="Charlie & Co", pan="AAAAA0000A"),
    ]
    for row in batch:
        _create(**row)
    assert len(db.rows("customers")) == 3

    # Re-import the identical file: every row already exists → all skipped.
    dupes = [_create(**row) for row in batch]
    assert all(r["data"]["duplicate"] is True for r in dupes)
    assert len(db.rows("customers")) == 3                    # count unchanged
