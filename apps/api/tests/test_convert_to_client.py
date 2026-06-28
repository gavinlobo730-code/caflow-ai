"""
Regression tests for the "Convert to Client" workflow (lifecycle.convert_lead).

Root cause being guarded against: clients.pan was NOT NULL while PAN is OPTIONAL
at conversion (collected during onboarding), so converting without a PAN raised a
not-null constraint error — and the raw PostgreSQL error was echoed to the user.

These verify the aligned behaviour:
  * convert WITH / WITHOUT pan both succeed (pan optional, nullable column)
  * pan/gstin are FORMAT-validated before the insert, with friendly messages
  * empty pan/gstin are stored as NULL (never an empty string)
  * an unexpected DB error returns a friendly message and NEVER leaks SQL/PG text
  * the signed-engagement gate (existing flow) still applies
No financial arithmetic here — these assert conversion behaviour only.
"""
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from fastapi import HTTPException

import routers.lifecycle as lc
from routers.lifecycle import convert_lead, LeadConvertIn

FIRM = "firm-aaa"
USER = {"auth_user_id": "u-mgr", "firm_id": FIRM, "role": "Manager", "email": "mgr@firm.in"}

_SIGNED_ENGAGEMENT = {
    "id": "eng-1", "fee_amount_paise": 500000, "template_id": None,
    "title": "GST Compliance — FY26", "start_date": "2026-04-01",
    "engagement_number": "EL-2026-0001",
    "signed_at": "2026-03-01T00:00:00Z", "created_at": "2026-02-01T00:00:00Z",
}


# ── Fake Supabase client (mirrors test_workflow_sync) ─────────────────────────

class _Res:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, db, table):
        self.db = db; self.t = table; self._op = None; self._payload = None; self._single = False

    def select(self, *a, **k): self._op = "select"; return self
    def insert(self, payload):
        self._op = "insert"; self._payload = payload
        self.db.inserts.setdefault(self.t, []).append(payload); return self
    def update(self, payload):
        self._op = "update"; self._payload = payload
        self.db.updates.setdefault(self.t, []).append(payload); return self
    def eq(self, *a, **k): return self
    def neq(self, *a, **k): return self
    def or_(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def order(self, *a, **k): return self
    def range(self, *a, **k): return self
    def single(self): self._single = True; return self
    def maybe_single(self): self._single = True; return self

    def execute(self):
        if self._op == "insert" and self.t == "clients" and self.db.raise_on_clients_insert:
            # Simulate the real driver error so we can prove it is NOT leaked.
            raise RuntimeError(
                'null value in column "pan" of relation "clients" violates '
                'not-null constraint'
            )
        if self._op == "select":
            rows = self.db.selects.get(self.t, [])
            return _Res(rows[0] if rows else None) if self._single else _Res(list(rows))
        if self._op == "insert":
            payload = self._payload if isinstance(self._payload, list) else [self._payload]
            return _Res(payload)
        if self._op == "update":
            return _Res([self._payload])
        return _Res(None)


class FakeDB:
    def __init__(self):
        self.selects = {}; self.inserts = {}; self.updates = {}
        self.raise_on_clients_insert = False
    def table(self, name): return _Q(self, name)


def _base_db():
    db = FakeDB()
    db.selects["leads"] = [{
        "id": "L1", "firm_id": FIRM, "is_converted": False,
        "company_name": "Sharma & Co", "contact_name": "Rahul",
        "email": "r@x.in", "phone": "9000000000", "stage": "Onboarding",
    }]
    db.selects["engagements"] = [dict(_SIGNED_ENGAGEMENT)]
    db.selects["engagement_templates"] = []
    return db


@contextmanager
def world(db):
    with patch("routers.lifecycle._db", return_value=db), \
         patch("routers.lifecycle.timeline_service"), \
         patch("routers.lifecycle.log_event"):
        yield


def _convert(db, **kw):
    with world(db):
        return convert_lead("L1", LeadConvertIn(create_onboarding=True, **kw), current_user=USER)


def _client_insert(db):
    return db.inserts["clients"][0]


# ── PAN optional ──────────────────────────────────────────────────────────────

def test_convert_without_pan_succeeds():
    db = _base_db()
    res = _convert(db)  # no pan, no gstin
    assert res["success"] is True
    assert res["data"]["converted_client_id"]
    # pan/gstin stored as NULL (never an empty string — that would fail the CHECK).
    assert _client_insert(db)["pan"] is None
    assert _client_insert(db)["gstin"] is None


def test_convert_with_valid_pan_succeeds_and_uppercases():
    db = _base_db()
    res = _convert(db, pan="abcde1234f")
    assert res["success"] is True
    assert _client_insert(db)["pan"] == "ABCDE1234F"


def test_convert_with_invalid_pan_returns_422_friendly_and_no_insert():
    db = _base_db()
    with pytest.raises(HTTPException) as exc:
        _convert(db, pan="NOTAPAN")
    assert exc.value.status_code == 422
    assert "PAN" in exc.value.detail
    # Validated BEFORE the DB — no client row attempted.
    assert "clients" not in db.inserts
    # Friendly message, not a DB/driver error.
    for leak in ("null value", "constraint", "violates", "relation"):
        assert leak not in exc.value.detail.lower()


# ── GSTIN optional ────────────────────────────────────────────────────────────

def test_convert_with_valid_gstin_succeeds():
    db = _base_db()
    res = _convert(db, gstin="27AAAAA0000A1Z5")
    assert res["success"] is True
    assert _client_insert(db)["gstin"] == "27AAAAA0000A1Z5"


def test_convert_with_invalid_gstin_returns_422():
    db = _base_db()
    with pytest.raises(HTTPException) as exc:
        _convert(db, gstin="BADGSTIN")
    assert exc.value.status_code == 422
    assert "GSTIN" in exc.value.detail
    assert "clients" not in db.inserts


def test_convert_without_gstin_succeeds():
    db = _base_db()
    res = _convert(db, pan="ABCDE1234F")   # pan present, gstin absent
    assert res["success"] is True
    assert _client_insert(db)["gstin"] is None


def test_pan_and_gstin_together_valid():
    db = _base_db()
    res = _convert(db, pan="ABCDE1234F", gstin="27AAAAA0000A1Z5")
    assert res["success"] is True


# ── Error handling: no raw PG error ever reaches the user ─────────────────────

def test_db_insert_failure_returns_friendly_message_without_leaking_sql():
    db = _base_db()
    db.raise_on_clients_insert = True
    with pytest.raises(HTTPException) as exc:
        _convert(db)
    assert exc.value.status_code == 422
    detail = exc.value.detail
    # Friendly, generic copy …
    assert "couldn't create the client" in detail.lower()
    # … and absolutely no PostgreSQL/driver internals.
    for leak in ("null value", "not-null", "constraint", "violates", "relation", "column \"pan\""):
        assert leak not in detail.lower()


# ── Duplicate PAN allowed (no UNIQUE constraint on clients.pan) ────────────────

def test_duplicate_pan_is_allowed():
    # Two clients converted with the same PAN must both succeed — there is no
    # unique constraint on clients.pan (a firm can legitimately hold the record
    # more than once across edge cases); this must not raise.
    db1 = _base_db(); res1 = _convert(db1, pan="ABCDE1234F")
    db2 = _base_db(); res2 = _convert(db2, pan="ABCDE1234F")
    assert res1["success"] is True and res2["success"] is True


# ── Existing flow preserved: signed engagement still required ──────────────────

def test_signed_engagement_still_required():
    db = _base_db()
    db.selects["engagements"] = []   # no signed engagement
    with pytest.raises(HTTPException) as exc:
        _convert(db, pan="ABCDE1234F")
    assert exc.value.status_code == 409
    assert "signed engagement" in exc.value.detail.lower()
    assert "clients" not in db.inserts


def test_convert_links_signed_engagement_and_creates_onboarding():
    # The full chain still works end to end with a valid (or absent) PAN.
    db = _base_db()
    res = _convert(db, pan="ABCDE1234F")
    assert res["success"] is True
    assert "fee_engagements" in db.inserts            # fee engagement created
    assert "onboarding_workflows" in db.inserts       # onboarding started
    assert any(u.get("is_converted") for u in db.updates["leads"])  # lead marked converted
