"""
Opening-balance journalisation — turns master-record opening balances into real
General-Ledger entries so the books reconcile.

Master fields customers/vendors/bank_accounts.opening_balance_paise are the single
source of truth for opening positions. This service keeps the General Ledger in
sync with them by posting **incremental adjusting entries (deltas)** — an
append-only model that never mutates or deletes a posted journal.

Why append-only deltas (not delete-and-recreate, not reverse-and-repost):
  * Delete-and-recreate conflicts with journal immutability — a posted entry
    cannot be deleted (trigger `prevent_posted_journal_delete`), so regeneration
    would fail whenever an opening journal already existed.
  * Reverse-and-repost preserves immutability but regenerates the WHOLE journal on
    every change, cluttering the AR/OBE ledgers with net-zero reversal pairs.
  * Deltas preserve immutability AND keep the books clean: each change posts ONE
    small balanced entry for the difference between the master target and what the
    GL currently carries. No special case, no trigger exemption — opening balances
    follow the same append-only, kernel-routed discipline as every transaction.

The opening position brought into the GL is contra'd to an "Opening Balance Equity"
control account:

    Dr Trade Receivables   = Σ active customers' opening_balance_paise   (asset)
    Dr Bank (per account)  = Σ active bank accounts' opening_balance_paise
    Cr Trade Payables      = Σ active vendors' opening_balance_paise      (liability)
    Cr/Dr Opening Balance Equity = balancing contra

Identity: the auto-maintained opening family is every journal entry with
`source_type = 'Opening'` for the client. A user's own manually-created "Opening"
entry uses `source_type = 'manual'`, so it is never touched by this service.

Idempotent & self-healing: a re-run with no master change computes a zero delta and
posts nothing; any drift between the GL and the masters is corrected by the next
delta. All money is integer paise. Opening balances are book figures, not supplies —
no GST is computed.

SCOPE — why a sync triggered from one screen may not touch another's leg
    This service is called two ways. The Accounting → Opening Balances screen calls
    it deliberately and wants the whole position reconciled, so it passes no scope.
    Everything else calls it as a SIDE EFFECT of saving one master record — a bank
    account, a customer, a vendor — and those callers pass the leg they changed.

    Without that, saving a bank account recomputed every leg. A CA adding an HDFC
    account to a live client had 40.54 lakh of opening Trade Payables silently
    reversed out of the GL, because the vendor masters happened to carry zero and
    the delta engine dutifully "corrected" the drift. The figures were defensible;
    posting them from the bank screen, with no warning and no confirmation, was not.

    So a scoped call computes deltas only for accounts belonging to its own leg and
    balances them through Opening Balance Equity. Drift on another leg is left
    exactly where it is, for the screen that owns it to reconcile. An account the
    service cannot attribute to a leg is never touched by a scoped call.
"""
import os
import uuid
import logging
from typing import Optional

from services.phase2_journal_service import phase2_journal_service
from services.period_validation_service import period_validation_service

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.opening_balance")

# entry_type MUST be one of the values allowed by the journal_entries CHECK
# constraint (Sales/Purchase/Payment/Receipt/Journal/Contra/Opening).
OPENING_ENTRY_TYPE = "Opening"
# source_type identifies the auto-maintained opening family (distinct from a user's
# manual "Opening" journal, which carries source_type='manual').
OPENING_SOURCE = "Opening"
# Human-readable reference prefix; each delta gets a unique suffix so it never
# collides with the kernel's (client, reference, date) de-duplication.
OPENING_REFERENCE = "OPENING-BALANCE"


def _db():
    from core.supabase_client import get_supabase
    return get_supabase()


def _sum_opening(rows: list[dict]) -> int:
    return sum(int(r.get("opening_balance_paise") or 0) for r in (rows or []))


def _fetch_masters(db, firm_id: str, client_id: str):
    """Deliberately NOT filtered by is_active: deactivating a customer/vendor/
    bank account only flips is_active — opening_balance_paise is untouched and
    deactivation docstrings promise history stays intact (customers.py /
    vendors.py delete_*, test_customer_lifecycle.py). _current_opening_net()
    below reads the posted GL without an is_active filter either, so this
    target computation must match it column-for-column — filtering here would
    make an unrelated party's opening-balance edit (which triggers a delta
    sync) silently reverse a deactivated party's opening balance out of Trade
    Receivables/Payables.

    task #231 audit finding (defense-in-depth): filtered by firm_id too — the
    primary fix is customers.py/vendors.py's create endpoints now validating
    client_id ownership before insert, but this was the amplification path a
    planted cross-firm row would have reached: unfiltered by firm_id, this
    used to aggregate EVERY row matching client_id regardless of which firm
    inserted it, so a firm that got a customer/vendor past that ownership
    check could pull another firm's real opening balances into its own
    posted GL journal."""
    customers = (db.table("customers").select("opening_balance_paise, opening_balance_date")
                 .eq("firm_id", firm_id).eq("client_id", client_id).execute().data or [])
    vendors = (db.table("vendors").select("opening_balance_paise, opening_balance_date")
               .eq("firm_id", firm_id).eq("client_id", client_id).execute().data or [])
    banks = (db.table("bank_accounts")
             .select("opening_balance_paise, opening_balance_date, coa_account_id")
             .eq("firm_id", firm_id).eq("client_id", client_id).execute().data or [])
    return customers, vendors, banks


def _default_opening_date(db, firm_id: str, client_id: str, customers: list[dict],
                          vendors: list[dict], banks: list[dict]) -> str:
    """Opening-balance date, in order of authority:

      1. the date the posted opening family already uses — one book, one opening
         date, and a later delta must not open a second one;
      2. the client's financial-year start;
      3. the earliest master opening_balance_date;
      4. April 1 of the current FY.

    (1) is ahead of (2) deliberately. Where they disagree the family is already
    posted and immutable, so matching it is the only way the opening position
    stays on a single date."""
    existing = None
    try:
        existing = _existing_opening_date(db, firm_id, client_id)
    except Exception as e:  # noqa: BLE001
        _logger.warning("opening_balance: existing-family date lookup failed: %s", e)
    if existing:
        return existing
    try:
        cl = db.table("clients").select("financial_year_start").eq("id", client_id).limit(1).execute()
        if cl.data and cl.data[0].get("financial_year_start"):
            return str(cl.data[0]["financial_year_start"])
    except Exception as e:
        _logger.warning("opening_balance: client FY-start lookup failed: %s", e)
    _logger.warning(
        "opening_balance: client %s has no financial_year_start — dating the opening "
        "entry from the earliest master record instead. That is a guess, and it is "
        "how an opening balance lands in the wrong financial year.", client_id)
    dates = [r.get("opening_balance_date") for r in (customers + vendors + banks)
             if r.get("opening_balance_date")]
    if dates:
        return str(min(dates))
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    fy_start = now.year if now.month >= 4 else now.year - 1
    return f"{fy_start}-04-01"


AR, AP, BANK = "ar", "ap", "bank"
ALL_LEGS = frozenset({AR, AP, BANK})


def _leg_accounts(db, firm_id: str, client_id: str, banks: list[dict]) -> dict[str, str]:
    """{account_id: leg} for every account the opening family can touch.

    Resolved whether or not the leg currently carries a balance, because a STALE
    balance has to be attributable too — the Trade Payables drift that started
    this was on a leg whose masters had all gone to zero. An account that cannot
    be attributed stays out of the map, and a scoped call therefore leaves it
    alone: not touching something is always the safe failure here.
    """
    legs: dict[str, str] = {}
    for pattern, key, leg in (("%Trade Receivable%", "ar", AR),
                              ("%Trade Payable%", "ap", AP),
                              ("%Bank%", "bank", BANK)):
        try:
            legs[phase2_journal_service._find_account(
                db, firm_id, client_id, pattern, system_key=key)] = leg
        except Exception as e:  # noqa: BLE001 — an unresolvable leg is not an error
            _logger.debug("opening_balance: no %s account for client %s (%s)", leg, client_id, e)
    for b in banks:
        coa = b.get("coa_account_id")
        if coa:
            legs[coa] = BANK
    return legs


def _existing_opening_date(db, firm_id: str, client_id: str) -> Optional[str]:
    """The date the client's posted opening family already sits on.

    Every opening entry for a client must share ONE date. Migration-era books can
    carry an opening journal dated to the FY the books actually start in, while a
    master record added later carries whatever date the CA typed into that form —
    and taking the master's date put a bank opening into the PREVIOUS financial
    year, before the book's own opening entry. Whatever date the family already
    uses is the one every later delta belongs on."""
    rows = (db.table("journal_entries").select("entry_date")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("source_type", OPENING_SOURCE).is_("deleted_at", "null")
            .order("entry_date").limit(1).execute().data or [])
    return str(rows[0]["entry_date"])[:10] if rows else None


def _current_opening_net(db, firm_id: str, client_id: str) -> dict[str, int]:
    """Net (debit − credit) paise per account across the posted opening family
    (source_type='Opening'), i.e. the opening position the GL currently carries."""
    entries = (db.table("journal_entries").select("id")
               .eq("firm_id", firm_id).eq("client_id", client_id)
               .eq("source_type", OPENING_SOURCE).is_("deleted_at", "null")
               .execute().data or [])
    ids = [e["id"] for e in entries]
    net: dict[str, int] = {}
    if not ids:
        return net
    lines = (db.table("journal_lines").select("account_id, debit_paise, credit_paise")
             .in_("journal_entry_id", ids).execute().data or [])
    for l in lines:
        acc = l.get("account_id")
        net[acc] = net.get(acc, 0) + int(l.get("debit_paise") or 0) - int(l.get("credit_paise") or 0)
    return net


def _plan_opening(db, firm_id: str, client_id: str,
                  customers: list[dict], vendors: list[dict], banks: list[dict],
                  scope: Optional[frozenset] = None):
    """Compute the balanced delta lines that move the GL opening family from its
    current position to the master target. Returns (lines, figures). lines is empty
    when the GL already reconciles to the masters (no-op).

    `scope` restricts which legs may move — see the module docstring. None means
    the whole position, which is what the Opening Balances screen asks for."""
    ar_total = _sum_opening(customers)
    ap_total = _sum_opening(vendors)
    bank_total = _sum_opening(banks)

    # TARGET net per account (debit-positive), from the master records.
    non_obe: dict[str, int] = {}
    if ar_total:
        ar_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Trade Receivable%", system_key="ar")
        non_obe[ar_id] = non_obe.get(ar_id, 0) + ar_total
    if ap_total:
        ap_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Trade Payable%", system_key="ap")
        non_obe[ap_id] = non_obe.get(ap_id, 0) - ap_total          # liability: credit-normal
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
        non_obe[coa_id] = non_obe.get(coa_id, 0) + amt
    if generic_bank_total:
        bank_id = phase2_journal_service._find_account(db, firm_id, client_id, "%Bank%", system_key="bank")
        non_obe[bank_id] = non_obe.get(bank_id, 0) + generic_bank_total

    current = _current_opening_net(db, firm_id, client_id)

    if scope is None:
        # UNSCOPED — the whole position, byte-for-byte the behaviour the Opening
        # Balances screen has always had.
        target = dict(non_obe)
        if non_obe:
            obe_id = phase2_journal_service._find_account(
                db, firm_id, client_id, "%Opening Balance Equity%")
            target[obe_id] = target.get(obe_id, 0) - sum(non_obe.values())   # balancing contra

        # DELTA = target − current, per account. Balanced by construction (both
        # sides net to zero), so the adjusting entry always balances.
        lines: list[dict] = []
        for acc in sorted(set(target) | set(current), key=lambda a: str(a)):
            d = int(target.get(acc, 0)) - int(current.get(acc, 0))
            if d > 0:
                lines.append({"account_id": acc, "debit_paise": d, "credit_paise": 0,
                              "narration": "Opening balance"})
            elif d < 0:
                lines.append({"account_id": acc, "debit_paise": 0, "credit_paise": -d,
                              "narration": "Opening balance"})
    else:
        # SCOPED — only this leg moves. Every other account, in target or already
        # in the GL, is left exactly as it is, including drift: the screen that
        # owns that leg is the one entitled to reconcile it.
        legs = _leg_accounts(db, firm_id, client_id, banks)
        lines = []
        contra = 0
        for acc in sorted(set(non_obe) | set(current), key=lambda a: str(a)):
            if legs.get(acc) not in scope:
                continue
            d = int(non_obe.get(acc, 0)) - int(current.get(acc, 0))
            if d > 0:
                lines.append({"account_id": acc, "debit_paise": d, "credit_paise": 0,
                              "narration": "Opening balance"})
            elif d < 0:
                lines.append({"account_id": acc, "debit_paise": 0, "credit_paise": -d,
                              "narration": "Opening balance"})
            contra += d
        if contra:
            # Balanced through OBE, exactly as the unscoped path is. The invariant
            # this preserves is that OBE always equals minus the sum of every other
            # opening line, so scoped and unscoped runs cannot leave the family
            # unbalanced between them.
            obe_id = phase2_journal_service._find_account(
                db, firm_id, client_id, "%Opening Balance Equity%")
            lines.append({"account_id": obe_id,
                          "debit_paise": -contra if contra < 0 else 0,
                          "credit_paise": contra if contra > 0 else 0,
                          "narration": "Opening balance"})
        # contra == 0 with lines present means the leg's own deltas already cancel
        # across its accounts — balanced, so no contra line is needed.

    figures = {
        "ar_paise": ar_total, "ap_paise": ap_total, "bank_paise": bank_total,
        "opening_equity_paise": ar_total + bank_total - ap_total,
    }
    return lines, figures


def post_opening_balances(
    firm_id: str,
    client_id: str,
    opening_date: Optional[str] = None,
    created_by: Optional[str] = None,
    scope: Optional[frozenset] = None,
) -> dict:
    """Reconcile the GL opening family to the current master records by posting ONE
    balanced adjusting (delta) journal — append-only; never deletes/mutates a posted
    entry. Returns a summary; posted=False when nothing needed to change.

    `scope` is a subset of {'ar', 'ap', 'bank'}. Pass the leg you changed when
    calling this as a side effect of saving a master record; pass None only from
    the screen whose job is to reconcile the whole opening position. See the module
    docstring for what went wrong without it.
    """
    if _USE_MOCK:
        return {"posted": False, "mock": True, "reason": "no DB configured"}

    db = _db()
    customers, vendors, banks = _fetch_masters(db, firm_id, client_id)
    date = opening_date or _default_opening_date(db, firm_id, client_id, customers, vendors, banks)

    # FY-lock: refuse to (re)write opening balances into a locked year. Validate
    # BEFORE any mutation. (No prior journal is ever deleted, so a block is safe.)
    period_validation_service.validate_posting_date(firm_id, date)

    lines, figures = _plan_opening(db, firm_id, client_id, customers, vendors, banks, scope=scope)
    if not lines:
        return {"posted": False, "reason": "opening balances already reconciled",
                "opening_date": date, "scope": sorted(scope) if scope else None, **figures}

    reference = f"{OPENING_REFERENCE}-{uuid.uuid4().hex[:8].upper()}"
    # The journal says which leg moved and why. A posted entry cannot be amended
    # (Rule 3(1) of the Companies (Accounts) Rules 2014, and the DB triggers that
    # implement it), so several small adjustments are the correct shape here — but
    # a reader of the ledger is entitled to know what each one was reconciling.
    narration = ("Opening balances brought forward" if not scope
                 else f"Opening balances brought forward — {', '.join(sorted(scope))}")
    entry_id = phase2_journal_service._create_journal(
        db, firm_id, client_id, date, reference,
        narration, OPENING_ENTRY_TYPE, lines,
        is_posted=True, source_type=OPENING_SOURCE, created_by=created_by,
    )

    _logger.info("Posted opening-balance adjustment %s for client %s (scope=%s ar=%d ap=%d "
                 "bank=%d, %d line(s))", entry_id, client_id,
                 ",".join(sorted(scope)) if scope else "all",
                 figures["ar_paise"], figures["ap_paise"], figures["bank_paise"], len(lines))
    return {"posted": True, "journal_entry_id": entry_id, "opening_date": date,
            "scope": sorted(scope) if scope else None,
            "adjustment_lines": len(lines), **figures}


def opening_balance_status(firm_id: str, client_id: str) -> dict:
    """Report whether the GL opening family reconciles to the master records.

    needs_posting is true when a non-zero delta exists (nothing posted yet, figures
    changed since posting, or a stale/partial position). Lets the UI surface
    "₹X opening balances are not yet reflected in the ledger".
    """
    if _USE_MOCK:
        return {"needs_posting": False, "ar_paise": 0, "ap_paise": 0, "bank_paise": 0,
                "expected_total_paise": 0, "posted_total_paise": 0, "has_opening_journal": False}

    db = _db()
    customers, vendors, banks = _fetch_masters(db, firm_id, client_id)
    lines, figures = _plan_opening(db, firm_id, client_id, customers, vendors, banks)
    current = _current_opening_net(db, firm_id, client_id)
    posted_total = sum(v for v in current.values() if v > 0)   # gross debit currently carried

    return {
        "needs_posting": bool(lines),
        "ar_paise": figures["ar_paise"],
        "ap_paise": figures["ap_paise"],
        "bank_paise": figures["bank_paise"],
        "expected_total_paise": max(figures["ar_paise"] + figures["bank_paise"], figures["ap_paise"]),
        "posted_total_paise": posted_total,
        "has_opening_journal": bool(current),
    }
