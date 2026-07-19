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


def _paginate_all(make_query, key: str = "id", page: int = 1000) -> list:
    """Fetch EVERY row of a Supabase query via keyset paging on `key`.

    An un-paged .execute() is silently capped at PostgREST's ~1000-row limit, so for
    a large ledger this would truncate the journal read and understate/mis-target the
    revaluation delta (no error raised). `make_query` returns a fresh query builder each
    call. Test doubles that don't implement order/limit/gt just return their whole (small)
    fixture from a single execute(), which is already correct."""
    first = make_query()
    if not (hasattr(first, "gt") and hasattr(first, "order") and hasattr(first, "limit")):
        return first.execute().data or []
    out: list = []
    cursor = None
    while True:
        q = make_query()
        if cursor is not None:
            q = q.gt(key, cursor)
        rows = q.order(key).limit(page).execute().data or []
        out.extend(rows)
        if len(rows) < page:
            break
        cursor = rows[-1][key]
    return out


def _next_day(period_end: str) -> str:
    return (date.fromisoformat(str(period_end)[:10]) + timedelta(days=1)).isoformat()


class FXRevaluationService:
    def _open_receivables(self, db, firm_id, client_id, period_end):
        rows = _paginate_all(lambda: db.table("client_sales_invoices")
                             .select("id, txn_currency, exchange_rate, total_paise, paid_paise, credited_paise, txn_total, paid_txn, status, invoice_date")
                             .eq("firm_id", firm_id).eq("client_id", client_id))
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
        rows = _paginate_all(lambda: db.table("purchase_bills")
                             .select("id, txn_currency, exchange_rate, net_payable_paise, paid_paise, debited_paise, txn_net_payable, paid_txn, status, bill_date")
                             .eq("firm_id", firm_id).eq("client_id", client_id))
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

    def _open_bank_balances(self, db, firm_id, client_id, period_end):
        """Open FOREIGN bank balances (Phase 5). Each foreign-currency bank account is
        revalued against ITS OWN GL account, so it is keyed by that account id
        (item_ref). foreign balance = Σ(txn_debit − txn_credit) over the account's
        posted journal lines; carrying base = Σ(debit − credit) in paise — both
        derived purely from posted data (no historical recompute). No-op until
        bank_accounts.currency exists (probed)."""
        try:
            banks = (db.table("bank_accounts")
                     .select("id, currency, coa_account_id")
                     .eq("firm_id", firm_id).eq("client_id", client_id).execute().data) or []
        except Exception:  # noqa: BLE001 — column/table absent ⇒ no foreign bank data
            return []
        out = []
        for b in banks:
            ccy = (b.get("currency") or _BASE).upper()
            acct = b.get("coa_account_id")
            if ccy == _BASE or not acct:
                continue
            foreign, base = self._account_foreign_and_base(db, firm_id, client_id, acct, period_end, ccy)
            if foreign != 0 or base != 0:
                out.append((ccy, acct, foreign, base))
        return out

    def _account_foreign_and_base(self, db, firm_id, client_id, account_id, as_of, currency):
        """Σ(txn_debit − txn_credit) [foreign] and Σ(debit − credit) [base paise] over an
        account's posted journal lines dated on/before `as_of`, counting ONLY lines in
        the account's own `currency`.

        Filtering by currency is essential: the base-INR revaluation overlay this service
        posts back onto the same bank account is stamped txn_currency='INR', so excluding
        it keeps BOTH the foreign holding and its carrying base at the original booked
        values across re-runs — that is what makes the delta idempotent/self-healing
        (exactly as AR/AP read the document, not the overlay)."""
        entries = _paginate_all(lambda: db.table("journal_entries").select("id, entry_date, is_posted, deleted_at")
                                .eq("firm_id", firm_id).eq("client_id", client_id)
                                .eq("is_posted", True).is_("deleted_at", "null"))
        keep = {e["id"] for e in entries if str(e.get("entry_date") or "")[:10] <= str(as_of)[:10]}
        if not keep:
            return 0, 0
        lines = _paginate_all(lambda: db.table("journal_lines")
                              .select("id, journal_entry_id, account_id, debit_paise, credit_paise, txn_debit, txn_credit, txn_currency")
                              .eq("account_id", account_id))
        cur = (currency or _BASE).upper()
        foreign = base = 0
        for l in lines:
            if l.get("journal_entry_id") not in keep:
                continue
            if (l.get("txn_currency") or _BASE).upper() != cur:
                continue
            base += int(l.get("debit_paise") or 0) - int(l.get("credit_paise") or 0)
            foreign += int(l.get("txn_debit") or 0) - int(l.get("txn_credit") or 0)
        return foreign, base

    def _prior_runs(self, db, firm_id, client_id, period_end, currency, item_type, item_ref=None):
        """Prior revaluation runs for this key → (cumulative_delta, run_count). The
        cumulative is what has already been posted; the next run posts target − it.
        item_ref is NULL for the aggregate AR/AP keys and the bank's GL account id for
        a per-account bank revaluation."""
        q = (db.table("fx_revaluations").select("delta_paise, item_ref")
             .eq("firm_id", firm_id).eq("client_id", client_id).eq("period_end", period_end)
             .eq("currency", currency).eq("item_type", item_type))
        if item_ref is None:
            rows = [r for r in (q.execute().data or []) if r.get("item_ref") in (None, "")]
        else:
            rows = q.eq("item_ref", item_ref).execute().data or []
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

        # Aggregate open foreign exposure per (currency, item_type, item_ref). AR/AP are
        # aggregated (item_ref=None); each foreign BANK account is its own item, keyed by
        # its GL account so multiple same-currency accounts never collide.
        exposure: dict = {}   # (currency, item_type, item_ref) -> [foreign_out, carrying_base]
        for ccy, f, b in self._open_receivables(db, firm_id, client_id, period_end):
            k = (ccy, "receivable", None); e = exposure.setdefault(k, [0, 0]); e[0] += f; e[1] += b
        for ccy, f, b in self._open_payables(db, firm_id, client_id, period_end):
            k = (ccy, "payable", None); e = exposure.setdefault(k, [0, 0]); e[0] += f; e[1] += b
        for ccy, acct_id, f, b in self._open_bank_balances(db, firm_id, client_id, period_end):
            k = (ccy, "bank", acct_id); e = exposure.setdefault(k, [0, 0]); e[0] += f; e[1] += b

        # Validate closing rates + currencies up front (Task 6).
        for (ccy, _item, _ref) in exposure:
            cur = currency_service.get_currency(db, ccy)
            if not cur:
                raise HTTPException(status_code=422, detail=f"Unsupported currency in revaluation: {ccy}.")
            if ccy not in closing_rates and str(ccy) not in {str(x) for x in closing_rates}:
                raise HTTPException(status_code=422, detail=f"Missing closing rate for {ccy} at {period_end}.")
            rate = Decimal(str(closing_rates[ccy]))
            if rate <= 0:
                raise HTTPException(status_code=422, detail=f"Closing rate for {ccy} must be positive.")

        results = []
        for (ccy, item_type, item_ref), (foreign_out, carrying_base) in sorted(
                exposure.items(), key=lambda kv: (kv[0][0], kv[0][1], str(kv[0][2] or ""))):
            minor = int(currency_service.get_currency(db, ccy).get("minor_unit", 2))
            rc = Decimal(str(closing_rates[ccy]))
            revalued = to_base_minor(foreign_out, rc, minor)
            # AR and BANK are assets, AP is a liability; the target adjustment to the
            # carrying base is the same signed quantity (revalued − carrying) for all —
            # only the journal direction differs (handled in _post_reval).
            target = revalued - carrying_base
            prior, run_count = self._prior_runs(db, firm_id, client_id, period_end, ccy, item_type, item_ref)
            delta = target - prior
            if delta == 0:
                results.append({"currency": ccy, "item_type": item_type, "item_ref": item_ref,
                                "target_paise": target, "delta_paise": 0, "journal_entry_id": None})
                continue

            entry_id = self._post_reval(db, firm_id, client_id, period_end, ccy, item_type,
                                        delta, actor, run_count + 1, item_ref)
            reversal_id = K.reverse_entry(
                db, firm_id=firm_id, entry_id=entry_id, reversal_date=reversal_date,
                narration=f"Auto-reversal of {ccy} {item_type} revaluation {period_end}",
                created_by=actor.get("id"))

            db.table("fx_revaluations").insert({
                "firm_id": firm_id, "client_id": client_id, "period_end": period_end,
                "currency": ccy, "item_type": item_type, "item_ref": item_ref, "closing_rate": str(rc),
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
            results.append({"currency": ccy, "item_type": item_type, "item_ref": item_ref,
                            "target_paise": target, "delta_paise": delta, "journal_entry_id": entry_id,
                            "reversal_entry_id": reversal_id})
        return {"period_end": period_end, "reversal_date": reversal_date, "adjustments": results}

    def _post_reval(self, db, firm_id, client_id, period_end, ccy, item_type, delta, actor, run_seq, item_ref=None) -> str:
        """Post the delta revaluation journal (base INR) through the kernel.

        Receivable / Bank (assets): a positive delta means the asset is worth more →
        Dr asset / Cr Unrealized FX (gain). Payable (liability): a positive delta means
        we owe more → Cr AP / Dr Unrealized FX (loss). Negative deltas swap the sides."""
        fx_id = K._find_account(db, firm_id, client_id, "%Foreign Exchange%", system_key="fx_unrealized")
        ref_suffix = f"-{str(item_ref)[:8]}" if item_ref else ""
        if item_type in ("receivable", "bank"):
            if item_type == "bank":
                ctrl = item_ref            # the specific foreign bank account's GL account
                asset_label = "Bank revaluation"
            else:
                ctrl = K._find_account(db, firm_id, client_id, "%Trade Receivable%", system_key="ar")
                asset_label = "AR revaluation"
            if delta > 0:      # asset up (Dr), unrealized gain (Cr)
                lines = [{"account_id": ctrl, "debit_paise": delta, "credit_paise": 0, "narration": asset_label},
                         {"account_id": fx_id, "debit_paise": 0, "credit_paise": delta, "narration": "Unrealized FX gain"}]
            else:              # asset down (Cr), unrealized loss (Dr)
                d = -delta
                lines = [{"account_id": fx_id, "debit_paise": d, "credit_paise": 0, "narration": "Unrealized FX loss"},
                         {"account_id": ctrl, "debit_paise": 0, "credit_paise": d, "narration": asset_label}]
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
        # idempotency dedup never collapses a genuine delta onto a prior run; the item_ref
        # suffix keeps two same-currency bank accounts distinct.
        ref = f"FXREVAL-{period_end}-{ccy}-{item_type[:3].upper()}{ref_suffix}-{run_seq}"
        return K._create_journal(
            db=db, firm_id=firm_id, client_id=client_id, entry_date=period_end,
            reference_no=ref, narration=f"Unrealized FX revaluation — {ccy} {item_type} @ {period_end}",
            entry_type="Journal", lines=lines, created_by=actor.get("id"))


fx_revaluation_service = FXRevaluationService()
