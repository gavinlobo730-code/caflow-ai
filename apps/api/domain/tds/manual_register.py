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

WHAT IT COUNTS, SINCE 15-11-2026 (POST-A-078)
    A typed deduction may NAME ITS SUPPLIER (`tds_deductions.vendor_id`, migration 594). One that does is in that supplier's year, with its
    purchase bills and advances (services/vendor_tds.aggregate_so_far), and its tax is the bill path's resolver's: the s.197 certificate,
    the s.194A class and the cap at the payment apply to it as they do to a bill. This module is what is LEFT: the year of a typed
    deduction that names NO supplier (a dividend, a partner's remuneration, a winning, a landowner's compensation are paid to people who
    are not suppliers, and a client whose books are elsewhere may have none). It counts the other typed rows for the same PAN that name
    none, and not a row a bill or an advance wrote (`written_by_a_document`) nor a typed row that names a supplier, either of which is
    counted in a supplier's year and would be counted twice here. Keyed on the PAN, because that is what identifies a payee to the
    department (Form 26Q's deductee annexure is a list of PANs), and never on a placeholder (`usable_pan_key`).

    BEFORE 15-11-2026 the two registers shared no aggregate at all: a Rs 30,000 professional fee typed here and four Rs 30,000 bills for
    the same payee each judged the s.194J yearly threshold on their own half, and the tax withheld on one half was not credited on the
    other. A typed row with no supplier still does not meet the bills, and the answer says so (GAP_NO_SUPPLIER).
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
    (the statement's note of what it leaves out), the doors that change a typed row (correct, remove), the typed rows' own aggregate below and the supplier's year
    (`services/vendor_tds._typed_rows_for`) ask this one question. Asking `purchase_bill_id` alone takes an advance's row for a typed one.
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
    from core.db_paging import fetch_all
    rows = fetch_all(lambda: (db.table("tds_deductions")
                              .select("id, payment_amount_paise, tds_paise, purchase_bill_id, purchase_payment_id, vendor_id, section")
                              .eq("firm_id", firm_id).eq("client_id", client_id)
                              .eq("deductee_pan", pan)
                              .gte("transaction_date", start).lte("transaction_date", end)))
    rows = [r for r in rows if parent_of(r.get("section") or "") == parent]
    # ONLY TYPED ROWS THAT NAME NO SUPPLIER (POST-A-078). A row a bill or an advance wrote is that document's, and a typed row that names a
    # supplier is in that supplier's year (services/vendor_tds.aggregate_so_far); counting either here would count it twice. Before
    # 15-11-2026 this asked `purchase_bill_id` alone, so an advance's register row was counted into a payee's typed total.
    earlier = [r for r in rows
               if not written_by_a_document(r) and not r.get("vendor_id") and r.get("id") != exclude_id]
    return (sum(int(r.get("payment_amount_paise") or 0) for r in earlier),
            sum(int(r.get("tds_paise") or 0) for r in earlier))


def same_name_key(deductee_name: Optional[str]) -> Optional[str]:
    """The typed name folded for COMPARISON only: case and runs of spaces do not tell two payees apart. None for a blank name."""
    folded = " ".join(str(deductee_name or "").split()).casefold()
    return folded or None


def same_name_without_a_pan(
    db, *, firm_id: str, client_id: str, section: str, deductee_name: Optional[str], on: date, exclude_id: Optional[str] = None,
) -> tuple[int, int, int]:
    """(how many, taxable, tax) of the year's earlier TYPED deductions under the same parent section that name no supplier, carry no
    usable PAN and were typed under the same name (`same_name_key`) as this one (POST-A-078, the second decision).

    THE DECISION: A NAME IS NEVER A KEY, AND A SAME-NAME PAYMENT IS NAMED, NOT ADDED. Two payees may share a name and one payee may be
    typed under two spellings, so adding a year up by the name would push one stranger's payments over another's threshold (a wrong
    deduction and a wrong credit, the reason `usable_pan_key` exists) and pooling by a spelling would miss the other half. The charge
    therefore stays the first-payment charge `prior_manual_aggregate` gives a payee with no key, and these figures go to the CA in a
    sentence, with the two ways to make the year add up: pick the supplier, or record the payee's PAN. Read only for a payee with no
    supplier and no usable PAN; a payee with a key has its year read by the key."""
    key = same_name_key(deductee_name)
    if not (firm_id and client_id and section and key):
        return 0, 0, 0
    start, end = fy_bounds(on)
    from domain.tds.section_rates import parent_of
    parent = parent_of(section)
    from core.db_paging import fetch_all
    rows = fetch_all(lambda: (db.table("tds_deductions")
                              .select("id, deductee_name, deductee_pan, payment_amount_paise, tds_paise, purchase_bill_id, "
                                      "purchase_payment_id, vendor_id, section")
                              .eq("firm_id", firm_id).eq("client_id", client_id)
                              .gte("transaction_date", start).lte("transaction_date", end)))
    same = [r for r in rows
            if r.get("id") != exclude_id and not written_by_a_document(r) and not r.get("vendor_id")
            and usable_pan_key(r.get("deductee_pan")) is None and parent_of(r.get("section") or "") == parent
            and same_name_key(r.get("deductee_name")) == key]
    return (len(same), sum(int(r.get("payment_amount_paise") or 0) for r in same),
            sum(int(r.get("tds_paise") or 0) for r in same))


def same_name_sentence(count: int, taxable_paise: int, tds_paise: int) -> str:
    """The sentence for `GAP_SAME_NAME_WITHOUT_A_PAN`, with the figures `same_name_without_a_pan` found."""
    from domain.money_sentence import rupee_text
    payments = "payment" if count == 1 else "payments"
    return (f"This financial year already holds {count} other {payments} typed under the same payee name and section with no supplier "
            f"and no PAN, of {rupee_text(taxable_paise)} with {rupee_text(tds_paise)} withheld. They were NOT added to this payment's year, "
            "because a name does not identify a payee: two payees can share one. If they are the same payee, pick the supplier or record "
            "the payee's PAN on each, and the year is added up.")


# The gaps a typed deduction can carry, reported to the caller rather than hidden. Read by routers/tds_workspace.py and surfaced on the screen.
#: The deduction names no supplier, so its year is the other typed deductions for its PAN that name none, and no supplier's bills (POST-A-078).
GAP_NO_SUPPLIER = "tds_deduction_names_no_supplier"
#: A bill or an advance of the same supplier carries the same day and the same taxable amount: possibly one payment entered twice.
GAP_MIRRORS_A_DOCUMENT = "tds_deduction_mirrors_a_document"
#: The supplier is recorded as not subject to TDS on its bills; the deduction was recorded as typed, under its own section.
GAP_SUPPLIER_NOT_SUBJECT_TO_TDS = "tds_supplier_recorded_not_subject_to_tds"
#: The year's tax due at this payment is more than the payment, so the payment's amount is withheld and the rest falls on the next payment.
GAP_CAPPED_AT_THE_PAYMENT = "tds_deduction_capped_at_the_payment"
#: The payee has no usable PAN, so the typed register could not look for the year's earlier payments to it at all (POST-A-078).
GAP_AGGREGATE_NOT_READ_WITHOUT_A_PAN = "tds_aggregate_not_read_without_a_pan"
#: Earlier typed payments of the year carry the same payee name with no supplier and no PAN; named with their figures and not added (POST-A-078).
#: Its sentence carries figures, so it is `same_name_sentence` and not in `GAP_MESSAGES`.
GAP_SAME_NAME_WITHOUT_A_PAN = "tds_same_name_payments_without_a_pan"
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
    GAP_NO_SUPPLIER: (
        "This deduction names no supplier, so its year is added up with the other deductions typed for this PAN that name none, and not "
        "with any supplier's purchase bills or advances. Pick the supplier to count it in that supplier's year."
    ),
    GAP_MIRRORS_A_DOCUMENT: (
        "A purchase bill or an advance of this supplier carries the same day and the same amount. If it is the same payment, recording this "
        "deduction counts it twice in the supplier's year: leave it unrecorded, or remove the deduction or the document."
    ),
    GAP_SUPPLIER_NOT_SUBJECT_TO_TDS: (
        "This supplier is recorded as not subject to TDS on its bills. This deduction is worked out under the section chosen; correct the "
        "supplier's record if its bills should withhold too."
    ),
    GAP_CAPPED_AT_THE_PAYMENT: (
        "The year's tax due at this payment is more than the payment itself, so only the payment's amount is withheld here. The rest is due "
        "on the next payment or bill to this payee, which credits what was withheld (s.200)."
    ),
}
