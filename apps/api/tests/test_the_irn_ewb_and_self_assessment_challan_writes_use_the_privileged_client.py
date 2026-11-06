"""The e-invoice records, the e-way bill records and the section 140A challans are WRITTEN with the privileged client, and the source says so at the write (POST-A-394).

THE PREMISE
    Production grants `authenticated` INSERT, UPDATE, DELETE and TRUNCATE on `einvoice_records`, `eway_bill_records` and `self_assessment_challans` (read from the
    database on 6-11-2026), behind row policies that ask the firm and the client assignment, and nothing else. The browser never touches them (no `.from()` on any of the three
    in `apps/web`), so the only writers are the API's, and a hand-made PostgREST request from a signed-in session reaches an IRN record, an e-way bill record or a challan
    that no route would have written: the day a portal printed is refused by the route and not by the table, the invoice a record names is asked by the route and not by the
    table, and a challan's duplicate check is a route's too.

    Migration 583 takes the write grants away. THIS is the half that must ship BEFORE it, in an earlier change: an API instance that is still serving when the grant goes, and
    that writes with the caller's own sign-in (`USE_USER_JWT`, the production default), would answer "permission denied" to a CA recording an IRN. So every write to the three
    tables is made with the privileged client now, which carries no row security: what the policies did (the firm, the client assignment, the role tier) is the caller's to
    assert, and the routes that reach these tables already do (`rbac()`, `assert_client_access`, `named_row_ownership`, `_assert_record_scope`, `_assert_ewb_scope`, and a
    `firm_id` on every write). `privileged_for` labels the client with the person of the request, so the row-level edit log still names who made the change.

THE RULE, NOT A SPELLING OF IT
    Every `.insert`, `.update`, `.upsert` or `.delete` made on `.table("<one of the three>")` starts from a privileged expression: a call of `privileged_for(...)` /
    `service_db()` / `service_db_or_none()` / `service_db_or_503()` / `get_service_supabase()`, a module-level name bound to one of them (`_db = db_provider.service_db_or_none`),
    a no-argument function that returns one (`_writer()`), or a local bound only to such an expression. A PARAMETER is never privileged, whatever its caller passes. The judgement
    is the one `test_a_payroll_bank_or_document_table_is_queried_with_the_privileged_client.py` makes for a payroll, bank or document table (it is imported, not copied: two
    copies of "what is privileged" would drift), applied to WRITES ONLY: a read of these three tables stays with the caller's client, whose row policies are the second lock on it.

WHAT IT DOES NOT SEE
    A table chosen at run time (`.table(name)`), a write made by a database function or a trigger, and a client held in an attribute. None of the three tables is reached any of those
    ways today; the census test below fails if a write site disappears, so the rule cannot go vacuous.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from tests import _table_uses as tu
from tests.test_a_payroll_bank_or_document_table_is_queried_with_the_privileged_client import (
    _Scope, _chain_receiver, _enclosing_function, is_privileged, privileged_names)

TABLES = frozenset({"einvoice_records", "eway_bill_records", "self_assessment_challans"})
WRITE_VERBS = frozenset({"insert", "update", "upsert", "delete"})

#: How many write sites each table has today. A change that adds or removes one updates this, so the rule is read against the real count.
WRITE_SITES = {"einvoice_records": 3, "eway_bill_records": 4, "self_assessment_challans": 2}


def _table_call_of(verb_call: ast.Call) -> ast.Call | None:
    """For `X.table("T").insert(...)`: the `X.table("T")` call, when the verb is a write and the table is one of the three."""
    if not (isinstance(verb_call.func, ast.Attribute) and verb_call.func.attr in WRITE_VERBS):
        return None
    recv = verb_call.func.value
    if (isinstance(recv, ast.Call) and isinstance(recv.func, ast.Attribute) and recv.func.attr == "table" and recv.args
            and isinstance(recv.args[0], ast.Constant) and recv.args[0].value in TABLES):
        return recv
    return None


def write_sites(source: str) -> list[tuple[str, str, int, bool, str]]:
    """(table, enclosing function, line, privileged?, receiver) for every write to one of the three tables in `source`."""
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


def test_every_write_to_the_three_tables_starts_at_the_privileged_client():
    bad = []
    for rel, text in _runtime_sources():
        if not any(t in text for t in TABLES):
            continue
        for table, fn, line, ok, recv in write_sites(text):
            if not ok:
                bad.append(f"{rel}:{line} {fn}(): a write to {table} on {recv}")
    assert not bad, ("A write to the e-invoice records, the e-way bill records or the section 140A challans is made with the caller's own client: migration 583 takes that client's "
                     "write grant away, and the write would answer \"permission denied\" the day it applies. Make it with `privileged_for(db)` (naming the firm, after the route has "
                     "asked the client):\n  " + "\n  ".join(bad))


def test_the_census_finds_the_writes_there_are():
    """The rule must not go vacuous: the count of write sites per table is the count of today, and a change updates it."""
    found: dict[str, int] = {t: 0 for t in TABLES}
    for _rel, text in _runtime_sources():
        if not any(t in text for t in TABLES):
            continue
        for table, *_rest in write_sites(text):
            found[table] += 1
    assert found == WRITE_SITES, f"the writers of the three tables changed: {found} (expected {WRITE_SITES}); update WRITE_SITES with the change, and read the new writer against the rule above"


def test_the_browser_writes_none_of_the_three_tables():
    """The premise of the revoke: nothing in `apps/web` reaches them, so taking the grant away breaks no screen."""
    web = Path(__file__).resolve().parents[2] / "web"
    hits = []
    for folder in ("app", "components", "lib"):
        for path in (web / folder).rglob("*.ts*"):
            if path.suffix not in {".ts", ".tsx"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for t in TABLES:
                # A table is reached by `.from("<table>")` (PostgREST); a comment that names it is not an access.
                if re.search(r"\.from\(\s*[\"'`]" + t + r"[\"'`]", text):
                    hits.append(f"{path.relative_to(web)} reads or writes {t}")
    assert not hits, "the browser reaches one of the three tables; it must be moved behind the API before the grant is taken away:\n  " + "\n  ".join(hits)


# ── the detector is tested on what it reads ──────────────────────────────────

def _flagged(src: str) -> list[str]:
    head = "from core import db_provider\nfrom core.db_provider import privileged_for\n"
    return [f"{fn}:{table}" for table, fn, _l, ok, _r in write_sites(head + src) if not ok]


def test_a_write_on_a_parameter_or_the_request_client_is_flagged():
    assert _flagged('def f(db):\n    db.table("einvoice_records").insert({}).execute()\n') == ["f:einvoice_records"]
    assert _flagged('def f():\n    sb = db_provider.request_db()\n    sb.table("eway_bill_records").update({}).eq("id", 1).execute()\n') == ["f:eway_bill_records"]
    assert _flagged('def f(db):\n    db.table("self_assessment_challans").delete().eq("id", 1).execute()\n') == ["f:self_assessment_challans"]
    assert _flagged('def f(db):\n    db.table("einvoice_records").upsert({}).execute()\n') == ["f:einvoice_records"]


def test_the_door_the_alias_and_a_local_bound_to_one_are_not_flagged():
    assert _flagged('def f(db):\n    privileged_for(db).table("einvoice_records").insert({}).execute()\n') == []
    assert _flagged('def f(db):\n    sb = privileged_for(db)\n    sb.table("eway_bill_records").update({}).execute()\n') == []
    assert _flagged('_db = db_provider.service_db_or_none\ndef f():\n    _db().table("self_assessment_challans").insert({}).execute()\n') == []
    assert _flagged('def _writer():\n    return db_provider.privileged_for(object())\ndef f():\n    sb = _writer()\n    sb.table("einvoice_records").update({}).execute()\n') == []


def test_a_read_is_left_alone_and_so_is_another_table():
    assert _flagged('def f(db):\n    return db.table("einvoice_records").select("*").execute()\n') == []
    assert _flagged('def f(db):\n    db.table("some_other_table").insert({}).execute()\n') == []


def test_a_local_bound_to_the_request_client_in_one_branch_is_flagged():
    src = 'def f(db, flag):\n    sb = privileged_for(db)\n    if flag:\n        sb = db\n    sb.table("einvoice_records").insert({}).execute()\n'
    assert _flagged(src) == ["f:einvoice_records"]
