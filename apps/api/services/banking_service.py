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

_logger = logging.getLogger("caflow.banking")

VALID_MATCH_STATUSES = frozenset({"unmatched", "matched", "posted", "ignored"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BankingService:
    """All bank-transaction mutations. db is the Supabase client (caller-supplied)."""

    # ── Statement import (storage only — parsing is Phase B.1) ────────────────
    def import_statement(
        self, db, firm_id: str, client_id: str, bank_name: str,
        account_number: Optional[str], rows: list[dict],
        bank_account_id: Optional[str] = None, actor_id: Optional[str] = None,
    ) -> dict:
        """Insert a bank_statements header and its bank_transactions lines.
        `rows` are already parsed (date/description/paise) — this service does not
        parse files. All amounts are integer paise."""
        if not rows:
            raise HTTPException(status_code=400, detail="No transactions provided.")

        dates = sorted(str(r["transaction_date"])[:10] for r in rows)
        total_debits = sum(int(r.get("debit_paise", 0) or 0) for r in rows)
        total_credits = sum(int(r.get("credit_paise", 0) or 0) for r in rows)
        stmt_payload = {
            "firm_id": firm_id, "client_id": client_id, "bank_name": bank_name,
            "account_number": account_number,
            "statement_from": dates[0], "statement_to": dates[-1],
            "opening_balance_paise": int(rows[0].get("balance_paise", 0) or 0),
            "closing_balance_paise": int(rows[-1].get("balance_paise", 0) or 0),
            "total_debits_paise": total_debits, "total_credits_paise": total_credits,
            "row_count": len(rows), "import_status": "pending",
        }
        if bank_account_id:
            stmt_payload["bank_account_id"] = bank_account_id

        stmt = db.table("bank_statements").insert(stmt_payload).execute().data
        if not stmt:
            raise HTTPException(status_code=500, detail="Failed to create bank statement.")
        statement_id = stmt[0]["id"]

        db.table("bank_transactions").insert([
            {
                "statement_id": statement_id, "firm_id": firm_id, "client_id": client_id,
                "transaction_date": str(r["transaction_date"])[:10],
                "description": r.get("description", ""),
                "debit_paise": int(r.get("debit_paise", 0) or 0),
                "credit_paise": int(r.get("credit_paise", 0) or 0),
                "balance_paise": int(r.get("balance_paise", 0) or 0),
                "reference_no": r.get("reference_no"),
                "match_status": "unmatched",
            }
            for r in rows
        ]).execute()

        timeline_service.log(
            client_id, "accounting", "Bank Statement Imported",
            f"{len(rows)} transactions imported from {bank_name}", "info",
            firm_id=firm_id, entity_type="bank_statement", entity_id=statement_id,
            actor_id=actor_id,
        )
        return {"statement_id": statement_id, "imported": len(rows)}

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

        db.table("bank_transactions").update({
            "account_id": account_id,
            "match_status": "posted",
            "reconciled": True,                       # legacy flag, kept in sync
            "reconciled_journal_id": journal_entry_id,
            "reconciled_at": _now(),
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
    ) -> list:
        q = db.table("bank_transactions").select("*").eq("firm_id", firm_id)
        if statement_id:
            q = q.eq("statement_id", statement_id)
        if client_id:
            q = q.eq("client_id", client_id)
        if match_status:
            q = q.eq("match_status", match_status)
        return q.order("transaction_date").execute().data or []

    # ── internal ──────────────────────────────────────────────────────────────
    def _get_txn(self, db, firm_id: str, txn_id: str) -> dict:
        res = (db.table("bank_transactions").select("*")
               .eq("id", txn_id).eq("firm_id", firm_id).single().execute())
        if not res.data:
            raise HTTPException(status_code=404, detail="Bank transaction not found.")
        return res.data


# Module-level singleton (mirrors phase2_journal_service)
banking_service = BankingService()
