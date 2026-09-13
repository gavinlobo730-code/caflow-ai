"""IT Act §43B(h) — the working, DERIVED from the purchase ledger.

WHAT WAS WRONG (PUR-15)

    `/accounting/msme-tracker` asked the CA to type each bill in again —
    supplier name, invoice number, invoice date, amount, whether the agreement
    was written, and the payment date — into `public.msme_payments`, over
    PostgREST, and then computed the whole statutory rule in TypeScript.

    Three things follow from that and all three are defects. The figure is a
    RE-KEYING of data the books already hold, so it drifts the moment a bill is
    corrected or a payment is recorded through the ordinary path. `rbac()`
    never runs on a direct PostgREST write. And a §43B(h) disallowance decided
    in the browser is business logic in the frontend, which this codebase does
    not do.

WHAT THIS DOES INSTEAD

    Reads `purchase_bills`, their `purchase_payment_allocations`, and
    `vendors.msme_status` — and hands them to `domain/income_tax/section_43b_h`,
    which holds the rule. Nothing is typed twice and nothing drifts: correct a
    bill and the disallowance changes with it.

    `public.msme_payments` is NOT read and NOT written. Dropping it is a
    migration and an owner decision; leaving it unread is neither.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. This computes a working for the
    # tax computation. It writes nothing and files nothing.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from core.db_paging import fetch_all
from domain.income_tax import section_43b_h as rule

_logger = logging.getLogger("caflow.tax.msme_43bh")

#: A bill is a §43B(h) candidate only once it is a real liability. A draft is
#: not payable and a cancelled one is not owed, so neither can be late.
LIVE_STATUSES = ("received", "partially_paid", "paid")


class MSME43BHError(Exception):
    """The working cannot be built."""


def _iso(value) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _bills(db, firm_id: str, client_id: str) -> list[dict]:
    return fetch_all(
        lambda: (db.table("purchase_bills")
                 .select("id, bill_no, bill_date, vendor_id, status, "
                         "total_paise, taxable_amount_paise, tds_paise, "
                         "ineligible_itc_igst_paise, ineligible_itc_cgst_paise, "
                         "ineligible_itc_sgst_paise")
                 .eq("firm_id", firm_id).eq("client_id", client_id)
                 .in_("status", list(LIVE_STATUSES))),
        label="msme_43bh.purchase_bills")


def _vendors(db, firm_id: str, client_id: str) -> dict:
    rows = fetch_all(
        lambda: (db.table("vendors")
                 .select("id, name, msme_status, msmed_agreement_days")
                 .eq("firm_id", firm_id).eq("client_id", client_id)),
        label="msme_43bh.vendors")
    return {str(r.get("id")): r for r in rows}


def _payments(db, firm_id: str, bill_ids: list) -> dict:
    """Allocations against each bill, with the DATE the money moved.

    The date is on `purchase_payments`, not on the allocation, so the two are
    read together. A VOIDED allocation is a reversed payment and did not settle
    anything — counting it would show a bill as paid in time that was never
    paid at all.
    """
    if not bill_ids:
        return {}
    allocs = fetch_all(
        lambda: (db.table("purchase_payment_allocations")
                 .select("id, purchase_payment_id, purchase_bill_id, "
                         "allocated_paise, is_voided")
                 .in_("purchase_bill_id", bill_ids)),
        label="msme_43bh.allocations")
    allocs = [a for a in allocs if not a.get("is_voided")]
    pay_ids = sorted({str(a.get("purchase_payment_id")) for a in allocs
                      if a.get("purchase_payment_id")})
    dates: dict = {}
    if pay_ids:
        for p in fetch_all(
                lambda: (db.table("purchase_payments")
                         .select("id, payment_date")
                         .eq("firm_id", firm_id).in_("id", pay_ids)),
                label="msme_43bh.payments"):
            dates[str(p.get("id"))] = _iso(p.get("payment_date"))
    out: dict = {}
    for a in allocs:
        out.setdefault(str(a.get("purchase_bill_id")), []).append(
            rule.Payment(paid_on=dates.get(str(a.get("purchase_payment_id"))),
                         amount_paise=int(a.get("allocated_paise") or 0)))
    return out


def _capitalised(db, firm_id: str, client_id: str) -> set:
    """Bills that became a fixed asset (migration 343's `purchase_bill_id`).

    Nothing was DEDUCTED on those — the cost sits on the balance sheet and only
    the depreciation is claimed — so §43B(h) has nothing to disallow. The
    MSMED §15 obligation to pay is unaffected, which is why they are reported
    rather than dropped.
    """
    rows = fetch_all(
        lambda: (db.table("fixed_assets").select("id, purchase_bill_id")
                 .eq("firm_id", firm_id).eq("client_id", client_id)
                 .is_("deleted_at", "null")
                 .not_.is_("purchase_bill_id", "null")),
        label="msme_43bh.fixed_assets")
    return {str(r.get("purchase_bill_id")) for r in rows
            if r.get("purchase_bill_id")}


def for_financial_year(db, firm_id: str, client_id: str,
                       financial_year: str) -> dict:
    """The §43B(h) working for one previous year.

    Every live bill is read, not only the year's own: an EARLIER year's bill
    paid late during this year comes back as a deduction now, and a bill of
    this year paid next year is disallowed now. Both need the whole ledger.
    """
    rows = _bills(db, firm_id, client_id)
    vendors = _vendors(db, firm_id, client_id)
    pays = _payments(db, firm_id, [str(r.get("id")) for r in rows])
    capitalised = _capitalised(db, firm_id, client_id)

    bills = []
    for r in rows:
        v = vendors.get(str(r.get("vendor_id"))) or {}
        blocked = (int(r.get("ineligible_itc_igst_paise") or 0)
                   + int(r.get("ineligible_itc_cgst_paise") or 0)
                   + int(r.get("ineligible_itc_sgst_paise") or 0))
        bills.append(rule.Bill(
            bill_id=str(r.get("id")),
            bill_no=r.get("bill_no"),
            vendor_id=r.get("vendor_id"),
            vendor_name=str(v.get("name") or r.get("vendor_id") or "—"),
            msme_status=v.get("msme_status"),
            bill_date=_iso(r.get("bill_date")),
            total_paise=int(r.get("total_paise") or 0),
            # What is CLAIMED: the taxable value, plus tax §17(5) blocked
            # (which is not credit and so is expensed or capitalised).
            # Creditable GST is not a deduction and is deliberately out.
            deductible_paise=int(r.get("taxable_amount_paise") or 0) + blocked,
            tds_paise=int(r.get("tds_paise") or 0),
            agreed_days=v.get("msmed_agreement_days"),
            payments=tuple(pays.get(str(r.get("id"))) or ()),
            capitalised=str(r.get("id")) in capitalised,
        ))

    # Oldest first — a reader following the year through wants them in order.
    # The key is coalesced because bill_date is read through _iso and can be
    # None, and comparing None to a date raises TypeError in Python where
    # Postgres sorted it happily.
    bills.sort(key=lambda b: (b.bill_date or date.min, b.bill_no or ""))

    out = rule.compute(bills, financial_year=financial_year).to_dict()
    out["source"] = ("derived from purchase_bills, purchase_payment_allocations "
                     "and vendors.msme_status")
    out["ca_review_required"] = True
    return out
