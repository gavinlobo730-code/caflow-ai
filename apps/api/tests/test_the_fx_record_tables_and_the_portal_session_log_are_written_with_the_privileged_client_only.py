"""`fx_adjustments`, `fx_revaluations` and `client_portal_sessions` are written with the privileged client, and by nothing else (ledger POST-A-299).

THE DEFECT
    The three tables carry a firm policy and no assignment scope and no role tier, and the signed-in role holds INSERT, UPDATE and
    DELETE on them (migrations 156 and 194), so any member of the firm, an unassigned Reviewer included, can write them over
    PostgREST. Reproduced on a throwaway database on 21-10-2026: a Reviewer forged a `client_portal_sessions` row (it feeds the
    health score's login recency), and the rows of `fx_revaluations` are what the next revaluation diffs against, so a forged one
    changes the next journal. `fx_adjustments` is what the FX reports and the vendor statement read the realised and unrealised
    gain or loss from. The migration that follows this change takes the writes away from `authenticated`, so their writers have to
    be on the privileged client BEFORE it applies, or every foreign receipt, foreign vendor payment and revaluation answers 42501 in
    production while passing in mock mode (a double accepts any caller). The privileged client is a superset of what the request's
    client could write, so this change is safe on today's grants too. The real-Postgres half is the file of the migration.

WHAT IS HELD (no database)
    * (source, derived from the AST of every module of the API, `scripts/` included) the only code that writes the three tables is
      the set of functions named below; a query kept in a variable, the table's name held in a constant, `.from_`, a module-level
      statement and SQL text are each shown to the detector and each must fire;
    * each FX write goes through the client `fx_writer` returned and never through the `db` it was handed, and the portal touch goes
      through `get_service_supabase()`; the functions that write the FX tables name no privileged accessor of their own;
    * the privileged receiver is used ONLY to write the two FX tables: a read, or a write to any other table, moved onto it would
      take row security away from a statement that relies on it;
    * the helper hands out the privileged client where there is one, the request's own where there is none (mock mode), and `None`
      stays `None`;
    * driven end to end through a request client that REFUSES the two FX tables' writes the way `authenticated` will, a foreign
      receipt, a single-bill foreign vendor payment, a multi-bill foreign vendor payment and a revaluation still succeed, every FX
      row lands on the privileged client, and each carries the firm and the client, because the privileged client does not carry
      row security;
    * nothing in the browser reads or writes the three tables.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import core.db_provider
from domain.currency.fx_writer import fx_writer
from tests._table_uses import WRITE_VERBS, sources as _sources, uses as _uses
from tests.e2e_harness import FakeDB, seed_standard_coa, wire_e2e

API_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = API_ROOT.parents[1] / "apps" / "web"

FX_TABLES = ("fx_adjustments", "fx_revaluations")
REVAL = "domain/currency/fx_revaluation_service.py"
PAYMENT_ROUTER = "routers/purchase_payments.py"
PAYMENT_SERVICE = "services/purchase_payment_service.py"
RECEIPT_SERVICE = "services/receipt_service.py"
PORTAL = "core/portal_auth.py"
# table -> {file: the set of functions that write it}
EXPECTED_WRITERS = {
    "fx_adjustments": {REVAL: {"revalue"}, PAYMENT_ROUTER: {"_create_foreign_payment"},
                       PAYMENT_SERVICE: {"create_foreign_payment_core"}, RECEIPT_SERVICE: {"create_foreign_receipt"}},
    "fx_revaluations": {REVAL: {"revalue"}},
    "client_portal_sessions": {PORTAL: {"_touch_portal_session"}},
}
FX_FILES = (REVAL, PAYMENT_ROUTER, PAYMENT_SERVICE, RECEIPT_SERVICE)
PRIVILEGED_NAMES = {"service_db", "service_db_or_none", "service_db_or_503", "get_service_supabase", "_service_client"}


def test_only_the_named_functions_write_each_table_and_no_spelling_hides_a_write():
    found: dict[str, dict[str, set]] = {t: {} for t in EXPECTED_WRITERS}
    hidden = []
    for rel, text in _sources():
        for table in EXPECTED_WRITERS:
            if table not in text:
                continue
            for kind, fn, line, _receiver, _verbs in _uses(text, table):
                if kind == "write":
                    found[table].setdefault(rel, set()).add(fn)
                elif kind in {"unchained", "named", "raw_write"} and not (table == "client_portal_sessions" and rel == "routers/health.py"):
                    hidden.append((rel, line, table, kind))
    assert not hidden, (f"these places name a table in a way the guard cannot read ({hidden}): a query kept in a variable, the "
                        "name held in a constant, or SQL text. Chain the verb off `.table(\"<table>\")` where it is used.")
    assert found == EXPECTED_WRITERS, found


def test_the_guard_sees_every_shape_a_write_can_take():
    for table in EXPECTED_WRITERS:
        shapes = {
            "a query kept in a variable": f'def f(db):\n    q = db.table("{table}")\n    q.update({{}}).execute()\n',
            "the name held in a constant": f'T = "{table}"\n\ndef f(db):\n    db.table(T).delete().execute()\n',
            "from_ instead of table": f'def f(db):\n    db.from_("{table}").insert({{}}).execute()\n',
            "a statement at module level": f'client.table("{table}").update({{}}).execute()\n',
            "an upsert": f'def f(db):\n    db.table("{table}").upsert({{}}).execute()\n',
            "raw SQL": f'def f(cur):\n    cur.execute("DELETE FROM public.{table} WHERE true")\n',
        }
        for label, source in shapes.items():
            kinds = {k for k, *_ in _uses(source, table)}
            assert kinds & {"write", "unchained", "named", "raw_write"}, f"the guard is blind to: {label} ({table})"
        assert [k for k, *_ in _uses(f'def f(db):\n    return db.table("{table}").select("*").execute()\n', table)] == ["read"]


def test_the_walk_reads_enough_modules_to_mean_something():
    rels = [rel for rel, _ in _sources()]
    assert len(rels) > 300, len(rels)
    assert any(r.startswith("scripts/") for r in rels), "the scripts directory is not walked: a one-off writer would pass"
    assert all(f in rels for f in (*FX_FILES, PORTAL, "domain/currency/fx_writer.py"))


def _is_fx_writer_call(node) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "fx_writer"


def test_each_fx_write_goes_through_the_client_the_helper_returned_and_never_the_one_it_was_handed():
    """A write on `db` itself is the defect; so is the helper being called after the write, and so is its result being re-bound."""
    for table in FX_TABLES:
        for rel in EXPECTED_WRITERS[table]:
            text = (API_ROOT / rel).read_text(encoding="utf-8")
            tree = ast.parse(text)
            for kind, fn, line, receiver, _verbs in _uses(text, table):
                if kind != "write":
                    continue
                if _is_fx_writer_call(receiver):
                    continue
                assert isinstance(receiver, ast.Name), f"{rel}:{line} {fn} writes {table} through {ast.dump(receiver)[:80]}"
                fdef = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == fn)
                bindings = [a for a in ast.walk(fdef) if isinstance(a, ast.Assign)
                            and any(isinstance(t, ast.Name) and t.id == receiver.id for t in a.targets)]
                assert bindings, f"{rel} {fn}: {receiver.id} is never assigned"
                assert all(_is_fx_writer_call(a.value) for a in bindings), \
                    f"{rel} {fn}: {receiver.id} is bound to something other than fx_writer(...)"
                assert min(a.lineno for a in bindings) < line, f"{rel} {fn}: {receiver.id} is bound after its first write"


def test_the_portal_touch_writes_through_the_service_accessor_it_names():
    text = (API_ROOT / PORTAL).read_text(encoding="utf-8")
    writes = [u for u in _uses(text, "client_portal_sessions") if u[0] == "write"]
    assert len(writes) == 1
    receiver = writes[0][3]
    assert (isinstance(receiver, ast.Call) and isinstance(receiver.func, ast.Name)
            and receiver.func.id == "get_service_supabase"), ast.dump(receiver)[:120]


def _names_a_privileged_accessor(fn) -> bool:
    for node in ast.walk(fn):
        name = node.attr if isinstance(node, ast.Attribute) else node.id if isinstance(node, ast.Name) else None
        if name in PRIVILEGED_NAMES:
            return True
        if isinstance(node, (ast.ImportFrom, ast.Import)) and any(a.name.split(".")[-1] in PRIVILEGED_NAMES for a in node.names):
            return True
    return False


def test_the_functions_that_write_the_fx_tables_name_no_privileged_accessor_and_the_helper_is_the_only_one_that_does():
    for rel in FX_FILES:
        tree = ast.parse((API_ROOT / rel).read_text(encoding="utf-8"))
        writers = {fn for table in FX_TABLES for fn in EXPECTED_WRITERS[table].get(rel, set())}
        for fdef in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            if fdef.name in writers:
                assert not _names_a_privileged_accessor(fdef), f"{rel} {fdef.name} reaches for a privileged client itself"
        top = [n for n in tree.body if isinstance(n, (ast.ImportFrom, ast.Import))
               and any(a.name.split(".")[-1] in PRIVILEGED_NAMES for a in n.names)]
        assert not top, (rel, "a module-level import of a privileged client accessor")
    helper = ast.parse((API_ROOT / "domain/currency/fx_writer.py").read_text(encoding="utf-8"))
    namers = {f.name for f in ast.walk(helper) if isinstance(f, ast.FunctionDef) and _names_a_privileged_accessor(f)}
    assert namers == {"fx_writer"}


def test_the_privileged_receiver_is_used_only_to_write_the_two_fx_tables():
    """Every `.table(...)` called on a result of the helper, or on a name bound to it, must name an FX table and chain a write
    verb: a read, or another table, would take row security away from a statement that relies on it."""
    seen = 0
    for rel in FX_FILES:
        tree = ast.parse((API_ROOT / rel).read_text(encoding="utf-8"))
        parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
        bound = {t.id for a in ast.walk(tree) if isinstance(a, ast.Assign) and _is_fx_writer_call(a.value)
                 for t in a.targets if isinstance(t, ast.Name)}
        for call in ast.walk(tree):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr in {"table", "from_"}):
                continue
            receiver = call.func.value
            if not (_is_fx_writer_call(receiver) or (isinstance(receiver, ast.Name) and receiver.id in bound)):
                continue
            seen += 1
            name = call.args[0].value if call.args and isinstance(call.args[0], ast.Constant) else None
            assert name in FX_TABLES, f"{rel}:{call.lineno} the privileged client is used on {name!r}, which is not an FX table"
            verbs, up = [], call
            while isinstance(parents.get(up), ast.Attribute) and isinstance(parents.get(parents[up]), ast.Call):
                verbs.append(parents[up].attr)
                up = parents[parents[up]]
            assert set(verbs) & WRITE_VERBS, f"{rel}:{call.lineno} the privileged client READS {name} (chain: {verbs})"
    assert seen == 5, seen            # four fx_adjustments writers and one fx_revaluations writer; a vacuous pass finds none


def test_nothing_in_the_browser_reads_or_writes_the_tables_directly():
    """SELECT stays granted (the API reads under the caller's sign-in), but nothing in the browser has a reason to read these
    tables, and a first read there would be a second reader that bypasses the routes' checks."""
    pattern = re.compile(r"""\.from\(\s*["'`](%s)["'`]""" % "|".join(EXPECTED_WRITERS))
    hits = []
    for path in WEB_ROOT.rglob("*"):
        if path.suffix not in {".ts", ".tsx"} or "node_modules" in path.parts or ".next" in path.parts:
            continue
        if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
            hits.append(path.relative_to(WEB_ROOT).as_posix())
    assert not hits, hits


# ── the helper ───────────────────────────────────────────────────────────────

class _Marker:
    pass


def test_the_helper_hands_out_the_privileged_client_and_keeps_none_none(monkeypatch):
    privileged, request = _Marker(), _Marker()
    monkeypatch.setattr(core.db_provider, "service_db_or_none", lambda: privileged)
    assert fx_writer(request) is privileged
    assert fx_writer(None) is None
    monkeypatch.setattr(core.db_provider, "service_db_or_none", lambda: None)
    assert fx_writer(request) is request


# ── a request client that refuses the writes, as `authenticated` now does ─────

class _Recording:
    """Wraps an in-memory double. A write to a protected table is recorded with its filters; with `refuse` it raises as the
    database now does for a signed-in session."""

    def __init__(self, inner, refuse):
        self.inner, self.refuse, self.log, self.refused = inner, refuse, [], []

    def table(self, name):
        return _Statement(self, self.inner.table(name), name)

    def __getattr__(self, attr):
        return getattr(self.inner, attr)


class _Statement:
    def __init__(self, owner, query, name):
        self._owner, self._query, self._name = owner, query, name
        self._verb, self._payload = "select", None

    def __getattr__(self, attr):
        target = getattr(self._query, attr)

        def call(*args, **kwargs):
            if attr in WRITE_VERBS:
                self._verb, self._payload = attr, args[0] if args else None
                if self._owner.refuse and self._name in FX_TABLES:
                    # recorded BEFORE it raises, so a writer left on the request's client is seen even where the caller swallows it
                    self._owner.refused.append((self._name, attr))
                    raise RuntimeError(f"permission denied for table {self._name}")
            result = target(*args, **kwargs)
            return self if result is self._query else result
        return call

    def execute(self):
        result = self._query.execute()
        if self._verb in WRITE_VERBS and self._name in FX_TABLES:
            self._owner.log.append({"table": self._name, "verb": self._verb, "payload": self._payload})
        return result


def test_the_refusing_double_refuses_every_write_verb_on_an_fx_table_and_only_there():
    inner = FakeDB()
    request = _Recording(inner, True)
    for table in FX_TABLES:
        for verb in sorted(WRITE_VERBS):
            with pytest.raises(RuntimeError, match="permission denied"):
                getattr(request.table(table), verb)({})
    assert {v for _t, v in request.refused} == WRITE_VERBS
    before = len(request.refused)
    request.table("currencies").insert({"code": "ZZZ"})                    # not protected: allowed
    assert len(request.refused) == before
    privileged = _Recording(inner, False)
    privileged.table("fx_adjustments").insert({"id": "y", "firm_id": "F", "client_id": "C"}).execute()
    assert privileged.refused == [] and [e["verb"] for e in privileged.log] == ["insert"]


FIRM = "FIRM-FX-WRITER"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "u1", "email": "ca@f.test", "role": "Partner"}


def _world(monkeypatch):
    """One in-memory store seen through two clients: the request's (refuses the FX writes) and the privileged one."""
    import routers.customers as cu
    import routers.vendors as ve
    import routers.sales_invoices as si
    import routers.purchase_bills as pb
    import routers.receipts as rc
    import routers.purchase_payments as pp
    import services.receipt_service as rs
    import services.purchase_payment_service as pps
    inner = FakeDB()
    request, privileged = _Recording(inner, True), _Recording(inner, False)
    wire_e2e(monkeypatch, request, [cu, ve, si, pb, rc, pp, rs, pps])
    monkeypatch.setattr(core.db_provider, "service_db_or_none", lambda: privileged)
    monkeypatch.setenv("MULTI_CURRENCY_ENABLED", "true")
    inner.seed("firms", {"id": FIRM, "multi_currency_entitled": True})
    inner.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5",
                           "functional_currency": "INR", "multi_currency_enabled": True})
    inner.seed("currencies", {"code": "USD", "symbol": "$", "display_name": "US Dollar", "minor_unit": 2, "is_active": True})
    inner.seed("currencies", {"code": "INR", "symbol": "₹", "display_name": "Indian Rupee", "minor_unit": 2, "is_active": True})
    seed_standard_coa(inner, FIRM, "CLI")
    inner.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI", "name": "Services", "kind": "service"})
    return inner, request, privileged, (cu, ve, si, pb, rc, pp, pps)


def _every_fx_row_names_the_firm_and_client(log):
    assert log, "nothing was written through the privileged client"
    for entry in log:
        assert entry["verb"] == "insert", entry
        assert entry["payload"]["firm_id"] == FIRM and entry["payload"]["client_id"] == "CLI", entry


def test_a_foreign_receipt_records_its_exchange_difference_on_the_privileged_client(monkeypatch):
    from models.invoices import (InvoiceLineIn, ReceiptAllocationIn, ReceiptIn, SalesInvoiceIn)
    from models.parties import CustomerIn
    inner, request, privileged, (cu, _ve, si, _pb, rc, _pp, _pps) = _world(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="US Co", state_code="27"), CALLER)["data"]
    inv = si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id=cust["id"], invoice_date="2026-06-01", invoice_no="USD-INV-1", currency="USD",
        exchange_rate="80.0",
        lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="Export", hsn_sac="9982", quantity=1,
                             rate_paise=100000, gst_rate_percent=0.0)]), CALLER)["data"]
    si.issue_invoice(inv["id"], CALLER)
    rc.create_receipt(ReceiptIn(
        client_id="CLI", customer_id=cust["id"], receipt_date="2026-06-10", amount_paise=100000, currency="USD",
        exchange_rate="83.0",
        allocations=[ReceiptAllocationIn(sales_invoice_id=inv["id"], allocated_paise=100000)]), CALLER)
    assert request.refused == []                                              # nothing was attempted on the request's client
    _every_fx_row_names_the_firm_and_client(privileged.log)
    assert [r["document_type"] for r in inner.rows("fx_adjustments")] == ["receipt"]
    assert inner.rows("fx_adjustments")[0]["base_delta_paise"] == 300000        # 1,000.00 USD * (83 - 80)


def test_a_single_bill_foreign_payment_records_its_exchange_difference_on_the_privileged_client(monkeypatch):
    from models.invoices import PurchaseBillIn, PurchaseBillLineIn, PurchasePaymentIn
    from models.parties import VendorIn
    inner, request, privileged, (_cu, ve, _si, pb, _rc, pp, _pps) = _world(monkeypatch)
    vend = ve.create_vendor(VendorIn(client_id="CLI", name="US Supplies", state_code="27"), CALLER)["data"]
    bill = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id=vend["id"], bill_date="2026-06-01", bill_no="USD-BILL-1", currency="USD", exchange_rate="80.0",
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="Import", hsn_sac="9982", quantity=1,
                                  rate_paise=100000, gst_rate_percent=0.0)]), CALLER)["data"]
    pb.receive_purchase_bill(bill["id"], CALLER)
    pp.create_purchase_payment(PurchasePaymentIn(
        client_id="CLI", vendor_id=vend["id"], payment_date="2026-06-10", amount_paise=100000,
        purchase_bill_id=bill["id"], currency="USD", exchange_rate="83.0"), CALLER)
    assert request.refused == []
    _every_fx_row_names_the_firm_and_client(privileged.log)
    assert [r["document_type"] for r in inner.rows("fx_adjustments")] == ["purchase_payment"]


def test_a_multi_bill_foreign_payment_records_its_exchange_difference_on_the_privileged_client(monkeypatch):
    from models.invoices import PurchaseBillIn, PurchaseBillLineIn
    from models.parties import VendorIn
    inner, request, privileged, (_cu, ve, _si, pb, _rc, _pp, pps) = _world(monkeypatch)
    vend = ve.create_vendor(VendorIn(client_id="CLI", name="US Supplies", state_code="27"), CALLER)["data"]
    ids = []
    for no in ("USD-BILL-A", "USD-BILL-B"):
        bill = pb.create_purchase_bill(PurchaseBillIn(
            client_id="CLI", vendor_id=vend["id"], bill_date="2026-06-01", bill_no=no, currency="USD", exchange_rate="80.0",
            lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="Import", hsn_sac="9982", quantity=1,
                                      rate_paise=50000, gst_rate_percent=0.0)]), CALLER)["data"]
        pb.receive_purchase_bill(bill["id"], CALLER)
        ids.append(bill["id"])
    pps.create_payment_core(FIRM, {
        "client_id": "CLI", "vendor_id": vend["id"], "payment_date": "2026-06-10", "amount_paise": 100000,
        "currency": "USD", "exchange_rate": "83.0",
        "allocations": [{"purchase_bill_id": ids[0], "allocated_paise": 50000},
                        {"purchase_bill_id": ids[1], "allocated_paise": 50000}]}, CALLER, request)
    assert request.refused == []
    _every_fx_row_names_the_firm_and_client(privileged.log)
    assert [r["document_type"] for r in inner.rows("fx_adjustments")] == ["purchase_payment"]


def test_a_revaluation_records_its_run_and_its_adjustment_on_the_privileged_client(monkeypatch):
    from domain.currency.fx_revaluation_service import fx_revaluation_service
    inner, request, privileged, _mods = _world(monkeypatch)
    ids = seed_standard_coa(inner, FIRM, "CLI")
    bank_coa = ids["bank"]
    inner.seed("bank_accounts", {"id": "bank-usd", "firm_id": FIRM, "client_id": "CLI", "currency": "USD", "coa_account_id": bank_coa})
    inner.seed("journal_entries", {"id": "je-bank", "firm_id": FIRM, "client_id": "CLI", "entry_date": "2025-06-01",
                                   "is_posted": True, "deleted_at": None})
    inner.seed("journal_lines", {"journal_entry_id": "je-bank", "account_id": bank_coa, "debit_paise": 8_000_000, "credit_paise": 0,
                                 "txn_debit": 100000, "txn_credit": 0, "txn_currency": "USD"})
    inner.seed("journal_lines", {"journal_entry_id": "je-bank", "account_id": ids["revenue"], "debit_paise": 0,
                                 "credit_paise": 8_000_000, "txn_debit": 0, "txn_credit": 100000, "txn_currency": "USD"})
    out = fx_revaluation_service.revalue(request, FIRM, "CLI", "2026-03-31", {"USD": "84.0"}, CALLER)
    assert [a["delta_paise"] for a in out["adjustments"]] == [400_000]
    assert request.refused == []
    assert sorted(e["table"] for e in privileged.log) == ["fx_adjustments", "fx_revaluations"]
    _every_fx_row_names_the_firm_and_client(privileged.log)
    assert [r["kind"] for r in inner.rows("fx_adjustments")] == ["unrealized"]
