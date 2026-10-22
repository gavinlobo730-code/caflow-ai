"""No code of the API hard-deletes a client row, and a client is deleted by marking it (ledger POST-A-303).

THE PREMISE THIS HOLDS
    `tally_migration_jobs.client_id` is ON DELETE SET NULL and a job with no client is open to the whole firm (migration 528),
    so a client row that was hard-deleted would turn its Tally job, and the parsed ledgers, customers and vendors under it, into a
    firm-level job every member reads. The item was filed as a defect of "deleting a client". It is not reachable: the API's
    client delete is a SOFT delete (`client_repo.soft_delete` sets `deleted_at` and leaves `client_id` on every row that hangs
    from it, the job included), a client with historical records cannot be deleted at all (`_check_delete_blockers`), and the one
    statement that removes client rows, the `platform_purge_firm` function, removes the whole firm with them and clears every
    firm-scoped table, the Tally jobs and their items among them, first (the real-database half is
    `test_a_firm_purge_removes_a_clients_tally_jobs_with_it_pg.py`).

    So the severity rests on "nothing hard-deletes a client", and this is that claim as a test (the rule of
    `test_an_unreachable_premise_fails_when_it_becomes_reachable.py`, which has two probes, a route and a symbol, and none for a
    table verb). The day a route or a script deletes a client row, this fails, and the fix is to decide what happens to the
    client's Tally job (keep it Partner-only, or delete it with the client) in the same change.

WHAT IT SEES AND WHAT IT DOES NOT
    * it sees a `delete` chained off `.table("clients")` / `.from_("clients")` and `DELETE FROM clients` written in a string, in
      every module the API runs or ships, `scripts/` included (the scanner of `tests/_table_uses.py`, with its own negative
      controls in the tests that use it);
    * it does not see a delete on a query kept in a variable (`q = db.table("clients")` ... `q.delete()`): a clients query is
      kept in a variable for reads in many places, and flagging them all would make the guard noise. A table name held in a
      constant is seen by the scanner as `named`, which is not asserted either.
"""
from __future__ import annotations

import ast
import re

from tests._table_uses import API_ROOT, sources, uses


def _hard_deletes(text: str) -> list[tuple[str, str, int]]:
    return [(kind, fn, line) for kind, fn, line, _receiver, verbs in uses(text, "clients")
            if (kind == "write" and "delete" in verbs) or (kind == "raw_write")]


def test_no_module_of_the_api_hard_deletes_a_client_row():
    found = {rel: hits for rel, text in sources() if "clients" in text for hits in [_hard_deletes(text)] if hits}
    assert not found, (
        f"these places delete a client row: {found}. A client's Tally job (tally_migration_jobs.client_id is ON DELETE SET NULL) "
        f"would become a firm-level job every member of the firm reads (migration 528, POST-A-303): decide what happens to it "
        f"in the same change.")


def test_the_scanner_would_see_a_client_delete_written_either_way():
    chained = 'def purge(db, cid):\n    db.table("clients").delete().eq("id", cid).execute()\n'
    keyword = 'def purge(db, cid):\n    db.table(name="clients").delete().eq("id", cid).execute()\n'
    sql = 'def purge(cur, cid):\n    cur.execute("DELETE FROM public.clients WHERE id = %s", (cid,))\n'
    for source in (chained, keyword, sql):
        assert _hard_deletes(source), source
    soft = 'def archive(db, cid):\n    db.table("clients").update({"deleted_at": "x"}).eq("id", cid).execute()\n'
    read = 'def one(db, cid):\n    return db.table("clients").select("id").eq("id", cid).execute().data\n'
    assert _hard_deletes(soft) == [] and _hard_deletes(read) == []


def test_the_delete_route_marks_the_client_and_never_removes_it():
    tree = ast.parse((API_ROOT / "routers" / "clients.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "delete_client")
    called = {ast.unparse(c.func) for stmt in fn.body for c in ast.walk(stmt) if isinstance(c, ast.Call)}      # not the decorator
    assert "client_repo.soft_delete" in called, called
    assert not any(name.endswith(".delete") for name in called), called

    repo = ast.parse((API_ROOT / "repositories" / "client_repository.py").read_text(encoding="utf-8"))
    soft = next(n for n in ast.walk(repo) if isinstance(n, ast.FunctionDef) and n.name == "soft_delete")
    text = ast.unparse(soft)
    assert "'deleted_at'" in text and "'is_deleted'" in text and ".delete()" not in text, text


def test_the_purge_function_is_the_only_statement_that_removes_client_rows_in_the_migrations():
    """The migrations are the other place a `DELETE FROM clients` could hide. Only the three definitions of the firm purge
    (089, 090, 141) have one, and each removes the whole firm in the same function."""
    holders = []
    for path in sorted((API_ROOT / "migrations").glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        if path.name.endswith("_rollback.sql"):
            continue
        if re.search(r"(?i)delete\s+from\s+(public\.)?clients\b", text):
            holders.append(path.name)
    assert holders == ["089_platform_purge.sql", "090_platform_purge_typesafe.sql", "141_hotfix_platform_purge_firm_authz.sql"], holders
