"""
Client-assignment scope on the workflow-builder router.

This router is where "does the table have a `client_id`?" stops being a good
enough question.

  * `workflow_instances` has one (nullable — a workflow can be a firm-level
    sweep with no client at all).
  * `workflow_executions`, `workflow_failures` and `workflow_approvals` have a
    `firm_id` and **no client_id whatsoever** — but each has a NOT NULL
    `instance_id`, and that instance may name a client. They are client data
    living in a table with no client column. Scoping by column presence would
    have declared all three firm-level and left the audit trail, the failure
    list and the approval queue readable across every client in the firm.
  * `workflow_templates` and `workflow_schedules` really are firm property — the
    DEFINITIONS, not the runs. Guarding those would be theatre.

So the tests here are as much about what the guards must NOT do (404 a
firm-level run, block a template) as about what they refuse.
"""
import pytest
from fastapi import HTTPException

import routers.workflow_builder as wb

FIRM, MINE, THEIRS = "firm-1", "client-mine", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "manager"}

INSTANCES = {
    "I-MINE": {"id": "I-MINE", "firm_id": FIRM, "client_id": MINE,
               "template_id": "T1", "status": "running"},
    "I-THEIRS": {"id": "I-THEIRS", "firm_id": FIRM, "client_id": THEIRS,
                 "template_id": "T1", "status": "running"},
    # A firm-level run: a monthly compliance sweep belonging to no one client.
    "I-FIRM": {"id": "I-FIRM", "firm_id": FIRM, "client_id": None,
               "template_id": "T1", "status": "running"},
}


class _Repo:
    """Only the reads the guards make. Anything a guard should never reach is a
    failure, not a stub."""
    def __init__(self):
        self.wrote = []

    def get_instance(self, firm_id, instance_id):
        i = INSTANCES.get(instance_id)
        return i if i and i["firm_id"] == firm_id else None

    def client_ids_for_instances(self, firm_id, instance_ids):
        return {i: INSTANCES[i]["client_id"] for i in set(instance_ids)
                if i in INSTANCES and INSTANCES[i]["firm_id"] == firm_id}

    def get_approval(self, firm_id, approval_id):
        return {"id": approval_id, "firm_id": firm_id,
                "instance_id": approval_id.replace("A-", "I-")}

    def get_failure(self, firm_id, failure_id):
        return {"id": failure_id, "firm_id": firm_id,
                "instance_id": failure_id.replace("F-", "I-")}

    def get_template(self, firm_id, template_id):
        return {"id": template_id, "firm_id": firm_id, "name": "Monthly GST",
                "trigger_type": "manual", "is_active": True}

    # writes — reaching any of these after a refusal is the bug
    def respond_approval(self, *a, **k):
        self.wrote.append("respond_approval"); return None

    def resolve_failure(self, *a, **k):
        self.wrote.append("resolve_failure"); return None

    def update_instance_status(self, *a, **k):
        self.wrote.append("update_instance_status"); return {}

    def log_execution(self, *a, **k):
        self.wrote.append("log_execution")

    def list_executions(self, firm_id, instance_id=None, limit=50):
        return [{"id": "X1", "instance_id": "I-MINE"},
                {"id": "X2", "instance_id": "I-THEIRS"},
                {"id": "X3", "instance_id": "I-FIRM"},
                {"id": "X4", "instance_id": "I-GONE"}]

    def list_failures(self, firm_id, resolved=False, limit=50):
        return [{"id": "F-MINE", "instance_id": "I-MINE"},
                {"id": "F-THEIRS", "instance_id": "I-THEIRS"}]

    def list_approvals(self, firm_id, status=None, limit=50):
        return [{"id": "A-MINE", "instance_id": "I-MINE"},
                {"id": "A-THEIRS", "instance_id": "I-THEIRS"}]

    def list_instances(self, firm_id, **k):
        return [dict(v) for v in INSTANCES.values()]

    def list_action_logs(self, instance_id):
        return []


@pytest.fixture
def repo(monkeypatch):
    r = _Repo()
    monkeypatch.setattr(wb, "_repo", lambda: r)
    return r


@pytest.fixture
def deny(monkeypatch):
    """Refuse exactly one client. A firm-level run (client_id None) must still
    pass — that is the case a blunt "deny everything" fixture would hide."""
    seen = []

    def _check(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    monkeypatch.setattr(wb, "assert_client_access", _check)
    return seen


@pytest.fixture
def narrow(monkeypatch):
    """Stand in for the real assignment set: this caller is on MINE only."""
    monkeypatch.setattr(wb, "filter_by_client",
                        lambda user, rows: [r for r in rows
                                            if not r.get("client_id")
                                            or r["client_id"] == MINE])


# ══════════════════════════════════════════════════════════════════════════════
# Instances — the one table that does carry a client
# ══════════════════════════════════════════════════════════════════════════════

def test_another_managers_workflow_instance_is_refused(repo, deny):
    with pytest.raises(HTTPException) as e:
        wb.get_instance("I-THEIRS", current_user=USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_cancelling_another_managers_instance_is_refused_before_the_write(repo, deny):
    with pytest.raises(HTTPException):
        wb.cancel_instance("I-THEIRS", current_user=USER)
    assert repo.wrote == [], "the cancel was written despite the refusal"


def test_a_firm_level_run_is_not_404d_for_having_no_client(repo, deny):
    """`workflow_instances.client_id` is nullable — a monthly compliance sweep
    belongs to the firm, not a client. Collapsing "no client" into "not found"
    would hide every firm-level run in the system."""
    assert wb._assert_instance_scope(USER, "I-FIRM") is None
    assert deny == [None]


def test_an_unknown_instance_is_the_same_404_as_a_forbidden_one(repo, deny):
    with pytest.raises(HTTPException) as missing:
        wb._assert_instance_scope(USER, "I-NOPE")
    with pytest.raises(HTTPException) as hidden:
        wb._assert_instance_scope(USER, "I-THEIRS")
    assert missing.value.status_code == hidden.value.status_code == 404


def test_the_instance_lookup_is_still_firm_scoped(repo, deny):
    other_firm = dict(USER, firm_id="firm-2")
    with pytest.raises(HTTPException) as e:
        wb._assert_instance_scope(other_firm, "I-MINE")
    assert e.value.status_code == 404


def test_the_instance_list_narrows_but_keeps_firm_level_runs(repo, narrow):
    out = wb.list_instances(template_id=None, client_id=None, status=None,
                            limit=50, offset=0, current_user=USER)
    assert [i["id"] for i in out["data"]["instances"]] == ["I-MINE", "I-FIRM"]


def test_naming_a_client_checks_it_rather_than_narrowing(repo, deny, monkeypatch):
    monkeypatch.setattr(wb, "filter_by_client",
                        lambda *_a: pytest.fail("should not narrow a named request"))
    with pytest.raises(HTTPException):
        wb.list_instances(template_id=None, client_id=THEIRS, status=None,
                          limit=50, offset=0, current_user=USER)


# ══════════════════════════════════════════════════════════════════════════════
# Child tables — client data with no client column
# ══════════════════════════════════════════════════════════════════════════════

def test_the_audit_trail_is_narrowed_through_the_parent_instance(repo, narrow):
    """workflow_executions has no client_id. Every row here is only reachable
    because its instance was resolved first."""
    out = wb.list_executions(instance_id=None, limit=100, current_user=USER)
    assert [x["id"] for x in out["data"]["executions"]] == ["X1", "X3"]


def test_a_child_row_whose_parent_has_vanished_is_dropped_not_kept(repo, narrow):
    """It cannot be shown to belong to a client the caller may see, and keeping
    it would be the permissive reading of an unanswerable question."""
    out = wb.list_executions(instance_id=None, limit=100, current_user=USER)
    assert "X4" not in [x["id"] for x in out["data"]["executions"]]


def test_asking_for_one_instances_trail_is_refused_not_silently_empty(repo, deny):
    """An empty list reads as "nothing happened", which is a different and more
    misleading answer than "not yours"."""
    with pytest.raises(HTTPException) as e:
        wb.list_executions(instance_id="I-THEIRS", limit=100, current_user=USER)
    assert e.value.status_code == 404


def test_the_failure_list_is_narrowed_through_the_parent(repo, narrow):
    out = wb.list_failures(resolved=False, limit=50, current_user=USER)
    assert [f["id"] for f in out["data"]["failures"]] == ["F-MINE"]


def test_the_approval_queue_is_narrowed_through_the_parent(repo, narrow):
    out = wb.list_approvals(status="pending", limit=50, current_user=USER)
    assert [a["id"] for a in out["data"]["approvals"]] == ["A-MINE"]


def test_responding_to_another_clients_approval_is_refused_before_the_write(repo, deny):
    """respond_approval() writes, and resuming the workflow afterwards runs real
    steps against that client's data. The check has to come first."""
    with pytest.raises(HTTPException) as e:
        wb.respond_to_approval("A-THEIRS", payload=None, current_user=USER)
    assert e.value.status_code == 404
    assert repo.wrote == []


def test_resolving_another_clients_failure_is_refused_before_the_write(repo, deny):
    with pytest.raises(HTTPException) as e:
        wb.resolve_failure("F-THEIRS", current_user=USER)
    assert e.value.status_code == 404
    assert repo.wrote == []


def test_the_parent_lookup_is_one_query_for_the_whole_page(repo, narrow, monkeypatch):
    """Resolving the parent one row at a time would be a query per row on a page
    of 200."""
    calls = []
    real = repo.client_ids_for_instances
    monkeypatch.setattr(repo, "client_ids_for_instances",
                        lambda f, ids: calls.append(list(ids)) or real(f, ids))
    wb.list_executions(instance_id=None, limit=100, current_user=USER)
    assert len(calls) == 1


# ══════════════════════════════════════════════════════════════════════════════
# Firing a template creates a run FOR a client
# ══════════════════════════════════════════════════════════════════════════════

def test_firing_a_template_against_another_clients_books_is_refused(repo, deny, monkeypatch):
    """The template is firm property, but the trigger CREATES an instance
    against the client named in the payload — that is the client-scoped act."""
    fired = []
    monkeypatch.setattr(wb, "_engine",
                        lambda: type("E", (), {"fire_trigger": lambda *a, **k: fired.append(k) or []})())
    with pytest.raises(HTTPException) as e:
        wb.manually_trigger("T1", payload={"client_id": THEIRS}, current_user=USER)
    assert e.value.status_code == 404
    assert fired == [], "the workflow fired despite the refusal"


def test_firing_a_template_with_no_client_is_a_firm_level_run(repo, deny, monkeypatch):
    monkeypatch.setattr(wb, "_engine",
                        lambda: type("E", (), {"fire_trigger": lambda *a, **k: []})())
    wb.manually_trigger("T1", payload={}, current_user=USER)
    assert deny == [None]


# ══════════════════════════════════════════════════════════════════════════════
# Definitions are firm property — guarding them would be theatre
# ══════════════════════════════════════════════════════════════════════════════

def test_templates_and_schedules_do_not_consult_client_scope(repo, monkeypatch):
    """workflow_templates and workflow_schedules have firm_id and nothing else
    (migration 068). Over-guarding is a real failure mode: a client check here
    would either block a legitimate user or check something meaningless."""
    monkeypatch.setattr(wb, "assert_client_access",
                        lambda *_a: pytest.fail("a definition has no client to scope to"))
    monkeypatch.setattr(repo, "list_templates",
                        lambda *a, **k: [{"id": "T1", "firm_id": FIRM}], raising=False)
    monkeypatch.setattr(repo, "list_schedules",
                        lambda *a, **k: [{"id": "S1", "firm_id": FIRM,
                                          "template_id": "T1"}], raising=False)
    assert wb.list_templates(category=None, trigger_type=None, is_active=None,
                             search=None, limit=50, offset=0,
                             current_user=USER)["success"] is True
    assert wb.list_schedules(is_active=None, current_user=USER)["success"] is True
