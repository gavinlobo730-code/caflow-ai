"""
Client-assignment scope on the six ROW-ADDRESSED routes in einvoice.py,
form_26as.py and fixed_assets.py.

All three routers already carry main.py's mount-level _CLIENT_GUARD, but that
guard only fires when a client_id is present in the path, query string, or
JSON body. These six routes are addressed by a *row id* and carry no
client_id anywhere, so the guard never ran for them and each scoped on
firm_id alone:

  * einvoice   POST /records/{record_id}/irn-generated, /records/{id}/cancel
  * form-26as  POST /uploads/{upload_id}/parse, /uploads/{upload_id}/uploaded
  * fixed-assets POST /{asset_id}/depreciate, PATCH /{asset_id}/dispose

The two fixed_assets routes are the sharpest in this sweep so far: both are
financial WRITES that post a journal entry, so an unassigned caller could
move a ledger belonging to a book they cannot otherwise see. Same IDOR family
as the task #241 read-side fix on depreciation_schedule.

Two subtleties pinned here on purpose:

  * einvoice's handlers wrap the service call in `except Exception ->
    HTTPException(500)`. HTTPException IS an Exception, so a scope check
    placed inside that try would be re-raised as a 500 — a denial masquerading
    as a server error. test_..._denial_is_404_not_500 fails if the guard is
    ever moved back inside the try.
  * form_26as.mark_26as_uploaded's mock branch previously read _MOCK_UPLOADS
    directly and checked NEITHER firm nor assignment. The shared resolver now
    covers both modes.
"""
import pytest
from fastapi import HTTPException

import routers.einvoice as ei
import routers.form_26as as f26
import routers.fixed_assets as fa

FIRM, OTHER_FIRM = "firm-1", "firm-2"
MINE, THEIRS = "client-mine", "client-theirs"

USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Executive"}


def _scope_to_mine(monkeypatch, module):
    """Pin can_access_client to a single assigned book on the router module.

    core.authz.can_access_client short-circuits to True under _USE_MOCK, so
    the tests would pass vacuously without this — patch the name the router
    actually calls.
    """
    monkeypatch.setattr(
        module, "can_access_client",
        lambda user, client_id: (not client_id) or client_id == MINE,
    )


# ══════════════════════════════════════════════════════════════════════════════
# einvoice.py — _assert_record_scope
# ══════════════════════════════════════════════════════════════════════════════

class _IRNReq:
    irn = "IRN123"
    ack_number = "ACK1"
    ack_date = "2026-01-05"
    qr_data = None
    provider_response = None


class _CancelReq:
    cancellation_reason = "duplicate"


def _patch_einvoice_record(monkeypatch, record):
    """get_einvoice_record is imported inside the resolver, so patch the source."""
    import domain.income_tax.einvoice_service as svc
    monkeypatch.setattr(
        svc, "get_einvoice_record",
        lambda firm_id, record_id: record if (record and record["firm_id"] == firm_id) else None,
    )


def _forbid_mutation(monkeypatch):
    """Any write reaching the service on a denied request is itself the bug."""
    import domain.income_tax.einvoice_service as svc

    def _boom(**_kw):
        raise AssertionError("mutation ran despite a denied client scope")

    monkeypatch.setattr(svc, "record_irn_generated", _boom)
    monkeypatch.setattr(svc, "record_irn_cancelled", _boom)


def test_irn_generated_allows_assigned_client(monkeypatch):
    _scope_to_mine(monkeypatch, ei)
    _patch_einvoice_record(monkeypatch, {"id": "r1", "firm_id": FIRM, "client_id": MINE})
    import domain.income_tax.einvoice_service as svc
    monkeypatch.setattr(svc, "record_irn_generated", lambda **kw: {"id": "r1", "client_id": MINE})
    monkeypatch.setattr(ei.timeline_service, "log", lambda **kw: None)

    resp = ei.record_irn_generated("r1", _IRNReq(), USER)
    assert resp["success"] is True


def test_irn_generated_denies_unassigned_client(monkeypatch):
    _scope_to_mine(monkeypatch, ei)
    _patch_einvoice_record(monkeypatch, {"id": "r1", "firm_id": FIRM, "client_id": THEIRS})
    _forbid_mutation(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        ei.record_irn_generated("r1", _IRNReq(), USER)
    assert exc.value.status_code == 404


def test_irn_generated_denial_is_404_not_500(monkeypatch):
    """Regression: the guard must sit OUTSIDE the handler's `except Exception`.

    If it is moved back inside, HTTPException(404) is caught by
    `except Exception as e: raise HTTPException(500, detail=str(e))` and the
    denial is reported as a server error instead.
    """
    _scope_to_mine(monkeypatch, ei)
    _patch_einvoice_record(monkeypatch, {"id": "r1", "firm_id": FIRM, "client_id": THEIRS})
    _forbid_mutation(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        ei.record_irn_generated("r1", _IRNReq(), USER)
    assert exc.value.status_code == 404
    assert exc.value.detail == "E-invoice record not found"


def test_irn_generated_denies_other_firms_record(monkeypatch):
    _scope_to_mine(monkeypatch, ei)
    _patch_einvoice_record(monkeypatch, {"id": "r1", "firm_id": OTHER_FIRM, "client_id": MINE})
    _forbid_mutation(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        ei.record_irn_generated("r1", _IRNReq(), USER)
    assert exc.value.status_code == 404


def test_irn_generated_denies_missing_record(monkeypatch):
    _scope_to_mine(monkeypatch, ei)
    _patch_einvoice_record(monkeypatch, None)
    _forbid_mutation(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        ei.record_irn_generated("nope", _IRNReq(), USER)
    assert exc.value.status_code == 404


def test_cancel_irn_denies_unassigned_client(monkeypatch):
    _scope_to_mine(monkeypatch, ei)
    _patch_einvoice_record(monkeypatch, {"id": "r1", "firm_id": FIRM, "client_id": THEIRS})
    _forbid_mutation(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        ei.cancel_irn("r1", _CancelReq(), USER)
    assert exc.value.status_code == 404


def test_cancel_irn_allows_assigned_client(monkeypatch):
    _scope_to_mine(monkeypatch, ei)
    _patch_einvoice_record(monkeypatch, {"id": "r1", "firm_id": FIRM, "client_id": MINE})
    import domain.income_tax.einvoice_service as svc
    monkeypatch.setattr(svc, "record_irn_cancelled", lambda **kw: {"id": "r1", "client_id": MINE})
    monkeypatch.setattr(ei.timeline_service, "log", lambda **kw: None)

    resp = ei.cancel_irn("r1", _CancelReq(), USER)
    assert resp["success"] is True


# ══════════════════════════════════════════════════════════════════════════════
# form_26as.py — _assert_upload_scope
# ══════════════════════════════════════════════════════════════════════════════

class _ParseReq:
    raw_text = "some 26AS text"


def _patch_upload(monkeypatch, upload):
    import domain.income_tax.form26as_service as svc
    monkeypatch.setattr(
        svc, "get_upload",
        lambda firm_id, upload_id: upload if (upload and upload["firm_id"] == firm_id) else None,
    )


def _upload(client_id, firm_id=FIRM):
    return {"id": "up1", "firm_id": firm_id, "client_id": client_id,
            "financial_year": "2025-26"}


def test_parse_upload_allows_assigned_client(monkeypatch):
    _scope_to_mine(monkeypatch, f26)
    _patch_upload(monkeypatch, _upload(MINE))
    import domain.income_tax.form26as_service as svc
    monkeypatch.setattr(svc, "parse_26as_text", lambda _t: [{"tan": "X"}])
    monkeypatch.setattr(svc, "save_parsed_records", lambda **kw: {"id": "up1"})

    resp = f26.parse_upload("up1", _ParseReq(), USER)
    assert resp["success"] is True
    assert resp["data"]["records_parsed"] == 1


def test_parse_upload_denies_unassigned_client(monkeypatch):
    _scope_to_mine(monkeypatch, f26)
    _patch_upload(monkeypatch, _upload(THEIRS))
    import domain.income_tax.form26as_service as svc

    def _boom(**_kw):
        raise AssertionError("parsed/saved despite a denied client scope")

    monkeypatch.setattr(svc, "save_parsed_records", _boom)

    with pytest.raises(HTTPException) as exc:
        f26.parse_upload("up1", _ParseReq(), USER)
    assert exc.value.status_code == 404
    assert exc.value.detail == "Upload not found"


def test_parse_upload_denies_other_firms_upload(monkeypatch):
    _scope_to_mine(monkeypatch, f26)
    _patch_upload(monkeypatch, _upload(MINE, firm_id=OTHER_FIRM))

    with pytest.raises(HTTPException) as exc:
        f26.parse_upload("up1", _ParseReq(), USER)
    assert exc.value.status_code == 404


def test_mark_uploaded_denies_unassigned_client(monkeypatch):
    _scope_to_mine(monkeypatch, f26)
    _patch_upload(monkeypatch, _upload(THEIRS))
    monkeypatch.setattr(
        f26.timeline_service, "log",
        lambda **kw: (_ for _ in ()).throw(AssertionError("logged despite denial")),
    )

    with pytest.raises(HTTPException) as exc:
        f26.mark_26as_uploaded("up1", USER)
    assert exc.value.status_code == 404


def test_mark_uploaded_allows_assigned_client(monkeypatch):
    _scope_to_mine(monkeypatch, f26)
    _patch_upload(monkeypatch, _upload(MINE))
    monkeypatch.setattr(f26.timeline_service, "log", lambda **kw: None)

    resp = f26.mark_26as_uploaded("up1", USER)
    assert resp["success"] is True
    assert resp["data"]["client_id"] == MINE


def test_mark_uploaded_enforces_firm_in_mock_mode(monkeypatch):
    """The old mock branch read _MOCK_UPLOADS directly and checked nothing —
    not even the firm. One resolver now covers both modes."""
    _scope_to_mine(monkeypatch, f26)
    _patch_upload(monkeypatch, _upload(MINE, firm_id=OTHER_FIRM))

    with pytest.raises(HTTPException) as exc:
        f26.mark_26as_uploaded("up1", USER)
    assert exc.value.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# fixed_assets.py — the two financial writes
# ══════════════════════════════════════════════════════════════════════════════

class _Resp:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, rows):
        self.rows, self.f = rows, []

    def select(self, *_a, **_k):
        return self

    def eq(self, k, v):
        self.f.append((k, v))
        return self

    def update(self, *_a, **_k):
        raise AssertionError("asset mutated despite a denied client scope")

    def single(self):
        return self

    def execute(self):
        matched = [r for r in self.rows if all(r.get(k) == v for k, v in self.f)]
        return _Resp(matched[0] if matched else None)


class _FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def table(self, _name):
        return _Q(self.rows)


def _asset(client_id, firm_id=FIRM):
    return {
        "id": "a1", "firm_id": firm_id, "client_id": client_id,
        "asset_name": "Machine", "is_disposed": False,
        "purchase_date": "2025-04-10", "purchase_cost_paise": 500_000_00,
        "salvage_value_paise": 0, "depreciation_method": "WDV",
        "wdv_rate_percent": 24.0, "accumulated_depreciation_paise": 0,
        "depreciation_posted_through": None,
    }


class _DeprIn:
    period = "2025-06"


class _DispIn:
    disposal_type = "sale"
    sale_proceeds_paise = 100_00
    disposal_date = "2025-06-30"
    notes = None


def _forbid_journal(monkeypatch):
    def _boom(*_a, **_k):
        raise AssertionError("journal posted despite a denied client scope")

    monkeypatch.setattr(fa._journal_svc, "journal_for_asset_depreciation", _boom, raising=False)
    monkeypatch.setattr(fa._journal_svc, "journal_for_asset_disposal", _boom, raising=False)


def test_post_depreciation_denies_unassigned_client(monkeypatch):
    _scope_to_mine(monkeypatch, fa)
    monkeypatch.setattr(fa, "_db", lambda: _FakeDB([_asset(THEIRS)]))
    _forbid_journal(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        fa.post_depreciation("a1", _DeprIn(), USER)
    assert exc.value.status_code == 404
    assert exc.value.detail == "Asset not found"


def test_post_depreciation_denies_other_firms_asset(monkeypatch):
    _scope_to_mine(monkeypatch, fa)
    monkeypatch.setattr(fa, "_db", lambda: _FakeDB([_asset(MINE, firm_id=OTHER_FIRM)]))
    _forbid_journal(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        fa.post_depreciation("a1", _DeprIn(), USER)
    assert exc.value.status_code == 404


def test_post_depreciation_reaches_the_asset_for_an_assigned_client(monkeypatch):
    """The guard must not deny the happy path — it gets past the scope check
    and fails later (period lock / update), never with 'Asset not found'."""
    _scope_to_mine(monkeypatch, fa)
    monkeypatch.setattr(fa, "_db", lambda: _FakeDB([_asset(MINE)]))

    with pytest.raises((HTTPException, AssertionError)) as exc:
        fa.post_depreciation("a1", _DeprIn(), USER)
    if isinstance(exc.value, HTTPException):
        assert exc.value.detail != "Asset not found"


def test_dispose_asset_denies_unassigned_client(monkeypatch):
    _scope_to_mine(monkeypatch, fa)
    monkeypatch.setattr(fa, "_db", lambda: _FakeDB([_asset(THEIRS)]))
    _forbid_journal(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        fa.dispose_asset("a1", _DispIn(), USER)
    assert exc.value.status_code == 404
    assert exc.value.detail == "Asset not found"


def test_dispose_asset_denies_other_firms_asset(monkeypatch):
    _scope_to_mine(monkeypatch, fa)
    monkeypatch.setattr(fa, "_db", lambda: _FakeDB([_asset(MINE, firm_id=OTHER_FIRM)]))
    _forbid_journal(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        fa.dispose_asset("a1", _DispIn(), USER)
    assert exc.value.status_code == 404


def test_dispose_asset_reaches_the_asset_for_an_assigned_client(monkeypatch):
    _scope_to_mine(monkeypatch, fa)
    monkeypatch.setattr(fa, "_db", lambda: _FakeDB([_asset(MINE)]))

    with pytest.raises((HTTPException, AssertionError)) as exc:
        fa.dispose_asset("a1", _DispIn(), USER)
    if isinstance(exc.value, HTTPException):
        assert exc.value.detail != "Asset not found"


# ══════════════════════════════════════════════════════════════════════════════
# The resolvers' own firm filter
#
# Every test above patches get_einvoice_record / get_upload wholesale, so the
# real function bodies never run — mutation testing caught exactly that: the
# firm check inside them could be deleted and the whole file still passed.
# These exercise the real mock-mode bodies instead.
# ══════════════════════════════════════════════════════════════════════════════

def test_get_einvoice_record_filters_by_firm(monkeypatch):
    import domain.income_tax.einvoice_service as svc
    monkeypatch.setattr(svc, "_USE_MOCK", True)
    monkeypatch.setattr(
        svc, "_MOCK_RECORDS",
        {"r1": {"id": "r1", "firm_id": FIRM, "client_id": MINE}},
    )

    assert svc.get_einvoice_record(FIRM, "r1")["id"] == "r1"
    assert svc.get_einvoice_record(OTHER_FIRM, "r1") is None
    assert svc.get_einvoice_record(FIRM, "missing") is None


def test_get_upload_filters_by_firm(monkeypatch):
    import domain.income_tax.form26as_service as svc
    monkeypatch.setattr(svc, "_USE_MOCK", True)
    monkeypatch.setattr(
        svc, "_MOCK_UPLOADS",
        {"up1": {"id": "up1", "firm_id": FIRM, "client_id": MINE}},
    )

    assert svc.get_upload(FIRM, "up1")["id"] == "up1"
    assert svc.get_upload(OTHER_FIRM, "up1") is None
    assert svc.get_upload(FIRM, "missing") is None
