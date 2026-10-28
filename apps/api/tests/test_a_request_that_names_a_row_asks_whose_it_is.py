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
from tests.e2e_harness import FakeDB, wire_e2e

API = Path(__file__).resolve().parent.parent

# field name -> (kind, functions that ask, tables whose client-filtered read counts)
KINDS: dict[str, tuple[re.Pattern, set[str], set[str]]] = {
    "vendor": (re.compile(r"(^|_)vendor_id$"), {"vendor_is_the_clients"}, {"vendors"}),
    "customer": (re.compile(r"(^|_)customer_id$"), {"customer_is_the_clients"}, {"customers"}),
    "bill": (re.compile(r"(^|_)purchase_bill_id$"), {"purchase_bill_is_the_clients"}, {"purchase_bills"}),
    "invoice": (re.compile(r"(^|_)sales_invoice_id$"), {"sales_invoice_is_the_clients"}, {"client_sales_invoices"}),
    "bank": (re.compile(r"(^|_)bank_account_id$"), {"bank_account_is_the_clients", "_validate_bank_account"}, {"bank_accounts"}),
    "order": (re.compile(r"(^|_)order_id$"), {"order_of_client", "row_of_client"}, {"purchase_orders", "sales_orders"}),
    "quotation": (re.compile(r"(^|_)quotation_id$"), {"row_of_client"}, {"sales_quotations"}),
}
SCAN_DIRS = ("services", "domain", "repositories", "routers", "models", "core")
WRITING_VERBS = ("post", "put", "patch", "delete")
DEPTH = 5

# A door the rule flags that is safe, and why. Shrink-only: each key must still be flagged.
REVIEWED: dict[tuple[str, str, str], str] = {
    ("purchase_bills", "probe_near_duplicates", "vendor"):
        "a read-only probe (POST only because an invoice number does not belong in a URL): it lists the bills of THIS client that carry the "
        "vendor id, so a vendor of another client matches no bill of this one and the answer is the empty list a missing vendor gets.",
}


# ── the scanner ────────────────────────────────────────────────────────────────────────────────────────────────────────────
class _Tree:
    """Every module under the scanned directories of `root`, its functions and methods, and what each file imports."""

    def __init__(self, root: Path):
        self.mods: dict[str, ast.Module] = {}
        for d in SCAN_DIRS:
            for p in (root / d).rglob("*.py") if (root / d).is_dir() else []:
                try:
                    tree = ast.parse(p.read_text(encoding="utf-8"))
                except (SyntaxError, UnicodeDecodeError):
                    continue
                self.mods[p.relative_to(root).with_suffix("").as_posix().replace("/", ".")] = tree
        self.funcs: dict[tuple[str, str], ast.AST] = {}
        self.imports: dict[str, dict] = {}
        self.by_name: dict[str, list[tuple[str, str]]] = {}
        for mod, tree in self.mods.items():
            self.imports[mod] = self._imports_of(tree)
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.funcs[(mod, node.name)] = node
                elif isinstance(node, ast.ClassDef):
                    for b in node.body:
                        if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            self.funcs[(mod, f"{node.name}.{b.name}")] = b
        for (mod, name) in self.funcs:
            self.by_name.setdefault(name.split(".")[-1], []).append((mod, name))
        self.models = self._models_with_named_fields()

    def _imports_of(self, scope) -> dict:
        out: dict = {}
        for node in ast.walk(scope):
            if isinstance(node, ast.Import):
                for a in node.names:
                    out[a.asname or a.name.split(".")[0]] = ("mod", a.name if a.asname else a.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                for a in node.names:
                    full = f"{node.module}.{a.name}"
                    out[a.asname or a.name] = ("mod", full) if full in self.mods else ("sym", node.module, a.name)
        return out

    def _models_with_named_fields(self) -> dict[str, dict[str, set[str]]]:
        found: dict[str, dict[str, set[str]]] = {}
        for mod, tree in self.mods.items():
            if not (mod.startswith("models.") or mod.startswith("routers.")):
                continue
            for c in ast.walk(tree):
                if isinstance(c, ast.ClassDef):
                    for n in c.body:
                        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                            for kind, (rx, _, _) in KINDS.items():
                                if rx.search(n.target.id):
                                    found.setdefault(c.name, {}).setdefault(kind, set()).add(n.target.id)
        return found

    # ── what a function asks, itself and down its calls ──
    @staticmethod
    def _called(call: ast.Call):
        f = call.func
        return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)

    @staticmethod
    def _chain(call: ast.Call):
        out, node = [], call
        while isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            out.append((node.func.attr, node))
            node = node.func.value
        return out

    def _tables(self, fn) -> set[str]:
        return {c.args[0].value for c in ast.walk(fn)
                if isinstance(c, ast.Call) and self._called(c) == "table" and c.args and isinstance(c.args[0], ast.Constant)}

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
            name = self._called(c) or ""
            for kind, (_, asking, _) in KINDS.items():
                if name in asking:
                    asked.add(kind)
            table, filtered = None, False
            for method, link in self._chain(c):
                if method == "table" and link.args and isinstance(link.args[0], ast.Constant):
                    table = link.args[0].value
                if method in ("eq", "in_") and link.args and isinstance(link.args[0], ast.Constant) and link.args[0].value == "client_id":
                    filtered = True
            if filtered:
                for kind, (_, _, tables) in KINDS.items():
                    if table in tables:
                        asked.add(kind)
        return asked

    def _resolve(self, call: ast.Call, mod: str, imports: dict, cls) -> list[tuple[str, str]]:
        f = call.func
        if isinstance(f, ast.Name):
            if (mod, f.id) in self.funcs:
                return [(mod, f.id)]
            i = imports.get(f.id)
            if i and i[0] == "sym" and (i[1], i[2]) in self.funcs:
                return [(i[1], i[2])]
            return []
        if isinstance(f, ast.Attribute):
            if isinstance(f.value, ast.Name):
                if f.value.id == "self" and cls and (mod, f"{cls}.{f.attr}") in self.funcs:
                    return [(mod, f"{cls}.{f.attr}")]
                i = imports.get(f.value.id)
                if i and i[0] in ("mod", "sym"):
                    if i[0] == "mod" and (i[1], f.attr) in self.funcs:
                        return [(i[1], f.attr)]
                    methods = [k for k in self.funcs if k[0] == i[1] and k[1].endswith("." + f.attr)]
                    if len(methods) == 1:
                        return methods
            candidates = self.by_name.get(f.attr, [])
            if len(candidates) == 1:
                return candidates
        return []

    def asks(self, key: tuple[str, str], depth: int = DEPTH, seen: frozenset = frozenset()) -> set[str]:
        mod, name = key
        fn = self.funcs[key]
        asked = self._own_kinds(fn)
        local = dict(self.imports[mod])
        local.update(self._imports_of(fn))
        cls = name.split(".")[0] if "." in name else None
        callees = [k for c in ast.walk(fn) if isinstance(c, ast.Call) for k in self._resolve(c, mod, local, cls)]
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
            for arg in fn.args.args + fn.args.kwonlyargs:
                annotation = ast.unparse(arg.annotation) if arg.annotation else ""
                for model, by_kind in tree.models.items():
                    if re.search(rf"\b{model}\b", annotation):
                        for kind, fields in by_kind.items():
                            named.setdefault(kind, set()).update(fields)
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
    seen_kinds = set().union(*(named for _r, _h, named, _m in real))
    assert seen_kinds == set(KINDS), f"kinds never seen: {set(KINDS) - seen_kinds}"
    handlers = {(r, h) for r, h, _n, _m in real}
    for expected in (("receipts", "create_receipt"), ("purchase_payments", "create_purchase_payment"), ("eway_bill", "create_eway_bill"),
                     ("recurring_invoices", "create_recurring"), ("recurring_purchase_bills", "create_recurring_bill"),
                     ("debit_notes", "create_debit_note"), ("fixed_assets", "create_asset"), ("bills_of_entry", "create_bill_of_entry")):
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
