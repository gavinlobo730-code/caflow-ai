"""POST-A-361 (parts 1 and 3) — the member check (migration 566) leaves two things alone on purpose, and each rests on a premise a test now holds.

WHAT THE MEMBER CHECK IS
    Migration 566 makes the database refuse a row that names a member of another firm. Two corners were left open in the ledger, and each is
    DECIDED here rather than built, because what would close them is either a worse trade or has nothing to guard:

    (1) THE PORTAL CONTACT. `client_portal_sessions.portal_contact_id` is a bare uuid: no table has a foreign key to `client_portal_users`, so
        566's catalog cannot see it. It STAYS bare, and the reasons are the three ways a key would be wrong for a LOG: `ON DELETE CASCADE` would
        delete the access record when a contact is removed, `ON DELETE SET NULL` would blank who it was (the row keeps only the email),
        and `RESTRICT` would stop a contact from ever being removed. What makes a bare column safe is WHO WRITES IT: one place,
        `core.portal_auth._touch_portal_session`, with the privileged client (since migration 542 nobody signed in can write the table),
        and every id it writes comes from the membership the portal dependency has just resolved for the verified sign-in, never from a request.
        The premise is that, and the first test below fails the day a second writer appears or the writer takes a value from anywhere else.

    (3) A MEMBER WHO CHANGES FIRM. 566 checks a row when it is written or when a member column of it changes, so a member who moved to another
        firm would leave rows that already name them in the old one unchecked. Nothing moves a member: no API write to `users` sets
        `firm_id` (the writers set `first_run_dismissed_at`, `cost_rate_paise` and `default_billable_rate_paise`, and onboarding INSERTS a
        member into a firm once), no migration's SQL updates it, and the signed-in role holds no UPDATE privilege on the column (production,
        read-only, 1-11-2026: no table-level UPDATE and no column-level one on `firm_id` or `role`; the two policies are the own-row select and
        the own-row rename). The second and third tests hold the first two halves and the real-Postgres test the third.

WHAT THE PROBES CANNOT SEE (and which way each limit fails)
    * The users-write probe reads a payload only when it is a dict LITERAL. A payload built in a variable, or spread from another dict, is
      reported as UNREADABLE and the test fails, so the blind spot fails towards tripping and not towards holding.
    * A write through a different door (a raw SQL function, an RPC, `execute_sql`) is not a `.table("users")` call; the migrations are read as text
      for `UPDATE users SET ... firm_id`, and a database function that does it would be in a migration.
    * `getattr`/string dispatch to `table`, and a table name held in a variable, are not seen.
"""
from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[1]
SKIP_DIRS = {"tests", "migrations", "scripts", "__pycache__", "venv", ".venv", "node_modules"}


def _python_files(root: Path):
    for path in sorted(root.rglob("*.py")):
        if not (set(path.relative_to(root).parts) & SKIP_DIRS):
            yield path


def _table_of(call: ast.AST) -> str | None:
    """The table a `.table("x")` or `.from_("x")` call names, or None."""
    if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr in {"table", "from_"}
            and call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str)):
        return call.args[0].value
    return None


def _root_table(node: ast.AST) -> str | None:
    """The table at the root of a builder chain (`db.table("users").update(...).eq(...)` -> "users")."""
    while isinstance(node, (ast.Call, ast.Attribute)):
        named = _table_of(node)
        if named:
            return named
        node = node.func if isinstance(node, ast.Call) else node.value
    return None


def table_writes(source: str, table: str, methods: frozenset[str]) -> list[tuple[int, str, ast.AST | None]]:
    """(line, method, payload) of every `<chain rooted at table(...)>.<method>(payload)` in `source`."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in methods
                and _root_table(node.func.value) == table):
            payload = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg in {"json", "values", "data"}), None)
            found.append((node.lineno, node.func.attr, payload))
    return found


def keys_of(payload: ast.AST | None) -> set[str] | None:
    """The literal keys of a dict payload, or None when it cannot be read (a variable, a call, a spread)."""
    if not isinstance(payload, ast.Dict) or any(k is None or not isinstance(k, ast.Constant) for k in payload.keys):
        return None
    return {str(k.value) for k in payload.keys}


# ── (1) the portal session log has one writer and it writes what it was just handed ───────────────────────────────────────────────────

def _portal_writers():
    out = []
    for path in _python_files(API):
        for line, method, payload in table_writes(path.read_text(encoding="utf-8"), "client_portal_sessions", frozenset({"insert", "upsert", "update"})):
            out.append((path.relative_to(API).as_posix(), line, method, payload))
    return out


def test_the_portal_session_log_has_one_writer_and_every_value_it_writes_comes_from_the_resolved_membership():
    writers = _portal_writers()
    assert [(rel, method) for rel, _, method, _ in writers] == [("core/portal_auth.py", "insert")], (
        "client_portal_sessions is written from somewhere other than core.portal_auth._touch_portal_session, or by something other than an "
        "insert. Its `portal_contact_id` is a bare uuid ON PURPOSE (a key would cascade away, blank or block the access log), and what makes "
        f"that safe is that one writer takes every value from the resolved membership. Found: {writers!r}")
    (_, _, _, payload), = writers
    assert isinstance(payload, ast.Dict), "the writer's payload is not a dict literal"
    wanted = {"firm_id", "client_id", "portal_contact_id", "email"}
    assert keys_of(payload) == wanted, f"the writer's columns changed: {keys_of(payload)}"
    for key, value in zip(payload.keys, payload.values, strict=True):
        ok = (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) and value.func.attr == "get"
              and isinstance(value.func.value, ast.Name) and value.func.value.id == "ctx" and value.args
              and isinstance(value.args[0], ast.Constant) and value.args[0].value == key.value)
        assert ok, f"`{key.value}` is not ctx.get({key.value!r}): a value the portal log stores comes from somewhere else than the resolved membership"


def test_the_writer_is_handed_only_the_membership_the_portal_dependency_resolved():
    src = (API / "core" / "portal_auth.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    calls = [(fn.name, node.lineno) for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef)
             for node in ast.walk(fn) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_touch_portal_session"]
    assert [name for name, _ in calls] == ["get_current_portal_client"], f"_touch_portal_session is called from {calls!r}"
    body = next(fn for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef) and fn.name == "get_current_portal_client")
    text = ast.get_source_segment(src, body) or ""
    assert "select_active_membership" in text and "list_portal_memberships" in text and "_touch_portal_session(ctx)" in text, (
        "the context handed to the log is no longer built from the memberships of the verified sign-in")
    for other in (p for p in _python_files(API) if p.relative_to(API).as_posix() != "core/portal_auth.py"):
        assert "_touch_portal_session" not in other.read_text(encoding="utf-8"), f"{other} reaches the portal log's writer"


# ── (3) nothing moves a member from one firm to another ──────────────────────────────────────────────────────────────────────────────

def _user_writes():
    out = []
    for path in _python_files(API):
        for line, method, payload in table_writes(path.read_text(encoding="utf-8"), "users", frozenset({"update", "upsert", "insert"})):
            out.append((path.relative_to(API).as_posix(), line, method, payload))
    return out


#: Writes whose payload is a variable, reviewed by hand, and why each cannot move a member. Every other write reads as a dict literal.
REVIEWED = {
    ("repositories/user_repository.py", "update"): (
        "UserRepository.update takes a dict from its callers and refuses one that names another firm BEFORE it reaches the database "
        "(`test_the_one_variable_payload_refuses_a_move_before_it_reaches_the_database`), and its filter carries the caller's firm as well"),
}


def test_no_write_to_users_sets_a_firm_on_an_existing_member():
    unreadable, moving = [], []
    for rel, line, method, payload in _user_writes():
        keys = keys_of(payload)
        if method == "insert":
            continue                    # creating a member INTO a firm is not moving one (onboarding does it once; it first asks for an existing row)
        if keys is None and (rel, method) in REVIEWED:
            continue
        if keys is None:
            unreadable.append(f"{rel}:{line} {method}")
        elif "firm_id" in keys:
            moving.append(f"{rel}:{line} {method} {sorted(keys)}")
    assert not unreadable, (
        "an update or upsert of `users` whose payload is not a dict literal cannot be read, so it cannot be shown NOT to set `firm_id`; "
        f"write the payload as a literal or review it and extend this test: {unreadable}")
    assert not moving, (f"a write moves a member to another firm: {moving}. Migration 566 does not re-check the rows that already name that "
                        "member in their old firm; do that first (ledger POST-A-361, part 3).")
    assert any(method == "update" for _, _, method, _ in _user_writes()), "the probe found no update of users at all: it is blind, not clean"


def test_the_one_variable_payload_refuses_a_move_before_it_reaches_the_database():
    from repositories.user_repository import user_repo
    with pytest.raises(ValueError, match="cannot move a user to another firm"):
        user_repo.update("m1", {"firm_id": "firm-B", "full_name": "x"}, firm_id="firm-A")
    src = (API / "repositories" / "user_repository.py").read_text(encoding="utf-8")
    update = src[src.index("    def update(self"):]
    assert update.index('"firm_id" in data and data["firm_id"] != firm_id') < update.index('.table("users")'), "the refusal comes after the write"
    assert '.eq("id", id).eq("firm_id", firm_id)' in update, "the write is not filtered by the caller's firm"


def test_the_probe_sees_a_write_that_moves_a_member_and_one_it_cannot_read():
    bad = 'def f(db):\n    db.table("users").update({"firm_id": "x"}).eq("id", 1).execute()\n    db.from_("users").upsert(payload)\n    db.table("firms").update({"firm_id": 1})\n'
    seen = sorted(table_writes(bad, "users", frozenset({"update", "upsert"})), key=lambda w: w[0])
    assert [(m, keys_of(p)) for _, m, p in seen] == [("update", {"firm_id"}), ("upsert", None)]
    assert keys_of(ast.parse('x = {"a": 1, **other}', mode="exec").body[0].value) is None


def test_no_migration_updates_the_firm_of_a_member():
    pattern = re.compile(r"UPDATE\s+(?:public\.)?users\s+SET\b[^;]*\bfirm_id\b", re.IGNORECASE | re.DOTALL)
    hits = [p.name for p in sorted((API / "migrations").glob("*.sql")) if pattern.search(p.read_text(encoding="utf-8"))]
    assert not hits, f"a migration updates users.firm_id: {hits}"


# ── (3, the database half) the signed-in role cannot change a member's firm ───────────────────────────────────────────────────────────

_ADMIN = os.environ.get("HARNESS_PG")


@pytest.mark.skipif(not _ADMIN or shutil.which("psql") is None, reason="requires HARNESS_PG + psql")
def test_the_signed_in_role_holds_no_update_on_a_members_firm_or_role_in_a_migration_built_database(pg_template):
    dsn = f"{_ADMIN.strip()} dbname={pg_template.name}"
    sql = ("select has_table_privilege('authenticated','public.users','UPDATE')::text || ',' || "
           "has_column_privilege('authenticated','public.users','firm_id','UPDATE')::text || ',' || "
           "has_column_privilege('authenticated','public.users','role','UPDATE')::text;")
    done = subprocess.run(["psql", dsn, "-X", "-q", "-tA", "-c", sql], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "false,false,false", (
        f"the signed-in role can update users ({done.stdout.strip()}: table, firm_id, role): a member could be moved to another firm from a "
        "browser, and migration 566 would not re-check the rows that already name them (ledger POST-A-361, part 3)")
