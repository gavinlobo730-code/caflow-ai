"""A request that names a row of a client-owned table asks whose it is, found from the request models and not from a list (POST-A-350).

WHAT WAS WRONG
    POST-A-338 closed the doors it knew of, and the independent review of that change found five it had not named: a hand-written list of
    doors ends that way. `test_a_document_names_only_rows_of_its_own_client.py` keeps the doors it lists honest and cannot find a new one.
    Run over the request models this rule found eleven more, and each was a real hole: a recurring invoice or purchase-bill template
    naming another client's customer or vendor (every run then invoices or bills that party under the wrong client), an e-way bill naming
    another client's invoice (it is listed on that invoice's own hub), a receipt or a vendor payment naming another client's bank account
    (the posting reads the account by firm alone and the ledger trigger refused it later, as a 500), and the linked bill or invoice of the
    four note kinds, which was stored as sent and refused only when the note was issued.

WHAT IS ASSERTED
    * THE RULE. Every POST, PUT, PATCH or DELETE route takes a request model with a field that names a row of a client-owned table
      (`*vendor_id`, `*customer_id`, `*purchase_bill_id`, `*sales_invoice_id`, `*bank_account_id`, `*order_id`, `*quotation_id`). For each
      such field the route, or something it calls up to five calls down (imports and methods followed), must ask whose that row is: a
      `*_is_the_clients` function, the purchase and sales cycles' own `order_of_client` / `row_of_client`, the bank reconciliation's
      `_validate_bank_account`, a read of the named table filtered by `client_id`, or a read that is compared with the client's id. A door
      that does none is listed below with the reason it is safe, and that list only shrinks: an entry whose door has since been checked is
      a failure that says to delete it.
    * WHAT THE SECOND READING ADDED (POST-A-353). The names are wider (`original_invoice_id`, `linked_bill_id` and a bare `invoice_id` or
      `bill_id` are rows of the same tables), a model that CARRIES another model (a receipt's allocations, a payment's bills) names that
      model's rows too, a QUERY or FORM parameter that names a row counts like a body field (a path parameter does not: it is the row the
      route is about), and a body taken as a plain dict is its own kind, `dict_body`, because the AST cannot know its keys, so every such
      door is on the reviewed list with what the dict carries. The first run of it found one real gap, the statement inspector, which
      looked a saved column layout up by a bank account id and the firm alone: another client's account answered with that client's
      layout. It asks whose the account is now, before it reads the file.
    * THE SECOND FAMILY (POST-A-353, the stored-file half). Seven more kinds: a stored file (`*document_id`), a ledger entry
      (`*journal_entry_id`), a payroll employee, a vendor payment and the three stock places (godown, batch, cost centre). The run found
      three real doors that stored another client's row under this one: the 26AS upload named any client's stored file, and the ITR
      workspace's deduction claim and disallowance named any client's evidence file (the disallowance also any client's ledger entry).
      The payroll, stock and ledger doors the survey listed were already asked, by helpers the rule now knows by name.
    * THE SCAN IS NOT BLIND. It finds more than forty doors and all seven kinds, it flags a synthetic route that writes without asking, it
      accepts one that asks in the route and one that asks two calls down, and it flags one whose check sits in a function nothing calls.
    * EACH DOOR THE RULE FOUND. A sibling client's row named under this client is answered in the words a missing row gets and nothing is
      written, and the same request with the client's own row is not stopped by the question (the control: the refusal is the client).
"""
from __future__ import annotations

import ast
import re
import textwrap
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.credit_notes as credit_notes_router
import routers.debit_notes as debit_notes_router
import routers.eway_bill as eway_router
import routers.form_26as as form26as_router
import routers.itr_workspace as itr_router
import routers.purchase_credit_notes as pcn_router
import routers.purchase_payments as pp_router
import routers.receipts as receipts_router
import routers.recurring_invoices as ri_router
import routers.recurring_purchase_bills as rpb_router
import routers.sales_debit_notes as sdn_router
import routers.sales_invoices as sales_router
import services.recurring_invoice_service as ri_service
import services.recurring_purchase_bill_service as rpb_service
from core.auth import get_current_user
from tests._call_graph import CallGraph, called_name, chain_of
from tests.e2e_harness import FakeDB, wire_e2e

API = Path(__file__).resolve().parent.parent

# field name -> (kind, functions that ask, tables whose client-filtered read counts)
KINDS: dict[str, tuple[re.Pattern, set[str], set[str]]] = {
    "vendor": (re.compile(r"(^|_)vendor_id$"), {"vendor_is_the_clients"}, {"vendors"}),
    "customer": (re.compile(r"(^|_)customer_id$"), {"customer_is_the_clients"}, {"customers"}),
    "bill": (re.compile(r"(^|_)(purchase_)?bill_id$"), {"purchase_bill_is_the_clients"}, {"purchase_bills"}),
    "invoice": (re.compile(r"(^|_)(sales_)?invoice_id$"), {"sales_invoice_is_the_clients"}, {"client_sales_invoices"}),
    "bank": (re.compile(r"(^|_)bank_account_id$"), {"bank_account_is_the_clients", "_validate_bank_account"}, {"bank_accounts"}),
    "order": (re.compile(r"(^|_)order_id$"), {"order_of_client", "row_of_client"}, {"purchase_orders", "sales_orders"}),
    "quotation": (re.compile(r"(^|_)quotation_id$"), {"row_of_client"}, {"sales_quotations"}),
    # THE SECOND FAMILY (POST-A-353): a stored file, a ledger entry, a payroll employee and the three stock places.
    "document": (re.compile(r"(^|_)document_id$"), {"client_document_is_the_clients", "_assert_document_in_firm"}, {"client_documents"}),
    "journal": (re.compile(r"(^|_)journal_entry_id$"), {"journal_entry_is_the_clients"}, {"journal_entries"}),
    "employee": (re.compile(r"(^|_)employee_id$"), {"_employee_of_client"}, {"payroll_employees"}),
    "vendor_payment": (re.compile(r"(^|_)purchase_payment_id$"), set(), {"purchase_payments"}),
    "godown": (re.compile(r"(^|_)godown_id$"), set(), {"godowns"}),
    "batch": (re.compile(r"(^|_)batch_id$"), set(), {"inventory_batches"}),
    "cost_centre": (re.compile(r"(^|_)cost_centre_id$"), set(), {"cost_centres"}),
}
DICT_BODY = re.compile(r"(Optional\[)?(dict|Dict)(\[[^\]]*\])?\]?")
SCAN_DIRS = ("services", "domain", "repositories", "routers", "models", "core")      # not jobs: nothing a route calls lives there
WRITING_VERBS = ("post", "put", "patch", "delete")
DEPTH = 5

# A door the rule flags that is safe, and why. Shrink-only: each key must still be flagged.
REVIEWED: dict[tuple[str, str, str], str] = {
    ("purchase_bills", "probe_near_duplicates", "vendor"):
        "a read-only probe (POST only because an invoice number does not belong in a URL): it lists the bills of THIS client that carry the "
        "vendor id, so a vendor of another client matches no bill of this one and the answer is the empty list a missing vendor gets.",
    # THE SHAPES THE FIRST RULE COULD NOT SEE (POST-A-353). A body taken as a plain dict is the kind "dict_body": the AST cannot know its
    # keys, so every such door is listed with what the dict carries, and a new one is a red test.
    ("fx_revaluation", "preview_revaluation", "dict_body"):
        "the payload is a period end and a map of currency to closing rate and names no row of any table; the client is a query "
        "parameter that the route asserts for the caller with assert_client_access before it reads anything. It writes nothing.",
    ("fx_revaluation", "run_revaluation", "dict_body"):
        "the payload is a period end and a map of currency to closing rate and names no row of any table; the client is a query "
        "parameter that the route asserts for the caller with assert_client_access before the revaluation is planned or posted.",
    ("memory_intelligence", "update_anomaly_status", "dict_body"):
        "the body carries a status word and nothing else; the row it acts on is the anomaly in the path, and the route reads that "
        "anomaly and asks the caller's access to its client (_assert_anomaly_scope) before the update, answering a missing one's words.",
    ("workflow_builder", "manually_trigger", "dict_body"):
        "the payload's client_id is asserted for the caller before the run starts and the run is created for that client; the other keys "
        "are the trigger's data, compared with the template's conditions and stored on the run. The one step that reads a client takes the "
        "instance's asserted client before the payload's, and checks it belongs to the firm.",
    # THE SECOND FAMILY (POST-A-353).
    ("banking", "remove_transaction_attachment", "document"):
        "the id only selects an entry to take out of the attachment list of THIS bank line (a comparison in domain/banking/attachments), and "
        "no row is written that names the document; adding an attachment, which does name one, asks the document under the line's client.",
    ("payroll", "put_leave_balance", "employee"):
        "the body names no client at all; the employee is resolved by the firm and the caller's assignment to the employee's OWN client is "
        "asked (_assert_employee_scope) before anything is read or written, a stranger answering in the words a missing employee gets.",
    # A NAMED ROW THE REQUEST CARRIES OUTSIDE THE BODY MODEL.
    ("payments", "create_payment_link", "invoice"):
        "the request names no client; the service reads the invoice by firm and asks can_access_client of the invoice's OWN client before "
        "anything is created, so an invoice of a client outside the caller's reach answers as a missing invoice.",
    ("purchase_bills", "preview_purchase_bill_tds", "bill"):
        "the id only drops one row from the list of THIS vendor's bills that the year's aggregate is summed over (a comparison of ids in "
        "services/vendor_tds), so a bill of another client matches nothing in it; the preview computes and writes nothing.",
}


# ── the scanner ────────────────────────────────────────────────────────────────────────────────────────────────────────────
class _Tree(CallGraph):
    """The shared call graph, plus the request models that carry a named field and what a function asks."""

    def __init__(self, root: Path):
        super().__init__(root, SCAN_DIRS)
        self.models = self._models_with_named_fields()

    def _models_with_named_fields(self) -> dict[str, dict[str, set[str]]]:
        found: dict[str, dict[str, set[str]]] = {}
        annotated: dict[str, list[tuple[str, str]]] = {}
        for mod, tree in self.mods.items():
            if not (mod.startswith("models.") or mod.startswith("routers.")):
                continue
            for c in ast.walk(tree):
                if isinstance(c, ast.ClassDef):
                    for n in c.body:
                        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                            annotated.setdefault(c.name, []).append((n.target.id, ast.unparse(n.annotation)))
                            for kind, (rx, _, _) in KINDS.items():
                                if rx.search(n.target.id):
                                    found.setdefault(c.name, {}).setdefault(kind, set()).add(n.target.id)
        # A model that CARRIES another model (a receipt's allocations, a payment's bills) names that model's rows too: the route
        # takes the outer model, so the scan has to read through it. Followed to a fixed point, so a list of lists is read.
        grew = True
        while grew:
            grew = False
            for outer, fields in annotated.items():
                for field, annotation in fields:
                    for inner, by_kind in list(found.items()):
                        if inner == outer or not re.search(rf"\b{inner}\b", annotation):
                            continue
                        for kind, names in by_kind.items():
                            have = found.setdefault(outer, {}).setdefault(kind, set())
                            for name in names:
                                if f"{field}.{name}" not in have:
                                    have.add(f"{field}.{name}")
                                    grew = True
        return found

    @staticmethod
    def _tables(fn) -> set[str]:
        return {c.args[0].value for c in ast.walk(fn)
                if isinstance(c, ast.Call) and called_name(c) == "table" and c.args and isinstance(c.args[0], ast.Constant)}

    @staticmethod
    def _compares_a_clients_id(fn) -> bool:
        for n in ast.walk(fn):
            if isinstance(n, ast.Compare):
                dumped = ast.dump(n)
                if "client_id" in dumped and ("Subscript" in dumped or "'get'" in dumped):
                    return True
        return False

    def _own_kinds(self, fn) -> set[str]:
        asked: set[str] = set()
        for c in ast.walk(fn):
            if not isinstance(c, ast.Call):
                continue
            name = called_name(c) or ""
            for kind, (_, asking, _) in KINDS.items():
                if name in asking:
                    asked.add(kind)
            table, filtered = None, False
            for method, link in chain_of(c):
                if method == "table" and link.args and isinstance(link.args[0], ast.Constant):
                    table = link.args[0].value
                if method in ("eq", "in_") and link.args and isinstance(link.args[0], ast.Constant) and link.args[0].value == "client_id":
                    filtered = True
            if filtered:
                for kind, (_, _, tables) in KINDS.items():
                    if table in tables:
                        asked.add(kind)
        return asked

    def asks(self, key: tuple[str, str], depth: int = DEPTH, seen: frozenset = frozenset()) -> set[str]:
        fn = self.funcs[key]
        asked = self._own_kinds(fn)
        callees = [t for _call, targets in self.calls_of(key) for t in targets]
        if self._compares_a_clients_id(fn):
            tables = set(self._tables(fn))
            for k in callees:
                tables |= self._tables(self.funcs[k])
            for kind, (_, _, kind_tables) in KINDS.items():
                if tables & kind_tables:
                    asked.add(kind)
        if depth > 0:
            for k in callees:
                if k not in seen:
                    asked |= self.asks(k, depth - 1, seen | {k})
        return asked


def doors(root: Path) -> list[tuple[str, str, set[str], set[str]]]:
    """(router, handler, kinds the request names, kinds nothing reached asks) for every writing route whose request names a row."""
    tree = _Tree(root)
    found = []
    for mod, module in sorted(tree.mods.items()):
        if not mod.startswith("routers."):
            continue
        for fn in ast.walk(module):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            verbs = [d.func.attr for d in fn.decorator_list
                     if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and getattr(d.func.value, "id", "") == "router"]
            if not verbs or verbs[0] not in WRITING_VERBS:
                continue
            named: dict[str, set[str]] = {}
            route_path = next((d.args[0].value for d in fn.decorator_list
                               if isinstance(d, ast.Call) and d.args and isinstance(d.args[0], ast.Constant)), "")
            defaults = dict(zip(reversed(fn.args.args), reversed(fn.args.defaults), strict=False))      # defaults are the TAIL of the arguments
            defaults.update({a: d for a, d in zip(fn.args.kwonlyargs, fn.args.kw_defaults, strict=True) if d is not None})
            for arg in fn.args.args + fn.args.kwonlyargs:
                if "Depends" in ast.unparse(defaults[arg]) if arg in defaults else False:
                    continue                                    # the caller's own identity, not something the caller named
                annotation = ast.unparse(arg.annotation) if arg.annotation else ""
                for model, by_kind in tree.models.items():
                    if re.search(rf"\b{model}\b", annotation):
                        for kind, fields in by_kind.items():
                            named.setdefault(kind, set()).update(fields)
                if "{" + arg.arg + "}" in route_path:
                    continue                                    # a path parameter is the row the route is about, not a second row it names
                for kind, (rx, _, _) in KINDS.items():
                    if rx.search(arg.arg):                      # a query or form parameter that names a row (the body is not the only door)
                        named.setdefault(kind, set()).add(arg.arg)
                if DICT_BODY.fullmatch(annotation):             # a body taken as a plain dict: the AST cannot know its keys
                    named.setdefault("dict_body", set()).add(arg.arg)
            if not named or (mod, fn.name) not in tree.funcs:
                continue
            found.append((mod.split(".")[-1], fn.name, set(named), set(named) - tree.asks((mod, fn.name))))
    return found


@pytest.fixture(scope="module")
def real():
    return doors(API)


# ── the rule ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_every_route_that_names_a_row_asks_whose_it_is_or_says_why_not(real):
    unasked = {(r, h, k) for r, h, _named, missing in real for k in missing}
    new = sorted(unasked - set(REVIEWED))
    assert not new, (
        "these routes take a request that names a row of a client-owned table and nothing they call asks whether the row is the client's. "
        "Call the matching function in services/named_row_ownership before the first write (it answers 404 in the words a missing row "
        "gets), or add the route to REVIEWED with the reason it is safe:\n  " + "\n  ".join(map(str, new)))


def test_a_reviewed_door_is_still_unasked_and_still_gives_its_reason(real):
    unasked = {(r, h, k) for r, h, _named, missing in real for k in missing}
    for key, reason in REVIEWED.items():
        assert key in unasked, f"{key} is now checked (or gone): delete it from REVIEWED, the list only shrinks"
        assert len(reason) > 80, f"{key} needs a reason"


def test_the_scan_sees_the_doors_it_is_meant_to(real):
    assert len(real) >= 40, f"only {len(real)} routes found: the scan has gone blind"
    seen_kinds = set().union(*(named for _r, _h, named, _m in real)) - {"dict_body"}
    assert seen_kinds == set(KINDS), f"kinds never seen: {set(KINDS) - seen_kinds}"
    handlers = {(r, h) for r, h, _n, _m in real}
    for expected in (("receipts", "create_receipt"), ("purchase_payments", "create_purchase_payment"), ("eway_bill", "create_eway_bill"),
                     ("recurring_invoices", "create_recurring"), ("recurring_purchase_bills", "create_recurring_bill"),
                     ("debit_notes", "create_debit_note"), ("fixed_assets", "create_asset"), ("bills_of_entry", "create_bill_of_entry"),
                     ("form_26as", "create_upload"), ("itr_workspace", "create_disallowance"), ("itr_workspace", "create_deduction"),
                     ("payroll", "put_attendance"), ("inventory", "transfer_stock")):
        assert expected in handlers, f"{expected} is no longer found as a door"


# ── the scan against code written for the purpose ──────────────────────────────────────────────────────────────────────────
_MODEL = '''
from pydantic import BaseModel
class ThingIn(BaseModel):
    client_id: str
    vendor_id: str
'''


def _tree_with(tmp_path: Path, router_body: str, service_body: str = "def noop():\n    return None\n") -> Path:
    for d in ("models", "routers", "services"):
        (tmp_path / d).mkdir(exist_ok=True)
    (tmp_path / "models" / "m.py").write_text(_MODEL)
    (tmp_path / "services" / "s.py").write_text(textwrap.dedent(service_body))
    (tmp_path / "routers" / "r.py").write_text(textwrap.dedent(router_body))
    return tmp_path


_ROUTER = '''
from fastapi import APIRouter
from models.m import ThingIn
from services import s
router = APIRouter()
@router.post("/x")
def make(data: ThingIn):
{body}
'''


def _verdict(tmp_path, body: str, service: str = "def noop():\n    return None\n"):
    out = doors(_tree_with(tmp_path, _ROUTER.replace("{body}", textwrap.indent(textwrap.dedent(body), "    ")), service))
    assert len(out) == 1, out
    return out[0][3]


def test_a_route_that_writes_without_asking_is_flagged(tmp_path):
    assert _verdict(tmp_path, 'db.table("things").insert({"vendor_id": data.vendor_id}).execute()') == {"vendor"}


def test_a_route_that_asks_in_its_own_body_is_not(tmp_path):
    assert _verdict(tmp_path, '''
        named_row_ownership.vendor_is_the_clients(db, "f", data.client_id, data.vendor_id)
        db.table("things").insert({"vendor_id": data.vendor_id}).execute()''') == set()


def test_a_route_whose_service_asks_two_calls_down_is_not(tmp_path):
    service = '''
        def first(db, data):
            return second(db, data)
        def second(db, data):
            named_row_ownership.vendor_is_the_clients(db, "f", data.client_id, data.vendor_id)
    '''
    assert _verdict(tmp_path, "s.first(db, data)", service) == set()


def test_a_route_whose_service_reads_the_vendor_under_the_client_is_not(tmp_path):
    service = '''
        def first(db, data):
            return db.table("vendors").select("id").eq("id", data.vendor_id).eq("client_id", data.client_id).execute()
    '''
    assert _verdict(tmp_path, "s.first(db, data)", service) == set()


def test_a_read_that_is_compared_with_the_clients_id_counts(tmp_path):
    service = '''
        def first(db, data):
            row = db.table("vendors").select("*").eq("id", data.vendor_id).execute().data[0]
            if row["client_id"] != data.client_id:
                raise ValueError("no")
    '''
    assert _verdict(tmp_path, "s.first(db, data)", service) == set()


def test_a_check_in_a_function_nothing_calls_does_not_count(tmp_path):
    service = '''
        def first(db, data):
            db.table("things").insert({"vendor_id": data.vendor_id}).execute()
        def never_called(db, data):
            named_row_ownership.vendor_is_the_clients(db, "f", data.client_id, data.vendor_id)
    '''
    assert _verdict(tmp_path, "s.first(db, data)", service) == {"vendor"}


def test_a_read_of_the_table_by_id_alone_does_not_count(tmp_path):
    service = '''
        def first(db, data):
            return db.table("vendors").select("id").eq("id", data.vendor_id).eq("firm_id", "f").execute()
    '''
    assert _verdict(tmp_path, "s.first(db, data)", service) == {"vendor"}


def test_a_route_that_asks_about_a_different_kind_is_still_flagged(tmp_path):
    assert _verdict(tmp_path, 'named_row_ownership.customer_is_the_clients(db, "f", data.client_id, "c")') == {"vendor"}


def test_a_dict_body_is_flagged_until_it_is_reviewed(tmp_path):
    (tmp_path / "models").mkdir(); (tmp_path / "routers").mkdir(); (tmp_path / "services").mkdir()
    (tmp_path / "models" / "m.py").write_text("x = 1\n")
    (tmp_path / "services" / "s.py").write_text("def noop():\n    return None\n")
    (tmp_path / "routers" / "r.py").write_text(textwrap.dedent('''
        from typing import Any
        from fastapi import APIRouter, Depends
        router = APIRouter()
        @router.post("/x")
        def make(payload: dict, current_user: dict = Depends(lambda: {})):
            return payload
        @router.post("/y/{thing_id}")
        def other(thing_id: str, payload: dict[str, Any]):
            return payload
    '''))
    out = doors(tmp_path)
    assert sorted((h, sorted(named), sorted(missing)) for _r, h, named, missing in out) == [
        ("make", ["dict_body"], ["dict_body"]), ("other", ["dict_body"], ["dict_body"])]


def test_a_query_parameter_that_names_a_row_is_a_door_and_a_path_parameter_is_not(tmp_path):
    (tmp_path / "models").mkdir(); (tmp_path / "routers").mkdir(); (tmp_path / "services").mkdir()
    (tmp_path / "models" / "m.py").write_text("x = 1\n")
    (tmp_path / "services" / "s.py").write_text("def noop():\n    return None\n")
    (tmp_path / "routers" / "r.py").write_text(textwrap.dedent('''
        from fastapi import APIRouter, Query
        router = APIRouter()
        @router.post("/a")
        def by_query(vendor_id: str = Query(...)):
            return vendor_id
        @router.post("/b/{vendor_id}")
        def by_path(vendor_id: str):
            return vendor_id
    '''))
    assert [(h, sorted(missing)) for _r, h, _n, missing in doors(tmp_path)] == [("by_query", ["vendor"])]


def test_a_model_that_carries_another_model_names_that_models_rows(tmp_path):
    (tmp_path / "models").mkdir(); (tmp_path / "routers").mkdir(); (tmp_path / "services").mkdir()
    (tmp_path / "models" / "m.py").write_text(textwrap.dedent('''
        from pydantic import BaseModel
        class LineIn(BaseModel):
            linked_bill_id: str
        class PayIn(BaseModel):
            client_id: str
            lines: list[LineIn]
    '''))
    (tmp_path / "services" / "s.py").write_text("def noop():\n    return None\n")
    (tmp_path / "routers" / "r.py").write_text(textwrap.dedent('''
        from fastapi import APIRouter
        from models.m import PayIn
        router = APIRouter()
        @router.post("/p")
        def pay(data: PayIn):
            return data
    '''))
    assert [(h, sorted(missing)) for _r, h, _n, missing in doors(tmp_path)] == [("pay", ["bill"])]


def test_the_names_that_the_ledger_listed_are_recognised():
    for name, kind in (("original_invoice_id", "invoice"), ("linked_bill_id", "bill"), ("sales_invoice_id", "invoice"),
                       ("purchase_bill_id", "bill"), ("exclude_bill_id", "bill")):
        assert KINDS[kind][0].search(name), name
    assert not KINDS["invoice"][0].search("fee_invoice_number")
    for name, kind in (("evidence_document_id", "document"), ("journal_entry_id", "journal"), ("employee_id", "employee"),
                       ("from_godown_id", "godown"), ("batch_id", "batch"), ("cost_centre_id", "cost_centre"),
                       ("purchase_payment_id", "vendor_payment")):
        assert KINDS[kind][0].search(name), name


# ── each door the rule found ───────────────────────────────────────────────────────────────────────────────────────────────
FIRM = "11111111-1111-1111-1111-111111111111"
A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
PARTNER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "au1", "role": "Partner", "email": "p@example.test"}
LINE = {"service_catalogue_id": "svc-a", "description": "Service", "quantity": 1, "rate_paise": 100_000, "gst_rate_percent": 18}


def _world() -> FakeDB:
    db = FakeDB()
    for client, tag in ((A, "a"), (B, "b")):
        db.seed("clients", {"id": client, "firm_id": FIRM, "financial_year_start": "2025-04-01"})
        db.seed("vendors", {"id": f"vendor-{tag}", "firm_id": FIRM, "client_id": client, "is_active": True, "name": f"Vendor {tag}"})
        db.seed("customers", {"id": f"customer-{tag}", "firm_id": FIRM, "client_id": client, "is_active": True, "name": f"Customer {tag}"})
        db.seed("purchase_bills", {"id": f"bill-{tag}", "firm_id": FIRM, "client_id": client, "vendor_id": f"vendor-{tag}",
                                   "bill_no": f"B-{tag}", "status": "received", "deleted_at": None})
        db.seed("client_sales_invoices", {"id": f"invoice-{tag}", "firm_id": FIRM, "client_id": client, "customer_id": f"customer-{tag}",
                                          "invoice_no": f"INV-{tag}", "status": "issued", "deleted_at": None, "invoice_date": "2026-04-10"})
        db.seed("service_catalogue", {"id": f"svc-{tag}", "firm_id": FIRM, "client_id": client, "name": f"Item {tag}"})
        db.seed("bank_accounts", {"id": f"bank-{tag}", "firm_id": FIRM, "client_id": client, "bank_name": f"Bank {tag}"})
    return db


@pytest.fixture()
def world(monkeypatch):
    db = _world()
    wire_e2e(monkeypatch, db, [ri_router, ri_service, rpb_router, rpb_service, eway_router, receipts_router, pp_router,
                               debit_notes_router, pcn_router, sdn_router, credit_notes_router, sales_router])
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    for module in (ri_service, rpb_service):
        monkeypatch.setattr(module, "_db", lambda db=db: db, raising=False)
    import services.audit_service as audit
    monkeypatch.setattr(audit, "log_event", lambda *a, **k: None)
    return db


def _client(*routers) -> TestClient:
    app = FastAPI()
    for r in routers:
        app.include_router(r.router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return TestClient(app, raise_server_exceptions=False)


def _refused(res, words: str):
    assert res.status_code == 404 and res.json()["detail"] == words, (res.status_code, res.text)


def test_a_recurring_invoice_template_names_a_customer_of_its_own_client_only(world):
    body = {"client_id": A, "title": "Retainer", "frequency": "monthly", "start_date": "2026-05-01", "lines": [
        {"service_catalogue_id": "svc-a", "description": "Retainer", "rate_paise": 100_000}]}
    client = _client(ri_router)
    _refused(client.post("/api/recurring-invoices", json={**body, "customer_id": "customer-b"}), "That customer was not found.")
    assert world.rows("recurring_invoice_templates") == [], "nothing was stored for the sibling's customer"
    own = client.post("/api/recurring-invoices", json={**body, "customer_id": "customer-a"})
    assert own.json().get("detail") != "That customer was not found.", own.text


def test_a_recurring_purchase_bill_template_names_a_vendor_of_its_own_client_only(world):
    line = {"service_catalogue_id": "svc-a", "description": "Rent", "rate_paise": 100_000}
    body = {"client_id": A, "title": "Rent", "frequency": "monthly", "start_date": "2026-05-01", "lines": [line]}
    client = _client(rpb_router)
    _refused(client.post("/api/recurring-purchase-bills", json={**body, "vendor_id": "vendor-b"}), "That vendor was not found.")
    assert world.rows("recurring_purchase_bill_templates") == []
    own = client.post("/api/recurring-purchase-bills", json={**body, "vendor_id": "vendor-a"})
    assert own.json().get("detail") != "That vendor was not found.", own.text


def test_a_recurring_purchase_bill_template_cannot_be_re_pointed_at_a_sibling_clients_vendor(world):
    world.seed("recurring_purchase_bill_templates", {"id": "tpl-1", "firm_id": FIRM, "client_id": A, "vendor_id": "vendor-a", "title": "Rent",
                                                     "frequency": "monthly", "start_date": "2026-05-01", "next_run_date": "2026-05-01",
                                                     "status": "active"})
    client = _client(rpb_router)
    _refused(client.put("/api/recurring-purchase-bills/tpl-1", json={"vendor_id": "vendor-b"}), "That vendor was not found.")
    assert world.rows("recurring_purchase_bill_templates")[0]["vendor_id"] == "vendor-a"
    own = client.put("/api/recurring-purchase-bills/tpl-1", json={"vendor_id": "vendor-a"})
    assert own.status_code == 200, own.text


def test_an_eway_bill_names_an_invoice_of_its_own_client_only(world):
    body = {"client_id": A, "invoice_number": "A/1", "dispatch_from": "Pune", "ship_to": "Mumbai", "goods_description": "Goods",
            "taxable_value_paise": 100_000}
    client = _client(eway_router)
    _refused(client.post("/api/eway-bill/records", json={**body, "sales_invoice_id": "invoice-b"}), "That invoice was not found.")
    assert world.rows("eway_bill_records") == []
    own = client.post("/api/eway-bill/records", json={**body, "sales_invoice_id": "invoice-a"})
    assert own.json().get("detail") != "That invoice was not found.", own.text


def test_a_receipt_names_a_bank_account_of_its_own_client_only(world):
    body = {"client_id": A, "customer_id": "customer-a", "receipt_date": "2026-05-02", "amount_paise": 50_000, "payment_mode": "bank"}
    client = _client(receipts_router)
    res = client.post("/api/receipts", json={**body, "bank_account_id": "bank-b"})
    _refused(res, "That bank account was not found.")
    assert world.rows("receipts") == [] and world.rows("journal_entries") == []
    own = client.post("/api/receipts", json={**body, "bank_account_id": "bank-a"})
    assert "That bank account was not found." not in own.text, own.text


def test_a_vendor_payment_names_a_bank_account_of_its_own_client_only(world):
    body = {"client_id": A, "vendor_id": "vendor-a", "payment_date": "2026-05-02", "amount_paise": 10_000, "payment_mode": "bank"}
    client = _client(pp_router)
    res = client.post("/api/purchase-payments", json={**body, "bank_account_id": "bank-b"})
    _refused(res, "That bank account was not found.")
    assert world.rows("purchase_payments") == [] and world.rows("journal_entries") == []
    own = client.post("/api/purchase-payments", json={**body, "bank_account_id": "bank-a"})
    assert "That bank account was not found." not in own.text, own.text


NOTE_CASES = [
    # (id, router, create path, create body without the link, link field, sibling id, own id, words, table, update path prefix)
    ("debit note", debit_notes_router, "/api/debit-notes",
     {"vendor_id": "vendor-a", "debit_note_date": "2026-05-02"}, "purchase_bill_id", "bill-b", "bill-a",
     "That bill was not found.", "debit_notes"),
    ("purchase credit note", pcn_router, "/api/purchase-credit-notes",
     {"vendor_id": "vendor-a", "credit_note_date": "2026-05-02"}, "purchase_bill_id", "bill-b", "bill-a",
     "That bill was not found.", "purchase_credit_notes"),
    ("sales debit note", sdn_router, "/api/sales-debit-notes",
     {"customer_id": "customer-a", "debit_note_date": "2026-05-02"}, "sales_invoice_id", "invoice-b", "invoice-a",
     "That invoice was not found.", "sales_debit_notes"),
]


@pytest.mark.parametrize("name,router,path,base,field,sibling,own,words,table", NOTE_CASES, ids=[c[0] for c in NOTE_CASES])
def test_a_note_names_the_bill_or_invoice_it_amends_only_if_it_is_the_clients(world, name, router, path, base, field, sibling, own, words, table):
    client = _client(router)
    body = {"client_id": A, "lines": [LINE], **base}
    _refused(client.post(path, json={**body, field: sibling}), words)
    assert world.rows(table) == [], "the sibling's document was stored as the note's link"
    created = client.post(path, json={**body, field: own})
    assert created.status_code == 200, created.text
    note_id = created.json()["data"]["id"]
    _refused(client.patch(f"{path}/{note_id}", json={field: sibling}), words)
    assert world.rows(table)[0][field] == own, "the correction re-pointed the note at the sibling's document"
    assert client.patch(f"{path}/{note_id}", json={field: own}).status_code == 200


def test_a_sales_credit_note_cannot_be_re_pointed_at_a_sibling_clients_invoice(world):
    client = _client(credit_notes_router)
    body = {"client_id": A, "customer_id": "customer-a", "credit_note_date": "2026-05-02", "lines": [LINE]}
    created = client.post("/api/credit-notes", json={**body, "sales_invoice_id": "invoice-a"})
    assert created.status_code == 200, created.text
    note_id = created.json()["data"]["id"]
    _refused(client.patch(f"/api/credit-notes/{note_id}", json={"sales_invoice_id": "invoice-b"}), "That invoice was not found.")
    assert world.rows("credit_notes")[0]["sales_invoice_id"] == "invoice-a"


def test_the_statement_inspector_names_a_bank_account_of_its_own_client_only(world, monkeypatch):
    """The gap the second reading found: a saved column layout was looked up by the account id and the firm, so another client's
    account answered with that client's layout."""
    import io
    import routers.banking as banking
    from fastapi import HTTPException
    from starlette.datastructures import UploadFile
    monkeypatch.setattr(banking, "_db", lambda: world)
    looked_up: list = []
    monkeypatch.setattr(banking.column_mappings, "find_mapping",
                        lambda db, firm, account, fingerprint: looked_up.append(account) or {"id": "m", "mapping": {"x": 1}, "match_scope": "account"})
    csv = b"Date,Narration,Withdrawal,Deposit,Balance\n01/04/2026,Opening,0,0,100\n"

    def call(account):
        return banking.inspect_statement_file(file=UploadFile(file=io.BytesIO(csv), filename="s.csv"), client_id=A,
                                              bank_account_id=account, pdf_password=None, current_user=PARTNER)

    with pytest.raises(HTTPException) as refused:
        call("bank-b")
    assert refused.value.status_code == 404 and refused.value.detail == "That bank account was not found."
    assert looked_up == [], "the sibling's saved layout was looked up before the account was asked about"
    own = call("bank-a")
    assert own["success"] is True and looked_up == ["bank-a"], own


# ── the second family: each door the rule found ────────────────────────────────────────────────────────────────────────────
@pytest.fixture()
def filed(world, monkeypatch):
    """The world, with a stored file and a ledger entry for each client, and the three workspaces' mock stores emptied."""
    import domain.income_tax.computation_workspace as workspace
    import domain.income_tax.form26as_service as form26as
    for client, tag in ((A, "a"), (B, "b")):
        world.seed("client_documents", {"id": f"doc-{tag}", "firm_id": FIRM, "client_id": client, "file_name": f"{tag}.pdf"})
        world.seed("journal_entries", {"id": f"je-{tag}", "firm_id": FIRM, "client_id": client, "entry_date": "2026-05-01"})
    for store in ("_MOCK_UPLOADS", "_MOCK_RECORDS"):
        monkeypatch.setattr(form26as, store, {})
    for store in ("_MOCK_DISALLOWANCES", "_MOCK_DEDUCTIONS"):
        monkeypatch.setattr(workspace, store, {})
    return world


def test_a_26as_upload_names_a_stored_file_of_its_own_client_only(filed):
    import domain.income_tax.form26as_service as form26as
    client = _client(form26as_router)
    body = {"client_id": A, "financial_year": "2025-26"}
    _refused(client.post("/api/form-26as/uploads", json={**body, "document_id": "doc-b"}), "That document was not found.")
    assert form26as._MOCK_UPLOADS == {}, "the sibling's file was stored as the upload's"
    own = client.post("/api/form-26as/uploads", json={**body, "document_id": "doc-a"})
    assert own.status_code == 200 and own.json()["data"]["document_id"] == "doc-a", own.text
    nothing_named = client.post("/api/form-26as/uploads", json=body)
    assert nothing_named.status_code == 200, "an upload that names no file is not stopped by the question"


def test_a_deduction_claim_names_an_evidence_file_of_its_own_client_only(filed):
    import domain.income_tax.computation_workspace as workspace
    client = _client(itr_router)
    body = {"client_id": A, "financial_year": "2025-26", "section": "80C", "claimed_amount_paise": 150_000_00}
    _refused(client.post("/api/itr/deductions", json={**body, "evidence_document_id": "doc-b"}), "That document was not found.")
    assert workspace._MOCK_DEDUCTIONS == {}
    own = client.post("/api/itr/deductions", json={**body, "evidence_document_id": "doc-a"})
    assert own.status_code == 200 and own.json()["data"]["evidence_document_id"] == "doc-a", own.text


@pytest.mark.parametrize("field,sibling,words", [
    ("evidence_document_id", "doc-b", "That document was not found."),
    ("journal_entry_id", "je-b", "That journal entry was not found."),
])
def test_a_disallowance_names_an_evidence_file_and_a_ledger_entry_of_its_own_client_only(filed, field, sibling, words):
    import domain.income_tax.computation_workspace as workspace
    client = _client(itr_router)
    body = {"client_id": A, "financial_year": "2025-26", "section": "40A(3)", "description": "Cash payment", "amount_paise": 20_000_00}
    own_ids = {"evidence_document_id": "doc-a", "journal_entry_id": "je-a"}
    _refused(client.post("/api/itr/disallowances", json={**body, **own_ids, field: sibling}), words)
    assert workspace._MOCK_DISALLOWANCES == {}, "the sibling's row was stored on the disallowance"
    own = client.post("/api/itr/disallowances", json={**body, **own_ids})
    assert own.status_code == 200, own.text
    assert (own.json()["data"]["evidence_document_id"], own.json()["data"]["journal_entry_id"]) == ("doc-a", "je-a")
