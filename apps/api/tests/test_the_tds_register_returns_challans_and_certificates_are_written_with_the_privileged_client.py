"""The TDS register, the TDS returns, the TDS challans and the TDS certificates are WRITTEN with the privileged client, and the source says so at the write (POST-A-443).

THE PREMISE
    Migration 345 left the signed-in role INSERT and UPDATE on `tds_deductions`, `tds_returns`, `tds_challans` and `tds_certificates` (Executive and above) and DELETE
    (Manager and above), behind row policies that ask the firm, the client assignment and the role tier, and nothing else. The browser never touches them (no `.from()` on any
    of the four in `apps/web`), so the only writers are the API's, and a hand-made PostgREST request from a signed-in session reaches a register row, a return, a challan or a
    certificate that no route would have written: the tax on a typed deduction is the engine's and not the caller's, a section the engine cannot answer for is refused by the
    route, a filed return's PRN and date are asked by the route, and a challan's duplicate and its day are the route's too. Found on 15-11-2026 while designing POST-A-078,
    which would make a typed register row count toward a supplier's yearly total, so that a hand-made row could lower the tax a later bill withholds.

    A later migration takes the write grants away. THIS is the half that must ship BEFORE it, in an earlier change: an API instance that is still serving when the grant goes,
    and that writes with the caller's own sign-in (`USE_USER_JWT`, the production default), would answer "permission denied" to a CA recording a deduction. So every write to
    the four tables is made with the privileged client now, which carries no row security: what the policies did (the firm, the client assignment, the role tier and,
    from migration 074, the firm's own practice being a Partner's) is the caller's to assert, and the routes that reach these tables do: `rbac("tds", "compute")` where
    the policy asked Executive and `rbac("tds", "write")` where it asked Manager, which is THE PERSON'S permission and can be wider than the role tier (a Partner may grant
    a member `tds` on the Team grid, where the policy asked the role alone); `assert_client_access` or `_visible_or_none` on the row; the router's client guard on a
    request that names a client and `assert_partner_for_internal_id` on the three that name a row (a deduction's correction and removal, a return's status); and the
    firm and the client named on every write. `privileged_for` labels the client with the person of the request, so the row-level edit log still names who made the
    change.

THE RULE, NOT A SPELLING OF IT
    As for the e-invoice records (POST-A-394), and with that test's judgement of what is privileged imported, not copied: every `.insert`, `.update`, `.upsert` or `.delete`
    made on `.table("<one of the four>")` starts from a privileged expression. A PARAMETER is never privileged, whatever its caller passes. Reads stay with the caller's client,
    whose row policies are the second lock on them.

WHAT IT DOES NOT SEE
    A table chosen at run time (`.table(name)`), a write made by a database function or a trigger, and a client held in an attribute. None of the four tables is written any of
    those ways today; the census test below fails if a write site appears or disappears, so the rule cannot go vacuous. On the browser's side the check reads code with its
    comments taken out and allows a table's name only as `.from("<table>")` followed at once by `.select(`: a name handed to a call (a shared delete door), a builder kept in a
    variable, a cast, or a constant is reported. It does not see a name assembled from pieces at run time.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from tests import _table_uses as tu
from tests.test_a_payroll_bank_or_document_table_is_queried_with_the_privileged_client import (
    _Scope, _chain_receiver, _enclosing_function, is_privileged, privileged_names)

TABLES = frozenset({"tds_deductions", "tds_returns", "tds_challans", "tds_certificates"})
WRITE_VERBS = frozenset({"insert", "update", "upsert", "delete"})

#: How many write sites each table has today. A change that adds or removes one updates this, so the rule is read against the real count.
WRITE_SITES = {"tds_deductions": 7, "tds_returns": 3, "tds_challans": 4, "tds_certificates": 1}


def _table_call_of(verb_call: ast.Call) -> ast.Call | None:
    """For `X.table("T").insert(...)`: the `X.table("T")` call, when the verb is a write and the table is one of the four."""
    if not (isinstance(verb_call.func, ast.Attribute) and verb_call.func.attr in WRITE_VERBS):
        return None
    recv = verb_call.func.value
    if (isinstance(recv, ast.Call) and isinstance(recv.func, ast.Attribute) and recv.func.attr == "table" and recv.args
            and isinstance(recv.args[0], ast.Constant) and recv.args[0].value in TABLES):
        return recv
    return None


def write_sites(source: str) -> list[tuple[str, str, int, bool, str]]:
    """(table, enclosing function, line, privileged?, receiver) for every write to one of the four tables in `source`."""
    tree = ast.parse(source)
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    names = privileged_names(tree)
    scope = _Scope(tree, parents)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        table_call = _table_call_of(node)
        if table_call is None:
            continue
        fn = _enclosing_function(node, parents)
        recv = _chain_receiver(table_call)
        out.append((table_call.args[0].value, fn.name if fn else "<module>", node.lineno, is_privileged(recv, names, scope, node), ast.unparse(recv)[:60]))
    return out


def _runtime_sources():
    for rel, text in tu.sources():
        if not rel.startswith(("scripts/", "tests/")):
            yield rel, text


def test_every_write_to_the_four_tds_tables_starts_at_the_privileged_client():
    bad = []
    for rel, text in _runtime_sources():
        if not any(t in text for t in TABLES):
            continue
        for table, fn, line, ok, recv in write_sites(text):
            if not ok:
                bad.append(f"{rel}:{line} {fn}(): a write to {table} on {recv}")
    assert not bad, ("A write to the TDS register, a TDS return, a TDS challan or a TDS certificate is made with the caller's own client: the migration that follows this "
                     "change takes that client's write grant away, and the write would answer \"permission denied\" the day it applies. Make it with `privileged_for(db)` "
                     "(naming the firm and the client, after the route has asked the client):\n  " + "\n  ".join(bad))


def _outer_chain(node: ast.AST, parents: dict) -> ast.AST:
    """The whole method chain a write sits in: `X.table(T).update({...}).eq(...).eq(...).execute()` from its `.update(...)` call."""
    while True:
        parent = parents.get(node)
        if isinstance(parent, ast.Attribute) and isinstance(parents.get(parent), ast.Call) and parents[parent].func is parent:
            node = parents[parent]
            continue
        return node


def unscoped_updates_and_deletes(source: str) -> list[str]:
    """Every `.update(` or `.delete(` on one of the four tables whose chain does not filter `client_id`: the privileged client carries no row security, so the
    firm AND the client the route checked must both be in the statement (CLAUDE.md, "A ROUTE THAT ASSERTS THE CLIENT THE CALLER NAMED ACTS ONLY ON A ROW OF THAT CLIENT")."""
    tree = ast.parse(source)
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _table_call_of(node) is None or node.func.attr not in {"update", "delete"}:
            continue
        chain = ast.unparse(_outer_chain(node, parents))
        if not re.search(r"\.eq\(\s*['\"]client_id['\"]", chain) or not re.search(r"\.eq\(\s*['\"]firm_id['\"]", chain):
            out.append(f"{_table_call_of(node).args[0].value} at line {node.lineno}")
    return out


def test_every_update_and_delete_of_the_four_tables_names_the_firm_and_the_client():
    bad = []
    for rel, text in _runtime_sources():
        if not any(t in text for t in TABLES):
            continue
        bad += [f"{rel}: {hit}" for hit in unscoped_updates_and_deletes(text)]
    assert not bad, ("an update or a delete of a TDS table does not name both the firm and the client; on the privileged client nothing else keeps it inside the "
                     "client the route checked:\n  " + "\n  ".join(bad))


def test_the_scope_check_reads_the_whole_chain():
    assert unscoped_updates_and_deletes('def f(db):\n    privileged_for(db).table("tds_deductions").delete().eq("id", 1).eq("firm_id", 2).execute()\n') == ["tds_deductions at line 2"]
    assert unscoped_updates_and_deletes(
        'def f(db):\n    privileged_for(db).table("tds_returns").update({}).eq("id", 1).eq("firm_id", 2).eq("client_id", 3).execute()\n') == []
    assert unscoped_updates_and_deletes('def f(db):\n    privileged_for(db).table("tds_challans").update({}).eq("client_id", 3).execute()\n') == ["tds_challans at line 2"]
    assert unscoped_updates_and_deletes('def f(db):\n    privileged_for(db).table("tds_certificates").insert({}).execute()\n') == []


def test_the_census_finds_the_writes_there_are():
    """The rule must not go vacuous: the count of write sites per table is the count of today, and a change updates it."""
    found: dict[str, int] = {t: 0 for t in TABLES}
    for _rel, text in _runtime_sources():
        if not any(t in text for t in TABLES):
            continue
        for table, *_rest in write_sites(text):
            found[table] += 1
    assert found == WRITE_SITES, f"the writers of the four tables changed: {found} (expected {WRITE_SITES}); update WRITE_SITES with the change, and read the new writer against the rule above"


def _without_comments(text: str) -> str:
    """The source with `/* */` blocks (JSX's `{/* */}` included) and `//` line comments taken out, so a comment that NAMES a table is not read as code.
    Crude on purpose: a `//` inside a string literal (a URL) ends that line's reading early, which can only hide code on the rest of that line."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def browser_writes(text: str) -> list[str]:
    """The tables of the four that a TypeScript source may WRITE or hand to something that writes, which the revoke would break.

    A name of one of the four in code (not a comment) is allowed in exactly one shape: `.from("<table>")` followed at once by `.select(`, which is a
    read, and a read keeps working after the grant goes (the migration takes the writes away and leaves SELECT and the row policies as they are).
    Every other appearance is reported: `.from("<table>")` followed by anything else (`.insert`, `.update`, `.upsert`, `.delete`, or a builder kept in
    a variable and written later), and the name passed to a call or held as a value (`deleteRowAndConfirm(sb, "tds_certificates", id)` deletes through
    `sb.from(table).delete()`, which names no table at the `.from`)."""
    code = _without_comments(text)
    out = []
    for m in re.finditer(r"[\"'`](" + "|".join(sorted(TABLES)) + r")[\"'`]", code):
        before = code[: m.start()]
        after = code[m.end():]
        is_from_argument = re.search(r"\.from\(\s*$", before) is not None and re.match(r"\s*\)", after) is not None
        if is_from_argument:
            rest = after[re.match(r"\s*\)", after).end():]
            if re.match(r"\s*\.select\(", rest):
                continue
        out.append(m.group(1))
    return out


def test_the_browser_writes_none_of_the_four_tables():
    """The premise of the revoke: nothing in `apps/web` WRITES them, so taking the write grant away breaks no screen."""
    web = Path(__file__).resolve().parents[2] / "web"
    hits = []
    for folder in ("app", "components", "lib"):
        for path in (web / folder).rglob("*.ts*"):
            if path.suffix not in {".ts", ".tsx"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for t in browser_writes(text):
                hits.append(f"{path.relative_to(web)} writes {t}")
    assert not hits, "the browser writes one of the four tables; it must be moved behind the API before the grant is taken away:\n  " + "\n  ".join(hits)


def test_the_browser_check_tells_a_write_from_a_read():
    assert browser_writes('const r = await sb.from("tds_returns").select("*").eq("id", x);') == []
    assert browser_writes('const r = await sb\n    .from("tds_returns")\n    .select("*")\n    .eq("firm_id", f);') == []
    assert browser_writes('await sb.from("tds_deductions").insert({ a: 1 });') == ["tds_deductions"]
    assert browser_writes('await sb\n  .from("tds_challans")\n  .update({ a: 1 })\n  .eq("id", x);') == ["tds_challans"]
    assert browser_writes('await sb.from("tds_certificates").delete().eq("id", x);') == ["tds_certificates"]
    assert browser_writes('await sb.from("tds_returns").select("*"); await other.update(1);') == []


def test_the_browser_check_sees_a_name_handed_on_or_a_builder_kept():
    """The shapes the review of 15-11-2026 named: a shared delete door that takes the table as an argument, a query builder kept in a variable and
    written on the next line, and a cast at the `.from`."""
    assert browser_writes('await deleteRowAndConfirm(sb, "tds_certificates", id);') == ["tds_certificates"]
    assert browser_writes('const q = sb.from("tds_returns"); await q.update({ a: 1 });') == ["tds_returns"]
    assert browser_writes('await sb.from("tds_returns" as const).update({});') == ["tds_returns"]
    assert browser_writes('const T = "tds_deductions";') == ["tds_deductions"]


def test_a_comment_that_names_a_table_is_not_code():
    assert browser_writes('// This used to read `tds_deductions` straight from the browser.\nconst x = 1;') == []
    assert browser_writes('/* the COLUMNS OF `tds_deductions` */ const x = 1;') == []
    assert browser_writes('{/* `tds_returns` stores no such status */}') == []


# ── the detector is tested on what it reads ──────────────────────────────────

def _flagged(src: str) -> list[str]:
    head = "from core import db_provider\nfrom core.db_provider import privileged_for\n"
    return [f"{fn}:{table}" for table, fn, _l, ok, _r in write_sites(head + src) if not ok]


def test_a_write_on_a_parameter_or_the_request_client_is_flagged():
    assert _flagged('def f(db):\n    db.table("tds_deductions").insert({}).execute()\n') == ["f:tds_deductions"]
    assert _flagged('def f():\n    sb = db_provider.request_db()\n    sb.table("tds_returns").update({}).eq("id", 1).execute()\n') == ["f:tds_returns"]
    assert _flagged('def f(db):\n    db.table("tds_challans").delete().eq("id", 1).execute()\n') == ["f:tds_challans"]
    assert _flagged('def f(db):\n    db.table("tds_deductions").upsert({}).execute()\n') == ["f:tds_deductions"]


def test_the_door_the_alias_and_a_local_bound_to_one_are_not_flagged():
    assert _flagged('def f(db):\n    privileged_for(db).table("tds_deductions").insert({}).execute()\n') == []
    assert _flagged('def f(db):\n    sb = privileged_for(db)\n    sb.table("tds_returns").update({}).execute()\n') == []
    assert _flagged('_db = db_provider.service_db_or_none\ndef f():\n    _db().table("tds_challans").insert({}).execute()\n') == []
    assert _flagged('def _writer():\n    return db_provider.privileged_for(object())\ndef f():\n    sb = _writer()\n    sb.table("tds_deductions").update({}).execute()\n') == []


def test_a_read_is_left_alone_and_so_is_another_table():
    assert _flagged('def f(db):\n    return db.table("tds_deductions").select("*").execute()\n') == []
    assert _flagged('def f(db):\n    db.table("some_other_table").insert({}).execute()\n') == []


def test_a_local_bound_to_the_request_client_in_one_branch_is_flagged():
    src = 'def f(db, flag):\n    sb = privileged_for(db)\n    if flag:\n        sb = db\n    sb.table("tds_deductions").insert({}).execute()\n'
    assert _flagged(src) == ["f:tds_deductions"]
