"""
The FY aggregate for a deduction somebody types in, rather than one a bill made.

WHY THIS EXISTS
    resolve_tds needs two numbers to apply the s.194 aggregate limb correctly:
    what this payee was already credited under this section this year, and what
    was already withheld from them. CLAUDE.md is explicit that passing the
    first without the second "re-charges the growing aggregate on every later
    bill".

    routers/purchase_bills.py already computes that pair for a BILL, keyed on
    `vendor_id`. A deduction entered on the /tds screen has no vendor — it has
    a name and a PAN — so the bill path's query cannot answer for it.

WHAT IT COUNTS, AND WHAT IT DELIBERATELY DOES NOT
    Manual rows only: `tds_deductions` where `purchase_bill_id IS NULL`.

    (A CORRECTION OF 6-11-2026, said here because the sentence above is the one everybody reads: since migration 358 a vendor ADVANCE writes a register row too,
    with `purchase_payment_id` set and `purchase_bill_id` NULL, so "NULL bill id" is not "typed". `written_by_a_document` is the question for that, and the
    statement's note and the doors that correct or remove a row ask it. The aggregate below still asks `purchase_bill_id` alone, so an advance's row counts into
    a payee's typed total. Whether it should is part of the unification (POST-A-078); saying so moves no figure.)

    Bill-sourced rows are EXCLUDED on purpose, and not because they do not
    matter. services/tds_register_service.sync_for_bill upserts a row for every
    RECEIVED bill, while the bill path's own aggregate reads `purchase_bills`
    and counts DRAFTS as well (IT Act s.194C(5) charges on sums "credited or
    paid or likely to be credited"). Counting both sources here would count a
    received bill twice, and counting `tds_deductions` alone would drop the
    drafts the bill path is careful to include.

    SO THE TWO REGISTERS DO NOT YET SHARE AN AGGREGATE, and that is a real gap
    with a real cost. A CA who records Rs.30,000 of s.194J on the /tds screen
    and then enters four Rs.30,000 purchase bills for the same payee gets the
    aggregate limb applied to the bills alone: the manual Rs.30,000 does not
    push the year over the Rs.50,000 threshold, and the s.200 credit for
    anything withheld on it is not given back.

    Unifying them means keying both halves on the PAN and taking bills from
    `purchase_bills` (for the drafts) unioned with manual `tds_deductions`
    rows. That is the right answer and it changes the bill path, which is
    delicately argued and heavily tested, so it is NOT done here. It is named
    instead — in this docstring, in the endpoint's response as a gap, and in
    the phase plan — because a number that is wrong in a knowable way and says
    so is not the same thing as one that is silently wrong.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

from domain.tds.residency import GAP_RESIDENT_RATES_UNVERIFIED
from domain.tds.tds_computer import has_pan

# A PAN is five letters, four digits and a letter. Nothing else is a key for a payee (see usable_pan_key).
_PAN_SHAPE = re.compile(r"[A-Z]{5}[0-9]{4}[A-Z]")


def fy_bounds(on: date) -> tuple[str, str]:
    """The Indian financial year containing `on`, as ISO dates. 1 Apr - 31 Mar."""
    start_year = on.year if on.month >= 4 else on.year - 1
    return f"{start_year}-04-01", f"{start_year + 1}-03-31"


def fy_label(on: date) -> str:
    """'2026-27' for the FY containing `on`."""
    start_year = on.year if on.month >= 4 else on.year - 1
    return f"{start_year}-{str(start_year + 1)[2:]}"


def written_by_a_document(row: dict) -> bool:
    """Whether a purchase BILL or a vendor ADVANCE wrote this register row, as against a CA typing it on the TDS screen.

    Two kinds of row are not typed: one a bill wrote (`purchase_bill_id`, migration 307) and one an advance wrote (`purchase_payment_id`, migration 358, where a CHECK
    allows at most one of the two). Both are rebuilt from their document and both are ON the statement built from the books, so the reader of the typed register
    (the statement's note of what it leaves out) and the doors that change a typed row (correct, remove) ask this one question. Asking `purchase_bill_id` alone, as
    this module's docstring and its aggregate below still do, takes an advance's row for a typed one.
    """
    return bool(row.get("purchase_bill_id") or row.get("purchase_payment_id"))


def usable_pan_key(deductee_pan: Optional[str]) -> Optional[str]:
    """The PAN as a key for a payee's year, or None where it cannot be one.

    A PAN identifies a payee to the department (Form 26Q's deductee annexure is a list of PANs), so it is what rows are pooled on. It is a key only
    if it is a REAL one: five letters, four digits and a letter. A blank is not, and neither is `PANNOTAVBL` or `PANAPPLIED` (the placeholders a
    deductee without a PAN is filed under) nor text that is not a PAN at all: the typed door takes whatever is typed, and every payee typed under the
    same placeholder would otherwise be pooled as one person. Two strangers' payments pushing each other over a threshold is a wrong deduction, and
    the tax already withheld from one being credited to the other is a wrong credit (POST-A-078).
    """
    pan = (deductee_pan or "").strip().upper()
    if not has_pan(pan) or not _PAN_SHAPE.fullmatch(pan):
        return None
    return pan


def prior_manual_aggregate(
    db, *, firm_id: str, client_id: str, section: str,
    deductee_pan: Optional[str], on: date, exclude_id: Optional[str] = None,
) -> tuple[int, int]:
    """(taxable already credited, tax already withheld) for this payee, this
    section, this FY — from MANUAL register rows only.

    Keyed on the PAN, because that is what identifies a payee to the department
    (Form 26Q's deductee annexure is a list of PANs). A row with NO usable PAN
    (`usable_pan_key`: blank, a placeholder, or not a PAN) cannot be aggregated
    with anything: two unrelated payees both missing a PAN are not the same
    person, and treating them as one would push a stranger's payments over
    another's threshold. So it returns (0, 0) — first payment behaviour — which
    cannot over-deduct from a stranger and CAN under-deduct from one payee: twelve
    Rs 15,000 commissions to the same agent typed under a placeholder were each
    "the first of the year" and the second used to be charged. The CALLER says so
    (the gap `tds_aggregate_not_read_without_a_pan` in the answer, and
    `aggregate_tested` false): a nil for "not looked for" must not read as a nil
    for "none". Under-deduction is the costly direction (s.40(a)(ia)); keying such
    a payee by name is a decision, not made here (POST-A-078).
    """
    pan = usable_pan_key(deductee_pan)
    if not (firm_id and client_id and section and pan):
        return 0, 0
    start, end = fy_bounds(on)
    # BY PARENT SECTION, for the same reason routers/purchase_bills.py is:
    # s.194I and s.194J have limbs with their own rate, and the FY aggregate
    # the statute's proviso speaks of is the SECTION's. Filtered in Python
    # because a prefix match would also catch s.194IA, which is a different
    # section entirely.
    from domain.tds.section_rates import parent_of
    parent = parent_of(section)
    rows = (db.table("tds_deductions")
            .select("id, payment_amount_paise, tds_paise, purchase_bill_id, section")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("deductee_pan", pan)
            .gte("transaction_date", start).lte("transaction_date", end)
            .execute().data) or []
    rows = [r for r in rows if parent_of(r.get("section") or "") == parent]
    earlier = [r for r in rows
               if r.get("purchase_bill_id") is None and r.get("id") != exclude_id]
    return (sum(int(r.get("payment_amount_paise") or 0) for r in earlier),
            sum(int(r.get("tds_paise") or 0) for r in earlier))


# The gap this module knowingly leaves, reported to the caller rather than
# hidden. Read by routers/tds_workspace.py and surfaced on the screen.
GAP_REGISTERS_NOT_UNIFIED = "tds_aggregate_excludes_purchase_bills"
#: The payee has no usable PAN, so the typed register could not look for the year's earlier payments to it at all (POST-A-078).
GAP_AGGREGATE_NOT_READ_WITHOUT_A_PAN = "tds_aggregate_not_read_without_a_pan"
GAP_MESSAGES = {
    # The bill and advance paths raise this gap too (domain/tds/residency.py has their sentence, which says "bill"); this door's is the same sentence about a deduction.
    GAP_RESIDENT_RATES_UNVERIFIED: (
        "The TDS rates and thresholds for this deduction's financial year have not been confirmed against that year's Finance Act — for a year the registry does not "
        "hold at all, another year's figures were used. Finance Act 2025 RAISED most thresholds, so an earlier year is likely UNDER-deducted, and s.40(a)(ia) "
        "disallows 30% of the expenditure. Check this deduction against that year's own rates before the quarter is filed."
    ),
    GAP_AGGREGATE_NOT_READ_WITHOUT_A_PAN: (
        "No usable PAN is recorded for this payee, so the year's earlier payments to the same payee were not looked for. This payment is "
        "charged as if it were the payee's first of the year, and that says nothing about what the year's total is."
    ),
    GAP_REGISTERS_NOT_UNIFIED: (
        "This year's aggregate for this payee counts hand-entered deductions "
        "only. Purchase bills for the same payee are held in a separate "
        "register and are not added in, so a section with an annual threshold "
        "may not have been triggered yet."
    ),
}
