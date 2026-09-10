"""
What is withheld on a sum credited or paid to a vendor, and on what aggregate.

WHY THIS MODULE EXISTS
    Every §194-series charging section, and §195, charges

        "at the time of credit of such sum to the account of the [payee] or at
         the time of PAYMENT thereof ... whichever is EARLIER"

    — two events, one charge. Until this module existed the code knew only one
    of them: `routers/purchase_bills.py` held both resolvers as private
    functions, and the payment path had no TDS logic at all (PUR-10). An
    advance to a contractor is the earlier event and withheld nothing.

    Reaching the same engine from the payment path meant the resolvers could
    not stay private to the bill router. They are MOVED here rather than
    copied: two implementations of a withholding rule drift, and the one that
    drifts is the one nobody reads.

WHAT IS AND IS NOT HERE
    Here: which section charges (residency), the year's aggregate, the rate,
    the §200 credit, and the sentence saying why. Not here: what the caller
    does with the figure — the journal legs, the register row, the columns.
    Those differ between a bill and a payment and belong to their own paths.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from fastapi import HTTPException

from core.ist_clock import fy_bounds as _fy_bounds_from_label, ist_fy_label

# NO MOCK-MODE FLAG HERE, DELIBERATELY. The routers carry one because they
# decide whether to touch a database at all; by the time this module is called
# the decision is already made and arrives as `db`, which is None in mock mode
# (routers/purchase_bills._resolve_vendor_and_interstate sets it that way). A
# second flag would be a second answer to the same question, and the test
# harness flips the routers' flag one module at a time — so a copy here would
# read "mock" while its caller was reading a real FakeDB, and the year's
# aggregate would silently come back empty.


# ── The financial year a dated event falls in ──────────────────────────────
# Both helpers take the DATE the money moved, not a label: a bill entered late
# for a prior year is withheld at that year's law, and the rate registries
# default to the current FY when they are given no year at all.

def fy_label(on_date) -> Optional[str]:
    """'YYYY-YY' for the FY a date falls in, or None where the date is unusable.

    None matters. `rates_for()` substitutes LATEST_VERIFIED_FY for a year it
    does not hold, so a caller that passes None gets today's law — which is the
    documented behaviour of the resident path and is why this returns None
    rather than raising.
    """
    try:
        d = datetime.strptime(str(on_date)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError, KeyError):
        return None
    return ist_fy_label(d)


def fy_bounds(on_date) -> tuple[str, str]:
    """(1 April, 31 March) of the financial year a date falls in."""
    label = fy_label(on_date)
    if label is None:
        raise ValueError(f"not a date: {on_date!r}")
    return _fy_bounds_from_label(label)


@dataclass(frozen=True)
class Aggregate:
    """This vendor's year so far under one charging section.

    base_paise and tds_paise are the two halves of ONE figure about the year:
    `resolve_tds` takes `fy_prior_taxable_paise` AND `fy_prior_tds_paise`, and
    a caller passing the first without the second re-charges the growing
    aggregate on every later document (CLAUDE.md).
    """
    base_paise: int = 0
    tds_paise: int = 0
    unadjusted_advance_paise: int = 0


def aggregate_so_far(
    db, *, firm_id: str, vendor_id: str, section: Optional[str], on_date: str,
    exclude_bill_id: Optional[str] = None,
    exclude_payment_id: Optional[str] = None,
) -> Aggregate:
    """The year's aggregate credited or paid to this vendor under this section.

    TWO SOURCES, BECAUSE THE STATUTE HAS TWO EVENTS. Bills carry the credit
    side; `purchase_payments.tds_base_paise` carries the advance side — the
    UNALLOCATED part of a payment, which is the only part that was not already
    charged at a bill.

    EACH RUPEE ONCE. An advance and the bill that later absorbs it are the same
    expenditure, so counting both would charge it twice: a ₹5,00,000 advance
    followed by the ₹5,00,000 bill would be taxed on ₹10,00,000. A bill
    therefore adjusts against the advance pool and records what it took in
    `purchase_bills.tds_advance_adjusted_paise`, and `unadjusted_advance_paise`
    here is what the pool has left — advances charged, less what bills have
    already absorbed. Its own charged base is `taxable − adjusted`, which is
    what this function's `base_paise` already reflects for earlier bills.

    DRAFT BILLS COUNT ON BOTH SIDES, and that is deliberate. §194C(5) reaches
    sums "credited or paid or LIKELY to be credited", so a live draft is
    expected; and the credit side has to count the same documents the charge
    side does, or the draft inflates the base while contributing nothing to the
    credit and the bill over-deducts. Worked through: bill A received
    (₹1,00,000, withheld ₹10,000), bill B a live draft (₹1,00,000), bill C now
    (₹1,00,000). Charging C on ₹3,00,000 and crediting A+B withholds ₹10,000,
    so the ledger holds ₹20,000 against the ₹2,00,000 actually credited —
    correct. Crediting A alone withholds ₹20,000 and the ledger holds ₹30,000 —
    an over-deduction recoverable only by a refund claim.

    SOFT-DELETED BILLS DO NOT. They keep status "draft", so a `.neq("status",
    "cancelled")` filter alone still counted them toward the §194C aggregate
    and wrongly triggered a deduction on later bills.

    THE AGGREGATE IS THE SECTION'S PARENT, NOT THE CLAUSE'S. §194I and §194J
    each have limbs with their own rate — "194I(A)", "194J(A)" — and a vendor
    moved between limbs mid-year must not lose the year's running total, or the
    threshold is re-crossed and the §200 credit for what earlier documents
    withheld is stranded. So the queries filter by PARENT and the clause keys
    are narrowed in Python: PostgREST has no "starts with this section" that
    would not also match §194IA.
    """
    if db is None or not vendor_id or not section:
        return Aggregate()

    from domain.tds.section_rates import parent_of

    fy_start, fy_end = fy_bounds(on_date)
    label = fy_label(on_date)
    want_parent = parent_of(section, label)

    base = 0
    withheld = 0
    advance_charged = 0
    advance_absorbed = 0

    bills = (db.table("purchase_bills")
             .select("id, taxable_amount_paise, tds_paise, tds_section, "
                     "tds_advance_adjusted_paise")
             .eq("firm_id", firm_id).eq("vendor_id", vendor_id)
             .neq("status", "cancelled")
             .is_("deleted_at", "null")
             .gte("bill_date", fy_start).lte("bill_date", fy_end)
             .execute().data) or []
    for b in bills:
        if b.get("id") == exclude_bill_id:
            continue
        if parent_of(b.get("tds_section") or "", label) != want_parent:
            continue
        adjusted = int(b.get("tds_advance_adjusted_paise") or 0)
        # The bill's OWN charged base, which is what it was charged on: the
        # part it absorbed from an advance was charged when the advance was
        # paid and is already in the payments loop below.
        base += max(0, int(b.get("taxable_amount_paise") or 0) - adjusted)
        withheld += int(b.get("tds_paise") or 0)
        advance_absorbed += adjusted

    payments = (db.table("purchase_payments")
                .select("id, tds_base_paise, tds_paise, tds_section")
                .eq("firm_id", firm_id).eq("vendor_id", vendor_id)
                .gte("payment_date", fy_start).lte("payment_date", fy_end)
                .execute().data) or []
    for p in payments:
        if p.get("id") == exclude_payment_id:
            continue
        charged = int(p.get("tds_base_paise") or 0)
        if not charged:
            continue
        if parent_of(p.get("tds_section") or "", label) != want_parent:
            continue
        base += charged
        withheld += int(p.get("tds_paise") or 0)
        advance_charged += charged

    return Aggregate(
        base_paise=base,
        tds_paise=withheld,
        unadjusted_advance_paise=max(0, advance_charged - advance_absorbed),
    )


@dataclass(frozen=True)
class ResidentWithholding:
    """What the §194 series takes out of one bill or one advance."""
    tds_paise: int
    rate_bps: int
    why: str
    advance_adjusted_paise: int = 0


def resolve_resident_tds(
    vendor: dict, tds_section: Optional[str], taxable_paise: int, on_date: str,
    firm_id: str, db, exclude_bill_id: Optional[str] = None, *,
    exclude_payment_id: Optional[str] = None,
    adjust_against_advances: bool = False,
    event_noun: str = "bill",
) -> ResidentWithholding:
    """TDS on a sum credited or paid to a RESIDENT payee — the §194 series.

    MOVED here from routers/purchase_bills.py, where it was
    `_resolve_bill_resident_tds`, so the payment path can charge an advance
    through the same engine instead of a second copy of it.

    `adjust_against_advances` is the one thing a BILL does that an advance does
    not: absorb an earlier advance's charged base so the same expenditure is
    not taxed twice. See aggregate_so_far.
    """
    if not tds_section:
        raise HTTPException(
            status_code=422,
            detail="Vendor is marked TDS-applicable but has no TDS section set.",
        )
    from domain.tds.tds_computer import TDSComputer, is_company_pan, has_pan
    from domain.tds.residency import deduction_section_refusal
    from domain.tds.section_rates import rate_gap_for

    agg = aggregate_so_far(
        db, firm_id=firm_id, vendor_id=vendor.get("id"), section=tds_section,
        on_date=on_date, exclude_bill_id=exclude_bill_id,
        exclude_payment_id=exclude_payment_id,
    )
    fy_prior = agg.base_paise
    fy_prior_tds = agg.tds_paise
    # A bill absorbs so much of the outstanding advance pool as it can, and no
    # more than its own value. What it absorbs was charged when the advance was
    # paid, so it is not charged again here — it is already inside fy_prior.
    adjusted = (min(taxable_paise, agg.unadjusted_advance_paise)
                if adjust_against_advances else 0)
    own_base = max(0, taxable_paise - adjusted)
    # Resolve thresholds/rates for the FY the EVENT falls in, not "today" —
    # a bill entered late for a prior FY must use that year's law.
    event_fy = fy_label(on_date)
    try:
        _tds = TDSComputer().resolve_tds(
            section=tds_section,
            taxable_paise=own_base,
            fy_prior_taxable_paise=fy_prior,
            fy_prior_tds_paise=fy_prior_tds,
            is_company=is_company_pan(vendor.get("pan")),
            fy=event_fy,
            # IT Act §206AA: no real PAN on file floors the rate at
            # 20% (R3.10) — previously computed with zero PAN
            # awareness, silently under-deducting for no-PAN vendors.
            has_pan=has_pan(vendor.get("pan")),
        )
    except ValueError as ve:
        # The ENGINE's ValueError is the backstop, not the message. A vendor
        # created before models/parties.py started refusing an unanswerable
        # section still reaches here, and "Unknown TDS section '194IA'" is an
        # internal string with no statute and no next step. Ask the same rule
        # the vendor master asks, so the legacy row gets the same sentence.
        named = deduction_section_refusal(tds_section, event_fy)
        raise HTTPException(status_code=422, detail=named or str(ve))
    # Persist the rate ACTUALLY applied — 0 when below threshold (nothing
    # deducted), the section/payee rate when TDS was deducted (H6, §203 audit).
    #
    # `why` is NOT persisted and is for the preview: a sentence saying WHY this
    # figure. A number with no reason is a number a CA cannot check, and this
    # one moves with the year's running total — the same vendor and the same
    # amount deduct differently on the document that crosses the aggregate.
    # Composed here, from what the engine returned, rather than in the browser:
    # which facts matter is a statutory judgement, and the frontend holds none
    # of them.
    if not _tds.applies:
        why = (f"Nothing withheld: §{tds_section} does not charge this "
               f"{event_noun}. The year's payments to this payee under this "
               f"section so far are ₹{(fy_prior + own_base) // 100:,}.")
    elif fy_prior > 0:
        why = (f"§{tds_section} at {_tds.rate_pct:g}% on the year's aggregate of "
               f"₹{(fy_prior + own_base) // 100:,}, less ₹{fy_prior_tds // 100:,} "
               f"already withheld on earlier bills and advances (§200).")
    else:
        why = f"§{tds_section} at {_tds.rate_pct:g}% on ₹{own_base // 100:,}."
    if adjusted:
        # Said on the document it affects. A bill that withholds nothing
        # because an advance already carried the tax looks, on its own, like a
        # bill the software forgot.
        why += (f" ₹{adjusted // 100:,} of this {event_noun} was already "
                f"charged as an advance and is not charged again "
                f"(§194 — credit or payment, whichever is earlier).")
    if _tds.applies and not has_pan(vendor.get("pan")):
        why += " Floored at 20% — no PAN on file (§206AA)."
    # THE LIMB THIS SOFTWARE CANNOT PRICE, said on the document it affects
    # rather than left in a module comment. §194I and §194J each charge one
    # limb at a lower rate than the other and only the higher is held, so a
    # plant rental or a technical engagement over-deducts — recoverable, but
    # only if somebody knows.
    _gap = rate_gap_for(tds_section, event_fy)
    if _tds.applies and _gap:
        why += " " + _gap
    return ResidentWithholding(
        tds_paise=_tds.tds_paise,
        rate_bps=(_tds.rate_bps if _tds.applies else 0),
        why=why,
        advance_adjusted_paise=adjusted,
    )


def resolve_non_resident_tds(vendor: dict, taxable_paise: int, on_date: str,
                             firm_id: str = "", db=None):
    """Withholding on a sum paid to a NON-RESIDENT payee — IT Act §195.

    MOVED here from routers/purchase_bills.py, where it was
    `_resolve_bill_section_195`.

    A different charging section from §194C and its neighbours, not a
    different rate for the same one: they charge sums paid "to a resident" and
    do not reach a non-resident at all. So there is no threshold, no FY
    aggregate, and the rate keys on the NATURE of the income rather than the
    kind of work — plus surcharge and cess, which the resident series does not
    carry. domain/tds/section_195.py holds the reasoning and the citations.

    Refuses rather than guessing. A refusal stops the document and makes a
    human decide; a wrong number is withheld, paid to the Government, reported
    on 27Q and discovered by the supplier.
    """
    from domain.tds.section_195 import payee_class_from_pan, resolve_section_195
    from domain.tds.tds_computer import has_pan
    from services.treaty_rate_service import treaty_position

    nature = vendor.get("section_195_nature_of_income")
    # The treaty position comes from the firm's own reading, keyed by (country,
    # nature) — migration 310. A per-vendor treaty_rate_bps still overrides it.
    pos = treaty_position(db, firm_id, vendor, nature)

    res = resolve_section_195(
        amount_paise=taxable_paise,
        nature=nature,
        # THE RECORDED CLASS WINS OVER THE DERIVED ONE, the same precedence
        # treaty_position already gives a per-vendor treaty rate over the
        # firm's country table. A non-resident payee often has no Indian PAN,
        # so the derivation answers "unknown" in the ordinary case — and
        # "unknown" is a refusal, not a guess.
        payee_class=(vendor.get("non_resident_payee_class")
                     or payee_class_from_pan(vendor.get("pan"))),
        has_pan=has_pan(vendor.get("pan")),
        trc_on_file=bool(vendor.get("trc_on_file")),
        form_10f_on_file=bool(vendor.get("form_10f_on_file")),
        no_pe_declaration_on_file=bool(vendor.get("no_pe_declaration_on_file")),
        treaty_rate_bps=(pos.rate_bps if pos.found else None),
        treaty_has_no_article=(pos.found and pos.no_article),
        # Rule 37BC's six particulars. Name, address, email and phone are
        # ordinary vendor fields; the TRC and the country TIN are the two that
        # a domestic vendor never has, so they are what actually gate it.
        rule_37bc_particulars_held=bool(
            vendor.get("trc_on_file")
            and (vendor.get("tax_identification_number") or "").strip()
            and (vendor.get("country_of_residence") or "").strip()
            and (vendor.get("email") or "").strip()
            and (vendor.get("phone") or "").strip()
            and (vendor.get("address") or "").strip()
        ),
        fy=fy_label(on_date),
    )
    if not res.applies:
        raise HTTPException(status_code=422, detail=res.refusal_detail)
    return res


@dataclass(frozen=True)
class Withholding:
    """One answer for either charging regime, so a caller need not branch twice.

    `section` is what was actually charged — "195" for a non-resident, whatever
    the vendor master says for a resident — and None where the vendor is not
    TDS-applicable at all.
    """
    tds_paise: int = 0
    rate_bps: int = 0
    section: Optional[str] = None
    surcharge_paise: int = 0
    cess_paise: int = 0
    nature: Optional[str] = None
    basis: Optional[str] = None
    citation: str = ""
    why: Optional[str] = None
    advance_adjusted_paise: int = 0


def resolve_withholding(
    vendor: dict, taxable_paise: int, on_date: str, firm_id: str, db, *,
    exclude_bill_id: Optional[str] = None,
    exclude_payment_id: Optional[str] = None,
    adjust_against_advances: bool = False,
    event_noun: str = "bill",
) -> Withholding:
    """Which section charges, and how much — the whole dispatch in one place.

    RESIDENCY DECIDES THE CHARGING SECTION, NOT JUST THE RETURN FORM. §194C,
    §194J and their neighbours charge, in their own words, sums paid "to a
    resident". A payment to a non-resident is deducted under §195 at the rates
    in force, so it does not go through the resident engine at all — different
    section, different base, no threshold, plus surcharge and cess.
    """
    if not vendor.get("tds_applicable"):
        return Withholding()

    from domain.tds.residency import is_non_resident

    tds_section = (vendor.get("tds_section") or "").upper().strip() or None
    if is_non_resident(vendor.get("residential_status")):
        res = resolve_non_resident_tds(vendor, taxable_paise, on_date, firm_id, db)
        return Withholding(
            tds_paise=res.tds_paise,
            # The BASE rate, not the effective one: Form 27Q's deductee
            # annexure asks for the rate at which tax was deducted and reports
            # surcharge and cess in their own columns.
            rate_bps=res.rate_bps,
            section="195",
            surcharge_paise=res.surcharge_paise,
            cess_paise=res.cess_paise,
            nature=res.nature,
            # How the number was arrived at — not_chargeable / treaty / act /
            # 206aa_floor. Persisted so a NIL can be told apart from an absence
            # months later, and so the register can say WHY nothing was
            # withheld on a remittance that still belongs on 27Q.
            basis=res.basis,
            citation=res.citation,
        )

    out = resolve_resident_tds(
        vendor, tds_section, taxable_paise, on_date, firm_id, db,
        exclude_bill_id, exclude_payment_id=exclude_payment_id,
        adjust_against_advances=adjust_against_advances,
        event_noun=event_noun,
    )
    return Withholding(
        tds_paise=out.tds_paise,
        rate_bps=out.rate_bps,
        section=tds_section,
        why=out.why,
        advance_adjusted_paise=out.advance_adjusted_paise,
    )
