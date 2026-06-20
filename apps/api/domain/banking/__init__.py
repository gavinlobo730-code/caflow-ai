"""Bank-feed foundation (Banking B.1): statement normalization + dedup.

Pure, DB-agnostic. Bank-specific column layouts live ONLY in normalizer._ADAPTERS;
everything downstream works on the single NormalizedTxn format.
"""
from .normalizer import (
    NormalizedTxn,
    parse_statement,
    parse_csv,
    parse_xlsx,
    detect_format,
    StatementParseError,
)
from .dedup import transaction_hash, file_hash

__all__ = [
    "NormalizedTxn", "parse_statement", "parse_csv", "parse_xlsx",
    "detect_format", "StatementParseError", "transaction_hash", "file_hash",
]
