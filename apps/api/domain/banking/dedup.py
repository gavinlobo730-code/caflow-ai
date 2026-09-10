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
    occurrence: int = 0,
) -> str:
    """Stable per-transaction fingerprint.

    THE BALANCE IS NOT ENOUGH, AND THAT IS WHY `occurrence` EXISTS.

    Balance was the whole answer to "two identical same-day debits": their
    running balances differ, so their hashes differ. But a statement with NO
    balance column gives every row a balance of 0 (normalizer._to_paise of an
    absent cell), so two genuinely identical rows — same date, same amount,
    same narration, no reference — collapsed to one hash and the second was
    dropped. Two ₹5,000 ATM withdrawals on one day, or two identical UPI
    payments to the same payee, are ordinary and they are NOT a duplicate.

    `occurrence` is how many rows with these exact fields came BEFORE this one
    IN THE SAME FILE. It distinguishes them without breaking the thing the
    hash is actually for:

      * two identical rows in one file -> occurrences 0 and 1 -> two rows kept;
      * the SAME file uploaded again -> the same fields in the same order ->
        the same occurrences -> the same hashes -> skipped, as before;
      * an OVERLAPPING file (1-15 April, then 1-30 April) -> a row unique
        within each file is occurrence 0 in both -> same hash -> still skipped.

    That last case is why this is not the row's ordinal position in the file,
    which was the obvious fix and would have re-imported every overlapping row
    as new.

    NO MIGRATION IS NEEDED for this, which is worth stating because the finding
    said otherwise: migration 224's UNIQUE (client_id, import_hash) only blocks
    keeping both rows if both keep the SAME hash. They no longer do.
    """
    parts = [
        str(client_id or ""),
        str(bank_account_id or ""),
        str(transaction_date or "")[:10],
        str(int(debit_paise or 0)),
        str(int(credit_paise or 0)),
        str(int(balance_paise or 0)),
        " ".join(str(description or "").split()).lower(),   # whitespace/case-normalised
        str(reference_no or "").strip().lower(),
        str(int(occurrence or 0)),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def hash_rows(client_id: str, bank_account_id: Optional[str],
              rows: list[dict]) -> tuple[list[str], int]:
    """One hash per row IN ORDER, and how many of them repeat an earlier row.

    The counting has to happen here rather than at the call site: an importer
    that hashed each row independently would have to keep the tally itself, and
    the one that did not is exactly how two identical rows became one.

    The repeat count is taken from the OCCURRENCE-0 hash, not from the hashes
    returned. The returned ones are distinct by construction — that is the
    whole point of the occurrence — so counting duplicates among them would
    always answer zero, which is how a "how many repeated" figure quietly
    becomes decoration.
    """
    seen: dict[str, int] = {}
    out: list[str] = []
    repeated = 0
    for r in rows:
        fields = (client_id, bank_account_id, r.get("transaction_date"),
                  r.get("debit_paise") or 0, r.get("credit_paise") or 0,
                  r.get("balance_paise") or 0, r.get("description"),
                  r.get("reference_no"))
        base = transaction_hash(*fields, occurrence=0)
        n = seen.get(base, 0)
        seen[base] = n + 1
        if n:
            repeated += 1
        out.append(base if n == 0 else transaction_hash(*fields, occurrence=n))
    return out, repeated


def file_hash(content: bytes) -> str:
    """sha256 of the raw uploaded bytes — identifies a re-uploaded identical file."""
    return hashlib.sha256(content or b"").hexdigest()
