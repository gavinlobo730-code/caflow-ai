"""The filing season at firm level: every return by stage, and a bulk run of the computations that can be run again (POST-A-068).

WHAT WAS MISSING
    The firm Income Tax screen offered one bulk action (Mark Filed); the computation screen is per client; nothing listed the season's
    returns by status and no bulk compute existed.

WHAT THIS HOLDS
    * the list gives each in-scope client one row with a stage read from the records (not started, computed, then the return's own
      status), the counts for the whole year and a window of rows; a client outside the caller's scope is absent from both;
    * documents received and e-verification are NOT stages and the answer says so;
    * 300 clients are listed in one read and a 100-client batch runs in one request; 101 is refused in a sentence;
    * the bulk run takes only RECORDED inputs: a client with no saved computation, or one saved before inputs were kept, is answered in
      words and nothing is computed or saved for it; the engine's refusal is passed on; a client outside scope is not run;
    * a different result is saved as the next version, DRAFT; the same result saves nothing; no return changes status;
    * the compute answer carries the inputs it ran on, which is what makes a saved computation re-runnable.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user
from core.exceptions import ValidationError
from domain.income_tax import computation_workspace as cw
from domain.income_tax import filing_season as rule
from routers.income_tax import ComputeITRRequest, compute_itr
from services import filing_season_service as svc
from tests.e2e_harness import FakeDB

FIRM = "11111111-1111-4111-8111-111111111111"
PARTNER = {"firm_id": FIRM, "id": "u1", "role": "Partner", "email": "p@f.test", "auth_user_id": "a1"}
FY, AY = "2025-26", "2026-27"


def _inputs(**over):
    base = {"fy": FY, "entity_type": "Individual", "gross_salary_paise": 1_200_000_00, "use_new_regime": True}
    return {**base, **over}


def _computation(**over):
    """A real engine answer for the inputs, as the screen saves it (`computation_json`)."""
    return compute_itr(ComputeITRRequest(**_inputs(**over)), current_user=PARTNER)["data"]


@pytest.fixture
def world(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(cw, "_USE_MOCK", False)
    monkeypatch.setattr(cw, "_supabase", lambda: db)
    return db


def _client(db, n, **extra):
    return db.seed("clients", {"firm_id": FIRM, "client_name": f"Client {n:03d}", "entity_type": "Individual", "status": "active",
                               "is_internal": False, "deleted_at": None, **extra})["id"]


def _snap(db, cid, *, version=1, data=None, status="draft"):
    return db.seed("tax_computation_snapshots", {
        "firm_id": FIRM, "client_id": cid, "financial_year": FY, "assessment_year": AY, "version": version, "regime": "new",
        "status": status, "computation_json": data, "net_payable_paise": 0, "created_at": f"2026-10-0{version}T10:00:00+00:00"})


def _filing(db, cid, status):
    return db.seed("itr_filings", {"firm_id": FIRM, "client_id": cid, "financial_year": FY, "assessment_year": AY, "itr_form": "ITR-1",
                                   "status": status, "created_at": "2026-10-01T10:00:00+00:00"})


# ── the rule ─────────────────────────────────────────────────────────────────

def test_a_stage_is_read_from_the_records():
    assert rule.stage_of(None, None) == "not_started"
    assert rule.stage_of(None, {"id": "s"}) == "computed"
    for status in ("draft", "review", "partner_review", "ready_for_filing", "filed"):
        assert rule.stage_of({"status": status}, {"id": "s"}) == status
    assert rule.stage_of({"status": "something new"}, None) == "draft"     # an unknown status is not drawn as filed


def test_the_answer_says_what_the_records_cannot(world):
    got = svc.season(world, PARTNER, FY)
    assert got["not_tracked"] and any("e-verified" in t for t in got["not_tracked"])
    assert "e_verified" not in got["counts"] and "documents_received" not in got["counts"]


# ── the list ─────────────────────────────────────────────────────────────────

def test_each_client_has_one_row_and_the_counts_are_the_years(world):
    a, b, c, d = (_client(world, i) for i in range(4))
    _snap(world, a, data={"x": 1})
    _filing(world, b, "review")
    _filing(world, c, "filed")
    _snap(world, c, data={"x": 1})
    got = svc.season(world, PARTNER, FY)
    assert got["total_clients"] == 4
    assert got["counts"] == {"not_started": 1, "computed": 1, "draft": 0, "review": 1, "partner_review": 0, "ready_for_filing": 0, "filed": 1}
    by = {r["client_id"]: r for r in got["rows"]}
    assert by[a]["stage"] == "computed" and by[d]["stage"] == "not_started" and by[c]["filing_status"] == "filed"
    assert [r["client_name"] for r in got["rows"]] == sorted(r["client_name"] for r in got["rows"])


def test_the_latest_computation_and_return_of_a_client_are_the_ones_read(world):
    a = _client(world, 1)
    _snap(world, a, version=1, status="draft", data={})
    _snap(world, a, version=3, status="reviewed", data={})
    _snap(world, a, version=2, status="draft", data={})
    row = svc.season(world, PARTNER, FY)["rows"][0]
    assert row["computation_version"] == 3 and row["computation_status"] == "reviewed"


def test_a_stage_filter_and_a_window_do_not_change_the_counts(world):
    ids = [_client(world, i) for i in range(5)]
    for cid in ids[:3]:
        _filing(world, cid, "draft")
    got = svc.season(world, PARTNER, FY, stage="draft", limit=2, offset=1)
    assert got["matching"] == 3 and len(got["rows"]) == 2 and got["counts"]["draft"] == 3 and got["counts"]["not_started"] == 2
    with pytest.raises(ValidationError):
        svc.season(world, PARTNER, FY, stage="e_verified")


def test_another_firms_clients_and_an_archived_client_are_not_listed(world):
    mine = _client(world, 1)
    world.seed("clients", {"firm_id": "other", "client_name": "Theirs", "entity_type": "Individual", "status": "active",
                           "is_internal": False, "deleted_at": None})
    _client(world, 2, status="archived")
    got = svc.season(world, PARTNER, FY)
    assert [r["client_id"] for r in got["rows"]] == [mine]


def test_three_hundred_clients_are_one_list(world):
    for i in range(300):
        _client(world, i)
    got = svc.season(world, PARTNER, FY, limit=500)
    assert got["total_clients"] == 300 and len(got["rows"]) == 300 and got["counts"]["not_started"] == 300


def test_an_assigned_only_caller_sees_only_their_clients(world, monkeypatch):
    import core.authz as authz
    mine, other = _client(world, 1), _client(world, 2)
    monkeypatch.setattr(authz, "_USE_MOCK", False)
    monkeypatch.setattr(authz, "assigned_client_ids", lambda user: {mine})
    got = svc.season(world, {**PARTNER, "role": "Manager"}, FY)
    assert [r["client_id"] for r in got["rows"]] == [mine] and got["total_clients"] == 1
    assert other not in {r["client_id"] for r in got["rows"]}


# ── the bulk run ─────────────────────────────────────────────────────────────

def test_the_compute_answer_keeps_the_inputs_it_ran_on():
    data = _computation()
    assert data["inputs"]["gross_salary_paise"] == 1_200_000_00 and data["inputs"]["use_new_regime"] is True
    assert rule.inputs_of({"computation_json": data}) == data["inputs"]


def test_a_saved_computation_whose_figures_moved_is_saved_as_the_next_draft_version(world):
    a = _client(world, 1)
    stale = _computation()
    stale = {**stale, "payable": {**stale["payable"], "net_payable_paise": stale["payable"]["net_payable_paise"] + 100_00}}
    _snap(world, a, data=stale)
    f = _filing(world, a, "review")

    out = svc.bulk_compute(world, PARTNER, FY, [a])

    (r,) = out["results"]
    assert r["state"] == "computed" and r["version"] == 2 and r["previous_version"] == 1
    saved = [s for s in world.rows("tax_computation_snapshots") if s["version"] == 2][0]
    assert saved["status"] == "draft" and saved["computation_json"]["inputs"]["gross_salary_paise"] == 1_200_000_00
    assert [x["status"] for x in world.rows("itr_filings") if x["id"] == f["id"]] == ["review"]      # the return did not move
    assert out["did_not"] and "Move any return" in out["did_not"][0]


def test_the_same_figures_save_nothing(world):
    a = _client(world, 1)
    _snap(world, a, data=_computation())
    out = svc.bulk_compute(world, PARTNER, FY, [a])
    assert out["results"][0]["state"] == "unchanged" and len(world.rows("tax_computation_snapshots")) == 1


def test_a_client_that_cannot_be_run_is_answered_in_words_and_nothing_is_saved(world):
    none_saved, old, refused = _client(world, 1), _client(world, 2), _client(world, 3)
    _snap(world, old, data={"regime": "new", "tax": {"total_tax_paise": 5}})            # saved before inputs were kept
    _snap(world, refused, data={"inputs": _inputs(entity_type="Trust")})               # the engine's own refusal
    out = svc.bulk_compute(world, PARTNER, FY, [none_saved, old, refused, "not-a-client"])
    by = {r["client_id"]: r for r in out["results"]}
    assert by[none_saved]["state"] == "no_saved_computation" and "Tax Computation screen" in by[none_saved]["message"]
    assert by[old]["state"] == "saved_without_inputs" and "before computations kept their inputs" in by[old]["message"]
    assert by[refused]["state"] == "refused" and by[refused]["message"]
    assert by["not-a-client"]["state"] == "not_your_client"
    assert len(world.rows("tax_computation_snapshots")) == 2
    assert out["tally"] == {"no_saved_computation": 1, "saved_without_inputs": 1, "refused": 1, "not_your_client": 1}


def test_a_hundred_run_in_one_request_and_a_hundred_and_one_are_refused(world):
    ids = [_client(world, i) for i in range(101)]
    out = svc.bulk_compute(world, PARTNER, FY, ids[:100])
    assert len(out["results"]) == 100 and out["tally"] == {"no_saved_computation": 100}
    with pytest.raises(ValidationError, match="at most 100"):
        svc.bulk_compute(world, PARTNER, FY, ids)


def test_a_client_outside_the_callers_book_is_not_run(world, monkeypatch):
    import core.authz as authz
    mine, other = _client(world, 1), _client(world, 2)
    stale = _computation()
    _snap(world, other, data={**stale, "payable": {**stale["payable"], "net_payable_paise": 1}})
    monkeypatch.setattr(authz, "_USE_MOCK", False)
    monkeypatch.setattr(authz, "assigned_client_ids", lambda user: {mine})
    out = svc.bulk_compute(world, {**PARTNER, "role": "Manager"}, FY, [other])
    assert out["results"][0]["state"] == "not_your_client" and len(world.rows("tax_computation_snapshots")) == 1


# ── the doors ────────────────────────────────────────────────────────────────

@pytest.fixture
def api(world, monkeypatch):
    import routers.itr_workspace as ws
    from core import db_provider
    monkeypatch.setattr(db_provider, "service_db", lambda: world)
    app = FastAPI()
    app.include_router(ws.router)
    state = {"user": {**PARTNER}}
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    return TestClient(app, raise_server_exceptions=False), state


def test_the_list_and_run_doors_answer(api, world):
    client, _ = api
    a = _client(world, 1)
    got = client.get("/api/itr/season", params={"financial_year": FY}).json()["data"]
    assert got["total_clients"] == 1 and got["max_bulk_clients"] == 100
    r = client.post("/api/itr/season/compute", json={"financial_year": FY, "chosen_clients": [a]})
    assert r.status_code == 200 and r.json()["data"]["results"][0]["state"] == "no_saved_computation"
    assert client.post("/api/itr/season/compute", json={"financial_year": FY, "chosen_clients": []}).status_code == 422
    assert client.get("/api/itr/season", params={"financial_year": FY, "stage": "nope"}).status_code == 422
    assert client.get("/api/itr/season", params={"financial_year": "2026-28"}).status_code == 422


@pytest.mark.parametrize("role,reads,computes", [("Partner", True, True), ("Manager", True, True), ("Executive", True, True),
                                                 ("Reviewer", True, False)])
def test_the_doors_follow_the_income_tax_permissions(api, role, reads, computes):
    from core.permissions import PERMISSIONS
    client, state = api
    state["user"] = {**PARTNER, "role": role}
    allowed = lambda action: role in {r.value if hasattr(r, "value") else r for r in PERMISSIONS["income_tax"][action]}   # noqa: E731
    assert (client.get("/api/itr/season", params={"financial_year": FY}).status_code == 200) is allowed("read")
    r = client.post("/api/itr/season/compute", json={"financial_year": FY, "chosen_clients": ["x"]})
    assert (r.status_code == 200) is allowed("compute")
