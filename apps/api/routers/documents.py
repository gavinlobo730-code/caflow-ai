from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from models.common import api_response
from mock_data import MOCK_DOCUMENTS
from services.activity_service import log_activity

router = APIRouter(prefix="/api/documents", tags=["documents"])

MOCK_FORM16_EXTRACTION = {
    "employee_name": "Rajesh Kumar Sharma",
    "pan": "ABCRS1234D",
    "employer_name": "TechCorp India Pvt Ltd",
    "employer_tan": "MUMB12345C",
    "assessment_year": "2024-25",
    "financial_year": "2023-24",
    "gross_salary_paise": 120000000,
    "gross_salary_display": "₹12,00,000",
    "total_tds_paise": 18500000,
    "total_tds_display": "₹1,85,000",
    "standard_deduction_paise": 5000000,
    "standard_deduction_display": "₹50,000",
    "net_taxable_income_paise": 115000000,
    "net_taxable_income_display": "₹11,50,000",
}

MOCK_GST_INVOICE_EXTRACTION = {
    "supplier_name": "Hindustan Goods Suppliers Pvt Ltd",
    "gstin": "27AABCH1234B1ZA",
    "invoice_number": "HGS/2024-25/001234",
    "invoice_date": "2024-03-15",
    "taxable_value_paise": 10000000,
    "taxable_value_display": "₹1,00,000",
    "cgst_rate": "9%",
    "cgst_paise": 900000,
    "cgst_display": "₹9,000",
    "sgst_rate": "9%",
    "sgst_paise": 900000,
    "sgst_display": "₹9,000",
    "igst_rate": "0%",
    "igst_paise": 0,
    "igst_display": "₹0",
    "total_amount_paise": 11800000,
    "total_amount_display": "₹1,18,000",
    "hsn_code": "8471",
    "place_of_supply": "Maharashtra (27)",
}


@router.get("")
def list_documents(client_id: str | None = None):
    docs = MOCK_DOCUMENTS
    if client_id:
        docs = [d for d in docs if d["client_id"] == client_id]
    return api_response(True, {"documents": docs, "total": len(docs)})


@router.post("/parse")
async def parse_document(
    file: UploadFile = File(...),
    document_type: str = Form(...),
    client_id: str = Form(None),
):
    # TODO: Replace mock with Claude API vision call
    allowed = {"form16": "FORM16", "gst_invoice": "GST_INVOICE",
               "FORM16": "FORM16", "GST_INVOICE": "GST_INVOICE"}
    if document_type not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported document_type: {document_type}")

    doc_type = allowed[document_type]
    fields = MOCK_FORM16_EXTRACTION if doc_type == "FORM16" else MOCK_GST_INVOICE_EXTRACTION

    activity = log_activity(
        action="document_uploaded",
        description=f"{doc_type} parsed: {file.filename}",
        client_id=client_id,
        entity_type="document",
    )

    return api_response(True, {
        "document_type": doc_type,
        "file_name": file.filename,
        "fields": fields,
        "confidence_score": 0.94,
        "review_status": "pending_review",
        "activity": activity,
    })
