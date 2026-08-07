"""
Client-assignment scope on the recurring-task router.

`task_recurring` sits on `/api/task-recurring`, so the `/api/tasks` prefix
registered for `tasks` + `task_extras` does NOT cover it. The two read as one
feature and are two registrations — which is exactly the trap.

WHAT WAS AND WASN'T THERE
    This router already checked the client on the way IN: `create_recurring` and
    `update_recurring` both called `assert_client_access` on a caller-supplied
    `body.client_id`. Nothing checked the client of a config named by ID, so
    every STORED config was open — edit it, delete it, or rewrite the assignment
    rules that decide who in the firm ends up doing the work. A guard on the
    input and none on the record is the shape that reads as "already handled".

THE NULLABLE CLIENT
    `task_recurring_configs.client_id` is nullable (migration 063). A config with
    no client is a FIRM-level recurring task, not a hidden one, and both paths
    have to agree about that: `assert_client_access(user, None)` passes it, and
    `filter_by_client` keeps it. Getting this wrong in the other direction —
    treating unassigned as forbidden — would silently stop the firm's own
    recurring tasks from ever being generated again.
"""
import pytest
from fastapi import HTTPException

import routers.task_recurring as trc

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "role": "Executive"}
PARTNER = {"id": "p1", "firm_id": FIRM, "role": "Partner"}

CONFIGS = [
    {"id": "C-MINE", "firm_id": FIRM, "client_id": MINE, "title": "Monthly GSTR-1",
     "template_id": None, "next_due_date": "2026-01-01", "is_active": True,
     "frequency": "monthly", "priority": "high"},
    {"id": "C-THEIRS", "firm_id": FIRM, "client_id": THEIRS, "title": "Acme board pack",
     "template_id": None, "next_due_date": "2026-01-01", "is_active": True,
     "frequency": "monthly", "priority": "high"},
    {"id": "C-FIRM", "firm_id": FIRM, "client_id": None, "title": "Team timesheet chase",
     "template_id": None, "next_due_date": "2026-01-01", "is_active": True,
     "frequency": "weekly", "priority": "low"},
    {"id": "C-OTHER-FIRM", "firm_id": "firm-2", "client_id": "c-x", "title": "not ours",
     "template_id": None, "next_due_date": "2026-01-01", "is_active": True,
     "frequency": "monthly", "priority": "low"},
]
RULES = [{"id": "R-1", "firm_id": FIRM, "recurring_config_id": "C-THEIRS"},
         {"id": "R-2", "firm_id": FIRM, "recurring_config_id": "C-MINE"}]
CLIENTS = [{"id": MINE, "firm_id": FIRM, "client_name": "My Client"},
           {"id": THEIRS, "firm_id": FIRM, "client_name": "Acme Holdings"}]


# ── A Supabase stand-in, only as rich as these handlers actually need ─────────

class _Res:
    def __init__(self, data):
        self.data = data


class _FakeQ:
    def __init__(self, name, rows, log):
        self.name, self.rows, self.log = name, rows, log
        self.filters, self.op, self.payload, self.single = [], "select", None, False

    def select(self, *_a, **_k):
        return self

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def delete(self):
        self.op = "delete"
        return self

    def eq(self, col, val):
        self.filters.append(("eq", col, val))
        return self

    def in_(self, col, vals):
        self.filters.append(("in", col, list(vals)))
        return self

    def lte(self, col, val):
        self.filters.append(("lte", col, val))
        return self

    def or_(self, expr):
        self.filters.append(("or", expr, None))
        return self

    def order(self, *_a, **_k):
        return self

    def maybe_single(self):
        self.single = True
        return self

    def execute(self):
        self.log.append((self.name, self.op, list(self.filters)))
        if self.op == "insert":
            return _Res([dict(self.payload, id="NEW")])
        out = list(self.rows)
        for kind, col, val in self.filters:
            if kind == "eq":
                out = [r for r in out if r.get(col) == val]
            elif kind == "in":
                out = [r for r in out if r.get(col) in val]
            elif kind == "lte":
                out = [r for r in out if str(r.get(col, "")) <= str(val)]
        if self.single:
            return _Res(out[0] if out else None)
        return _Res(out)


class _FakeDb:
    def __init__(self, tables):
        self.tables, self.log = tables, []

    def table(self, name):
        return _FakeQ(name, self.tables.get(name, []), self.log)


@pytest.fixture
def db(monkeypatch):
    fake = _FakeDb({"task_recurring_configs": CONFIGS, "assignment_rules": RULES,
                    "clients": CLIENTS, "users": [{"id": "u1", "firm_id": FIRM}],
                    "task_templates": [], "tasks": []})
    monkeypatch.setattr(trc, "_get_db", lambda: fake)
    return fake


@pytest.fixture
def deny(monkeypatch):
    """Refuse one client, allow the rest — a real assignment boundary, and it
    catches a guard that resolves the wrong config's client."""
    seen = []

    def _check(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    monkeypatch.setattr(trc, "assert_client_access", _check)
    return seen


def _writes(db):
    return [(t, op) for t, op, _f in db.log if op in ("insert", "update", "delete")]


# ══════════════════════════════════════════════════════════════════════════════
# The guard itself
# ══════════════════════════════════════════════════════════════════════════════

def test_another_clients_config_is_refused(db, deny):
    with pytest.raises(HTTPException) as e:
        trc._assert_config_scope(USER, "C-THEIRS")
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_your_own_config_resolves_and_is_returned(db, deny):
    assert trc._assert_config_scope(USER, "C-MINE")["client_id"] == MINE


def test_a_config_with_no_client_is_firm_level_not_forbidden(db, deny):
    """Nullable client_id means "the firm's own recurring task". Reading that as
    a refusal would quietly kill every firm-level config in the product."""
    assert trc._assert_config_scope(USER, "C-FIRM")["client_id"] is None
    assert deny == [None]


def test_an_unknown_config_is_the_same_404_as_a_forbidden_one(db, deny):
    with pytest.raises(HTTPException) as missing:
        trc._assert_config_scope(USER, "no-such-config")
    with pytest.raises(HTTPException) as hidden:
        trc._assert_config_scope(USER, "C-THEIRS")
    assert missing.value.status_code == hidden.value.status_code == 404


def test_another_firms_config_is_not_reachable_at_all(db, deny):
    """The firm filter is on the same query, so tenancy is not left to the
    client check to catch."""
    with pytest.raises(HTTPException) as e:
        trc._assert_config_scope(USER, "C-OTHER-FIRM")
    assert e.value.status_code == 404
    assert deny == [], "the client guard was reached for another firm's row"


# ══════════════════════════════════════════════════════════════════════════════
# Every config-addressed endpoint
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("fn,args", [
    ("update_recurring", (trc.RecurringUpdate(title="renamed"),)),
    ("delete_recurring", ()),
    ("list_assignment_rules", ()),
    ("create_assignment_rule", (trc.AssignmentRuleCreate(rule_type="fallback"),)),
])
def test_every_config_endpoint_refuses_before_it_acts(fn, args, db, deny):
    with pytest.raises(HTTPException) as e:
        getattr(trc, fn)("C-THEIRS", *args, current_user=USER)
    assert e.value.status_code == 404
    assert _writes(db) == [], f"{fn} wrote despite the refusal"


@pytest.mark.parametrize("fn,args", [
    ("update_assignment_rule", (trc.AssignmentRuleUpdate(priority=5),)),
    ("delete_assignment_rule", ()),
])
def test_every_rule_endpoint_refuses_before_it_acts(fn, args, db, deny, monkeypatch):
    """`assignment_rules` carries a firm_id and a recurring_config_id and no
    client of its own, so it can only be scoped through its config."""
    touched = []
    for name in ("update", "delete"):
        monkeypatch.setattr(trc.assignment_rule_repo, name,
                            (lambda n: lambda *a, **k: touched.append(n) or {})(name))
    with pytest.raises(HTTPException) as e:
        getattr(trc, fn)("C-THEIRS", "R-1", *args, current_user=USER)
    assert e.value.status_code == 404
    assert touched == [], f"{fn} reached the repository despite the refusal"


def test_deleting_your_own_config_still_works(db, deny):
    out = trc.delete_recurring("C-MINE", current_user=USER)
    assert out["success"] is True
    assert ("task_recurring_configs", "delete") in _writes(db)


def test_listing_the_rules_of_your_own_config_still_works(db, deny, monkeypatch):
    monkeypatch.setattr(trc.assignment_rule_repo, "find_all",
                        lambda **_k: [RULES[1]])
    out = trc.list_assignment_rules("C-MINE", current_user=USER)
    assert out["data"]["total"] == 1


# ── Moving a config between clients touches two clients ──────────────────────

def test_moving_a_config_out_of_another_clients_book_is_refused(db, deny):
    """The destination is one you ARE on, so a destination-only check passes it.
    The config being lifted belongs to somebody else."""
    with pytest.raises(HTTPException) as e:
        trc.update_recurring("C-THEIRS", trc.RecurringUpdate(client_id=MINE),
                             current_user=USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS], "the config's own client was never checked"
    assert _writes(db) == []


def test_moving_your_own_config_into_another_clients_book_is_refused(db, deny):
    """And the mirror image: the source is fine, the destination is not."""
    with pytest.raises(HTTPException):
        trc.update_recurring("C-MINE", trc.RecurringUpdate(client_id=THEIRS),
                             current_user=USER)
    assert deny == [MINE, THEIRS]
    assert _writes(db) == []


def test_editing_your_own_config_still_works(db, deny):
    out = trc.update_recurring("C-MINE", trc.RecurringUpdate(title="renamed"),
                               current_user=USER)
    assert out["success"] is True
    assert ("task_recurring_configs", "update") in _writes(db)


def test_creating_a_config_in_another_clients_book_is_refused(db, deny):
    with pytest.raises(HTTPException):
        trc.create_recurring(
            trc.RecurringCreate(client_id=THEIRS, title="x", frequency="monthly",
                                next_due_date="2026-01-01"),
            current_user=USER)
    assert _writes(db) == []


# ══════════════════════════════════════════════════════════════════════════════
# The list — narrowed, and client-less rows survive it
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def assigned_to(monkeypatch):
    """Drive the REAL `filter_by_client` by setting what the caller is assigned
    to, rather than substituting a lambda that re-implements it. The nullable
    client_id is the whole reason: a hand-written stub would encode my own
    reading of the rule and then agree with itself."""
    def _set(ids):
        monkeypatch.setattr("core.authz.effective_client_ids", lambda _u: ids)
    return _set


def test_the_list_is_narrowed_to_your_clients(db, assigned_to):
    assigned_to({MINE})
    out = trc.list_recurring(current_user=USER)
    assert [c["id"] for c in out["data"]["configs"]] == ["C-MINE", "C-FIRM"]


def test_the_list_never_looks_up_a_filtered_out_clients_name(db, assigned_to):
    """Narrow first, enrich second. The client_name IS the disclosure, so an
    enrich-then-filter ordering would fetch precisely what must not be shown."""
    assigned_to({MINE})
    trc.list_recurring(current_user=USER)
    asked = {cid for name, _op, filters in db.log if name == "clients"
             for kind, col, vals in filters if kind == "in" for cid in vals}
    assert asked == {MINE}


def test_a_caller_assigned_to_nothing_still_sees_the_firms_own_configs(db, assigned_to):
    assigned_to(set())
    out = trc.list_recurring(current_user=USER)
    assert [c["id"] for c in out["data"]["configs"]] == ["C-FIRM"]


def test_a_firmwide_role_sees_every_config_in_the_firm(db, assigned_to):
    assigned_to(None)          # what effective_client_ids returns for a Partner
    out = trc.list_recurring(current_user=PARTNER)
    assert [c["id"] for c in out["data"]["configs"]] == ["C-MINE", "C-THEIRS", "C-FIRM"]


# ══════════════════════════════════════════════════════════════════════════════
# /generate — a WRITE across the firm, so the RUN is confined, not the output
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def generate(monkeypatch):
    captured = {}

    def _gen(firm_id=None, allowed_client_ids=None):
        captured["firm_id"] = firm_id
        captured["allowed_client_ids"] = allowed_client_ids
        return []

    monkeypatch.setattr("services.recurring_task_service.generate_due_recurring_tasks",
                        _gen)
    return captured


def test_generation_is_confined_to_the_clients_you_are_assigned_to(generate, monkeypatch):
    """Without this, anyone in the firm could create tasks in EVERY client's book
    by hitting one endpoint with no parameters at all."""
    monkeypatch.setattr(trc, "effective_client_ids", lambda _u: {MINE})
    trc.generate_tasks(current_user=USER)
    assert generate["allowed_client_ids"] == {MINE}


def test_a_firmwide_role_still_generates_in_one_pass(generate, monkeypatch):
    """None is the service's "no narrowing" signal — the fix must not turn one
    pass into N for the people who legitimately see everyone."""
    monkeypatch.setattr(trc, "effective_client_ids", lambda _u: None)
    trc.generate_tasks(current_user=PARTNER)
    assert generate["allowed_client_ids"] is None


# ── The service end of the same rule ─────────────────────────────────────────

@pytest.fixture
def service_db(monkeypatch):
    fake = _FakeDb({"task_recurring_configs": CONFIGS, "tasks": [],
                    "task_templates": []})
    monkeypatch.setattr("services.recurring_task_service._get_db", lambda: fake)
    monkeypatch.setattr("repositories.user_repository.user_repo.find_all",
                        lambda **_k: [])
    monkeypatch.setattr(
        "repositories.task_extras_repository.task_extras_repo.log_event",
        lambda **_k: {})
    return fake


def _generated_for(service_db, **kwargs):
    from services.recurring_task_service import generate_due_recurring_tasks
    tasks = generate_due_recurring_tasks(firm_id=FIRM, **kwargs)
    return sorted(t["title"] for t in tasks)


def test_the_service_generates_everything_when_not_narrowed(service_db):
    assert _generated_for(service_db) == [
        "Acme board pack", "Monthly GSTR-1", "Team timesheet chase"]


def test_the_service_skips_configs_outside_the_allowed_clients(service_db):
    assert _generated_for(service_db, allowed_client_ids={MINE}) == [
        "Monthly GSTR-1", "Team timesheet chase"]


def test_a_firm_level_config_survives_a_narrowed_run(service_db):
    """The config with no client belongs to the firm, not to a book somebody is
    or isn't assigned to. An empty assignment set still generates it — and
    generates nothing else."""
    assert _generated_for(service_db, allowed_client_ids=set()) == [
        "Team timesheet chase"]
