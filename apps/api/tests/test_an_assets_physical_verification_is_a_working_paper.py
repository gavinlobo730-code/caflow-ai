"""A physical count of a client's fixed assets is a dated working paper with a finding per asset (POST-A-112, its second half;
migration 592).

WHAT WAS MISSING
    A CA auditing a client's books asks whether the fixed assets were physically verified, when, by whom and what was found against the
    register, and the working paper was a spreadsheet kept outside the product.

WHAT THESE HOLD (mock mode, through the real routes over the shared in-memory database, whose doubles of the two functions say what
the functions say; the functions themselves are held on real Postgres in the `_pg` file)
    * a count is opened on a day that has come, by someone named, for a client the caller may reach, one open count at a time, the
      refusal naming the open one;
    * an open count's paper lists every asset held on the day counted (bought by it, not disposed of by it, not deleted), each with its
      finding or none yet, and the tally says how many are left; an asset bought after the day or disposed of before it is not listed;
    * a finding is stored beside the register's place and keeper, replaces the asset's earlier one, moves nothing in the register, and
      what cannot be a finding is refused in the function's words;
    * a count closes once every asset held on the day has a finding, the refusal naming how many have none; a closed count takes no
      finding and does not close again, and its paper is its findings alone, even of an asset deleted since;
    * a count of another firm or of a client the caller may not reach is one 404; every read names the firm and the client, the writes
      go through the privileged client, the routes ask the accounting permissions and the client check, and without a database they
      say so.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import routers.fixed_asset_verifications as vr
from domain.fixed_assets.verification import held_on
from tests.e2e_harness import FakeDB, wire_e2e

API = pathlib.Path(__file__).resolve().parents[1]
FIRM, CLIENT, OTHER_CLIENT = "FIRM-A", "CLI", "CLI-2"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "auth-u1", "email": "ca@f.test", "role": "Partner"}
DAY = "2026-03-31"


@pytest.fixture()
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [vr])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.audited = []
    monkeypatch.setattr(vr, "log_event", lambda *a, **k: d.audited.append((a, k)))
    d.seed("firms", {"id": FIRM, "name": "Test & Co"})
    for c in (CLIENT, OTHER_CLIENT):
        d.seed("clients", {"id": c, "firm_id": FIRM})
    d.seed("clients", {"id": "CLI-X", "firm_id": "FIRM-B"})
    d.seed("users", {"id": "u1", "firm_id": FIRM, "full_name": "Asha Rao", "email": "ca@f.test"})
    return d


def _asset(db, code, *, bought="2024-04-10", place="Factory", keeper=None, gone=None, client=CLIENT, firm=FIRM, **extra):
    return db.seed("fixed_assets", {"firm_id": firm, "client_id": client, "asset_code": code, "asset_name": f"Asset {code}",
                                    "asset_category": "Plant & Machinery", "purchase_date": bought, "purchase_cost_paise": 1_00_000_00,
                                    "location": place, "custodian": keeper, "is_disposed": bool(gone), "disposal_date": gone, **extra})


def _open(day=DAY, by="Stores team", client=CLIENT, user=CALLER):
    return vr.open_verification(vr.CountIn(client_id=client, verified_on=day, counted_by=by), current_user=user)["data"]


def _paper(vid, user=CALLER):
    return vr.verification_paper(vid, current_user=user)["data"]


def _find(vid, asset_id, finding="found", found_in=None, note=None, user=CALLER):
    return vr.record_finding(vid, asset_id, vr.FindingIn(finding=finding, found_in=found_in, note=note), current_user=user)["data"]


def _close(vid, user=CALLER):
    return vr.close_verification(vid, current_user=user)["data"]


def _refused(call, status, says=None):
    with pytest.raises(HTTPException) as exc:
        call()
    assert exc.value.status_code == status, exc.value.detail
    if says:
        assert says in exc.value.detail, exc.value.detail
    return exc.value.detail


@pytest.fixture()
def register(db):
    return {
        "held": _asset(db, "FA-1"),
        "spaced": _asset(db, "FA-2", place="Head  Office ", keeper="R.  Iyer"),
        "sold_after": _asset(db, "FA-3", gone="2026-04-15"),
        "late": _asset(db, "FA-4", bought="2026-04-01"),
        "gone": _asset(db, "FA-5", gone="2025-01-01"),
        "sold_on": _asset(db, "FA-6", gone=DAY),
        "other_client": _asset(db, "FB-1", client=OTHER_CLIENT),
    }


def test_a_count_is_opened_once_at_a_time_and_the_refusal_names_the_open_one(db):
    got = _open()
    assert (got["verified_on"], got["counted_by"], got["status"], got["created_by"]) == (DAY, "Stores team", "open", "u1")
    _refused(lambda: _open(day="2026-04-02"), 409, "The count of 31 Mar 2026 is still open")
    assert _open(client=OTHER_CLIENT)["status"] == "open"                         # another client's is its own
    [(args, kwargs)] = [e for e in db.audited if e[0][3] == "open"][:1]
    assert args[:2] == (FIRM, "fixed_asset_verification") and kwargs["actor_id"] == "auth-u1" and kwargs["actor_email"] == "ca@f.test"


@pytest.mark.parametrize("make, says", [
    (lambda: vr.CountIn(client_id=CLIENT, verified_on="2099-01-01", counted_by="X"), "has not come yet"),
    (lambda: vr.CountIn(client_id=CLIENT, verified_on=DAY, counted_by="   "), "counted_by"),
    (lambda: vr.CountIn(client_id=CLIENT, verified_on=DAY, counted_by="x" * 201), "counted_by"),
    (lambda: vr.FindingIn(finding="missing"), "finding"),
])
def test_what_cannot_be_a_count_or_a_finding_is_refused_at_the_request(make, says):
    with pytest.raises(ValidationError) as exc:
        make()
    assert says in str(exc.value)


def test_a_count_of_a_client_the_caller_may_not_reach_or_of_another_firm_is_a_404(db, monkeypatch):
    _refused(lambda: _open(client="CLI-X"), 404, "Client not found")
    vid = _open()["id"]
    monkeypatch.setattr(vr, "can_access_client", lambda user, client_id: False)
    for call in (lambda: _paper(vid), lambda: _find(vid, "any"), lambda: _close(vid)):
        assert _refused(call, 404) == "Verification not found"
    _refused(lambda: vr.list_verifications(CLIENT, current_user=CALLER), 404, "Client not found")
    _refused(lambda: _open(), 404, "Client not found")
    other_firm = {**CALLER, "firm_id": "FIRM-B"}
    monkeypatch.setattr(vr, "can_access_client", lambda user, client_id: True)
    assert _refused(lambda: _paper(vid, user=other_firm), 404) == "Verification not found"


def test_an_open_counts_paper_lists_every_asset_held_on_the_day_and_says_how_many_are_left(db, register):
    _asset(db, "FA-7", deleted_at="2025-06-01T10:00:00+00:00")                 # deleted from the register: not held
    vid = _open()["id"]
    paper = _paper(vid)
    codes = [line["asset_code"] for line in paper["lines"]]
    assert codes == ["FA-1", "FA-2", "FA-3"]    # bought after, disposed of before or on the day, deleted, another client's: out
    assert all(line["finding"] is None and line["held_on_the_day"] for line in paper["lines"])
    assert paper["verification"]["tally"] == {"found": 0, "found_elsewhere": 0, "not_found": 0, "damaged": 0, "to_count": 3}
    assert set(paper["findings"]) == {"found", "found_elsewhere", "not_found", "damaged"}


def test_a_finding_is_stored_beside_the_registers_place_and_keeper_replaces_the_last_and_moves_nothing(db, register):
    vid = _open()["id"]
    got = _find(vid, register["spaced"]["id"], "found_elsewhere", found_in="  Bay   3 ", note="Moved for the audit")
    assert (got["finding"], got["found_in"], got["register_location"], got["register_custodian"], got["recorded_by_name"]) == \
        ("found_elsewhere", "Bay 3", "Head Office", "R. Iyer", "Asha Rao")
    _find(vid, register["spaced"]["id"], "damaged", found_in="Bay 3")
    rows = [r for r in db.rows("fixed_asset_verification_findings") if r["asset_id"] == register["spaced"]["id"]]
    assert [(r["finding"], r["found_in"]) for r in rows] == [("damaged", None)]
    assert next(a for a in db.rows("fixed_assets") if a["id"] == register["spaced"]["id"])["location"] == "Head  Office "
    line = next(line for line in _paper(vid)["lines"] if line["asset_code"] == "FA-2")
    assert (line["finding"], line["recorded_by"], line["register_location"]) == ("damaged", "Asha Rao", "Head Office")


def test_the_register_beside_a_finding_is_the_register_on_the_day_counted_and_a_later_movement_does_not_rewrite_it(db, register):
    vid = _open()["id"]
    asset = register["held"]
    assert _find(vid, asset["id"], "found_elsewhere", found_in="Bay 3")["register_location"] == "Factory"
    # The person then records the move the screen suggests, dated after the count: the register now has the asset in Bay 3.
    db.seed("fixed_asset_movements", {"firm_id": FIRM, "client_id": CLIENT, "asset_id": asset["id"], "moved_on": "2026-04-02",
                                      "from_location": "Factory", "to_location": "Bay 3", "from_custodian": None, "to_custodian": None,
                                      "created_at": "2026-04-02T10:00:00+00:00"})
    db.seed("fixed_asset_movements", {"firm_id": FIRM, "client_id": CLIENT, "asset_id": asset["id"], "moved_on": "2026-04-10",
                                      "from_location": "Bay 3", "to_location": "Bay 5", "from_custodian": None, "to_custodian": "Stores",
                                      "created_at": "2026-04-10T10:00:00+00:00"})
    asset["location"], asset["custodian"] = "Bay 5", "Stores"
    again = _find(vid, asset["id"], "found_elsewhere", found_in="Bay 3", note="Moved after the count")
    assert (again["register_location"], again["register_custodian"]) == ("Factory", None), \
        "a movement after the day rewrote what the register held on it"
    line = next(line for line in _paper(vid)["lines"] if line["asset_id"] == asset["id"])
    assert (line["location"], line["register_location"]) == ("Factory", "Factory")
    # A move dated on or before the day, recorded only now, is what the register held on the day: the next finding reads it.
    other = register["spaced"]
    other["location"] = "Store 9"
    db.seed("fixed_asset_movements", {"firm_id": FIRM, "client_id": CLIENT, "asset_id": other["id"], "moved_on": "2026-03-20",
                                      "from_location": "Head Office", "to_location": "Store 9", "from_custodian": "R. Iyer",
                                      "to_custodian": "R. Iyer", "created_at": "2026-11-01T10:00:00+00:00"})
    other["custodian"] = "R. Iyer"
    assert _find(vid, other["id"], "found")["register_location"] == "Store 9"


@pytest.mark.parametrize("asset, finding, found_in, status, says", [
    ("late", "found", None, 422, "was not held on 31 Mar 2026"),
    ("gone", "found", None, 422, "was not held on 31 Mar 2026"),
    ("sold_on", "found", None, 422, "was not held on 31 Mar 2026"),
    ("other_client", "found", None, 404, "Asset not found"),
    ("held", "found_elsewhere", "   ", 422, "say where the asset was found"),
])
def test_what_cannot_be_a_finding_is_refused_in_the_functions_words_and_stores_nothing(db, register, asset, finding, found_in,
                                                                                       status, says):
    vid = _open()["id"]
    _refused(lambda: _find(vid, register[asset]["id"], finding, found_in=found_in), status, says)
    assert db.rows("fixed_asset_verification_findings") == []


def test_a_count_closes_once_every_asset_held_has_a_finding_and_then_is_the_working_paper(db, register):
    vid = _open()["id"]
    _find(vid, register["held"]["id"], "found")
    _refused(lambda: _close(vid), 422, "2 assets held on 31 Mar 2026 have no finding yet")
    _find(vid, register["spaced"]["id"], "not_found", note="Not in the office")
    _refused(lambda: _close(vid), 422, "1 asset held on 31 Mar 2026 has no finding yet")
    _find(vid, register["sold_after"]["id"], "found")
    closed = _close(vid)
    assert (closed["status"], closed["closed_by"]) == ("closed", "u1") and closed["closed_at"]
    _refused(lambda: _find(vid, register["held"]["id"], "damaged"), 409, "cannot change")
    _refused(lambda: _close(vid), 409, "stays closed")
    # An asset deleted after the count still appears on the paper it was counted on, and the paper is the findings alone.
    register["held"]["deleted_at"] = "2026-05-01T10:00:00+00:00"
    _asset(db, "FA-9")                                               # bought before the day but added to the register later
    paper = _paper(vid)
    assert [line["asset_code"] for line in paper["lines"]] == ["FA-1", "FA-2", "FA-3"]
    assert paper["verification"]["tally"] == {"found": 2, "found_elsewhere": 0, "not_found": 1, "damaged": 0, "to_count": None}
    assert paper["verification"]["closed_by_name"] == "Asha Rao" and paper["verification"]["closed_on"]
    # A new count may be opened once the last is closed.
    assert _open(day="2026-04-30")["status"] == "open"


def test_the_counts_are_listed_latest_first_with_their_tally(db, register):
    first = _open(day="2025-03-31")["id"]
    for key in register:                                  # FA-1, FA-2, FA-3 and FA-6 were held then; FA-5 had gone
        if register[key]["client_id"] == CLIENT and held_on(register[key], "2025-03-31"):
            _find(first, register[key]["id"], "found")
    _close(first)
    second = _open()["id"]
    _find(second, register["held"]["id"], "not_found")
    listed = vr.list_verifications(CLIENT, current_user=CALLER)["data"]
    assert set(listed["findings"]) == {"found", "found_elsewhere", "not_found", "damaged"}
    got = listed["counts"]
    assert [c["id"] for c in got] == [second, first]
    assert got[0]["tally"] == {"found": 0, "found_elsewhere": 0, "not_found": 1, "damaged": 0, "to_count": 2}
    assert got[1]["tally"]["to_count"] is None and got[1]["tally"]["found"] == 4


def test_every_read_names_the_firm_and_the_client_and_the_writes_go_through_the_privileged_client():
    src = (API / "services/fixed_asset_verifications.py").read_text()
    tree = ast.parse(src)
    for fn in ("_assets", "_findings", "_counts", "one_count"):
        body = ast.unparse(next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == fn))
        assert ".eq('firm_id', firm_id)" in body and ".eq('client_id', client_id)" in body, fn
    names = ast.unparse(next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_names"))
    assert ".eq('firm_id', firm_id)" in names
    for fn, writes in (("record_finding", "privileged_for(db).rpc('record_fixed_asset_finding'"),
                       ("close", "privileged_for(db).rpc('close_fixed_asset_verification'"),
                       ("create", "privileged_for(db).table('fixed_asset_verifications').insert(")):
        body = ast.unparse(next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == fn))
        assert writes in body, fn
    the_row = inspect.getsource(vr._the_count_row)
    assert '.eq("firm_id", firm_id)' in the_row


def test_the_routes_ask_the_accounting_permissions_and_the_client_check():
    for route, action in ((vr.list_verifications, "read"), (vr.verification_paper, "read"), (vr.open_verification, "write"),
                          (vr.record_finding, "write"), (vr.close_verification, "write")):
        src = inspect.getsource(route)
        assert f'rbac("accounting", "{action}")' in src and "can_access_client(current_user" in src, route.__name__


def test_without_a_database_the_routes_say_so(monkeypatch):
    import core.db_provider as dp
    monkeypatch.setattr(dp, "service_db_or_none", lambda: None)
    _refused(lambda: _paper("v1"), 503, "database")
