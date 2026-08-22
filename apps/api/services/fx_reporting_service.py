"""
FX reporting service — Multi-Currency Phase 5, Task 3. READ-ONLY.

Five foreign-exchange reports, every one DERIVED FROM POSTED ACCOUNTING DATA (the
append-only `fx_adjustments` / `fx_revaluations` audit tables written by the Phase-4
settlement + revaluation paths, and the open foreign documents whose base amounts
already sit in the GL). Nothing here posts, recomputes a historical rate, or changes
any balance — the functional (INR) ledger stays authoritative.

  1. realized_fx           — realized gain/loss on settlement (fx_adjustments)
  2. unrealized_fx         — period-end revaluation runs (fx_revaluations)
  3. currency_exposure     — open foreign AR / AP / bank by currency
  4. exchange_rate_audit   — every rate used, with full provenance
  5. open_foreign_balances — each open foreign document's foreign + base outstanding

Sign convention (as written by the posting paths): base_delta_paise > 0 is a GAIN,
< 0 is a LOSS. All money is integer paise / integer minor units.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

_BASE = "INR"
# A document no longer contributes to an OPEN foreign balance once it is a draft,
# cancelled, or fully paid — matching FXRevaluationService's open-item filter.
_DEAD = {"draft", "cancelled", "paid"}
# For the rate-audit trail (below), a draft was never issued (no journal posted, no
# real transaction) and a cancelled document was voided — neither used its stamped
# rate for anything real. "paid" is intentionally NOT excluded here: a fully-settled
# document is exactly the kind of completed FX transaction the audit trail exists to
# show, unlike the open-balance filter above.
_DEAD_UNISSUED = {"draft", "cancelled"}


def _paginate_all(make_query, key: str = "id", page: int = 1000) -> list:
    """Fetch EVERY row of a Supabase query via keyset paging on `key`.

    An un-paged .execute() is silently capped at PostgREST's ~1000-row limit, so
    for a large ledger this would truncate the read and understate FX balances /
    mis-date FX adjustments (no error). `make_query` returns a fresh query builder
    each call. Test doubles that don't implement order/limit/gt just return their
    whole (small) fixture from a single execute(), which is already correct."""
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


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _d(v) -> str:
    return str(v)[:10]


def _within(when, start: Optional[str], end: Optional[str]) -> bool:
    day = _d(when)
    if start and day < _d(start):
        return False
    if end and day > _d(end):
        return False
    return True


class FXReportingService:
    # ── shared open-document readers (foreign only) ────────────────────────────
    def _open_foreign_invoices(self, db, firm_id, client_id, as_of: str) -> list[dict]:
        rows = _paginate_all(lambda: db.table("client_sales_invoices")
                             .select("id, invoice_no, invoice_date, customer_id, status, total_paise, paid_paise, "
                                     "credited_paise, txn_currency, exchange_rate, txn_total, paid_txn")
                             .eq("firm_id", firm_id).eq("client_id", client_id))
        out = []
        for r in rows:
            cur = (r.get("txn_currency") or _BASE).upper()
            if cur == _BASE or (r.get("status") or "") in _DEAD:
                continue
            if _d(r.get("invoice_date")) > _d(as_of):
                continue
            base_out = int(r.get("total_paise") or 0) - int(r.get("paid_paise") or 0) - int(r.get("credited_paise") or 0)
            foreign_out = int(r.get("txn_total") or 0) - int(r.get("paid_txn") or 0)
            if foreign_out > 0:
                out.append({"id": r.get("id"), "doc_no": r.get("invoice_no"), "party_id": r.get("customer_id"),
                            "date": _d(r.get("invoice_date")), "currency": cur,
                            "exchange_rate": str(r.get("exchange_rate") or 1),
                            "foreign_outstanding_minor": foreign_out, "base_outstanding_paise": base_out})
        return out

    def _open_foreign_bills(self, db, firm_id, client_id, as_of: str) -> list[dict]:
        rows = _paginate_all(lambda: db.table("purchase_bills")
                             .select("id, bill_no, bill_date, vendor_id, status, net_payable_paise, paid_paise, "
                                     "debited_paise, txn_currency, exchange_rate, txn_net_payable, paid_txn")
                             .eq("firm_id", firm_id).eq("client_id", client_id))
        out = []
        for r in rows:
            cur = (r.get("txn_currency") or _BASE).upper()
            if cur == _BASE or (r.get("status") or "") in _DEAD:
                continue
            if _d(r.get("bill_date")) > _d(as_of):
                continue
            base_out = int(r.get("net_payable_paise") or 0) - int(r.get("paid_paise") or 0) - int(r.get("debited_paise") or 0)
            foreign_out = int(r.get("txn_net_payable") or 0) - int(r.get("paid_txn") or 0)
            if foreign_out > 0:
                out.append({"id": r.get("id"), "doc_no": r.get("bill_no"), "party_id": r.get("vendor_id"),
                            "date": _d(r.get("bill_date")), "currency": cur,
                            "exchange_rate": str(r.get("exchange_rate") or 1),
                            "foreign_outstanding_minor": foreign_out, "base_outstanding_paise": base_out})
        return out

    def _foreign_bank_balances(self, db, firm_id, client_id) -> list[dict]:
        """Open foreign BANK balances from posted data (Task 5). A no-op until
        bank_accounts.currency exists (the column is probed, so this is safe on any
        schema). foreign balance = Σ(txn_debit − txn_credit) over the account's posted
        journal lines; base carrying = Σ(debit − credit) in paise."""
        try:
            banks = (db.table("bank_accounts")
                     .select("id, bank_name, account_no, currency, coa_account_id")
                     .eq("firm_id", firm_id).eq("client_id", client_id).execute().data) or []
        except Exception:  # noqa: BLE001 — column/table absent ⇒ no foreign bank data yet
            return []
        out = []
        for b in banks:
            cur = (b.get("currency") or _BASE).upper()
            if cur == _BASE or not b.get("coa_account_id"):
                continue
            foreign, base = _account_foreign_and_base(db, firm_id, client_id, b["coa_account_id"], cur)
            if foreign == 0 and base == 0:
                continue
            out.append({"id": b.get("id"), "name": b.get("bank_name"), "account_no": b.get("account_no"),
                        "currency": cur, "foreign_balance_minor": foreign, "base_balance_paise": base})
        return out

    def _entry_dates(self, db, firm_id, client_id) -> dict:
        """{journal_entry_id: entry_date} for posted entries — so an FX adjustment is
        reported in its SETTLEMENT/posting period (period-accurate for backdated and
        multi-year settlements), not by the audit row's insert timestamp."""
        rows = _paginate_all(lambda: db.table("journal_entries").select("id, entry_date")
                             .eq("firm_id", firm_id).eq("client_id", client_id)
                             .eq("is_posted", True).is_("deleted_at", "null"))
        return {r["id"]: _d(r.get("entry_date")) for r in rows}

    # ── 1. Realized FX gain/loss ───────────────────────────────────────────────
    def realized_fx(self, db, firm_id, client_id, start=None, end=None) -> dict:
        def _adj_query():
            qq = db.table("fx_adjustments").select("*").eq("firm_id", firm_id).eq("kind", "realized")
            if client_id:
                qq = qq.eq("client_id", client_id)
            return qq
        entry_dates = self._entry_dates(db, firm_id, client_id)
        lines, by_ccy, gain, loss = [], {}, 0, 0
        for r in _paginate_all(_adj_query):
            when = entry_dates.get(r.get("journal_entry_id")) or r.get("created_at")
            if not _within(when, start, end):
                continue
            delta = int(r.get("base_delta_paise") or 0)
            cur = (r.get("currency") or "").upper()
            gain += delta if delta > 0 else 0
            loss += -delta if delta < 0 else 0
            slot = by_ccy.setdefault(cur, {"currency": cur, "gain_paise": 0, "loss_paise": 0, "net_paise": 0})
            slot["gain_paise"] += delta if delta > 0 else 0
            slot["loss_paise"] += -delta if delta < 0 else 0
            slot["net_paise"] += delta
            lines.append({
                "date": _d(when), "document_type": r.get("document_type"),
                "document_id": r.get("document_id"), "currency": cur,
                "settlement_rate": (str(r["settlement_rate"]) if r.get("settlement_rate") is not None else None),
                "base_delta_paise": delta, "is_gain": delta > 0,
                "journal_entry_id": r.get("journal_entry_id"), "rate_source": r.get("rate_source"),
            })
        lines.sort(key=lambda x: (x["date"], str(x["currency"])))
        return {"period": {"start": _d(start) if start else None, "end": _d(end) if end else None},
                "lines": lines, "gain_paise": gain, "loss_paise": loss, "net_paise": gain - loss,
                "by_currency": sorted(by_ccy.values(), key=lambda x: x["currency"])}

    # ── 2. Unrealized FX revaluation ───────────────────────────────────────────
    def unrealized_fx(self, db, firm_id, client_id, period_end=None) -> dict:
        def _reval_query():
            qq = db.table("fx_revaluations").select("*").eq("firm_id", firm_id)
            if client_id:
                qq = qq.eq("client_id", client_id)
            if period_end:
                qq = qq.eq("period_end", _d(period_end))
            return qq
        rows = _paginate_all(_reval_query)
        groups: dict = {}
        for r in rows:
            key = (_d(r.get("period_end")), (r.get("currency") or "").upper(), r.get("item_type"))
            g = groups.setdefault(key, {
                "period_end": key[0], "currency": key[1], "item_type": key[2],
                "closing_rate": None, "target_adjustment_paise": 0, "cumulative_delta_paise": 0,
                "runs": 0, "journal_entry_ids": [], "reversal_entry_ids": [], "last_run_at": None,
            })
            g["cumulative_delta_paise"] += int(r.get("delta_paise") or 0)
            g["target_adjustment_paise"] = int(r.get("target_adjustment_paise") or 0)   # latest wins
            g["closing_rate"] = str(r["closing_rate"]) if r.get("closing_rate") is not None else g["closing_rate"]
            g["runs"] += 1
            if r.get("journal_entry_id"):
                g["journal_entry_ids"].append(r["journal_entry_id"])
            if r.get("reversal_entry_id"):
                g["reversal_entry_ids"].append(r["reversal_entry_id"])
            if not g["last_run_at"] or _d(r.get("run_at")) >= _d(g["last_run_at"]):
                g["last_run_at"] = r.get("run_at")
        by_ccy: dict = {}
        for g in groups.values():
            slot = by_ccy.setdefault(g["currency"], {"currency": g["currency"], "net_paise": 0})
            slot["net_paise"] += g["cumulative_delta_paise"]
        return {"period_end": _d(period_end) if period_end else None,
                "lines": sorted(groups.values(), key=lambda x: (x["period_end"], x["currency"], str(x["item_type"]))),
                "by_currency": sorted(by_ccy.values(), key=lambda x: x["currency"]),
                "net_paise": sum(s["net_paise"] for s in by_ccy.values())}

    # ── 3. Currency exposure ───────────────────────────────────────────────────
    def currency_exposure(self, db, firm_id, client_id, as_of=None) -> dict:
        as_of = _d(as_of) if as_of else _today()
        by: dict = {}

        def slot(cur):
            return by.setdefault(cur, {
                "currency": cur, "receivable_foreign_minor": 0, "receivable_base_paise": 0,
                "payable_foreign_minor": 0, "payable_base_paise": 0,
                "bank_foreign_minor": 0, "bank_base_paise": 0,
                "net_foreign_minor": 0, "net_base_paise": 0})

        for inv in self._open_foreign_invoices(db, firm_id, client_id, as_of):
            s = slot(inv["currency"])
            s["receivable_foreign_minor"] += inv["foreign_outstanding_minor"]
            s["receivable_base_paise"] += inv["base_outstanding_paise"]
        for bill in self._open_foreign_bills(db, firm_id, client_id, as_of):
            s = slot(bill["currency"])
            s["payable_foreign_minor"] += bill["foreign_outstanding_minor"]
            s["payable_base_paise"] += bill["base_outstanding_paise"]
        for bank in self._foreign_bank_balances(db, firm_id, client_id):
            s = slot(bank["currency"])
            s["bank_foreign_minor"] += bank["foreign_balance_minor"]
            s["bank_base_paise"] += bank["base_balance_paise"]

        for s in by.values():
            # Net monetary exposure = assets (AR + bank) − liabilities (AP).
            s["net_foreign_minor"] = s["receivable_foreign_minor"] + s["bank_foreign_minor"] - s["payable_foreign_minor"]
            s["net_base_paise"] = s["receivable_base_paise"] + s["bank_base_paise"] - s["payable_base_paise"]
        return {"as_of": as_of, "by_currency": sorted(by.values(), key=lambda x: x["currency"])}

    # ── 4. Exchange-rate audit ─────────────────────────────────────────────────
    def exchange_rate_audit(self, db, firm_id, client_id, start=None, end=None) -> dict:
        documents = []
        for tbl, no_col, date_col in (("client_sales_invoices", "invoice_no", "invoice_date"),
                                      ("purchase_bills", "bill_no", "bill_date")):
            # Every one of these three conditions belongs in the query (CLAUDE.md,
            # "Reporting performance"). This used to fetch every invoice and every
            # bill the client had ever raised and drop the INR / unissued / out-of-
            # window ones in Python: 6,421 rows on the live client to produce a
            # report that, with no foreign activity booked, is EMPTY. The endpoint
            # already took start/end and threw them away.
            #
            # txn_currency and status are both NOT NULL on both tables (verified
            # against the live catalogue), so neq/not-in are exact here — no row
            # goes missing to SQL's three-valued logic the way a nullable column
            # would. The Python guard below stays as belt and braces for test
            # doubles and for a lower-cased currency code.
            def _doc_query(tbl=tbl, no_col=no_col, date_col=date_col):
                q = (db.table(tbl)
                     .select(f"id, {no_col}, {date_col}, txn_currency, exchange_rate, rate_source, "
                             f"rate_type, rate_date, rate_selected_by, rate_overridden, status")
                     .eq("firm_id", firm_id).eq("client_id", client_id)
                     .neq("txn_currency", _BASE)
                     .not_.in_("status", list(_DEAD_UNISSUED)))
                if start:
                    q = q.gte(date_col, _d(start))
                if end:
                    q = q.lte(date_col, _d(end))
                return q
            rows = _paginate_all(_doc_query)
            for r in rows:
                cur = (r.get("txn_currency") or _BASE).upper()
                if cur == _BASE or (r.get("status") or "") in _DEAD_UNISSUED or not _within(r.get(date_col), start, end):
                    continue
                documents.append({
                    "document_type": tbl, "document_id": r.get("id"), "document_no": r.get(no_col),
                    "date": _d(r.get(date_col)), "currency": cur,
                    "exchange_rate": str(r.get("exchange_rate") or 1), "rate_source": r.get("rate_source"),
                    "rate_type": r.get("rate_type"), "rate_date": (_d(r["rate_date"]) if r.get("rate_date") else None),
                    "rate_selected_by": r.get("rate_selected_by"), "rate_overridden": bool(r.get("rate_overridden")),
                })
        def _adj_query():
            qq = db.table("fx_adjustments").select("*").eq("firm_id", firm_id)
            if client_id:
                qq = qq.eq("client_id", client_id)
            return qq
        entry_dates = self._entry_dates(db, firm_id, client_id)
        adjustments = []
        for r in _paginate_all(_adj_query):
            when = entry_dates.get(r.get("journal_entry_id")) or r.get("created_at")
            if not _within(when, start, end):
                continue
            adjustments.append({
                "date": _d(when), "kind": r.get("kind"), "currency": (r.get("currency") or "").upper(),
                "document_type": r.get("document_type"), "document_id": r.get("document_id"),
                "original_rate": (str(r["original_rate"]) if r.get("original_rate") is not None else None),
                "settlement_rate": (str(r["settlement_rate"]) if r.get("settlement_rate") is not None else None),
                "closing_rate": (str(r["closing_rate"]) if r.get("closing_rate") is not None else None),
                "base_delta_paise": int(r.get("base_delta_paise") or 0), "rate_source": r.get("rate_source"),
                "created_by": r.get("created_by"),
            })
        documents.sort(key=lambda x: (x["date"], str(x["document_no"])))
        adjustments.sort(key=lambda x: (x["date"], str(x["currency"])))
        return {"period": {"start": _d(start) if start else None, "end": _d(end) if end else None},
                "documents": documents, "adjustments": adjustments,
                "overridden_count": sum(1 for d in documents if d["rate_overridden"])}

    # ── 5. Open foreign balances ───────────────────────────────────────────────
    def open_foreign_balances(self, db, firm_id, client_id, as_of=None) -> dict:
        as_of = _d(as_of) if as_of else _today()
        receivables = self._open_foreign_invoices(db, firm_id, client_id, as_of)
        payables = self._open_foreign_bills(db, firm_id, client_id, as_of)
        banks = self._foreign_bank_balances(db, firm_id, client_id)
        for r in receivables:
            r["document_type"] = "sales_invoice"
        for p in payables:
            p["document_type"] = "purchase_bill"
        return {"as_of": as_of, "receivables": receivables, "payables": payables, "bank_accounts": banks}


def _account_foreign_and_base(db, firm_id, client_id, account_id, currency=_BASE) -> tuple[int, int]:
    """Σ(txn_debit − txn_credit) [foreign minor] and Σ(debit − credit) [base paise] over
    the posted journal lines of one account, counting ONLY lines in `currency`.

    Filtering by currency isolates the foreign-currency holding from any base-INR
    revaluation overlay posted back onto the same account (overlays are stamped
    txn_currency='INR'), so the reported foreign balance and its carrying base are the
    stable booked values. Derived purely from posted data; tolerant of an absent FX
    column set (returns 0/0 for a foreign filter) so it is safe on any schema."""
    entries = _paginate_all(lambda: db.table("journal_entries").select("id, is_posted, deleted_at")
                            .eq("firm_id", firm_id).eq("client_id", client_id)
                            .eq("is_posted", True).is_("deleted_at", "null"))
    entry_ids = {e["id"] for e in entries}
    if not entry_ids:
        return 0, 0
    lines = _paginate_all(lambda: db.table("journal_lines")
                          .select("id, journal_entry_id, account_id, debit_paise, credit_paise, txn_debit, txn_credit, txn_currency")
                          .eq("account_id", account_id))
    cur = (currency or _BASE).upper()
    foreign = base = 0
    for l in lines:
        if l.get("journal_entry_id") not in entry_ids:
            continue
        if (l.get("txn_currency") or _BASE).upper() != cur:
            continue
        base += int(l.get("debit_paise") or 0) - int(l.get("credit_paise") or 0)
        foreign += int(l.get("txn_debit") or 0) - int(l.get("txn_credit") or 0)
    return foreign, base


fx_reporting_service = FXReportingService()
