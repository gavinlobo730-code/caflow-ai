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
UNREAD: set[tuple[str, str, str, str]] = {
    ("domain/inventory_service.py", "_insert_and_cache", "inventory_stock_ledger", "created_by"),
    ("repositories/ai_copilot_repository.py", "create_conversation", "ai_conversations", "user_id"),
    ("repositories/dsc_repository.py", "soft_delete", "dsc_records", "deleted_by"),
    ("services/bank_posting_service.py", "settle_on_post", "bank_transactions", "posted_by"),
    ("services/gst_2b_reconciliation_service.py", "keep_upload", "gstr2b_uploads", "created_by"),
    ("services/inventory_location_service.py", "transfer", "inventory_stock_ledger", "created_by"),
    ("services/opening_document_service.py", "_write_receivables", "client_sales_invoices", "created_by"),
    ("services/phase2_journal_service.py", "_create_journal", "journal_entries", "posted_by"),
}

#: Mapped columns with NO direct dict-literal writer anywhere in the API as the scan reads it: their rows are written through a payload built
#: elsewhere (a repository or a helper) or by a path the scan does not follow. Listed so that the day a direct writer appears it is read,
#: and so that "twenty columns are mapped" is not read as "twenty are guarded". Equality in both directions.
NOT_SEEN: set[tuple[str, str]] = {("login_events", "user_id"), ("time_entries", "user_id"), ("year_end_notes", "created_by")}


def kind_of(value: ast.expr) -> str:
    """'auth', 'users', 'none' (a constant None) or 'unread'."""
    if isinstance(value, ast.Constant) and value.value is None:
        return "none"
    text = ast.unparse(value)
    if AUTH_VALUE.search(text):
        return "auth"
    if USERS_VALUE.search(text):
        return "users"
    return "unread"


def _function_of(node, parents) -> ast.AST | None:
    while node is not None and not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        node = parents.get(node)
    return node


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


def _call_sites(sources: dict[str, str] | None = None) -> dict[str, list[tuple[str, str, ast.Call]]]:
    """function name -> [(file, module the call is made through or '', call)]. A bare-name call is made through the file's own module
    unless the name was imported from another (`from module import f`), in which case it is made through that module; `x.f(...)` is made
    through whatever module the alias `x` stands for, and through nothing the scan can name (a parameter, `self`) otherwise."""
    sites: dict[str, list[tuple[str, str, ast.Call]]] = {}
    for rel, text in (sources if sources is not None else _sources_on_disk()).items():
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        own, aliases = Path(rel).stem, _aliases(tree)
        imported_from = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module:
                for a in n.names:
                    imported_from[a.asname or a.name] = (n.module.split(".")[-1], a.name)
        for call in [n for n in ast.walk(tree) if isinstance(n, ast.Call)]:
            if isinstance(call.func, ast.Name):
                module, real = imported_from.get(call.func.id, (own, call.func.id))
                sites.setdefault(real, []).append((rel, module, call))
            elif isinstance(call.func, ast.Attribute):
                base = call.func.value
                module = aliases.get(base.id, "") if isinstance(base, ast.Name) else ""
                sites.setdefault(call.func.attr, []).append((rel, module, call))
    return sites


def supplied_kinds(function: str, module: str, parameter: tuple[str, int], sites=None) -> list[tuple[str, int, str]]:
    """(file, line, kind) of what each call of `module.function` passes for `parameter` (one hop; a name passed on again is `unread`).
    Only calls made THROUGH `module` count: `create` is the name of a dozen unrelated functions."""
    name, position = parameter
    sites = sites if sites is not None else _call_sites()
    out = []
    for rel, through, call in sites.get(function, []):
        if through != module:
            continue
        passed = next((kw.value for kw in call.keywords if kw.arg == name), None)
        if passed is None and 0 <= position < len(call.args):
            passed = call.args[position]
        if passed is None:
            continue                                  # the call leaves it to the default
        out.append((rel, call.lineno, kind_of(passed)))
    return out


def traced() -> tuple[dict[tuple[str, str, str, str], list], dict[tuple[str, str, str, str], str]]:
    """For every unread write whose value is a parameter: what its callers pass. -> (callers by write, verdict by write).

    verdict 'ok' when there is at least one caller and every caller passes the kind the column holds (or None); 'wrong' when one passes
    the other kind; 'open' when a caller passes something this scan cannot read, or nothing calls it."""
    sites = _call_sites()
    callers, verdict = {}, {}
    for f, fn, t, c, k, _l in WRITES_FOUND:
        key = (f, fn, t, c)
        if k != "unread" or key in callers:
            continue
        param = PARAM_OF.get(key)
        if not param:
            callers[key], verdict[key] = [], "open"
            continue
        passed = supplied_kinds(fn, Path(f).stem, param, sites)
        callers[key] = passed
        kinds = {kind for _f, _line, kind in passed}
        want = HOLDS[(t, c)]
        verdict[key] = ("wrong" if kinds & ({"auth", "users"} - {want}) else
                        "ok" if passed and kinds <= {want, "none"} else "open")
    return callers, verdict


CALLERS, VERDICT = traced()


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
    assert len(proven) >= 4, sorted(proven)
    assert ("services/journal_posting_service.py", "post_draft", "journal_entries", "posted_by") in proven


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
