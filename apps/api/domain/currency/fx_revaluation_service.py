"""
FXRevaluationService — period-end UNREALIZED FX revaluation (Multi-Currency Phase 4).

Ind AS 21 / AS 11: monetary items in a foreign currency are retranslated at the
closing rate at period end; the difference is an unrealized exchange gain/loss.
Here it is booked as a GL overlay on the AR/AP control accounts against
Unrealized FX Gain/Loss, then AUTO-REVERSED on day 1 of the next period — so the
sub-ledger and individual documents keep their frozen booking rates (historical
data is never modified) and realized FX is recognised only on actual settlement.

Design guarantees (Task 5/6):
  • Idempotent / re-runnable / self-healing — a run posts only the DELTA needed to
    reach the new target (target − cumulative already posted for that key). Same
    rate ⇒ delta 0 ⇒ nothing posted. Rate changed before close ⇒ the delta corrects
    it. Everything is append-only through the posting kernel; nothing is edited.
  • Validations — missing closing rate, unsupported currency, and closed/locked
    period are rejected with clear messages.

NOT here (Phase 5): foreign TB/BS/P&L, presentation currency, translation reserve.
Foreign bank-balance revaluation is structurally supported but has no data source
until foreign-currency bank accounts exist (a deferred master), so it is a no-op.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi import HTTPException

from domain.currency.conversion import to_base_minor
from domain.currency import currency_service
from services.period_validation_service import period_validation_service
from services.phase2_journal_service import phase2_journal_service as K

_BASE = "INR"


def _next_day(period_end: str) -> str:
    return (date.fromisoformat(str(period_end)[:10]) + timedelta(days=1)).isoformat()


class FXRevaluationService:
    def _open_receivables(self, db, firm_id, client_id, period_end):
        rows = (db.table("client_sales_invoices")
                .select("txn_currency, exchange_rate, total_paise, paid_paise, credited_paise, txn_total, paid_txn, status, invoice_date")
                .eq("firm_id", firm_id).eq("client_id", client_id).execute().data) or []
        out = []
        for r in rows:
            if (r.get("txn_currency") or "INR").upper() == _BASE:
                continue
            if (r.get("status") or "") in ("draft", "cancelled", "paid"):
                continue
            if str(r.get("invoice_date") or "")[:10] > str(period_end)[:10]:
                continue
            base_out = int(r["total_paise"]) - int(r.get("paid_paise") or 0) - int(r.get("credited_paise") or 0)
            foreign_out = int(r.get("txn_total") or 0) - int(r.get("paid_txn") or 0)
            if foreign_out > 0:
                out.append(((r.get("txn_currency") or "").upper(), foreign_out, base_out))
        return out

    def _open_payables(self, db, firm_id, client_id, period_end):
        rows = (db.table("purchase_bills")
                .select("txn_currency, exchange_rate, net_payable_paise, paid_paise, debited_paise, txn_net_payable, paid_txn, status, bill_date")
                .eq("firm_id", firm_id).eq("client_id", client_id).execute().data) or []
        out = []
        for r in rows:
            if (r.get("txn_currency") or "INR").upper() == _BASE:
                continue
            if (r.get("status") or "") in ("draft", "cancelled", "paid"):
                continue
            if str(r.get("bill_date") or "")[:10] > str(period_end)[:10]:
                continue
            base_out = int(r.get("net_payable_paise") or 0) - int(r.get("paid_paise") or 0) - int(r.get("debited_paise") or 0)
            foreign_out = int(r.get("txn_net_payable") or 0) - int(r.get("paid_txn") or 0)
            if foreign_out > 0:
                out.append(((r.get("txn_currency") or "").upper(), foreign_out, base_out))
        return out

    def _prior_runs(self, db, firm_id, client_id, period_end, currency, item_type):
        """Prior revaluation runs for this key → (cumulative_delta, run_count). The
        cumulative is what has already been posted; the next run posts target − it."""
        rows = (db.table("fx_revaluations").select("delta_paise")
                .eq("firm_id", firm_id).eq("client_id", client_id).eq("period_end", period_end)
                .eq("currency", currency).eq("item_type", item_type).execute().data) or []
        return sum(int(r.get("delta_paise") or 0) for r in rows), len(rows)

    def revalue(self, db, firm_id: str, client_id: str, period_end: str,
                closing_rates: dict, actor: dict | None = None) -> dict:
        """Revalue open foreign AR/AP at `period_end` using `closing_rates`
        ({currency: rate}). Idempotent/self-healing. Returns a summary."""
        actor = actor or {}
        period_end = str(period_end)[:10]
        reversal_date = _next_day(period_end)
        # Validation: the period and its reversal day must not be in a locked FY.
        period_validation_service.validate_posting_date(firm_id or "", period_end)
        period_validation_service.validate_posting_date(firm_id or "", reversal_date)

        # Aggregate open foreign exposure per (currency, item_type).
        exposure: dict = {}   # (currency, item_type) -> [foreign_out, carrying_base]
        for ccy, f, b in self._open_receivables(db, firm_id, client_id, period_end):
            k = (ccy, "receivable"); e = exposure.setdefault(k, [0, 0]); e[0] += f; e[1] += b
        for ccy, f, b in self._open_payables(db, firm_id, client_id, period_end):
            k = (ccy, "payable"); e = exposure.setdefault(k, [0, 0]); e[0] += f; e[1] += b

        # Validate closing rates + currencies up front (Task 6).
        for (ccy, _item) in exposure:
            cur = currency_service.get_currency(db, ccy)
            if not cur:
                raise HTTPException(status_code=422, detail=f"Unsupported currency in revaluation: {ccy}.")
            if ccy not in closing_rates and str(ccy) not in {str(x) for x in closing_rates}:
                raise HTTPException(status_code=422, detail=f"Missing closing rate for {ccy} at {period_end}.")
            rate = Decimal(str(closing_rates[ccy]))
            if rate <= 0:
                raise HTTPException(status_code=422, detail=f"Closing rate for {ccy} must be positive.")

        results = []
        for (ccy, item_type), (foreign_out, carrying_base) in sorted(exposure.items()):
            minor = int(currency_service.get_currency(db, ccy).get("minor_unit", 2))
            rc = Decimal(str(closing_rates[ccy]))
            revalued = to_base_minor(foreign_out, rc, minor)
            # For BOTH AR and AP the target adjustment to the carrying base is the same
            # signed quantity (revalued − carrying); the journal direction differs.
            target = revalued - carrying_base
            prior, run_count = self._prior_runs(db, firm_id, client_id, period_end, ccy, item_type)
            delta = target - prior
            if delta == 0:
                results.append({"currency": ccy, "item_type": item_type, "target_paise": target,
                                "delta_paise": 0, "journal_entry_id": None})
                continue

            entry_id = self._post_reval(db, firm_id, client_id, period_end, ccy, item_type, delta, actor, run_count + 1)
            reversal_id = K.reverse_entry(
                db, firm_id=firm_id, entry_id=entry_id, reversal_date=reversal_date,
                narration=f"Auto-reversal of {ccy} {item_type} revaluation {period_end}",
                created_by=actor.get("id"))

            db.table("fx_revaluations").insert({
                "firm_id": firm_id, "client_id": client_id, "period_end": period_end,
                "currency": ccy, "item_type": item_type, "closing_rate": str(rc),
                "target_adjustment_paise": target, "delta_paise": delta,
                "journal_entry_id": entry_id, "reversal_entry_id": reversal_id,
                "run_by": actor.get("id"),
            }).execute()
            db.table("fx_adjustments").insert({
                "firm_id": firm_id, "client_id": client_id, "kind": "unrealized",
                "document_type": "revaluation", "document_id": entry_id, "currency": ccy,
                "closing_rate": str(rc), "base_delta_paise": delta,
                "journal_entry_id": entry_id, "rate_source": "closing",
                "created_by": actor.get("id"),
            }).execute()
            results.append({"currency": ccy, "item_type": item_type, "target_paise": target,
                            "delta_paise": delta, "journal_entry_id": entry_id,
                            "reversal_entry_id": reversal_id})
        return {"period_end": period_end, "reversal_date": reversal_date, "adjustments": results}

    def _post_reval(self, db, firm_id, client_id, period_end, ccy, item_type, delta, actor, run_seq) -> str:
        """Post the delta revaluation journal (base INR) through the kernel.

        Receivable: a positive delta means AR is worth more → Dr AR / Cr Unrealized
        FX (gain). Payable: a positive delta means we owe more → Cr AP / Dr
        Unrealized FX (loss). Negative deltas swap the sides."""
        fx_id = K._find_account(db, firm_id, client_id, "%Foreign Exchange%", system_key="fx_unrealized")
        if item_type == "receivable":
            ctrl = K._find_account(db, firm_id, client_id, "%Trade Receivable%", system_key="ar")
            if delta > 0:      # AR up (Dr), unrealized gain (Cr)
                lines = [{"account_id": ctrl, "debit_paise": delta, "credit_paise": 0, "narration": "AR revaluation"},
                         {"account_id": fx_id, "debit_paise": 0, "credit_paise": delta, "narration": "Unrealized FX gain"}]
            else:              # AR down (Cr), unrealized loss (Dr)
                d = -delta
                lines = [{"account_id": fx_id, "debit_paise": d, "credit_paise": 0, "narration": "Unrealized FX loss"},
                         {"account_id": ctrl, "debit_paise": 0, "credit_paise": d, "narration": "AR revaluation"}]
        else:  # payable
            ctrl = K._find_account(db, firm_id, client_id, "%Trade Payable%", system_key="ap")
            if delta > 0:      # AP up (Cr), unrealized loss (Dr)
                lines = [{"account_id": fx_id, "debit_paise": delta, "credit_paise": 0, "narration": "Unrealized FX loss"},
                         {"account_id": ctrl, "debit_paise": 0, "credit_paise": delta, "narration": "AP revaluation"}]
            else:              # AP down (Dr), unrealized gain (Cr)
                d = -delta
                lines = [{"account_id": ctrl, "debit_paise": d, "credit_paise": 0, "narration": "AP revaluation"},
                         {"account_id": fx_id, "debit_paise": 0, "credit_paise": d, "narration": "Unrealized FX gain"}]
        # run_seq makes each self-healing delta a distinct reference so the kernel's
        # idempotency dedup never collapses a genuine delta onto a prior run.
        ref = f"FXREVAL-{period_end}-{ccy}-{item_type[:3].upper()}-{run_seq}"
        return K._create_journal(
            db=db, firm_id=firm_id, client_id=client_id, entry_date=period_end,
            reference_no=ref, narration=f"Unrealized FX revaluation — {ccy} {item_type} @ {period_end}",
            entry_type="Journal", lines=lines, created_by=actor.get("id"))


fx_revaluation_service = FXRevaluationService()
