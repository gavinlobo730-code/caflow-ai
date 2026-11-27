"""
Task #227 finding #5 — issuing a credit/debit note applies its effect to the
linked invoice/bill's sub-ledger paise field (credited_paise / debit_note_paise
/ credit_note_paise / debited_paise) with a plain read-then-write and NO
compare-and-set guard — unlike every other money-movement write path in this
codebase (receipts._adjust_invoice_paid, reversal_service's rollback helpers,
purchase_payments._claim_bill_outstanding), which are all CAS-guarded for
exactly this reason. Two credit/debit notes issued concurrently against the
SAME invoice/bill could both read the same stale paise value, both pass their
own outstanding check against that stale snapshot, and the second write
silently clobbers the first — a lost update, even though both notes' own rows
end up "issued" with journals posted.

Each of the 4 note types is proven with a deterministic single-collision
test: a monkeypatched execute() simulates a concurrent writer landing its own
update on the invoice/bill in the gap between this request's read and its
own write — the exact interleaving a CAS guard exists to survive. (A
real-thread barrier was tried first but proved unreliable here: under the
GIL, both racing requests' brief read-then-write windows tend to run
back-to-back rather than genuinely interleaved, so it didn't reliably
reproduce the lost update — the deterministic simulation does.)
"""
from models.parties import CustomerIn, VendorIn
from models.invoices import SalesInvoiceIn, InvoiceLineIn, PurchaseBillIn, PurchaseBillLineIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa, _Query

FIRM = "FIRM-R227-5"
CALLER = {"firm_id": FIRM, "id": "u1", "auth_user_id": "u1", "email": "ca@f.test", "role": "Partner"}


def _setup(monkeypatch):
    import routers.customers as cu
    import routers.vendors as ve
    import routers.sales_invoices as si
    import routers.purchase_bills as pb
    import routers.credit_notes as cn
    import routers.sales_debit_notes as sdn
    import routers.purchase_credit_notes as pcn
    import routers.debit_notes as dn
    db = FakeDB()
    wire_e2e(monkeypatch, db, [cu, ve, si, pb, cn, sdn, pcn, dn])
    db.seed("firms", {"id": FIRM})
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Services", "kind": "service"})
    return cu, ve, si, pb, cn, sdn, pcn, dn, db


def _invoice(si, cust_id, rate_paise=1_000_000, invoice_no="INV-1"):
    inv = si.create_invoice(SalesInvoiceIn(
        client_id="CLI", customer_id=cust_id, invoice_date="2026-06-01", invoice_no=invoice_no,
        lines=[InvoiceLineIn(service_catalogue_id="SVC-1", description="Svc", hsn_sac="9982", quantity=1,
                             rate_paise=rate_paise, gst_rate_percent=0.0)]), CALLER)["data"]
    si.issue_invoice(inv["id"], CALLER)
    return inv


def _bill(pb, vend_id, rate_paise=1_000_000, bill_no="BILL-1"):
    bill = pb.create_purchase_bill(PurchaseBillIn(
        client_id="CLI", vendor_id=vend_id, bill_date="2026-06-01", bill_no=bill_no,
        lines=[PurchaseBillLineIn(service_catalogue_id="SVC-1", description="svc", rate_paise=rate_paise,
                                  quantity=1, gst_rate_percent=0.0)]), CALLER)["data"]
    pb.receive_purchase_bill(bill["id"], CALLER)
    return bill


def _draft_credit_note(cn, client_id, cust_id, inv_id, amount):
    res = cn.create_credit_note(cn.CreditNoteIn(
        client_id=client_id, customer_id=cust_id, sales_invoice_id=inv_id,
        credit_note_date="2026-06-10", reason="Return",
        lines=[InvoiceLineIn(description="return", quantity=1, rate_paise=amount,
                             gst_rate_percent=0.0, service_catalogue_id="SVC-1")],
    ), CALLER)
    assert res["success"] is True
    return res["data"]


def test_credit_note_cas_retries_on_stale_write(monkeypatch):
    """A single simulated CAS collision (not a full thread race — see module
    docstring) proves the retry loop actually retries against fresh state
    instead of silently losing the concurrent writer's update."""
    cu, ve, si, pb, cn, sdn, pcn, dn, db = _setup(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="Acme", state_code="27"), CALLER)["data"]
    inv = _invoice(si, cust["id"], rate_paise=2_000_000)
    note = _draft_credit_note(cn, "CLI", cust["id"], inv["id"], 100_000)

    # Simulate a concurrent writer landing credited_paise=200000 on the
    # invoice AFTER this request's first read but BEFORE its first CAS write.
    real_execute = _Query.execute
    state = {"first_select_done": False}

    def racy_execute(self):
        if (self.table == "client_sales_invoices" and self._op == "select"
                and not state["first_select_done"]):
            state["first_select_done"] = True
            result = real_execute(self)
            db.table("client_sales_invoices").update({"credited_paise": 200_000}).eq("id", inv["id"]).execute()
            return result
        return real_execute(self)

    monkeypatch.setattr(_Query, "execute", racy_execute)

    result = cn.issue_credit_note(note["id"], CALLER)
    assert result["success"] is True

    inv_row = db.table("client_sales_invoices").select("*").eq("id", inv["id"]).execute().data[0]
    # Must reflect BOTH the concurrent writer's 200000 AND this note's own
    # 100000 — a lost update would show only 100000 (this write clobbering
    # the concurrent one) or only 200000 (this write silently no-op'd).
    assert inv_row["credited_paise"] == 300_000


def test_sales_debit_note_cas_retries_on_stale_write(monkeypatch):
    """A single simulated CAS collision (not a full thread race) proves the
    retry loop actually retries against fresh state instead of silently
    losing the concurrent writer's update."""
    cu, ve, si, pb, cn, sdn, pcn, dn, db = _setup(monkeypatch)
    cust = cu.create_customer(CustomerIn(client_id="CLI", name="Acme", state_code="27"), CALLER)["data"]
    inv = _invoice(si, cust["id"], rate_paise=2_000_000)
    note_res = sdn.create_sales_debit_note(sdn.SalesDebitNoteIn(
        client_id="CLI", customer_id=cust["id"], sales_invoice_id=inv["id"],
        debit_note_date="2026-06-10", reason="Undercharge",
        lines=[InvoiceLineIn(description="undercharge", quantity=1, rate_paise=100_000,
                             gst_rate_percent=0.0, service_catalogue_id="SVC-1")],
    ), CALLER)
    assert note_res["success"] is True
    note = note_res["data"]

    # Simulate a concurrent writer landing debit_note_paise=200000 on the
    # invoice AFTER this request's first read but BEFORE its first CAS write.
    real_execute = _Query.execute
    state = {"first_select_done": False}

    def racy_execute(self):
        if (self.table == "client_sales_invoices" and self._op == "select"
                and not state["first_select_done"]):
            state["first_select_done"] = True
            result = real_execute(self)
            db.table("client_sales_invoices").update({"debit_note_paise": 200_000}).eq("id", inv["id"]).execute()
            return result
        return real_execute(self)

    monkeypatch.setattr(_Query, "execute", racy_execute)

    result = sdn.issue_sales_debit_note(note["id"], CALLER)
    assert result["success"] is True

    inv_row = db.table("client_sales_invoices").select("*").eq("id", inv["id"]).execute().data[0]
    # Must reflect BOTH the concurrent writer's 200000 AND this note's own
    # 100000 — a lost update would show only 100000 (this write clobbering
    # the concurrent one) or only 200000 (this write silently no-op'd).
    assert inv_row["debit_note_paise"] == 300_000


def test_purchase_credit_note_cas_retries_on_stale_write(monkeypatch):
    cu, ve, si, pb, cn, sdn, pcn, dn, db = _setup(monkeypatch)
    vend = ve.create_vendor(VendorIn(client_id="CLI", name="Acme Supplies", state_code="27"), CALLER)["data"]
    bill = _bill(pb, vend["id"], rate_paise=2_000_000)
    note_res = pcn.create_purchase_credit_note(pcn.PurchaseCreditNoteIn(
        client_id="CLI", vendor_id=vend["id"], purchase_bill_id=bill["id"],
        credit_note_date="2026-06-10", reason="Return",
        lines=[InvoiceLineIn(description="return", quantity=1, rate_paise=100_000,
                             gst_rate_percent=0.0, service_catalogue_id="SVC-1")],
    ), CALLER)
    assert note_res["success"] is True
    note = note_res["data"]

    real_execute = _Query.execute
    state = {"first_select_done": False}

    def racy_execute(self):
        if (self.table == "purchase_bills" and self._op == "select"
                and not state["first_select_done"]):
            state["first_select_done"] = True
            result = real_execute(self)
            db.table("purchase_bills").update({"credit_note_paise": 200_000}).eq("id", bill["id"]).execute()
            return result
        return real_execute(self)

    monkeypatch.setattr(_Query, "execute", racy_execute)

    result = pcn.issue_purchase_credit_note(note["id"], CALLER)
    assert result["success"] is True

    bill_row = db.table("purchase_bills").select("*").eq("id", bill["id"]).execute().data[0]
    assert bill_row["credit_note_paise"] == 300_000


def test_debit_note_cas_retries_on_stale_write(monkeypatch):
    cu, ve, si, pb, cn, sdn, pcn, dn, db = _setup(monkeypatch)
    vend = ve.create_vendor(VendorIn(client_id="CLI", name="Acme Supplies", state_code="27"), CALLER)["data"]
    bill = _bill(pb, vend["id"], rate_paise=2_000_000)
    note_res = dn.create_debit_note(dn.DebitNoteIn(
        client_id="CLI", vendor_id=vend["id"], purchase_bill_id=bill["id"],
        debit_note_date="2026-06-10", reason="Overcharge",
        lines=[InvoiceLineIn(description="overcharge", quantity=1, rate_paise=100_000,
                             gst_rate_percent=0.0, service_catalogue_id="SVC-1")],
    ), CALLER)
    assert note_res["success"] is True
    note = note_res["data"]

    real_execute = _Query.execute
    state = {"first_select_done": False}

    def racy_execute(self):
        if (self.table == "purchase_bills" and self._op == "select"
                and not state["first_select_done"]):
            state["first_select_done"] = True
            result = real_execute(self)
            db.table("purchase_bills").update({"debited_paise": 200_000}).eq("id", bill["id"]).execute()
            return result
        return real_execute(self)

    monkeypatch.setattr(_Query, "execute", racy_execute)

    result = dn.issue_debit_note(note["id"], CALLER)
    assert result["success"] is True

    bill_row = db.table("purchase_bills").select("*").eq("id", bill["id"]).execute().data[0]
    assert bill_row["debited_paise"] == 300_000
