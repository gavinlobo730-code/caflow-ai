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
from middleware.rate_limit import ai_limit
from core.uploads import read_limited
from core.authz import assert_client_access
from services.internal_client_service import assert_partner_for_internal_id
from domain.extraction_totals import check_totals
from domain.extraction_checks import check_supplier
from domain.ai import extraction_schemas, gemini_vision, groq_text, untrusted
from domain.ai.gateway import ProviderFailed

_logger = logging.getLogger("caflow.doc_intelligence_v1")
_GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
# Which TEXT model reads a PDF with embedded text, and which VISION model reads a
# photographed or scanned bill, are decided in domain/ai (groq_text.text_model()
# and gemini_vision.vision_model(), each with its own fallback list) and read at
# call time. This module used to snapshot both names at import and hand them to
# the vendor SDKs itself; it no longer imports either SDK (ai-04) — the two
# doors are the only modules that do.
#
# Vision is Gemini because Groq's own vision models returned a live 404
# model_not_found on this account; Gemini's free tier is multimodal-native and
# was already provisioned for this project. The PDF/text path stays on Groq.
_GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")

router = APIRouter(prefix="/api/document-intelligence-v1", tags=["document_intelligence_v1"])

# Same private Storage bucket routers/documents.py uses — reusing its bucket/
# path convention rather than inventing a second one.
_BUCKET = "Documents"

_EXTRACTION_PROMPT = """
You are an expert Indian accountant. Analyse the invoice document supplied to you (as text between markers, or as images) and extract
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
      "quantity": number or null,
      "unit": "string or null (the unit printed against the quantity, e.g. NOS, KGS, LTR, MTR)",
      "rate_paise": integer or null,
      "gst_rate_bps": integer or null (basis points: 1800 = 18%; 0 = the document prints 0%, nil-rated or exempt)
    }
  ]
}

Rules:
- All rupee amounts must be converted to paise (multiply by 100, integer only, no floats).
- If a header field is not present in the document, use null or 0 as appropriate.
- For each line item, NEVER guess quantity, unit, rate_paise or gst_rate_bps. If the document does
  not print it, use null. 0 is an answer, not a blank: use 0 for gst_rate_bps only when the document
  shows 0%, nil-rated or exempt.
- GSTIN format is 15 characters: 2-digit state code + 10-char PAN + entity digit + Z + check digit.
- Return ONLY the JSON object, no markdown, no explanation.
"""
# The document is NOT part of this prompt any more (ai-16): it travels in its own
# message, between markers the system message names as untrusted data
# (domain/ai/untrusted), so a file that says "ignore the above" is read as a
# file that says it.


@router.post("/extract-invoice")
def extract_invoice(
    file: UploadFile = File(...),
    client_id: str = Form(...),
    current_user: dict = Depends(rbac("document", "write")),
    _limit: None = Depends(ai_limit("extract")),
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
    # Bounded read (SECURITY-PRIVACY-20): it used to read the whole body and then
    # compare its length, so the cap protected nothing it was written to protect.
    content = read_limited(file, MAX_BYTES, message="File too large (max 10 MB)")

    content_type = (file.content_type or "").lower()
    filename = file.filename or ""

    # Retain the original file as ITC/audit evidence regardless of whether AI
    # extraction succeeds — CGST Rule 36(1) conditions ITC on possession of
    # the vendor's tax invoice, and extraction only ever reads the bytes into
    # memory. Best-effort: a storage failure must never block extraction or
    # manual bill entry.
    document_url = _upload_bill_document(content, content_type, filename, current_user.get("firm_id"), client_id)

    extracted, error, status_code = _run_extraction(
        content, content_type, filename,
        firm_id=current_user.get("firm_id"), user_id=current_user.get("id"))
    if error:
        # R2.8/F19: no more fabricated fallback data — surface the failure
        # honestly so the CA knows to enter the bill manually, instead of a
        # plausible-looking invoice silently flowing into the draft bill form.
        # The attachment (if it uploaded) is still worth returning — the CA
        # can enter the bill by hand and the original stays attached.
        data = {"document_url": document_url} if document_url else None
        return JSONResponse(status_code=status_code, content=api_response(False, data, error))

    # Does the reading add up? The five header figures are the model's reading
    # of five printed numbers whose relationship the document itself asserts,
    # and nothing checked it (PUR-21). Warns, never refuses — see
    # domain/extraction_totals.py for the tolerance and why.
    totals = check_totals(extracted)
    # And does the SUPPLIER it names exist, and is the tax the kind its place
    # gives (ai-02)? The GSTIN is fifteen characters the model typed, and the
    # editor then matches a vendor on it. Reports; refuses and rewrites nothing.
    supplier = check_supplier(
        extracted, _client_for_checks(client_id, current_user.get("firm_id")))
    return api_response(True, {
        "extracted": extracted,
        "confidence": _estimate_confidence(extracted, totals, supplier),
        "totals_check": totals,
        "supplier_check": supplier,
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


def _client_for_checks(client_id: str, firm_id: Optional[str]) -> Optional[dict]:
    """The client's row, for the State its GSTIN and `state_code` give — or None.

    Best-effort and firm-scoped: the checks that need it say "the client's State
    is not recorded" when it is missing, and a failed read must not cost the CA
    an extraction that already succeeded."""
    try:
        from repositories.client_repository import client_repo
        return client_repo.find_by_id(client_id, firm_id=firm_id)
    except Exception:                                            # noqa: BLE001
        _logger.warning("extract-invoice: the client row could not be read for the "
                        "place-of-supply check", exc_info=True)
        return None


def _run_extraction(
    content: bytes, content_type: str, filename: str, *,
    firm_id: Optional[str] = None, user_id: Optional[str] = None,
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

    A provider failure comes back as the gateway's CLASSIFIED sentence and its
    status (504 for a timeout, 502 for a refusal, and so on — the same words every
    other AI route uses), and a reply that cannot be accepted as a reading comes
    back as a refusal that says what was wrong with it. Only a failure nobody
    classified is the generic sentence.
    """
    is_pdf = "pdf" in content_type or filename.lower().endswith(".pdf")
    if not is_pdf and not _GEMINI_KEY:
        _logger.info("No GEMINI_API_KEY — refusing to fabricate an extraction")
        return None, "AI extraction is not configured on the server", 503

    try:
        if is_pdf:
            doc_text = _extract_pdf_text(content)
            if doc_text is None:
                # A PDF with no text layer is a SCAN. It used to be sent to the
                # text model as "[PDF content — base64 prefix, no extractable
                # text layer]: <200 base64 characters>" under an "extract invoice
                # fields" prompt, and since confidence is presence-based a
                # plausible invented vendor and invoice number could come back
                # from gibberish (ai-03). It is read as the picture it is, or
                # refused — never guessed at.
                return _extract_scanned_pdf(content, firm_id=firm_id, user_id=user_id)
            if not _GROQ_KEY:
                _logger.info("No GROQ_API_KEY — refusing to fabricate an extraction")
                return None, "AI extraction is not configured on the server", 503
            return _groq_extract_text(doc_text, firm_id=firm_id, user_id=user_id), None, 200
        return _gemini_extract_image(content, content_type, firm_id=firm_id, user_id=user_id), None, 200
    except ProviderFailed as e:
        # The provider did not answer, and the gateway has already retried and
        # tried any configured fallback. What the CA is told is the classified
        # sentence — which setting is wrong, or whether trying again can help —
        # where this used to be one generic sentence for every cause (ai-04).
        return None, e.sentence, e.http_status
    except extraction_schemas.ExtractionRefused as e:
        _logger.error("AI extraction refused (%s)", e.sentence)
        return None, e.sentence, e.http_status
    except Exception as e:
        # A failure nobody classified. The reason goes to the server log only.
        _logger.error("AI extraction failed (%s): %s", type(e).__name__, e)
        return None, "AI extraction failed — please retry or enter the bill details manually", 502


#: The most pages of a scanned PDF that are read as ONE invoice. An invoice is a
#: page or two; more than this is a statement-sized scan, and reading only its
#: first pages would drop line items without saying so, so it is refused instead.
SCANNED_PDF_PAGE_LIMIT = 3


def _extract_scanned_pdf(
    content: bytes, *, firm_id: Optional[str] = None, user_id: Optional[str] = None,
) -> tuple[Optional[dict], Optional[str], int]:
    """Read a PDF that has no text layer through the image path, or say why not.

    The image path is Gemini, the same one a photographed invoice takes
    (`_gemini_extract_image`): each page is rasterised and sent as the picture it
    is. Three refusals, each its own sentence because the remedy differs:
    image reading is not configured, the file is not a readable PDF, and the scan
    is longer than one invoice can be."""
    if not _GEMINI_KEY:
        if not _GROQ_KEY:
            # Neither provider is set up — the honest answer is the general one.
            return None, "AI extraction is not configured on the server", 503
        return None, ("This PDF is a scan with no readable text, and image reading is "
                      "not switched on for this server. Upload a photo of the invoice "
                      "instead, or enter the bill details by hand."), 422
    from domain.banking import vision
    try:
        pages, total = vision.first_pages(content, SCANNED_PDF_PAGE_LIMIT)
    except vision.StatementParseError:
        return None, ("This PDF is a scan with no readable text, and it could not be "
                      "opened to read as a picture. Upload a photo of the invoice "
                      "instead, or enter the bill details by hand."), 422
    if total > SCANNED_PDF_PAGE_LIMIT:
        return None, (f"This PDF is a scan of {total} pages — more than can be read as "
                      f"one invoice. Upload a photo of the invoice page, or enter the "
                      f"bill details by hand."), 422
    if not pages:
        return None, "This PDF has no pages to read.", 422
    return _gemini_extract_images(pages, "image/png", firm_id=firm_id, user_id=user_id), None, 200


def _extract_pdf_text(content: bytes) -> Optional[str]:
    """Best-effort text extraction from a PDF, or None when it has no text layer.

    None — not a stand-in string — is what a scan returns: a marker dressed as
    document text is exactly what reached the text model as base64 noise before
    (ai-03). The caller decides what a scan gets; nothing here invents text."""
    try:
        import io
        from pdfminer.high_level import extract_text as pdf_extract
        text = pdf_extract(io.BytesIO(content))
        if text and text.strip():
            return text[:8000]  # cap at 8000 chars for token budget
    except Exception:
        pass
    return None


def _parse_extraction_json(raw: str) -> dict:
    """Shared parsing, validation and paise-field coercion for both the text and
    vision extraction paths — same response shape (_EXTRACTION_PROMPT).

    The reply is validated against `extraction_schemas`' pydantic model (ai-05):
    a reply that is not a JSON object, an amount that is not a whole number of
    paise, lines that are not objects — each is `ExtractionRefused` with a
    sentence saying what was wrong, not a generic failure and not a trusted key.
    Lines then go through `read_line` (AI-01): an absent value is UNKNOWN, never
    a default. The two lines `read_line` replaced were `int(x or 1800)` and
    `float(x or 1)`, and `0` is falsy — so a nil-rated or exempt line read as 0%
    came back as 18%, and ITC on an exempt purchase was overstated unless the CA
    spotted it. It keeps a real zero as zero, leaves what was not read as None,
    and names it in `not_read` so the screen can leave it empty instead of
    showing a guess as a reading."""
    return extraction_schemas.parse_invoice(raw)


def _groq_extract_text(doc_text: str, *, firm_id: Optional[str] = None,
                       user_id: Optional[str] = None) -> dict:
    """Ask Groq's text model to extract invoice fields from PDF-extracted text.

    Through the ONE door (`groq_text.chat_sync`): timeout, bounded retry, the
    configured fallback model, the classified failure sentence and a usage row.
    `redact=False` is deliberate and is the exemption this module is listed under
    in `tests/test_no_model_call_site_sends_an_identifier`: the supplier's GSTIN is
    printed on the invoice being read, and redacting it would read an invoice
    without the number it is for. The document is untrusted DATA, in its own
    message (domain/ai/untrusted)."""
    reply = groq_text.chat_sync(
        untrusted.messages(_EXTRACTION_PROMPT, doc_text),
        api_key=_GROQ_KEY,
        max_tokens=groq_text.EXTRACTION_MAX_TOKENS,
        temperature=0.0,
        reasoning_effort="low",
        response_schema=extraction_schemas.INVOICE_SCHEMA,
        redact=False,
        feature="invoice_extraction",
        firm_id=firm_id,
        user_id=user_id,
    )
    return _parse_extraction_json(reply.text)


def _gemini_extract_image(content: bytes, content_type: str, *,
                          firm_id: Optional[str] = None, user_id: Optional[str] = None) -> dict:
    """Call Gemini's vision-capable model with the actual image bytes so it
    can genuinely read a photographed or scanned invoice. See _run_extraction
    for why this is Gemini rather than Groq."""
    mime = content_type if content_type.startswith("image/") else "image/jpeg"
    return _gemini_extract_images([content], mime, firm_id=firm_id, user_id=user_id)


def _gemini_extract_images(images: list[bytes], mime: str, *,
                           firm_id: Optional[str] = None, user_id: Optional[str] = None) -> dict:
    """One Gemini call over one or more page images of the SAME invoice, through
    the ONE vision door (`gemini_vision.generate`): timeout, bounded retry, the
    configured fallback model, the classified failure sentence and a usage row.
    The pictures are untrusted DATA, said so in the system instruction."""
    text = gemini_vision.generate(
        api_key=_GEMINI_KEY,
        images=images,
        mime=mime,
        prompt=_EXTRACTION_PROMPT.strip(),
        system_instruction=untrusted.image_system_instruction(),
        response_schema=extraction_schemas.INVOICE_GEMINI_SCHEMA,
        feature="invoice_extraction",
        firm_id=firm_id,
        user_id=user_id,
    )
    return _parse_extraction_json(text)


def _estimate_confidence(extracted: dict, totals: Optional[dict] = None,
                         supplier: Optional[dict] = None) -> str:
    """Heuristic confidence in the reading.

    R2.8/F19: extracted is always a real Groq result here — the mock fallback
    has been removed, so there is no `_is_mock` branch anymore.

    FIELD PRESENCE IS NOT EVIDENCE OF A CORRECT READING, and until PUR-21 it
    was the only input: five fields populated scored "high" whether or not
    they added up. A reading that fails its own arithmetic is the one piece of
    evidence available that a figure has been misread, so it caps the answer at
    "low" — the CA is being told how much to trust these numbers, and the
    honest answer when they contradict each other is: not much.

    The same cap now applies on ANY check that ran and found something (ai-02):
    the lines not adding up to the header, a tax that is not the lines' rates, a
    supplier GSTIN whose check digit fails, IGST between two same-State
    registrations. A check that could not run (nothing to test) does not lower
    it — an unread figure is not a disagreement.
    """
    if totals is not None and not totals.get("agrees", True):
        return "low"
    if supplier is not None and not supplier.get("agrees", True):
        return "low"
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
