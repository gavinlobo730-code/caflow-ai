"""
Bank transaction splits (Tier 1.2) — read and replace.

Writes go through ONE path: the replace_bank_transaction_splits RPC (migration
256). That is deliberate. The invariant — splits sum exactly to what the bank
moved — spans rows, so it cannot be a CHECK, and PostgREST commits each
statement separately, so a delete-then-insert through the REST API would leave a
window where the transaction is half-split. The RPC does both inside one
transaction and refuses to commit unless they tie.

The domain module validates the same rules first, so the CA gets a message about
₹2,200 being unallocated rather than a Postgres error. The RPC is the backstop,
not the error surface — but it is a real backstop: it also catches anything that
reaches the database by another route.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException

from domain.banking.splits import (
    parse_splits, validate_splits, unallocated_paise, SplitError,
)

_logger = logging.getLogger("caflow.bank_splits")


def _amount(txn: dict) -> tuple[int, bool]:
    debit = int(txn.get("debit_paise") or 0)
    credit = int(txn.get("credit_paise") or 0)
    return max(debit, credit), credit > 0


class BankSplitService:

    def _get_txn(self, db, firm_id: str, txn_id: str) -> dict:
        res = (db.table("bank_transactions").select("*")
               .eq("id", txn_id).eq("firm_id", firm_id).limit(1).execute())
        rows = res.data or []
        if not rows:
            raise HTTPException(status_code=404, detail="Bank transaction not found.")
        return rows[0]

    def _validate_accounts(self, db, firm_id: str, client_id: str, account_ids: list[str]) -> None:
        """Every split account must belong to this firm and be usable by this
        client. Without this a split could post to another firm's GL account —
        the same unscoped-read-by-id class of bug task #227/#228 fixed in the
        AR/AP and bank-posting paths."""
        if not account_ids:
            return
        rows = (db.table("chart_of_accounts").select("id, client_id, is_active")
                .eq("firm_id", firm_id).in_("id", list(set(account_ids)))
                .execute().data) or []
        found = {r["id"]: r for r in rows}
        for aid in set(account_ids):
            r = found.get(aid)
            if not r:
                raise HTTPException(status_code=422,
                                    detail="A selected account does not belong to this firm.")
            if r.get("is_active") is False:
                raise HTTPException(status_code=422,
                                    detail="A selected account is archived and cannot be posted to.")
            if r.get("client_id") not in (None, client_id):
                raise HTTPException(status_code=422,
                                    detail="A selected account belongs to a different client.")

    @staticmethod
    def _settles_a_document(txn: dict) -> bool:
        """True when posting this transaction will also settle an invoice/bill.

        Shares bank_posting_service's definition rather than restating it, so the
        two guards cannot drift apart and let a split through on one path.
        """
        from services.bank_posting_service import bank_posting_service
        return bank_posting_service._settles_a_document(txn)

    # ── read ────────────────────────────────────────────────────────────────
    def list_splits(self, db, firm_id: str, txn_id: str) -> list[dict]:
        return (db.table("bank_transaction_splits").select("*")
                .eq("firm_id", firm_id).eq("bank_transaction_id", txn_id)
                .order("sequence_no").execute().data) or []

    def get(self, db, firm_id: str, txn_id: str) -> dict:
        """The split set plus what is still unallocated, for the editor."""
        txn = self._get_txn(db, firm_id, txn_id)
        rows = self.list_splits(db, firm_id, txn_id)
        amount, is_credit = _amount(txn)
        allocated = sum(int(r.get("amount_paise") or 0) for r in rows)
        return {
            "transaction_id": txn_id,
            "amount_paise": amount,
            "is_credit": is_credit,
            "splits": rows,
            "allocated_paise": allocated,
            "unallocated_paise": amount - allocated,
            "is_split": len(rows) > 0,
            # Once a journal exists the splits are frozen: the journal is
            # immutable (migration 251), so editing them would leave the ledger
            # and its explanation disagreeing.
            "editable": not txn.get("posted_journal_id"),
        }

    # ── write ───────────────────────────────────────────────────────────────
    def replace(self, db, firm_id: str, txn_id: str, splits: list[dict],
                actor_id: Optional[str] = None) -> dict:
        """Replace a transaction's splits, atomically. An empty list clears them
        and returns the transaction to an ordinary single-account posting."""
        txn = self._get_txn(db, firm_id, txn_id)
        if txn.get("posted_journal_id"):
            raise HTTPException(
                status_code=409,
                detail=("This transaction already has a journal. Reverse it before "
                        "changing how the amount is split."))
        amount, _ = _amount(txn)
        if splits and self._settles_a_document(txn):
            # Refuse at the point of splitting, not only at posting: the CA
            # should find out while they still have the editor open, and a saved
            # split that can never be posted is worse than no split.
            raise HTTPException(
                status_code=422,
                detail=("This transaction is matched to an invoice or bill, so it settles "
                        "that document in full. Unmatch it before splitting it across "
                        "accounts."))

        payload: list[dict] = []
        if splits:
            try:
                parsed = parse_splits(splits)
                validate_splits(parsed, amount)
            except SplitError as e:
                # A business message, not a database error — the CA is being
                # told which figure is wrong and by how much.
                raise HTTPException(status_code=422, detail=str(e))
            self._validate_accounts(db, firm_id, txn["client_id"],
                                    [s.account_id for s in parsed])
            payload = [{"account_id": s.account_id, "amount_paise": s.amount_paise,
                        "narration": s.narration} for s in parsed]

        try:
            db.rpc("replace_bank_transaction_splits", {
                "p_firm_id": firm_id, "p_txn_id": txn_id,
                "p_splits": payload, "p_actor_id": actor_id,
            }).execute()
        except Exception as e:
            # The RPC re-checks everything above. Reaching here means either a
            # genuine race (the transaction got posted between our check and the
            # call) or a caller that bypassed validation — both worth surfacing
            # rather than swallowing.
            from core.observability import capture_posting_failure
            capture_posting_failure(e, operation="bank_splits.replace",
                                    firm_id=firm_id, transaction_id=txn_id)
            raise HTTPException(status_code=422,
                                detail=f"Could not save the split: {e}")

        try:
            from services.audit_service import log_event
            log_event(firm_id, "bank_transaction", txn_id, "update", actor_id=actor_id,
                      new_data={"splits": payload, "split_count": len(payload)},
                      metadata={"source": "bank_split"})
        except Exception:  # pragma: no cover - audit must never block
            pass

        return self.get(db, firm_id, txn_id)

    # ── used by the posting engine ──────────────────────────────────────────
    def splits_for_posting(self, db, firm_id: str, txn_id: str, amount_paise: int):
        """Parsed, validated splits — or None when the transaction is not split.

        Re-validates against the CURRENT amount rather than trusting what was
        stored. Nothing in this system edits a bank transaction's amount today,
        but posting a journal from splits that no longer tie is exactly the kind
        of thing that must fail loudly rather than balance by luck.
        """
        rows = self.list_splits(db, firm_id, txn_id)
        if not rows:
            return None
        parsed = parse_splits(rows)
        try:
            validate_splits(parsed, amount_paise)
        except SplitError as e:
            raise HTTPException(
                status_code=422,
                detail=(f"The saved split no longer matches the transaction: {e} "
                        "Re-open the split and correct it before posting."))
        return parsed


bank_split_service = BankSplitService()
