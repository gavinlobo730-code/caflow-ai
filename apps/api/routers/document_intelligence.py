from fastapi import APIRouter
from models.common import api_response
from domain.document_intelligence_service import (
    list_documents_with_risk,
    get_firm_document_stats,
    get_extraction,
    extract_document,
    get_document_risks,
    resolve_risk,
    classify_document,
    MOCK_DOCUMENT_EXTRACTIONS,
)
from mock_data import MOCK_DOCUMENTS

router = APIRouter(prefix="/api/document-intelligence", tags=["document-intelligence"])


@router.get("/documents")
def list_documents(client_id: str = None):
    docs = list_documents_with_risk(client_id=client_id)
    return api_response(True, docs)


@router.get("/stats")
def get_stats():
    stats = get_firm_document_stats()
    return api_response(True, stats)


@router.get("/{doc_id}/extraction")
def get_doc_extraction(doc_id: str):
    extraction = get_extraction(doc_id)
    if extraction is None:
        return api_response(False, None, "Extraction not found")
    return api_response(True, extraction)


@router.post("/{doc_id}/extract")
def trigger_extraction(doc_id: str):
    from mock_data import MOCK_DOCUMENTS
    from domain.document_intelligence_service import MOCK_EXTRA_DOCUMENTS
    all_docs = MOCK_DOCUMENTS + MOCK_EXTRA_DOCUMENTS
    doc = next((d for d in all_docs if d["id"] == doc_id), None)
    if doc is None:
        return api_response(False, None, "Document not found")
    doc_type = doc.get("document_type", "OTHER")
    extraction = extract_document(doc_id, doc_type, provider="mock")
    return api_response(True, extraction)


@router.get("/{doc_id}/risks")
def get_risks_for_document(doc_id: str):
    risks = get_document_risks(doc_id)
    return api_response(True, risks)


@router.post("/{doc_id}/risks/{risk_id}/resolve")
def resolve_document_risk(doc_id: str, risk_id: str, resolution_status: str = "resolved"):
    risk = resolve_risk(risk_id, resolution_status)
    if risk is None:
        return api_response(False, None, "Risk not found")
    return api_response(True, risk)
