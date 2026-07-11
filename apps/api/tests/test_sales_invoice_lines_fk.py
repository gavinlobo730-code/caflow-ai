"""
Regression tests — sales invoice line FK column (production blocker).

The bug: create_invoice()/update_invoice()/get_invoice()/list_invoices() wrote
or queried client_sales_invoice_lines using `invoice_id`, but migration 050
defines the FK column as `sales_invoice_id`. PostgREST rejected the line insert
(PGRST204), leaving an orphan invoice header and a masked 200-with-error.

These tests force the NON-mock DB path (the path the existing mock-mode tests
never exercised) with a fake Supabase client that records every operation, then
assert:
  * lines are written/queried via sales_invoice_id (never invoice_id)
  * totals match the production case (interstate ₹60.18 → taxable 5100 + IGST 918)
  * a line-insert failure rolls back the header (no orphan left behind)

CGST Act §8: inter-state supply → IGST. All amounts in integer paise.
"""
import pytest
from fastapi import HTTPException

from routers import sales_invoices
from models.invoices import SalesInvoiceIn, SalesInvoiceUpdateIn, InvoiceLineIn


# ---------------------------------------------------------------------------
# Fake Supabase query-builder that records every execute()
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, data=None, count=None):
        self.data = data
        self.count = count


class _Query:
    def __init__(self, table, recorder, controller):
        self._table = table
        self._rec = recorder
        self._ctl = controller
        self._op = "select"
        self._payload = None
        self._count = None
        self._filters = {}

    def select(self, *a, **k):
        self._op = "select"
        self._count = k.get("count")
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    # chainable no-ops used by the router
    def like(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    def ilike(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def range(self, *a, **k):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        event = {
            "table": self._table,
            "op": self._op,
            "payload": self._payload,
            "filters": dict(self._filters),
            "count": self._count,
        }
        self._rec.append(event)
        return self._ctl(event)


class _FakeDB:
    def __init__(self, recorder, controller):
        self._rec = recorder
        self._ctl = controller

    def table(self, name):
        return _Query(name, self._rec, self._ctl)


_USER = {"firm_id": "F1", "auth_user_id": "u1", "email": "u@firm.test", "role": "Partner"}


@pytest.fixture
def fake_db(monkeypatch):
    """Force the non-mock DB path and install a recording fake client."""
    recorder: list[dict] = []
    holder = {"controller": lambda event: _Resp(data=[])}

    def _get_supabase():
        return _FakeDB(recorder, holder["controller"])

    # Router reads `_USE_MOCK` to branch; flip it off so the real DB path runs.
    monkeypatch.setattr(sales_invoices, "_USE_MOCK", False)
    # get_supabase is imported inside the function from core.supabase_client.
    monkeypatch.setattr("core.supabase_client.get_supabase", _get_supabase)
    # Neutralise side-effects unrelated to the line insert.
    monkeypatch.setattr(
        sales_invoices.period_validation_service, "validate_posting_date",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(sales_invoices, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(sales_invoices.timeline_service, "log", lambda *a, **k: None)

    return recorder, holder


def _interstate_create_controller(event):
    """Customer in state 07, client in state 27 → inter-state supply."""
    t, op = event["table"], event["op"]
    if t == "customers" and op == "select":
        return _Resp(data=[{"state_code": "07", "gstin": "07AAAAA0000A1Z5"}])
    if t == "clients" and op == "select":
        return _Resp(data=[{"gstin": "27AAAAA0000A1Z5"}])
    if t == "client_sales_invoices" and op == "select" and event["count"] == "exact":
        return _Resp(data=[], count=0)  # first invoice this FY
    if t == "client_sales_invoices" and op == "insert":
        return _Resp(data=[{**event["payload"], "id": "INV-TEST-1"}])
    if t == "client_sales_invoice_lines" and op == "insert":
        return _Resp(data=[{**row, "id": f"L{i}"} for i, row in enumerate(event["payload"])])
    return _Resp(data=[])


# ---------------------------------------------------------------------------
# Create Invoice
# ---------------------------------------------------------------------------

class TestCreateInvoice:
    def _payload(self):
        # Production case: ₹60.18 total interstate @18% → taxable 5100, IGST 918.
        return SalesInvoiceIn(
            client_id="C1",
            customer_id="CUST1",
            invoice_no="TEST-0001",
            invoice_date="2026-06-19",
            lines=[InvoiceLineIn(
                description="Consulting services",
                hsn_sac="998311",
                rate_paise=5100,
                quantity=1,
                gst_rate_percent=18.0,
            )],
        )

    def test_lines_inserted_with_sales_invoice_id(self, fake_db):
        recorder, holder = fake_db
        holder["controller"] = _interstate_create_controller

        resp = sales_invoices.create_invoice(self._payload(), _USER)

        assert resp["success"] is True
        line_inserts = [e for e in recorder
                        if e["table"] == "client_sales_invoice_lines" and e["op"] == "insert"]
        assert len(line_inserts) == 1, "lines must be inserted exactly once"
        for row in line_inserts[0]["payload"]:
            assert row["sales_invoice_id"] == "INV-TEST-1", "FK must be sales_invoice_id"
            assert "invoice_id" not in row, "must NOT use the non-existent invoice_id column"

    def test_header_and_lines_both_created(self, fake_db):
        recorder, holder = fake_db
        holder["controller"] = _interstate_create_controller

        resp = sales_invoices.create_invoice(self._payload(), _USER)

        assert resp["success"] is True
        header_inserts = [e for e in recorder
                          if e["table"] == "client_sales_invoices" and e["op"] == "insert"]
        line_inserts = [e for e in recorder
                        if e["table"] == "client_sales_invoice_lines" and e["op"] == "insert"]
        assert len(header_inserts) == 1
        assert len(line_inserts) == 1
        assert resp["data"]["lines"], "response must include the created lines"

    def test_totals_match_production_case(self, fake_db):
        recorder, holder = fake_db
        holder["controller"] = _interstate_create_controller

        resp = sales_invoices.create_invoice(self._payload(), _USER)

        inv = resp["data"]
        # Inter-state: IGST only (CGST Act §8). ₹51.00 taxable + ₹9.18 IGST = ₹60.18
        # before round-off. Batch 1 adds invoice-level round-off (nearest ₹1): the
        # taxable value and GST are UNCHANGED (CGST Act §15); only the payable total
        # is rounded — ₹60.18 → ₹60.00 with a −18 paise round-off posted to the
        # 'Round Off' ledger so the journal stays balanced.
        assert inv["is_interstate"] is True
        assert inv["taxable_amount_paise"] == 5100   # unchanged by round-off
        assert inv["igst_paise"] == 918              # unchanged by round-off
        assert inv["cgst_paise"] == 0
        assert inv["sgst_paise"] == 0
        assert inv["round_off_paise"] == -18         # 6018 → 6000 (round down)
        assert inv["total_paise"] == 6000            # ₹60.00 payable (rounded)
        # Round-off never changes the value of supply / GST — total reconciles to
        # taxable + GST + round-off.
        assert inv["total_paise"] == (
            inv["taxable_amount_paise"] + inv["igst_paise"] + inv["round_off_paise"]
        )

    def test_header_rolled_back_on_line_insert_failure(self, fake_db):
        """If the line insert fails, the just-created header must be deleted —
        no orphan invoice headers (the exact production failure mode)."""
        recorder, holder = fake_db

        def _failing_controller(event):
            if event["table"] == "client_sales_invoice_lines" and event["op"] == "insert":
                raise RuntimeError("PGRST204: simulated line insert failure")
            return _interstate_create_controller(event)

        holder["controller"] = _failing_controller

        resp = sales_invoices.create_invoice(self._payload(), _USER)

        assert resp["success"] is False, "masked failure response preserved"
        header_deletes = [e for e in recorder
                          if e["table"] == "client_sales_invoices" and e["op"] == "delete"]
        assert len(header_deletes) == 1, "header must be rolled back on line failure"
        assert header_deletes[0]["filters"].get("id") == "INV-TEST-1"

    def test_line_unit_defaults_to_nos_when_omitted(self, fake_db):
        """InvoiceLineIn.model_dump() always includes "unit" (None when the
        caller omits it), so a plain `ln.get("unit", "NOS")` would return None,
        not "NOS" — the fallback must be `ln.get("unit") or "NOS"`."""
        recorder, holder = fake_db
        holder["controller"] = _interstate_create_controller

        resp = sales_invoices.create_invoice(self._payload(), _USER)

        assert resp["data"]["lines"][0]["unit"] == "NOS"
        line_inserts = [e for e in recorder
                        if e["table"] == "client_sales_invoice_lines" and e["op"] == "insert"]
        assert line_inserts[0]["payload"][0]["unit"] == "NOS"

    def test_line_unit_round_trips_when_provided(self, fake_db):
        recorder, holder = fake_db
        holder["controller"] = _interstate_create_controller

        payload = SalesInvoiceIn(
            client_id="C1", customer_id="CUST1", invoice_no="TEST-0002",
            invoice_date="2026-06-19",
            lines=[InvoiceLineIn(
                description="Gold sale", hsn_sac="7108", rate_paise=100000,
                quantity=2, unit="GMS", gst_rate_percent=3.0,
            )],
        )
        resp = sales_invoices.create_invoice(payload, _USER)

        assert resp["data"]["lines"][0]["unit"] == "GMS"
        line_inserts = [e for e in recorder
                        if e["table"] == "client_sales_invoice_lines" and e["op"] == "insert"]
        assert line_inserts[0]["payload"][0]["unit"] == "GMS"

    def test_reference_no_round_trips(self, fake_db):
        """SalesInvoiceIn already declared reference_no, and the DB column
        exists (migration 050), but the header payload dict was built
        field-by-field without it — so a PO/reference number the CA typed was
        silently dropped on create. Blueprint §3.1 wireframe requires it."""
        recorder, holder = fake_db
        holder["controller"] = _interstate_create_controller

        payload = SalesInvoiceIn(
            client_id="C1", customer_id="CUST1", invoice_no="TEST-0003",
            invoice_date="2026-06-19",
            reference_no="PO-8891",
            lines=[InvoiceLineIn(description="Consulting", hsn_sac="998311", rate_paise=5100, quantity=1, gst_rate_percent=18.0)],
        )
        resp = sales_invoices.create_invoice(payload, _USER)

        assert resp["data"]["reference_no"] == "PO-8891"
        header_inserts = [e for e in recorder if e["table"] == "client_sales_invoices" and e["op"] == "insert"]
        assert header_inserts[0]["payload"]["reference_no"] == "PO-8891"


# ---------------------------------------------------------------------------
# Get Invoice
# ---------------------------------------------------------------------------

class TestGetInvoice:
    def test_lines_queried_by_sales_invoice_id(self, fake_db):
        recorder, holder = fake_db

        def _controller(event):
            t, op = event["table"], event["op"]
            if t == "client_sales_invoices" and op == "select":
                return _Resp(data=[{"id": "INV-1", "invoice_no": "SINV-1",
                                    "status": "issued", "total_paise": 6018}])
            if t == "client_sales_invoice_lines" and op == "select":
                return _Resp(data=[{"id": "L0", "sales_invoice_id": "INV-1"}])
            return _Resp(data=[])

        holder["controller"] = _controller
        resp = sales_invoices.get_invoice("INV-1", _USER)

        assert resp["success"] is True
        line_selects = [e for e in recorder
                        if e["table"] == "client_sales_invoice_lines" and e["op"] == "select"]
        assert len(line_selects) == 1
        assert line_selects[0]["filters"].get("sales_invoice_id") == "INV-1"
        assert "invoice_id" not in line_selects[0]["filters"]
        assert resp["data"]["lines"], "invoice must load with its lines"


# ---------------------------------------------------------------------------
# Update Invoice
# ---------------------------------------------------------------------------

class TestUpdateInvoice:
    def test_lines_replaced_via_sales_invoice_id(self, fake_db):
        recorder, holder = fake_db

        def _controller(event):
            t, op = event["table"], event["op"]
            if t == "client_sales_invoices" and op == "select":
                return _Resp(data=[{"id": "INV-1", "status": "draft", "is_interstate": True}])
            if t == "client_sales_invoice_lines" and op == "insert":
                return _Resp(data=event["payload"])
            if t == "client_sales_invoices" and op == "update":
                return _Resp(data=[{**event["payload"], "id": "INV-1"}])
            return _Resp(data=[])

        holder["controller"] = _controller
        upd = SalesInvoiceUpdateIn(lines=[InvoiceLineIn(
            description="Revised line", rate_paise=10000, quantity=1, gst_rate_percent=18.0)])
        resp = sales_invoices.update_invoice("INV-1", upd, _USER)

        assert resp["success"] is True
        # Old lines deleted by sales_invoice_id
        line_deletes = [e for e in recorder
                        if e["table"] == "client_sales_invoice_lines" and e["op"] == "delete"]
        assert len(line_deletes) == 1
        assert line_deletes[0]["filters"].get("sales_invoice_id") == "INV-1"
        assert "invoice_id" not in line_deletes[0]["filters"]
        # New lines inserted with sales_invoice_id
        line_inserts = [e for e in recorder
                        if e["table"] == "client_sales_invoice_lines" and e["op"] == "insert"]
        assert len(line_inserts) == 1
        for row in line_inserts[0]["payload"]:
            assert row["sales_invoice_id"] == "INV-1"
            assert "invoice_id" not in row

    def test_update_line_unit_defaults_to_nos_and_round_trips(self, fake_db):
        recorder, holder = fake_db

        def _controller(event):
            t, op = event["table"], event["op"]
            if t == "client_sales_invoices" and op == "select":
                return _Resp(data=[{"id": "INV-1", "status": "draft", "is_interstate": True}])
            if t == "client_sales_invoice_lines" and op == "insert":
                return _Resp(data=event["payload"])
            if t == "client_sales_invoices" and op == "update":
                return _Resp(data=[{**event["payload"], "id": "INV-1"}])
            return _Resp(data=[])

        holder["controller"] = _controller
        upd = SalesInvoiceUpdateIn(lines=[
            InvoiceLineIn(description="No unit given", rate_paise=10000, quantity=1, gst_rate_percent=18.0),
            InvoiceLineIn(description="Explicit unit", rate_paise=10000, quantity=1, gst_rate_percent=18.0, unit="HRS"),
        ])
        resp = sales_invoices.update_invoice("INV-1", upd, _USER)

        assert resp["success"] is True
        line_inserts = [e for e in recorder
                        if e["table"] == "client_sales_invoice_lines" and e["op"] == "insert"]
        rows = line_inserts[0]["payload"]
        assert rows[0]["unit"] == "NOS"
        assert rows[1]["unit"] == "HRS"

    def test_edit_remaps_interstate_flag_and_recomputes_intrastate(self, fake_db):
        """Editing a draft may flip the IGST checkbox. The request field
        is_inter_state must persist as the is_interstate COLUMN (never the bad
        is_inter_state name), and the existing GST math must re-split the line
        intra-state (CGST+SGST). CGST Act §8."""
        recorder, holder = fake_db

        def _controller(event):
            t, op = event["table"], event["op"]
            if t == "client_sales_invoices" and op == "select":
                # Was inter-state; the edit switches it to intra-state.
                return _Resp(data=[{"id": "INV-1", "status": "draft",
                                    "is_interstate": True, "client_id": "C1"}])
            if t == "client_sales_invoice_lines" and op == "insert":
                return _Resp(data=event["payload"])
            if t == "client_sales_invoices" and op == "update":
                return _Resp(data=[{**event["payload"], "id": "INV-1"}])
            return _Resp(data=[])

        holder["controller"] = _controller
        upd = SalesInvoiceUpdateIn(
            is_inter_state=False,
            lines=[InvoiceLineIn(description="Consulting", rate_paise=10000,
                                 quantity=1, gst_rate_percent=18.0)],
        )
        resp = sales_invoices.update_invoice("INV-1", upd, _USER)

        assert resp["success"] is True
        upd_event = [e for e in recorder
                     if e["table"] == "client_sales_invoices" and e["op"] == "update"][0]
        pl = upd_event["payload"]
        assert "is_inter_state" not in pl, "must map to the is_interstate column"
        assert pl["is_interstate"] is False
        # ₹100 @18% intra-state → CGST 900 + SGST 900, no IGST. Integer paise.
        assert pl["taxable_amount_paise"] == 10000
        assert pl["cgst_paise"] == 900
        assert pl["sgst_paise"] == 900
        assert pl["igst_paise"] == 0
        assert pl["total_paise"] == 11800

    # ── Post-issue soft-field edits (audit fix) ──────────────────────────────
    # Once issued, only reference_no/notes/due_date/credit_days and line_units
    # may still change — everything else is CGST Rule 46 tax-invoice content
    # and needs a Credit Note to correct (CGST Act §34).

    def test_update_rejects_locked_field_on_issued_invoice(self, fake_db):
        recorder, holder = fake_db

        def _controller(event):
            t, op = event["table"], event["op"]
            if t == "client_sales_invoices" and op == "select":
                return _Resp(data=[{"id": "INV-1", "status": "issued", "client_id": "C1"}])
            return _Resp(data=[])

        holder["controller"] = _controller
        upd = SalesInvoiceUpdateIn(invoice_date="2026-07-01")
        with pytest.raises(HTTPException) as exc:
            sales_invoices.update_invoice("INV-1", upd, _USER)
        assert exc.value.status_code == 422
        # No write should have been attempted once the field check fails.
        assert not [e for e in recorder if e["table"] == "client_sales_invoices" and e["op"] == "update"]

    def test_update_allows_soft_fields_on_issued_invoice(self, fake_db):
        recorder, holder = fake_db

        def _controller(event):
            t, op = event["table"], event["op"]
            if t == "client_sales_invoices" and op == "select":
                return _Resp(data=[{"id": "INV-1", "status": "issued", "client_id": "C1"}])
            if t == "client_sales_invoices" and op == "update":
                return _Resp(data=[{**event["payload"], "id": "INV-1"}])
            return _Resp(data=[])

        holder["controller"] = _controller
        upd = SalesInvoiceUpdateIn(reference_no="PO-9981", notes="Called customer to confirm", due_date="2026-08-01")
        resp = sales_invoices.update_invoice("INV-1", upd, _USER)

        assert resp["success"] is True
        upd_event = [e for e in recorder if e["table"] == "client_sales_invoices" and e["op"] == "update"][0]
        assert upd_event["payload"]["reference_no"] == "PO-9981"
        assert upd_event["payload"]["notes"] == "Called customer to confirm"
        assert upd_event["payload"]["due_date"] == "2026-08-01"

    def test_update_line_units_on_issued_invoice(self, fake_db):
        recorder, holder = fake_db

        def _controller(event):
            t, op = event["table"], event["op"]
            if t == "client_sales_invoices" and op == "select":
                return _Resp(data=[{"id": "INV-1", "status": "issued", "client_id": "C1"}])
            if t == "client_sales_invoices" and op == "update":
                return _Resp(data=[{**event["payload"], "id": "INV-1"}])
            if t == "client_sales_invoice_lines" and op == "update":
                return _Resp(data=[{**event["payload"], "id": "L1"}])
            return _Resp(data=[])

        holder["controller"] = _controller
        upd = SalesInvoiceUpdateIn(line_units={"L1": "kgs"})
        resp = sales_invoices.update_invoice("INV-1", upd, _USER)

        assert resp["success"] is True
        line_updates = [e for e in recorder if e["table"] == "client_sales_invoice_lines" and e["op"] == "update"]
        assert len(line_updates) == 1
        assert line_updates[0]["payload"] == {"unit": "KGS"}
        assert line_updates[0]["filters"] == {"id": "L1", "sales_invoice_id": "INV-1"}
        # Line unit changes never touch the header's own amount/GST columns.
        header_update = [e for e in recorder if e["table"] == "client_sales_invoices" and e["op"] == "update"][0]
        assert "taxable_amount_paise" not in header_update["payload"]

    def test_update_rejects_any_edit_on_cancelled_invoice(self, fake_db):
        recorder, holder = fake_db

        def _controller(event):
            t, op = event["table"], event["op"]
            if t == "client_sales_invoices" and op == "select":
                return _Resp(data=[{"id": "INV-1", "status": "cancelled", "client_id": "C1"}])
            return _Resp(data=[])

        holder["controller"] = _controller
        upd = SalesInvoiceUpdateIn(notes="trying to edit a cancelled invoice")
        with pytest.raises(HTTPException) as exc:
            sales_invoices.update_invoice("INV-1", upd, _USER)
        assert exc.value.status_code == 422
