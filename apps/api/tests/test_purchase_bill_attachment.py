"""
Purchase Bill invoice attachment — retain the originally uploaded file as ITC/
audit evidence (CGST Rule 36(1) conditions ITC on possession of the vendor's
tax invoice). Prior to this, extract-invoice read the file into memory for AI
OCR and discarded it; nothing was ever persisted.

Covers:
  * _upload_bill_document: best-effort, never blocks extraction on failure
  * extract-invoice: document_url flows through on both success AND a failed
    extraction (the attachment is independent of whether OCR succeeded)
  * PurchaseBillIn.document_url is persisted on create
  * GET /{bill_id}/document-url mints a fresh signed URL, 404s cleanly
"""
from unittest.mock import MagicMock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from core.auth import get_current_user
import routers.purchase_bills as pb
from models.invoices import PurchaseBillIn, PurchaseBillLineIn
from tests.e2e_harness import FakeDB, wire_e2e, seed_standard_coa

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@firma.test", "role": "Partner"}
PARTNER_A = {"id": "u-a", "auth_user_id": "u-a", "firm_id": "firm-aaa", "role": "Partner", "email": "a@f"}


def _client_for(router, user):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


# ── _upload_bill_document — best-effort, never fatal ────────────────────────

class TestUploadBillDocument:
    def test_returns_none_when_storage_not_configured(self, monkeypatch):
        import routers.document_intelligence_v1 as mod
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        assert mod._upload_bill_document(b"bytes", "application/pdf", "x.pdf", "firm-1", "client-1") is None

    def test_returns_none_without_firm_id(self, monkeypatch):
        import routers.document_intelligence_v1 as mod
        monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.co")
        assert mod._upload_bill_document(b"bytes", "application/pdf", "x.pdf", None, "client-1") is None

    def test_uploads_and_returns_storage_path(self, monkeypatch):
        import routers.document_intelligence_v1 as mod
        monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.co")
        fake_bucket = MagicMock()
        fake_sb = MagicMock()
        fake_sb.storage.from_.return_value = fake_bucket
        monkeypatch.setattr("core.supabase_client.get_supabase", lambda: fake_sb)

        path = mod._upload_bill_document(b"bytes", "application/pdf", "invoice.pdf", "firm-1", "client-1")

        assert path is not None
        assert path.startswith("firm-1/client-1/purchase_bill/")
        assert path.endswith("_invoice.pdf")
        fake_sb.storage.from_.assert_called_once_with("Documents")
        fake_bucket.upload.assert_called_once()

    def test_storage_failure_is_non_fatal(self, monkeypatch):
        """A broken bucket/network must never surface as a 500 from
        extract-invoice — attachment is best-effort."""
        import routers.document_intelligence_v1 as mod
        monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.co")
        fake_sb = MagicMock()
        fake_sb.storage.from_.side_effect = RuntimeError("bucket unreachable")
        monkeypatch.setattr("core.supabase_client.get_supabase", lambda: fake_sb)

        path = mod._upload_bill_document(b"bytes", "application/pdf", "x.pdf", "firm-1", "client-1")
        assert path is None


# ── extract-invoice endpoint — document_url flows through both branches ─────

class TestExtractInvoiceAttachment:
    def test_document_url_included_on_successful_extraction(self, monkeypatch):
        import routers.document_intelligence_v1 as mod
        monkeypatch.setattr(mod, "_GROQ_KEY", "fake-key")
        monkeypatch.setattr(mod, "_groq_extract_text", MagicMock(return_value={
            "vendor_name": "V", "vendor_gstin": None, "invoice_no": "I-1", "invoice_date": None,
            "taxable_amount_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "igst_paise": 0,
            "total_paise": 0, "line_items": [],
        }))
        monkeypatch.setattr(mod, "_upload_bill_document", MagicMock(return_value="firm-aaa/c-001/purchase_bill/abc_invoice.pdf"))
        c = _client_for(mod.router, PARTNER_A)
        files = {"file": ("invoice.pdf", b"%PDF-1.4 fake bytes", "application/pdf")}
        r = c.post("/api/document-intelligence-v1/extract-invoice", files=files, data={"client_id": "c-001"})
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["data"]["document_url"] == "firm-aaa/c-001/purchase_bill/abc_invoice.pdf"

    def test_document_url_still_returned_when_extraction_fails(self, monkeypatch):
        """The original file is retained as evidence even when Groq fails —
        the CA enters the bill manually but the attachment isn't lost."""
        import routers.document_intelligence_v1 as mod
        monkeypatch.setattr(mod, "_GROQ_KEY", "fake-key")
        monkeypatch.setattr(mod, "_groq_extract_text", MagicMock(side_effect=RuntimeError("groq down")))
        monkeypatch.setattr(mod, "_upload_bill_document", MagicMock(return_value="firm-aaa/c-001/purchase_bill/abc_invoice.pdf"))
        c = _client_for(mod.router, PARTNER_A)
        files = {"file": ("invoice.pdf", b"%PDF-1.4 fake bytes", "application/pdf")}
        r = c.post("/api/document-intelligence-v1/extract-invoice", files=files, data={"client_id": "c-001"})
        assert r.status_code == 502
        body = r.json()
        assert body["success"] is False
        assert body["data"]["document_url"] == "firm-aaa/c-001/purchase_bill/abc_invoice.pdf"

    def test_document_url_null_when_upload_failed(self, monkeypatch):
        import routers.document_intelligence_v1 as mod
        monkeypatch.setattr(mod, "_GROQ_KEY", "fake-key")
        monkeypatch.setattr(mod, "_groq_extract_text", MagicMock(return_value={
            "vendor_name": "V", "vendor_gstin": None, "invoice_no": "I-1", "invoice_date": None,
            "taxable_amount_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "igst_paise": 0,
            "total_paise": 0, "line_items": [],
        }))
        monkeypatch.setattr(mod, "_upload_bill_document", MagicMock(return_value=None))
        c = _client_for(mod.router, PARTNER_A)
        files = {"file": ("invoice.pdf", b"%PDF-1.4 fake bytes", "application/pdf")}
        r = c.post("/api/document-intelligence-v1/extract-invoice", files=files, data={"client_id": "c-001"})
        assert r.status_code == 200
        body = r.json()
        assert body["data"]["document_url"] is None


# ── purchase-bill create + document-url retrieval ────────────────────────────

class _FakeBucket:
    def __init__(self, signed_url):
        self._signed_url = signed_url

    def create_signed_url(self, path, expires_in=3600):
        return {"signedURL": self._signed_url, "path": path}


class _FakeStorage:
    def __init__(self, signed_url="https://signed.example/fake-url"):
        self._bucket = _FakeBucket(signed_url)

    def from_(self, bucket_name):
        assert bucket_name == "Documents"
        return self._bucket


def _setup(monkeypatch):
    db = FakeDB()
    wire_e2e(monkeypatch, db, [pb])
    db.storage = _FakeStorage()
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    db.seed("vendors", {"id": "VEND", "firm_id": FIRM, "client_id": "CLI",
                        "name": "Supplier Co", "state_code": "27", "gstin": "27PQRST9012K1Z8",
                        "pan": "PQRST9012K", "is_active": True, "tds_applicable": False,
                        "credit_days": 30})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI",
                                  "name": "Consulting", "kind": "service"})
    return db


def _bill(**over):
    kw = dict(client_id="CLI", vendor_id="VEND", bill_date="2026-04-10", bill_no="AT-001",
              lines=[PurchaseBillLineIn(description="X", hsn_sac="9982", quantity=1,
                                        rate_paise=1_000_000, gst_rate_percent=18.0,
                                        service_catalogue_id="SVC-1")])
    kw.update(over)
    return PurchaseBillIn(**kw)


def test_create_bill_persists_document_url(monkeypatch):
    _setup(monkeypatch)
    bill = pb.create_purchase_bill(_bill(document_url="FIRM-A/CLI/purchase_bill/xyz_invoice.pdf"), CALLER)["data"]
    assert bill["document_url"] == "FIRM-A/CLI/purchase_bill/xyz_invoice.pdf"


def test_create_bill_without_attachment_leaves_document_url_none(monkeypatch):
    _setup(monkeypatch)
    bill = pb.create_purchase_bill(_bill(), CALLER)["data"]
    assert bill.get("document_url") is None


def test_document_url_endpoint_mints_fresh_signed_url(monkeypatch):
    db = _setup(monkeypatch)
    bill = pb.create_purchase_bill(_bill(document_url="FIRM-A/CLI/purchase_bill/xyz_invoice.pdf"), CALLER)["data"]

    resp = pb.get_purchase_bill_document_url(bill["id"], CALLER)
    assert resp["success"] is True
    assert resp["data"]["url"] == "https://signed.example/fake-url"


def test_document_url_endpoint_404s_when_nothing_attached(monkeypatch):
    _setup(monkeypatch)
    bill = pb.create_purchase_bill(_bill(), CALLER)["data"]

    with pytest.raises(HTTPException) as ei:
        pb.get_purchase_bill_document_url(bill["id"], CALLER)
    assert ei.value.status_code == 404


def test_document_url_endpoint_404s_for_unknown_bill(monkeypatch):
    _setup(monkeypatch)
    with pytest.raises(HTTPException) as ei:
        pb.get_purchase_bill_document_url("no-such-bill", CALLER)
    assert ei.value.status_code == 404


def test_document_url_endpoint_firm_scoped(monkeypatch):
    """A different firm's caller must not be able to fetch this bill's
    attachment — same tenant-isolation rule as every other bill endpoint."""
    _setup(monkeypatch)
    bill = pb.create_purchase_bill(_bill(document_url="FIRM-A/CLI/purchase_bill/xyz_invoice.pdf"), CALLER)["data"]

    other_firm_caller = {"firm_id": "FIRM-B", "auth_user_id": "u2", "email": "ca@firmb.test", "role": "Partner"}
    with pytest.raises(HTTPException) as ei:
        pb.get_purchase_bill_document_url(bill["id"], other_firm_caller)
    assert ei.value.status_code == 404


def test_attachment_editable_post_receipt_as_soft_field(monkeypatch):
    """A CA scanning a paper copy after the bill was already received can
    still attach it — document_url is in _SOFT_BILL_UPDATE_FIELDS."""
    from models.invoices import PurchaseBillUpdateIn
    db = _setup(monkeypatch)
    bill = pb.create_purchase_bill(_bill(), CALLER)["data"]

    for row in db.rows("purchase_bills"):
        if row["id"] == bill["id"]:
            row["status"] = "received"

    resp = pb.update_purchase_bill(bill["id"], PurchaseBillUpdateIn(document_url="FIRM-A/CLI/purchase_bill/late_scan.pdf"), CALLER)
    assert resp["success"] is True, resp
    assert resp["data"]["document_url"] == "FIRM-A/CLI/purchase_bill/late_scan.pdf"
