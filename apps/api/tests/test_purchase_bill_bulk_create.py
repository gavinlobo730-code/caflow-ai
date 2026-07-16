"""
Bulk purchase-bill creation (bulk-select / import-performance work).

POST /api/purchase-bills/bulk loops the exact same _create_purchase_bill_core
logic used by the single-bill endpoint, in-process — collapsing what the CSV
importer used to do as N sequential HTTP round-trips into ONE request. This
must be a pure plumbing change: identical GST/TDS computation, and a bad row
must not abort the rest of the batch (matches the existing CSV-import UX).
"""
from models.invoices import PurchaseBillIn, PurchaseBillLineIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firma.test", "role": "Partner"}


def _setup(monkeypatch, tds_applicable=True):
    import routers.purchase_bills as pb
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pb])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    db.seed("vendors", {"id": "VEND", "firm_id": FIRM, "client_id": "CLI",
                        "name": "Supplier Co", "state_code": "27", "gstin": "27PQRST9012K1Z8",
                        "pan": "PQRST9012K", "is_active": True, "tds_applicable": tds_applicable,
                        "tds_section": "194J", "tds_rate_bps": 1000})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Audit Services", "kind": "service"})
    return pb, db


def _bill_dict(bill_no, rate_paise=10_000_000, gst=18.0):
    return PurchaseBillIn(
        client_id="CLI", vendor_id="VEND", bill_date="2026-04-05", bill_no=bill_no,
        lines=[PurchaseBillLineIn(description="Audit services", hsn_sac="9982",
                                  quantity=1, rate_paise=rate_paise, gst_rate_percent=gst,
                                  service_catalogue_id="SVC-1")],
    ).model_dump()


class _BulkPayload:
    def __init__(self, bills):
        self.bills = bills


def test_bulk_create_all_valid(monkeypatch):
    pb, db = _setup(monkeypatch)
    payload = _BulkPayload([_bill_dict(f"VINV-{i:03d}") for i in range(1, 4)])

    resp = pb.bulk_create_purchase_bills(payload, CALLER)

    assert resp["success"] is True
    assert len(resp["data"]["created"]) == 3
    assert resp["data"]["errors"] == []
    for bill in resp["data"]["created"]:
        assert bill["status"] == "draft"
        # TDS §194J at 10% on taxable ₹1,00,000 = ₹10,000 = 1_000_000 paise
        assert bill["tds_paise"] == 1_000_000
        assert bill["net_payable_paise"] == bill["total_paise"] - bill["tds_paise"]


def test_bulk_create_bad_row_does_not_abort_batch(monkeypatch):
    pb, db = _setup(monkeypatch)
    bad = _bill_dict("VINV-BAD")
    bad["lines"] = []
    payload = _BulkPayload([_bill_dict("VINV-A"), bad, _bill_dict("VINV-C")])

    resp = pb.bulk_create_purchase_bills(payload, CALLER)

    assert resp["success"] is True
    created_nos = {b["bill_no"] for b in resp["data"]["created"]}
    assert created_nos == {"VINV-A", "VINV-C"}
    assert len(resp["data"]["errors"]) == 1
    assert resp["data"]["errors"][0]["index"] == 1
    assert resp["data"]["errors"][0]["bill_no"] == "VINV-BAD"


def test_bulk_create_unknown_vendor_reported_not_raised(monkeypatch):
    pb, db = _setup(monkeypatch)
    good = _bill_dict("VINV-OK")
    bad_vendor = _bill_dict("VINV-NOVEND")
    bad_vendor["vendor_id"] = "NOPE"
    payload = _BulkPayload([good, bad_vendor])

    resp = pb.bulk_create_purchase_bills(payload, CALLER)

    assert resp["success"] is True
    created_nos = {b["bill_no"] for b in resp["data"]["created"]}
    assert created_nos == {"VINV-OK"}
    assert len(resp["data"]["errors"]) == 1
    assert resp["data"]["errors"][0]["bill_no"] == "VINV-NOVEND"


def test_bulk_create_empty_batch(monkeypatch):
    pb, db = _setup(monkeypatch)
    resp = pb.bulk_create_purchase_bills(_BulkPayload([]), CALLER)
    assert resp["success"] is True
    assert resp["data"] == {"created": [], "errors": [], "skipped": []}


def test_bulk_create_skips_duplicate_vendor_bill_no_already_in_db(monkeypatch):
    # Reproduces the real-world incident: a large CSV import's fetch times out
    # client-side (or the user re-uploads the same file) after the backend
    # already committed some/all of the batch. Without this guard, the retry
    # silently doubles every bill -- same vendor, same bill_no, same amounts.
    pb, db = _setup(monkeypatch)
    first = pb.bulk_create_purchase_bills(_BulkPayload([_bill_dict("VINV-001"), _bill_dict("VINV-002")]), CALLER)
    assert len(first["data"]["created"]) == 2

    retry = pb.bulk_create_purchase_bills(
        _BulkPayload([_bill_dict("VINV-001"), _bill_dict("VINV-002"), _bill_dict("VINV-003")]), CALLER
    )

    assert len(retry["data"]["created"]) == 1
    assert retry["data"]["created"][0]["bill_no"] == "VINV-003"
    assert {s["bill_no"] for s in retry["data"]["skipped"]} == {"VINV-001", "VINV-002"}
    all_bills = [b for b in db.rows("purchase_bills") if b.get("firm_id") == FIRM]
    assert len(all_bills) == 3  # not 5 -- the duplicates were never inserted


def test_bulk_create_skips_duplicate_bill_no_within_same_batch(monkeypatch):
    # Two rows in the SAME upload sharing a vendor+bill_no (e.g. a bad CSV, or
    # the frontend accidentally sending a row twice) must not both land —
    # mirrors bulk_create_customers' within-batch dedup.
    pb, db = _setup(monkeypatch)
    resp = pb.bulk_create_purchase_bills(
        _BulkPayload([_bill_dict("VINV-DUP"), _bill_dict("VINV-DUP")]), CALLER
    )
    assert len(resp["data"]["created"]) == 1
    assert len(resp["data"]["skipped"]) == 1


def test_bulk_create_prefetches_vendor_and_client_once_not_per_bill(monkeypatch):
    # The whole point of bulk_cache: a real import naturally bills the same
    # vendor many times, so a per-row vendor/client lookup (what this used to
    # do before the fix) is exactly the N+1 pattern that made a big products/
    # services import hang long enough to trip the frontend's own timeout.
    pb, db = _setup(monkeypatch)
    calls = {"vendors": 0, "clients": 0}
    orig_table = db.table

    def counting_table(name):
        if name in calls:
            calls[name] += 1
        return orig_table(name)

    monkeypatch.setattr(db, "table", counting_table)

    payload = _BulkPayload([_bill_dict(f"VINV-{i:03d}") for i in range(1, 6)])
    resp = pb.bulk_create_purchase_bills(payload, CALLER)

    assert resp["success"] is True
    assert len(resp["data"]["created"]) == 5
    assert calls["vendors"] == 1
    assert calls["clients"] == 1
