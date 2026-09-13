"""GST compensation cess, end to end (PUR-20, SALES-20).

`domain/gst/compensation_cess.py` is the arithmetic and is pinned to the
browser mirror by shared/gst-parity-vectors.json
(tests/test_gst_parity_vectors.py). These are about the four things a domain
test cannot see:

  * that the sales-invoice and purchase-bill CREATE paths compute the cess,
    write both rate limbs and the amount to the line, and total it onto the
    header — a rate the router discards is the whole defect PUR-20 describes,
    in a new place;
  * that it reaches the PAYABLE and not `total_gst_paise`. GST (Compensation
    to States) Act 2017 s.11(2), proviso: credit of this cess "shall be
    utilised only towards payment of cess", so folding it into the GST figure
    would offer it to the s.49(5) set-off ladder in Table 6;
  * that the JOURNAL posts it to its own ledger and still FOOTS. Adding cess
    to the payable with no matching leg is the one way this change could break
    a trial balance that has always balanced;
  * that s.17(5) reaches it on a purchase — a blocked line's cess is a cost,
    exactly as its GST is (PUR-04's reasoning, applied by s.11(2)).
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

_API_ROOT = os.path.join(os.path.dirname(__file__), "..")
if _API_ROOT not in sys.path:
    sys.path.insert(0, _API_ROOT)

from routers import purchase_bills, sales_invoices              # noqa: E402
from models.invoices import (                                    # noqa: E402
    PurchaseBillIn, PurchaseBillLineIn, SalesInvoiceIn, SalesInvoiceLineIn,
)

_USER = {"firm_id": "F1", "auth_user_id": "u1", "email": "u@firm.test", "role": "Partner"}


# ── a recording fake Supabase, the same shape test_sales_invoice_lines_fk uses ──

class _Resp:
    def __init__(self, data=None, count=None):
        self.data = data
        self.count = count


class _Query:
    def __init__(self, table, recorder, controller):
        self._table, self._rec, self._ctl = table, recorder, controller
        self._op, self._payload, self._count = "select", None, None
        self._filters: dict = {}

    def select(self, *a, **k):
        self._op = "select"
        self._count = k.get("count")
        return self

    def insert(self, payload):
        self._op, self._payload = "insert", payload
        return self

    def update(self, payload):
        self._op, self._payload = "update", payload
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def neq(self, *a, **k): return self
    def gte(self, *a, **k): return self
    def lte(self, *a, **k): return self
    def gt(self, *a, **k): return self
    def like(self, *a, **k): return self
    def is_(self, *a, **k): return self
    def ilike(self, *a, **k): return self
    def or_(self, *a, **k): return self
    def in_(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def order(self, *a, **k): return self
    def range(self, *a, **k): return self
    def maybe_single(self): return self

    def execute(self):
        event = {"table": self._table, "op": self._op, "payload": self._payload,
                 "filters": dict(self._filters), "count": self._count}
        self._rec.append(event)
        return self._ctl(event)


class _FakeDB:
    def __init__(self, recorder, controller):
        self._rec, self._ctl = recorder, controller

    def table(self, name):
        return _Query(name, self._rec, self._ctl)

    def rpc(self, fn, params=None):
        # The period lock fails CLOSED, so a fake that cannot answer makes
        # every period look shut. Nothing is seeded, so answer as an empty
        # database does: open.
        return type("R", (), {"execute": lambda self: _Resp(data=None)})()


# ── sales invoice ───────────────────────────────────────────────────────────

@pytest.fixture
def sales_db(monkeypatch):
    recorder: list[dict] = []
    holder = {"controller": lambda e: _Resp(data=[])}
    monkeypatch.setattr(sales_invoices, "_USE_MOCK", False)
    monkeypatch.setattr("core.supabase_client.get_supabase",
                        lambda: _FakeDB(recorder, holder["controller"]))
    monkeypatch.setattr(sales_invoices.period_validation_service,
                        "validate_posting_date", lambda *a, **k: None)
    monkeypatch.setattr(sales_invoices, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(sales_invoices.timeline_service, "log", lambda *a, **k: None)
    return recorder, holder


def _sales_controller(event):
    """Customer and client both in state 27 → intra-state (CGST + SGST)."""
    t, op = event["table"], event["op"]
    if t == "customers" and op == "select":
        return _Resp(data=[{"state_code": "27", "gstin": "27AABCU9603R1ZM"}])
    if t == "clients" and op == "select":
        return _Resp(data=[{"gstin": "27AAAAA0000A1Z2", "state_code": "27"}])
    if t == "client_sales_invoices" and op == "select" and event["count"] == "exact":
        return _Resp(data=[], count=0)
    if t == "client_sales_invoices" and op == "insert":
        return _Resp(data=[{**event["payload"], "id": "INV-CESS-1"}])
    if t == "client_sales_invoice_lines" and op == "insert":
        return _Resp(data=[{**r, "id": f"L{i}"} for i, r in enumerate(event["payload"])])
    return _Resp(data=[])


def _sales_payload(**line_kwargs):
    # Rs.1,000.00 at 28% GST — the slab cess goods actually sit in.
    return SalesInvoiceIn(
        client_id="C1", customer_id="CUST1", invoice_no="CESS-0001",
        invoice_date="2026-06-19",
        lines=[SalesInvoiceLineIn(
            service_catalogue_id="SVC-1", description="Aerated waters",
            hsn_sac="22021010", rate_paise=100_000, quantity=1,
            gst_rate_percent=28.0, **line_kwargs)],
    )


def _created(recorder, table):
    return [e for e in recorder if e["table"] == table and e["op"] == "insert"]


def test_the_ad_valorem_cess_the_CA_types_reaches_the_line_and_the_header(sales_db):
    recorder, holder = sales_db
    holder["controller"] = _sales_controller

    resp = sales_invoices.create_invoice(_sales_payload(cess_rate_bps=1200), _USER)
    assert resp["success"] is True
    inv = resp["data"]

    # 12% of Rs.1,000 = Rs.120.
    assert inv["cess_paise"] == 12_000
    line = _created(recorder, "client_sales_invoice_lines")[0]["payload"][0]
    assert line["cess_rate_bps"] == 1200
    assert line["cess_specific_paise_per_unit"] == 0
    assert line["cess_paise"] == 12_000
    # The line's own total carries it, because the customer pays it.
    assert line["line_total_paise"] == 100_000 + 28_000 + 12_000


def test_the_specific_limb_is_per_unit_of_the_lines_own_quantity(sales_db):
    recorder, holder = sales_db
    holder["controller"] = _sales_controller

    # Rs.400 per tonne on 2.5 tonnes = Rs.1,000. Compensation Act s.8(2),
    # "on the basis of ... quantity".
    payload = SalesInvoiceIn(
        client_id="C1", customer_id="CUST1", invoice_no="CESS-0002",
        invoice_date="2026-06-19",
        lines=[SalesInvoiceLineIn(
            service_catalogue_id="SVC-1", description="Coal", hsn_sac="27011200",
            rate_paise=500_000, quantity=2.5, unit="TON", gst_rate_percent=5.0,
            cess_specific_paise_per_unit=40_000)],
    )
    resp = sales_invoices.create_invoice(payload, _USER)
    assert resp["success"] is True
    assert resp["data"]["cess_paise"] == 100_000


def test_both_limbs_are_added_and_not_compared(sales_db):
    recorder, holder = sales_db
    holder["controller"] = _sales_controller

    # Cigarettes: 5% of value PLUS a figure per thousand. A max() would
    # under-charge by whichever limb it discarded.
    payload = SalesInvoiceIn(
        client_id="C1", customer_id="CUST1", invoice_no="CESS-0003",
        invoice_date="2026-06-19",
        lines=[SalesInvoiceLineIn(
            service_catalogue_id="SVC-1", description="Cigarettes",
            hsn_sac="24022010", rate_paise=1_000, quantity=1000,
            gst_rate_percent=28.0, cess_rate_bps=500,
            cess_specific_paise_per_unit=207)],
    )
    resp = sales_invoices.create_invoice(payload, _USER)
    assert resp["data"]["cess_paise"] == 50_000 + 207_000


def test_the_cess_is_in_the_payable_and_out_of_the_gst_figure(sales_db):
    """s.11(2), proviso: cess credit pays only cess. `total_gst_paise` is what
    GSTR-3B Table 6 sets off under s.49(5), so putting cess there would assert
    an offset the electronic credit ledger refuses."""
    recorder, holder = sales_db
    holder["controller"] = _sales_controller

    inv = sales_invoices.create_invoice(_sales_payload(cess_rate_bps=1200), _USER)["data"]
    assert inv["total_gst_paise"] == 28_000            # the three s.9 heads only
    assert inv["cess_paise"] == 12_000
    assert inv["total_paise"] == 100_000 + 28_000 + 12_000
    assert inv["total_paise"] == (inv["taxable_amount_paise"] + inv["total_gst_paise"]
                                  + inv["cess_paise"] + inv["round_off_paise"])


def test_an_invoice_with_no_cess_is_byte_for_byte_what_it_always_was(sales_db):
    recorder, holder = sales_db
    holder["controller"] = _sales_controller

    inv = sales_invoices.create_invoice(_sales_payload(), _USER)["data"]
    assert inv["cess_paise"] == 0
    assert inv["total_paise"] == 128_000
    line = _created(recorder, "client_sales_invoice_lines")[0]["payload"][0]
    assert (line["cess_rate_bps"], line["cess_specific_paise_per_unit"],
            line["cess_paise"]) == (0, 0, 0)


def test_the_cess_is_charged_on_the_value_after_the_section_15_3_a_discount(sales_db):
    """s.11(1) of the Compensation Act applies CGST s.15 to this levy, so the
    base is the value of supply — what is left after a discount recorded in
    the invoice, not the gross."""
    recorder, holder = sales_db
    holder["controller"] = _sales_controller

    payload = _sales_payload(cess_rate_bps=1200, discount_percent_bps=1000)  # 10% off
    inv = sales_invoices.create_invoice(payload, _USER)["data"]
    assert inv["taxable_amount_paise"] == 90_000
    assert inv["cess_paise"] == 10_800          # 12% of 90,000, not of 1,00,000


@pytest.mark.parametrize("model", [SalesInvoiceLineIn, PurchaseBillLineIn])
@pytest.mark.parametrize("field", ["cess_rate_bps", "cess_specific_paise_per_unit"])
def test_a_negative_cess_rate_is_refused_at_the_model(model, field):
    """Both models and both limbs. Parametrised because the two classes carry
    their own copy of the validator — a negative control mutating only
    PurchaseBillLineIn's passed while the sales-only test watched."""
    with pytest.raises(Exception):
        model(service_catalogue_id="S", description="x", rate_paise=100,
              **{field: -1})


def test_the_cess_rate_has_no_upper_bound_because_the_schedule_has_none():
    """Schedule column (4) carries entries well above 100% — unmanufactured
    tobacco, the pan-masala entries — so a ceiling written from intuition
    would refuse a lawful charge."""
    for model in (SalesInvoiceLineIn, PurchaseBillLineIn):
        assert model(service_catalogue_id="S", description="x", rate_paise=100,
                     cess_rate_bps=29_000).cess_rate_bps == 29_000


def test_editing_a_draft_keeps_the_cess_in_the_total(sales_db):
    """The EDIT path recomputes every figure from the lines it is sent, and
    `update_invoice` deletes and reinserts them — so a cess the edit path
    dropped would silently reduce the invoice on the next save of an invoice
    nobody meant to change. A negative control on the create path alone
    passed while the edit path's total omitted the cess."""
    recorder, holder = sales_db
    stored = {"id": "INV-CESS-1", "client_id": "C1", "status": "draft",
              "is_interstate": False, "txn_currency": "INR", "exchange_rate": "1",
              "round_off_enabled": False, "discount_paise": 0}

    def _edit_controller(event):
        t, op = event["table"], event["op"]
        if t == "client_sales_invoices" and op == "select":
            return _Resp(data=[stored])
        if t == "client_sales_invoices" and op == "update":
            stored.update(event["payload"])
            return _Resp(data=[stored])
        return _sales_controller(event)

    holder["controller"] = _edit_controller
    from models.invoices import SalesInvoiceUpdateIn

    resp = sales_invoices.update_invoice("INV-CESS-1", SalesInvoiceUpdateIn(
        lines=[SalesInvoiceLineIn(
            service_catalogue_id="SVC-1", description="Aerated waters",
            hsn_sac="22021010", rate_paise=100_000, quantity=1,
            gst_rate_percent=28.0, cess_rate_bps=1200)]), _USER)
    assert resp["success"] is True

    updates = [e for e in recorder
               if e["table"] == "client_sales_invoices" and e["op"] == "update"]
    assert updates, "the header must be rewritten"
    payload = updates[-1]["payload"]
    assert payload["cess_paise"] == 12_000
    assert payload["total_gst_paise"] == 28_000
    assert payload["total_paise"] == 140_000

    line = _created(recorder, "client_sales_invoice_lines")[-1]["payload"][0]
    assert line["cess_rate_bps"] == 1200
    assert line["cess_paise"] == 12_000


def test_the_note_models_have_no_cess_field():
    """Migration 374 covers the invoice and the bill; the four s.34 note tables
    have no cess column. A field the note path accepted and then dropped would
    let a CA believe they had reversed a charge they had not."""
    from models.invoices import InvoiceLineIn
    assert "cess_rate_bps" not in InvoiceLineIn.model_fields
    assert "cess_specific_paise_per_unit" not in InvoiceLineIn.model_fields


# ── purchase bill ───────────────────────────────────────────────────────────

@pytest.fixture
def bill_db(monkeypatch):
    recorder: list[dict] = []
    holder = {"controller": lambda e: _Resp(data=[])}
    monkeypatch.setattr(purchase_bills, "_USE_MOCK", False)
    monkeypatch.setattr("core.supabase_client.get_supabase",
                        lambda: _FakeDB(recorder, holder["controller"]))
    monkeypatch.setattr(purchase_bills.period_validation_service,
                        "validate_posting_date_cached", lambda *a, **k: None)
    monkeypatch.setattr(purchase_bills.period_lock_service, "assert_open",
                        lambda *a, **k: None)
    monkeypatch.setattr(purchase_bills, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(purchase_bills.timeline_service, "log", lambda *a, **k: None)
    return recorder, holder


def _bill_controller(event):
    """Vendor and client both in state 27 → intra-state, and no TDS."""
    t, op = event["table"], event["op"]
    if t == "vendors" and op == "select":
        return _Resp(data=[{"id": "V1", "client_id": "C1", "state_code": "27",
                            "gstin": "27AABCU9603R1ZM", "tds_applicable": False}])
    if t == "clients" and op == "select":
        return _Resp(data=[{"gstin": "27AAAAA0000A1Z2", "state_code": "27"}])
    if t == "purchase_bills" and op == "insert":
        return _Resp(data=[{**event["payload"], "id": "BILL-CESS-1"}])
    if t == "purchase_bill_lines" and op == "insert":
        return _Resp(data=[{**r, "id": f"L{i}"} for i, r in enumerate(event["payload"])])
    return _Resp(data=[])


def _bill_payload(*, reverse_charge=False, **line_kwargs):
    return PurchaseBillIn(
        client_id="C1", vendor_id="V1", bill_no="VBILL-1",
        bill_date="2026-06-19", is_reverse_charge=reverse_charge,
        lines=[PurchaseBillLineIn(
            service_catalogue_id="SVC-1", description="Aerated waters",
            hsn_sac="22021010", rate_paise=100_000, quantity=1,
            gst_rate_percent=28.0, **line_kwargs)],
    )


def test_the_cess_on_a_bill_reaches_the_line_the_header_and_the_payable(bill_db):
    recorder, holder = bill_db
    holder["controller"] = _bill_controller

    resp = purchase_bills.create_purchase_bill(_bill_payload(cess_rate_bps=1200), _USER)
    assert resp["success"] is True
    bill = resp["data"]

    assert bill["cess_paise"] == 12_000
    assert bill["total_gst_paise"] == 28_000
    assert bill["total_paise"] == 140_000
    # No TDS on this vendor, so the vendor is owed the whole of it.
    assert bill["net_payable_paise"] == 140_000
    line = _created(recorder, "purchase_bill_lines")[0]["payload"][0]
    assert line["cess_rate_bps"] == 1200
    assert line["cess_paise"] == 12_000


def test_a_blocked_line_puts_its_cess_in_the_ineligible_column(bill_db):
    """CGST s.17(5), reaching this levy through s.11(2) of the Compensation
    Act. Migration 240 added `ineligible_itc_cess_paise` and nothing has ever
    written to it, because no cess could be recorded to be blocked."""
    recorder, holder = bill_db
    holder["controller"] = _bill_controller

    bill = purchase_bills.create_purchase_bill(
        _bill_payload(cess_rate_bps=1200, itc_eligible=False,
                      blocked_credit_reason="s.17(5)(b) — food and beverages"),
        _USER)["data"]

    assert bill["cess_paise"] == 12_000
    assert bill["ineligible_itc_cess_paise"] == 12_000
    # And the bill is still owed in full — eligibility changes the CLAIM, not
    # the amount payable.
    assert bill["total_paise"] == 140_000


def test_an_eligible_line_leaves_the_ineligible_cess_at_nil(bill_db):
    recorder, holder = bill_db
    holder["controller"] = _bill_controller
    bill = purchase_bills.create_purchase_bill(
        _bill_payload(cess_rate_bps=1200), _USER)["data"]
    assert bill["ineligible_itc_cess_paise"] == 0


def test_a_reverse_charge_bill_owes_the_vendor_no_cess_but_still_records_it(bill_db):
    """CGST s.9(3)/(4) with s.11(2): the vendor invoices without tax of any
    head, so the cess is not part of what they are owed — but it is
    self-assessed, so it stays on the bill for Table 3.1(d), the credit and
    the journal.

    The LINE total is asserted as well as the header, and that is not
    belt-and-braces: the header takes `total_taxable` outright on an RCM bill,
    so a `line_total_paise` that wrongly carried the cess would leave the
    header right and every per-line figure the CA reads — the editor's Amount
    column, the bill view — overstated. A negative control proved nothing
    caught it.
    """
    recorder, holder = bill_db
    holder["controller"] = _bill_controller

    bill = purchase_bills.create_purchase_bill(
        _bill_payload(reverse_charge=True, cess_rate_bps=1200), _USER)["data"]

    assert bill["cess_paise"] == 12_000
    assert bill["total_paise"] == 100_000        # taxable only
    assert bill["net_payable_paise"] == 100_000
    line = _created(recorder, "purchase_bill_lines")[0]["payload"][0]
    assert line["cess_paise"] == 12_000, "the self-assessed cess is still recorded"
    assert line["line_total_paise"] == 100_000, (
        "on a reverse-charge bill the vendor charged no tax of any head, so the "
        "line owes the taxable value alone")


def test_a_bill_with_no_cess_is_byte_for_byte_what_it_always_was(bill_db):
    recorder, holder = bill_db
    holder["controller"] = _bill_controller
    bill = purchase_bills.create_purchase_bill(_bill_payload(), _USER)["data"]
    assert bill["cess_paise"] == 0
    assert bill["ineligible_itc_cess_paise"] == 0
    assert bill["total_paise"] == 128_000


# ── the journal ─────────────────────────────────────────────────────────────
#
# The invariant this half exists for: the entry must still FOOT. Adding cess to
# the payable with no matching leg is the one way this change could break a
# trial balance that has always balanced, and `_create_journal` asserts double
# entry, so a missing leg surfaces as a refusal rather than a wrong statement —
# which is worse for the CA meeting it than for the test finding it.

_LEDGERS = {
    "ar": "ACC-AR", "revenue": "ACC-REV", "gst_cgst": "ACC-GSTOUT",
    "gst_sgst": "ACC-GSTOUT", "gst_igst": "ACC-GSTOUT",
    "gst_cess_output": "ACC-CESSOUT", "gst_cess_input": "ACC-CESSIN",
    "gst_input": "ACC-GSTIN", "ap": "ACC-AP", "tds_payable": "ACC-TDS",
    "round_off": "ACC-ROUND",
}
_BY_PATTERN = {
    "%Trade Receivable%": "ACC-AR", "%Sales%": "ACC-REV",
    "%GST Output%": "ACC-GSTOUT", "%GST Input%": "ACC-GSTIN",
    "%Trade Payable%": "ACC-AP", "%TDS Payable%": "ACC-TDS",
    "%Purchase%": "ACC-PURCH", "%Expense%": "ACC-PURCH",
    "%Round Off%": "ACC-ROUND",
    "%Compensation Cess Payable%": "ACC-CESSOUT",
    "%Compensation Cess Input%": "ACC-CESSIN",
}


def _journal_svc():
    """A Phase2JournalService forced out of mock mode. Reloaded back to the
    ambient environment in `teardown_module`, because patch.dict restores
    os.environ and NOT the reloaded module — the leak
    test_phase2_journal_key_resolution records."""
    with patch.dict(os.environ, {"SUPABASE_URL": "https://mock.supabase.co"}):
        import importlib
        import services.phase2_journal_service as mod
        importlib.reload(mod)
        return mod.Phase2JournalService()


def teardown_module(_module):
    import importlib
    import services.phase2_journal_service as mod
    importlib.reload(mod)


class _AccountAwareDB:
    """Resolves chart_of_accounts by system_account_key or ILIKE pattern, so a
    posting can be asserted by WHICH LEDGER it hit rather than by call order.
    Everything else answers empty and records what was inserted."""

    def __init__(self, line_rows=None):
        self.inserted: dict[str, list] = {}
        self.line_rows = line_rows or []
        self.posted_lines: list[dict] = []

    def table(self, name):
        return _AccountQuery(name, self)

    def rpc(self, fn, params=None):
        # The kernel posts through `post_journal_atomic` (migration 152), not
        # through two inserts — there is deliberately no fallback, so a fake
        # without this captures nothing and every posting test fails on an
        # empty entry id rather than on what it meant to assert.
        if fn == "post_journal_atomic" and params:
            self.posted_lines.extend(params.get("p_lines") or [])
            return type("R", (), {"execute": lambda _self: _Resp(data="JNL-1")})()
        return type("R", (), {"execute": lambda _self: _Resp(data=None)})()


class _AccountQuery:
    def __init__(self, table, db):
        self.table_name, self.db = table, db
        self.op, self.payload = "select", None
        self.key = None
        self.pattern = None

    def select(self, *a, **k): self.op = "select"; return self
    def insert(self, payload): self.op, self.payload = "insert", payload; return self
    def update(self, payload): self.op, self.payload = "update", payload; return self
    def delete(self): self.op = "delete"; return self

    def eq(self, col, val):
        if col == "system_account_key":
            self.key = val
        return self

    def ilike(self, col, pattern):
        self.pattern = pattern
        return self

    def or_(self, *a, **k): return self
    def is_(self, *a, **k): return self
    def in_(self, *a, **k): return self
    def neq(self, *a, **k): return self
    def gte(self, *a, **k): return self
    def lte(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def order(self, *a, **k): return self
    def maybe_single(self): return self

    def execute(self):
        if self.table_name == "chart_of_accounts":
            acc = _LEDGERS.get(self.key or "") or _BY_PATTERN.get(self.pattern or "")
            return _Resp(data=[{"id": acc}] if acc else [])
        if self.table_name == "purchase_bill_lines" and self.op == "select":
            return _Resp(data=self.db.line_rows)
        if self.op == "insert":
            self.db.inserted.setdefault(self.table_name, []).append(self.payload)
            rows = self.payload if isinstance(self.payload, list) else [self.payload]
            return _Resp(data=[{**r, "id": f"{self.table_name}-1"} for r in rows])
        return _Resp(data=[])


def _posted_lines(db):
    """The lines the kernel handed to post_journal_atomic."""
    return db.posted_lines


def _foots(lines):
    return (sum(int(l.get("debit_paise") or 0) for l in lines)
            == sum(int(l.get("credit_paise") or 0) for l in lines))


def _post(svc, fn_name, doc, db, monkeypatch):
    import services.phase2_journal_service as mod
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    monkeypatch.setattr(mod, "_USE_MOCK", False)
    return getattr(svc, fn_name)(doc, "F1", "C1")


def test_a_sales_invoice_credits_the_cess_to_its_own_ledger_and_the_entry_foots(monkeypatch):
    svc = _journal_svc()
    db = _AccountAwareDB()
    invoice = {
        "id": "INV-1", "invoice_no": "CESS-0001", "invoice_date": "2026-06-19",
        "taxable_amount_paise": 100_000, "cgst_paise": 14_000, "sgst_paise": 14_000,
        "igst_paise": 0, "cess_paise": 12_000, "total_paise": 140_000,
    }
    _post(svc, "journal_for_sales_invoice", invoice, db, monkeypatch)

    lines = _posted_lines(db)
    assert lines, "nothing posted"
    assert _foots(lines), "Dr and Cr must be equal — cess is in total_paise"
    cess = [l for l in lines if l["account_id"] == "ACC-CESSOUT"]
    assert len(cess) == 1 and cess[0]["credit_paise"] == 12_000
    # NEVER the GST Output ledger: s.11(2), proviso, ring-fences the credit,
    # and one ledger for both would assert an offset s.49(5) refuses.
    assert sum(int(l["credit_paise"]) for l in lines
               if l["account_id"] == "ACC-GSTOUT") == 28_000


def test_a_purchase_bill_debits_the_creditable_cess_to_its_own_asset(monkeypatch):
    svc = _journal_svc()
    db = _AccountAwareDB(line_rows=[{
        "expense_account_id": None, "taxable_amount_paise": 100_000,
        "itc_eligible": True, "cgst_paise": 14_000, "sgst_paise": 14_000,
        "igst_paise": 0, "cess_paise": 12_000,
    }])
    bill = {
        "id": "BILL-1", "bill_no": "VBILL-1", "bill_date": "2026-06-19",
        "taxable_amount_paise": 100_000, "cgst_paise": 14_000, "sgst_paise": 14_000,
        "igst_paise": 0, "cess_paise": 12_000, "total_paise": 140_000,
        "net_payable_paise": 140_000, "tds_paise": 0,
        "ineligible_itc_cgst_paise": 0, "ineligible_itc_sgst_paise": 0,
        "ineligible_itc_igst_paise": 0, "ineligible_itc_cess_paise": 0,
    }
    _post(svc, "journal_for_purchase_bill", bill, db, monkeypatch)

    lines = _posted_lines(db)
    assert lines and _foots(lines)
    cess = [l for l in lines if l["account_id"] == "ACC-CESSIN"]
    assert len(cess) == 1 and cess[0]["debit_paise"] == 12_000
    assert sum(int(l["debit_paise"]) for l in lines
               if l["account_id"] == "ACC-GSTIN") == 28_000


def test_a_blocked_lines_cess_lands_on_the_expense_and_not_on_the_asset(monkeypatch):
    """CGST s.17(5) bars the credit outright, so the cess is part of what the
    supply cost — the same reasoning PUR-04 applied to the GST heads, reaching
    this levy through s.11(2) of the Compensation Act. A phantom asset on the
    balance sheet is the alternative."""
    svc = _journal_svc()
    db = _AccountAwareDB(line_rows=[{
        "expense_account_id": None, "taxable_amount_paise": 100_000,
        "itc_eligible": False, "cgst_paise": 14_000, "sgst_paise": 14_000,
        "igst_paise": 0, "cess_paise": 12_000,
    }])
    bill = {
        "id": "BILL-2", "bill_no": "VBILL-2", "bill_date": "2026-06-19",
        "taxable_amount_paise": 100_000, "cgst_paise": 14_000, "sgst_paise": 14_000,
        "igst_paise": 0, "cess_paise": 12_000, "total_paise": 140_000,
        "net_payable_paise": 140_000, "tds_paise": 0,
        "ineligible_itc_cgst_paise": 14_000, "ineligible_itc_sgst_paise": 14_000,
        "ineligible_itc_igst_paise": 0, "ineligible_itc_cess_paise": 12_000,
    }
    _post(svc, "journal_for_purchase_bill", bill, db, monkeypatch)

    lines = _posted_lines(db)
    assert lines and _foots(lines)
    assert not [l for l in lines if l["account_id"] == "ACC-CESSIN"], \
        "a blocked line's cess is a cost, never an input-credit asset"
    # Taxable + the whole blocked tax, cess included, sits on the expense.
    assert sum(int(l["debit_paise"]) for l in lines
               if l["account_id"] == "ACC-PURCH") == 100_000 + 28_000 + 12_000


def test_a_reverse_charge_bill_self_assesses_the_cess_liability(monkeypatch):
    svc = _journal_svc()
    db = _AccountAwareDB(line_rows=[{
        "expense_account_id": None, "taxable_amount_paise": 100_000,
        "itc_eligible": True, "cgst_paise": 14_000, "sgst_paise": 14_000,
        "igst_paise": 0, "cess_paise": 12_000,
    }])
    bill = {
        "id": "BILL-3", "bill_no": "VBILL-3", "bill_date": "2026-06-19",
        "is_reverse_charge": True,
        "taxable_amount_paise": 100_000, "cgst_paise": 14_000, "sgst_paise": 14_000,
        "igst_paise": 0, "cess_paise": 12_000, "total_paise": 100_000,
        "net_payable_paise": 100_000, "tds_paise": 0,
        "ineligible_itc_cgst_paise": 0, "ineligible_itc_sgst_paise": 0,
        "ineligible_itc_igst_paise": 0, "ineligible_itc_cess_paise": 0,
    }
    _post(svc, "journal_for_purchase_bill", bill, db, monkeypatch)

    lines = _posted_lines(db)
    assert lines and _foots(lines), (
        "the vendor is owed the taxable value only, so the self-assessed cess "
        "credit is what balances the input debit")
    out = [l for l in lines if l["account_id"] == "ACC-CESSOUT"]
    assert len(out) == 1 and out[0]["credit_paise"] == 12_000


# ── GSTR-3B ─────────────────────────────────────────────────────────────────

from domain.gst.gstr3b_computer import (                          # noqa: E402
    PurchaseTransaction, SalesTransaction, compute_gstr3b,
)


def _outward_cess_supply(cess):
    return SalesTransaction(
        transaction_type="sales_invoice", taxable_amount_paise=100_000,
        cgst_paise=14_000, sgst_paise=14_000, igst_paise=0, cess_paise=cess,
        supply_type="taxable", is_reverse_charge=False,
    )


def _inward(cess, *, rcm=False, ineligible_cess=0):
    return PurchaseTransaction(
        taxable_amount_paise=100_000, cgst_paise=14_000, sgst_paise=14_000,
        igst_paise=0, cess_paise=cess, is_reverse_charge=rcm,
        ineligible_cess_paise=ineligible_cess,
    )


def test_a_reverse_charge_cess_is_declared_in_table_3_1_d_and_paid_in_cash():
    """s.11(2) of the Compensation Act applies the CGST Act to this levy
    mutatis mutandis, s.9(3)/(4) included. s.49(4) with s.2(82) then makes the
    reverse-charge liability cash-only, whatever credit is available."""
    r = compute_gstr3b([], [_inward(12_000, rcm=True)], [])
    assert r.rcm_cess == 12_000
    payload = r.as_gstn_payload("27AAAAA0000A1Z2", "062026")
    assert payload["sup_details"]["isup_rev"]["csamt"] == 120.0
    # In the cash figure, and never discharged out of credit.
    assert r.cash_payable_cess == r.net_cess + 12_000


def test_an_ordinary_purchase_declares_no_reverse_charge_cess():
    r = compute_gstr3b([], [_inward(12_000)], [])
    assert r.rcm_cess == 0
    assert r.itc_cess == 12_000


def test_the_reverse_charge_cess_credit_is_claimed_on_the_isrc_row():
    """4(A)(3) is where self-assessed tax is taken as credit in the same
    return (s.9(3)/(4) with s.16). The row used to carry a hard 0 in the cess
    column while OTH took the whole of it, so a period's 4(A) split said the
    cess came from an ordinary purchase."""
    r = compute_gstr3b([], [_inward(12_000, rcm=True)], [])
    rows = dict((ty, cess) for ty, _i, _c, _s, cess in r.itc_avl_rows())
    assert rows["ISRC"] == 12_000
    assert rows["OTH"] == 0
    # The five rows still sum to 4(A) exactly.
    assert sum(rows.values()) == r.itc_avail_cess


def test_cess_credit_never_discharges_igst_cgst_or_sgst():
    """s.11(2), proviso: credit of this cess "shall be utilised only towards
    payment of cess". A period with cess credit and no cess liability must
    still pay its GST in cash."""
    r = compute_gstr3b([_outward_cess_supply(0)], [_inward(50_000)], [])
    assert r.itc_cess == 50_000
    # Output CGST+SGST is 28,000 and input CGST+SGST is 28,000, so those net
    # off; the cess credit sits unused rather than paying anything else.
    assert r.net_cess == 0
    assert r.cash_payable_cess == 0


def test_a_blocked_cess_is_reversed_in_table_4_b_1_and_not_claimed():
    r = compute_gstr3b([], [_inward(12_000, ineligible_cess=12_000)], [])
    assert r.itc_ineligible_cess == 12_000
    assert r.itc_net_cess == 0


def test_the_outward_cess_is_the_liability_table_6_settles():
    r = compute_gstr3b([_outward_cess_supply(12_000)], [], [])
    assert r.liability_cess == 12_000
    assert r.net_cess == 12_000
    assert r.cash_payable_cess == 12_000


# ── GSTR-1 ──────────────────────────────────────────────────────────────────

def test_the_line_cess_reaches_table_12(monkeypatch):
    """`_document_lines` hardcoded `cess_paise=0` because no line table had
    the column; migration 374 gives the sales line one, and table 12's HSN
    summary apportions per line."""
    import services.gst_return_service as grs
    from domain.gst.gstr1_builder import InvoiceLine

    rows = [{
        "sales_invoice_id": "INV-1", "sort_order": 0, "hsn_sac": "22021010",
        "description": "Aerated waters", "quantity": 1, "unit": "NOS",
        "rate_paise": 100_000, "taxable_amount_paise": 100_000,
        "gst_rate_bps": 2800, "cgst_paise": 14_000, "sgst_paise": 14_000,
        "igst_paise": 0, "cess_paise": 12_000,
    }]

    class _DB:
        def table(self, name):
            return self
        def select(self, *a, **k): return self
        def in_(self, *a, **k): return self
        def order(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def gt(self, *a, **k): return self
        def execute(self): return type("R", (), {"data": rows})()

    monkeypatch.setattr(grs, "_paginate_all", lambda fn: rows)
    by_doc = grs._document_lines(
        _DB(), "client_sales_invoice_lines", "sales_invoice_id", {"INV-1"})
    line = by_doc["INV-1"][0]
    assert isinstance(line, InvoiceLine)
    assert line.cess_paise == 12_000


def test_a_note_against_a_cess_invoice_is_named_rather_than_silently_short():
    """The four s.34 note tables have no cess column, so such a note adjusts
    the value and the GST and leaves the cess. That is a real short
    declaration; the return says so instead of showing a nil that reads as
    "none due"."""
    import services.gst_return_service as grs

    parents = {"INV-1": {"cess_paise": 12_000}, "INV-2": {"cess_paise": 0}}
    notes = [{"sales_invoice_id": "INV-1", "credit_note_no": "CN-1"},
             {"sales_invoice_id": "INV-2", "credit_note_no": "CN-2"}]
    gaps = grs._note_cess_not_carried(notes, parents)
    assert len(gaps) == 1
    assert "CN-1" in gaps[0] and "12000 paise" in gaps[0]
    assert "CN-2" not in " ".join(gaps)


# ── the customer's copy ─────────────────────────────────────────────────────

def test_the_invoice_pdf_prints_the_cess_because_rule_46_m_names_it():
    """CGST Rule 46(m): "amount of tax charged in respect of taxable goods or
    services (central tax, State tax, integrated tax, Union territory tax or
    CESS)". A cess-bearing invoice that omits it is not a compliant tax
    invoice, and the recipient cannot claim credit from a document that does
    not show the charge."""
    from services.invoice_pdf_service import summary_lines
    inv = {"cess_paise": 12_000}
    rows = summary_lines(inv, [], 100_000, 28_000, 14_000, 14_000, 0, 140_000)
    labels = [lbl for lbl, _v in rows]
    assert "Compensation Cess" in labels
    assert dict(rows)["Compensation Cess"] == "120.00"
    # Below the GST heads and above the Total, so the block still reads down
    # to the figure the customer pays.
    assert labels.index("Compensation Cess") > labels.index("CGST @ 14%")
    assert labels.index("Compensation Cess") < labels.index("Total")


def test_an_invoice_with_no_cess_keeps_the_layout_it_always_had():
    from services.invoice_pdf_service import summary_lines
    rows = summary_lines({}, [], 100_000, 28_000, 14_000, 14_000, 0, 128_000)
    assert "Compensation Cess" not in [lbl for lbl, _v in rows]


# ── the e-way threshold ─────────────────────────────────────────────────────

def test_the_eway_consignment_value_includes_the_cess():
    """CGST Rule 138(1), Explanation 2: the consignment value is the value
    declared in the invoice "including the central tax, State or Union
    territory tax, integrated tax and CESS charged, if any". `EwayLine` has
    carried the field since SALES-17 with a comment saying it was always 0
    because no column existed; migration 374 gives it one.

    The number matters: a consignment measured short of the cess can fall
    under the Rs.50,000 limit and be advised as not needing a bill.
    """
    lines = [{
        "hsn_sac": "22021010", "taxable_amount_paise": 40_00_000,
        "cgst_paise": 5_60_000, "sgst_paise": 5_60_000, "igst_paise": 0,
        "cess_paise": 4_80_000, "gst_rate_bps": 2800,
    }]
    with_cess = sales_invoices._eway_assessment(lines)
    without = sales_invoices._eway_assessment(
        [{**lines[0], "cess_paise": 0}])
    assert with_cess["consignment_value_paise"] == 40_00_000 + 11_20_000 + 4_80_000
    assert without["consignment_value_paise"] == 40_00_000 + 11_20_000
    assert with_cess["consignment_value_paise"] > without["consignment_value_paise"]
