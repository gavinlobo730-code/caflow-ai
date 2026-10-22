"""The monthly balances the reports read are written by one module, with the privileged client (ledger POST-A-318, migration 534).

THE DEFECT
    `account_period_balances` is read DIRECTLY by the trial balance, profit and loss, balance sheet, ratios, budgets, cash flow and
    the year-end statements, and was writable by every signed-in member (`authenticated` held INSERT, UPDATE and DELETE and the
    only policy was the firm-and-client one): an assigned Executive rewrote a bucket of a closed year with no journal entry.
    Migration 534 revokes the verbs and the function that applies a posted line; its own test is the real-Postgres one.

WHAT IS HELD (no database)
    * (source, derived from the AST of the whole API, not a list of files) the only code that writes the table is
      `services/balance_cache_service.recompute_client`; nothing else in `apps/api` inserts, updates, upserts or deletes it, and
      nothing calls the `apb_` database functions;
    * the callers of that module's two entry points are the nightly job and itself, and the job hands them
      `db_provider.service_db`, the privileged client, never a request's;
    * the browser (`apps/web`) names the table in comments only: it does not `.from()` it.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = API_ROOT.parents[1] / "apps" / "web"
TABLE = "account_period_balances"
WRITE_VERBS = {"insert", "update", "delete", "upsert"}
ENTRY_POINTS = {"recompute_client", "audit_and_heal_client", "audit_and_heal_firm"}
WRITER_MODULE = "services/balance_cache_service.py"
RAW_WRITE = re.compile(r"\b(insert\s+into|update|delete\s+from|truncate(\s+table)?)\s+(only\s+)?(public\.)?%s\b" % TABLE, re.I)


def _production_sources():
    """Every Python module the API runs or ships, `scripts/` included (a one-off script run with a service key is still a writer)."""
    for path in sorted(API_ROOT.rglob("*.py")):
        rel = path.relative_to(API_ROOT).as_posix()
        if rel.startswith(("tests/", "migrations/", ".venv", "venv/")) or "/.venv/" in rel or "/venv/" in rel:
            continue
        yield rel, path.read_text(encoding="utf-8")


def _uses_of_the_table(source: str):
    """(kind, function, line, verbs) for every place `account_period_balances` is named as a value or written in SQL text.

    kind is `write` (a write verb chained off `.table(...)` / `.from_(...)`), `read` (a chain with no write verb),
    `unchained` (`q = db.table("account_period_balances")`: what is done to it is not visible, so it counts as a use to be
    explained), `named` (the name as a bare string used any other way: a constant, an argument, a list) and `raw_write`
    (INSERT INTO / UPDATE / DELETE FROM / TRUNCATE in a string). A docstring is not a use.
    """
    tree = ast.parse(source)
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                docstrings.add(body[0].value)

    def enclosing(node):
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node.name
        return "<module>"

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node not in docstrings:
            if RAW_WRITE.search(node.value):
                yield "raw_write", enclosing(node), node.lineno, []
                continue
            if node.value != TABLE:
                continue
            call = parents.get(node)
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr in {"table", "from_"}
                    and node in call.args):
                verbs, up = [], call
                while True:
                    parent = parents.get(up)
                    if isinstance(parent, ast.Attribute) and isinstance(parents.get(parent), ast.Call):
                        verbs.append(parent.attr)
                        up = parents[parent]
                    else:
                        break
                if [v for v in verbs if v in WRITE_VERBS]:
                    yield "write", enclosing(node), node.lineno, [v for v in verbs if v in WRITE_VERBS]
                elif not verbs:
                    yield "unchained", enclosing(node), node.lineno, []
                else:
                    yield "read", enclosing(node), node.lineno, verbs
            else:
                yield "named", enclosing(node), node.lineno, []


def test_only_the_balance_cache_service_writes_the_table_and_nobody_names_it_in_a_way_that_hides_a_write():
    found = {}
    for rel, text in _production_sources():
        if TABLE not in text:
            continue
        for kind, fn, line, verbs in _uses_of_the_table(text):
            found.setdefault(rel, []).append((kind, fn, line, verbs))
    hidden = {rel: [u for u in uses if u[0] in {"unchained", "named", "raw_write"}] for rel, uses in found.items()}
    hidden = {rel: uses for rel, uses in hidden.items() if uses}
    assert not hidden, (
        f"these modules name {TABLE} in a way the guard cannot read ({hidden}): a query kept in a variable, the name held in "
        "a constant, or SQL text. Chain the verb off `.table(\"account_period_balances\")` where it is used.")
    writers = {rel: [u for u in uses if u[0] == "write"] for rel, uses in found.items()}
    writers = {rel: uses for rel, uses in writers.items() if uses}
    assert set(writers) == {WRITER_MODULE}, (
        f"these modules write {TABLE}: {sorted(writers)}. Under USE_USER_JWT a write on the request's client is a signed-in "
        "session's, which migration 534 refuses; the nightly audit is the only writer and uses the privileged client.")
    assert {fn for _, fn, _, _ in writers[WRITER_MODULE]} == {"recompute_client"}


def test_the_guard_sees_every_shape_a_write_can_take():
    """The detector is only worth its verdict if it fires on the spellings a hurried author reaches for."""
    shapes = {
        "a query kept in a variable": 'def f(db):\n    q = db.table("account_period_balances")\n    q.update({"debit_paise": 1}).execute()\n',
        "the name held in a constant": 'T = "account_period_balances"\n\ndef f(db):\n    db.table(T).delete().execute()\n',
        "from_ instead of table": 'def f(db):\n    db.from_("account_period_balances").insert({}).execute()\n',
        "a statement at module level": 'client.table("account_period_balances").update({}).execute()\n',
        "an upsert": 'def f(db):\n    db.table("account_period_balances").upsert({}).execute()\n',
        "raw SQL": 'def f(cur):\n    cur.execute("DELETE FROM public.account_period_balances WHERE true")\n',
        "raw SQL, lower case": 'SQL = "update account_period_balances set debit_paise = 1"\n',
    }
    for label, source in shapes.items():
        kinds = {k for k, _, _, _ in _uses_of_the_table(source)}
        assert kinds & {"write", "unchained", "named", "raw_write"}, f"the guard is blind to: {label}"
    reads = 'def f(db):\n    return db.table("account_period_balances").select("*").eq("client_id", 1).execute()\n'
    assert [k for k, _, _, _ in _uses_of_the_table(reads)] == ["read"]
    doc = 'def f():\n    """UPDATE account_period_balances is what the nightly job does."""\n'
    assert list(_uses_of_the_table(doc)) == []


def test_the_walk_reads_enough_modules_to_mean_something():
    rels = [rel for rel, _ in _production_sources()]
    assert len(rels) > 300, len(rels)
    assert any(r.startswith("scripts/") for r in rels), "the scripts directory is not walked: a one-off writer would pass"
    assert WRITER_MODULE in rels


def test_nothing_else_in_the_api_calls_the_database_functions_that_maintain_it():
    offenders = []
    for rel, text in _production_sources():
        if rel == "services/balance_cache_service.py":
            continue
        for node in ast.walk(ast.parse(text)):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "rpc"
                    and node.args and isinstance(node.args[0], ast.Constant) and str(node.args[0].value).startswith("apb_")):
                offenders.append((rel, node.lineno, node.args[0].value))
    assert not offenders, offenders


def test_the_entry_points_are_called_by_the_nightly_job_with_the_privileged_client():
    callers = []
    for rel, text in _production_sources():
        if rel == "services/balance_cache_service.py":
            continue
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
                if name in ENTRY_POINTS:
                    callers.append((rel, name, ast.unparse(node.args[0]) if node.args else None))
    assert callers and {rel for rel, _, _ in callers} == {"jobs/scheduler.py"}, callers
    assert all(arg == "_get_db()" for _, _, arg in callers), callers
    scheduler = (API_ROOT / "jobs" / "scheduler.py").read_text(encoding="utf-8")
    assert re.search(r"^_get_db\s*=\s*db_provider\.service_db\s*$", scheduler, re.M), (
        "the scheduler's database accessor is no longer db_provider.service_db: the nightly balance audit would write on a "
        "request-shaped client")


def test_the_browser_does_not_read_or_write_the_table_directly():
    pattern = re.compile(r"""\.from\(\s*["'`]%s["'`]""" % TABLE)
    hits = []
    for path in WEB_ROOT.rglob("*"):
        if path.suffix not in {".ts", ".tsx"} or "node_modules" in path.parts or ".next" in path.parts:
            continue
        if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
            hits.append(path.relative_to(WEB_ROOT).as_posix())
    assert not hits, hits
