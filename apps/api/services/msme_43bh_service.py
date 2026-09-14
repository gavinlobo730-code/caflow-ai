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
from domain.accounting import opening_documents as _opening
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
    """Every live bill — EXCEPT the ones carried over from the old system.

    s.43B(h) disallows a DEDUCTION claimed in this previous year. An opening
    bill's expense was claimed in a year whose return was prepared elsewhere, so
    adding it back here would tax the client on a deduction their own books
    never took. ⚠️ The other direction is NAMED rather than computed: an opening
    bill paid during this year could be an earlier year's disallowance coming
    back as a deduction under the same clause, and nothing here records whether
    it was disallowed — `_carried_over_named` reports them so the CA can decide
    (ACC-14, migration 391).
    """
    return _opening.without_carried_over(fetch_all(
        lambda: (db.table("purchase_bills")
                 .select("id, bill_no, bill_date, vendor_id, status, "
                         "total_paise, taxable_amount_paise, tds_paise, "
                         "ineligible_itc_igst_paise, ineligible_itc_cgst_paise, "
                         "ineligible_itc_sgst_paise, is_opening")
                 .eq("firm_id", firm_id).eq("client_id", client_id)
                 .in_("status", list(LIVE_STATUSES))),
        label="msme_43bh.purchase_bills"))


def _vendors(db, firm_id: str, client_id: str) -> dict:
    rows = fetch_all(
        lambda: (db.table("vendors")
                 .select("id, name, msme_status, msmed_agreement_days")
                 .eq("firm_id", firm_id).eq("client_id", client_id)),
        label="msme_43bh.vendors")
    return {str(r.get("id")): r for r in rows}


def _payments(db, firm_id: str, bill_ids: list) -> dict:
    """What was paid against each bill, with the DATE the money moved.

    A PAYMENT SETTLES A BILL IN ONE OF TWO SHAPES AND THIS READS BOTH. The
    multi-bill engine (`purchase_payment_service.create_payment_core`, migration
    226) writes a `purchase_payment_allocations` row per bill and leaves
    `purchase_payments.purchase_bill_id` NULL; the single-bill path
    (`routers/purchase_payments.create_purchase_payment`, which is what the
    Purchases screen and the bill drawer have always posted to) writes that
    column and NO allocation row. Reading only the bridge table therefore saw
    nothing at all for a bill paid the ordinary way — and §43B(h) disallows the
    deduction for a sum payable to a micro or small enterprise that was not
    ACTUALLY PAID within the MSMED §15 limit, so a bill paid on time was added
    back to taxable income. Wrong in the direction that costs the client money,
    and invisible, because "no payment found" and "paid late" produce the same
    disallowance.

    The date is on `purchase_payments`, not on the allocation, so the two are
    read together. A VOIDED allocation is a reversed payment and did not settle
    anything — counting it would show a bill as paid in time that was never
    paid at all. The single-bill shape's twin of that is `is_reversed` on the
    payment row itself (`reversal_service.reverse_payment` branches on exactly
    the same column this function does), and both filters run in PYTHON: a row
    lacking the key must read as NOT voided and NOT reversed, which
    `.eq(..., False)` gets backwards.

    A legacy single-bill payment settles the WHOLE of itself against its bill —
    that is what `_claim_bill_outstanding` reserved when it was recorded — so
    `amount_paise` is its allocated figure.
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
    legacy = [p for p in fetch_all(
        lambda: (db.table("purchase_payments")
                 .select("id, purchase_bill_id, payment_date, amount_paise, is_reversed")
                 .eq("firm_id", firm_id).in_("purchase_bill_id", bill_ids)),
        label="msme_43bh.single_bill_payments") if not p.get("is_reversed")]
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
    for p in legacy:
        out.setdefault(str(p.get("purchase_bill_id")), []).append(
            rule.Payment(paid_on=_iso(p.get("payment_date")),
                         amount_paise=int(p.get("amount_paise") or 0)))
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


def _carried_over_bills(db, firm_id: str, client_id: str) -> list[dict]:
    """The opening bills, so the answer can NAME what it left out."""
    rows = fetch_all(
        lambda: (db.table("purchase_bills")
                 .select("id, bill_no, bill_date, vendor_id, total_paise, "
                         "is_opening")
                 .eq("firm_id", firm_id).eq("client_id", client_id)
                 .in_("status", list(LIVE_STATUSES))),
        label="msme_43bh.carried_over_bills")
    return [
        {"bill_id": str(r.get("id")), "bill_no": r.get("bill_no"),
         "bill_date": str(r.get("bill_date") or "")[:10] or None,
         "vendor_id": r.get("vendor_id"),
         "total_paise": int(r.get("total_paise") or 0)}
        for r in rows if _opening.carried_over(r)
    ]


def for_financial_year(db, firm_id: str, client_id: str,
                       financial_year: str) -> dict:
    """The §43B(h) working for one previous year.

    Every live bill is read, not only the year's own: an EARLIER year's bill
    paid late during this year comes back as a deduction now, and a bill of
    this year paid next year is disallowed now. Both need the whole ledger.
    """
    rows = _bills(db, firm_id, client_id)
    carried_over = _carried_over_bills(db, firm_id, client_id)
    vendors = _vendors(db, firm_id, client_id)
    pays = _payments(db, firm_id, [str(r.get("id")) for r in rows])
    capitalised = _capitalised(db, firm_id, client_id)
    # THE DAY MSMED §15 ACTUALLY RUNS FROM, where the books hold one (PUR-25,
    # migration 393). §2(b)'s Explanation makes the day of acceptance the day
    # of ACTUAL DELIVERY — a goods receipt — or, where the buyer objected in
    # writing, the day the objection was removed. Read ONCE for the whole
    # client rather than per bill: this walks every live bill, and a per-bill
    # lookup would be a Singapore-to-Mumbai round trip each.
    #
    # A bill with no order, or an order with no receipt, is simply absent and
    # `section_43b_h.compute` falls back to the bill date, saying so on that
    # bill rather than on every answer.
    from services.purchase_cycle_service import acceptance_dates_by_bill
    accepted = acceptance_dates_by_bill(db, firm_id, client_id)

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
            acceptance_date=_iso(accepted.get(str(r.get("id")))),
        ))

    # Oldest first — a reader following the year through wants them in order.
    # The key is coalesced because bill_date is read through _iso and can be
    # None, and comparing None to a date raises TypeError in Python where
    # Postgres sorted it happily.
    bills.sort(key=lambda b: (b.bill_date or date.min, b.bill_no or ""))

    out = rule.compute(bills, financial_year=financial_year).to_dict()
    out["source"] = ("derived from purchase_bills, purchase_payment_allocations, "
                     "vendors.msme_status and goods_receipt_notes.received_on")
    # THE OPENING BILLS ARE NAMED, NOT COUNTED (ACC-14, migration 391). They are
    # out of the computation because their expense was claimed in a year whose
    # return was prepared elsewhere — but s.43B(h)'s other direction is that an
    # earlier year's disallowance ACTUALLY PAID during this year comes back as a
    # deduction now, and nothing on a carried-over bill records whether it was
    # disallowed. A nil here would read as "none", so the answer says which
    # bills it could not speak for.
    if carried_over:
        out["carried_over_bills"] = carried_over
        out.setdefault("gaps", []).append(
            f"{len(carried_over)} bill(s) carried over from the system this "
            f"client migrated from are outside this computation: the deduction "
            f"was claimed in a year whose return was prepared elsewhere. If any "
            f"of them was disallowed under s.43B(h) that year and has been paid "
            f"during this one, it comes back as a deduction now — a fact these "
            f"books do not hold.")
    out["ca_review_required"] = True
    return out
