"""
A GST return that has been approved or filed changes only in the hands of someone who may APPROVE GST returns
(POST-A-223, POST-A-224).

WHAT WAS WRONG
    The web screens wrote `status: "ca_approved"` and the approver straight into the return tables, past the route that
    asks for `gst:approve` (Manager and above). The routes themselves were the other half: they asked the ROLE and not
    the PERSON (`can(role, ...)`, so a Partner's grid decision was ignored), asked nobody about REOPENING an approved
    or filed return (PATCH status `draft` on it, a re-save, a recompute and a delete all went through for anyone with
    `gst:compute`, Executive), and the annual-return save wrote `draft` over a FILED GSTR-9 with its ARN still on
    the row. Migration 491 asks the database the same question with the same pair; this module holds the routes'
    side, so the route answers in words before the database has to answer in a policy error (or, for an UPDATE or a
    DELETE, in zero rows read as success).

WHAT THIS ASSERTS (for GSTR-1 and GSTR-3B alike)
    * an Executive prepares a draft, a Manager approves it;
    * an Executive can NOT re-save, reopen (PATCH to any status), recompute or delete an approved return, and the
      row is exactly as it was;
    * a Manager who re-saves an approved return voids the approval: status draft, no approver, no time;
    * a Partner's per-person decision counts: an Executive the grid GRANTS `gst:approve` may approve, and a Manager the
      grid DENIES it may not;
    * a FILED annual return is refused by the GSTR-9 save, in the server's words.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import routers.gst_workspace as gw
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "firm-1"
CLIENT = "client-1"
GSTIN = "27AAPFU0939F1ZV"       # checksum-valid (tests/fixtures/gstin.json)
JUNE = "062026"


def _user(role, uid, **extra):
    return {"id": uid, "firm_id": FIRM, "auth_user_id": f"auth-{uid}", "email": f"{uid}@f.test", "role": role, **extra}


EXEC = _user("Executive", "exec")
MANAGER = _user("Manager", "mgr")
PARTNER = _user("Partner", "ptr")


@pytest.fixture
def world(monkeypatch):
    d = FakeDB()
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.test")
    monkeypatch.setattr(gw, "_USE_MOCK", False)
    wire_e2e(monkeypatch, d, [gw])
    d.seed("clients", {
        "id": CLIENT, "firm_id": FIRM, "client_name": "Acme Industries",
        "legal_name": "Acme Industries Private Limited", "gstin": GSTIN, "state_code": "27",
        "gst_filing_frequency": "monthly", "gst_registration_date": None,
        "gst_registration_type": None, "composition_category": None,
    })
    d.seed("firms", {"id": FIRM, "name": "F", "locked_financial_years": []})
    # a recompute asks the books; this module is about WHO MAY, not what the books say
    monkeypatch.setattr(gw, "_books_now", lambda cu, rec: {
        "tax_liability_paise": 10_000_00, "itc_claimed_paise": 2_000_00, "net_tax_paise": 8_000_00,
        "payload": {}, "working": {}, "credit_ledger": None})
    # ...nor what the credit ledger says: the recompute writes its ten columns, and only their NAMES matter here
    monkeypatch.setattr(gw.credit_ledger, "statement_columns", lambda block: {
        **{f"credit_{side}_{head}_paise": 0 for side in ("opening", "closing")
           for head in ("igst", "cgst", "sgst", "cess")},
        "credit_closing_as_of": "2026-06-30", "credit_opening_source": "none"})
    return d


def _save(kind, user):
    if kind == "gstr1":
        return gw.save_gstr1(gw.SaveGSTR1Request(
            client_id=CLIENT, period=JUNE, gstin=GSTIN, payload_json={"b2b": []}, summary_json={},
            total_taxable_paise=10_000_00), current_user=user)["data"]
    return gw.save_gstr3b(gw.SaveGSTR3BRequest(
        client_id=CLIENT, period=JUNE, gstin=GSTIN, payload_json={}, summary_json={},
        tax_liability_paise=10_000_00, itc_claimed_paise=2_000_00, net_tax_paise=8_000_00),
        current_user=user)["data"]


ROUTES = [
    ("gstr1", gw.update_gstr1_status, "gstr1_returns", gw.delete_gstr1),
    ("gstr3b", gw.update_gstr3b_status, "gstr3b_returns", gw.delete_gstr3b),
]


def _row(db, table, return_id):
    return [r for r in db.rows(table) if r["id"] == return_id][0]


def _approve(fn, return_id, user):
    return fn(return_id, gw.UpdateStatusRequest(status="ca_approved", ca_approved=True, acknowledge_stale=True),
              current_user=user)


@pytest.fixture(params=ROUTES, ids=[r[0] for r in ROUTES])
def route(request):
    return request.param


def _an_approved_return(world, route):
    kind, status_fn, table, _delete = route
    saved = _save(kind, EXEC)
    out = _approve(status_fn, saved["id"], MANAGER)
    assert out["success"] is True, out
    row = _row(world, table, saved["id"])
    assert row["status"] == "ca_approved" and row["ca_approved_by"] == "mgr", "premise: a Manager approved it"
    return saved["id"]


def test_an_executive_cannot_reopen_an_approved_return(world, route):
    kind, status_fn, table, _ = route
    rid = _an_approved_return(world, route)
    before = dict(_row(world, table, rid))

    for target in ("draft", "validated", "ca_approved"):
        out = status_fn(rid, gw.UpdateStatusRequest(status=target, ca_approved=True, acknowledge_stale=True),
                        current_user=EXEC)
        assert out["success"] is False, target
    assert _row(world, table, rid) == before


def test_an_executive_cannot_resave_an_approved_return(world, route):
    kind, _status, table, _ = route
    rid = _an_approved_return(world, route)
    before = dict(_row(world, table, rid))

    with pytest.raises(HTTPException) as e:
        _save(kind, EXEC)

    assert e.value.status_code == 403 and "may approve" in e.value.detail
    assert _row(world, table, rid) == before


def test_an_executive_cannot_delete_an_approved_return(world, route):
    _kind, _status, table, delete = route
    rid = _an_approved_return(world, route)

    out = delete(rid, current_user=EXEC)

    assert out["success"] is False and "may approve" in out["error"]
    assert _row(world, table, rid)["status"] == "ca_approved"


def test_an_executive_cannot_recompute_an_approved_return(world):
    saved = _save("gstr3b", EXEC)
    _approve(gw.update_gstr3b_status, saved["id"], MANAGER)

    out = gw.recompute_gstr3b(saved["id"], dry_run=False, current_user=EXEC)

    assert out["success"] is False and "may approve" in out["error"]
    row = _row(world, "gstr3b_returns", saved["id"])
    assert row["status"] == "ca_approved" and row["ca_approved_by"] == "mgr"


def test_a_manager_resaving_an_approved_return_voids_the_approval(world, route):
    kind, _status, table, _ = route
    rid = _an_approved_return(world, route)

    again = _save(kind, MANAGER)

    assert again["id"] == rid
    row = _row(world, table, rid)
    assert row["status"] == "draft"
    assert row["ca_approved_by"] is None and row["ca_approved_at"] is None


def test_a_manager_recomputing_an_approved_gstr3b_voids_the_approval(world):
    saved = _save("gstr3b", EXEC)
    _approve(gw.update_gstr3b_status, saved["id"], MANAGER)

    out = gw.recompute_gstr3b(saved["id"], dry_run=False, current_user=MANAGER)

    assert out["success"] is True, out
    row = _row(world, "gstr3b_returns", saved["id"])
    assert row["status"] == "draft" and row["ca_approved_by"] is None


def test_an_executive_still_prepares_and_revises_a_draft(world, route):
    kind, _status, table, delete = route
    first = _save(kind, EXEC)
    second = _save(kind, EXEC)
    assert first["id"] == second["id"] and _row(world, table, first["id"])["status"] == "draft"
    assert delete(first["id"], current_user=EXEC)["success"] is True


def test_an_executive_cannot_approve(world, route):
    kind, status_fn, table, _ = route
    saved = _save(kind, EXEC)

    out = _approve(status_fn, saved["id"], EXEC)

    assert out["success"] is False and "Manager or above" in out["error"]
    assert _row(world, table, saved["id"])["status"] == "draft"


def test_the_grid_decides_per_person_in_both_directions(world, route):
    """`can(role, ...)` could not see a Partner's grid; `can_user` does."""
    kind, status_fn, table, _ = route
    saved = _save(kind, EXEC)

    granted = _user("Executive", "exec2", permission_overrides={"gst:approve": True})
    assert _approve(status_fn, saved["id"], granted)["success"] is True
    assert _row(world, table, saved["id"])["ca_approved_by"] == "exec2"

    denied = _user("Manager", "mgr2", permission_overrides={"gst:approve": False})
    again = _save(kind, MANAGER)                       # a Manager voids it, then asks a second Manager
    out = _approve(status_fn, again["id"], denied)
    assert out["success"] is False and "Manager or above" in out["error"]
    assert _row(world, table, again["id"])["status"] == "draft"


def test_a_refused_update_is_not_read_as_success(world, route, monkeypatch):
    """The database may decline an UPDATE without an error (zero rows). The route must say so."""
    kind, status_fn, table, _ = route
    saved = _save(kind, EXEC)
    real = world.table

    class _NoRows:
        def __init__(self, inner): self._inner = inner
        def __getattr__(self, name):
            attr = getattr(self._inner, name)
            if name != "update":
                return attr
            def _update(*a, **k):
                class _Empty:
                    def eq(self, *x, **y): return self
                    def execute(self_inner):
                        class _R: data = []
                        return _R()
                return _Empty()
            return _update

    monkeypatch.setattr(world, "table", lambda name: _NoRows(real(name)) if name == table else real(name))

    out = _approve(status_fn, saved["id"], MANAGER)

    assert out["success"] is False and "not changed" in out["error"]


# ── the annual return ────────────────────────────────────────────────────────

def _gstr9(user, fy="2025-26"):
    return gw.save_gstr9(gw.GSTR9In(client_id=CLIENT, financial_year=fy, gstin=GSTIN,
                                    total_taxable_paise=500_00), current_user=user)


def test_a_filed_annual_return_is_not_rewritten_as_a_draft(world):
    """The save wrote `draft` over whatever the row held, a submitted GSTR-9 included, ARN and all."""
    first = _gstr9(EXEC)
    assert first["success"] is True, first
    row = [r for r in world.rows("gstr1_returns") if r["id"] == first["data"]["id"]][0]
    row.update({"status": "submitted", "arn": "AA270626123456A"})

    with pytest.raises(HTTPException) as e:
        _gstr9(MANAGER)

    assert e.value.status_code == 422 and "already been filed" in e.value.detail
    assert row["status"] == "submitted" and row["arn"] == "AA270626123456A"


def test_an_executive_cannot_rewrite_an_approved_annual_return_and_a_manager_voids_the_approval(world):
    first = _gstr9(EXEC)
    row = [r for r in world.rows("gstr1_returns") if r["id"] == first["data"]["id"]][0]
    row.update({"status": "ca_approved", "ca_approved_by": "mgr"})

    with pytest.raises(HTTPException) as e:
        _gstr9(EXEC)
    assert e.value.status_code == 403 and row["status"] == "ca_approved"

    assert _gstr9(MANAGER)["success"] is True
    assert row["status"] == "draft" and row["ca_approved_by"] is None
