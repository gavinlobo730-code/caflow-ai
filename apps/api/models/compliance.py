from pydantic import BaseModel
from typing import Optional
from enum import Enum


class ComplianceType(str, Enum):
    GSTR1 = "GSTR1"
    GSTR3B = "GSTR3B"
    GSTR9 = "GSTR9"
    ITR = "ITR"
    TDS24Q = "TDS24Q"
    TDS26Q = "TDS26Q"
    ADVANCE_TAX = "ADVANCE_TAX"
    TCS_RETURN = "TCS_RETURN"
    OTHER = "OTHER"


class ComplianceStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    FILED = "filed"
    OVERDUE = "overdue"
    NOT_APPLICABLE = "not_applicable"


class CompliancePriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
