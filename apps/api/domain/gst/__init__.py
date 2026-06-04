"""GST filing engine — GSTR-1 and GSTR-3B payload generation.

Ref: CGST Act 2017, CGST Rules 2017.
All monetary amounts are integer paise. Never float.
"""
from .classifier import GSTInvoiceCategory, classify_transaction, classify_transactions, TransactionForClassification
from .gstr3b_computer import GSTR3BResult, compute_gstr3b
from .gstr1_builder import GSTR1Payload, build_gstr1
from .validator import GSTValidator, ValidationError as GSTValidationError

__all__ = [
    "GSTInvoiceCategory",
    "TransactionForClassification",
    "classify_transaction",
    "classify_transactions",
    "GSTR3BResult",
    "compute_gstr3b",
    "GSTR1Payload",
    "build_gstr1",
    "GSTValidator",
    "GSTValidationError",
]
