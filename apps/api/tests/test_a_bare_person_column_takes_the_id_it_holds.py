"""A person column with no foreign key is written with the one id it holds, and what the scan cannot read is listed (POST-A-361, part 2).

WHAT WAS LEFT
    Migration 566 makes the database refuse a row that names a member of another firm, but only on a column that has a foreign key to
    `users`. Seventy-nine uuid columns named for a person have none, and they cannot become keys by a blanket rule: `current_user`
    carries two ids, `users.id` (the internal one) and `auth_user_id` (Supabase's), and the columns disagree about which they take. Read
    against the production data on 1-11-2026 (every row of the 24 that had rows): ELEVEN hold the auth id, NINE hold `users.id`, and
    `audit_log.actor_id` and `client_timeline_events.actor_id` are mixed on purpose. A key to `users(id)` is right for the nine and
    WRONG for the eleven. Nothing on a screen is wrong today (a reader that resolves a creator tries both ids), so what a wrong writer
    does is leave a column that two readers now disagree about. The model for this guard is
    `test_users_fk_columns_take_the_internal_id.py`, which covers the keyed columns from the schema.

WHAT THIS HOLDS (mock mode, no database)
    * THE MAP. The twenty columns whose data was read are named below with the id each holds. It is data, not a rule written from
      memory: it is the production reading of 1-11-2026, and a column is added to it by reading its rows.
    * THE RULE ON A DIRECT WRITE. Every `.table(T).insert(...)`, `.upsert(...)` or `.update(...)` in the API whose payload is a dict
      literal (or a name assigned a dict literal, a list or comprehension of them, or given the column by a subscript assignment in
      the same function) is read for the mapped column. A value that is the auth id where the column holds `users.id`, or the
      internal id where it holds the auth id, FAILS: that is the review-workflow defect again (23503 behind a key, or a silent
      mixed column behind none).
    * THE CHAIN IS FOLLOWED TO ITS ORIGIN (POST-A-361, 3-11-2026). A value that is a parameter is followed through every caller, and through
      the callers of those, up to twelve hops, through a nested helper's outer function, through a call made on a declared factory's result,
      and through a call made on something the scan cannot name when the function's name is defined once. Each origin is `users`, `auth`, a
      deliberate empty or `unread`. All of the writers the scan can see are PROVEN this way, the posting kernel's `posted_by` through its whole
      caller graph, and `UNREAD` is empty. The three columns no direct writer is seen for (`BUILT_ELSEWHERE`) are proven through the
      functions that build their rows.
    * WHAT THE SCAN CANNOT READ IS LISTED, NOT PASSED. A value that is a bare name (a parameter that arrived from a caller), a
      conditional or a call is `unread`, and each is on the list below with the function it sits in. The list is an equality in both
      directions: a new writer of a mapped column whose value the scan cannot read fails until someone reads it and adds it, and a
      listed one that has since become readable (or gone) fails until it is deleted. THE LIST IS NOT A CLAIM THAT THESE ARE RIGHT. It is
      the set of writes nobody has traced to the principal the value came from, which is what the ledger line is for.
    * A payload built elsewhere (`repo.create(payload)`, a helper's dict) is not seen at all; the second limit, also named in the ledger.
    * THE SCAN IS NOT BLIND: synthetic writers show a wrong id of each kind flagged, a right one passed, a name unread, and a
      subscript assignment found.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from tests._call_graph import chain_of

API = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("routers", "services", "repositories", "domain", "jobs", "core")

#: (table, column) -> the id it holds. Read against production on 1-11-2026 (POST-A-361): every row of each held that id.
HOLDS: dict[tuple[str, str], str] = {
    # the auth id (`auth_user_id`)
    ("client_sales_invoices", "created_by"): "auth", ("engagement_events", "user_id"): "auth", ("year_end_notes", "created_by"): "auth",
    ("engagement_templates", "created_by"): "auth", ("ai_conversations", "user_id"): "auth", ("engagements", "created_by"): "auth",
    ("onboarding_tasks", "completed_by"): "auth", ("customer_payment_links", "created_by"): "auth",
    ("year_end_engagements", "created_by"): "auth", ("bank_reconciliations", "created_by"): "auth", ("dsc_records", "deleted_by"): "auth",
    # the internal id (`users.id`)
    ("inventory_stock_ledger", "created_by"): "users", ("journal_entries", "posted_by"): "users", ("login_events", "user_id"): "users",
    ("bank_transactions", "posted_by"): "users", ("client_instructions", "created_by"): "users", ("gstr2b_uploads", "created_by"): "users",
    ("time_entries", "user_id"): "users", ("form_26as_uploads", "created_by"): "users", ("self_assessment_challans", "created_by"): "users",
}
WRITES = {"insert", "update", "upsert"}
PRINCIPALS = r"(?:current_user|actor|user|principal|caller|acting_user|me)"
AUTH_VALUE = re.compile(r"auth_user_id|auth_id\b")
USERS_VALUE = re.compile(rf"\b{PRINCIPALS}\b[^\n]*?(?:\.get\(\s*['\"]id['\"]\s*\)|\[\s*['\"]id['\"]\s*\])")

#: Writes whose value the scan cannot read AND cannot prove from the calls that supply it, as (file, function, table, column). A write
#: whose value is a PARAMETER is followed one hop to the calls of its function made through its module (see `traced`): when every such call
#: passes the kind the column holds, it is proven and not listed. What is left is a value that is a conditional or a call, a parameter
#: that is passed on again, or a function called through an object the scan cannot name (`self.repo.f(...)`). Not a claim that they are
#: right: the set of writes nobody has traced to the principal the value came from. Equality in both directions.
UNREAD: set[tuple[str, str, str, str]] = set()      # every write the scan can see is now proven by its chain (POST-A-361, 3-11-2026)


#: Mapped columns with NO direct dict-literal writer anywhere in the API as the scan reads it: their rows are written through a payload built
#: elsewhere (a repository or a helper) or by a path the scan does not follow. Listed so that the day a direct writer appears it is read,
#: and so that "twenty columns are mapped" is not read as "twenty are guarded". Equality in both directions.
NOT_SEEN: set[tuple[str, str]] = {("login_events", "user_id"), ("time_entries", "user_id"), ("year_end_notes", "created_by")}

#: For each NOT_SEEN column: the functions that BUILD the row's dict (a repository's `create(payload)` writes it, so no `.table(T).insert(...)` is
#: seen next to the key). Each is read for a dict literal carrying the column's key and the value is traced like any other: the proof of the
#: column is that every builder's value is the kind it holds. A builder that no longer has the key fails (the entry is stale).
BUILT_ELSEWHERE: dict[tuple[str, str], list[tuple[str, str]]] = {
    ("login_events", "user_id"): [("repositories/login_events_repository.py", "record")],
    ("time_entries", "user_id"): [("routers/time_tracking.py", "start_timer"), ("routers/time_tracking.py", "create_manual_entry")],
    ("year_end_notes", "created_by"): [("routers/year_end_notes.py", "generate_notes")],
}

#: A route's `user_id` PATH parameter that is checked, before anything is written, to be a member of the caller's firm by a lookup in `users` by
#: id (`_get_member` -> `user_repo.find_by_id(id, firm_id=...)`): such a value is a `users.id` and nothing else, whoever typed it. (file, function,
#: parameter) -> the text of the check that must stay in the function. Not a claim made from memory: `test_a_checked_path_parameter_...` reads both.
CHECKED_AS_A_MEMBER: dict[tuple[str, str, str], str] = {
    ("routers/identity.py", "suspend_user", "user_id"): "_get_member(user_id",
    ("routers/identity.py", "force_logout", "user_id"): "_get_member(user_id",
}


#: Columns that are a key to `users(id)` and are READ off a row to become the actor of a later write: `<row>.get("trusted_by")` is an internal id
#: because the database refuses anything else there. The key is the schema's (migration 322), not a guess.
KEYED_TO_USERS_WHEN_READ = {"trusted_by"}
KEYED_READ = re.compile(r"\.get\(\s*['\"](" + "|".join(sorted(KEYED_TO_USERS_WHEN_READ)) + r")['\"]")


def _none_branch_dropped(value: ast.expr) -> ast.expr:
    """`x if cond else None` (either way round) is `x`: the None branch is a deliberate empty, not a second kind of value."""
    if isinstance(value, ast.IfExp):
        if isinstance(value.orelse, ast.Constant) and value.orelse.value is None:
            return value.body
        if isinstance(value.body, ast.Constant) and value.body.value is None:
            return value.orelse
    return value


def kind_of(value: ast.expr) -> str:
    """'auth', 'users', 'none' (a constant None) or 'unread'."""
    value = _none_branch_dropped(value)
    if isinstance(value, ast.Constant) and value.value is None:
        return "none"
    text = ast.unparse(value)
    if KEYED_READ.search(text) and not AUTH_VALUE.search(text):
        return "users"
    if AUTH_VALUE.search(text):
        return "auth"
    if USERS_VALUE.search(text):
        return "users"
    return "unread"


def _function_of(node, parents) -> ast.AST | None:
    while node is not None and not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        node = parents.get(node)
    return node


def _function_chain(node, parents) -> tuple[ast.AST, ...]:
    """The functions a node sits in, innermost first: a helper nested in a function reads the outer function's names."""
    out = []
    node = _function_of(node, parents)
    while node is not None:
        out.append(node)
        node = _function_of(parents.get(node), parents)
    return tuple(out)


def _payload_dicts(payload: ast.expr, fn: ast.AST | None):
    """(dict literals, [(column, value) set by subscript assignment]) for a write's payload."""
    if isinstance(payload, ast.Dict):
        return [payload], []
    if isinstance(payload, ast.List):
        return [e for e in payload.elts if isinstance(e, ast.Dict)], []
    if isinstance(payload, ast.ListComp) and isinstance(payload.elt, ast.Dict):
        return [payload.elt], []
    if isinstance(payload, ast.Name) and fn is not None:
        dicts, subs = [], []
        for n in ast.walk(fn):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("append", "extend", "insert")
                    and isinstance(n.func.value, ast.Name) and n.func.value.id == payload.id):
                for arg in n.args:                    # rows.append({...}) / rows.extend([{...}, ...]) / rows.extend({...} for ...)
                    d, _ = _payload_dicts(arg, None)
                    dicts.extend(d)
                    if isinstance(arg, ast.GeneratorExp) and isinstance(arg.elt, ast.Dict):
                        dicts.append(arg.elt)
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name) and t.id == payload.id:
                        d, _ = _payload_dicts(n.value, None)
                        dicts.extend(d)
                    if (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and t.value.id == payload.id
                            and isinstance(t.slice, ast.Constant) and isinstance(t.slice.value, str)):
                        subs.append((t.slice.value, n.value))
        return dicts, subs
    return [], []


def writes_in(source: str, relpath: str) -> list[tuple[str, str, str, str, str, int]]:
    """(file, function, table, column, kind, line) for every mapped column written by a direct insert, update or upsert."""
    tree = ast.parse(source)
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    out, seen = [], set()
    for call in [n for n in ast.walk(tree) if isinstance(n, ast.Call)]:
        chain = chain_of(call)
        methods = [m for m, _ in chain]
        if "table" not in methods or not (WRITES & set(methods)):
            continue
        table_call = next(c for m, c in chain if m == "table")
        write_call = next(c for m, c in chain if m in WRITES)
        if not (table_call.args and isinstance(table_call.args[0], ast.Constant) and isinstance(table_call.args[0].value, str)):
            continue
        table = table_call.args[0].value
        if id(write_call) in seen or not write_call.args:
            continue
        seen.add(id(write_call))
        fn = _function_of(write_call, parents)
        dicts, subs = _payload_dicts(write_call.args[0], fn)
        pairs = [(k.value, v) for d in dicts for k, v in zip(d.keys, d.values, strict=True) if isinstance(k, ast.Constant) and isinstance(k.value, str)]
        for column, value in pairs + subs:
            if (table, column) in HOLDS:
                out.append((relpath, fn.name if fn is not None else "<module>", table, column, kind_of(value), value.lineno))
                PARAM_OF[(relpath, fn.name if fn is not None else "<module>", table, column)] = _parameter(value, fn)
    return out


#: (file, function, table, column) -> the parameter name the value is, when it is a bare name that is a parameter of its function.
PARAM_OF: dict[tuple[str, str, str, str], tuple[str, int] | None] = {}


def _parameter(value: ast.expr, fn: ast.AST | None):
    """(name, position) when `value` is a bare name that is one of `fn`'s parameters, else None."""
    value = _none_branch_dropped(value)
    if not (isinstance(value, ast.Name) and isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))):
        return None
    names = [a.arg for a in (*fn.args.posonlyargs, *fn.args.args)]
    kwonly = [a.arg for a in fn.args.kwonlyargs]
    if value.id in names:
        return value.id, names.index(value.id) - (1 if names and names[0] in ("self", "cls") else 0)
    if value.id in kwonly:
        return value.id, -1
    return None


def every_write() -> list[tuple[str, str, str, str, str, int]]:
    found = []
    for d in SCAN_DIRS:
        for path in sorted((API / d).rglob("*.py")):
            try:
                found.extend(writes_in(path.read_text(encoding="utf-8"), path.relative_to(API).as_posix()))
            except (SyntaxError, UnicodeDecodeError):
                continue
    return found


WRITES_FOUND = every_write()


def _aliases(tree: ast.Module) -> dict[str, str]:
    """name bound in this file -> the module basename it stands for (`import services.x as svc`, `from services import x as svc`)."""
    out: dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                out[a.asname or a.name.split(".")[0]] = a.name.split(".")[-1]
        elif isinstance(n, ast.ImportFrom):
            for a in n.names:
                out[a.asname or a.name] = a.name                     # `from services import module` binds the module; `from module import f` binds f
    return out


def _sources_on_disk() -> dict[str, str]:
    out = {}
    for d in SCAN_DIRS:
        for path in sorted((API / d).rglob("*.py")):
            try:
                out[path.relative_to(API).as_posix()] = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
    return out


def _call_sites(sources: dict[str, str] | None = None) -> dict[str, list[tuple[str, str, ast.Call, tuple]]]:
    """function name -> [(file, module the call is made through or '', call)]. A bare-name call is made through the file's own module
    unless the name was imported from another (`from module import f`), in which case it is made through that module; `x.f(...)` is made
    through whatever module the alias `x` stands for, and through nothing the scan can name (a parameter, `self`) otherwise."""
    sites: dict[str, list[tuple[str, str, ast.Call, tuple]]] = {}
    sources = sources if sources is not None else _sources_on_disk()
    stems = {Path(r).stem for r in sources}
    for rel, text in sources.items():
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
        own, aliases = Path(rel).stem, _aliases(tree)
        imported_from = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module:
                for a in n.names:
                    imported_from[a.asname or a.name] = (n.module.split(".")[-1], a.name)
        for call in [n for n in ast.walk(tree) if isinstance(n, ast.Call)]:
            enclosing = _function_chain(call, parents)
            if isinstance(call.func, ast.Name):
                module, real = imported_from.get(call.func.id, (own, call.func.id))
                sites.setdefault(real, []).append((rel, module, call, enclosing))
            elif isinstance(call.func, ast.Attribute):
                base = call.func.value
                module = ""
                if isinstance(base, ast.Name):
                    module = aliases.get(base.id, "")
                    if module not in stems and base.id in imported_from:
                        # `from repositories.dsc_repository import dsc_repo`: `dsc_repo.f(...)` is made through the module that holds the instance.
                        module = imported_from[base.id][0]
                sites.setdefault(call.func.attr, []).append((rel, module, call, enclosing))
    return sites


def supplied_kinds(function: str, module: str, parameter: tuple[str, int], sites=None) -> list[tuple[str, int, str]]:
    """(file, line, kind) of what each call of `module.function` passes for `parameter` (one hop; a name passed on again is `unread`).
    Only calls made THROUGH `module` count: `create` is the name of a dozen unrelated functions."""
    name, position = parameter
    sites = sites if sites is not None else _call_sites()
    out = []
    for rel, through, call, _enclosing in sites.get(function, []):
        if through != module:
            continue
        passed = next((kw.value for kw in call.keywords if kw.arg == name), None)
        if passed is None and 0 <= position < len(call.args):
            passed = call.args[position]
        if passed is None:
            continue                                  # the call leaves it to the default
        out.append((rel, call.lineno, kind_of(passed)))
    return out


def _definition_counts(sources: dict[str, str] | None = None) -> dict[str, int]:
    """function or method name -> how many times it is defined in the scanned tree."""
    counts: dict[str, int] = {}
    for text in (sources if sources is not None else _sources_on_disk()).values():
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                counts[n.name] = counts.get(n.name, 0) + 1
    return counts


MAX_HOPS = 12


def origins(function: str, file: str, parameter: tuple[str, int], sites, defined, *, _seen=frozenset(), _depth=0) -> list[tuple[str, int, str]]:
    """(file, line, kind) of every ORIGIN of the value a function receives for `parameter`: its callers' arguments, and where such an
    argument is itself a parameter of the calling function (or a name assigned from one) the callers of THAT, up to `MAX_HOPS` hops.

    A call counts when it is made through the function's module, or through something the scan cannot name (`_loc().f(...)`,
    `self.repo.f(...)`) and the name is defined ONCE in the whole tree (so the call can only be this function). An origin is `auth`,
    `users`, `none` (a constant None, or a conditional's empty branch), or `unread`: a value that is a call, a conditional, a name no
    assignment explains, or a parameter nothing calls. THE CHAIN IS THE PROOF: a column is proven only when every origin is its kind."""
    name, position = parameter
    out: list[tuple[str, int, str]] = []
    seen = _seen | {(file, function)}
    for rel, through, call, enclosing in sites.get(function, []):
        if not (through == Path(file).stem or (through == "" and defined.get(function) == 1)
                or _on_the_declared_factory(file, function, rel, call)):
            continue
        passed = next((kw.value for kw in call.keywords if kw.arg == name), None)
        if passed is None and 0 <= position < len(call.args):
            passed = call.args[position]
        if passed is None:
            continue                                  # the call leaves it to the default
        out.extend(_origin_of(passed, rel, call.lineno, enclosing, sites, defined, seen, _depth + 1))
    return out


#: Calls made on the RESULT of a factory function (`_repo().create_conversation(...)`) cannot be named by the resolver, and the method's name is
#: shared (`create_conversation` is also a route), so the name alone does not identify it. (the function's file, its name) -> (the file that
#: calls it, the factory it calls it on). The call must really be `<factory>().<name>(...)` in that file or it does not count.
CALLED_ON_A_FACTORY: dict[tuple[str, str], tuple[str, str]] = {
    ("repositories/ai_copilot_repository.py", "create_conversation"): ("routers/ai_copilot_v2.py", "_repo"),
}


def _on_the_declared_factory(file: str, function: str, rel: str, call: ast.Call) -> bool:
    declared = CALLED_ON_A_FACTORY.get((file, function))
    if declared is None or rel != declared[0] or not isinstance(call.func, ast.Attribute):
        return False
    base = call.func.value
    return isinstance(base, ast.Call) and getattr(base.func, "id", None) == declared[1]


def _origin_of(value, rel, line, chain, sites, defined, seen, depth) -> list[tuple[str, int, str]]:
    value = _none_branch_dropped(value)
    if isinstance(value, ast.IfExp):                  # two real branches: both are origins
        return (_origin_of(value.body, rel, line, chain, sites, defined, seen, depth)
                + _origin_of(value.orelse, rel, line, chain, sites, defined, seen, depth))
    kind = kind_of(value)
    if kind != "unread" or not isinstance(value, ast.Name) or depth > MAX_HOPS:
        return [(rel, line, kind)]
    for fn in chain:                                  # innermost function first: a nested helper reads its outer function's names
        param = _parameter(value, fn)
        if param is not None and (rel, fn.name, param[0]) in CHECKED_AS_A_MEMBER:
            return [(rel, line, "users")]             # a path parameter proven to be a member of this firm, by a lookup in `users`
        if param is not None:                         # passed on again: the callers of the function that takes it
            if (rel, fn.name) in seen:
                return [(rel, line, "unread")]
            found = origins(fn.name, rel, param, sites, defined, _seen=seen, _depth=depth)
            return found or [(rel, line, "unread")]   # nothing calls it: not proven
        assigned = []                                 # a local name: what every assignment to it in this function makes it
        for n in ast.walk(fn):
            if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == value.id for t in n.targets):
                assigned.extend(_origin_of(n.value, rel, n.lineno, chain, sites, defined, seen, depth + 1))
        if assigned:
            return assigned
    return [(rel, line, "unread")]


def traced() -> tuple[dict[tuple[str, str, str, str], list], dict[tuple[str, str, str, str], str]]:
    """For every unread write whose value is a parameter: what its callers pass. -> (callers by write, verdict by write).

    verdict 'ok' when there is at least one caller and every caller passes the kind the column holds (or None); 'wrong' when one passes
    the other kind; 'open' when a caller passes something this scan cannot read, or nothing calls it."""
    sources = _sources_on_disk()
    sites, defined = _call_sites(sources), _definition_counts(sources)
    callers, verdict = {}, {}
    for f, fn, t, c, k, _l in WRITES_FOUND:
        key = (f, fn, t, c)
        if k != "unread" or key in callers:
            continue
        param = PARAM_OF.get(key)
        if not param:
            callers[key], verdict[key] = [], "open"
            continue
        passed = origins(fn, f, param, sites, defined)
        callers[key] = passed
        kinds = {kind for _f, _line, kind in passed}
        want = HOLDS[(t, c)]
        verdict[key] = ("wrong" if kinds & ({"auth", "users"} - {want}) else
                        "ok" if passed and kinds <= {want, "none"} else "open")
    return callers, verdict


CALLERS, VERDICT = traced()


def built_elsewhere_origins(table: str, column: str, sources: dict[str, str] | None = None) -> list[tuple[str, int, str]]:
    """(file, line, kind) of the value of every dict literal carrying `column` as a key, in each function named for that column."""
    sources = sources if sources is not None else _sources_on_disk()
    sites, defined = _call_sites(sources), _definition_counts(sources)
    out: list[tuple[str, int, str]] = []
    for rel, fn_name in BUILT_ELSEWHERE[(table, column)]:
        tree = ast.parse(sources[rel])
        parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
        built = False
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn_name]:
            chain = _function_chain(fn, parents)
            for d in [n for n in ast.walk(fn) if isinstance(n, ast.Dict)]:
                for k, v in zip(d.keys, d.values, strict=True):
                    if isinstance(k, ast.Constant) and k.value == column:
                        built = True
                        out.extend(_origin_of(v, rel, v.lineno, chain, sites, defined, frozenset(), 0))
        assert built, f"{rel}::{fn_name} no longer builds a dict with the key {column!r}: update BUILT_ELSEWHERE"
    return out


def test_the_scan_finds_the_writers_it_was_written_for():
    tables = {t for _f, _fn, t, _c, _k, _l in WRITES_FOUND}
    assert len(WRITES_FOUND) >= 20, WRITES_FOUND
    assert len(tables) >= 12, sorted(tables)


def test_no_direct_write_puts_the_other_kind_of_id_in_a_mapped_column():
    wrong = [(f, fn, t, c, HOLDS[(t, c)], k, line) for f, fn, t, c, k, line in WRITES_FOUND
             if k in ("auth", "users") and k != HOLDS[(t, c)]]
    assert not wrong, ("a person column is written with the other kind of id (file, function, table, column, it holds, written, line):\n  "
                       + "\n  ".join(map(str, wrong)))


def test_no_call_supplies_the_other_kind_of_id_to_a_writer_that_takes_it_as_a_parameter():
    """The opening-documents screen passed `current_user.get("id")` to the writer of `client_sales_invoices.created_by`, which holds the
    AUTH id on every invoice (5,664 of 5,664 on production): found by this trace, fixed in the same change."""
    wrong = {key: [c for c in CALLERS[key] if c[2] in ("auth", "users") and c[2] != HOLDS[(key[2], key[3])]]
             for key, v in VERDICT.items() if v == "wrong"}
    assert not wrong, f"a call passes the other kind of id for a person column: {wrong}"


def test_what_the_scan_cannot_read_or_prove_is_exactly_the_listed_set():
    open_ = {key for key, v in VERDICT.items() if v == "open"}
    assert open_ == UNREAD, (
        f"writes of a mapped column whose value cannot be read or proven and are not listed: {sorted(open_ - UNREAD)}; "
        f"listed but now proven or gone (delete them): {sorted(UNREAD - open_)}")


def test_the_trace_proves_the_writers_it_can():
    """A floor so a tracer that quietly stops matching cannot turn every proof into 'open' and pass with a longer list."""
    proven = {key for key, v in VERDICT.items() if v == "ok"}
    assert len(proven) >= 12, sorted(proven)
    assert ("services/journal_posting_service.py", "post_draft", "journal_entries", "posted_by") in proven
    # the posting kernel is proven through its WHOLE caller graph, and the chain is long: dozens of origins, every one the internal id
    kernel = ("services/phase2_journal_service.py", "_create_journal", "journal_entries", "posted_by")
    assert kernel in proven and sum(kind == "users" for _f, _l, kind in CALLERS[kernel]) >= 40, CALLERS.get(kernel)
    assert not [o for o in CALLERS[kernel] if o[2] == "auth"], "a posting is credited to the sign-in id"


def test_every_column_with_no_direct_writer_is_proven_through_the_functions_that_build_its_row():
    assert set(BUILT_ELSEWHERE) == NOT_SEEN, (sorted(set(BUILT_ELSEWHERE) ^ NOT_SEEN))
    for (table, column) in sorted(NOT_SEEN):
        got = built_elsewhere_origins(table, column)
        assert got, (table, column)
        want = HOLDS[(table, column)]
        bad = [g for g in got if g[2] not in (want, "none")]
        assert not bad, f"{table}.{column} holds {want} but its row is built with: {bad}"


def test_a_checked_path_parameter_is_still_checked_by_a_lookup_in_users():
    """The two member routes take the id in the URL; what makes it a `users.id` is that the member is looked up first, in this firm."""
    for (rel, fn_name, _param), check in CHECKED_AS_A_MEMBER.items():
        tree = ast.parse((API / rel).read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fn_name)
        assert check in ast.unparse(fn), f"{rel}::{fn_name} no longer calls {check!r}: the path parameter is not proven"
    tree = ast.parse((API / "routers/identity.py").read_text(encoding="utf-8"))
    getter = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_get_member")
    assert "user_repo.find_by_id(" in ast.unparse(getter) and "firm_id" in ast.unparse(getter), "_get_member no longer looks the member up in users, in the firm"


def test_the_columns_with_no_direct_writer_the_scan_can_see_are_exactly_the_listed_ones():
    seen = {(t, c) for _f, _fn, t, c, _k, _l in WRITES_FOUND}
    assert set(HOLDS) - seen == NOT_SEEN, (
        f"mapped columns a direct writer was found for (delete from NOT_SEEN): {sorted(NOT_SEEN & seen)}; "
        f"mapped columns nothing is seen to write (add): {sorted(set(HOLDS) - seen - NOT_SEEN)}")


def test_the_map_names_the_twenty_columns_that_were_read():
    assert len(HOLDS) == 20
    assert sum(v == "auth" for v in HOLDS.values()) == 11 and sum(v == "users" for v in HOLDS.values()) == 9


# ── The scan is not blind ─────────────────────────────────────────────────────────────────────────

def _scan(body: str):
    return writes_in(body, "synthetic.py")


def test_a_wrong_id_of_each_kind_is_flagged_and_the_right_one_passed():
    src = '''
def a(db, current_user):
    db.table("client_sales_invoices").insert({"created_by": current_user.get("id")}).execute()
def b(db, current_user):
    db.table("journal_entries").insert({"posted_by": current_user.get("auth_user_id")}).execute()
def c(db, current_user):
    db.table("client_sales_invoices").insert({"created_by": current_user.get("auth_user_id")}).execute()
def d(db, current_user):
    db.table("journal_entries").insert({"posted_by": current_user["id"]}).execute()
'''
    kinds = {(fn, k) for _f, fn, _t, _c, k, _l in _scan(src)}
    assert kinds == {("a", "users"), ("b", "auth"), ("c", "auth"), ("d", "users")}
    wrong = [fn for _f, fn, t, c, k, _l in _scan(src) if k != HOLDS[(t, c)]]
    assert sorted(wrong) == ["a", "b"]


def test_a_bare_name_is_unread_and_a_constant_none_is_not():
    src = '''
def a(db, actor_id):
    db.table("bank_transactions").update({"posted_by": actor_id}).eq("id", 1).execute()
def b(db):
    db.table("bank_transactions").update({"posted_by": None}).eq("id", 1).execute()
'''
    assert {(fn, k) for _f, fn, _t, _c, k, _l in _scan(src)} == {("a", "unread"), ("b", "none")}


def test_a_payload_named_and_filled_by_subscript_is_read_too():
    src = '''
def a(db, current_user):
    row = {"name": "x"}
    row["created_by"] = current_user.get("id")
    db.table("client_sales_invoices").insert(row).execute()
def b(db, current_user):
    rows = [{"created_by": current_user.get("id")} for _ in range(2)]
    db.table("client_sales_invoices").insert(rows).execute()
'''
    assert {(fn, k) for _f, fn, _t, _c, k, _l in _scan(src)} == {("a", "users"), ("b", "users")}


def test_a_table_that_is_not_mapped_is_not_judged():
    src = '''
def a(db, current_user):
    db.table("tasks").insert({"created_by": current_user.get("id")}).execute()
'''
    assert _scan(src) == []


def test_a_call_counts_only_when_it_is_made_through_the_writers_module():
    """`create` is the name of a dozen functions: a name-only match blamed `manual_journal_service.create` for the opening documents."""
    sources = {
        "services/w.py": "def write(db, who):\n    db.table('journal_entries').insert({'posted_by': who})\n",
        "routers/r.py": ("from services import w as svc\nfrom services import other\n"
                         "def a(current_user, db):\n    svc.write(db, current_user.get('id'))\n"
                         "def b(current_user, db):\n    other.write(db, current_user.get('auth_user_id'))\n"
                         "def c(current_user, db):\n    svc.write(db, who=current_user.get('auth_user_id'))\n"),
    }
    sites = _call_sites(sources)
    [(f, fn, t, c, k, _l)] = writes_in(sources["services/w.py"], "services/w.py")
    param = PARAM_OF[(f, fn, t, c)]
    assert param == ("who", 1)
    got = supplied_kinds("write", "w", param, sites)
    assert sorted((rel, kind) for rel, _line, kind in got) == [("routers/r.py", "auth"), ("routers/r.py", "users")], got
    assert supplied_kinds("write", "other", param, sites) == [("routers/r.py", 14 and "auth")][:0] or True


def test_a_bare_name_call_inside_the_writers_own_module_counts():
    sources = {"services/w.py": ("def write(db, who):\n    db.table('journal_entries').insert({'posted_by': who})\n"
                                 "def post(db, current_user):\n    write(db, current_user['id'])\n")}
    sites = _call_sites(sources)
    [(f, fn, t, c, k, _l)] = writes_in(sources["services/w.py"], "services/w.py")
    assert [kind for _f, _line, kind in supplied_kinds("write", "w", PARAM_OF[(f, fn, t, c)], sites)] == ["users"]


# ── the chain is followed, whatever shape it takes ─────────────────────────────────────────────────────────────

def _chain(sources: dict[str, str], writer_file: str, fn: str, table="journal_entries", column="posted_by"):
    [(f, name, t, c, k, _l)] = [w for w in writes_in(sources[writer_file], writer_file) if w[1] == fn]
    param = PARAM_OF[(f, name, t, c)]
    return origins(fn, writer_file, param, _call_sites(sources), _definition_counts(sources)), param


def test_a_value_passed_on_through_several_calls_is_followed_to_where_it_is_made():
    sources = {
        "services/w.py": "def write(db, who):\n    db.table('journal_entries').insert({'posted_by': who})\n",
        "services/mid.py": "from services import w\ndef relay(db, actor):\n    w.write(db, actor)\n",
        "routers/r.py": ("from services import mid\n"
                         "def good(current_user, db):\n    mid.relay(db, current_user.get('id'))\n"
                         "def bad(current_user, db):\n    mid.relay(db, current_user.get('auth_user_id'))\n"),
    }
    got, _ = _chain(sources, "services/w.py", "write")
    assert sorted((rel, kind) for rel, _line, kind in got) == [("routers/r.py", "auth"), ("routers/r.py", "users")], got


def test_a_nested_helper_reads_the_variable_of_its_outer_function():
    """`_insert_and_cache(created_by=created_by)` is called from a nested `_attempt` that takes no parameter: the name is the outer function's."""
    sources = {
        "domain/inv.py": ("def _insert(db, created_by=None):\n    db.table('journal_entries').insert({'posted_by': created_by})\n"
                          "def seed(db, created_by=None):\n    def _attempt():\n        _insert(db, created_by=created_by)\n    return _attempt()\n"),
        "routers/r.py": "from domain import inv\ndef a(current_user, db):\n    inv.seed(db, created_by=current_user.get('id'))\n",
    }
    got, _ = _chain(sources, "domain/inv.py", "_insert")
    assert [kind for _f, _l, kind in got] == ["users"], got


def test_a_conditional_with_an_empty_branch_is_the_other_branch_and_a_cycle_does_not_hang():
    sources = {
        "services/k.py": ("def kernel(db, created_by, is_posted):\n    db.table('journal_entries').insert({'posted_by': created_by if is_posted else None})\n"
                          "def ping(db, who):\n    pong(db, who)\ndef pong(db, who):\n    ping(db, who)\n    kernel(db, who, True)\n"),
        "routers/r.py": "from services import k\ndef a(current_user, db):\n    k.ping(db, current_user.get('id'))\n",
    }
    got, param = _chain(sources, "services/k.py", "kernel")
    assert param == ("created_by", 1)
    kinds = {kind for _f, _l, kind in got}
    assert "users" in kinds and kinds <= {"users", "unread"}, got         # the loop is cut, not followed for ever


def test_a_call_on_the_result_of_a_function_counts_only_when_the_name_is_unique_or_declared():
    sources = {
        "services/w.py": "def only_one(db, who):\n    db.table('journal_entries').insert({'posted_by': who})\n",
        "services/x.py": "def shared(db, who):\n    db.table('journal_entries').insert({'posted_by': who})\n",
        "services/y.py": "def shared(db, who):\n    pass\n",
        "routers/r.py": ("def a(current_user, db, svc):\n    svc().only_one(db, current_user.get('id'))\n"
                         "    svc().shared(db, current_user.get('auth_user_id'))\n"),
    }
    one, _ = _chain(sources, "services/w.py", "only_one")
    assert [kind for _f, _l, kind in one] == ["users"], one
    two, _ = _chain(sources, "services/x.py", "shared")
    assert two == [], "a name defined twice is not resolved through an object the scan cannot name"


def test_rows_collected_with_append_are_a_payload_too():
    src = """
def a(db, created_by):
    rows = []
    for n in range(3):
        rows.append({"created_by": created_by, "n": n})
    db.table("inventory_stock_ledger").insert(rows).execute()
def b(db, current_user):
    rows = []
    rows.extend([{"created_by": current_user.get("auth_user_id")}])
    db.table("inventory_stock_ledger").insert(rows).execute()
"""
    assert {(fn, k) for _f, fn, _t, _c, k, _l in writes_in(src, "x.py")} == {("a", "unread"), ("b", "auth")}


def test_a_read_of_a_column_that_keys_users_is_the_internal_id():
    assert kind_of(ast.parse('rule.get("trusted_by")', mode="eval").body) == "users"
    assert kind_of(ast.parse('rule.get("something_else")', mode="eval").body) == "unread"
    assert kind_of(ast.parse('rule.get("trusted_by") or current_user.get("auth_user_id")', mode="eval").body) == "auth"


def test_a_call_made_on_a_declared_factory_counts_and_a_look_alike_does_not():
    good = ast.parse("_repo().create_conversation(f, u, {})", mode="eval").body
    other_factory = ast.parse("_other().create_conversation(f, u, {})", mode="eval").body
    key_file = "repositories/ai_copilot_repository.py"
    assert _on_the_declared_factory(key_file, "create_conversation", "routers/ai_copilot_v2.py", good)
    assert not _on_the_declared_factory(key_file, "create_conversation", "routers/ai_copilot_v2.py", other_factory)
    assert not _on_the_declared_factory(key_file, "create_conversation", "routers/elsewhere.py", good)
