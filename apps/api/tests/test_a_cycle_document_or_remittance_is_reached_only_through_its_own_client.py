"""A sales or purchase cycle document, and a payroll remittance, are reached only through the client they belong to (24-10-2026).

WHAT WAS WRONG
    Fourteen routes took the client from the query or the path, called `assert_client_access` on it, and then handed only the firm and
    the document's id to a service that reads and writes through the privileged client: the quotation lines, quotation PATCH,
    order position, order PATCH and challan read and PATCH of the SALES cycle, the order lines, order position, order PATCH, receipt
    lines, receipt PATCH and bill match of the PURCHASE cycle, and the payroll remittance link and retract. A member assigned to
    client A alone could name A beside client B's document id and read B's lines and positions, amend B's orders and challans
    (including the challan's `received_back_on`, which stops the s.143 clock), change B's goods receipt objection dates (which move
    the MSMED s.43B(h) fifteen days), and link or retract B's statutory remittance. They were found by the independent review of the
    first version of this hardening, which had fixed the payroll employee handlers and the Bills of Entry and had said the shape was
    closed; a syntactic scan cannot see a read that sits inside a service function.

THE FIX, AND THE RULE
    Each route now reads the document by firm and id and compares its client with the one the caller named (`row_of_client`,
    `order_of_client`, `receipt_of_client`, `bill_of_client`: 404 in the words a missing document gets), and the remittance service
    takes `client_id` as a required keyword and filters on it. The rule is derived from the two routers' own source: every handler
    with a document id in its path calls one of the four helpers or is listed with the reason it does not.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest
from fastapi import HTTPException

import routers.payroll as payroll_router
import routers.purchase_cycle as pc
import routers.sales_cycle as sc
from services import purchase_cycle_service as pcs
from services import sales_cycle_service as scs
from services import statutory_remittance_service as rem
from tests.e2e_harness import FakeDB, wire_e2e

FIRM = "11111111-1111-1111-1111-111111111111"
A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
QT, SO, DC = "q0000000-0000-0000-0000-00000000000b", "s0000000-0000-0000-0000-00000000000b", "c0000000-0000-0000-0000-00000000000b"
PO, GR, PB = "p0000000-0000-0000-0000-00000000000b", "g0000000-0000-0000-0000-00000000000b", "e0000000-0000-0000-0000-00000000000b"
RM, JE = "r0000000-0000-0000-0000-00000000000b", "j0000000-0000-0000-0000-00000000000b"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "au1", "role": "Partner", "email": "p@example.test"}


@pytest.fixture
def world(monkeypatch):
    db = FakeDB()
    db.seed("sales_quotations", {"id": QT, "firm_id": FIRM, "client_id": B, "kind": "quotation", "document_no": "Q1", "status": "draft",
                                 "notes": "original"})
    db.seed("sales_orders", {"id": SO, "firm_id": FIRM, "client_id": B, "document_no": "S1", "status": "confirmed", "notes": "original"})
    db.seed("delivery_challans", {"id": DC, "firm_id": FIRM, "client_id": B, "document_no": "D1", "status": "issued",
                                  "document_date": "2026-06-01", "reason": "job_work", "received_back_on": None, "notes": "original"})
    db.seed("purchase_orders", {"id": PO, "firm_id": FIRM, "client_id": B, "document_no": "P1", "status": "approved", "notes": "original"})
    db.seed("goods_receipt_notes", {"id": GR, "firm_id": FIRM, "client_id": B, "document_no": "G1", "received_on": "2026-06-01",
                                    "status": "received", "objection_raised_on": None, "objection_removed_on": None})
    db.seed("purchase_bills", {"id": PB, "firm_id": FIRM, "client_id": B, "bill_no": "PB1", "status": "received"})
    db.seed("statutory_remittances", {"id": RM, "firm_id": FIRM, "client_id": B, "scheme": "esic", "wage_month": "2026-09",
                                      "status": "paid", "journal_entry_id": None, "deleted_at": None})
    db.seed("journal_entries", {"id": JE, "firm_id": FIRM, "client_id": A, "entry_date": "2026-10-15"})
    wire_e2e(monkeypatch, db, [sc, pc])
    for mod in (sc, pc):
        monkeypatch.setattr(mod, "_mock", lambda: False)
        monkeypatch.setattr(mod, "_db", lambda: db)
    monkeypatch.setattr(payroll_router, "_db", lambda: db)
    import services.audit_service as audit
    monkeypatch.setattr(audit, "log_event", lambda *a, **k: None)
    return db


TABLES = ("sales_quotations", "sales_orders", "delivery_challans", "purchase_orders", "goods_receipt_notes", "purchase_bills",
          "statutory_remittances", "sales_quotation_lines", "sales_order_lines", "delivery_challan_lines", "purchase_order_lines",
          "goods_receipt_lines")


_DERIVED = {"outstanding_paise", "txn_outstanding"}      # generated columns the double fills in on a read; not a write


def _snapshot(db):
    return {t: [{k: v for k, v in r.items() if k not in _DERIVED} for r in db.rows(t)] for t in TABLES}


def _calls():
    """Each names client A (the caller's own) beside a document that belongs to client B."""
    return [
        ("sales quotation lines", lambda: sc.quotation_lines(QT, client_id=A, current_user=USER), "That quotation was not found."),
        ("sales quotation PATCH", lambda: sc.update_quotation(QT, sc.QuotationUpdateIn(notes="forged"), client_id=A, current_user=USER),
         "That quotation was not found."),
        ("sales order position", lambda: sc.order_position(SO, client_id=A, current_user=USER), "That sales order was not found."),
        ("sales order PATCH", lambda: sc.update_order(SO, sc.SalesOrderUpdateIn(notes="forged"), client_id=A, current_user=USER),
         "That sales order was not found."),
        ("challan particulars", lambda: sc.challan_particulars(DC, client_id=A, current_user=USER), "That delivery challan was not found."),
        ("challan PATCH", lambda: sc.update_challan(DC, sc.DeliveryChallanUpdateIn(received_back_on="2026-06-30"), client_id=A,
                                                    current_user=USER), "That delivery challan was not found."),
        ("purchase order lines", lambda: pc.order_lines(PO, client_id=A, current_user=USER), "That purchase order was not found."),
        ("purchase order position", lambda: pc.order_position(PO, client_id=A, current_user=USER), "That purchase order was not found."),
        ("purchase order PATCH", lambda: pc.update_order(PO, pc.PurchaseOrderUpdateIn(notes="forged"), client_id=A, current_user=USER),
         "That purchase order was not found."),
        ("goods receipt lines", lambda: pc.receipt_lines(GR, client_id=A, current_user=USER), "That goods receipt was not found."),
        ("goods receipt PATCH", lambda: pc.update_receipt(GR, pc.GoodsReceiptUpdateIn(objection_raised_on="2026-06-05"), client_id=A,
                                                          current_user=USER), "That goods receipt was not found."),
        ("bill match", lambda: pc.match_bill(PB, client_id=A, current_user=USER), "That bill was not found."),
        ("remittance link", lambda: payroll_router.link_remittance_payment(A, RM, payroll_router.RemittancePaymentIn(journal_entry_id=JE),
                                                                           current_user=USER), "Remittance not found"),
        ("remittance retract", lambda: payroll_router.retract_remittance(A, RM, current_user=USER), "Remittance not found"),
    ]


@pytest.mark.parametrize("label,call,words", _calls(), ids=[c[0] for c in _calls()])
def test_naming_ones_own_client_beside_another_clients_document_is_a_404_and_changes_nothing(world, label, call, words):
    before = _snapshot(world)
    with pytest.raises(HTTPException) as e:
        call()
    assert (e.value.status_code, e.value.detail) == (404, words), label
    assert _snapshot(world) == before, f"{label} changed a row of the other client"


def test_the_clients_own_documents_are_still_served(world):
    assert sc.quotation_lines(QT, client_id=B, current_user=USER)["success"] is True
    assert sc.order_position(SO, client_id=B, current_user=USER)["success"] is True
    assert sc.challan_particulars(DC, client_id=B, current_user=USER)["success"] is True
    assert pc.order_lines(PO, client_id=B, current_user=USER)["success"] is True
    assert pc.order_position(PO, client_id=B, current_user=USER)["success"] is True
    assert pc.receipt_lines(GR, client_id=B, current_user=USER)["success"] is True
    assert pc.match_bill(PB, client_id=B, current_user=USER)["success"] is True
    out = pc.update_receipt(GR, pc.GoodsReceiptUpdateIn(objection_raised_on="2026-06-05"), client_id=B, current_user=USER)
    assert out["success"] is True
    assert [r["objection_raised_on"] for r in world.rows("goods_receipt_notes")] == ["2026-06-05"]
    out = sc.update_challan(DC, sc.DeliveryChallanUpdateIn(notes="corrected"), client_id=B, current_user=USER)
    assert out["success"] is True
    assert [r["notes"] for r in world.rows("delivery_challans")] == ["corrected"]


def test_a_remittance_is_linked_and_retracted_by_its_own_client(world):
    world.rows("journal_entries")[0]["client_id"] = B
    out = payroll_router.link_remittance_payment(B, RM, payroll_router.RemittancePaymentIn(journal_entry_id=JE), current_user=USER)
    assert out["success"] is True and world.rows("statutory_remittances")[0]["journal_entry_id"] == JE
    out = payroll_router.retract_remittance(B, RM, current_user=USER)
    assert out["success"] is True and world.rows("statutory_remittances")[0]["deleted_at"]


def test_a_payment_cannot_be_linked_to_a_journal_entry_of_another_client(world):
    """The remittance is client B's and the entry is client A's: naming B (so the remittance is found) must not accept A's entry."""
    with pytest.raises(HTTPException) as e:
        payroll_router.link_remittance_payment(B, RM, payroll_router.RemittancePaymentIn(journal_entry_id=JE), current_user=USER)
    assert e.value.status_code == 422 and "not an entry of this client" in e.value.detail
    assert world.rows("statutory_remittances")[0]["journal_entry_id"] is None


def test_the_remittance_service_has_no_default_for_the_client():
    import inspect
    for fn in (rem.link_payment, rem.retract):
        p = inspect.signature(fn).parameters["client_id"]
        assert p.default is inspect.Parameter.empty and p.kind is inspect.Parameter.KEYWORD_ONLY, fn.__name__


# ── the rule over the two routers' own source ────────────────────────────────────────────────────────────────────────
HELPERS = ("row_of_client", "order_of_client", "receipt_of_client", "bill_of_client")


def _calls_a_helper(source: str) -> bool:
    """A real, reachable CALL of one of the helpers, on `svc` (the module the routers import them from), handed the client: a comment,
    a lambda, `if False`, another object's method of the same name and a call that is not given a client do not count."""
    import textwrap
    tree = ast.parse(textwrap.dedent(source))
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}

    def unreachable(node) -> bool:
        while node in parents:
            node = parents[node]
            if isinstance(node, ast.Lambda):
                return True
            if isinstance(node, ast.If) and isinstance(node.test, ast.Constant) and not node.test.value:
                return True
        return False

    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in HELPERS
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "svc"
                and "client_id" in ast.unparse(n) and not unreachable(n)):
            return True
    return False


EXEMPT = {
    ("sales_cycle.py", "record_challan_return"): (
        "the client in the body is asserted AND is what the challan line is looked up under in `itc_04_service.record_return`, "
        "which also checks the path's challan against the line's own (GST-30)"),
}


def _id_handlers(name: str):
    path = pathlib.Path(__file__).resolve().parent.parent / "routers" / name
    src = path.read_text(encoding="utf-8")
    for fn in ast.parse(src).body:
        if not isinstance(fn, ast.FunctionDef):
            continue
        for d in fn.decorator_list:
            if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                    and d.func.attr in ("get", "post", "put", "patch", "delete") and d.args
                    and re.search(r"\{\w+_id\}", str(getattr(d.args[0], "value", "")))):
                yield fn.name, ast.get_source_segment(src, fn)


@pytest.mark.parametrize("router", ["sales_cycle.py", "purchase_cycle.py"])
def test_every_handler_with_a_document_id_in_its_path_ties_the_document_to_the_client(router):
    offenders = sorted(n for n, s in _id_handlers(router)
                       if not _calls_a_helper(s) and (router, n) not in EXEMPT)
    assert not offenders, (
        f"{router}: these handlers take a document id and assert only the client the caller named, then read by firm and id "
        f"through the privileged client: {offenders}. Call the matching `*_of_client` helper before the service.")


def test_the_exemptions_are_still_needed_and_the_rule_is_not_vacuous():
    covered = {r: [n for n, s in _id_handlers(r) if _calls_a_helper(s)] for r in ("sales_cycle.py", "purchase_cycle.py")}
    assert len(covered["sales_cycle.py"]) == 6 and len(covered["purchase_cycle.py"]) == 6, covered
    for (router, name) in EXEMPT:
        handlers = dict(_id_handlers(router))
        assert name in handlers and not _calls_a_helper(handlers[name]), (router, name)


def test_the_helpers_compare_the_documents_client_not_just_its_existence():
    # behaviourally: a document of client B asked for as client A is the same 404 a missing one gives
    db = FakeDB()
    db.seed("sales_quotations", {"id": QT, "firm_id": FIRM, "client_id": B})
    with pytest.raises(HTTPException) as other:
        scs.row_of_client(db, "sales_quotations", FIRM, QT, A, "quotation")
    with pytest.raises(HTTPException) as missing:
        scs.row_of_client(db, "sales_quotations", FIRM, "no-such", A, "quotation")
    assert (other.value.status_code, other.value.detail) == (missing.value.status_code, missing.value.detail)
    assert scs.row_of_client(db, "sales_quotations", FIRM, QT, B, "quotation")["id"] == QT
    db.seed("purchase_orders", {"id": PO, "firm_id": FIRM, "client_id": B})
    with pytest.raises(HTTPException):
        pcs.order_of_client(db, FIRM, PO, A)
    assert pcs.order_of_client(db, FIRM, PO, B)["id"] == PO


def test_the_helper_check_cannot_be_satisfied_by_a_call_that_protects_nothing():
    base = "def f(order_id, client_id):\n    pass\n"
    assert _calls_a_helper(base + "    svc.order_of_client(db, firm, order_id, client_id)\n")
    assert not _calls_a_helper(base + "    # svc.order_of_client(db, firm, order_id, client_id)\n")
    assert not _calls_a_helper(base + "    if False:\n        svc.order_of_client(db, firm, order_id, client_id)\n")
    assert not _calls_a_helper(base + "    g = lambda: svc.order_of_client(db, firm, order_id, client_id)\n")
    assert not _calls_a_helper(base + "    other.order_of_client(db, firm, order_id, client_id)\n")
    assert not _calls_a_helper(base + "    svc.order_of_client(db, firm, order_id, order_id)\n")


# handler -> (the helper it must call, the arguments after `db` and the firm)
WIRING = {
    (sc, "quotation_lines"): ("row_of_client", ("sales_quotations", QT, A, "quotation")),
    (sc, "update_quotation"): ("row_of_client", ("sales_quotations", QT, A, "quotation")),
    (sc, "order_position"): ("row_of_client", ("sales_orders", SO, A, "sales order")),
    (sc, "update_order"): ("row_of_client", ("sales_orders", SO, A, "sales order")),
    (sc, "challan_particulars"): ("row_of_client", ("delivery_challans", DC, A, "delivery challan")),
    (sc, "update_challan"): ("row_of_client", ("delivery_challans", DC, A, "delivery challan")),
    (pc, "order_lines"): ("order_of_client", (PO, A)),
    (pc, "order_position"): ("order_of_client", (PO, A)),
    (pc, "update_order"): ("order_of_client", (PO, A)),
    (pc, "receipt_lines"): ("receipt_of_client", (GR, A)),
    (pc, "update_receipt"): ("receipt_of_client", (GR, A)),
    (pc, "match_bill"): ("bill_of_client", (PB, A)),
}


def _drive(mod, name):
    fn = getattr(mod, name)
    ids = {"quotation_lines": QT, "update_quotation": QT, "order_position": SO if mod is sc else PO, "update_order": SO if mod is sc else PO,
           "challan_particulars": DC, "update_challan": DC, "order_lines": PO, "receipt_lines": GR, "update_receipt": GR, "match_bill": PB}
    args = [ids[name]]
    models = {(sc, "update_quotation"): sc.QuotationUpdateIn(), (sc, "update_order"): sc.SalesOrderUpdateIn(),
              (sc, "update_challan"): sc.DeliveryChallanUpdateIn(), (pc, "update_order"): pc.PurchaseOrderUpdateIn(),
              (pc, "update_receipt"): pc.GoodsReceiptUpdateIn()}
    if (mod, name) in models:
        args.append(models[(mod, name)])
    return fn(*args, client_id=A, current_user=USER)


@pytest.mark.parametrize("key", list(WIRING), ids=[f"{m.__name__.split('.')[-1]}.{n}" for m, n in WIRING])
def test_each_route_asks_the_helper_about_the_document_and_the_client_it_was_given(world, monkeypatch, key):
    """A wrong argument (the id where the client goes) would 404 the client's OWN document, which no negative case above can see."""
    mod, name = key
    helper, want = WIRING[key]
    seen = []

    def spy(db, *args):
        # sales: (table, firm_id, row_id, client_id, what); purchase: (firm_id, id, client_id): keep what follows the firm
        seen.append(args[:1] + args[2:] if mod is sc else args[1:])
        raise HTTPException(status_code=404, detail="stop")

    monkeypatch.setattr(scs if mod is sc else pcs, helper, spy)
    with pytest.raises(HTTPException):
        _drive(mod, name)
    assert seen == [want], (name, seen)


def test_a_retracted_remittance_and_a_retracted_ecr_filing_carry_a_real_instant(world):
    """`deleted_at` is a timestamptz: a bare date is stored as midnight in the session's zone, an instant nobody chose (the test double
    refuses such a write, and the stored value is asserted here to carry a time and an offset)."""
    from services import epfo_ecr_filing_service as ecr
    world.seed("epfo_ecr_filings", {"id": "f0000000-0000-0000-0000-00000000000f", "firm_id": FIRM, "client_id": B, "deleted_at": None})
    assert rem.retract(world, firm_id=FIRM, client_id=B, remittance_id=RM)
    assert ecr.retract_filing(world, firm_id=FIRM, filing_id="f0000000-0000-0000-0000-00000000000f")
    for table in ("statutory_remittances", "epfo_ecr_filings"):
        stored = str(world.rows(table)[0]["deleted_at"])
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:\d{2}|Z)", stored), (table, stored)


def test_a_payment_cannot_be_linked_to_a_deleted_journal_entry(world):
    world.rows("journal_entries")[0].update({"client_id": B, "deleted_at": "2026-10-20T00:00:00+05:30"})
    with pytest.raises(rem.RemittanceError):
        rem.link_payment(world, firm_id=FIRM, client_id=B, remittance_id=RM, journal_entry_id=JE)
    assert world.rows("statutory_remittances")[0]["journal_entry_id"] is None


def test_the_helpers_compare_client_ids_without_regard_to_case(world):
    assert scs.row_of_client(world, "sales_quotations", FIRM, QT, B.upper(), "quotation")["id"] == QT
    assert pcs.order_of_client(world, FIRM, PO, B.upper())["id"] == PO
    assert pcs.receipt_of_client(world, FIRM, GR, B.upper())["id"] == GR
    assert pcs.bill_of_client(world, FIRM, PB, B.upper())["id"] == PB
