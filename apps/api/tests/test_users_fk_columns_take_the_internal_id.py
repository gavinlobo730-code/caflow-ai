"""
A column that FKs public.users(id) is written with the INTERNAL user id.

WHAT WAS WRONG
    current_user carries two ids: "id" (public.users.id) and "auth_user_id"
    (Supabase's). CLAUDE.md says which one a users-FK column takes. The
    year-end review workflow wrote the OTHER one into submitted_by,
    approved_by, revision_requested_by and final_approved_by — and users.id
    never equals auth_user_id (checked on production: 0 of 2) — so every
    submit / approve / request-revision / final-approve raised SQLSTATE 23503,
    unguarded. The bank column mapper made the identical mistake the same
    week and was caught only by a live database.

WHY THE MOCK SUITE COULD NOT SEE EITHER
    Mock mode has no foreign keys. An FK violation is invisible to ~9,000
    tests, and the one review-workflow test seeded users by auth_user_id and
    read them back by auth_user_id, so it was consistent with the bug.

The first test here is a source-level guard on the file that was wrong. The
second is the pattern: it needs the real schema to know which columns FK
users, so it lives with the _pg tests and runs in CI's migration-apply job.
"""
import ast
import os
import pathlib
import re
import subprocess

import pytest

API = pathlib.Path(__file__).resolve().parent.parent
_PG = os.environ.get("HARNESS_PG")


def test_the_review_workflow_writes_the_internal_id():
    src = (API / "routers" / "year_end_reviews.py").read_text()
    for col in ("submitted_by", "approved_by", "revision_requested_by", "final_approved_by"):
        bad = re.findall(rf'"{col}"\s*:\s*current_user\.get\("auth_user_id"\)', src)
        assert not bad, f"{col} is a public.users(id) FK; auth_user_id can never satisfy it"
        assert re.search(rf'"{col}"\s*:\s*current_user\.get\("id"\)', src), col
    # The review trail's actor and the name lookup have to agree on WHICH id.
    assert 'current_user.get("id"), data.comment)' in src
    assert '.in_("id", list(actor_ids))' in src
    assert 'in_("auth_user_id"' not in src


def test_the_audit_log_actor_is_deliberately_untouched():
    """audit_log.actor_id has no FK and takes the auth id everywhere in the
    codebase. Fixing the review columns must not have swept it along.

    THIS TEST WAS PINNING THE BUG. It asserted the literal string
    `actor_id=current_user.get("auth_user_id"), actor_email=` anywhere in the
    file, and in that file exactly ONE call wrote those two arguments on one
    line: the `lock_year_if_completing(...)` call, whose actor_id reaches
    client_year_locks.locked_by — a public.users(id) FK that an auth id can
    never satisfy. Every log_event call spelt the same pair across two lines
    and so was never what the assertion matched. A guard that names a SPELLING
    rather than the rule can end up holding the defect in place, which is what
    happened here.

    So the question is asked properly now: it is log_event, and only log_event,
    that takes the auth id.
    """
    src = (API / "routers" / "year_end_reviews.py").read_text()

    # Every log_event call passes the AUTH id...
    calls = re.findall(r"log_event\((?:[^()]|\([^()]*\))*\)", src, re.S)
    assert calls, "no log_event calls found — the guard is asserting nothing"
    for call in calls:
        assert 'actor_id=current_user.get("auth_user_id")' in call, call

    # ...and nothing that reaches a users-FK column does. lock_year_if_completing
    # is named because its actor_id lands in client_year_locks.locked_by; the
    # auth id belongs in its actor_auth_id, which goes to audit_log.
    for fn in ("lock_year_if_completing", "unlock_year_on_reopen", "set_client_lock"):
        for call in re.findall(rf"{fn}\((?:[^()]|\([^()]*\))*\)", src, re.S):
            assert 'actor_id=current_user.get("auth_user_id")' not in call, call
            if "actor_id=" in call:
                assert 'actor_id=current_user.get("id")' in call, call


def test_the_year_lock_takes_the_internal_id_through_every_caller():
    """The instance the _pg sweep below could not see (ACC-05).

    client_year_locks.locked_by FKs public.users(id) and is written in
    services/year_lock_service.py as `"locked_by": actor_id` — a PARAMETER.
    The auth id was supplied one frame up, by the two routers that call
    lock_year_if_completing. The sweep looks for the column name and the auth
    id in the same window of source, so a value that crosses a function
    boundary is invisible to it: the write site has no `auth_user_id` in sight
    and the call site has no `locked_by`.

    Consequence, had it ever run against the live database: SQLSTATE 23503 out
    of set_client_lock, AFTER routers/year_end.py and year_end_reviews.py had
    already written status='locked' on the engagement row. The engagement
    would read as finalised — terminal, before ACC-05's reopen existed — while
    the client's year stayed open to posting. Latent only because production
    holds no year-end engagements yet.
    """
    for router in ("year_end.py", "year_end_reviews.py"):
        src = (API / "routers" / router).read_text()
        for fn in ("lock_year_if_completing", "unlock_year_on_reopen"):
            for call in re.findall(rf"{fn}\((?:[^()]|\([^()]*\))*\)", src, re.S):
                if "actor_id=" not in call:
                    continue
                assert 'actor_id=current_user.get("id")' in call, (router, call)
                assert 'actor_auth_id=current_user.get("auth_user_id")' in call, (router, call)

    svc = (API / "services" / "year_lock_service.py").read_text()
    # The split has to exist in the service too, or the routers are passing an
    # argument nothing reads.
    assert "actor_auth_id" in svc
    assert '"locked_by": actor_id' in svc, "locked_by must take the internal id"
    assert "actor_id=actor_auth_id or actor_id" in svc, (
        "audit_log attribution keeps the auth id, falling back to the internal "
        "one rather than recording nobody")


@pytest.mark.skipif(not _PG, reason="needs HARNESS_PG — reads the real FK list")
def test_no_router_writes_the_auth_id_into_a_users_fk_column(pg_template):
    """The pattern, not the instance. Read every (table, column) that FKs
    public.users from the schema, then refuse any insert/update payload that
    sets one of them from auth_user_id.

    Reads the session's pre-migrated template database directly: the query
    only SELECTs from the catalogue, so there is nothing to isolate and no
    reason to pay for a clone. HARNESS_PG carries no dbname on purpose — every
    _pg test names its own — and pointing psql at it bare lands on the
    `postgres` database, which has no public.users."""
    out = subprocess.run(
        ["psql", f"{_PG} dbname={pg_template.name}", "-Atc",
         "select c.conrelid::regclass::text||'|'||a.attname "
         "from pg_constraint c join pg_attribute a "
         "  on a.attrelid=c.conrelid and a.attnum=c.conkey[1] "
         "where c.contype='f' and c.confrelid='public.users'::regclass"],
        capture_output=True, text=True, check=True).stdout
    pairs: dict[str, set[str]] = {}
    for line in out.splitlines():
        if "|" in line:
            t, c = line.split("|", 1)
            pairs.setdefault(t.replace("public.", ""), set()).add(c)
    assert pairs, "the FK list came back empty — the query or the schema is wrong"

    offenders = []
    for path in sorted((API / "routers").glob("*.py")) + sorted((API / "services").glob("*.py")):
        src = path.read_text()
        for m in re.finditer(r'\.table\(\s*["\'](?P<t>[a-z_]+)["\']\s*\)', src):
            cols = pairs.get(m.group("t"))
            if not cols:
                continue
            window = src[max(0, m.start() - 1500): m.end() + 1500]
            for col in cols:
                if re.search(rf'["\']{col}["\']\s*:\s*[^,\n]*auth_user_id', window):
                    offenders.append(f"{path.name}: {m.group('t')}.{col}")
    assert not offenders, (
        "these columns FK public.users(id) but are set from the Supabase auth "
        "id, which can never satisfy the FK:\n  " + "\n  ".join(sorted(set(offenders))))


# ── One level of indirection, which is where this last hid ───────────────────

def _users_fk_pairs(pg_template) -> dict[str, set[str]]:
    out = subprocess.run(
        ["psql", f"{_PG} dbname={pg_template.name}", "-Atc",
         "select c.conrelid::regclass::text||'|'||a.attname "
         "from pg_constraint c join pg_attribute a "
         "  on a.attrelid=c.conrelid and a.attnum=c.conkey[1] "
         "where c.contype='f' and c.confrelid='public.users'::regclass"],
        capture_output=True, text=True, check=True).stdout
    pairs: dict[str, set[str]] = {}
    for line in out.splitlines():
        if "|" in line:
            t, c = line.split("|", 1)
            pairs.setdefault(t.replace("public.", ""), set()).add(c)
    return pairs


def _source_files() -> list[pathlib.Path]:
    return (sorted((API / "routers").glob("*.py"))
            + sorted((API / "services").glob("*.py"))
            + sorted((API / "domain").rglob("*.py")))


def _table_names_in(node: ast.AST) -> set[str]:
    """Every `.table("X")` reached from this expression."""
    names = set()
    for n in ast.walk(node):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "table" and len(n.args) == 1
                and isinstance(n.args[0], ast.Constant)
                and isinstance(n.args[0].value, str)):
            names.add(n.args[0].value)
    return names


def _params_carrying_a_users_id(tree: ast.AST, pairs: dict[str, set[str]]) -> set[str]:
    """Parameter names whose value is written straight into a users-FK column.

    `{"locked_by": actor_id}` inside `.table("client_year_locks").insert(...)`
    makes `actor_id` a parameter that MUST receive an internal user id.
    """
    carriers: set[str] = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        params = {a.arg for a in
                  fn.args.args + fn.args.kwonlyargs + fn.args.posonlyargs}
        for call in ast.walk(fn):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and call.func.attr in ("insert", "update", "upsert")):
                continue
            tables = _table_names_in(call.func.value)
            cols = set().union(*(pairs.get(t, set()) for t in tables)) if tables else set()
            if not cols:
                continue
            for arg in call.args:
                for d in ast.walk(arg):
                    if not isinstance(d, ast.Dict):
                        continue
                    for k, v in zip(d.keys, d.values):
                        if (isinstance(k, ast.Constant) and k.value in cols
                                and isinstance(v, ast.Name) and v.id in params):
                            carriers.add(f"{fn.name}:{v.id}")
    return carriers


@pytest.mark.skipif(not _PG, reason="needs HARNESS_PG — reads the real FK list")
def test_no_caller_passes_the_auth_id_into_a_parameter_that_becomes_a_users_fk(pg_template):
    """The sweep above, but across the function boundary.

    THE HOLE IT CLOSES. The sweep above reads a window of source around each
    `.table("X")` and looks for the auth id beside the column name. In
    services/year_lock_service.py the write is `"locked_by": actor_id` — a
    parameter — and the auth id was supplied by routers/year_end.py and
    routers/year_end_reviews.py, one frame away. Neither half of the pattern
    was ever in the same window as the other, so a guard written specifically
    for this bug did not see this instance of it (ACC-05).

    So: find the parameters that BECOME a users-FK column, then check what
    every caller passes into them. This is the same lesson as the money-parser
    guard in CLAUDE.md — a rule beats a spelling, and each new spelling of a
    defect is a defect the old guard is blind to.
    """
    pairs = _users_fk_pairs(pg_template)
    assert pairs, "the FK list came back empty — the query or the schema is wrong"

    # function name -> the parameters of it that reach a users-FK column
    carriers: dict[str, set[str]] = {}
    for path in _source_files():
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:                                       # pragma: no cover
            continue
        for entry in _params_carrying_a_users_id(tree, pairs):
            fn, param = entry.split(":", 1)
            carriers.setdefault(fn, set()).add(param)
    assert carriers, "no users-FK writes found at all — the AST walk is wrong"

    # A function that only FORWARDS a carrier's parameter is a carrier too, so
    # the chain router -> workflow service -> lock service is followed whole.
    for _ in range(4):                       # depth 4 is far past anything here
        grew = False
        for path in _source_files():
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:                                   # pragma: no cover
                continue
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                params = {a.arg for a in
                          fn.args.args + fn.args.kwonlyargs + fn.args.posonlyargs}
                for call in ast.walk(fn):
                    if not isinstance(call, ast.Call):
                        continue
                    callee = (call.func.attr if isinstance(call.func, ast.Attribute)
                              else getattr(call.func, "id", None))
                    for kw in call.keywords:
                        if (kw.arg in carriers.get(callee or "", set())
                                and isinstance(kw.value, ast.Name)
                                and kw.value.id in params):
                            before = len(carriers.get(fn.name, set()))
                            carriers.setdefault(fn.name, set()).add(kw.value.id)
                            grew = grew or len(carriers[fn.name]) != before
        if not grew:
            break

    offenders = []
    for path in _source_files():
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:                                       # pragma: no cover
            continue
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            callee = (call.func.attr if isinstance(call.func, ast.Attribute)
                      else getattr(call.func, "id", None))
            for kw in call.keywords:
                if kw.arg not in carriers.get(callee or "", set()):
                    continue
                if "auth_user_id" in ast.unparse(kw.value):
                    offenders.append(f"{path.name}: {callee}({kw.arg}=...) "
                                     f"is written into a public.users(id) FK")
    assert not offenders, (
        "these arguments end up in a column that FKs public.users(id), but are "
        "supplied from the Supabase auth id:\n  " + "\n  ".join(sorted(set(offenders))))
