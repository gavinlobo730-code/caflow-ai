"""Document Intelligence v1 — Invoice PDF/Image upload and AI extraction.
Extracts vendor name, GSTIN, invoice number, date, tax values, total amount.
Creates a DRAFT purchase bill — human CA approval required before posting.
# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
"""
import os
import base64
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from models.common import api_response
from core.permissions import rbac

_logger = logging.getLogger("caflow.doc_intelligence_v1")
_GROQ_KEY = os.environ.get("GROQ_API_KEY", "")

router = APIRouter(prefix="/api/document-intelligence-v1", tags=["document_intelligence_v1"])

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
    # File size guard (10 MB)
    MAX_BYTES = 10 * 1024 * 1024
    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

    content_type = (file.content_type or "").lower()
    filename = file.filename or ""

    extracted = _run_extraction(content, content_type, filename)
    return api_response(True, {
        "extracted": extracted,
        "confidence": _estimate_confidence(extracted),
        "requires_review": True,  # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
        "client_id": client_id,
    })


def _run_extraction(content: bytes, content_type: str, filename: str) -> dict:
    """
    Attempt AI extraction via Groq. Falls back to mock if no API key.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    if not _GROQ_KEY:
        _logger.info("No GROQ_API_KEY — returning mock extraction")
        return _mock_extraction(filename)

    try:
        doc_text = _read_document_text(content, content_type, filename)
        return _groq_extract(doc_text)
    except Exception as e:
        _logger.error("AI extraction failed: %s", e)
        return _mock_extraction(filename)


def _read_document_text(content: bytes, content_type: str, filename: str) -> str:
    """Convert uploaded file to text for the AI prompt."""
    # PDF: attempt basic text extraction; images: describe as base64 note
    if "pdf" in content_type or filename.lower().endswith(".pdf"):
        try:
            import io
            # Attempt pdfminer extraction
            from pdfminer.high_level import extract_text as pdf_extract
            text = pdf_extract(io.BytesIO(content))
            return text[:8000]  # cap at 8000 chars for token budget
        except Exception:
            # Fallback: base64-encode and pass as note
            b64 = base64.b64encode(content[:4096]).decode()
            return f"[PDF content — base64 prefix]: {b64[:200]}..."
    else:
        # Image: pass as descriptive note (vision not available on Groq text models)
        b64 = base64.b64encode(content[:4096]).decode()
        return f"[Image invoice — base64 preview]: {b64[:200]}... (image filename: {filename})"


def _groq_extract(doc_text: str) -> dict:
    """Call Groq API with llama-3.3-70b-versatile to extract invoice fields."""
    import json
    from groq import Groq

    client = Groq(api_key=_GROQ_KEY)
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "user", "content": _EXTRACTION_PROMPT + doc_text},
        ],
        temperature=0.0,
        max_tokens=1024,
    )
    raw = response.choices[0].message.content.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    data = json.loads(raw)

    # Coerce all paise fields to int
    for field in ("taxable_amount_paise", "cgst_paise", "sgst_paise", "igst_paise", "total_paise"):
        data[field] = int(data.get(field) or 0)

    for item in data.get("line_items", []):
        item["rate_paise"] = int(item.get("rate_paise") or 0)
        item["gst_rate_bps"] = int(item.get("gst_rate_bps") or 1800)
        item["quantity"] = float(item.get("quantity") or 1)

    return data


def _mock_extraction(filename: str) -> dict:
    """Return plausible mock extraction for testing without API key."""
    return {
        "vendor_name": "Sample Vendor Pvt Ltd",
        "vendor_gstin": "27AABCS1429B1Z5",
        "invoice_no": "INV-2025-001",
        "invoice_date": "2025-06-01",
        "taxable_amount_paise": 1000000,
        "cgst_paise": 90000,
        "sgst_paise": 90000,
        "igst_paise": 0,
        "total_paise": 1180000,
        "line_items": [
            {
                "description": "Professional Services",
                "hsn_sac": "998313",
                "quantity": 1.0,
                "rate_paise": 1000000,
                "gst_rate_bps": 1800,
            }
        ],
        "_is_mock": True,
        "_source_file": filename,
    }


def _estimate_confidence(extracted: dict) -> str:
    """Simple heuristic confidence score based on fields populated."""
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
    if extracted.get("_is_mock"):
        return "low"
    if score >= 8:
        return "high"
    if score >= 5:
        return "medium"
    return "low"
