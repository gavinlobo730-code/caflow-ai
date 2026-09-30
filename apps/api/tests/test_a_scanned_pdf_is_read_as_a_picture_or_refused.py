"""
A PDF with no text layer is never sent to the text model as base64 noise (ai-03).

WHAT WAS WRONG
    When pdfminer found no text, `_extract_pdf_text` returned
    "[PDF content — base64 prefix, no extractable text layer]: <200 base64 chars>"
    and `_groq_extract_text` sent that to the model under an "extract invoice
    fields" prompt. Nothing refused it, and confidence is presence-based, so a
    plausible invented vendor and invoice number could come back from gibberish —
    on a document a CA is about to book ITC against.

WHAT THIS ASSERTS
    A scan is read as the picture it is (the same Gemini path a photographed
    invoice takes), or refused with a sentence that says what to do — and in NEITHER
    case does the text model see it. A scan too long to be one invoice is refused,
    never read in part.
"""
from __future__ import annotations

import io
from unittest.mock import MagicMock

import pytest
from reportlab.pdfgen import canvas

import routers.document_intelligence_v1 as mod
from tests.test_r2_8_ai_extraction import PARTNER_A, _client_for

READING = {
    "vendor_name": "Scanned Vendor", "vendor_gstin": None, "invoice_no": "SC-1",
    "invoice_date": None, "taxable_amount_paise": 0, "cgst_paise": 0,
    "sgst_paise": 0, "igst_paise": 0, "total_paise": 0, "line_items": [],
}


def _pdf(pages: int, text: str | None) -> bytes:
    """`text=None` draws only shapes, so pdfminer finds nothing — a scan."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for i in range(pages):
        if text is None:
            c.rect(50, 50, 200 + i, 100, fill=1)
        else:
            c.drawString(72, 720, f"{text} page {i + 1}")
        c.showPage()
    c.save()
    return buf.getvalue()


def _upload(content: bytes):
    c = _client_for(mod.router, PARTNER_A)
    return c.post("/api/document-intelligence-v1/extract-invoice",
                  files={"file": ("invoice.pdf", content, "application/pdf")},
                  data={"client_id": "c-001"})


@pytest.fixture
def models(monkeypatch):
    """Both providers present, both mocked; the text model fails the test if asked."""
    text = MagicMock(side_effect=AssertionError("the text model must never see a scan"))
    images = MagicMock(return_value=READING)
    monkeypatch.setattr(mod, "_GROQ_KEY", "g")
    monkeypatch.setattr(mod, "_GEMINI_KEY", "m")
    monkeypatch.setattr(mod, "_groq_extract_text", text)
    monkeypatch.setattr(mod, "_gemini_extract_images", images)
    return text, images


# ── the premise: what a scan looks like to the parser ────────────────────────

def test_a_scan_has_no_text_and_the_helper_says_so_with_none():
    assert mod._extract_pdf_text(_pdf(1, None)) is None


def test_a_digital_invoice_still_has_its_text():
    assert "Tax Invoice" in mod._extract_pdf_text(_pdf(1, "Tax Invoice"))


def test_unreadable_bytes_are_no_text_not_a_stand_in_string():
    assert mod._extract_pdf_text(b"%PDF-1.4 fake bytes") is None


def test_the_base64_stand_in_is_gone_from_the_code():
    import inspect
    src = inspect.getsource(mod)
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert "base64.b64encode" not in code, "a scan must not be dressed as document text"


# ── a scan is read as a picture ──────────────────────────────────────────────

def test_a_scanned_pdf_goes_to_the_image_path_and_never_the_text_model(models):
    text, images = models
    r = _upload(_pdf(2, None))
    assert r.status_code == 200, r.text
    assert r.json()["data"]["extracted"]["vendor_name"] == "Scanned Vendor"
    text.assert_not_called()
    images.assert_called_once()
    pages, mime = images.call_args.args
    assert len(pages) == 2 and mime == "image/png"
    assert all(p.startswith(b"\x89PNG") for p in pages), "real page images, not the file's bytes"


def test_a_digital_pdf_still_takes_the_text_path(models, monkeypatch):
    text, images = models
    text.side_effect = None
    text.return_value = READING
    r = _upload(_pdf(1, "Tax Invoice INV-9"))
    assert r.status_code == 200, r.text
    text.assert_called_once()
    images.assert_not_called()


# ── and where it cannot be, it is refused in words ───────────────────────────

def test_a_scan_with_no_image_reading_is_refused_and_says_what_to_do(models, monkeypatch):
    text, images = models
    monkeypatch.setattr(mod, "_GEMINI_KEY", "")
    r = _upload(_pdf(1, None))
    assert r.status_code == 422
    err = r.json()["error"]
    assert "scan" in err and "photo" in err
    text.assert_not_called()
    images.assert_not_called()


def test_with_no_provider_at_all_the_answer_is_not_configured(models, monkeypatch):
    monkeypatch.setattr(mod, "_GEMINI_KEY", "")
    monkeypatch.setattr(mod, "_GROQ_KEY", "")
    r = _upload(_pdf(1, None))
    assert r.status_code == 503
    assert "not configured" in r.json()["error"]


def test_a_scan_longer_than_one_invoice_is_refused_not_read_in_part(models):
    text, images = models
    r = _upload(_pdf(mod.SCANNED_PDF_PAGE_LIMIT + 1, None))
    assert r.status_code == 422
    assert str(mod.SCANNED_PDF_PAGE_LIMIT + 1) in r.json()["error"]
    images.assert_not_called()
    text.assert_not_called()


def test_a_scan_at_exactly_the_page_limit_is_read(models):
    _, images = models
    assert _upload(_pdf(mod.SCANNED_PDF_PAGE_LIMIT, None)).status_code == 200
    assert len(images.call_args.args[0]) == mod.SCANNED_PDF_PAGE_LIMIT


def test_a_file_that_is_not_a_pdf_at_all_is_refused_not_guessed_at(models):
    text, images = models
    r = _upload(b"%PDF-1.4 this is not really a pdf")
    assert r.status_code == 422
    text.assert_not_called()
    images.assert_not_called()


def test_a_failing_image_reader_is_a_502_with_nothing_invented(models):
    _, images = models
    images.side_effect = RuntimeError("vision is down")
    r = _upload(_pdf(1, None))
    assert r.status_code == 502
    assert r.json()["data"] is None
