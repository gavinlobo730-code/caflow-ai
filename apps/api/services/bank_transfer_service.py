"""
Transfer auto-detection and pairing (Tier 1.5).

Finds the two halves of one movement between the client's own accounts, and —
once a human confirms — records them as a pair in which exactly ONE side carries
the journal.

That second part is the point. `posting_map.build_transfer_lines` already writes
the complete double entry, so a detected pair whose sides both post would
double-count the cash: the very bug this exists to prevent. Pairing is written
through an RPC (migration 258) so a half-paired state — one side pointing at a
partner that does not point back, free to post its own journal — cannot exist.

Detection is a SUGGESTION. Nothing is paired without a human clicking.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException

from core.db_paging import fetch_all
from domain.banking.transfers import (
    DEFAULT_WINDOW_DAYS, TransferPair, describe, detect, scan_window,
)

_logger = logging.getLogger("caflow.bank_transfers")


class BankTransferService:

    def _get_txn(self, db, firm_id: str, txn_id: str) -> dict:
        rows = (db.table("bank_transactions").select("*")
                .eq("id", txn_id).eq("firm_id", firm_id).limit(1).execute().data) or []
        if not rows:
            raise HTTPException(status_code=404, detail="Bank transaction not found.")
        return rows[0]

    def _account_by_statement(self, db, firm_id: str, client_id: str) -> dict:
        """statement_id -> bank_account_id. One query; the pairing rules need to
        know which account each line belongs to, and that lives on the statement."""
        rows = (db.table("bank_statements").select("id, bank_account_id")
                .eq("firm_id", firm_id).eq("client_id", client_id).execute().data) or []
        return {r["id"]: r.get("bank_account_id") for r in rows}

    # ── detection ───────────────────────────────────────────────────────────
    def detect_pairs(self, db, firm_id: str, client_id: str,
                     window_days: int = DEFAULT_WINDOW_DAYS,
                     txns: Optional[list[dict]] = None,
                     around: Optional[list[dict]] = None) -> list[TransferPair]:
        """Candidate pairs for this client. Never writes.

        `around` IS THE ROWS AN ANSWER IS WANTED FOR, and passing it is what
        keeps this proportional to the question rather than to the ledger
        (BANK-15). The scan then covers only `transfers.scan_window` of those
        dates, which is every row that could pair with one of them and every
        row that could compete for the same counterpart.

        This used to read the newest 1,000 transactions of the whole client,
        and that was not only slow. `bank_entry_service.redraft` walks its
        chunks in transaction_date order, OLDEST FIRST, so on a client past a
        thousand lines the index it consulted covered the newest lines and the
        chunk it was drafting was the oldest: every old line was told it had no
        transfer counterpart, which is a wrong answer rather than a slow one.
        And the cap was silent — 1,000 rows and 1,000-of-40,000 rows come back
        looking identical.

        With no `around` the scan is the whole client, PAGED — `fetch_all`
        rather than a cap, because a truncated read here says "no transfer"
        about lines it never looked at.
        """
        rows = txns
        if rows is None:
            lo, hi = scan_window(around or [], window_days=window_days)

            def q():
                base = (db.table("bank_transactions").select("*")
                        .eq("firm_id", firm_id).eq("client_id", client_id))
                if lo and hi:
                    base = (base.gte("transaction_date", lo.isoformat())
                                .lte("transaction_date", hi.isoformat()))
                return base

            rows = fetch_all(q, label="bank_transfer_scan")
        by_stmt = self._account_by_statement(db, firm_id, client_id)
        # The domain module compares accounts, not statements — a client can have
        # many statements per account, and two lines on different statements of
        # the SAME account are not a transfer.
        enriched = [{**t, "bank_account_id": by_stmt.get(t.get("statement_id"))} for t in rows]
        return detect(enriched, window_days=window_days)

    @staticmethod
    def as_dict(p: TransferPair) -> dict:
        return {
            "primary_id": p.primary_id,
            "counterpart_id": p.counterpart_id,
            "amount_paise": p.amount_paise,
            "primary_date": p.primary_date.isoformat() if p.primary_date else None,
            "counterpart_date": p.counterpart_date.isoformat() if p.counterpart_date else None,
            "primary_account_id": p.primary_account_id,
            "counterpart_account_id": p.counterpart_account_id,
            "day_gap": p.day_gap,
            "confidence": p.confidence,
            "is_unambiguous": p.is_unambiguous,
            "primary_alternatives": p.primary_alternatives,
            "counterpart_alternatives": p.counterpart_alternatives,
            "summary": describe(p),
        }

    # ── pairing ─────────────────────────────────────────────────────────────
    def pair(self, db, firm_id: str, primary_id: str, counterpart_id: str,
             actor_id: Optional[str] = None) -> dict:
        """Record two lines as one transfer. The RPC re-checks every rule."""
        try:
            db.rpc("pair_bank_transfer", {
                "p_firm_id": firm_id, "p_primary_id": primary_id,
                "p_counter_id": counterpart_id, "p_actor_id": actor_id,
            }).execute()
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Could not pair the transfer: {e}")

        self._log(firm_id, primary_id, actor_id,
                  {"transfer_pair_id": counterpart_id, "transfer_is_primary": True})
        self._log(firm_id, counterpart_id, actor_id,
                  {"transfer_pair_id": primary_id, "transfer_is_primary": False})
        return self.get(db, firm_id, primary_id)

    def unpair(self, db, firm_id: str, txn_id: str, actor_id: Optional[str] = None) -> dict:
        try:
            db.rpc("unpair_bank_transfer", {
                "p_firm_id": firm_id, "p_txn_id": txn_id,
            }).execute()
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Could not unpair the transfer: {e}")
        self._log(firm_id, txn_id, actor_id, {"transfer_pair_id": None})
        return self.get(db, firm_id, txn_id)

    @staticmethod
    def _log(firm_id, txn_id, actor_id, new_data) -> None:
        try:
            from services.audit_service import log_event
            log_event(firm_id, "bank_transaction", txn_id, "update", actor_id=actor_id,
                      new_data=new_data, metadata={"source": "bank_transfer_pair"})
        except Exception:  # pragma: no cover - audit must never block
            pass

    def get(self, db, firm_id: str, txn_id: str) -> dict:
        txn = self._get_txn(db, firm_id, txn_id)
        return {
            "transaction_id": txn_id,
            "transfer_pair_id": txn.get("transfer_pair_id"),
            "transfer_is_primary": txn.get("transfer_is_primary"),
            "is_paired": bool(txn.get("transfer_pair_id")),
            "category": txn.get("category"),
        }

    # ── used by the posting engine ──────────────────────────────────────────
    def counterpart_bank_account(self, db, firm_id: str, txn: dict) -> Optional[str]:
        """The GL account of the OTHER side of this transfer.

        Lets a paired transfer post without the CA re-selecting a destination
        they have already identified by confirming the pair.
        """
        pair_id = txn.get("transfer_pair_id")
        if not pair_id:
            return None
        other = (db.table("bank_transactions").select("statement_id, client_id")
                 .eq("id", pair_id).eq("firm_id", firm_id).limit(1).execute().data or [None])[0]
        if not other:
            return None
        stmt = (db.table("bank_statements").select("bank_account_id")
                .eq("id", other.get("statement_id")).eq("firm_id", firm_id)
                .limit(1).execute().data or [None])[0]
        if not stmt or not stmt.get("bank_account_id"):
            return None
        acct = (db.table("bank_accounts").select("coa_account_id")
                .eq("id", stmt["bank_account_id"]).eq("firm_id", firm_id)
                .eq("client_id", other.get("client_id")).limit(1).execute().data or [None])[0]
        return (acct or {}).get("coa_account_id")


bank_transfer_service = BankTransferService()
