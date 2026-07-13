"""
R2.8/F19 — AI extraction must stop fabricating data and stop persisting
mock-derived notices/tasks; the AI Copilot's firm-context builder must be
firm-scoped.

Covers:
  1. document-intelligence-v1 (invoice extraction): success path works;
     a missing GROQ_API_KEY or a failed Groq call must surface an honest
     failure — never the old hardcoded "Sample Vendor Pvt Ltd" mock payload.
  2. document-intelligence-v2 (notice extraction): success path still
     persists a government_notices row + linked task; a missing key or a
     failed Groq call must persist NOTHING (no notice, no task, no
     partner notification) — previously a full mock record was always
     created regardless of extraction outcome.
  3. Cross-firm tenancy: domain/task_service.py's overdue-task count, and
     routers/ai_copilot.py's `_build_firm_context`, must be scoped to the
     caller's own firm rather than defaulting to a platform-wide query.
"""
from unittest.mock import patch, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user

FIRM_A = "firm-aaa"
FIRM_B = "firm-bbb"
PARTNER_A = {"id": "u-a", "auth_user_id": "u-a", "firm_id": FIRM_A, "role": "Partner", "email": "a@f"}
PARTNER_B = {"id": "u-b", "auth_user_id": "u-b", "firm_id": FIRM_B, "role": "Partner", "email": "b@f"}


def _client_for(router, user):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


# ─── 1. document-intelligence-v1: invoice extraction ────────────────────────

class TestInvoiceExtractionV1:
    def test_successful_extraction_returns_real_data(self, monkeypatch):
        import routers.document_intelligence_v1 as mod
        monkeypatch.setattr(mod, "_GROQ_KEY", "fake-key")
        real = {
            "vendor_name": "Real Vendor Ltd",
            "vendor_gstin": "27AAAAA0000A1Z5",
            "invoice_no": "INV-777",
            "invoice_date": "2026-01-01",
            "taxable_amount_paise": 500000,
            "cgst_paise": 45000,
            "sgst_paise": 45000,
            "igst_paise": 0,
            "total_paise": 590000,
            "line_items": [],
        }
        monkeypatch.setattr(mod, "_groq_extract_text", MagicMock(return_value=real))
        c = _client_for(mod.router, PARTNER_A)
        files = {"file": ("invoice.pdf", b"%PDF-1.4 fake bytes", "application/pdf")}
        data = {"client_id": "c-001"}
        r = c.post("/api/document-intelligence-v1/extract-invoice", files=files, data=data)
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["error"] is None
        assert body["data"]["extracted"]["vendor_name"] == "Real Vendor Ltd"
        assert body["data"]["extracted"]["invoice_no"] == "INV-777"
        assert body["data"]["requires_review"] is True

    def test_missing_groq_key_returns_honest_failure_not_mock(self, monkeypatch):
        import routers.document_intelligence_v1 as mod
        monkeypatch.setattr(mod, "_GROQ_KEY", "")
        c = _client_for(mod.router, PARTNER_A)
        files = {"file": ("invoice.pdf", b"%PDF-1.4 fake bytes", "application/pdf")}
        data = {"client_id": "c-001"}
        r = c.post("/api/document-intelligence-v1/extract-invoice", files=files, data=data)
        assert r.status_code == 503
        body = r.json()
        assert body["success"] is False
        assert body["data"] is None
        assert "not configured" in body["error"]
        # Never leak which AI provider/env var backs this feature — an
        # internal implementation detail, and not actionable for the CA
        # (they can't set env vars on the server themselves).
        assert "GROQ" not in body["error"]
        # The old mock fallback must be completely gone.
        assert "Sample Vendor" not in str(body)
        assert "INV-2025-001" not in str(body)

    def test_groq_failure_returns_honest_failure_not_mock(self, monkeypatch):
        import routers.document_intelligence_v1 as mod
        monkeypatch.setattr(mod, "_GROQ_KEY", "fake-key")
        monkeypatch.setattr(mod, "_groq_extract_text", MagicMock(side_effect=RuntimeError("groq is down")))
        c = _client_for(mod.router, PARTNER_A)
        files = {"file": ("invoice.pdf", b"%PDF-1.4 fake bytes", "application/pdf")}
        data = {"client_id": "c-001"}
        r = c.post("/api/document-intelligence-v1/extract-invoice", files=files, data=data)
        assert r.status_code == 502
        body = r.json()
        assert body["success"] is False
        assert body["data"] is None
        assert "Sample Vendor" not in str(body)
        assert "_is_mock" not in str(body)

    def test_mock_extraction_helper_removed(self):
        """The fabrication helper itself must no longer exist on the module."""
        import routers.document_intelligence_v1 as mod
        assert not hasattr(mod, "_mock_extraction")

    def test_image_upload_routes_through_the_vision_extractor_not_text(self, monkeypatch):
        """BUG FIX: a JPEG/PNG upload must call _gemini_extract_image (which
        sends the actual image bytes to a vision-capable model), never
        _groq_extract_text (which previously received nothing but a
        meaningless base64 snippet of the raw bytes dressed up as a text
        "note" — the model had no way to read the image, so every photo
        upload silently returned near-empty fields). Images route through
        Gemini specifically because Groq's own vision model returned a live
        404 model_not_found on this account — see _run_extraction."""
        import routers.document_intelligence_v1 as mod
        monkeypatch.setattr(mod, "_GEMINI_KEY", "fake-key")
        text_mock = MagicMock(side_effect=AssertionError("must not call the text extractor for an image"))
        image_mock = MagicMock(return_value={
            "vendor_name": "Photo Vendor", "vendor_gstin": None, "invoice_no": "PH-1",
            "invoice_date": None, "taxable_amount_paise": 0, "cgst_paise": 0,
            "sgst_paise": 0, "igst_paise": 0, "total_paise": 0, "line_items": [],
        })
        monkeypatch.setattr(mod, "_groq_extract_text", text_mock)
        monkeypatch.setattr(mod, "_gemini_extract_image", image_mock)
        c = _client_for(mod.router, PARTNER_A)
        files = {"file": ("bill.jpg", b"\xff\xd8\xff fake jpeg bytes", "image/jpeg")}
        data = {"client_id": "c-001"}
        r = c.post("/api/document-intelligence-v1/extract-invoice", files=files, data=data)
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["data"]["extracted"]["vendor_name"] == "Photo Vendor"
        image_mock.assert_called_once()
        text_mock.assert_not_called()

    def test_pdf_upload_still_routes_through_the_text_extractor(self, monkeypatch):
        import routers.document_intelligence_v1 as mod
        monkeypatch.setattr(mod, "_GROQ_KEY", "fake-key")
        text_mock = MagicMock(return_value={
            "vendor_name": "PDF Vendor", "vendor_gstin": None, "invoice_no": "PD-1",
            "invoice_date": None, "taxable_amount_paise": 0, "cgst_paise": 0,
            "sgst_paise": 0, "igst_paise": 0, "total_paise": 0, "line_items": [],
        })
        image_mock = MagicMock(side_effect=AssertionError("must not call the vision extractor for a PDF"))
        monkeypatch.setattr(mod, "_groq_extract_text", text_mock)
        monkeypatch.setattr(mod, "_gemini_extract_image", image_mock)
        c = _client_for(mod.router, PARTNER_A)
        files = {"file": ("invoice.pdf", b"%PDF-1.4 fake bytes", "application/pdf")}
        data = {"client_id": "c-001"}
        r = c.post("/api/document-intelligence-v1/extract-invoice", files=files, data=data)
        assert r.status_code == 200
        assert r.json()["data"]["extracted"]["vendor_name"] == "PDF Vendor"
        text_mock.assert_called_once()
        image_mock.assert_not_called()

    def test_image_upload_without_gemini_key_returns_honest_failure(self, monkeypatch):
        """PDFs and images now need different provider keys — an image
        upload must not silently fall through to the PDF/Groq path or
        fabricate data just because GROQ_API_KEY happens to be set."""
        import routers.document_intelligence_v1 as mod
        monkeypatch.setattr(mod, "_GROQ_KEY", "fake-key")
        monkeypatch.setattr(mod, "_GEMINI_KEY", "")
        c = _client_for(mod.router, PARTNER_A)
        files = {"file": ("bill.jpg", b"\xff\xd8\xff fake jpeg bytes", "image/jpeg")}
        data = {"client_id": "c-001"}
        r = c.post("/api/document-intelligence-v1/extract-invoice", files=files, data=data)
        assert r.status_code == 503
        body = r.json()
        assert body["success"] is False
        assert "not configured" in body["error"]
        assert "GEMINI" not in body["error"]

    def test_parse_extraction_json_strips_markdown_fences_and_coerces_paise_fields(self):
        import routers.document_intelligence_v1 as mod
        raw = (
            "```json\n"
            '{"vendor_name": "V", "vendor_gstin": null, "invoice_no": "I-1", '
            '"invoice_date": null, "taxable_amount_paise": "500000", "cgst_paise": null, '
            '"sgst_paise": null, "igst_paise": 90000, "total_paise": "590000", '
            '"line_items": [{"description": "x", "hsn_sac": null, "quantity": "2", '
            '"rate_paise": "1000", "gst_rate_bps": null}]}'
            "\n```"
        )
        data = mod._parse_extraction_json(raw)
        assert data["taxable_amount_paise"] == 500000
        assert data["cgst_paise"] == 0  # null coerced to 0, not left as None
        assert data["igst_paise"] == 90000
        assert data["total_paise"] == 590000
        li = data["line_items"][0]
        assert li["rate_paise"] == 1000
        assert li["quantity"] == 2.0
        assert li["gst_rate_bps"] == 1800  # missing/null defaults to 18%

    def test_gemini_extract_image_sends_the_actual_image_bytes(self, monkeypatch):
        """Regression guard for the fix itself: the vision call must include
        a Part built from the real uploaded bytes (not a text-only prompt),
        and must go to the configured Gemini model."""
        import routers.document_intelligence_v1 as mod
        from google.genai import types

        captured = {}

        class _FakeResponse:
            text = '{"vendor_name": "V", "vendor_gstin": null, "invoice_no": null, "invoice_date": null, "taxable_amount_paise": 0, "cgst_paise": 0, "sgst_paise": 0, "igst_paise": 0, "total_paise": 0, "line_items": []}'

        class _FakeModels:
            def generate_content(self, **kwargs):
                captured.update(kwargs)
                return _FakeResponse()

        class _FakeGeminiClient:
            def __init__(self, api_key=None):
                captured["api_key"] = api_key
            models = _FakeModels()

        monkeypatch.setattr(mod, "_GEMINI_KEY", "fake-key")
        monkeypatch.setattr("google.genai.Client", _FakeGeminiClient)

        content = b"\xff\xd8\xff fake jpeg bytes"
        mod._gemini_extract_image(content, "image/jpeg")

        assert captured["api_key"] == "fake-key"
        assert captured["model"] == mod._GEMINI_VISION_MODEL
        image_part = next(p for p in captured["contents"] if isinstance(p, types.Part))
        assert image_part.inline_data.data == content
        assert image_part.inline_data.mime_type == "image/jpeg"
        assert any(isinstance(p, str) and "expert Indian accountant" in p for p in captured["contents"])


# ─── 2. document-intelligence-v2: notice extraction ─────────────────────────

class TestNoticeExtractionV2:
    def _reset(self, mod):
        mod._MOCK_NOTICES.clear()

    def test_successful_extraction_persists_notice_and_task(self, monkeypatch):
        import routers.document_intelligence_v2 as mod
        self._reset(mod)
        monkeypatch.setattr(mod, "_GROQ_KEY", "fake-key")
        real = {
            "authority": "GSTN",
            "notice_type": "gst_scrutiny",
            "reference_no": "REAL-REF-42",
            "issue_date": "2026-01-01",
            "response_due_date": "2026-01-15",
            "description": "Respond to scrutiny notice.",
        }
        monkeypatch.setattr(mod, "_extract_with_groq", MagicMock(return_value=real))
        c = _client_for(mod.router, PARTNER_A)
        r = c.post("/api/document-intelligence-v2/notices/extract", json={
            "client_id": "c-001",
            "document_text": "Please respond to this GST scrutiny notice.",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["data"]["reference_no"] == "REAL-REF-42"
        assert body["data"]["ca_approved"] is False
        assert len(mod._MOCK_NOTICES) == 1
        stored = list(mod._MOCK_NOTICES.values())[0]
        assert stored["reference_no"] == "REAL-REF-42"
        assert stored["task_id"] is not None
        assert stored["firm_id"] == FIRM_A

    def test_missing_groq_key_persists_nothing(self, monkeypatch):
        import routers.document_intelligence_v2 as mod
        self._reset(mod)
        monkeypatch.setattr(mod, "_GROQ_KEY", "")
        c = _client_for(mod.router, PARTNER_A)
        r = c.post("/api/document-intelligence-v2/notices/extract", json={
            "client_id": "c-001",
            "document_text": "This is a GST scrutiny notice, reference ABC123.",
        })
        assert r.status_code == 503
        body = r.json()
        assert body["success"] is False
        assert body["data"] is None
        assert "not configured" in body["error"]
        assert "GROQ" not in body["error"]
        # Nothing must be persisted for a failed/unavailable extraction.
        assert mod._MOCK_NOTICES == {}
        assert "REF-MOCK-001" not in str(body)

    def test_groq_failure_persists_nothing(self, monkeypatch):
        import routers.document_intelligence_v2 as mod
        self._reset(mod)
        monkeypatch.setattr(mod, "_GROQ_KEY", "fake-key")
        monkeypatch.setattr(mod, "_extract_with_groq", MagicMock(side_effect=RuntimeError("groq is down")))
        c = _client_for(mod.router, PARTNER_A)
        r = c.post("/api/document-intelligence-v2/notices/extract", json={
            "client_id": "c-001",
            "document_text": "This is a GST scrutiny notice.",
        })
        assert r.status_code == 502
        body = r.json()
        assert body["success"] is False
        assert body["data"] is None
        assert mod._MOCK_NOTICES == {}
        assert "REF-MOCK-001" not in str(body)

    def test_mock_extract_helper_removed(self):
        """The fabrication helper itself must no longer exist on the module."""
        import routers.document_intelligence_v2 as mod
        assert not hasattr(mod, "_mock_extract")


# ─── 3a. documents.py /parse: dead mock endpoint no longer fabricates ───────

class TestDocumentsParseNoLongerFabricates:
    def test_parse_returns_honest_not_implemented(self):
        import routers.documents as mod
        c = _client_for(mod.router, PARTNER_A)
        files = {"file": ("form16.pdf", b"fake", "application/pdf")}
        data = {"document_type": "form16"}
        r = c.post("/api/documents/parse", files=files, data=data)
        assert r.status_code == 501
        body = r.json()
        assert body["success"] is False
        assert "Rajesh Kumar Sharma" not in str(body)
        assert "TechCorp" not in str(body)

    def test_mock_extraction_constants_removed(self):
        import routers.documents as mod
        assert not hasattr(mod, "MOCK_FORM16_EXTRACTION")
        assert not hasattr(mod, "MOCK_GST_INVOICE_EXTRACTION")


# ─── 3b. Cross-firm tenancy ──────────────────────────────────────────────────

class TestDashboardSummaryOverdueTasksFirmScoped:
    """domain/task_service.py get_dashboard_summary: overdue_tasks must only
    count the caller's own firm. Fixed in R3.5c: task_repo.find_overdue()
    now takes a firm_id parameter and pushes the scope to the query
    (repositories/task_repository.py) instead of scanning every firm's
    tasks and post-filtering in Python — same fix applied to
    domain/ai_copilot_service.py's call sites (R3.5a)."""

    def test_overdue_tasks_scoped_to_firm(self):
        from domain.task_service import task_domain_service
        overdue_mixed = [
            {"id": "t1", "firm_id": FIRM_A, "client_id": "c1", "status": "open", "due_date": "2020-01-01"},
            {"id": "t2", "firm_id": FIRM_B, "client_id": "c2", "status": "open", "due_date": "2020-01-01"},
            {"id": "t3", "firm_id": FIRM_B, "client_id": "c3", "status": "open", "due_date": "2020-01-01"},
        ]

        def fake_find_overdue(firm_id=None):
            return [t for t in overdue_mixed if not firm_id or t["firm_id"] == firm_id]

        with patch("domain.task_service.client_repo") as mock_clients, \
             patch("domain.task_service.task_repo") as mock_tasks, \
             patch("repositories.compliance_repository.compliance_repo") as mock_ctasks, \
             patch("domain.compliance_record_service.compliance_record_service") as mock_records:
            mock_clients.find_all.return_value = []
            mock_tasks.find_all.return_value = []
            mock_tasks.find_overdue.side_effect = fake_find_overdue
            mock_ctasks.find_all.return_value = []
            mock_records.list_records.return_value = []

            result_a = task_domain_service.get_dashboard_summary(firm_id=FIRM_A)
            result_b = task_domain_service.get_dashboard_summary(firm_id=FIRM_B)

        assert result_a["overdue_tasks"] == 1   # only t1 belongs to FIRM_A
        assert result_b["overdue_tasks"] == 2   # t2 + t3 belong to FIRM_B
        # The scoping is now pushed at the call site, not post-filtered —
        # confirm get_dashboard_summary actually passes firm_id through.
        mock_tasks.find_overdue.assert_any_call(firm_id=FIRM_A)
        mock_tasks.find_overdue.assert_any_call(firm_id=FIRM_B)


class TestAiCopilotFirmContextScoping:
    """routers/ai_copilot.py `_build_firm_context` previously called
    get_dashboard_summary()/get_firm_summary()/get_risk_dashboard_stats()
    with no firm_id at all (defaulting to firm-wide/None), leaking every
    firm's counts into the Groq system prompt. Every call must now receive
    the caller's firm_id."""

    def test_build_firm_context_passes_firm_id_to_every_service(self, monkeypatch):
        import routers.ai_copilot as mod
        import domain.task_service as task_mod
        import domain.compliance_record_service as comp_mod
        import domain.risk_engine as risk_mod
        import repositories.client_repository as client_mod

        captured = {}

        class FakeTaskDomainService:
            def get_dashboard_summary(self, firm_id=None):
                captured["dashboard_firm_id"] = firm_id
                return {"active_clients": 1, "overdue_tasks": 0}

        class FakeComplianceService:
            def get_firm_summary(self, firm_id=None, allowed_client_ids=None):
                captured["compliance_firm_id"] = firm_id
                return {"overdue": 0, "ready_to_file": 0}

        class FakeClientRepo:
            def find_all(self, firm_id=None):
                captured["clients_firm_id"] = firm_id
                return []

        def fake_risk_stats(firm_id=None):
            captured["risk_firm_id"] = firm_id
            return {"critical": 0, "high": 0, "medium": 0, "total_open": 0}

        monkeypatch.setattr(task_mod, "TaskDomainService", FakeTaskDomainService)
        monkeypatch.setattr(comp_mod, "compliance_record_service", FakeComplianceService())
        monkeypatch.setattr(risk_mod, "get_risk_dashboard_stats", fake_risk_stats)
        monkeypatch.setattr(client_mod, "client_repo", FakeClientRepo())

        mod._build_firm_context(FIRM_A)

        assert captured["dashboard_firm_id"] == FIRM_A
        assert captured["compliance_firm_id"] == FIRM_A
        assert captured["risk_firm_id"] == FIRM_A
        assert captured["clients_firm_id"] == FIRM_A

    def test_build_firm_context_isolates_two_firms(self, monkeypatch):
        """A cross-firm sanity check: firm B's context must not reflect
        firm A's data even when both firms have rows in the same store."""
        import routers.ai_copilot as mod
        import domain.task_service as task_mod
        import domain.compliance_record_service as comp_mod
        import domain.risk_engine as risk_mod
        import repositories.client_repository as client_mod

        ALL_CLIENTS = [
            {"id": "c1", "client_name": "Firm A Client", "firm_id": FIRM_A},
            {"id": "c2", "client_name": "Firm B Client", "firm_id": FIRM_B},
        ]

        class FakeTaskDomainService:
            def get_dashboard_summary(self, firm_id=None):
                return {"active_clients": len([c for c in ALL_CLIENTS if c["firm_id"] == firm_id])}

        class FakeComplianceService:
            def get_firm_summary(self, firm_id=None, allowed_client_ids=None):
                return {}

        class FakeClientRepo:
            def find_all(self, firm_id=None):
                return [c for c in ALL_CLIENTS if c["firm_id"] == firm_id]

        def fake_risk_stats(firm_id=None):
            return {}

        monkeypatch.setattr(task_mod, "TaskDomainService", FakeTaskDomainService)
        monkeypatch.setattr(comp_mod, "compliance_record_service", FakeComplianceService())
        monkeypatch.setattr(risk_mod, "get_risk_dashboard_stats", fake_risk_stats)
        monkeypatch.setattr(client_mod, "client_repo", FakeClientRepo())

        ctx_a = mod._build_firm_context(FIRM_A)
        ctx_b = mod._build_firm_context(FIRM_B)

        assert "Firm A Client" in ctx_a
        assert "Firm B Client" not in ctx_a
        assert "Firm B Client" in ctx_b
        assert "Firm A Client" not in ctx_b


# ─── 4. GET /api/ai-copilot/firm-context: sibling handler, same tenancy fix ──

class TestAiCopilotGetFirmContextScoping:
    """routers/ai_copilot.py `get_firm_context()` (GET /firm-context) is a
    separate handler from `_build_firm_context()` (used by POST /chat) and
    had its own, un-scoped `TaskDomainService().get_dashboard_summary()` call
    (no firm_id) even after `_build_firm_context` was fixed — leaking
    platform-wide active_clients/tasks counts into a response nominally
    scoped to the caller's own firm. `get_firm_summary`/`get_risk_dashboard_stats`/
    `client_repo.find_all` in the same handler were already correctly scoped."""

    def test_get_firm_context_passes_firm_id_to_dashboard_summary(self, monkeypatch):
        import routers.ai_copilot as mod
        import domain.task_service as task_mod

        captured = {}

        class FakeTaskDomainService:
            def get_dashboard_summary(self, firm_id=None):
                captured["dashboard_firm_id"] = firm_id
                return {"active_clients": 0, "overdue_tasks": 0}

        monkeypatch.setattr(task_mod, "TaskDomainService", FakeTaskDomainService)

        mod.get_firm_context(current_user=PARTNER_A)

        assert captured["dashboard_firm_id"] == FIRM_A

    def test_get_firm_context_isolates_two_firms(self, monkeypatch):
        """Firm A (1 client) must not see Firm B's aggregate counts (2 clients)
        in active_clients / tasks.overdue, even though both firms share the
        same underlying (unscoped-by-default) task service."""
        import routers.ai_copilot as mod
        import domain.task_service as task_mod
        import domain.compliance_record_service as comp_mod
        import domain.risk_engine as risk_mod
        import repositories.client_repository as client_mod

        ALL_CLIENTS = [
            {"id": "c1", "client_name": "Firm A Client 1", "firm_id": FIRM_A, "status": "active"},
            {"id": "c2", "client_name": "Firm B Client 1", "firm_id": FIRM_B, "status": "active"},
            {"id": "c3", "client_name": "Firm B Client 2", "firm_id": FIRM_B, "status": "active"},
        ]
        ALL_TASKS_OVERDUE = {FIRM_A: 1, FIRM_B: 5}

        class FakeTaskDomainService:
            def get_dashboard_summary(self, firm_id=None):
                return {
                    "active_clients": len([c for c in ALL_CLIENTS if c["firm_id"] == firm_id]),
                    "overdue_tasks": ALL_TASKS_OVERDUE.get(firm_id, 0),
                }

        class FakeComplianceService:
            def get_firm_summary(self, firm_id=None, allowed_client_ids=None):
                return {}

        class FakeClientRepo:
            def find_all(self, firm_id=None):
                return [c for c in ALL_CLIENTS if c["firm_id"] == firm_id]

        def fake_risk_stats(firm_id=None):
            return {}

        monkeypatch.setattr(task_mod, "TaskDomainService", FakeTaskDomainService)
        monkeypatch.setattr(comp_mod, "compliance_record_service", FakeComplianceService())
        monkeypatch.setattr(risk_mod, "get_risk_dashboard_stats", fake_risk_stats)
        monkeypatch.setattr(client_mod, "client_repo", FakeClientRepo())

        resp_a = mod.get_firm_context(current_user=PARTNER_A)
        resp_b = mod.get_firm_context(current_user=PARTNER_B)

        assert resp_a["data"]["active_clients"] == 1
        assert resp_a["data"]["tasks"]["overdue"] == 1
        assert resp_b["data"]["active_clients"] == 2
        assert resp_b["data"]["tasks"]["overdue"] == 5


# ─── 5. Legacy unversioned document-intelligence generation retired ─────────

class TestLegacyDocumentIntelligenceRouterRetired:
    """routers/document_intelligence.py (unversioned /api/document-intelligence)
    was a 4th, undisclosed extraction generation serving hardcoded fabricated
    data (fake confidence scores, fake GSTINs/TDS figures) verbatim via
    GET /{doc_id}/extraction — the exact class of fabrication R2.8 eliminated
    in document-intelligence-v1/v2. It has zero real callers (frontend or
    otherwise) and is retired in the R2.8 fix phase; assert it stays unmounted."""

    def test_unversioned_document_intelligence_router_not_mounted(self):
        import main
        paths = {r.path for r in main.app.routes}
        assert "/api/document-intelligence/documents" not in paths
        assert "/api/document-intelligence/{doc_id}/extraction" not in paths
        # v1/v2 (the real, audited generations) remain mounted.
        assert any(p.startswith("/api/document-intelligence-v1") for p in paths)
        assert any(p.startswith("/api/document-intelligence-v2") for p in paths)


# ─── 6. risk_engine.get_risk_dashboard_stats: "resolved" count firm-scoped ──

class TestRiskDashboardStatsResolvedCountFirmScoped:
    """get_risk_dashboard_stats() feeds routers/ai_copilot.py's firm context
    (the same tenancy surface fixed elsewhere in R2.8). The "resolved" count
    previously scanned the raw global MOCK_RISKS list with no firm_id filter
    at all, while every other count in this dict went through the firm-scoped
    get_all_risks(). It must now use get_all_risks(firm_id=..., status="resolved")
    like the "open" count already does."""

    def test_resolved_count_requested_with_caller_firm_id(self, monkeypatch):
        import domain.risk_engine as mod

        calls = []

        def fake_get_all_risks(firm_id=None, client_id=None, severity=None, status="open"):
            calls.append({"firm_id": firm_id, "status": status})
            if status == "resolved":
                return [{"id": "r1", "severity": "low", "resolution_status": "resolved"}]
            return []

        monkeypatch.setattr(mod, "get_all_risks", fake_get_all_risks)

        stats = mod.get_risk_dashboard_stats(firm_id=FIRM_A)

        assert stats["resolved"] == 1
        statuses_by_firm = {(c["firm_id"], c["status"]) for c in calls}
        assert (FIRM_A, "open") in statuses_by_firm
        assert (FIRM_A, "resolved") in statuses_by_firm
        # No call is ever made with firm_id=None (the platform-wide leak).
        assert all(c["firm_id"] == FIRM_A for c in calls)
