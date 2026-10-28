"""A route that asserts the client the caller named does not READ a client-owned row by its id with the firm alone (POST-A-352).

THE SHAPE
    The write rule of POST-A-337 (`test_a_route_that_asserts_a_client_does_not_write_a_row_by_the_firm_alone.py`) closed every update and
    delete of a client-owned row by id and firm with no client filter. A READ of that shape is information and not tampering, so it
    was left. It is not harmless: a read that feeds a FIGURE (a return, a reclaim, a balance) takes another client's row into this
    client's answer, and a read that feeds a screen shows an assigned person a client they are not assigned to. This is the rule that
    states the shape for reads, built on the same population and the same scan.

WHAT IT COUNTS AS TIED (a read is not asked about when any step on the way to it does one of these)
    * a function on the path compares a row's own `client_id` to something, or asserts access on a client taken from a row (the write
      rule's own test);
    * a function on the path calls a helper whose name says it ties a row to the client (`..._of_client`, `..._of_the_client`,
      `..._is_the_clients`, `..._are_the_clients`): `named_row_ownership`, `order_of_client`, `receipt_of_client` and their kin;
    * the read itself filters on `client_id`.
    A tie ANYWHERE on the path from the handler to the read ties it. The write rule asked only the handler, which is why its first
    run flagged readers whose caller had compared the client; here the path is followed.

WHAT IS LEFT ON THE REVIEWED LIST, AND WHY IT IS NOT A FINDING
    Nineteen handlers read a row whose id was not typed by the caller but TAKEN FROM A ROW OF THIS CLIENT: a customer or vendor id on
    this client's own invoice or bill, a parent invoice id on this client's own note, an employee id on this client's own payroll row.
    The foreign keys and the ownership checks at the doors (POST-A-246, POST-A-338, POST-A-350) are what keep that id this client's, so
    the lookup is a join and not a request. They are listed, with the reason, so that a new reader of that shape is a decision and a
    reader of a caller-supplied id is not. The list only shrinks.
    The first run found ONE real gap, now fixed: `itc_register_service.record_reclaim` read the reversal a reclaim releases by id and
    firm, so a reclaim could be registered against another client's reversal.
"""
from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
_w = importlib.import_module("test_a_route_that_asserts_a_client_does_not_write_a_row_by_the_firm_alone")
_call_name, _chain, _literal = _w._call_name, _w._chain, _w._literal
ties_a_row_to_its_client, client_tables, _function_index = _w.ties_a_row_to_its_client, _w.client_tables, _w._function_index
ROUTERS, DEPTH = _w.ROUTERS, _w.DEPTH

TIE_HELPER_SUFFIXES = ("_of_client", "_of_the_client", "_is_the_clients", "_are_the_clients")

#: (router file, handler): why the read is a join on an id that came from a row of this client. Delete the entry when the handler is
#: fixed or its read is tied (the second test fails on a stale entry); a new handler that fires is fixed, or added here with its reason.
_FROM_THIS_CLIENTS_OWN_DOCUMENTS = "the ids are read from this client's own invoices, bills and notes, not typed by the caller"
REVIEWED: dict[tuple[str, str], str] = {
    ("banking.py", "worth_a_look"): "the documents are the ones this client's own bank lines were matched to",
    ("gst.py", "gstr1_from_books_endpoint"): _FROM_THIS_CLIENTS_OWN_DOCUMENTS + " (customer and parent-invoice lookups of the return build)",
    ("gst.py", "gstr1_with_amendments_endpoint"): _FROM_THIS_CLIENTS_OWN_DOCUMENTS,
    ("gst.py", "gstr3b_from_books_endpoint"): _FROM_THIS_CLIENTS_OWN_DOCUMENTS,
    ("gst_workspace.py", "compute_cmp08"): _FROM_THIS_CLIENTS_OWN_DOCUMENTS,
    ("gst_workspace.py", "compute_iff"): _FROM_THIS_CLIENTS_OWN_DOCUMENTS,
    ("gst_workspace.py", "gstr1_advances"): "the customers are the ones on this client's own receipts",
    ("gst_workspace.py", "gstr1_exception_report"): _FROM_THIS_CLIENTS_OWN_DOCUMENTS,
    ("gst_workspace.py", "upload_gstr2b"): "the vendors are the ones on this client's own bills",
    ("itr_workspace.py", "create_filing"): "reads back the filing this request has just created, by the id it just got",
    ("purchase_bills.py", "delete_landed_cost"): "the bill is the one the router tied to the client and the charge is matched on it (`bill_id` is part of the chain)",
    ("rcm_documents.py", "issue_document"): "the vendor id is read from the bill or the payment the route tied to the client",
    ("rcm_documents.py", "preview_payment_voucher"): "the vendor id is read from the bill or the payment the route tied to the client",
    ("rcm_documents.py", "preview_self_invoice"): "the vendor id is read from the bill or the payment the route tied to the client",
    ("reports.py", "gst_summary"): _FROM_THIS_CLIENTS_OWN_DOCUMENTS,
    ("tds.py", "compute_24q_from_books"): "the employees are the ones on this client's own payroll rows",
    ("tds.py", "compute_26q_from_books"): "the vendors are the ones on this client's own deductions and bills",
    ("tds.py", "compute_27q_from_books"): "the vendors are the ones on this client's own deductions and bills",
    ("post_dated_cheques.py", "convert_cheque"): "the vendor id is read from the cheque, which `_get` read by firm, client and id; the payment core then repeats the lookup",
}


def _tie_helper_called(fn: ast.AST) -> bool:
    return any(isinstance(n, ast.Call) and (_call_name(n) or "").endswith(TIE_HELPER_SUFFIXES) for n in ast.walk(fn))


def is_tied(fn: ast.AST) -> bool:
    return ties_a_row_to_its_client(fn) or _tie_helper_called(fn)


def untied_reads(fn: ast.AST, tables: set[str]) -> list[tuple[str, int]]:
    """(table, line) of every read by id and firm with no client filter, in this function alone."""
    inner = {id(n.func.value) for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Call)}
    found = []
    for n in ast.walk(fn):
        if not isinstance(n, ast.Call) or id(n) in inner or not isinstance(n.func, ast.Attribute):
            continue
        chain = _chain(n)
        methods = [m for m, _ in chain]
        if not ({"select", "maybe_single", "single"} & set(methods)) or {"update", "delete", "upsert", "insert"} & set(methods):
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


def _reach(fn, index, tables, tied, depth=DEPTH + 1, seen=None) -> list[tuple[str, str, int]]:
    seen = seen if seen is not None else set()
    found: list[tuple[str, str, int]] = []
    if depth == 0:
        return found
    for n in ast.walk(fn):
        if not isinstance(n, ast.Call):
            continue
        name = _call_name(n)
        if name in index and len(index[name]) == 1:
            path, callee = index[name][0]
            if (path, name) in seen:
                continue
            seen.add((path, name))
            callee_tied = tied or is_tied(callee)
            if not callee_tied:
                found += [(f"{path}:{name}", t, ln) for t, ln in untied_reads(callee, tables)]
            found += _reach(callee, index, tables, callee_tied, depth - 1, seen)
    return found


def handlers_that_fire(source: str, filename: str, tables: set[str], index) -> list[tuple[str, str]]:
    out = []
    for fn in ast.walk(ast.parse(source, filename)):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        decorated = any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and getattr(d.func.value, "id", "") == "router"
                        for d in fn.decorator_list)
        asserts = any(isinstance(n, ast.Call) and (_call_name(n) or "").startswith("assert_client_access") for n in ast.walk(fn))
        if not (decorated and asserts):
            continue
        tied = is_tied(fn)
        if not tied:
            out += [(fn.name, f"{t} (line {ln})") for t, ln in untied_reads(fn, tables)]
        out += [(fn.name, f"{where} -> {t} (line {ln})") for where, t, ln in _reach(fn, index, tables, tied)]
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
def test_no_handler_reads_a_client_owned_row_by_the_firm_alone_unless_it_is_reviewed(world):
    unreviewed = sorted(_fired(world) - set(REVIEWED))
    assert not unreviewed, (
        "a handler asserts the client the caller named and then reads a row of a client-owned table by id with the firm alone, so a "
        "row of ANOTHER client of the firm can reach this client's answer. Add `.eq('client_id', client_id)` to the read, or tie the "
        "row first with a `..._of_client` helper (`services/named_row_ownership` has them for customers, vendors, bills, invoices and "
        "bank accounts). If the id was taken from a row of this client and not typed by the caller, add the handler to REVIEWED with "
        "that reason. " + ", ".join(f"{f}::{h}" for f, h in unreviewed))


def test_every_reviewed_entry_still_fires_so_the_list_can_only_shrink(world):
    stale = sorted(set(REVIEWED) - _fired(world))
    assert not stale, f"these entries no longer fire (the handler was fixed or removed): delete them from REVIEWED: {stale}"


def test_the_scan_is_not_vacuous(world):
    tables, index = world
    assert len(tables) >= 200 and len(index) >= 500
    assert len(REVIEWED) >= 15 and len(_fired(world)) >= 15, "the scan stopped seeing the reads it exists for"


# ── negative controls: the rule fires on the shape and on nothing it should leave alone ─────────────────────────────────────
TABLES = {"purchase_orders"}
HANDLER = '''
@router.get("/orders/{order_id}")
def get_order(order_id: str, client_id: str, current_user=Depends(rbac("accounting", "read"))):
    assert_client_access(current_user, client_id)
    return svc.order(db, current_user["firm_id"], order_id)
'''
SERVICE = 'def order(db, firm_id, order_id):\n    return db.table("purchase_orders").select("id").eq("firm_id", firm_id).eq("id", order_id).limit(1).execute().data\n'


def _fires(handler: str = HANDLER, service: str = SERVICE) -> bool:
    index = {"order": [("services/x.py", ast.parse(service).body[0])]}
    return bool(handlers_that_fire(handler, "<src>", TABLES, index))


def test_negative_control_the_shape_fires():
    assert _fires()


def test_negative_control_a_client_filter_on_the_read_is_enough():
    assert not _fires(service=SERVICE.replace('.eq("id", order_id)', '.eq("id", order_id).eq("client_id", client_id)'))


def test_negative_control_a_tie_helper_on_the_handler_is_enough():
    assert not _fires(HANDLER.replace("    return svc", "    order_of_client(db, current_user['firm_id'], order_id, client_id)\n    return svc"))


def test_negative_control_a_compare_in_the_service_ties_the_read_below_it():
    """The write rule asked only the handler; here a tie anywhere on the path counts."""
    tied = ('def order(db, firm_id, order_id):\n    row = _row(db, firm_id, order_id)\n    if row["client_id"] != order_id:\n        raise X\n'
            '    return row\n')
    index = {"order": [("services/x.py", ast.parse(tied).body[0])], "_row": [("services/x.py", ast.parse(SERVICE.replace("def order", "def _row")).body[0])]}
    assert not handlers_that_fire(HANDLER, "<src>", TABLES, index)


def test_negative_control_a_write_is_not_a_read():
    assert not _fires(service=SERVICE.replace(".select(\"id\")", ".update({\"a\": 1})"))


def test_negative_control_a_table_without_a_client_is_not_asked():
    index = {"order": [("services/x.py", ast.parse(SERVICE).body[0])]}
    assert not handlers_that_fire(HANDLER, "<src>", {"some_other_table"}, index)
