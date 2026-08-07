"""
Batch accept / exclude (Tier 1.7) and attachments (Tier 1.8).

WHY A BATCH ACTION REPORTS PER ROW
    The existing bulk categorize fires one request per selected row from the
    browser and reports a count. That is fine when every row succeeds and
    misleading when one does not: "8 applied" tells a CA nothing about which two
    did not, or why.

    A bulk action over financial records has to say what happened to EACH row.
    Some rows will legitimately fail — already posted, already ignored, nothing
    to accept — and a partial success reported as a success is how a
    transaction quietly stays uncoded until year end. So every entry comes back
    with an outcome and, when it failed, a reason in words.

    Nothing here is atomic across rows, deliberately: eight good rows should not
    be rolled back because the ninth was already posted. Each row is its own
    decision, which is exactly why each needs its own answer.

WHAT "ACCEPT" MEANS
    Whatever this row already has to offer, in order of how strong the evidence
    is: a matching rule first (a human wrote it), then learned history (a human
    did it before). A row with neither is reported as skipped rather than
    guessed at — the whole module's contract is that no GL account is ever
    invented.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from domain.banking import attachments as att
from domain.banking.categories import is_valid_category

_logger = logging.getLogger("caflow.bank_batch")

# A batch is a human selecting rows on a screen. Beyond this it is a script, and
# a script should be using the per-row endpoints where failures are visible.
MAX_BATCH = 200


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BankBatchService:

    def _fetch(self, db, firm_id: str, txn_ids: list[str]) -> dict:
        rows = (db.table("bank_transactions").select("*")
                .eq("firm_id", firm_id).in_("id", txn_ids).execute().data) or []
        return {r["id"]: r for r in rows}

    @staticmethod
    def _check_batch(txn_ids: list[str]) -> list[str]:
        ids = [str(t).strip() for t in (txn_ids or []) if str(t).strip()]
        if not ids:
            raise HTTPException(status_code=422, detail="Select at least one transaction.")
        if len(ids) > MAX_BATCH:
            raise HTTPException(
                status_code=422,
                detail=f"Select at most {MAX_BATCH} transactions at a time.")
        # Duplicates in one batch would produce two outcomes for one row and
        # make the counts disagree with reality.
        return list(dict.fromkeys(ids))

    # ── 1.7 accept ──────────────────────────────────────────────────────────
    def accept(self, db, firm_id: str, txn_ids: list[str],
               actor_id: Optional[str] = None) -> dict:
        """Apply each row's own strongest suggestion. Per-row outcomes."""
        ids = self._check_batch(txn_ids)
        found = self._fetch(db, firm_id, ids)

        # Both suggestion sources, built once for the whole batch rather than
        # once per row — same reasoning as the queue.
        from services.bank_payee_service import bank_payee_service
        from domain.banking.rules import match_rule
        client_ids = {r.get("client_id") for r in found.values() if r.get("client_id")}
        history: dict = {}
        rules_by_client: dict = {}
        for cid in client_ids:
            history[cid] = bank_payee_service.history_index(db, firm_id, cid)
        rules = (db.table("bank_matching_rules").select("*")
                 .eq("firm_id", firm_id).eq("is_active", True)
                 .order("created_at").execute().data) or []
        for r in rules:
            rules_by_client.setdefault(r.get("client_id"), []).append(r)

        results = []
        for txn_id in ids:
            txn = found.get(txn_id)
            if not txn:
                results.append(self._outcome(txn_id, "failed", "Not found for this firm."))
                continue
            if txn.get("posted_journal_id") or txn.get("match_status") == "posted":
                results.append(self._outcome(
                    txn_id, "skipped", "Already posted — its coding is decided."))
                continue
            if txn.get("match_status") == "ignored":
                results.append(self._outcome(
                    txn_id, "skipped", "Excluded. Include it again first."))
                continue

            category, account_id, source = self._suggestion_for(
                txn, rules_by_client, history, bank_payee_service, match_rule)
            if not (category or account_id):
                results.append(self._outcome(
                    txn_id, "skipped",
                    "Nothing to accept — no rule matches and it has no history."))
                continue

            update: dict = {"updated_at": _now()}
            if category and not txn.get("category"):
                if not is_valid_category(category):
                    results.append(self._outcome(
                        txn_id, "failed", f"Suggested category '{category}' is not valid."))
                    continue
                update["category"] = category
            if account_id and not txn.get("account_id"):
                update["account_id"] = account_id
            if len(update) == 1:                      # only updated_at
                results.append(self._outcome(
                    txn_id, "skipped", "Already coded — nothing was changed."))
                continue

            (db.table("bank_transactions").update(update)
             .eq("id", txn_id).eq("firm_id", firm_id).execute())
            results.append(self._outcome(
                txn_id, "applied", f"Coded from {source}.",
                category=update.get("category"), account_id=update.get("account_id")))

        self._log_batch(firm_id, "accept", results, actor_id)
        return self._summarise(results)

    @staticmethod
    def _suggestion_for(txn, rules_by_client, history, payee_service, match_rule):
        """A rule first (a human wrote it), then learned history (a human did it
        before). Neither is invented."""
        debit = int(txn.get("debit_paise") or 0)
        credit = int(txn.get("credit_paise") or 0)
        amount, is_debit = max(debit, credit), credit == 0
        hit = match_rule(txn.get("description"), amount, is_debit,
                         rules_by_client.get(txn.get("client_id"), []))
        if hit and (hit.category or hit.account_id):
            return hit.category, hit.account_id, f"rule “{hit.rule_name}”"
        learned = payee_service.suggest_for(txn, history.get(txn.get("client_id"), {}))
        if learned and (learned.category or learned.account_id):
            return learned.category, learned.account_id, "how this payee was coded before"
        return None, None, ""

    # ── 1.7 exclude / include ───────────────────────────────────────────────
    def set_excluded(self, db, firm_id: str, txn_ids: list[str], excluded: bool,
                     actor_id: Optional[str] = None) -> dict:
        ids = self._check_batch(txn_ids)
        found = self._fetch(db, firm_id, ids)
        results = []
        for txn_id in ids:
            txn = found.get(txn_id)
            if not txn:
                results.append(self._outcome(txn_id, "failed", "Not found for this firm."))
                continue
            if txn.get("posted_journal_id") or txn.get("match_status") == "posted":
                # Excluding a posted transaction would hide a line that is on
                # the books, which is the opposite of what exclusion means.
                results.append(self._outcome(
                    txn_id, "skipped", "Already posted — it cannot be excluded."))
                continue
            already = txn.get("match_status") == "ignored"
            if already == excluded:
                results.append(self._outcome(
                    txn_id, "skipped",
                    "Already excluded." if excluded else "Already included."))
                continue
            (db.table("bank_transactions")
             .update({"match_status": "ignored" if excluded else "unmatched",
                      "updated_at": _now()})
             .eq("id", txn_id).eq("firm_id", firm_id).execute())
            results.append(self._outcome(
                txn_id, "applied", "Excluded." if excluded else "Included again."))

        self._log_batch(firm_id, "exclude" if excluded else "include", results, actor_id)
        return self._summarise(results)

    # ── 1.8 attachments ─────────────────────────────────────────────────────
    def add_attachment(self, db, firm_id: str, txn_id: str, name: str, url: str,
                       actor_id: Optional[str] = None) -> dict:
        txn = self._one(db, firm_id, txn_id)
        try:
            updated = att.add(txn.get("attachments"), name, url)
        except att.AttachmentError as e:
            raise HTTPException(status_code=422, detail=str(e))
        return self._save_attachments(db, firm_id, txn_id, updated, actor_id)

    def remove_attachment(self, db, firm_id: str, txn_id: str, url: str,
                          actor_id: Optional[str] = None) -> dict:
        txn = self._one(db, firm_id, txn_id)
        try:
            updated = att.remove(txn.get("attachments"), url)
        except att.AttachmentError as e:
            raise HTTPException(status_code=422, detail=str(e))
        return self._save_attachments(db, firm_id, txn_id, updated, actor_id)

    def list_attachments(self, db, firm_id: str, txn_id: str) -> dict:
        txn = self._one(db, firm_id, txn_id)
        # Read through the validator: anything stored before a rule existed is
        # reported rather than handed to the UI as if it were fine.
        try:
            items = [a.to_dict() for a in att.parse_attachments(txn.get("attachments"))]
            invalid = None
        except att.AttachmentError as e:
            items, invalid = [], str(e)
        return {"transaction_id": txn_id, "attachments": items, "invalid": invalid}

    def _one(self, db, firm_id: str, txn_id: str) -> dict:
        rows = (db.table("bank_transactions").select("*")
                .eq("id", txn_id).eq("firm_id", firm_id).limit(1).execute().data) or []
        if not rows:
            raise HTTPException(status_code=404, detail="Bank transaction not found.")
        return rows[0]

    def _save_attachments(self, db, firm_id, txn_id, items, actor_id) -> dict:
        (db.table("bank_transactions")
         .update({"attachments": items, "updated_at": _now()})
         .eq("id", txn_id).eq("firm_id", firm_id).execute())
        try:
            from services.audit_service import log_event
            log_event(firm_id, "bank_transaction", txn_id, "update", actor_id=actor_id,
                      new_data={"attachment_count": len(items)},
                      metadata={"source": "bank_attachment"})
        except Exception:  # pragma: no cover - audit must never block
            pass
        return {"transaction_id": txn_id, "attachments": items, "invalid": None}

    # ── shared ──────────────────────────────────────────────────────────────
    @staticmethod
    def _outcome(txn_id, status, reason, **extra) -> dict:
        return {"transaction_id": txn_id, "status": status, "reason": reason, **extra}

    @staticmethod
    def _summarise(results: list[dict]) -> dict:
        counts = {"applied": 0, "skipped": 0, "failed": 0}
        for r in results:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        return {
            "results": results,
            "applied": counts["applied"],
            "skipped": counts["skipped"],
            "failed": counts["failed"],
            "total": len(results),
        }

    @staticmethod
    def _log_batch(firm_id, action, results, actor_id) -> None:
        try:
            from services.audit_service import log_event
            applied = [r["transaction_id"] for r in results if r["status"] == "applied"]
            if not applied:
                return
            log_event(firm_id, "bank_transaction", applied[0], "update", actor_id=actor_id,
                      new_data={"batch_action": action, "transaction_ids": applied,
                                "count": len(applied)},
                      metadata={"source": "bank_batch"})
        except Exception:  # pragma: no cover
            pass


bank_batch_service = BankBatchService()
