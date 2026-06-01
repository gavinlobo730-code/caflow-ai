"""
Document Intelligence Service.
Extraction pipeline: Upload → Classify → Extract → Validate → Risk Detect → Task Generate
Provider-swappable: mock | aws_textract | google_docai | azure_formrec | claude_vision
"""
from datetime import date, timedelta
from typing import Optional

today = date.today()

# ---------------------------------------------------------------------------
# Seed mock data
# ---------------------------------------------------------------------------

MOCK_DOCUMENT_EXTRACTIONS: list[dict] = [
    {
        "id": "ext-001",
        "document_id": "doc-001",
        "extraction_status": "completed",
        "provider": "mock",
        "confidence_score": 0.97,
        "extracted_data": {
            "invoice_no": "HGS/2024-25/001234",
            "gstin_supplier": "27AABCH1234B1ZA",
            "gstin_recipient": "27AABCS1429B1ZB",
            "taxable_value_paise": 10000000,
            "cgst_paise": 900000,
            "sgst_paise": 900000,
            "igst_paise": 0,
            "total_paise": 11800000,
        },
        "validation_results": {
            "valid": True,
            "missing_fields": [],
            "warnings": [],
        },
        "error_message": None,
        "created_at": (today - timedelta(days=5)).isoformat(),
        "updated_at": (today - timedelta(days=5)).isoformat(),
    },
    {
        "id": "ext-002",
        "document_id": "doc-002",
        "extraction_status": "pending",
        "provider": "mock",
        "confidence_score": None,
        "extracted_data": None,
        "validation_results": None,
        "error_message": None,
        "created_at": (today - timedelta(days=2)).isoformat(),
        "updated_at": (today - timedelta(days=2)).isoformat(),
    },
    {
        "id": "ext-003",
        "document_id": "doc-003",
        "extraction_status": "completed",
        "provider": "mock",
        "confidence_score": 0.91,
        "extracted_data": {
            "employer_name": "Joshi Textiles Pvt Ltd",
            "employee_pan": "AAJCS3329B",
            "gross_salary_paise": 120000000,
            "tds_deducted_paise": 18000000,
            "assessment_year": "2025-26",
        },
        "validation_results": {
            "valid": True,
            "missing_fields": [],
            "warnings": ["TDS amount seems high — verify with 26AS"],
        },
        "error_message": None,
        "created_at": (today - timedelta(days=10)).isoformat(),
        "updated_at": (today - timedelta(days=10)).isoformat(),
    },
    {
        "id": "ext-004",
        "document_id": "doc-004",
        "extraction_status": "completed",
        "provider": "mock",
        "confidence_score": 0.88,
        "extracted_data": {
            "pan": "AACCS7829B",
            "assessment_year": "2025-26",
            "total_income_paise": 85000000,
            "tds_details": [
                {"deductor": "Patel & Sons", "tds_paise": 5000000},
            ],
            "sft_details": [],
        },
        "validation_results": {
            "valid": True,
            "missing_fields": [],
            "warnings": ["AIS income differs from book income by ₹12,000"],
        },
        "error_message": None,
        "created_at": (today - timedelta(days=7)).isoformat(),
        "updated_at": (today - timedelta(days=7)).isoformat(),
    },
    {
        "id": "ext-005",
        "document_id": "doc-005",
        "extraction_status": "failed",
        "provider": "mock",
        "confidence_score": 0.41,
        "extracted_data": None,
        "validation_results": None,
        "error_message": "Low confidence score — document too blurry or unsupported format",
        "created_at": (today - timedelta(days=3)).isoformat(),
        "updated_at": (today - timedelta(days=3)).isoformat(),
    },
]

MOCK_DOCUMENT_RISKS: list[dict] = [
    {
        "id": "risk-001",
        "document_id": "doc-004",
        "client_id": "c-003",
        "severity": "high",
        "category": "AIS_MISMATCH",
        "title": "AIS Income vs Book Income Mismatch",
        "description": "AIS shows total income of ₹8.5L but books show ₹7.3L. Difference of ₹1.2L may trigger scrutiny.",
        "resolution_status": "open",
        "resolved_at": None,
        "created_at": (today - timedelta(days=7)).isoformat(),
    },
    {
        "id": "risk-002",
        "document_id": "doc-003",
        "client_id": "c-005",
        "severity": "critical",
        "category": "TDS_MISMATCH",
        "title": "Form 16 TDS vs 26AS Mismatch",
        "description": "Form 16 shows TDS of ₹1.8L but 26AS shows only ₹1.4L. Difference of ₹40,000 must be reconciled before ITR.",
        "resolution_status": "open",
        "resolved_at": None,
        "created_at": (today - timedelta(days=10)).isoformat(),
    },
    {
        "id": "risk-003",
        "document_id": "doc-001",
        "client_id": "c-001",
        "severity": "medium",
        "category": "MISSING_INVOICE",
        "title": "Missing GST Input Invoices",
        "description": "GSTR-2B shows 4 supplier invoices but only 2 are present in purchase register. Missing invoices worth ₹45,000.",
        "resolution_status": "acknowledged",
        "resolved_at": None,
        "created_at": (today - timedelta(days=5)).isoformat(),
    },
    {
        "id": "risk-004",
        "document_id": "doc-005",
        "client_id": "c-002",
        "severity": "high",
        "category": "CLASSIFICATION_ERROR",
        "title": "Low Confidence Extraction — Manual Review Required",
        "description": "Confidence score 41% is below threshold 70%. Document may be misclassified or corrupted.",
        "resolution_status": "open",
        "resolved_at": None,
        "created_at": (today - timedelta(days=3)).isoformat(),
    },
    {
        "id": "risk-005",
        "document_id": "doc-002",
        "client_id": "c-001",
        "severity": "medium",
        "category": "BANK_RECONCILIATION",
        "title": "Bank Statement — Unreconciled Entries",
        "description": "5 debit entries totalling ₹2.3L not matched in books. Potential unreported income or expense.",
        "resolution_status": "open",
        "resolved_at": None,
        "created_at": (today - timedelta(days=2)).isoformat(),
    },
    {
        "id": "risk-006",
        "document_id": "doc-003",
        "client_id": "c-005",
        "severity": "high",
        "category": "HIGH_LIABILITY",
        "title": "High TDS Liability Detected",
        "description": "TDS deducted ₹1.8L significantly higher than prior year. Verify with employer for any one-time payments.",
        "resolution_status": "open",
        "resolved_at": None,
        "created_at": (today - timedelta(days=9)).isoformat(),
    },
    {
        "id": "risk-007",
        "document_id": "doc-001",
        "client_id": "c-001",
        "severity": "low",
        "category": "GST_MISMATCH",
        "title": "GST Rate Classification Check",
        "description": "Invoice uses 18% GST rate. Verify if goods qualify for 12% rate under HSN classification.",
        "resolution_status": "resolved",
        "resolved_at": (today - timedelta(days=1)).isoformat(),
        "created_at": (today - timedelta(days=5)).isoformat(),
    },
    {
        "id": "risk-008",
        "document_id": "doc-004",
        "client_id": "c-003",
        "severity": "medium",
        "category": "MISSING_FORM16",
        "title": "Missing Form 16 from Secondary Employer",
        "description": "AIS shows TDS from 2 deductors but only 1 Form 16 submitted. Obtain Form 16 from second employer.",
        "resolution_status": "open",
        "resolved_at": None,
        "created_at": (today - timedelta(days=6)).isoformat(),
    },
]

# Enrich mock documents with extra entries for doc-003/doc-004/doc-005
MOCK_EXTRA_DOCUMENTS: list[dict] = [
    {
        "id": "doc-003",
        "client_id": "c-005",
        "document_type": "FORM16",
        "file_name": "form16_joshi_2024_25.pdf",
        "file_path": "/uploads/c-005/form16_joshi_2024_25.pdf",
        "financial_year": "2024-25",
        "review_status": "pending_review",
        "confidence_score": 0.91,
        "upload_date": (today - timedelta(days=10)).isoformat(),
        "extracted_json": None,
    },
    {
        "id": "doc-004",
        "client_id": "c-003",
        "document_type": "AIS",
        "file_name": "ais_mehta_2025_26.pdf",
        "file_path": "/uploads/c-003/ais_mehta_2025_26.pdf",
        "financial_year": "2025-26",
        "review_status": "pending_review",
        "confidence_score": 0.88,
        "upload_date": (today - timedelta(days=7)).isoformat(),
        "extracted_json": None,
    },
    {
        "id": "doc-005",
        "client_id": "c-002",
        "document_type": "BANK_STATEMENT",
        "file_name": "bank_stmt_patel_apr2025.pdf",
        "file_path": "/uploads/c-002/bank_stmt_patel_apr2025.pdf",
        "financial_year": "2025-26",
        "review_status": "review_required",
        "confidence_score": 0.41,
        "upload_date": (today - timedelta(days=3)).isoformat(),
        "extracted_json": None,
    },
]

_EXTRACTION_INDEX = {e["document_id"]: e for e in MOCK_DOCUMENT_EXTRACTIONS}
_RISK_INDEX: dict[str, list[dict]] = {}
for _r in MOCK_DOCUMENT_RISKS:
    _RISK_INDEX.setdefault(_r["document_id"], []).append(_r)

# ---------------------------------------------------------------------------
# Mock extraction templates by document type
# ---------------------------------------------------------------------------

_MOCK_EXTRACTED: dict[str, dict] = {
    "FORM16": {
        "employer_name": "Sample Employer Pvt Ltd",
        "employee_pan": "SAMPLE1234A",
        "gross_salary_paise": 80000000,
        "tds_deducted_paise": 12000000,
        "assessment_year": "2025-26",
    },
    "GST_INVOICE": {
        "invoice_no": "INV/2025/0001",
        "gstin_supplier": "27AABCS1429B1ZB",
        "gstin_recipient": "27AAPCS4229B1ZC",
        "taxable_value_paise": 5000000,
        "cgst_paise": 450000,
        "sgst_paise": 450000,
        "igst_paise": 0,
        "total_paise": 5900000,
    },
    "BANK_STATEMENT": {
        "account_no": "XXXX1234",
        "bank_name": "HDFC Bank",
        "period_start": "2025-04-01",
        "period_end": "2025-04-30",
        "opening_balance_paise": 50000000,
        "closing_balance_paise": 62000000,
        "total_credits_paise": 30000000,
        "total_debits_paise": 18000000,
    },
    "AIS": {
        "pan": "SAMPLE1234A",
        "assessment_year": "2025-26",
        "total_income_paise": 75000000,
        "tds_details": [],
        "sft_details": [],
    },
    "FORM26AS": {
        "pan": "SAMPLE1234A",
        "assessment_year": "2025-26",
        "tds_entries": [],
        "tax_paid": [],
    },
}


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------

def classify_document(filename: str, file_type: str) -> str:
    """Classify document by filename heuristics."""
    name = filename.lower()
    if "form16" in name or "form_16" in name:
        return "FORM16"
    if "26as" in name or "form26" in name:
        return "FORM26AS"
    if "ais" in name:
        return "AIS"
    if "bank" in name or "statement" in name:
        return "BANK_STATEMENT"
    if "invoice" in name or "gst" in name:
        return "GST_INVOICE"
    return "OTHER"


def extract_document(document_id: str, document_type: str, provider: str = "mock") -> dict:
    """Run mock extraction and return extracted_data dict."""
    extraction = _EXTRACTION_INDEX.get(document_id)
    if extraction:
        extraction["extraction_status"] = "completed"
        extraction["provider"] = provider
        if extraction["extracted_data"] is None:
            extraction["extracted_data"] = _MOCK_EXTRACTED.get(document_type, {})
            extraction["confidence_score"] = 0.85
        return extraction

    # Create new extraction record
    import uuid
    from datetime import datetime
    new_ext = {
        "id": f"ext-{str(uuid.uuid4())[:8]}",
        "document_id": document_id,
        "extraction_status": "completed",
        "provider": provider,
        "confidence_score": 0.85,
        "extracted_data": _MOCK_EXTRACTED.get(document_type, {}),
        "validation_results": {"valid": True, "missing_fields": [], "warnings": []},
        "error_message": None,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    MOCK_DOCUMENT_EXTRACTIONS.append(new_ext)
    _EXTRACTION_INDEX[document_id] = new_ext
    return new_ext


def validate_extraction(document_id: str, extracted_data: dict, document_type: str) -> dict:
    """Validate required fields present, return validation_results."""
    required_fields: dict[str, list[str]] = {
        "FORM16": ["employer_name", "employee_pan", "gross_salary_paise", "tds_deducted_paise", "assessment_year"],
        "GST_INVOICE": ["invoice_no", "gstin_supplier", "taxable_value_paise", "total_paise"],
        "BANK_STATEMENT": ["account_no", "bank_name", "period_start", "period_end"],
        "AIS": ["pan", "assessment_year", "total_income_paise"],
        "FORM26AS": ["pan", "assessment_year"],
    }
    required = required_fields.get(document_type, [])
    missing = [f for f in required if f not in extracted_data or extracted_data[f] is None]
    warnings: list[str] = []
    if document_type == "FORM16":
        tds = extracted_data.get("tds_deducted_paise", 0) or 0
        gross = extracted_data.get("gross_salary_paise", 1) or 1
        if tds / gross > 0.3:
            warnings.append("TDS rate exceeds 30% of gross salary — verify")
    result = {
        "valid": len(missing) == 0,
        "missing_fields": missing,
        "warnings": warnings,
    }
    ext = _EXTRACTION_INDEX.get(document_id)
    if ext:
        ext["validation_results"] = result
    return result


def detect_document_risks(document_id: str, client_id: str, extracted_data: dict, document_type: str) -> list[dict]:
    """Generate DocumentRisk records based on extraction data."""
    import uuid
    from datetime import datetime
    new_risks: list[dict] = []

    # Check confidence score
    ext = _EXTRACTION_INDEX.get(document_id)
    confidence = ext.get("confidence_score") if ext else None
    if confidence is not None and confidence < 0.7:
        new_risks.append({
            "id": f"risk-{str(uuid.uuid4())[:8]}",
            "document_id": document_id,
            "client_id": client_id,
            "severity": "high",
            "category": "CLASSIFICATION_ERROR",
            "title": "Low Confidence Score — Manual Review Required",
            "description": f"Extraction confidence {confidence:.0%} is below 70% threshold.",
            "resolution_status": "open",
            "resolved_at": None,
            "created_at": datetime.utcnow().isoformat(),
        })

    if document_type == "AIS":
        total_income = extracted_data.get("total_income_paise", 0) or 0
        book_income = int(total_income * 0.85)  # mock book income difference
        diff = total_income - book_income
        if diff > 0:
            new_risks.append({
                "id": f"risk-{str(uuid.uuid4())[:8]}",
                "document_id": document_id,
                "client_id": client_id,
                "severity": "high",
                "category": "AIS_MISMATCH",
                "title": "AIS Income vs Book Income Mismatch",
                "description": f"AIS shows ₹{total_income // 100:,} but books show ₹{book_income // 100:,}. Difference ₹{diff // 100:,}.",
                "resolution_status": "open",
                "resolved_at": None,
                "created_at": datetime.utcnow().isoformat(),
            })

    if document_type == "FORM16":
        new_risks.append({
            "id": f"risk-{str(uuid.uuid4())[:8]}",
            "document_id": document_id,
            "client_id": client_id,
            "severity": "medium",
            "category": "TDS_MISMATCH",
            "title": "Verify Form 16 TDS against 26AS",
            "description": "Always cross-check Form 16 TDS with 26AS before filing ITR.",
            "resolution_status": "open",
            "resolved_at": None,
            "created_at": datetime.utcnow().isoformat(),
        })

    if document_type == "BANK_STATEMENT":
        credits = extracted_data.get("total_credits_paise", 0) or 0
        debits = extracted_data.get("total_debits_paise", 0) or 0
        if abs(credits - debits) > 1000000:
            new_risks.append({
                "id": f"risk-{str(uuid.uuid4())[:8]}",
                "document_id": document_id,
                "client_id": client_id,
                "severity": "medium",
                "category": "BANK_RECONCILIATION",
                "title": "Bank Statement — Unreconciled Entries",
                "description": f"Net unreconciled amount ₹{abs(credits - debits) // 100:,}. Verify entries against ledger.",
                "resolution_status": "open",
                "resolved_at": None,
                "created_at": datetime.utcnow().isoformat(),
            })

    if document_type == "GST_INVOICE":
        new_risks.append({
            "id": f"risk-{str(uuid.uuid4())[:8]}",
            "document_id": document_id,
            "client_id": client_id,
            "severity": "medium",
            "category": "MISSING_INVOICE",
            "title": "Verify Input Tax Credit Eligibility",
            "description": "Ensure supplier has filed GSTR-1 so ITC is available in GSTR-2B before claiming.",
            "resolution_status": "open",
            "resolved_at": None,
            "created_at": datetime.utcnow().isoformat(),
        })

    for r in new_risks:
        MOCK_DOCUMENT_RISKS.append(r)
        _RISK_INDEX.setdefault(document_id, []).append(r)

    return new_risks


def get_extraction(document_id: str) -> dict | None:
    """Return extraction record for a document."""
    return _EXTRACTION_INDEX.get(document_id)


def get_firm_document_stats() -> dict:
    """Return counts: total, pending_review, processing, high_risk, extraction_failures."""
    from mock_data import MOCK_DOCUMENTS
    all_docs = MOCK_DOCUMENTS + MOCK_EXTRA_DOCUMENTS
    total = len(all_docs)
    pending_review = len([d for d in all_docs if d.get("review_status") in ("pending_review", "review_required")])
    processing = len([e for e in MOCK_DOCUMENT_EXTRACTIONS if e["extraction_status"] == "processing"])
    extraction_failures = len([e for e in MOCK_DOCUMENT_EXTRACTIONS if e["extraction_status"] == "failed"])
    high_risk = len(set(
        r["document_id"] for r in MOCK_DOCUMENT_RISKS
        if r["severity"] in ("critical", "high") and r["resolution_status"] == "open"
    ))
    return {
        "total": total,
        "pending_review": pending_review,
        "processing": processing,
        "high_risk": high_risk,
        "extraction_failures": extraction_failures,
    }


def list_documents_with_risk(client_id: Optional[str] = None) -> list[dict]:
    """Return documents enriched with risk_level and extraction status."""
    from mock_data import MOCK_DOCUMENTS
    all_docs = MOCK_DOCUMENTS + MOCK_EXTRA_DOCUMENTS
    if client_id:
        all_docs = [d for d in all_docs if d["client_id"] == client_id]

    from mock_data import MOCK_CLIENTS
    client_map = {c["id"]: c["client_name"] for c in MOCK_CLIENTS}

    result = []
    for doc in all_docs:
        extraction = _EXTRACTION_INDEX.get(doc["id"])
        doc_risks = _RISK_INDEX.get(doc["id"], [])
        open_risks = [r for r in doc_risks if r["resolution_status"] == "open"]
        severity_order = ["critical", "high", "medium", "low", "info"]
        risk_level = None
        for sev in severity_order:
            if any(r["severity"] == sev for r in open_risks):
                risk_level = sev
                break

        result.append({
            **doc,
            "client_name": client_map.get(doc["client_id"], "Unknown"),
            "extraction": extraction,
            "risks": doc_risks,
            "risk_level": risk_level,
        })
    return result


def get_document_risks(document_id: str) -> list[dict]:
    """Return risks for a specific document."""
    return _RISK_INDEX.get(document_id, [])


def resolve_risk(risk_id: str, resolution_status: str) -> dict | None:
    """Update resolution status of a risk."""
    from datetime import datetime
    for risk in MOCK_DOCUMENT_RISKS:
        if risk["id"] == risk_id:
            risk["resolution_status"] = resolution_status
            if resolution_status == "resolved":
                risk["resolved_at"] = datetime.utcnow().isoformat()
            return risk
    return None
