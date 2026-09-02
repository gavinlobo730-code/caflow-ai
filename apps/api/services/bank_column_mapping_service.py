"""Saved statement column mappings — audit Tier 3.2.

The mapping itself is validated and applied in `domain/banking/normalizer`;
this module only stores and retrieves it. The split matters: the normalizer is
pure and runs in mock mode with no database, so the rule about what a valid
mapping is stays testable without one.
"""
from __future__ import annotations

import logging
from typing import Optional

from domain.banking.normalizer import (
    MAPPING_KEYS, StatementParseError, header_fingerprint, validate_mapping,
)

_logger = logging.getLogger("caflow.banking.column_mapping")

TABLE = "bank_statement_column_mappings"


def find_mapping(db, firm_id: str, bank_account_id: str,
                 fingerprint: str) -> Optional[dict]:
    """The saved mapping for this account and this exact header layout.

    Returns None — never a mapping for a DIFFERENT layout. Falling back to the
    account's other saved mapping is the one thing this must not do: it would
    read a changed export at the old column positions and produce numbers that
    are wrong without being obviously wrong.
    """
    if not db or not bank_account_id or not fingerprint:
        return None
    try:
        rows = (db.table(TABLE).select("*")
                .eq("firm_id", firm_id)
                .eq("bank_account_id", bank_account_id)
                .eq("header_fingerprint", fingerprint)
                .limit(1).execute().data) or []
    except Exception as e:                                       # noqa: BLE001
        # A lookup failure must not block an import that would otherwise work
        # by detection. The caller falls back to detect_format.
        _logger.warning("column mapping lookup failed: %s", e)
        return None
    return rows[0] if rows else None


def list_mappings(db, firm_id: str, client_id: Optional[str] = None,
                  bank_account_id: Optional[str] = None) -> list[dict]:
    if not db:
        return []
    q = db.table(TABLE).select("*").eq("firm_id", firm_id)
    if client_id:
        q = q.eq("client_id", client_id)
    if bank_account_id:
        q = q.eq("bank_account_id", bank_account_id)
    try:
        return (q.order("created_at", desc=True).execute().data) or []
    except Exception as e:                                       # noqa: BLE001
        _logger.warning("column mapping list failed: %s", e)
        return []


def save_mapping(db, firm_id: str, client_id: str, bank_account_id: str,
                 headers: list, mapping: dict, *,
                 actor_id: Optional[str] = None) -> dict:
    """Store the mapping for this account and layout, replacing any earlier one.

    Validated against the ACTUAL header row before it is written, so a mapping
    that could never parse this file cannot be saved and then silently applied
    to the next import. Raises StatementParseError, which the router renders as
    a 422.
    """
    clean = validate_mapping(mapping, len(headers))
    fingerprint = header_fingerprint(headers)
    row = {
        "firm_id": firm_id,
        "client_id": client_id,
        "bank_account_id": bank_account_id,
        "header_fingerprint": fingerprint,
        "header_labels": [str(h) if h is not None else "" for h in headers],
        "mapping": {k: clean.get(k) for k in MAPPING_KEYS},
        "created_by": actor_id,
    }
    if not db:
        return {**row, "id": "mock-mapping-id"}

    existing = find_mapping(db, firm_id, bank_account_id, fingerprint)
    if existing:
        # Re-mapping the same layout is a correction, not a second answer. The
        # unique index would refuse an insert anyway; updating in place keeps
        # the row's identity so anything referring to it still resolves.
        out = (db.table(TABLE).update({
            "mapping": row["mapping"],
            "header_labels": row["header_labels"],
            "updated_at": "now()",
        }).eq("id", existing["id"]).execute().data) or []
        return out[0] if out else {**existing, **row}
    out = (db.table(TABLE).insert(row).execute().data) or []
    return out[0] if out else row


def delete_mapping(db, firm_id: str, mapping_id: str) -> bool:
    if not db:
        return True
    try:
        (db.table(TABLE).delete()
         .eq("firm_id", firm_id).eq("id", mapping_id).execute())
        return True
    except Exception as e:                                       # noqa: BLE001
        _logger.warning("column mapping delete failed: %s", e)
        return False
