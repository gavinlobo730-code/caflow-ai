"""
Bank reconciliation service (Banking B.4) — session → tie-out → report.

Reconciles a bank account's POSTED ledger against its statement for a period:
open a session, manually reconcile/unreconcile posted transactions (never
automatic — explicit human confirmation), and complete it only when the balance
ties out (Opening + Deposits − Withdrawals ± Adjustments = Closing). A completed
session is immutable. All money is integer paise; firm/client isolation is
enforced on every query.
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from domain.banking import reconciliation as recon
from services.timeline_service import timeline_service

_logger = logging.getLogger("caflow.bank_reconciliation")

_MUTABLE = ("open", "in_progress")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _d(value) -> str:
    """Normalise a date/timestamp to YYYY-MM-DD for range comparison."""
    return str(value)[:10]


class BankReconciliationService:

    # ── session fetch / scoping ────────────────────────────────────────────────
    def _get_session(self, db, firm_id: str, recon_id: str) -> dict:
        res = (db.table("bank_reconciliations").select("*")
               .eq("id", recon_id).eq("firm_id", firm_id).single().execute())
        if not res.data:
            raise HTTPException(status_code=404, detail="Reconciliation not found.")
        return res.data

    def _require_mutable(self, session: dict) -> None:
        if session.get("status") == "completed":
            raise HTTPException(status_code=409,
                                detail="Reconciliation is completed and can no longer be edited.")

    def _account_statement_ids(self, db, firm_id: str, bank_account_id: str) -> list[str]:
        res = (db.table("bank_statements").select("id")
               .eq("firm_id", firm_id).eq("bank_account_id", bank_account_id).execute())
        return [r["id"] for r in (res.data or [])]

    def _posted_account_txns(self, db, firm_id: str, bank_account_id: str) -> list[dict]:
        """All POSTED transactions belonging to the account's statements."""
        stmt_ids = self._account_statement_ids(db, firm_id, bank_account_id)
        if not stmt_ids:
            return []
        rows = (db.table("bank_transactions").select("*")
                .eq("firm_id", firm_id).in_("statement_id", stmt_ids).execute().data or [])
        return [t for t in rows if t.get("posted_journal_id")]

    def _validate_bank_account(self, db, firm_id: str, client_id: str, bank_account_id: str) -> dict:
        res = (db.table("bank_accounts").select("*")
               .eq("id", bank_account_id).eq("firm_id", firm_id).limit(1).execute())
        ba = (res.data or [None])[0]
        if not ba:
            raise HTTPException(status_code=422, detail="Bank account not found for this firm.")
        if ba.get("client_id") and client_id and ba["client_id"] != client_id:
            raise HTTPException(status_code=422, detail="Bank account does not belong to this client.")
        return ba

    # ── classification (reconciled / unreconciled / exceptions) ────────────────
    def _classify(self, session: dict, txns: list[dict]) -> dict:
        recon_id = session["id"]
        start, end = _d(session["period_start"]), _d(session["period_end"])

        def in_range(t) -> bool:
            return start <= _d(t["transaction_date"]) <= end

        reconciled = [t for t in txns if t.get("reconciliation_id") == recon_id]
        unreconciled = [t for t in txns if t.get("reconciliation_id") is None and in_range(t)]
        # Posted txns in this period already claimed by ANOTHER session — a conflict
        # that needs human attention (cannot be reconciled here).
        exceptions = [
            {**t, "exception_reason": "Reconciled in another session"}
            for t in txns
            if t.get("reconciliation_id") not in (None, recon_id) and in_range(t)
        ]
        return {"reconciled": reconciled, "unreconciled": unreconciled, "exceptions": exceptions}

    def _summary(self, session: dict, reconciled: list[dict]) -> dict:
        deposits, withdrawals = recon.split_amounts(reconciled)
        return recon.tie_out(
            opening_balance_paise=int(session.get("opening_balance_paise") or 0),
            closing_balance_paise=int(session.get("closing_balance_paise") or 0),
            deposits_paise=deposits,
            withdrawals_paise=withdrawals,
            adjustments_paise=int(session.get("adjustments_paise") or 0),
        )

    @staticmethod
    def _session_view(session: dict) -> dict:
        """Expose period_start/period_end under the B.4 statement_* field names."""
        return {
            "id": session["id"],
            "firm_id": session.get("firm_id"),
            "client_id": session.get("client_id"),
            "bank_account_id": session.get("bank_account_id"),
            "account_no": session.get("account_no"),
            "statement_start_date": _d(session["period_start"]),
            "statement_end_date": _d(session["period_end"]),
            "opening_balance_paise": int(session.get("opening_balance_paise") or 0),
            "closing_balance_paise": int(session.get("closing_balance_paise") or 0),
            "adjustments_paise": int(session.get("adjustments_paise") or 0),
            "status": session.get("status"),
            "completed_at": session.get("completed_at"),
            "completed_by": session.get("completed_by"),
            "created_at": session.get("created_at"),
            # Reopen provenance (migration 253). A period that has been reopened
            # is a fact about the books, so it travels with the session rather
            # than living only in the audit log.
            "reopen_count": int(session.get("reopen_count") or 0),
            "reopened_at": session.get("reopened_at"),
            "reopened_by": session.get("reopened_by"),
            "reopen_reason": session.get("reopen_reason"),
        }

    # ── opening balance: suggestion + mismatch detection ───────────────────────
    def opening_suggestion(self, db, firm_id, client_id, bank_account_id) -> dict:
        """Where a new reconciliation for this account should start, and whether
        the books still agree with it.

        The opening balance used to be typed in by hand every time, with nothing
        to check it against. A typo produced a reconciliation that tied out
        perfectly to the wrong number — the arithmetic is exact either way, so
        nothing downstream could notice. The figure is not a matter of opinion:
        it is the closing balance the last completed reconciliation tied out to,
        and it is already stored in that session's frozen snapshot.

        Returns the suggestion, its provenance, and the
        `domain.banking.reconciliation.opening_balance_check` comparison against
        the books' own record of everything reconciled so far.
        """
        ba = self._validate_bank_account(db, firm_id, client_id, bank_account_id)
        account_opening = int(ba.get("opening_balance_paise") or 0)

        sessions = (db.table("bank_reconciliations").select("*")
                    .eq("firm_id", firm_id).eq("bank_account_id", bank_account_id)
                    .eq("status", "completed").execute().data or [])
        # Chronological, so "the last one" is unambiguous and the accumulation
        # below runs in period order.
        sessions.sort(key=lambda s: (_d(s.get("period_end")), str(s.get("completed_at") or "")))

        txns = self._posted_account_txns(db, firm_id, bank_account_id)
        by_session: dict = {}
        for t in txns:
            rid = t.get("reconciliation_id")
            if rid:
                by_session.setdefault(rid, []).append(t)

        movements = []
        for s in sessions:
            deposits, withdrawals = recon.split_amounts(by_session.get(s["id"], []))
            movements.append({
                "deposits_paise": deposits,
                "withdrawals_paise": withdrawals,
                "adjustments_paise": int(s.get("adjustments_paise") or 0),
            })

        book_balance = recon.reconciled_book_balance(
            account_opening_paise=account_opening, completed_sessions=movements)

        previous = sessions[-1] if sessions else None
        if previous is not None:
            # Prefer the frozen snapshot — it is the figure the session actually
            # tied out to, and cannot drift if the row is later touched.
            snap = self._frozen_snapshot(previous) or {}
            snap_summary = (snap.get("summary") or {}) if isinstance(snap, dict) else {}
            suggested = int(
                snap_summary.get("statement_closing_balance_paise")
                if snap_summary.get("statement_closing_balance_paise") is not None
                else (previous.get("closing_balance_paise") or 0)
            )
            source = "previous_reconciliation"
            prev_view = {
                "reconciliation_id": previous["id"],
                "period_end": _d(previous.get("period_end")),
                "closing_balance_paise": suggested,
                "completed_at": previous.get("completed_at"),
            }
        else:
            suggested = account_opening
            source = "bank_account_opening"
            prev_view = None

        check = recon.opening_balance_check(
            suggested_opening_paise=suggested,
            reconciled_book_balance_paise=book_balance,
        )
        return {
            "bank_account_id": bank_account_id,
            "source": source,
            "previous_reconciliation": prev_view,
            "completed_count": len(sessions),
            **check,
        }

    # ── B.4.1 session lifecycle ─────────────────────────────────────────────────
    def create_session(self, db, firm_id, client_id, bank_account_id,
                        statement_start_date, statement_end_date,
                        opening_balance_paise=None, closing_balance_paise=0, actor_id=None) -> dict:
        ba = self._validate_bank_account(db, firm_id, client_id, bank_account_id)
        # Opening balance defaults to where the last completed reconciliation
        # left off rather than to zero. An omitted opening used to silently mean
        # "zero", which is right only for a brand-new account.
        suggestion = self.opening_suggestion(db, firm_id, client_id, bank_account_id)
        if opening_balance_paise is None:
            opening_balance_paise = suggestion["suggested_opening_paise"]
        row = (db.table("bank_reconciliations").insert({
            "firm_id": firm_id, "client_id": client_id, "bank_account_id": bank_account_id,
            "account_no": ba.get("account_no"),
            "period_start": statement_start_date, "period_end": statement_end_date,
            "opening_balance_paise": int(opening_balance_paise),
            "closing_balance_paise": int(closing_balance_paise),
            "status": "open", "created_by": actor_id, "updated_at": _now(),
        }).execute().data or [{}])[0]
        try:
            timeline_service.log(client_id, "accounting", "Reconciliation Opened",
                                 f"{ba.get('bank_name', 'Bank')} {statement_start_date} → {statement_end_date}",
                                 "info", firm_id=firm_id, entity_type="bank_reconciliation",
                                 entity_id=row.get("id"), actor_id=actor_id)
        except Exception:  # pragma: no cover - timeline must never block
            pass
        view = self._session_view(row)
        # Carried on the create response so the CA is told at the moment they
        # open a period — not after they have ticked fifty lines against a
        # foundation that has moved. Warning only; opening is never blocked.
        view["opening_balance_check"] = {
            **suggestion,
            "typed_opening_paise": int(opening_balance_paise),
            "used_suggestion": int(opening_balance_paise) == suggestion["suggested_opening_paise"],
        }
        return view

    def list_sessions(self, db, firm_id, client_id: Optional[str],
                      bank_account_id: Optional[str] = None) -> list[dict]:
        q = db.table("bank_reconciliations").select("*").eq("firm_id", firm_id)
        if client_id:
            q = q.eq("client_id", client_id)
        if bank_account_id:
            q = q.eq("bank_account_id", bank_account_id)
        rows = q.order("period_end", desc=True).execute().data or []
        return [self._session_view(r) for r in rows]

    def _frozen_snapshot(self, session: dict) -> Optional[dict]:
        """The frozen report stored at completion (F2). None for mutable sessions."""
        if session.get("status") != "completed":
            return None
        snap = session.get("snapshot")
        if snap is None:
            return None
        if isinstance(snap, str):  # jsonb may arrive as text from some drivers
            import json
            snap = json.loads(snap)
        return snap

    def get_session(self, db, firm_id, recon_id) -> dict:
        session = self._get_session(db, firm_id, recon_id)
        snap = self._frozen_snapshot(session)
        if snap is not None:  # completed → serve frozen summary/counts
            return {**snap["reconciliation"], "summary": snap["summary"], "counts": snap["counts"]}
        txns = self._posted_account_txns(db, firm_id, session["bank_account_id"])
        buckets = self._classify(session, txns)
        view = self._session_view(session)
        view["summary"] = self._summary(session, buckets["reconciled"])
        view["counts"] = {
            "reconciled": len(buckets["reconciled"]),
            "unreconciled": len(buckets["unreconciled"]),
            "exceptions": len(buckets["exceptions"]),
        }
        return view

    def update_session(self, db, firm_id, recon_id, fields: dict, actor_id=None) -> dict:
        session = self._get_session(db, firm_id, recon_id)
        self._require_mutable(session)
        update = {k: int(v) for k, v in fields.items()
                  if k in ("opening_balance_paise", "closing_balance_paise", "adjustments_paise")
                  and v is not None}
        if not update:
            return self.get_session(db, firm_id, recon_id)
        update["updated_at"] = _now()
        db.table("bank_reconciliations").update(update).eq("id", recon_id).eq("firm_id", firm_id).execute()
        return self.get_session(db, firm_id, recon_id)

    # ── B.4.2 manual reconcile / unreconcile (human confirmation only) ──────────
    def _index_account_txns(self, db, firm_id, session) -> dict:
        return {t["id"]: t for t in self._posted_account_txns(db, firm_id, session["bank_account_id"])}

    def reconcile(self, db, firm_id, recon_id, txn_ids: list[str], actor_id=None) -> dict:
        session = self._get_session(db, firm_id, recon_id)
        self._require_mutable(session)
        by_id = self._index_account_txns(db, firm_id, session)
        start, end = _d(session["period_start"]), _d(session["period_end"])
        for tid in txn_ids:
            t = by_id.get(tid)
            if not t:
                raise HTTPException(status_code=422,
                                    detail=f"Transaction {tid} is not a posted transaction for this account.")
            if not (start <= _d(t["transaction_date"]) <= end):
                raise HTTPException(status_code=422,
                                    detail=f"Transaction {tid} falls outside the statement period.")
            existing = t.get("reconciliation_id")
            if existing and existing != recon_id:
                raise HTTPException(status_code=409,
                                    detail=f"Transaction {tid} is already reconciled in another session.")
        for tid in txn_ids:
            t = by_id[tid]
            existing = t.get("reconciliation_id")
            # Concurrency guard: claim exclusive reconciliation rights on this
            # transaction via a CAS-guarded update. The pre-check above (raise
            # 409 if `existing` belongs to another session) reads a snapshot
            # that can go stale before this write lands -- two overlapping
            # sessions, or two near-simultaneous reconcile calls on the same
            # session, could both pass the read-check and the transaction would
            # silently end up claimed by whichever write lands last, with no
            # error surfaced to the loser. Guarding the write on the exact
            # reconciliation_id this call read closes that gap.
            q = db.table("bank_transactions").update({
                "reconciliation_id": recon_id, "reconciled": True, "reconciled_at": _now(),
                "reconciled_journal_id": t.get("posted_journal_id"), "updated_at": _now(),
            }).eq("id", tid).eq("firm_id", firm_id)
            q = q.eq("reconciliation_id", existing) if existing else q.is_("reconciliation_id", "null")
            claim = q.execute()
            if not claim.data:
                raise HTTPException(status_code=409,
                                    detail=f"Transaction {tid} was claimed by another reconciliation session.")
        self._advance_to_in_progress(db, firm_id, session)
        self._log(session, actor_id, "Transactions Reconciled", f"{len(txn_ids)} item(s) reconciled")
        return self.get_session(db, firm_id, recon_id)

    def unreconcile(self, db, firm_id, recon_id, txn_ids: list[str], actor_id=None) -> dict:
        session = self._get_session(db, firm_id, recon_id)
        self._require_mutable(session)
        by_id = self._index_account_txns(db, firm_id, session)
        for tid in txn_ids:
            t = by_id.get(tid)
            if not t or t.get("reconciliation_id") != recon_id:
                raise HTTPException(status_code=422,
                                    detail=f"Transaction {tid} is not reconciled in this session.")
        for tid in txn_ids:
            # Same CAS-guard rationale as reconcile(): guard the write on the
            # exact reconciliation_id this call read, so a concurrent request
            # that already moved this transaction (re-reconciled it elsewhere,
            # or unreconciled it first) can't be silently overwritten.
            claim = db.table("bank_transactions").update({
                "reconciliation_id": None, "reconciled": False, "reconciled_at": None,
                "reconciled_journal_id": None, "updated_at": _now(),
            }).eq("id", tid).eq("firm_id", firm_id).eq("reconciliation_id", recon_id).execute()
            if not claim.data:
                raise HTTPException(status_code=409,
                                    detail=f"Transaction {tid} was already unreconciled by a concurrent request.")
        self._log(session, actor_id, "Transactions Unreconciled", f"{len(txn_ids)} item(s) unreconciled")
        return self.get_session(db, firm_id, recon_id)

    def _advance_to_in_progress(self, db, firm_id, session) -> None:
        if session.get("status") == "open":
            db.table("bank_reconciliations").update({"status": "in_progress", "updated_at": _now()}) \
                .eq("id", session["id"]).eq("firm_id", firm_id).execute()

    # ── B.4.3 completion (tie-out enforced; immutable thereafter) ───────────────
    def complete(self, db, firm_id, recon_id, actor_id=None) -> dict:
        session = self._get_session(db, firm_id, recon_id)
        if session.get("status") == "completed":
            raise HTTPException(status_code=409, detail="Reconciliation is already completed.")
        txns = self._posted_account_txns(db, firm_id, session["bank_account_id"])
        buckets = self._classify(session, txns)
        summary = self._summary(session, buckets["reconciled"])
        # F1 Condition 2: every in-period statement line must be reviewed. A clean
        # arithmetic tie-out is NOT sufficient — unreconciled items (even ones that
        # net to zero) mean the statement was not fully reconciled.
        unreconciled = len(buckets["unreconciled"])
        if unreconciled:
            raise HTTPException(
                status_code=422,
                detail=(f"Cannot complete — {unreconciled} transaction(s) in this period are "
                        f"still unreconciled. Every statement line must be reconciled before "
                        f"completing, even if the balance already ties out."))
        # F1 Condition 1: arithmetic tie-out.
        if not summary["reconciles"]:
            raise HTTPException(
                status_code=422,
                detail=(f"Cannot complete — statement does not tie out. Difference "
                        f"₹{summary['difference_paise'] / 100:.2f}. Reconcile the remaining "
                        f"items or record an adjustment."))
        # F2: freeze the report at completion so the historical reconciliation can
        # never silently change if transactions are later modified / reversed / removed.
        now = _now()
        snapshot = self._compute_report(session, txns)
        snapshot["reconciliation"].update({"status": "completed", "completed_at": now, "completed_by": actor_id})
        db.table("bank_reconciliations").update({
            "status": "completed", "completed_at": now, "completed_by": actor_id,
            "snapshot": snapshot, "updated_at": now,
        }).eq("id", recon_id).eq("firm_id", firm_id).execute()
        self._log(session, actor_id, "Reconciliation Completed",
                  f"Tied out at ₹{summary['statement_closing_balance_paise'] / 100:.2f}", severity="success")
        try:
            from services.audit_service import log_event
            log_event(firm_id, "bank_reconciliation", recon_id, "status_change", actor_id=actor_id,
                      new_data={"status": "completed", **summary},
                      metadata={"source": "bank_reconciliation"})
        except Exception:  # pragma: no cover
            pass
        return self.get_session(db, firm_id, recon_id)

    # ── reopen a completed reconciliation (Tier 2.5) ────────────────────────────
    _MIN_REOPEN_REASON = 10

    def reopen(self, db, firm_id, recon_id, reason: str, actor_id=None) -> dict:
        """Undo a completion so the period can be corrected.

        WHY THIS IS ALLOWED AT ALL
            A completed reconciliation is immutable, and that is right — it is a
            period a CA has certified. But immutability with no escape hatch is
            its own failure mode: a period completed against a mistake (a
            transaction reconciled into the wrong month, a closing balance typed
            off the wrong statement page) was previously permanent, and the only
            remedy was to leave the books wrong.

            The discipline is not in forbidding the action. It is in making it
            visible and expensive: Partner-only (the router gates on
            rbac("accounting", "approve"), the same gate as posting a journal),
            a substantive reason required, audit-logged and on the client
            timeline, and the certified snapshot preserved rather than
            overwritten.

        WHAT IS AND IS NOT TOUCHED
            The session returns to 'in_progress' — work has been done, so 'open'
            would misdescribe it. Reconciled transactions KEEP their
            reconciliation_id: reopening is not un-reconciling, it restores the
            ability to change things. The CA then unreconciles whatever was
            wrong and completes again, which re-runs both completion guards
            (ties out AND every in-period line reviewed) from scratch.

            `snapshot` is pushed onto `reopen_history` first, so the report the
            CA signed off remains retrievable even after the period is redone.
            _require_mutable is NOT relaxed — every other edit path still
            refuses a completed session.
        """
        session = self._get_session(db, firm_id, recon_id)
        if session.get("status") != "completed":
            raise HTTPException(
                status_code=409,
                detail="Only a completed reconciliation can be reopened.")

        clean = (reason or "").strip()
        if len(clean) < self._MIN_REOPEN_REASON:
            raise HTTPException(
                status_code=422,
                detail=(f"A reason of at least {self._MIN_REOPEN_REASON} characters is "
                        "required to reopen a completed reconciliation."))

        now = _now()
        history = session.get("reopen_history") or []
        if isinstance(history, str):  # jsonb may arrive as text from some drivers
            import json
            try:
                history = json.loads(history)
            except Exception:
                history = []
        history = list(history) + [{
            "reopened_at": now,
            "reopened_by": actor_id,
            "reason": clean,
            "completed_at": session.get("completed_at"),
            "completed_by": session.get("completed_by"),
            # The certification as it stood. Preserved here because completing
            # again overwrites `snapshot`.
            "snapshot": session.get("snapshot"),
        }]

        db.table("bank_reconciliations").update({
            "status": "in_progress",
            "completed_at": None, "completed_by": None,
            "reopened_at": now, "reopened_by": actor_id, "reopen_reason": clean,
            "reopen_count": len(history),
            "reopen_history": history,
            "updated_at": now,
        }).eq("id", recon_id).eq("firm_id", firm_id).execute()

        self._log(session, actor_id, "Reconciliation Reopened", clean, severity="warning")
        try:
            from services.audit_service import log_event
            log_event(firm_id, "bank_reconciliation", recon_id, "status_change", actor_id=actor_id,
                      old_data={"status": "completed", "completed_at": session.get("completed_at")},
                      new_data={"status": "in_progress", "reason": clean,
                                "reopen_count": len(history)},
                      metadata={"source": "bank_reconciliation_reopen"})
        except Exception:  # pragma: no cover
            pass
        return self.get_session(db, firm_id, recon_id)

    # ── B.4.4 report + CSV ──────────────────────────────────────────────────────
    def _compute_report(self, session: dict, txns: list[dict]) -> dict:
        """Build the full report payload from live transaction data."""
        buckets = self._classify(session, txns)
        summary = self._summary(session, buckets["reconciled"])

        def line(t: dict) -> dict:
            return {
                "id": t["id"], "transaction_date": _d(t["transaction_date"]),
                "description": t.get("description", ""), "reference_no": t.get("reference_no"),
                "debit_paise": int(t.get("debit_paise") or 0),
                "credit_paise": int(t.get("credit_paise") or 0),
                "posted_journal_id": t.get("posted_journal_id"),
                "exception_reason": t.get("exception_reason"),
            }
        return {
            "reconciliation": self._session_view(session),
            "summary": summary,
            "ties_out": summary["reconciles"],
            "reconciled": [line(t) for t in buckets["reconciled"]],
            "unreconciled": [line(t) for t in buckets["unreconciled"]],
            "exceptions": [line(t) for t in buckets["exceptions"]],
            "reconciled_transaction_ids": [t["id"] for t in buckets["reconciled"]],
            "counts": {
                "reconciled": len(buckets["reconciled"]),
                "unreconciled": len(buckets["unreconciled"]),
                "exceptions": len(buckets["exceptions"]),
            },
        }

    def report(self, db, firm_id, recon_id) -> dict:
        """Completed sessions serve a frozen snapshot (F2); mutable sessions compute
        live. No recomputation ever changes a completed reconciliation."""
        session = self._get_session(db, firm_id, recon_id)
        snap = self._frozen_snapshot(session)
        if snap is not None:
            return snap
        txns = self._posted_account_txns(db, firm_id, session["bank_account_id"])
        return self._compute_report(session, txns)

    def report_csv(self, db, firm_id, recon_id) -> str:
        rep = self.report(db, firm_id, recon_id)
        s, v = rep["summary"], rep["reconciliation"]
        buf = io.StringIO()
        w = csv.writer(buf)
        rupees = lambda p: f"{p / 100:.2f}"  # noqa: E731 - display only; storage is paise
        w.writerow(["Bank Reconciliation Report"])
        w.writerow(["Bank account", v["bank_account_id"], "Account no", v.get("account_no") or ""])
        w.writerow(["Period", v["statement_start_date"], "to", v["statement_end_date"]])
        w.writerow(["Status", v["status"]])
        w.writerow([])
        w.writerow(["Opening balance", rupees(s["opening_balance_paise"])])
        w.writerow(["Add: Deposits (reconciled)", rupees(s["deposits_paise"])])
        w.writerow(["Less: Withdrawals (reconciled)", rupees(s["withdrawals_paise"])])
        w.writerow(["Adjustments", rupees(s["adjustments_paise"])])
        w.writerow(["= Reconciled book balance", rupees(s["reconciled_book_balance_paise"])])
        w.writerow(["Statement closing balance", rupees(s["statement_closing_balance_paise"])])
        w.writerow(["Difference", rupees(s["difference_paise"])])
        w.writerow(["Ties out", "YES" if rep["ties_out"] else "NO"])
        w.writerow([])
        w.writerow(["Section", "Date", "Description", "Reference", "Debit", "Credit", "Journal", "Note"])
        for sect in ("reconciled", "unreconciled", "exceptions"):
            for t in rep[sect]:
                w.writerow([sect, t["transaction_date"], t["description"], t.get("reference_no") or "",
                            rupees(t["debit_paise"]), rupees(t["credit_paise"]),
                            t.get("posted_journal_id") or "", t.get("exception_reason") or ""])
        return buf.getvalue()

    # ── helpers ─────────────────────────────────────────────────────────────────
    def _log(self, session, actor_id, title, desc, severity="info") -> None:
        try:
            timeline_service.log(session.get("client_id"), "accounting", title, desc, severity,
                                 firm_id=session.get("firm_id"), entity_type="bank_reconciliation",
                                 entity_id=session["id"], actor_id=actor_id)
        except Exception:  # pragma: no cover
            pass


bank_reconciliation_service = BankReconciliationService()
