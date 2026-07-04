"""
Banking domain service — the single entry point for every bank-transaction
mutation (Phase B.0 foundation).

Before B.0 the browser wrote bank statements, transaction mappings and even the
double-entry journal directly to Supabase. That violated CLAUDE.md ("zero
business logic in the frontend") and made the frontend a second source of
accounting truth. All of that logic now lives here, behind the API:

  • import_statement      — store an already-parsed statement + its lines
                            (file PARSING stays out of scope — that is Phase B.1)
  • set_account / ignore  — map a transaction to a GL account / mark ignored
  • post_transaction      — post to the ledger via the shared double-entry engine
                            (phase2_journal_service), respecting FY locks

Canonical bank_transactions model (verified against the live schema, migration
094): transaction_date, match_status (unmatched|matched|posted|ignored),
account_id, reconciled_journal_id. match_status is the single source of truth;
the legacy `reconciled` boolean is kept in sync for backward compatibility.

Integer paise throughout — never float. Every method is firm-scoped.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from services.phase2_journal_service import phase2_journal_service
from services.period_validation_service import period_validation_service
from services.timeline_service import timeline_service
from domain.banking.dedup import transaction_hash

_logger = logging.getLogger("caflow.banking")

VALID_MATCH_STATUSES = frozenset({"unmatched", "matched", "posted", "ignored"})

# Batch size for chunked transaction inserts (large-statement safe).
_IMPORT_BATCH = 500


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _opening_closing_balance(rows: list[dict]) -> tuple[int, int]:
    """Return (opening_balance_paise, closing_balance_paise) derived from the
    rows' transaction_date order, not raw file position.

    R2.11: some bank exports list the most recent transaction FIRST
    (newest-first/descending), which previously inverted opening/closing —
    row[0]'s balance (actually the closing balance) was stored as "opening"
    and vice versa.

    Adversarial-review fix (R2.11 fix phase): the original version compared
    only rows[0] vs rows[-1], which a single out-of-place row (or a file whose
    first/last row coincidentally share one date while OTHER rows in between
    span different dates) could fool into either the wrong direction or a
    false "single-day" classification — silently discarding the true min/max
    date's balance. This version finds the TRUE earliest/latest date across
    every row (matching how _import_core derives statement_from/statement_to
    via a full sort), decides the file's overall direction by a majority vote
    across every adjacent pair (robust to a handful of out-of-order rows,
    unlike a bare two-endpoint compare), and picks the correct occurrence of
    the extreme date accordingly — the FIRST file-order occurrence of the
    earliest date and the LAST file-order occurrence of the latest date if
    the file is ascending overall, or the reverse if descending. A genuinely
    single-day statement (every row shares one date) has no cross-date signal
    at all and falls back to file order — a residual limitation of date-only
    (no timestamp) granularity. An exact ascending/descending tie (e.g. only
    two rows total) defaults to ascending, the more common convention.
    """
    if not rows:
        return 0, 0
    if len(rows) == 1:
        return rows[0]["balance_paise"], rows[0]["balance_paise"]

    dates = [r["transaction_date"] for r in rows]
    min_date, max_date = min(dates), max(dates)
    if min_date == max_date:
        return rows[0]["balance_paise"], rows[-1]["balance_paise"]

    ascending_votes = sum(1 for a, b in zip(dates, dates[1:]) if a <= b)
    descending_votes = sum(1 for a, b in zip(dates, dates[1:]) if a >= b)
    is_descending = descending_votes > ascending_votes

    first_at_min = next(r for r in rows if r["transaction_date"] == min_date)
    last_at_min = next(r for r in reversed(rows) if r["transaction_date"] == min_date)
    first_at_max = next(r for r in rows if r["transaction_date"] == max_date)
    last_at_max = next(r for r in reversed(rows) if r["transaction_date"] == max_date)

    if is_descending:
        return last_at_min["balance_paise"], first_at_max["balance_paise"]
    return first_at_min["balance_paise"], last_at_max["balance_paise"]


class BankingService:
    """All bank-transaction mutations. db is the Supabase client (caller-supplied)."""

    # ── Statement import (B.1: dedup + chunked insert + file metadata) ────────
    def import_statement(
        self, db, firm_id: str, client_id: str, bank_name: str,
        account_number: Optional[str], rows: list[dict],
        bank_account_id: Optional[str] = None, actor_id: Optional[str] = None,
    ) -> dict:
        """Backward-compatible entry: store already-normalised dict rows
        (transaction_date / description / reference_no / *_paise). Deduplicates and
        chunk-inserts via the shared core."""
        norm = [{
            "transaction_date": str(r["transaction_date"])[:10],
            "description": r.get("description", ""),
            "reference_no": r.get("reference_no"),
            "debit_paise": int(r.get("debit_paise", 0) or 0),
            "credit_paise": int(r.get("credit_paise", 0) or 0),
            "balance_paise": int(r.get("balance_paise", 0) or 0),
        } for r in rows]
        return self._import_core(db, firm_id, client_id, bank_name, account_number,
                                 norm, bank_account_id, actor_id, file_meta=None)

    def import_normalized(
        self, db, firm_id: str, client_id: str, bank_name: str,
        account_number: Optional[str], txns: list, bank_account_id: Optional[str] = None,
        actor_id: Optional[str] = None, file_meta: Optional[dict] = None,
    ) -> dict:
        """Store NormalizedTxn rows produced by the server-side normalizer (B.1)."""
        norm = [{
            "transaction_date": t.transaction_date, "description": t.description,
            "reference_no": t.reference_no, "debit_paise": t.debit_paise,
            "credit_paise": t.credit_paise, "balance_paise": t.balance_paise,
        } for t in txns]
        return self._import_core(db, firm_id, client_id, bank_name, account_number,
                                 norm, bank_account_id, actor_id, file_meta=file_meta)

    def _existing_hashes(self, db, firm_id: str, client_id: str, hashes: list[str]) -> set:
        """Hashes already stored for this client (chunked IN lookup)."""
        found: set = set()
        for i in range(0, len(hashes), 200):
            res = (db.table("bank_transactions").select("import_hash")
                   .eq("firm_id", firm_id).eq("client_id", client_id)
                   .in_("import_hash", hashes[i:i + 200]).execute())
            for row in (res.data or []):
                if row.get("import_hash"):
                    found.add(row["import_hash"])
        return found

    def _import_core(self, db, firm_id, client_id, bank_name, account_number,
                     norm: list[dict], bank_account_id, actor_id, file_meta) -> dict:
        if not norm:
            raise HTTPException(status_code=400, detail="No transactions provided.")

        # 1) fingerprint every row; drop within-file duplicates (keep first).
        seen, deduped = set(), []
        for r in norm:
            h = transaction_hash(
                client_id, bank_account_id, r["transaction_date"],
                r["debit_paise"], r["credit_paise"], r["balance_paise"],
                r["description"], r["reference_no"],
            )
            if h not in seen:
                seen.add(h)
                deduped.append({**r, "import_hash": h})

        total_rows = len(norm)
        # 2) drop rows already stored for this client (idempotent re-import).
        existing = self._existing_hashes(db, firm_id, client_id, [r["import_hash"] for r in deduped])
        new_rows = [r for r in deduped if r["import_hash"] not in existing]
        duplicates = total_rows - len(new_rows)

        if not new_rows:
            return {"statement_id": None, "imported": 0,
                    "duplicates_skipped": duplicates, "total_rows": total_rows}

        # 3) statement header (summary over the rows actually stored).
        dates = sorted(r["transaction_date"] for r in new_rows)
        opening_paise, closing_paise = _opening_closing_balance(new_rows)
        stmt_payload = {
            "firm_id": firm_id, "client_id": client_id, "bank_name": bank_name,
            "account_number": account_number,
            "statement_from": dates[0], "statement_to": dates[-1],
            "opening_balance_paise": opening_paise,
            "closing_balance_paise": closing_paise,
            "total_debits_paise": sum(r["debit_paise"] for r in new_rows),
            "total_credits_paise": sum(r["credit_paise"] for r in new_rows),
            "row_count": len(new_rows), "import_status": "pending",
            "imported_count": len(new_rows), "duplicate_count": duplicates,
        }
        if bank_account_id:
            stmt_payload["bank_account_id"] = bank_account_id
        if file_meta:
            for k in ("file_name", "file_size_bytes", "source_format", "file_hash"):
                if file_meta.get(k) is not None:
                    stmt_payload[k] = file_meta[k]

        stmt = db.table("bank_statements").insert(stmt_payload).execute().data
        if not stmt:
            raise HTTPException(status_code=500, detail="Failed to create bank statement.")
        statement_id = stmt[0]["id"]

        # 4) chunked transaction insert (large-statement safe).
        for i in range(0, len(new_rows), _IMPORT_BATCH):
            db.table("bank_transactions").insert([{
                "statement_id": statement_id, "firm_id": firm_id, "client_id": client_id,
                "transaction_date": r["transaction_date"], "description": r["description"],
                "debit_paise": r["debit_paise"], "credit_paise": r["credit_paise"],
                "balance_paise": r["balance_paise"], "reference_no": r["reference_no"],
                "import_hash": r["import_hash"], "match_status": "unmatched",
            } for r in new_rows[i:i + _IMPORT_BATCH]]).execute()

        timeline_service.log(
            client_id, "accounting", "Bank Statement Imported",
            f"{len(new_rows)} transactions imported from {bank_name}"
            + (f" ({duplicates} duplicate(s) skipped)" if duplicates else ""),
            "info", firm_id=firm_id, entity_type="bank_statement",
            entity_id=statement_id, actor_id=actor_id,
        )
        try:
            from services.audit_service import log_event
            log_event(firm_id, "bank_statement", statement_id, "create", actor_id=actor_id,
                      new_data={"imported": len(new_rows), "duplicates_skipped": duplicates},
                      metadata={"source": "bank_feed_import",
                                "file_name": (file_meta or {}).get("file_name")})
        except Exception:  # pragma: no cover - audit must never block import
            pass
        return {"statement_id": statement_id, "imported": len(new_rows),
                "duplicates_skipped": duplicates, "total_rows": total_rows}

    # ── Account mapping ───────────────────────────────────────────────────────
    def set_account(self, db, firm_id: str, txn_id: str, account_id: str) -> dict:
        txn = self._get_txn(db, firm_id, txn_id)
        if txn["match_status"] == "posted":
            raise HTTPException(status_code=409, detail="Transaction already posted to the ledger.")
        db.table("bank_transactions").update({
            "account_id": account_id, "match_status": "matched", "updated_at": _now(),
        }).eq("id", txn_id).eq("firm_id", firm_id).execute()
        return {"id": txn_id, "match_status": "matched", "account_id": account_id}

    def ignore(self, db, firm_id: str, txn_id: str) -> dict:
        txn = self._get_txn(db, firm_id, txn_id)
        if txn["match_status"] == "posted":
            raise HTTPException(status_code=409, detail="Cannot ignore a posted transaction.")
        db.table("bank_transactions").update({
            "match_status": "ignored", "updated_at": _now(),
        }).eq("id", txn_id).eq("firm_id", firm_id).execute()
        return {"id": txn_id, "match_status": "ignored"}

    # ── Posting to the ledger ─────────────────────────────────────────────────
    def post_transaction(
        self, db, firm_id: str, txn_id: str, account_id: str,
        bank_coa_account_id: str, actor_id: Optional[str] = None,
    ) -> dict:
        """Post a bank transaction to the ledger via the shared double-entry engine.
        Refuses to post into a locked financial year. Records the journal link on
        the transaction and advances match_status to 'posted'."""
        txn = self._get_txn(db, firm_id, txn_id)
        if txn["match_status"] == "posted":
            raise HTTPException(status_code=409, detail="Transaction already posted.")
        client_id = txn["client_id"]

        # FY lock (Companies Act §128 / firm policy) — never post into a closed period.
        period_validation_service.validate_posting_date(firm_id, str(txn["transaction_date"])[:10])

        journal_entry_id = phase2_journal_service.journal_for_bank_transaction(
            db, firm_id, client_id, txn, account_id, bank_coa_account_id,
        )

        # Posting records the journal link only; reconciliation (B.4) is a separate
        # human step that owns the `reconciled` / `reconciled_at` columns.
        db.table("bank_transactions").update({
            "account_id": account_id,
            "match_status": "posted",
            "posted_journal_id": journal_entry_id,
            "updated_at": _now(),
        }).eq("id", txn_id).eq("firm_id", firm_id).execute()

        timeline_service.log(
            client_id, "accounting", "Bank Transaction Posted",
            f"Posted to ledger: {txn.get('description', '')}", "success",
            firm_id=firm_id, entity_type="bank_transaction", entity_id=txn_id,
            actor_id=actor_id,
        )
        return {"id": txn_id, "match_status": "posted", "journal_entry_id": journal_entry_id}

    # ── Reads ─────────────────────────────────────────────────────────────────
    def list_statements(self, db, firm_id: str, client_id: Optional[str] = None) -> list:
        q = db.table("bank_statements").select("*").eq("firm_id", firm_id)
        if client_id:
            q = q.eq("client_id", client_id)
        return q.order("created_at", desc=True).execute().data or []

    def list_transactions(
        self, db, firm_id: str, statement_id: Optional[str] = None,
        client_id: Optional[str] = None, match_status: Optional[str] = None,
        date_from: Optional[str] = None, date_to: Optional[str] = None,
        min_amount_paise: Optional[int] = None, max_amount_paise: Optional[int] = None,
    ) -> list:
        q = db.table("bank_transactions").select("*").eq("firm_id", firm_id)
        if statement_id:
            q = q.eq("statement_id", statement_id)
        if client_id:
            q = q.eq("client_id", client_id)
        if match_status:
            q = q.eq("match_status", match_status)
        if date_from:
            q = q.gte("transaction_date", date_from[:10])
        if date_to:
            q = q.lte("transaction_date", date_to[:10])
        rows = q.order("transaction_date").execute().data or []
        # Amount filter on the transaction magnitude (max of debit/credit).
        if min_amount_paise is not None or max_amount_paise is not None:
            lo = min_amount_paise if min_amount_paise is not None else 0
            hi = max_amount_paise if max_amount_paise is not None else None
            def amt(r):
                return max(int(r.get("debit_paise") or 0), int(r.get("credit_paise") or 0))
            rows = [r for r in rows if amt(r) >= lo and (hi is None or amt(r) <= hi)]
        return rows

    # ── internal ──────────────────────────────────────────────────────────────
    def _get_txn(self, db, firm_id: str, txn_id: str) -> dict:
        res = (db.table("bank_transactions").select("*")
               .eq("id", txn_id).eq("firm_id", firm_id).single().execute())
        if not res.data:
            raise HTTPException(status_code=404, detail="Bank transaction not found.")
        return res.data


# Module-level singleton (mirrors phase2_journal_service)
banking_service = BankingService()
