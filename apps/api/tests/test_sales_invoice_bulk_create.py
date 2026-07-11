"""
Bulk sales-invoice creation (bulk-select / import-performance work).

POST /api/sales-invoices/bulk loops the exact same _create_invoice_core logic
used by the single-invoice endpoint, in-process — collapsing what the CSV
importer used to do as N sequential HTTP round-trips into ONE request. This
must be a pure plumbing change: identical GST computation, identical
duplicate-invoice-number handling, and a bad row must not abort the rest of
the batch (matches the existing CSV-import UX).
"""
from models.invoices import SalesInvoiceIn, InvoiceLineIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firma.test", "role": "Partner"}


def _setup(monkeypatch):
    import routers.sales_invoices as si
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    db.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": "CLI",
                          "name": "Acme Buyer", "state_code": "27",
                          "gstin": "27XYZAB5678C1Z2", "is_active": True})
    seed_standard_coa(db, FIRM, "CLI")
    return si, db


def _line():
    return InvoiceLineIn(description="Consulting", hsn_sac="9982",
                         quantity=1, rate_paise=1_000_000, gst_rate_percent=18.0)


def _invoice_dict(invoice_no):
    return SalesInvoiceIn(
        client_id="CLI", customer_id="CUST", invoice_date="2026-04-10",
        due_date="2026-05-10", invoice_no=invoice_no, lines=[_line()],
    ).model_dump()


class _BulkPayload:
    """Mimics the FastAPI-parsed _BulkInvoicesIn body for a direct call."""
    def __init__(self, invoices):
        self.invoices = invoices


def test_bulk_create_all_valid(monkeypatch):
    si, db = _setup(monkeypatch)
    payload = _BulkPayload([_invoice_dict(f"BULK-{i:03d}") for i in range(1, 4)])

    resp = si.bulk_create_invoices(payload, CALLER)

    assert resp["success"] is True
    assert len(resp["data"]["created"]) == 3
    assert resp["data"]["errors"] == []
    numbers = {inv["invoice_no"] for inv in resp["data"]["created"]}
    assert numbers == {"BULK-001", "BULK-002", "BULK-003"}
    # GST computed identically to the single-invoice path.
    for inv in resp["data"]["created"]:
        assert inv["cgst_paise"] == 90_000 and inv["sgst_paise"] == 90_000
        assert inv["total_paise"] == 1_180_000
        assert inv["status"] == "draft"


def test_bulk_create_bad_row_does_not_abort_batch(monkeypatch):
    si, db = _setup(monkeypatch)
    # Second item has no lines — must fail without touching the other two.
    bad = _invoice_dict("BULK-BAD")
    bad["lines"] = []
    payload = _BulkPayload([_invoice_dict("BULK-A"), bad, _invoice_dict("BULK-C")])

    resp = si.bulk_create_invoices(payload, CALLER)

    assert resp["success"] is True
    created_numbers = {inv["invoice_no"] for inv in resp["data"]["created"]}
    assert created_numbers == {"BULK-A", "BULK-C"}
    assert len(resp["data"]["errors"]) == 1
    assert resp["data"]["errors"][0]["index"] == 1
    assert resp["data"]["errors"][0]["invoice_no"] == "BULK-BAD"
    assert "line" in resp["data"]["errors"][0]["error"].lower()


def test_bulk_create_duplicate_invoice_no_reported_not_raised(monkeypatch):
    si, db = _setup(monkeypatch)
    # Create BULK-DUP once directly, then try to bulk-import a batch that
    # repeats it — the second occurrence must be reported as a per-row error,
    # not raise and abort the whole request.
    si.create_invoice(SalesInvoiceIn(**_invoice_dict("BULK-DUP")), CALLER)
    payload = _BulkPayload([_invoice_dict("BULK-DUP"), _invoice_dict("BULK-OK")])

    resp = si.bulk_create_invoices(payload, CALLER)

    assert resp["success"] is True
    created_numbers = {inv["invoice_no"] for inv in resp["data"]["created"]}
    assert created_numbers == {"BULK-OK"}
    assert len(resp["data"]["errors"]) == 1
    assert resp["data"]["errors"][0]["invoice_no"] == "BULK-DUP"
    assert "already exists" in resp["data"]["errors"][0]["error"]


def test_bulk_create_empty_batch(monkeypatch):
    si, db = _setup(monkeypatch)
    resp = si.bulk_create_invoices(_BulkPayload([]), CALLER)
    assert resp["success"] is True
    assert resp["data"] == {"created": [], "errors": []}


def test_bulk_create_prefetches_once_not_per_invoice(monkeypatch):
    """The whole point of this endpoint's rewrite: customer/client rows and
    the existing-invoice-number check must be fetched ONCE for the batch, not
    once per invoice — at import scale (thousands of rows) the per-invoice
    version is the difference between a few seconds and a request timeout.
    Asserts .table() call count grows with the number of DISTINCT
    lookups needed (a small constant), not with batch size."""
    si, db = _setup(monkeypatch)
    calls = {"n": 0}
    real_table = db.table
    def counting_table(name):
        calls["n"] += 1
        return real_table(name)
    monkeypatch.setattr(db, "table", counting_table)

    payload = _BulkPayload([_invoice_dict(f"BULK-{i:03d}") for i in range(1, 21)])
    resp = si.bulk_create_invoices(payload, CALLER)

    assert resp["success"] is True
    assert len(resp["data"]["created"]) == 20
    # Every invoice shares the same client/customer, so the pre-fetch is 3
    # calls total (customers, clients, existing invoice numbers) regardless
    # of batch size — the per-invoice .table() calls that remain are the
    # ones that genuinely can't be batched (the header insert and the lines
    # insert, 2 per invoice = 40), not the ~7 each the old code did.
    assert calls["n"] < 20 * 4, (
        f"{calls['n']} .table() calls for 20 invoices — pre-fetch batching "
        "does not appear to be working (expected well under 80)"
    )


def test_bulk_create_intra_batch_duplicate_invoice_no(monkeypatch):
    """Two rows sharing an invoice_no within the SAME batch (never produced by
    buildSalesInvoices' grouping, but the endpoint must still reject the
    second occurrence rather than create it) — the set-based dedup this
    endpoint uses to avoid a per-invoice existence query must catch a
    duplicate introduced mid-batch, not just one that already existed before
    the request started."""
    si, db = _setup(monkeypatch)
    payload = _BulkPayload([_invoice_dict("BULK-SAME"), _invoice_dict("BULK-SAME")])

    resp = si.bulk_create_invoices(payload, CALLER)

    assert resp["success"] is True
    created_numbers = [inv["invoice_no"] for inv in resp["data"]["created"]]
    assert created_numbers == ["BULK-SAME"]
    assert len(resp["data"]["errors"]) == 1
    assert resp["data"]["errors"][0]["invoice_no"] == "BULK-SAME"
    assert "already exists" in resp["data"]["errors"][0]["error"]
