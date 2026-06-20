"""
Deterministic hashing for bank-feed deduplication (Banking B.1, Part D).

transaction_hash() yields a stable fingerprint per transaction so re-importing
the same statement is idempotent (duplicates are skipped), while genuinely
distinct same-day/same-amount transactions (different running balance) are kept.
file_hash() fingerprints the raw upload for duplicate-file detection.

Pure and side-effect free. Hashes are deterministic across processes (sha256 over
a canonical, ordered field list) — never Python's salted hash().
"""
from __future__ import annotations

import hashlib
from typing import Optional


def transaction_hash(
    client_id: str,
    bank_account_id: Optional[str],
    transaction_date: str,
    debit_paise: int,
    credit_paise: int,
    balance_paise: int,
    description: str,
    reference_no: Optional[str],
) -> str:
    """Stable per-transaction fingerprint. Balance is included so two identical
    same-day debits (distinct running balances) are not collapsed."""
    parts = [
        str(client_id or ""),
        str(bank_account_id or ""),
        str(transaction_date or "")[:10],
        str(int(debit_paise or 0)),
        str(int(credit_paise or 0)),
        str(int(balance_paise or 0)),
        " ".join(str(description or "").split()).lower(),   # whitespace/case-normalised
        str(reference_no or "").strip().lower(),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def file_hash(content: bytes) -> str:
    """sha256 of the raw uploaded bytes — identifies a re-uploaded identical file."""
    return hashlib.sha256(content or b"").hexdigest()
