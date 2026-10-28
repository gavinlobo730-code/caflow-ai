"""A route that asserts the client the caller named does not WRITE a client-owned row by its id with the firm alone (POST-A-337).

THE SHAPE
    `assert_client_access(current_user, client_id)` proves the caller may act on the client they SENT. A handler that then updates or
    deletes a row of a client-owned table with `.eq("id", x).eq("firm_id", f)` and no client filter acts on the row of ANY client of the
    firm. The 24-10-2026 hardening closed thirty-one handlers of this shape found by an AST scan, a review found fourteen more the scan
    could not see because the write sits in a service function, and sixteen were left and closed on 28-10-2026
    (`test_a_route_that_names_a_client_acts_only_on_a_row_of_that_client.py`). This is the rule that states the shape, so the next
    handler is held to it without being listed.

HOW IT LOOKS
    * the population is every `@router.<verb>` handler in `routers/` that calls `assert_client_access*`;
    * it follows a call into `services/`, `domain/` and `repositories/` by function name (a name defined once), three calls deep, because
      the write usually sits in a service;
    * a chain is a WRITE (`update`, `delete`, `upsert`) on a table that carries `client_id` (the production snapshot, plus any table a
      migration creates with the column), filtered on `id` and `firm_id`, with no filter on `client_id`;
    * a function that COMPARES a row's own client to something, or asserts access on a client taken from a row, has tied the row to a
      client already and is not flagged.

WHAT IT DOES NOT SEE (said here so the rule is not read as more than it is)
    A READ by id with the firm alone (information, not tampering) is not asked, a chain built across several statements is not followed,
    a write through a variable table name is not read, and a row tied by a helper whose body this scan does not look into is flagged and
    listed below with the reason. The list can only shrink.
"""
from __future__ import annotations

import ast
import glob
import json
import pathlib

import pytest

from tests.test_a_client_table_a_migration_creates_is_assignment_scoped import client_tables_created_by

API = pathlib.Path(__file__).resolve().parent.parent
ROUTERS = API / "routers"
CALLEE_DIRS = [API / "services", API / "domain", API / "repositories"]
DEPTH = 3

# (router file, handler): why the write is tied to the client although the scan does not see how. A handler that is fixed leaves this
# list (the second test fails on a stale entry), and a new one that fires must be fixed or added here with its reason.
REVIEWED: dict[tuple[str, str], str] = {
    ("ais.py", "add_manual_record"): "the upload id was compared with the client (`upload['client_id'] != client_id`) before totals are restated",
    ("banking.py", "create_bank_account"): "rolls back the account this request created a moment ago",
    ("banking.py", "upload_statement"): "the mapping row is keyed by the bank account the upload was already tied to (`.eq('bank_account_id', ...)`)",
    ("bills_of_entry.py", "create_bill_of_entry"): "updates the landed-cost row that a read filtered on the bill's client just returned",
    ("bills_of_entry.py", "update_bill_of_entry"): "updates the landed-cost row that a read filtered on the bill's client just returned",
    ("gst_credit_ledger.py", "put_opening"): "updates the row a read filtered on firm, client, GSTIN and window just returned",
    ("gst_credit_ledger.py", "delete_opening"): "deletes the row a read filtered on firm, client, GSTIN and window just returned",
    ("gst_workspace.py", "save_gstr1"): "updates the return `_existing_return` found by client and period",
    ("gst_workspace.py", "save_gstr3b"): "updates the return `_existing_return` found by client and period",
    ("late_interest.py", "prepare_drafts"): "takes back the draft this request created a moment ago, keyed by the id it just got",
    ("payroll.py", "import_employees"): "updates ids of the client's own roster, read by firm and client in the same request",
    ("payroll.py", "create_run"): "rolls back the run this request created a moment ago",
    ("payroll.py", "record_settlement"): "the employee was read by `_employee_of_client` (firm and client) before the status is written",
    ("payroll.py", "put_bonus_declaration"): "updates the declaration `_declaration` returned, read by firm, client and year",
    ("payroll.py", "put_bonus_disqualification"): "the employee was read by `_employee_of_client` and the row by firm, employee and year",
    ("purchase_bills.py", "delete_landed_cost"): "deletes the charge of the bill the route tied to the client (`bill_id` is part of the chain)",
    ("purchase_cycle.py", "update_receipt"): "the receipt was read by `receipt_of_client` (firm and client) before the update",
    ("sales_cycle.py", "update_quotation"): "the route calls `row_of_client` (firm and client) before the update",
    ("sales_cycle.py", "record_challan_return"): "the challan is the one the client-scoped return line belongs to (the line is looked up under the client)",
    ("sales_cycle.py", "update_challan"): "the route calls `row_of_client` (firm and client) before the update",
    ("task_recurring.py", "update_recurring"): "`_assert_config_scope` asserts access on the config's own client before the update",
}


# ── the population: tables that carry client_id ────────────────────────────────────────────────────────────────────────────
def client_tables() -> set[str]:
    # The newest snapshot; the sibling *.meta.json describes it and is not one (`tests/production_types.py` reads them the same way).
    snapshots = sorted(f for f in glob.glob(str(API / "tests/fixtures/production_schema_*.json")) if not f.endswith(".meta.json"))
    snap = json.loads(pathlib.Path(snapshots[-1]).read_text(encoding="utf-8"))
    tables = {t for t, cols in snap.items() if isinstance(cols, dict) and "client_id" in cols}
    for path in (API / "migrations").glob("*.sql"):
        if not path.name.endswith("_rollback.sql"):
            tables |= set(client_tables_created_by(path.read_text(encoding="utf-8")))
    return tables


# ── the scan ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _call_name(call: ast.Call):
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)


def _literal(node):
    return node.value if isinstance(node, ast.Constant) else None


def _chain(call: ast.Call) -> list[tuple[str, ast.Call]]:
    out, node = [], call
    while isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        out.append((node.func.attr, node))
        node = node.func.value
    return out


def ties_a_row_to_its_client(fn: ast.AST) -> bool:
    """True if the function compares a row's own client_id to something, or asserts access on a client taken from a row."""
    for n in ast.walk(fn):
        if isinstance(n, ast.Compare) and "client_id" in ast.dump(n) and ("Subscript" in ast.dump(n) or "'get'" in ast.dump(n)):
            return True
        if isinstance(n, ast.Call) and (_call_name(n) or "").startswith("assert_client_access") and len(n.args) >= 2:
            arg = n.args[1]
            if isinstance(arg, (ast.Subscript, ast.Call)) and "client_id" in ast.dump(arg):
                return True
    return False


def untied_writes(fn: ast.AST, tables: set[str]) -> list[tuple[str, int]]:
    """(table, line) of every write by id and firm with no client filter, in this function alone."""
    if ties_a_row_to_its_client(fn):
        return []
    inner = {id(n.func.value) for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Call)}
    found = []
    for n in ast.walk(fn):
        if not isinstance(n, ast.Call) or id(n) in inner or not isinstance(n.func, ast.Attribute):
            continue
        chain = _chain(n)
        if not any(m in ("update", "delete", "upsert") for m, _ in chain):
            continue
        table, keys, tied = None, set(), False
        for method, call in chain:
            first = _literal(call.args[0]) if call.args else None
            if method == "table" and first:
                table = first
            elif method in ("eq", "in_") and first:
                keys.add(first)
            if first == "client_id" and method in ("eq", "in_", "is_"):
                tied = True
            if method == "or_" and any("client_id" in ast.dump(a) for a in call.args):
                tied = True
        if table in tables and {"id", "firm_id"} <= keys and not tied:
            found.append((table, n.lineno))
    return found


def _function_index() -> dict[str, list[tuple[str, ast.AST]]]:
    index: dict[str, list[tuple[str, ast.AST]]] = {}
    for directory in CALLEE_DIRS:
        for path in directory.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    index.setdefault(node.name, []).append((path.relative_to(API).as_posix(), node))
    return index


def _reach(fn: ast.AST, index, tables, depth=DEPTH, seen=None) -> list[tuple[str, str, int]]:
    seen = seen if seen is not None else set()
    found: list[tuple[str, str, int]] = []
    if depth == 0:
        return found
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            name = _call_name(n)
            if name in index and len(index[name]) == 1:
                path, callee = index[name][0]
                if (path, name) in seen:
                    continue
                seen.add((path, name))
                found += [(f"{path}:{name}", t, ln) for t, ln in untied_writes(callee, tables)]
                found += _reach(callee, index, tables, depth - 1, seen)
    return found


def handlers_that_fire(source: str, filename: str, tables: set[str], index) -> list[tuple[str, str]]:
    """(handler, where) for each handler that asserts a client and reaches an untied write."""
    out = []
    for fn in ast.walk(ast.parse(source, filename)):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorated = any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and getattr(d.func.value, "id", "") == "router"
                        for d in fn.decorator_list)
        asserts = any(isinstance(n, ast.Call) and (_call_name(n) or "").startswith("assert_client_access") for n in ast.walk(fn))
        if not (decorated and asserts) or ties_a_row_to_its_client(fn):
            continue
        for table, line in untied_writes(fn, tables):
            out.append((fn.name, f"{table} (line {line})"))
        for where, table, line in _reach(fn, index, tables):
            out.append((fn.name, f"{where} -> {table} (line {line})"))
    return out


@pytest.fixture(scope="module")
def world():
    return client_tables(), _function_index()


def _fired(world) -> set[tuple[str, str]]:
    tables, index = world
    fired = set()
    for path in sorted(ROUTERS.glob("*.py")):
        for handler, _ in handlers_that_fire(path.read_text(encoding="utf-8"), str(path), tables, index):
            fired.add((path.name, handler))
    return fired


# ── the rule ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_no_handler_writes_a_client_owned_row_by_the_firm_alone_unless_it_is_reviewed(world):
    unreviewed = sorted(_fired(world) - set(REVIEWED))
    assert not unreviewed, (
        "a handler asserts the client the caller named and then updates or deletes a row of a client-owned table by id with the firm "
        "alone, so it acts on the row of ANY client of the firm. Add `.eq('client_id', client_id)` to the write (and pass the client "
        "down to the service), or tie the row to the client before it is written. If the row is already tied by a step this scan cannot "
        "see, add the handler to REVIEWED with the reason. " + ", ".join(f"{f}::{h}" for f, h in unreviewed))


def test_every_reviewed_entry_still_fires_so_the_list_can_only_shrink(world):
    stale = sorted(set(REVIEWED) - _fired(world))
    assert not stale, f"these entries no longer fire (the handler was fixed or removed): delete them from REVIEWED: {stale}"


def test_the_scan_is_not_vacuous(world):
    tables, index = world
    assert len(tables) >= 200, f"only {len(tables)} tables carry client_id: the snapshot or the migration scan moved"
    handlers = 0
    for path in ROUTERS.glob("*.py"):
        for fn in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                    isinstance(n, ast.Call) and (_call_name(n) or "").startswith("assert_client_access") for n in ast.walk(fn)):
                handlers += 1
    assert handlers >= 400, f"only {handlers} handlers assert a client: the population moved"
    assert len(REVIEWED) >= 20


# ── negative controls: the rule fires on the old shape and on nothing it should leave alone ───────────────────────────────────
def _fires(source: str) -> bool:
    return bool(handlers_that_fire(source, "<src>", {"gstr9c_expense_lines"}, {}))


OLD = '''
@router.delete("/lines/{line_id}")
def delete_line(line_id: str, client_id: str, current_user=Depends(rbac("gst", "compute"))):
    assert_client_access(current_user, client_id)
    db.table("gstr9c_expense_lines").update({"deleted_at": now}).eq("id", line_id).eq("firm_id", current_user["firm_id"]).execute()
'''


def test_negative_control_the_old_shape_fires():
    assert _fires(OLD)


def test_negative_control_a_client_filter_on_the_write_is_enough():
    assert not _fires(OLD.replace('.eq("firm_id", current_user["firm_id"])', '.eq("firm_id", current_user["firm_id"]).eq("client_id", client_id)'))


def test_negative_control_asserting_on_the_rows_own_client_is_enough():
    tied = OLD.replace("    assert_client_access(current_user, client_id)\n",
                       '    row = find(line_id)\n    assert_client_access(current_user, row["client_id"])\n')
    assert not _fires(tied)


def test_negative_control_comparing_the_rows_client_is_enough():
    tied = OLD.replace("    assert_client_access(current_user, client_id)\n",
                       '    assert_client_access(current_user, client_id)\n    row = find(line_id)\n    if row["client_id"] != client_id:\n        raise HTTPException(404)\n')
    assert not _fires(tied)


def test_negative_control_a_read_is_not_a_write():
    assert not _fires(OLD.replace(".update({\"deleted_at\": now})", ".select('id')"))


def test_negative_control_a_table_without_a_client_is_not_asked():
    assert not handlers_that_fire(OLD, "<src>", {"some_other_table"}, {})


def test_negative_control_the_write_in_a_service_is_followed():
    service = ('def withdraw(db, firm_id, line_id):\n'
               '    db.table("gstr9c_expense_lines").update({"deleted_at": now}).eq("id", line_id).eq("firm_id", firm_id).execute()\n')
    handler = ('@router.delete("/lines/{line_id}")\n'
               'def delete_line(line_id: str, client_id: str, current_user=Depends(rbac("gst", "compute"))):\n'
               '    assert_client_access(current_user, client_id)\n'
               '    svc.withdraw(db, current_user["firm_id"], line_id)\n')
    index = {"withdraw": [("services/x.py", ast.parse(service).body[0])]}
    assert handlers_that_fire(handler, "<src>", {"gstr9c_expense_lines"}, index)
