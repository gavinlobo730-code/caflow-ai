"""An asset's place and keeper have a dated history (POST-A-112, its first half; migration 591).

WHAT WAS MISSING
    `fixed_assets.location` was one free-text field that a move overwrote, so where an asset was last March, and who held it before,
    was nowhere, and nothing recorded who an asset is in the keeping of.

WHAT THESE HOLD (mock mode, through the real routes over the shared in-memory database, whose double of the database function says
what the function says; the function itself is held on real Postgres in the `_pg` file)
    * a movement stores the asset's own place and keeper as "before" (never sent), the new ones as "after", the day it moved, the note
      and who recorded it, and moves the asset; the history is every movement, latest first, with the recorder's name;
    * what cannot be a movement is refused in the function's own words and changes nothing: a day not yet come (at the request), a day
      before the purchase or before the latest movement, a disposed asset, a movement that moves nothing;
    * an asset of another firm, a deleted one or one of a client the caller may not reach is a 404 in one sentence, and so is one
      gone between the route's read and the function's;
    * a form opened before the asset last moved is a 409 that records nothing, and a place stored with stray spaces is the same
      place (no movement out of nothing); the request tidies a place before it asks its length and needs what the form opened on;
    * a keeper can be named when the asset is created and corrected by an edit of the asset, which records no movement (a typo is not
      a movement), a blank keeper being nobody;
    * every read names the firm and the client, the write goes through the privileged client, the routes ask the accounting
      permissions and the client check, and without a database they say so.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import routers.fixed_asset_movements as mv
import routers.fixed_assets as fa
from models.accounting import FixedAssetIn, FixedAssetUpdateIn
from tests.e2e_harness import FakeDB, seed_standard_coa, wire_e2e

API = pathlib.Path(__file__).resolve().parents[1]
FIRM, CLIENT = "FIRM-A", "CLI"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "auth-u1", "email": "ca@f.test", "role": "Partner"}


@pytest.fixture()
def db(monkeypatch):
    d = FakeDB()
    _DB["db"] = d
    wire_e2e(monkeypatch, d, [fa, mv])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.audited = []
    monkeypatch.setattr(mv, "log_event", lambda *a, **k: d.audited.append((a, k)))
    d.seed("firms", {"id": FIRM, "name": "Test & Co", "locked_financial_years": []})
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "financial_year_start": "2025-04-01"})
    d.seed("users", {"id": "u1", "firm_id": FIRM, "full_name": "Asha Rao", "email": "ca@f.test"})
    seed_standard_coa(d, FIRM, CLIENT)
    for name in ("Plant & Machinery", "Depreciation Expense", "Accumulated Depreciation"):
        d.seed("chart_of_accounts", {"firm_id": FIRM, "client_id": CLIENT, "account_name": name,
                                     "account_code": f"FA{abs(hash(name)) % 9000 + 1000}", "account_type": "Asset", "is_active": True})
    return d


def _asset(db, *, location="Factory", custodian=None, firm=FIRM, client=CLIENT, **extra):
    return db.seed("fixed_assets", {"firm_id": firm, "client_id": client, "asset_name": "Lathe", "asset_category": "Plant & Machinery",
                                    "purchase_date": "2024-04-10", "purchase_cost_paise": 1_00_000_00, "location": location,
                                    "custodian": custodian, **extra})


_NOW = object()   # the form opened on the register as it is now
_DB = {}


def _move(asset_id, day="2025-06-01", place=None, keeper=None, note=None, user=CALLER, seen=_NOW):
    if seen is _NOW:
        row = next((r for r in _DB["db"].rows("fixed_assets") if r["id"] == asset_id), {})
        seen = (row.get("location"), row.get("custodian"))
    body = mv.MovementIn(moved_on=day, from_location=seen[0], from_custodian=seen[1], to_location=place, to_custodian=keeper, note=note)
    return mv.record_asset_movement(asset_id, body, current_user=user)["data"]


def _history(asset_id, user=CALLER):
    return mv.asset_movements(asset_id, current_user=user)["data"]


def _row(db, asset_id):
    return next(r for r in db.rows("fixed_assets") if r["id"] == asset_id)


def test_a_movement_stores_the_assets_own_before_and_the_new_after_and_moves_the_asset(db):
    a = _asset(db)
    got = _move(a["id"], place="  Warehouse   2 ", keeper="Stores team", note="Shifted for repairs")
    assert (got["from_location"], got["to_location"], got["from_custodian"], got["to_custodian"]) == \
        ("Factory", "Warehouse 2", None, "Stores team")
    assert (got["moved_on"], got["note"], got["recorded_by"]) == ("2025-06-01", "Shifted for repairs", "Asha Rao")
    assert (_row(db, a["id"])["location"], _row(db, a["id"])["custodian"]) == ("Warehouse 2", "Stores team")
    [(args, kwargs)] = db.audited
    assert args[:4] == (FIRM, "fixed_asset", a["id"], "move") and kwargs["actor_id"] == "auth-u1"
    assert kwargs["actor_email"] == "ca@f.test"
    assert kwargs["old_data"] == {"location": "Factory", "custodian": None}


def test_the_history_is_every_movement_latest_first_with_the_place_and_keeper_now(db):
    a = _asset(db)
    _move(a["id"], day="2025-05-01", place="Bay 2")
    _move(a["id"], day="2025-06-01", place="Bay 2", keeper="R. Iyer")
    _move(a["id"], day="2025-06-01", place="Warehouse", keeper="R. Iyer")
    got = _history(a["id"])
    assert (got["location"], got["custodian"]) == ("Warehouse", "R. Iyer")
    assert [(m["moved_on"], m["to_location"], m["to_custodian"]) for m in got["movements"]] == [
        ("2025-06-01", "Warehouse", "R. Iyer"), ("2025-06-01", "Bay 2", "R. Iyer"), ("2025-05-01", "Bay 2", None)]
    assert all(m["recorded_by"] == "Asha Rao" for m in got["movements"])


@pytest.mark.parametrize("setup, call, says", [
    (lambda db, a: None, lambda a: _move(a["id"], day="2024-04-09", place="X"), "before the asset was bought on 10 Apr 2024"),
    (lambda db, a: _move(a["id"], day="2025-06-01", place="Bay 2"), lambda a: _move(a["id"], day="2025-05-31", place="X"),
     "latest movement is dated 01 Jun 2025"),
    (lambda db, a: None, lambda a: _move(a["id"], place=" Factory "), "Nothing moved"),
    (lambda db, a: a.update(is_disposed=True), lambda a: _move(a["id"], place="X"), "has been disposed of"),
])
def test_what_cannot_be_a_movement_is_refused_in_the_functions_words_and_changes_nothing(db, setup, call, says):
    a = _asset(db)
    setup(db, a)
    before = (_row(db, a["id"])["location"], len(db.rows("fixed_asset_movements")))
    with pytest.raises(HTTPException) as exc:
        call(a)
    assert exc.value.status_code == 422 and says in exc.value.detail, exc.value.detail
    assert (_row(db, a["id"])["location"], len(db.rows("fixed_asset_movements"))) == before


def test_a_form_opened_before_the_asset_last_moved_is_a_409_that_records_nothing(db):
    a = _asset(db)
    _move(a["id"], place="Bay 3", seen=("Factory", None))
    with pytest.raises(HTTPException) as exc:
        _move(a["id"], day="2025-06-02", place="Factory", keeper="R. Iyer", seen=("Factory", None))
    assert exc.value.status_code == 409
    assert "the register now has it at Bay 3, kept by nobody named. Nothing was recorded." in exc.value.detail
    assert (_row(db, a["id"])["location"], _row(db, a["id"])["custodian"], len(db.rows("fixed_asset_movements"))) == ("Bay 3", None, 1)


def test_a_place_stored_with_stray_spaces_is_the_same_place(db):
    a = _asset(db, location="Head  Office \t")
    with pytest.raises(HTTPException) as exc:
        _move(a["id"], place="Head Office")
    assert exc.value.status_code == 422 and "Nothing moved" in exc.value.detail
    got = _move(a["id"], place="Head Office", keeper="R. Iyer")
    assert (got["from_location"], got["to_location"]) == ("Head Office", "Head Office")


def test_the_request_tidies_a_place_before_it_asks_its_length_and_needs_what_the_form_opened_on():
    body = mv.MovementIn(moved_on="2025-06-01", from_location=None, from_custodian=None, to_location="  " + "x" * 200 + "   ")
    assert body.to_location == "x" * 200
    with pytest.raises(ValidationError):
        mv.MovementIn(moved_on="2025-06-01", from_location=None, from_custodian=None, to_location="x" * 201)
    with pytest.raises(ValidationError) as exc:
        mv.MovementIn(moved_on="2025-06-01", to_location="X")
    assert "from_location" in str(exc.value) and "from_custodian" in str(exc.value)


def test_an_asset_gone_between_the_read_and_the_write_is_the_same_404(db, monkeypatch):
    a = _asset(db)
    monkeypatch.setattr(mv, "_live_asset", lambda *_: {"id": a["id"], "client_id": CLIENT, "location": "Factory", "custodian": None})
    a["deleted_at"] = "2025-05-01T10:00:00+00:00"
    with pytest.raises(HTTPException) as exc:
        _move(a["id"], place="X", seen=("Factory", None))
    assert exc.value.status_code == 404 and exc.value.detail == "Asset not found"


def test_a_day_not_yet_come_is_refused_at_the_request(db):
    with pytest.raises(ValidationError) as exc:
        mv.MovementIn(moved_on="2099-01-01", from_location=None, from_custodian=None, to_location="X")
    assert "has not come yet" in str(exc.value)


@pytest.mark.parametrize("make", [
    lambda db: _asset(db, firm="FIRM-B"),
    lambda db: _asset(db, deleted_at="2025-05-01T10:00:00+00:00"),
])
def test_another_firms_asset_or_a_deleted_one_is_a_404_in_one_sentence(db, make):
    a = make(db)
    for call in (lambda: _history(a["id"]), lambda: _move(a["id"], place="X")):
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.status_code == 404 and exc.value.detail == "Asset not found"


def test_an_asset_of_a_client_the_caller_may_not_reach_is_the_same_404(db, monkeypatch):
    a = _asset(db)
    monkeypatch.setattr(mv, "can_access_client", lambda user, client_id: False)
    for call in (lambda: _history(a["id"]), lambda: _move(a["id"], place="X")):
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.status_code == 404 and exc.value.detail == "Asset not found"
    assert db.rows("fixed_asset_movements") == []


def test_a_keeper_is_named_at_creation_and_corrected_by_an_edit_which_records_no_movement(db):
    made = fa.create_asset(FixedAssetIn(client_id=CLIENT, asset_name="Laptop", asset_category="Plant & Machinery",
                                        purchase_date="2025-04-05", purchase_cost_paise=50_000_00, useful_life_years=5,
                                        acquisition_mode="paid", custodian="  R. Iyer "), CALLER)["data"]
    assert _row(db, made["id"])["custodian"] == "R. Iyer"
    fa.correct_asset(made["id"], FixedAssetUpdateIn(custodian="  R.   Iyengar "), CALLER)
    assert _row(db, made["id"])["custodian"] == "R. Iyengar"
    fa.correct_asset(made["id"], FixedAssetUpdateIn(custodian="   "), CALLER)
    assert _row(db, made["id"])["custodian"] is None
    assert db.rows("fixed_asset_movements") == []


def test_every_read_names_the_firm_and_the_client_and_the_write_goes_through_the_privileged_client():
    src = (API / "services/fixed_asset_movements.py").read_text()
    tree = ast.parse(src)
    reads = [ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "table"]
    assert reads, "no read found"
    history = ast.unparse(next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "history"))
    assert ".eq('firm_id', firm_id).eq('client_id', client_id)" in history
    names = ast.unparse(next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_with_names"))
    assert ".eq('firm_id', firm_id)" in names
    record = ast.unparse(next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "record"))
    assert "privileged_for(db).rpc('record_fixed_asset_movement'" in record
    assert ".table(" not in record, "a movement is written only by the database function"


def test_the_routes_ask_the_accounting_permissions_and_the_client_check():
    read, write = inspect.getsource(mv.asset_movements), inspect.getsource(mv.record_asset_movement)
    assert 'rbac("accounting", "read")' in read and 'rbac("accounting", "write")' in write
    for route in (read, write):
        assert 'can_access_client(current_user, asset.get("client_id"))' in route
    live = inspect.getsource(mv._live_asset)
    assert '.eq("firm_id", firm_id)' in live and '.is_("deleted_at", "null")' in live


def test_without_a_database_the_routes_say_so(monkeypatch):
    import core.db_provider as dp
    monkeypatch.setattr(dp, "service_db_or_none", lambda: None)
    with pytest.raises(HTTPException) as exc:
        mv.asset_movements("a1", current_user=CALLER)
    assert exc.value.status_code == 503 and "database" in exc.value.detail
