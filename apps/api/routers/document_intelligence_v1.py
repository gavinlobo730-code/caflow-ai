"""Document Intelligence v1 — Invoice PDF/Image upload and AI extraction.
Extracts vendor name, GSTIN, invoice number, date, tax values, total amount.
Creates a DRAFT purchase bill — human CA approval required before posting.
# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
"""
import os
import base64
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from models.common import api_response
from core.permissions import rbac
from core.authz import assert_client_access
from services.internal_client_service import assert_partner_for_internal_id

_logger = logging.getLogger("caflow.doc_intelligence_v1")
_GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
# Text-only model for PDFs with embedded text — this path works and is
# unchanged. Overridable without a code change since Groq's model lineup
# changes over time.
_GROQ_TEXT_MODEL = os.environ.get("GROQ_TEXT_MODEL", "llama-3.3-70b-versatile")
# Vision-capable model for photo/scanned invoice uploads (JPEG/PNG) — a
# text-only model cannot read pixels (see _run_extraction's docstring for the
# original bug this replaced: images used to be silently unreadable).
# Previously routed through Groq (meta-llama/llama-4-maverick-17b-128e-
# instruct), which returned a live 404 model_not_found on this account.
# Gemini's free tier is multimodal-native, requires no billing setup, and
# was already provisioned for this project — switched the image path only;
# the PDF/text path above still works fine on Groq and is untouched.
_GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
# gemini-2.5-flash was retired by Google ahead of its announced shutdown
# date (confirmed live 404 "no longer available to new users" — a known,
# reported issue, not specific to this account). gemini-3.5-flash is the
# current free-tier vision-capable model as of this fix.
_GEMINI_VISION_MODEL = os.environ.get("GEMINI_VISION_MODEL", "gemini-3.5-flash")

router = APIRouter(prefix="/api/document-intelligence-v1", tags=["document_intelligence_v1"])

# Same private Storage bucket routers/documents.py uses — reusing its bucket/
# path convention rather than inventing a second one.
_BUCKET = "Documents"

_EXTRACTION_PROMPT = """
You are an expert Indian accountant. Analyse the following invoice document text and extract
the data as valid JSON with exactly these keys:
{
  "vendor_name": "string",
  "vendor_gstin": "string or null",
  "invoice_no": "string",
  "invoice_date": "YYYY-MM-DD or null",
  "taxable_amount_paise": integer (amount in paise, i.e. rupees × 100),
  "cgst_paise": integer,
  "sgst_paise": integer,
  "igst_paise": integer,
  "total_paise": integer,
  "line_items": [
    {
      "description": "string",
      "hsn_sac": "string or null",
      "quantity": number,
      "rate_paise": integer,
      "gst_rate_bps": integer (basis points: 1800 = 18%)
    }
  ]
}

Rules:
- All rupee amounts must be converted to paise (multiply by 100, integer only, no floats).
- If a field is not present in the document, use null or 0 as appropriate.
- GSTIN format is 15 characters: 2-digit state code + 10-char PAN + entity digit + Z + check digit.
- Return ONLY the JSON object, no markdown, no explanation.

Document text:
"""


@router.post("/extract-invoice")
async def extract_invoice(
    file: UploadFile = File(...),
    client_id: str = Form(...),
    current_user: dict = Depends(rbac("document", "write")),
):
    """
    Upload invoice PDF or image. AI extracts fields and returns a DRAFT purchase bill payload.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    Human must review extracted data and call POST /api/purchase-bills to create the bill,
    or POST /api/purchase-bills/from-document to create draft directly.

    Returns:
      extracted data + requires_review: true flag always set.
    """
    # Client scope: multipart form client_id bypasses the central JSON guard, so
    # enforce internal-client (G1) + assignment (M2) here explicitly.
    assert_partner_for_internal_id(client_id, current_user)
    assert_client_access(current_user, client_id)
    # File size guard (10 MB)
    MAX_BYTES = 10 * 1024 * 1024
    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

    content_type = (file.content_type or "").lower()
    filename = file.filename or ""

    # Retain the original file as ITC/audit evidence regardless of whether AI
    # extraction succeeds — CGST Rule 36(1) conditions ITC on possession of
    # the vendor's tax invoice, and extraction only ever reads the bytes into
    # memory. Best-effort: a storage failure must never block extraction or
    # manual bill entry.
    document_url = _upload_bill_document(content, content_type, filename, current_user.get("firm_id"), client_id)

    extracted, error, status_code = _run_extraction(content, content_type, filename)
    if error:
        # R2.8/F19: no more fabricated fallback data — surface the failure
        # honestly so the CA knows to enter the bill manually, instead of a
        # plausible-looking invoice silently flowing into the draft bill form.
        # The attachment (if it uploaded) is still worth returning — the CA
        # can enter the bill by hand and the original stays attached.
        data = {"document_url": document_url} if document_url else None
        return JSONResponse(status_code=status_code, content=api_response(False, data, error))

    return api_response(True, {
        "extracted": extracted,
        "confidence": _estimate_confidence(extracted),
        "requires_review": True,  # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
        "client_id": client_id,
        "document_url": document_url,
    })


def _upload_bill_document(
    content: bytes, content_type: str, filename: str, firm_id: Optional[str], client_id: str
) -> Optional[str]:
    """Best-effort: persist the original uploaded invoice to Supabase Storage
    (bucket/path convention shared with routers/documents.py) so it stays
    retrievable after AI extraction discards the in-memory bytes. Returns the
    storage PATH (never a signed URL — those expire; GET
    /api/purchase-bills/{id}/document-url mints a fresh one on read), or None
    when storage isn't configured or the upload fails. A failed attachment
    must never block extraction or manual bill entry."""
    if not os.environ.get("SUPABASE_URL") or not firm_id:
        return None
    try:
        from core.supabase_client import get_supabase
        sb = get_supabase()
        safe_name = (filename or "upload").replace("/", "_")
        storage_path = f"{firm_id}/{client_id}/purchase_bill/{uuid.uuid4()}_{safe_name}"
        sb.storage.from_(_BUCKET).upload(
            path=storage_path, file=content,
            file_options={"content-type": content_type or "application/octet-stream"},
        )
        return storage_path
    except Exception as e:
        _logger.warning("Purchase-bill invoice attachment upload failed (non-fatal): %s", e)
        return None


def _run_extraction(
    content: bytes, content_type: str, filename: str
) -> tuple[Optional[dict], Optional[str], int]:
    """
    Attempt AI extraction. Never fabricates data: on any failure returns
    (None, reason, http_status) instead of falling back to a mock.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT

    PDFs use Groq (pdfminer text extraction + a text-only model). Images use
    Gemini (a genuinely vision-capable model, sent the real image bytes) —
    a text-only model cannot read pixels, and Groq's own vision offering was
    unavailable on this account (live 404 model_not_found), so the two paths
    now use two different providers rather than forcing one non-working fit.
    """
    is_pdf = "pdf" in content_type or filename.lower().endswith(".pdf")
    if is_pdf and not _GROQ_KEY:
        _logger.info("No GROQ_API_KEY — refusing to fabricate an extraction")
        return None, "AI extraction is not configured on the server", 503
    if not is_pdf and not _GEMINI_KEY:
        _logger.info("No GEMINI_API_KEY — refusing to fabricate an extraction")
        return None, "AI extraction is not configured on the server", 503

    try:
        if is_pdf:
            doc_text = _extract_pdf_text(content)
            return _groq_extract_text(doc_text), None, 200
        return _gemini_extract_image(content, content_type), None, 200
    except Exception as e:
        # Full failure reason (provider, model, exact error) goes to server
        # logs only — never to the client. Which AI vendor/model this app
        # uses under the hood is an internal implementation detail, not
        # something to surface to the CA using the product; it's also not
        # actionable for them ("retry or enter manually" already is).
        _logger.error("AI extraction failed (%s): %s", type(e).__name__, e)
        return None, "AI extraction failed — please retry or enter the bill details manually", 502


def _extract_pdf_text(content: bytes) -> str:
    """Best-effort text extraction from a PDF. Scanned/image-only PDFs (no
    embedded text layer) fall back to base64 noise, same limitation as
    before — pdfminer can't OCR a raster PDF. A genuinely scanned PDF should
    be uploaded as an image instead so it goes through the vision path."""
    try:
        import io
        from pdfminer.high_level import extract_text as pdf_extract
        text = pdf_extract(io.BytesIO(content))
        if text and text.strip():
            return text[:8000]  # cap at 8000 chars for token budget
    except Exception:
        pass
    b64 = base64.b64encode(content[:4096]).decode()
    return f"[PDF content — base64 prefix, no extractable text layer]: {b64[:200]}..."


def _parse_extraction_json(raw: str) -> dict:
    """Shared JSON parsing + paise-field coercion for both the text and
    vision extraction paths — same response shape (_EXTRACTION_PROMPT)."""
    import json

    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    data = json.loads(raw)

    for field in ("taxable_amount_paise", "cgst_paise", "sgst_paise", "igst_paise", "total_paise"):
        data[field] = int(data.get(field) or 0)

    for item in data.get("line_items", []):
        item["rate_paise"] = int(item.get("rate_paise") or 0)
        item["gst_rate_bps"] = int(item.get("gst_rate_bps") or 1800)
        item["quantity"] = float(item.get("quantity") or 1)

    return data


def _groq_extract_text(doc_text: str) -> dict:
    """Call Groq's text model to extract invoice fields from PDF-extracted text."""
    from groq import Groq

    client = Groq(api_key=_GROQ_KEY)
    response = client.chat.completions.create(
        model=_GROQ_TEXT_MODEL,
        messages=[
            {"role": "user", "content": _EXTRACTION_PROMPT + doc_text},
        ],
        temperature=0.0,
        max_tokens=1024,
    )
    return _parse_extraction_json(response.choices[0].message.content)


def _gemini_extract_image(content: bytes, content_type: str) -> dict:
    """Call Gemini's vision-capable model with the actual image bytes so it
    can genuinely read a photographed or scanned invoice. See _run_extraction
    for why this is Gemini rather than Groq."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=_GEMINI_KEY)
    mime = content_type if content_type.startswith("image/") else "image/jpeg"
    response = client.models.generate_content(
        model=_GEMINI_VISION_MODEL,
        contents=[
            types.Part.from_bytes(data=content, mime_type=mime),
            _EXTRACTION_PROMPT.strip(),
        ],
    )
    return _parse_extraction_json(response.text)


def _estimate_confidence(extracted: dict) -> str:
    """Simple heuristic confidence score based on fields populated.
    R2.8/F19: extracted is always a real Groq result here — the mock
    fallback has been removed, so there is no `_is_mock` branch anymore."""
    score = 0
    if extracted.get("vendor_name"):
        score += 2
    if extracted.get("vendor_gstin"):
        score += 2
    if extracted.get("invoice_no"):
        score += 2
    if extracted.get("invoice_date"):
        score += 2
    if extracted.get("total_paise", 0) > 0:
        score += 2
    if score >= 8:
        return "high"
    if score >= 5:
        return "medium"
    return "low"
