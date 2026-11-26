"""A function that writes a receipt's or a payment's allocation rows says what is left of the document in the same function (POST-A-369, part 2).

THE DECISION THIS HOLDS
    `receipts.unallocated_paise` and `purchase_payments.unallocated_paise` are NOT derived by the database, and that was decided on
    16-11-2026 rather than left to chance. Migration 571 derives the receipt's ALLOCATED total because it is the sum of rows and nothing
    else. What is LEFT of a document is a different kind of figure:
      * it is `settlement - allocated`, and the settlement is a rule about the document, not a fact in its rows: cash plus the tax the
        customer withheld for a rupee receipt, and for a foreign-currency one the foreign amount settled, translated once at the receipt's
        rate and rounded in the currency's minor units, which is not `amount - the rupees the allocations relieved` (the exchange
        difference goes to its own account). The second cannot be written in SQL without copying `to_base_minor`, and a rule that exists in
        two languages is the thing the posting-kernel rule exists to prevent;
      * a single-bill vendor payment has NO allocation rows at all and writes `0` (it discharged its bill) or the whole amount (it did
        not), so a figure derived from the rows would call every one of them an advance (`domain/reporting/party_advances.py`);
      * a reversal voids the rows and leaves the figure, and every reader drops a reversed document, but the GST advance report reads the
        figure without looking at `is_reversed`: a derived figure would turn each reversed receipt into an advance received and not adjusted.
    The readers already put the derivation beside the stored figure as a CROSS-CHECK and name a disagreement (`gaps`), so a drift is
    shown, not absorbed. Nothing signed in can write the rows (the signed-in role holds no INSERT, UPDATE or DELETE on either allocation
    table), so the only writers are the server's own code, which this test holds.

WHAT IS HELD
    Every function of the API that INSERTS or DELETES rows of `receipt_allocations` or `purchase_payment_allocations` also states
    `unallocated_paise` (as a key or a keyword) in the same function, which is where the row and the figure about what is left of the
    document are written together. A function that only VOIDS rows (`{"is_voided": True}`, the reversals) is named below with its reason.
    The list is an equality in both directions: a new writer that says nothing fails, and an entry whose function no longer writes
    rows or now states the figure fails until it is deleted.

WHAT IT DOES NOT SEE
    Whether the figure is the RIGHT one (the cross-check on the screens and `test_571_..._pg.py` hold that for the receipt), a writer
    reached through a name the scan cannot resolve, and a database function (`settle_receipt_atomic` inserts the receipt with its
    figure, which `test_every_key_the_receipt_payload_sends_is_stored_by_the_function_that_records_it.py` holds).
"""
from __future__ import annotations

import ast
from pathlib import Path

from tests._call_graph import chain_of

API = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("routers", "services", "domain", "repositories", "jobs", "core")

#: allocation table -> the header whose `unallocated_paise` it feeds.
ALLOCATION_TABLES = {"receipt_allocations": "receipts", "purchase_payment_allocations": "purchase_payments"}

#: (module path, function) -> why it writes allocation rows and need not state what is left. Each only VOIDS rows.
VOIDS_ONLY: dict[tuple[str, str], str] = {
    ("services/reversal_service.py", "reverse_receipt"):
        "voids the receipt's allocation rows and marks the receipt reversed; the figure is left as it was and every reader drops a reversed receipt",
    ("services/reversal_service.py", "reverse_payment"):
        "voids the payment's allocation rows and marks the payment reversed; the figure is left as it was and every reader drops a reversed payment",
}


def _payload_keys(call: ast.Call) -> set[str]:
    return {k.value for a in call.args for d in ast.walk(a) if isinstance(d, ast.Dict) for k in d.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)}


def writers(source: str) -> dict[str, dict]:
    """function name -> {"ops": {(table, op)}, "voids_only": bool, "says_what_is_left": bool} for every function that writes allocation rows.

    The function is the OUTERMOST def the write sits in, so a helper nested inside a function that states the figure is that function's."""
    tree = ast.parse(source)
    outer: dict[ast.AST, ast.AST] = {}

    def visit(node, top):
        for child in ast.iter_child_nodes(node):
            here = top or (child if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else None)
            outer[child] = here
            visit(child, here)
    visit(tree, None)

    found: dict[str, dict] = {}
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        chain = chain_of(call)
        tables = [c.args[0].value for name, c in chain if name == "table" and c.args and isinstance(c.args[0], ast.Constant)]
        if not tables or tables[0] not in ALLOCATION_TABLES or chain[0][0] not in ("insert", "delete", "update", "upsert"):
            continue
        fn = outer.get(call)
        if fn is None:
            continue
        slot = found.setdefault(fn.name, {"ops": set(), "voids_only": True, "says_what_is_left": False, "node": fn})
        op = chain[0][0]
        slot["ops"].add((tables[0], op))
        if not (op == "update" and _payload_keys(call) == {"is_voided"}):
            slot["voids_only"] = False
    for slot in found.values():
        fn = slot.pop("node")
        slot["says_what_is_left"] = any(
            (isinstance(n, ast.Dict) and any(isinstance(k, ast.Constant) and k.value == "unallocated_paise" for k in n.keys))
            or (isinstance(n, ast.keyword) and n.arg == "unallocated_paise")
            or (isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) and n.slice.value == "unallocated_paise")
            for n in ast.walk(fn))
    return found


def census(root: Path = API) -> dict[tuple[str, str], dict]:
    out = {}
    for d in SCAN_DIRS:
        for path in sorted((root / d).rglob("*.py")):
            for name, slot in writers(path.read_text(encoding="utf-8")).items():
                out[(path.relative_to(root).as_posix(), name)] = slot
    return out


def test_every_writer_of_allocation_rows_says_what_is_left_of_the_document_or_only_voids():
    found = census()
    silent = sorted(k for k, s in found.items() if not s["says_what_is_left"] and not (s["voids_only"] and k in VOIDS_ONLY))
    assert not silent, (
        "these functions write allocation rows and never state `unallocated_paise`, so the figure about what is left of the receipt or "
        "payment is not written with them (the shape migration 571 fixed for the allocated total: a comment said the application "
        f"maintained it and no code did). State it beside the rows, or, if the function only voids rows, name it in VOIDS_ONLY: {silent}")
    stale = sorted(k for k in VOIDS_ONLY if k not in found or not found[k]["voids_only"] or found[k]["says_what_is_left"])
    assert not stale, f"these no longer only void allocation rows; delete them from VOIDS_ONLY: {stale}"


def test_the_scan_sees_the_writers_it_was_written_for():
    """Not vacuous: the six functions that create or rewrite allocation rows, and the two reversals, are all found."""
    found = census()
    expected = {
        ("routers/receipts.py", "update_allocations"), ("services/receipt_service.py", "create_receipt_core"),
        ("services/receipt_service.py", "create_foreign_receipt"), ("services/purchase_payment_service.py", "create_payment_core"),
        ("services/purchase_payment_service.py", "create_foreign_payment_core"),
        ("services/purchase_payment_service.py", "update_allocations_core"), *VOIDS_ONLY,
    }
    assert expected <= set(found), sorted(expected - set(found))
    assert all(found[k]["says_what_is_left"] for k in expected - set(VOIDS_ONLY))
    assert all(found[k]["voids_only"] for k in VOIDS_ONLY)


_STATES_IT = """
def create(db, rid, rows):
    db.table("receipt_allocations").insert(rows).execute()
    db.table("receipts").update({"unallocated_paise": 0}).eq("id", rid).execute()
"""
_SILENT = """
def create(db, rid, rows):
    db.table("receipt_allocations").insert(rows).execute()
"""
_SILENT_DELETE = """
def clear(db, rid):
    db.table("purchase_payment_allocations").delete().eq("purchase_payment_id", rid).execute()
"""
_VOID = """
def reverse(db, rid):
    db.table("receipt_allocations").update({"is_voided": True}).eq("receipt_id", rid).execute()
"""
_REWRITE = """
def rewrite(db, rid):
    db.table("receipt_allocations").update({"allocated_paise": 5}).eq("receipt_id", rid).execute()
"""
_NESTED = """
def create(db, rid, rows):
    def put():
        db.table("receipt_allocations").insert(rows).execute()
    put()
    db.table("receipts").update(dict(unallocated_paise=0)).eq("id", rid).execute()
"""


def test_the_scan_tells_a_writer_that_states_the_figure_from_one_that_does_not():
    assert writers(_STATES_IT)["create"]["says_what_is_left"] is True
    assert writers(_SILENT)["create"]["says_what_is_left"] is False
    assert writers(_SILENT_DELETE)["clear"]["says_what_is_left"] is False
    assert writers(_NESTED)["create"]["says_what_is_left"] is True                 # a helper nested in the function is the function's


def test_a_void_is_not_a_rewrite():
    assert writers(_VOID)["reverse"]["voids_only"] is True
    assert writers(_REWRITE)["rewrite"]["voids_only"] is False and writers(_REWRITE)["rewrite"]["says_what_is_left"] is False
    assert writers("def f(db):\n    db.table('receipts').insert({'unallocated_paise': 1}).execute()\n") == {}
