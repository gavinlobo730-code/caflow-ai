from pydantic import BaseModel
from typing import Optional, Any
from enum import Enum
from models.fy import OptionalFYLabel


class DocumentType(str, Enum):
    FORM16 = "FORM16"
    GST_INVOICE = "GST_INVOICE"
    BANK_STATEMENT = "BANK_STATEMENT"
    AIS = "AIS"
    FORM26AS = "FORM26AS"
    TDS_CERTIFICATE = "TDS_CERTIFICATE"
    RENTAL_AGREEMENT = "RENTAL_AGREEMENT"
    CAPITAL_GAINS_STATEMENT = "CAPITAL_GAINS_STATEMENT"
    OTHER = "OTHER"


class ReviewStatus(str, Enum):
    PENDING = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class DocumentRecord(BaseModel):
    id: str
    client_id: str
    document_type: DocumentType
    file_name: str
    file_path: str
    financial_year: OptionalFYLabel
    extracted_json: Optional[Any]
    confidence_score: Optional[float]
    review_status: ReviewStatus
    upload_date: str
