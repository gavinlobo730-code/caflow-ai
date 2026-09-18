"""
The write door for per-person access (migration 403).

Three refusals, and they are NOT interchangeable — a shared "that is not
allowed" would say the wrong thing about two of them:

  * an unknown (resource, action) pair — the column is free TEXT with no CHECK,
    because the vocabulary is a Python dict and SQL cannot read one, so this
    door is where the vocabulary is enforced;
  * denying a Partner a pair in UNREVOKABLE_FOR_PARTNER — refused here as well
    as ignored by the resolver, because a door that silently accepted a write
    the resolver then ignored would be a control that does nothing, which is
    the exact fault the read-only Team grid was left as a monument to;
  * a member of another firm — `users.id` is a global key, so without the check
    the caller could write a row against anybody's account in the database.

And one invariant over all three: NOTHING is written if ANY change is refused.
A request carrying one bad pair must change nothing rather than half of what
was asked, or a Partner fixing a typo silently applies the rest.
"""
import pytest

from core.permissions import UNREVOKABLE_FOR_PARTNER, can_user
from services import user_permission_service as svc
from services.user_permission_service import PermissionWriteRefused


class _Table:
    def __init__(self, store, name):
        self._store, self._name = store, name
        self._filters, self._op, self._payload = {}, None, None

    def select(self, *a, **k):
        self._op = "select"; return self

    def insert(self, payload):
        self._op, self._payload = "insert", payload; return self

    def update(self, payload):
        self._op, self._payload = "update", payload; return self

    def delete(self):
        self._op = "delete"; return self

    def eq(self, col, val):
        self._filters[col] = val; return self

    def gt(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self

    def _matching(self):
        return [r for r in self._store.rows
                if all(str(r.get(c)) == str(v) for c, v in self._filters.items())]

    def execute(self):
        if self._op == "select":
            return type("R", (), {"data": list(self._matching())})()
        if self._op == "insert":
            row = {"id": f"p{len(self._store.rows) + 1}", **self._payload}
            self._store.rows.append(row)
            self._store.writes.append(("insert", row))
            return type("R", (), {"data": [row]})()
        if self._op == "update":
            for r in self._matching():
                r.update(self._payload)
                self._store.writes.append(("update", dict(r)))
            return type("R", (), {"data": []})()
        if self._op == "delete":
            gone = self._matching()
            for r in gone:
                self._store.rows.remove(r)
                self._store.writes.append(("delete", dict(r)))
            return type("R", (), {"data": []})()
        raise AssertionError(f"unexpected op {self._op}")


class _DB:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.writes = []

    def table(self, name):
        assert name == "user_permissions", f"unexpected table {name}"
        return _Table(self, name)


FIRM = "f1"
EXEC = {"id": "u-exec", "role": "Executive", "full_name": "Priya", "email": "p@f", "firm_id": FIRM}
PARTNER = {"id": "u-partner", "role": "Partner", "full_name": "Rahul", "email": "r@f", "firm_id": FIRM}


def _grant(db, member, **changes):
    return svc.set_permissions(db, FIRM, member, changes, actor_id="actor")


# ── The happy path, and the three states ─────────────────────────────────────

def test_a_grant_is_stored_and_takes_effect():
    db = _DB()
    grid = _grant(db, EXEC, **{"payroll:write": True})
    assert grid["overrides"]["payroll:write"] is True
    assert "write" in grid["effective"]["payroll"]
    # And what rbac() would do, resolved from the same overrides.
    assert can_user({"role": "Executive", "permission_overrides": grid["overrides"]},
                    "payroll", "write") is True


def test_a_block_is_stored_and_takes_effect():
    db = _DB()
    grid = _grant(db, PARTNER, **{"payroll:finalize": False})
    assert grid["overrides"]["payroll:finalize"] is False
    assert "finalize" not in grid["effective"].get("payroll", [])


def test_none_deletes_the_row_and_is_not_a_block():
    """The difference that makes the third state necessary: after clearing, the
    person follows their ROLE again — including a later change to it."""
    db = _DB()
    _grant(db, EXEC, **{"payroll:write": True})
    assert db.rows, "the grant should have been stored"
    grid = _grant(db, EXEC, **{"payroll:write": None})
    assert db.rows == [], "null must DELETE the row, not store false"
    assert "payroll:write" not in grid["overrides"]
    assert "write" not in grid["effective"].get("payroll", [])


def test_setting_the_same_value_again_writes_nothing():
    db = _DB()
    _grant(db, EXEC, **{"payroll:write": True})
    db.writes.clear()
    _grant(db, EXEC, **{"payroll:write": True})
    assert db.writes == [], "an unchanged value must not produce an UPDATE"


def test_clearing_a_pair_that_has_no_row_writes_nothing():
    db = _DB()
    _grant(db, EXEC, **{"payroll:write": None})
    assert db.writes == []


# ── The three refusals, each its own ─────────────────────────────────────────

def test_an_unknown_pair_is_refused_and_names_the_vocabulary():
    db = _DB()
    with pytest.raises(PermissionWriteRefused) as e:
        _grant(db, EXEC, **{"tarot:read": True})
    assert "not a permission" in str(e.value)
    assert "permission-vocabulary" in str(e.value)


@pytest.mark.parametrize("resource,action", sorted(UNREVOKABLE_FOR_PARTNER))
def test_a_partner_cannot_be_denied_the_pairs_that_reach_this_screen(resource, action):
    db = _DB()
    with pytest.raises(PermissionWriteRefused) as e:
        _grant(db, PARTNER, **{f"{resource}:{action}": False})
    assert "nobody able to put it back" in str(e.value)


@pytest.mark.parametrize("resource,action", sorted(UNREVOKABLE_FOR_PARTNER))
def test_granting_a_partner_those_pairs_is_fine(resource, action):
    """The refusal is about DENYING. A redundant grant is harmless and must not
    be turned into an error by a check written as "this pair is special"."""
    db = _DB()
    _grant(db, PARTNER, **{f"{resource}:{action}": True})


@pytest.mark.parametrize("resource,action", sorted(UNREVOKABLE_FOR_PARTNER))
def test_a_non_partner_can_still_be_denied_them(resource, action):
    db = _DB()
    grid = _grant(db, EXEC, **{f"{resource}:{action}": False})
    assert grid["overrides"][f"{resource}:{action}"] is False


def test_a_malformed_key_is_refused():
    db = _DB()
    with pytest.raises(PermissionWriteRefused) as e:
        _grant(db, EXEC, **{"payroll": True})
    assert "resource:action" in str(e.value)


def test_a_non_boolean_value_is_refused_rather_than_coerced():
    db = _DB()
    for bad in ("true", 1, [], {}):
        with pytest.raises(PermissionWriteRefused):
            svc.set_permissions(db, FIRM, EXEC, {"payroll:write": bad}, actor_id="a")


# ── Nothing is written if anything is refused ────────────────────────────────

def test_one_bad_pair_changes_nothing_at_all():
    """A Partner who mistypes one row must not silently have the other nine
    applied — they would have no way to tell which took."""
    db = _DB()
    with pytest.raises(PermissionWriteRefused):
        svc.set_permissions(db, FIRM, EXEC, {
            "payroll:write": True,
            "gst:approve": True,
            "tarot:read": True,          # <- the bad one, listed last
        }, actor_id="a")
    assert db.writes == [], "a refused request must write nothing"
    assert db.rows == []


def test_a_partner_floor_violation_also_rolls_the_whole_request_back():
    db = _DB()
    with pytest.raises(PermissionWriteRefused):
        svc.set_permissions(db, FIRM, PARTNER, {
            "payroll:write": False,
            "team:write": False,         # <- refused
        }, actor_id="a")
    assert db.rows == []


# ── Clearing an obsolete row stays possible ──────────────────────────────────

def test_a_row_from_an_older_vocabulary_can_be_cleared():
    """Refusing `null` on an unknown pair would make such a row permanent, and
    the resolver already treats it as inert — so removing it must be allowed."""
    db = _DB(rows=[{"id": "p1", "firm_id": FIRM, "user_id": "u-exec",
                    "resource": "tarot", "action": "read", "granted": True}])
    svc.set_permissions(db, FIRM, EXEC, {"tarot:read": None}, actor_id="a")
    assert db.rows == []


# ── The grid answers three different questions ───────────────────────────────

def test_the_grid_shows_the_template_the_overrides_and_the_effect():
    db = _DB()
    grid = _grant(db, EXEC, **{"payroll:write": True, "task:write": False})
    assert "write" not in grid["role_defaults"].get("payroll", []), "the role does not give this"
    assert "write" in grid["effective"]["payroll"], "the person does"
    assert "write" in grid["role_defaults"]["task"], "the role gives this"
    assert "write" not in grid["effective"].get("task", []), "the person does not"


# ── The vocabulary is derived, never listed ──────────────────────────────────

def test_the_vocabulary_is_every_pair_permissions_defines():
    from core.permissions import PERMISSIONS
    served = {(p["resource"], p["action"]) for p in svc.vocabulary()}
    real = {(r, a) for r, actions in PERMISSIONS.items() for a in actions}
    assert served == real
