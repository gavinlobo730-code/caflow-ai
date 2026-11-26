"""
A value written into a column keyed to users(id) is the internal id, and the sweep that says so runs (POST-A-438).

WHAT WAS WRONG
    The two sweeps below lived in `tests/test_users_fk_columns_take_the_internal_id.py`, skipped unless HARNESS_PG was set, and that
    file's name does not end in `_pg.py`. The mock job skipped them, and the real-Postgres job, which collects `tests/test_*_pg.py`,
    never saw them: neither had run in CI since it was written. Run by hand on 14-11-2026 the second one was red on main.

    It was red because it keyed what it found on a function's bare NAME. It found `actor_id` written into
    `client_gst_registrations.created_by` (a key to users(id)) inside `services/client_gst_registration_service.create`, and from then
    on treated every call of ANY function called `create` as a call of that one. `routers/opening_documents.py` calls
    `services/opening_document_service.create(actor_id=<the sign-in id>)`, and that `actor_id` is written into
    `client_sales_invoices.created_by`, a different table's column, so the router read as writing the sign-in id into a key to users.

    THE OPENING-DOCUMENTS WRITER IS RIGHT, AND ONLY BECAUSE THAT COLUMN HAS NO KEY. `client_sales_invoices.created_by` has no foreign
    key, holds the sign-in id on every production row (5,664 of 5,664 on 2-11-2026), and the invoice detail reads it back through the
    sign-in id; `tests/test_a_bare_person_column_takes_the_id_it_holds.py` (READ_FROM_ROWS) proves the writer. So this sweep must not
    pass it by being blind to it: the day a migration keys that column to users(id), the pair comes back from the schema and the
    router fails here. `test_the_sweep_is_keyed_on_the_table_and_the_column` holds exactly that, by adding the one pair.

WHAT IT DOES NOW
    The (table, column) pairs come from the migration-built database's own catalogue: every foreign key whose referenced table is
    public.users. A function is a CARRIER of a parameter when its value is written into one of those pairs (a dict literal in the
    payload, a name assigned one, or a `row["col"] = value` in the same function), and every carrier is the function itself, by module
    and name, with the pairs each parameter reaches. A call is matched to a carrier by what `tests/_call_graph.py` resolves it to, and
    the argument for the parameter is read whether it is passed by keyword or by position. A call the graph cannot resolve is matched
    by its name, as before and by keyword only: a caller nobody can name is unknown, not safe.

A PAYLOAD BUILT IN ONE FUNCTION AND WRITTEN BY ANOTHER (POST-A-166, 16-11-2026)
    `document_repo.create(data)` in a router, and `.table("documents").insert({**data, ...})` in the repository: the table is named in
    one file and the column in another, which is how `documents.uploaded_by` reached production keyed to `team_members` (migration 479
    re-keyed it). `tests/_write_payloads.py` follows a payload parameter (handed over whole or spread) through every caller the graph
    resolves, to the function that builds the dict, and three rules read it: no such write sets a users key from the sign-in id; a
    router parameter written into a users key through a repository is a carrier like any other, so its callers are checked; and nothing
    but None is written into a column still keyed to the retired `team_members`.

WHAT IT STILL CANNOT SEE
    A payload returned by a call (`od.row_for(...)`), a column named by a variable, a call made at module level, and a value that
    reaches a carrier through anything but a plain parameter (an attribute, a dict lookup). The person column guard follows more shapes
    for the columns WITHOUT a key; this one is the rule for the columns WITH one.
"""
from __future__ import annotations

import ast
import os
import pathlib
import re
import subprocess
from functools import lru_cache

import pytest

from tests._call_graph import CallGraph, called_name
from tests._write_payloads import Reader

API = pathlib.Path(__file__).resolve().parent.parent
_PG = os.environ.get("HARNESS_PG")
_NEEDS_PG = pytest.mark.skipif(not _PG, reason="needs HARNESS_PG — reads the real FK list")

#: Where a write or a caller may sit. The first sweep (routers, services, domain) plus the two other places the API writes from.
SCAN_DIRS = ("routers", "services", "domain", "repositories", "jobs")

_WRITES = ("insert", "update", "upsert")

Pairs = dict[str, set[str]]
FnKey = tuple[str, str]


def users_fk_pairs(template: str) -> Pairs:
    """table -> its columns that are a foreign key to public.users, read from the catalogue of a migration-built database."""
    out = subprocess.run(
        ["psql", f"{_PG} dbname={template}", "-X", "-Atc",
         "select c.conrelid::regclass::text||'|'||a.attname "
         "from pg_constraint c join pg_attribute a "
         "  on a.attrelid=c.conrelid and a.attnum=c.conkey[1] "
         "where c.contype='f' and c.confrelid='public.users'::regclass"],
        capture_output=True, text=True, check=True).stdout
    pairs: Pairs = {}
    for line in out.splitlines():
        if "|" in line:
            t, c = line.split("|", 1)
            pairs.setdefault(t.replace("public.", ""), set()).add(c)
    return pairs


# ── The window sweep, moved here unchanged so the real-Postgres job runs it ──────────────────────────────────────────────

@_NEEDS_PG
def test_no_router_writes_the_auth_id_into_a_users_fk_column(pg_template):
    """The pattern, not the instance. Read every (table, column) that FKs public.users from the schema, then refuse any
    insert/update payload that sets one of them from auth_user_id.

    Reads the session's pre-migrated template database directly: the query only SELECTs from the catalogue, so there is
    nothing to isolate and no reason to pay for a clone."""
    pairs = users_fk_pairs(pg_template.name)
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


# ── Across the function boundary, keyed on the function and on (table, column) ───────────────────────────────────────────

def _tables_in(node: ast.AST) -> set[str]:
    """Every `.table("X")` reached from this expression."""
    names = set()
    for n in ast.walk(node):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "table" and len(n.args) == 1
                and isinstance(n.args[0], ast.Constant)
                and isinstance(n.args[0].value, str)):
            names.add(n.args[0].value)
    return names


def _payload_entries(payload: ast.expr, fn: ast.AST):
    """(key, value) of every dict the payload is, holds, or is filled from in the same function: a literal, a name assigned a
    literal, and a `name["col"] = value` subscript assignment."""
    for d in ast.walk(payload):
        if isinstance(d, ast.Dict):
            yield from zip(d.keys, d.values, strict=True)
    if not isinstance(payload, ast.Name):
        return
    for n in ast.walk(fn):
        if not isinstance(n, ast.Assign):
            continue
        for tgt in n.targets:
            if isinstance(tgt, ast.Name) and tgt.id == payload.id and isinstance(n.value, ast.Dict):
                yield from zip(n.value.keys, n.value.values, strict=True)
            elif (isinstance(tgt, ast.Subscript) and isinstance(tgt.value, ast.Name) and tgt.value.id == payload.id
                  and isinstance(tgt.slice, ast.Constant)):
                yield tgt.slice, n.value


def _direct_carriers(graph: CallGraph, pairs: Pairs) -> dict[FnKey, dict[str, set[tuple[str, str]]]]:
    """{function: {parameter: {(table, column)}}} for every function that writes a parameter of its own into a users key.

    A function the graph does not index (one nested inside another) is keyed `(module, "<nested>.name")`, so it can only ever be
    reached through the by-name fallback."""
    indexed = {id(fn): key for key, fn in graph.funcs.items()}
    carriers: dict[FnKey, dict[str, set[tuple[str, str]]]] = {}
    for mod, tree in graph.mods.items():
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            key = indexed.get(id(fn), (mod, f"<nested>.{fn.name}"))
            params = set(graph.parameters(fn))
            for call in ast.walk(fn):
                if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr in _WRITES):
                    continue
                for table in _tables_in(call.func.value):
                    cols = pairs.get(table, set())
                    for payload in call.args:
                        for k, v in _payload_entries(payload, fn):
                            if (isinstance(k, ast.Constant) and k.value in cols
                                    and isinstance(v, ast.Name) and v.id in params):
                                carriers.setdefault(key, {}).setdefault(v.id, set()).add((table, k.value))
    # POST-A-166: a parameter written into a users key through a payload another function inserts (a repository's caller).
    for w in _reader(graph).followed():
        if (w.column in pairs.get(w.table, ()) and isinstance(w.value, ast.Name)
                and w.value.id in graph.parameters(w.scope)):
            carriers.setdefault(w.function, {}).setdefault(w.value.id, set()).add((w.table, w.column))
    return carriers


_READERS: dict[int, Reader] = {}


def _reader(graph: CallGraph) -> Reader:
    """The payload reader over the same graph, built once per graph."""
    if id(graph) not in _READERS:
        _READERS[id(graph)] = Reader(pathlib.Path("."), graph=graph)
    return _READERS[id(graph)]


@lru_cache(maxsize=4)
def _graph(root: str, scan_dirs: tuple[str, ...]) -> tuple[CallGraph, tuple]:
    """The graph and every call in it with what it resolves to, built once per tree: the sweep runs several times per module."""
    graph = CallGraph(pathlib.Path(root), scan_dirs)
    calls = tuple((key, call, tuple(targets)) for key in graph.funcs for call, targets in graph.calls_of(key))
    return graph, calls


def offenders(root: pathlib.Path, pairs: Pairs, scan_dirs: tuple[str, ...] = SCAN_DIRS) -> tuple[list[str], dict]:
    """(offenders, carriers) for the tree at `root` against these users-key pairs."""
    graph, calls = _graph(str(root), scan_dirs)
    carriers = _direct_carriers(graph, pairs)

    def matched(call: ast.Call, targets: tuple) -> list[tuple[FnKey, bool]]:
        """(carrier, resolved?) the call may reach: what the graph resolves it to, or, when it cannot, every carrier of that name."""
        if targets:
            return [(t, True) for t in targets if t in carriers]
        name = called_name(call)
        return [(k, False) for k in carriers if k[1].rsplit(".", 1)[-1] == name]

    def argument(call: ast.Call, target: FnKey, param: str, resolved: bool):
        if resolved:
            return graph.argument_for(call, target, param)
        return next((kw.value for kw in call.keywords if kw.arg == param), None)

    # A function that FORWARDS a parameter into a carrier is a carrier too, so router -> workflow service -> lock service is followed whole.
    for _ in range(8):                       # the longest chain here is three; eight is far past it
        grew = False
        for caller, call, targets in calls:
            params = set(graph.parameters(graph.funcs[caller]))
            for target, resolved in matched(call, targets):
                for param, reach in list(carriers[target].items()):
                    value = argument(call, target, param, resolved)
                    if isinstance(value, ast.Name) and value.id in params:
                        held = carriers.setdefault(caller, {}).setdefault(value.id, set())
                        if not reach <= held:
                            held |= reach
                            grew = True
        if not grew:
            break

    found = []
    for caller, call, targets in calls:
        for target, resolved in matched(call, targets):
            for param, reach in carriers[target].items():
                value = argument(call, target, param, resolved)
                if value is not None and "auth_user_id" in ast.unparse(value):
                    cols = ", ".join(f"{t}.{c}" for t, c in sorted(reach))
                    how = "" if resolved else " (by name: the call could not be resolved)"
                    found.append(f"{caller[0]}.{caller[1]}: {target[0]}.{target[1]}({param}=...) is written into {cols}{how}")
    return sorted(set(found)), carriers


@_NEEDS_PG
def test_no_caller_passes_the_auth_id_into_a_parameter_that_becomes_a_users_fk(pg_template):
    """The sweep above, but across the function boundary.

    THE HOLE IT CLOSES. The sweep above reads a window of source around each `.table("X")` and looks for the auth id beside the
    column name. In services/year_lock_service.py the write is `"locked_by": actor_id` — a parameter — and the auth id was
    supplied by routers/year_end.py and routers/year_end_reviews.py, one frame away. Neither half of the pattern was ever in the
    same window as the other, so a guard written specifically for this bug did not see this instance of it (ACC-05).

    So: find the parameters that BECOME a users-FK column, then check what every caller passes into them. This is the same lesson
    as the money-parser guard in CLAUDE.md — a rule beats a spelling, and each new spelling of a defect is a defect the old guard is
    blind to.
    """
    pairs = users_fk_pairs(pg_template.name)
    assert pairs, "the FK list came back empty — the query or the schema is wrong"
    found, carriers = offenders(API, pairs)

    # Not blind: the instance this sweep was written for is found, and followed one frame up into the year-end routers' callee.
    lock = carriers.get(("services.year_lock_service", "set_client_lock"), {})
    assert ("client_year_locks", "locked_by") in lock.get("actor_id", set()), "the year lock's writer is no longer found"
    assert "actor_id" in carriers.get(("services.year_end_workflow_service", "lock_year_if_completing"), {}), (
        "the forwarding step no longer reaches lock_year_if_completing, whose callers supplied the auth id (ACC-05)")
    assert len(carriers) >= 60, f"only {len(carriers)} functions reach a users key — the AST walk is wrong"

    assert not found, (
        "these arguments end up in a column that FKs public.users(id), but are supplied from the Supabase auth id:\n  "
        + "\n  ".join(found))


# ── Not blind, and keyed on the table and the column (no database needed, so these run in both jobs) ─────────────────────

def test_the_sweep_is_keyed_on_the_table_and_the_column():
    """The opening-documents writer passes ONLY because `client_sales_invoices.created_by` has no key. Give it one and the router
    that hands it the sign-in id fails; key `client_gst_registrations.created_by` alone (the pair the old sweep took it for) and it
    does not. One tree, two schemas, two answers: what decides is the (table, column), not the column's name."""
    keyed, _ = offenders(API, {"client_sales_invoices": {"created_by"}})
    assert any(line.startswith("routers.opening_documents.add_document: services.opening_document_service.create(actor_id=...)")
               and "client_sales_invoices.created_by" in line for line in keyed), keyed
    assert any(line.startswith("routers.opening_documents.bulk_import: ") for line in keyed), keyed

    elsewhere, carriers = offenders(API, {"client_gst_registrations": {"created_by"}})
    assert ("services.client_gst_registration_service", "create") in carriers, "the GST registration writer is no longer found"
    assert not elsewhere, f"a writer of another table's created_by was taken for the GST registration's: {elsewhere}"


def _tree(tmp_path: pathlib.Path, files: dict[str, str]) -> pathlib.Path:
    for rel, src in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(src)
    return tmp_path


_TWO_CREATES = {
    "services/keyed.py": "def create(db, actor_id):\n    db.table('keyed').insert({'created_by': actor_id}).execute()\n",
    "services/plain.py": ("def create(db, actor_id):\n    row = {}\n    row['created_by'] = actor_id\n"
                          "    db.table('plain').insert(row).execute()\n"),
    "routers/r.py": ("from services import keyed, plain\n\n"
                     "def a(db, current_user):\n    keyed.create(db, actor_id=current_user.get('id'))\n\n"
                     "def b(db, current_user):\n    plain.create(db, actor_id=current_user.get('auth_user_id'))\n"),
}


def test_two_functions_of_one_name_are_two_carriers(tmp_path):
    """The defect on main, in miniature: `keyed.create` writes into a users key and `plain.create` into a column with none, and
    the router hands the sign-in id only to `plain.create`. Keyed on the name, `b` read as an offender; keyed on the function, it
    is one only when `plain.created_by` is a key."""
    root = _tree(tmp_path, _TWO_CREATES)
    assert offenders(root, {"keyed": {"created_by"}})[0] == []
    assert offenders(root, {"plain": {"created_by"}})[0] == [
        "routers.r.b: services.plain.create(actor_id=...) is written into plain.created_by"]


def test_a_forwarded_parameter_and_a_positional_argument_are_followed(tmp_path):
    root = _tree(tmp_path, {
        "services/lock.py": "def set_lock(db, client_id, actor_id):\n    db.table('locks').insert({'locked_by': actor_id}).execute()\n",
        "services/flow.py": ("from services.lock import set_lock\n\n"
                             "def complete(db, client_id, actor_id):\n    set_lock(db, client_id, actor_id)\n"),
        "routers/r.py": ("from services import flow\n\n"
                         "def route(db, current_user):\n    flow.complete(db, 'c1', current_user.get('auth_user_id'))\n"),
    })
    found, carriers = offenders(root, {"locks": {"locked_by"}})
    assert carriers[("services.flow", "complete")] == {"actor_id": {("locks", "locked_by")}}
    assert found == ["routers.r.route: services.flow.complete(actor_id=...) is written into locks.locked_by"]


def test_a_call_the_graph_cannot_resolve_is_matched_by_name_and_not_passed(tmp_path):
    files = dict(_TWO_CREATES)
    files["routers/r.py"] = ("def c(db, current_user, writer):\n"
                             "    writer.create(db, actor_id=current_user.get('auth_user_id'))\n")
    found, _ = offenders(_tree(tmp_path, files), {"keyed": {"created_by"}})
    assert found == ["routers.r.c: services.keyed.create(actor_id=...) is written into keyed.created_by "
                     "(by name: the call could not be resolved)"]


# ── A payload built in one function and written by another, and the retired team_members keys (POST-A-166) ───────────────

def team_members_fk_pairs(template: str) -> Pairs:
    """table -> its columns still keyed to the retired public.team_members (none, once the table goes)."""
    out = subprocess.run(
        ["psql", f"{_PG} dbname={template}", "-X", "-Atc",
         "select c.conrelid::regclass::text||'|'||a.attname "
         "from pg_constraint c join pg_attribute a "
         "  on a.attrelid=c.conrelid and a.attnum=c.conkey[1] "
         "where c.contype='f' and c.confrelid=to_regclass('public.team_members')"],
        capture_output=True, text=True, check=True).stdout
    pairs: Pairs = {}
    for line in out.splitlines():
        if "|" in line:
            t, c = line.split("|", 1)
            pairs.setdefault(t.replace("public.", ""), set()).add(c)
    return pairs


def payload_reader(root: pathlib.Path, scan_dirs: tuple[str, ...] = SCAN_DIRS) -> Reader:
    return _reader(_graph(str(root), scan_dirs)[0])


def auth_id_writes(reader: Reader, keyed: Pairs) -> list[str]:
    """Every write, made where its dict is built or through a function that inserts a payload it was handed, that sets a keyed
    column from the sign-in id."""
    return sorted({f"{w.module}:{w.line} {w.table}.{w.column}" + (f" (written by {w.via})" if w.via else "")
                   for w in reader.writes
                   if w.column in keyed.get(w.table, ()) and "auth_user_id" in ast.unparse(w.value)})


def team_member_writes(reader: Reader, keyed: Pairs) -> list[str]:
    """Every write that puts anything but None into a column keyed to the retired `team_members`."""
    return sorted({f"{w.module}:{w.line} {w.table}.{w.column}" + (f" (written by {w.via})" if w.via else "")
                   for w in reader.writes
                   if w.column in keyed.get(w.table, ())
                   and not (isinstance(w.value, ast.Constant) and w.value.value is None)})


@_NEEDS_PG
def test_no_write_puts_the_auth_id_into_a_users_fk_column_wherever_its_payload_is_built(pg_template):
    """The repository pattern. The window sweep saw the table in one file and the column in another, and passed."""
    pairs = users_fk_pairs(pg_template.name)
    assert pairs, "the FK list came back empty — the query or the schema is wrong"
    found = auth_id_writes(payload_reader(API), pairs)
    assert not found, (
        "these writes set a column that FKs public.users(id) from the Supabase auth id, which can never satisfy the key:\n  "
        + "\n  ".join(found))


@_NEEDS_PG
def test_nothing_writes_a_person_into_a_column_keyed_to_the_retired_team_members(pg_template):
    """`team_members` holds no rows on production and nothing in the API writes it, so a column keyed to it can hold only NULL: any
    other value is refused with 23503, in whatever path writes it. Read on production on 30-10-2026, every value of the four columns
    still keyed to it (`activity_logs.actor_id`, `ai_insights.resolved_by`, `clients.assigned_to`, `filings.filed_by`) is NULL and
    nothing writes them; this holds that for the next writer, a repository's caller included. Retiring the keys goes with the table
    (POST-B-303 decides the documents half of it); until then this is the rule."""
    keyed = team_members_fk_pairs(pg_template.name)
    found = team_member_writes(payload_reader(API), keyed)
    assert not found, (
        "these writes put a value into a column keyed to team_members, which has no rows; the database refuses every one of them. "
        "Write the person into a column keyed to users instead:\n  " + "\n  ".join(found))


_REPOSITORY_TREE = {
    "repositories/doc_repository.py": (
        "class DocRepository:\n"
        "    def create(self, data):\n"
        "        return db().table('documents').insert({**data, 'created_at': 'now'}).execute()\n\n"
        "doc_repo = DocRepository()\n"),
    "routers/docs.py": (
        "from repositories.doc_repository import doc_repo\n\n"
        "def upload(current_user):\n"
        "    data = {'title': 'x', 'uploaded_by': current_user.get('UPLOADER')}\n"
        "    doc_repo.create(data)\n\n"
        "def file_it(db, actor_id):\n"
        "    doc_repo.create({'title': 'y', 'reviewed_by': actor_id})\n\n"
        "def route(db, current_user):\n"
        "    file_it(db, current_user.get('REVIEWER'))\n"),
}


def _repository_tree(tmp_path: pathlib.Path, **ids: str) -> pathlib.Path:
    files = {}
    for rel, src in _REPOSITORY_TREE.items():
        for name, value in ids.items():
            src = src.replace(name, value)
        files[rel] = src
    return _tree(tmp_path, files)


def test_a_payload_a_router_builds_and_a_repository_writes_is_read(tmp_path):
    root = _repository_tree(tmp_path, UPLOADER="auth_user_id", REVIEWER="id")
    keyed = {"documents": {"uploaded_by", "reviewed_by"}}
    expected = "routers.docs:4 documents.uploaded_by (written by repositories.doc_repository:DocRepository.create)"
    assert auth_id_writes(payload_reader(root), keyed) == [expected]
    assert team_member_writes(payload_reader(root), {"documents": {"uploaded_by"}}) == [expected]
    assert offenders(root, keyed)[0] == []


def test_a_router_parameter_written_through_a_repository_is_a_carrier(tmp_path):
    root = _repository_tree(tmp_path, UPLOADER="id", REVIEWER="auth_user_id")
    keyed = {"documents": {"uploaded_by", "reviewed_by"}}
    assert auth_id_writes(payload_reader(root), keyed) == []
    found, carriers = offenders(root, keyed)
    assert carriers[("routers.docs", "file_it")] == {"actor_id": {("documents", "reviewed_by")}}
    assert found == ["routers.docs.route: routers.docs.file_it(actor_id=...) is written into documents.reviewed_by"]


def test_the_reader_follows_the_documents_router_into_its_repository():
    """An anchor on the real tree, with no database: the write that escaped is one the reader now sees."""
    seen = {(w.module, w.column, w.via) for w in payload_reader(API).followed() if w.table == "documents"}
    assert ("routers.documents", "uploaded_by", "repositories.document_repository:DocumentRepository.create") in seen, sorted(seen)

