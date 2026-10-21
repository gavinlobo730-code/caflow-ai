"""`POST /api/recurring-journals/run` with no client runs the CALLER'S clients' templates, as its twin for bills does (POST-A-307).

WHAT WAS WRONG
    `run_due` called `recurring_journal_service.run_due(firm_id, client_id=None)` for a request with no `client_id`, and the
    service lists every active template of the FIRM with the privileged client. So a Manager assigned to one client pressed
    "run all due" and started a draft for every client of the firm, each one writing a run row and an audit line under the
    Manager's name. The drafts are drafts and the route never posts, which is why it was filed low, but whose drafts and
    whose audit line is exactly the line the assignment scope draws. The recurring purchase bills (`run_due_recurring_bills`)
    and the recurring invoices already narrow the same call by `effective_client_ids`.

WHAT THIS HOLDS
    * a caller assigned to one client generates the drafts of that client's templates and of no other;
    * a caller assigned to NOTHING generates nothing, and does not fall through to "no filter" (the empty set is the
      negative control: treating it as None would run the whole firm);
    * a firm-wide caller (a Partner) still generates for every client, in one call;
    * a named client is checked with `assert_client_access` first and the run is confined to it;
    * the response keeps the shape the screen reads (the three lists and their counts).

Runs in the mock-mode job: no database is needed.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clean():
    from services import recurring_journal_service as svc
    svc.MOCK_JOURNAL_TEMPLATES.clear()
    svc.MOCK_JOURNAL_RUNS.clear()
    yield
    svc.MOCK_JOURNAL_TEMPLATES.clear()
    svc.MOCK_JOURNAL_RUNS.clear()


class _Journal:
    """A manual_journal_service double that records what it was asked for."""

    def __init__(self):
        self.calls: list[dict] = []

    def create(self, db, firm_id, data, actor_id=None):
        self.calls.append(data)
        return {"id": f"JE-{len(self.calls)}", "status": data.get("status"), "source_type": "manual"}


class _Backwards(set):
    """A set that iterates in descending order, so an unsorted `list(eff)` cannot match the sorted order by chance."""

    def __iter__(self):
        return iter(sorted(super().__iter__(), reverse=True))


def _template(client: str, name: str):
    from services import recurring_journal_service as svc
    return svc.create_template("F1", {
        "client_id": client, "name": name, "frequency": "monthly", "day_of_month": 1, "start_date": "2026-04-01",
        "narration": "Rent", "lines": [
            {"account_id": "ACC-DR", "debit_paise": 5_00_000, "credit_paise": 0},
            {"account_id": "ACC-CR", "debit_paise": 0, "credit_paise": 5_00_000}]}, created_by="u1")


def _world(monkeypatch):
    import services.manual_journal_service as mjs
    journal = _Journal()
    monkeypatch.setattr(mjs, "manual_journal_service", journal)
    return journal, _template("C1", "rent C1"), _template("C2", "rent C2")


def _run(monkeypatch, effective, client_id=None):
    import routers.recurring_journals as mod
    monkeypatch.setattr(mod, "effective_client_ids", lambda _user: effective, raising=False)    # absent from the pre-fix router: the control must reach the behaviour
    return mod.run_due(client_id=client_id, as_of="2026-04-02",
                       current_user={"id": "u1", "firm_id": "F1", "role": "Manager"})


def _data(response: dict) -> dict:
    assert response["success"] is True, response
    return response["data"]


def test_a_caller_assigned_to_one_client_generates_that_clients_drafts_only(monkeypatch):
    journal, t1, t2 = _world(monkeypatch)
    out = _data(_run(monkeypatch, {"C1"}))
    assert [c["client_id"] for c in journal.calls] == ["C1"], "a draft was started for a client the caller is not assigned to"
    assert out["generated_count"] == 1 and {g["template_id"] for g in out["generated"]} == {t1["id"]}
    assert t2["next_run_date"] == "2026-04-01", "the other client's template was advanced"


def test_a_caller_assigned_to_nothing_generates_nothing_and_does_not_fall_through_to_the_whole_firm(monkeypatch):
    journal, t1, t2 = _world(monkeypatch)
    out = _data(_run(monkeypatch, set()))
    assert journal.calls == [], "an empty scope ran the firm's templates"
    assert out["generated_count"] == out["skipped_count"] == out["failed_count"] == 0
    assert t1["next_run_date"] == t2["next_run_date"] == "2026-04-01"


def test_a_firm_wide_caller_still_generates_for_every_client_in_one_call(monkeypatch):
    import services.recurring_journal_service as svc
    journal, t1, t2 = _world(monkeypatch)
    seen: list = []
    real = svc.run_due
    monkeypatch.setattr(svc, "run_due", lambda *a, **k: (seen.append(k.get("client_id")), real(*a, **k))[1])
    out = _data(_run(monkeypatch, None))
    assert sorted(c["client_id"] for c in journal.calls) == ["C1", "C2"]
    assert out["generated_count"] == 2
    assert seen == [None], "a Partner's run should be one unrestricted call"


def test_a_caller_assigned_to_two_clients_gets_both_clients_drafts_in_one_answer(monkeypatch):
    """The per-client answers are merged, not overwritten: two calls that each generate must both be in the response."""
    journal, t1, t2 = _world(monkeypatch)
    out = _data(_run(monkeypatch, {"C1", "C2"}))
    assert out["generated_count"] == 2 and {g["template_id"] for g in out["generated"]} == {t1["id"], t2["id"]}
    assert sorted(c["client_id"] for c in journal.calls) == ["C1", "C2"]


def test_the_real_scope_function_gives_a_manager_with_no_assignments_the_empty_set_not_none(monkeypatch):
    """Every other test replaces `effective_client_ids`; this one asks the real function (outside mock mode) so that 'an
    empty set means nothing runs' is a property of the pair and not of the double."""
    import core.authz as authz
    import routers.recurring_journals as mod
    journal, _t1, _t2 = _world(monkeypatch)
    monkeypatch.setattr(authz, "_USE_MOCK", False)
    monkeypatch.setattr(authz, "assigned_client_ids", lambda _user: set())
    monkeypatch.setattr(mod, "effective_client_ids", authz.effective_client_ids)
    out = mod.run_due(client_id=None, as_of="2026-04-02", current_user={"id": "u1", "firm_id": "F1", "role": "Manager"})
    assert out["data"]["generated_count"] == 0 and journal.calls == [], "a Manager assigned to nothing ran the firm"
    partner = mod.run_due(client_id=None, as_of="2026-04-02", current_user={"id": "u2", "firm_id": "F1", "role": "Partner"})
    assert partner["data"]["generated_count"] == 2, "the Partner no longer runs every client"


def test_a_caller_assigned_to_two_clients_runs_each_in_a_stable_order(monkeypatch):
    import services.recurring_journal_service as svc
    _world(monkeypatch)
    seen: list = []
    actors: list = []
    monkeypatch.setattr(svc, "run_due", lambda *a, **k: (seen.append(k.get("client_id")), actors.append(k.get("actor_id")),
                                                          {"generated": [], "skipped": [], "failed": []})[2])
    _run(monkeypatch, _Backwards({"C1", "C2"}))
    assert seen == ["C1", "C2"], "the clients were run in the order the set happened to iterate"
    assert actors == ["u1", "u1"], "the run did not carry the person who pressed it (the audit line names them)"


def test_a_named_client_is_checked_first_and_the_run_is_confined_to_it(monkeypatch):
    import routers.recurring_journals as mod
    journal, t1, t2 = _world(monkeypatch)
    asked: list = []
    monkeypatch.setattr(mod, "assert_client_access", lambda user, cid, **_k: asked.append(cid))
    out = _data(_run(monkeypatch, {"C1", "C2"}, client_id="C2"))
    assert asked == ["C2"]
    assert [c["client_id"] for c in journal.calls] == ["C2"] and out["generated_count"] == 1


def test_a_named_client_the_caller_may_not_reach_runs_nothing(monkeypatch):
    from fastapi import HTTPException

    import routers.recurring_journals as mod
    journal, _t1, _t2 = _world(monkeypatch)

    def refuse(user, cid, **_k):
        raise HTTPException(status_code=404, detail="Client not found.")

    monkeypatch.setattr(mod, "assert_client_access", refuse)
    with pytest.raises(HTTPException) as e:
        _run(monkeypatch, {"C1"}, client_id="C2")
    assert e.value.status_code == 404 and journal.calls == []


def test_the_response_keeps_the_shape_the_screen_reads(monkeypatch):
    _world(monkeypatch)
    out = _data(_run(monkeypatch, {"C1"}))
    assert set(out) == {"generated", "skipped", "failed", "generated_count", "skipped_count", "failed_count"}
