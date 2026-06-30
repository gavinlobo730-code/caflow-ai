"""
Opening-balance journalisation — turns master-record opening balances into real
General-Ledger entries so the books reconcile.

Background (audit finding): customers.opening_balance_paise, vendors.opening_balance_paise
and bank_accounts.opening_balance_paise are onboarding inputs that were NEVER posted
to the ledger. Customer/vendor statements add them ad-hoc, but the Trial Balance and
Balance Sheet sum journal_lines only — so opening balances were invisible to the GL and
the books did not reconcile.

Fix: post ONE balanced opening journal per client (entry_type='opening_balance'),
contra'd to an "Opening Balance Equity" control account:

    Dr Trade Receivables   = Σ active customers' opening_balance_paise   (asset)
    Dr Bank (per account)  = Σ active bank accounts' opening_balance_paise
    Cr Trade Payables      = Σ active vendors' opening_balance_paise      (liability)
    Cr/Dr Opening Balance Equity = balancing contra

Why this reconciles WITHOUT touching the reporting engine or statements:
  * GL/TB/BS already sum posted journal_lines cumulatively → they now include the
    opening journal, so AR/AP/Bank controls carry their opening balances.
  * Customer/vendor statements keep reading the master opening_balance_paise field.
  * Each opening figure is therefore counted exactly once per report (the statement
    via the master field; the GL via this journal), and the two agree in aggregate:
        GL Trade Receivables = Σ customer openings + invoice AR − receipt AR
                             = Σ (customer statement balances)
  No double counting; reporting/statement code is unchanged.

Idempotent & single source of truth: posting first deletes the client's prior
opening_balance journal, then re-derives from the current master records. Re-running
never duplicates and always reflects the current opening figures.

All money is integer paise. CGST/IT Act: opening balances are book figures, not new
supplies — no GST is computed on them.
"""
import os
import logging
from typing import Optional

from services.phase2_journal_service import phase2_journal_service
from services.period_validation_service import period_validation_service

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.opening_balance")

OPENING_ENTRY_TYPE = "opening_balance"
OPENING_REFERENCE = "OPENING-BALANCE"


def _db():
    from core.supabase_client import get_supabase
    return get_supabase()


def _sum_opening(rows: list[dict]) -> int:
    return sum(int(r.get("opening_balance_paise") or 0) for r in (rows or []))


def _default_opening_date(db, client_id: str, customers: list[dict],
                          vendors: list[dict], banks: list[dict]) -> str:
    """Pick the opening-balance date: the client's financial-year start, else the
    earliest master opening_balance_date, else April 1 of the earliest such year,
    else today's April 1. Opening balances are conventionally dated at FY start."""
    try:
        cl = db.table("clients").select("financial_year_start").eq("id", client_id).limit(1).execute()
        if cl.data and cl.data[0].get("financial_year_start"):
            return str(cl.data[0]["financial_year_start"])
    except Exception as e:
        _logger.warning("opening_balance: client FY-start lookup failed: %s", e)
    dates = [r.get("opening_balance_date") for r in (customers + vendors + banks)
             if r.get("opening_balance_date")]
    if dates:
        return str(min(dates))
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    fy_start = now.year if now.month >= 4 else now.year - 1
    return f"{fy_start}-04-01"


def _delete_existing(db, firm_id: str, client_id: str) -> None:
    """Remove any prior opening-balance journal (and its lines) for this client so a
    re-post is idempotent and always reflects the current master figures."""
    existing = (
        db.table("journal_entries").select("id")
        .eq("firm_id", firm_id).eq("client_id", client_id)
        .eq("entry_type", OPENING_ENTRY_TYPE).execute()
    )
    for e in (existing.data or []):
        db.table("journal_lines").delete().eq("journal_entry_id", e["id"]).execute()
        db.table("journal_entries").delete().eq("id", e["id"]).execute()


def post_opening_balances(
    firm_id: str,
    client_id: str,
    opening_date: Optional[str] = None,
    created_by: Optional[str] = None,
) -> dict:
    """(Re)post the client's opening-balance journal from current master records.

    Returns a summary: {posted, journal_entry_id, opening_date, ar_paise, ap_paise,
    bank_paise, opening_equity_paise}. posted=False when there are no opening
    balances to record.
    """
    if _USE_MOCK:
        return {"posted": False, "mock": True, "reason": "no DB configured"}

    db = _db()

    customers = (db.table("customers").select("opening_balance_paise, opening_balance_date")
                 .eq("client_id", client_id).eq("is_active", True).execute().data or [])
    vendors = (db.table("vendors").select("opening_balance_paise, opening_balance_date")
               .eq("client_id", client_id).eq("is_active", True).execute().data or [])
    banks = (db.table("bank_accounts")
             .select("opening_balance_paise, opening_balance_date, coa_account_id")
             .eq("client_id", client_id).eq("is_active", True).execute().data or [])

    ar_total = _sum_opening(customers)
    ap_total = _sum_opening(vendors)
    bank_total = _sum_opening(banks)

    date = opening_date or _default_opening_date(db, client_id, customers, vendors, banks)

    # FY-lock: refuse to (re)write opening balances into a locked year. Validate
    # BEFORE any mutation so a locked-year block never wipes the existing journal.
    period_validation_service.validate_posting_date(firm_id, date)

    # Clear the prior opening journal (idempotent / single source of truth).
    _delete_existing(db, firm_id, client_id)

    if ar_total == 0 and ap_total == 0 and bank_total == 0:
        return {"posted": False, "reason": "no opening balances", "opening_date": date,
                "ar_paise": 0, "ap_paise": 0, "bank_paise": 0, "opening_equity_paise": 0}

    lines: list[dict] = []
    if ar_total:
        ar_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Trade Receivable%", system_key="ar")
        lines.append({"account_id": ar_id, "debit_paise": ar_total, "credit_paise": 0,
                      "narration": "Opening trade receivables"})
    if ap_total:
        ap_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Trade Payable%", system_key="ap")
        lines.append({"account_id": ap_id, "debit_paise": 0, "credit_paise": ap_total,
                      "narration": "Opening trade payables"})
    # Bank: post to each account's mapped COA account when set, else the generic Bank.
    bank_by_account: dict[str, int] = {}
    generic_bank_total = 0
    for b in banks:
        amt = int(b.get("opening_balance_paise") or 0)
        if not amt:
            continue
        coa = b.get("coa_account_id")
        if coa:
            bank_by_account[coa] = bank_by_account.get(coa, 0) + amt
        else:
            generic_bank_total += amt
    for coa_id, amt in bank_by_account.items():
        lines.append({"account_id": coa_id, "debit_paise": amt, "credit_paise": 0,
                      "narration": "Opening bank balance"})
    if generic_bank_total:
        bank_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Bank%", system_key="bank")
        lines.append({"account_id": bank_id, "debit_paise": generic_bank_total, "credit_paise": 0,
                      "narration": "Opening bank balance"})

    # Balancing contra → Opening Balance Equity.
    total_debit = sum(l["debit_paise"] for l in lines)
    total_credit = sum(l["credit_paise"] for l in lines)
    diff = total_debit - total_credit
    opening_equity = 0
    if diff != 0:
        obe_id = phase2_journal_service._find_account(
            db, firm_id, client_id, "%Opening Balance Equity%"
        )
        if diff > 0:
            lines.append({"account_id": obe_id, "debit_paise": 0, "credit_paise": diff,
                          "narration": "Opening balance equity"})
        else:
            lines.append({"account_id": obe_id, "debit_paise": -diff, "credit_paise": 0,
                          "narration": "Opening balance equity"})
        opening_equity = diff

    entry_id = phase2_journal_service._create_journal(
        db, firm_id, client_id, date, OPENING_REFERENCE,
        "Opening balances brought forward", OPENING_ENTRY_TYPE, lines,
        is_posted=True, source_type=OPENING_ENTRY_TYPE, created_by=created_by,
    )

    _logger.info("Posted opening-balance journal %s for client %s (ar=%d ap=%d bank=%d)",
                 entry_id, client_id, ar_total, ap_total, bank_total)
    return {
        "posted": True,
        "journal_entry_id": entry_id,
        "opening_date": date,
        "ar_paise": ar_total,
        "ap_paise": ap_total,
        "bank_paise": bank_total,
        "opening_equity_paise": opening_equity,
    }


def opening_balance_status(firm_id: str, client_id: str) -> dict:
    """Report whether the client's master opening balances are reflected in the GL.

    Lets the UI surface "₹X opening balances are not yet in the ledger" and decide
    whether to prompt a (re)post — so the Trial Balance can never silently disagree
    with Customer Statements.

    needs_posting is true when the posted opening journal's gross debit total does
    not equal what the current master records imply — i.e. nothing posted yet,
    figures changed since posting, or balances were cleared but a stale journal
    remains. Comparing the scalar gross debit total is exact for this journal shape
    (Dr AR + Dr Bank + Cr AP, contra Opening Balance Equity).
    """
    if _USE_MOCK:
        return {"needs_posting": False, "ar_paise": 0, "ap_paise": 0, "bank_paise": 0,
                "expected_total_paise": 0, "posted_total_paise": 0, "has_opening_journal": False}

    db = _db()
    customers = (db.table("customers").select("opening_balance_paise")
                 .eq("client_id", client_id).eq("is_active", True).execute().data or [])
    vendors = (db.table("vendors").select("opening_balance_paise")
               .eq("client_id", client_id).eq("is_active", True).execute().data or [])
    banks = (db.table("bank_accounts").select("opening_balance_paise")
             .eq("client_id", client_id).eq("is_active", True).execute().data or [])
    ar = _sum_opening(customers)
    ap = _sum_opening(vendors)
    bank = _sum_opening(banks)
    # Gross debit total the opening journal should carry for these figures.
    expected_total = max(ar + bank, ap)

    existing = (db.table("journal_entries").select("id")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .eq("entry_type", OPENING_ENTRY_TYPE).execute().data or [])
    posted_total = 0
    for e in existing:
        lines = db.table("journal_lines").select("debit_paise").eq("journal_entry_id", e["id"]).execute().data or []
        posted_total += sum(int(l.get("debit_paise") or 0) for l in lines)

    return {
        "needs_posting": expected_total != posted_total,
        "ar_paise": ar,
        "ap_paise": ap,
        "bank_paise": bank,
        "expected_total_paise": expected_total,
        "posted_total_paise": posted_total,
        "has_opening_journal": bool(existing),
    }
