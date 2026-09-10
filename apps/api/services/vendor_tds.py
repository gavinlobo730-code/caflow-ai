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

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from fastapi import HTTPException

from core.ist_clock import fy_bounds as _fy_bounds_from_label, ist_fy_label

_logger = logging.getLogger("caflow.vendor_tds")

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

    `base_in_window_paise` is how much of that base fell inside a date window
    the caller asked about — how much of a §197 certificate's Rule 28AA(4)
    ceiling earlier documents have already used up. Zero when no window was
    asked for, which is not the same as "none".
    """
    base_paise: int = 0
    tds_paise: int = 0
    unadjusted_advance_paise: int = 0
    base_in_window_paise: int = 0


def aggregate_so_far(
    db, *, firm_id: str, vendor_id: str, section: Optional[str], on_date: str,
    exclude_bill_id: Optional[str] = None,
    exclude_payment_id: Optional[str] = None,
    window: Optional[tuple] = None,
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
    in_window = 0
    w_from, w_to = (window or (None, None))

    def _inside(on) -> bool:
        """Whether a document's own date falls in the caller's window.

        String comparison on ISO dates, which is exactly what the PostgREST
        range filters above already do — one comparison rule for the query and
        for the arithmetic, rather than two that can disagree at a boundary.
        """
        if not w_from or not w_to:
            return False
        return w_from <= str(on or "")[:10] <= w_to

    bills = (db.table("purchase_bills")
             # bill_date is selected because the §197 window is measured on it
             # — the FakeDB honours a select list exactly as PostgREST does, so
             # a column left out of it reads as None and every bill silently
             # falls OUTSIDE the certificate's validity period.
             .select("id, bill_date, taxable_amount_paise, tds_paise, "
                     "tds_section, tds_advance_adjusted_paise")
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
        own = max(0, int(b.get("taxable_amount_paise") or 0) - adjusted)
        base += own
        withheld += int(b.get("tds_paise") or 0)
        advance_absorbed += adjusted
        if _inside(b.get("bill_date")):
            in_window += own

    # A REVERSED PAYMENT IS NOT A PAYMENT. reverse_payment reverses its journal
    # and its TDS credit with it (migration 215's is_reversed), so leaving it in
    # the aggregate would charge a sum that never left and credit tax that was
    # never withheld.
    payments = (db.table("purchase_payments")
                .select("id, payment_date, tds_base_paise, tds_paise, "
                        "tds_section, is_reversed")
                .eq("firm_id", firm_id).eq("vendor_id", vendor_id)
                .gte("payment_date", fy_start).lte("payment_date", fy_end)
                .execute().data) or []
    for p in payments:
        if p.get("id") == exclude_payment_id or p.get("is_reversed"):
            continue
        charged = int(p.get("tds_base_paise") or 0)
        if not charged:
            continue
        if parent_of(p.get("tds_section") or "", label) != want_parent:
            continue
        base += charged
        withheld += int(p.get("tds_paise") or 0)
        advance_charged += charged
        if _inside(p.get("payment_date")):
            in_window += charged

    # AN ADJUSTMENT WHOSE ADVANCE HAS SINCE GONE PUTS THE SUM BACK IN THE BASE.
    # A bill that absorbed ₹5,00,000 of advance took that ₹5,00,000 out of its
    # own charged base, because the advance had already carried the tax. If that
    # advance is later reversed — or its bill cancelled — the sum is charged
    # nowhere, and the year's aggregate is short by exactly the difference. A
    # posted bill's withholding cannot be silently rewritten, so the shortfall
    # is restored here instead and the NEXT bill re-charges it, crediting under
    # §200 whatever is still actually withheld. Without this the two figures
    # simply drift apart and the vendor is under-deducted for the rest of the
    # year with nothing saying so.
    orphaned = max(0, advance_absorbed - advance_charged)

    return Aggregate(
        base_paise=base + orphaned,
        tds_paise=withheld,
        unadjusted_advance_paise=max(0, advance_charged - advance_absorbed),
        base_in_window_paise=in_window,
    )


@dataclass(frozen=True)
class ResidentWithholding:
    """What the §194 series takes out of one bill or one advance."""
    tds_paise: int
    rate_bps: int
    why: str
    advance_adjusted_paise: int = 0
    #: IT Act §197 — the certificate that lowered the rate, for the 26Q
    #: deductee row's own lower-deduction fields (migration 037 has carried
    #: them since it was written and nothing ever set them).
    is_lower_deduction: bool = False
    certificate_no: Optional[str] = None


def certificates_for(db, *, firm_id: str, client_id: Optional[str],
                     vendor_id: Optional[str]) -> list:
    """This vendor's §197 certificates, or an empty list.

    Firm- AND client-scoped: the service-role key bypasses RLS, so the
    app-layer filter is the primary isolation control (CLAUDE.md). client_id is
    tolerated as None only because the resident resolver is reachable from a
    preview that does not carry one — the firm filter still holds, and a vendor
    belongs to exactly one client.
    """
    if db is None or not vendor_id:
        return []
    q = (db.table("tds_lower_deduction_certificates").select("*")
         .eq("firm_id", firm_id).eq("vendor_id", vendor_id))
    if client_id:
        q = q.eq("client_id", client_id)
    try:
        return q.execute().data or []
    except Exception:                                            # noqa: BLE001
        # A certificate table that cannot be read must not stop a bill being
        # booked. The consequence of missing one is an OVER-deduction the payee
        # can reclaim; the consequence of failing the save is a CA who cannot
        # record a real purchase. Never silent: the caller's `why` says the
        # certificate was not consulted only when one was actually found, so an
        # unreadable table shows as the ordinary section rate.
        _logger.warning("could not read §197 certificates for vendor %s", vendor_id)
        return []


def resolve_resident_tds(
    vendor: dict, tds_section: Optional[str], taxable_paise: int, on_date: str,
    firm_id: str, db, exclude_bill_id: Optional[str] = None, *,
    exclude_payment_id: Optional[str] = None,
    adjust_against_advances: bool = False,
    event_noun: str = "bill",
    client_id: Optional[str] = None,
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
    from domain.tds import lower_deduction

    payee_has_pan = has_pan(vendor.get("pan"))
    # IT Act §197 — read BEFORE the aggregate, because the certificate's
    # validity period is the window the aggregate has to measure against. Asked
    # of the YEAR rather than of this document's date: the charge is on the
    # year's aggregate, so a bill dated after the certificate expired still
    # recomputes the whole year, and dropping the certificate at that point
    # would re-charge the earlier certified slice at the full rate.
    fy_start, fy_end = fy_bounds(on_date)
    position = lower_deduction.position_for(
        certificates_for(db, firm_id=firm_id, client_id=client_id,
                         vendor_id=vendor.get("id")),
        section=tds_section, fy_start=fy_start, fy_end=fy_end,
        has_pan=payee_has_pan)
    cert = position.certificate
    window = ((cert.valid_from.isoformat(), cert.valid_to.isoformat())
              if cert else None)

    agg = aggregate_so_far(
        db, firm_id=firm_id, vendor_id=vendor.get("id"), section=tds_section,
        on_date=on_date, exclude_bill_id=exclude_bill_id,
        exclude_payment_id=exclude_payment_id, window=window,
    )
    fy_prior = agg.base_paise
    fy_prior_tds = agg.tds_paise
    # A bill absorbs so much of the outstanding advance pool as it can, and no
    # more than its own value. What it absorbs was charged when the advance was
    # paid, so it is not charged again here — it is already inside fy_prior.
    adjusted = (min(taxable_paise, agg.unadjusted_advance_paise)
                if adjust_against_advances else 0)
    own_base = max(0, taxable_paise - adjusted)
    # HOW MUCH OF THE YEAR'S AGGREGATE THE CERTIFICATE REACHES. Rule 28AA(4)'s
    # ceiling is on the sums credited or paid INSIDE the validity period, so the
    # certified slice is what earlier documents in the window already used plus
    # this one — capped at the ceiling. The rest of the aggregate, including any
    # document dated outside the window, stays at the section rate.
    certified_base = 0
    this_doc_inside = False
    headroom_before = 0
    if cert is not None:
        this_doc_inside = window is not None and window[0] <= str(on_date)[:10] <= window[1]
        # What the ceiling still had when THIS document was reached, which is
        # what decides the rate that goes on ITS 26Q row — separately from how
        # much of the whole year the certificate reaches.
        headroom_before = max(0, cert.ceiling_paise - agg.base_in_window_paise)
        in_window = agg.base_in_window_paise + (own_base if this_doc_inside else 0)
        # consumed_paise=0 and the whole in-window total as the base: this is
        # not an incremental draw-down but a restatement of the year so far, so
        # what the certificate reaches is min(in-window total, ceiling) in one
        # step. Capped at the charge base as well, because a window can reach
        # into a prior document that this aggregate excludes.
        certified_base = lower_deduction.certified_base(
            cert, consumed_paise=0,
            charge_base_paise=min(in_window, fy_prior + own_base))
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
            has_pan=payee_has_pan,
            certified_base_paise=certified_base,
            certificate_rate_bps=(cert.rate_bps if cert is not None else None),
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
    # IT Act §197, said on the document. A certificate that lowered the rate and
    # a certificate that was REFUSED are both facts a CA has to see: the second
    # looks, from the figure alone, exactly like the software ignoring a
    # certificate they know they recorded.
    if _tds.applies and _tds.certified_base_paise and cert is not None:  # noqa: E501
        why += (f" §197 certificate {cert.certificate_no} at "
                f"{cert.rate_bps / 100:g}% on ₹{_tds.certified_base_paise // 100:,} "
                f"of that.")
        if _tds.certified_base_paise < (fy_prior + own_base):
            why += (f" The certificate's ₹{cert.ceiling_paise // 100:,} ceiling "
                    f"(Rule 28AA(4)) is exhausted, so the excess is at the "
                    f"section rate.")
    elif position.refusal:
        why += " " + position.detail
    if _tds.applies and not payee_has_pan:
        why += " Floored at 20% — no PAN on file (§206AA)."
    # THE LIMB THIS SOFTWARE CANNOT PRICE, said on the document it affects
    # rather than left in a module comment. §194I and §194J each charge one
    # limb at a lower rate than the other and only the higher is held, so a
    # plant rental or a technical engagement over-deducts — recoverable, but
    # only if somebody knows.
    _gap = rate_gap_for(tds_section, event_fy)
    if _tds.applies and _gap:
        why += " " + _gap
    # THE RATE THAT GOES ON THE 26Q ROW. Form 26Q's annexure has ONE rate
    # column, so where the certificate covers the whole charge base it is the
    # certified rate — that, with the certificate number, is what the FVU
    # requires whenever a below-normal rate is used. Where the ceiling was
    # crossed mid-year two rates genuinely applied to one aggregate and no
    # single figure is true; the section rate goes on the row and the sentence
    # above says why the arithmetic does not close, which is the same treatment
    # the FY catch-up already gets (GAP_TDS_IS_A_FY_CATCH_UP).
    # THIS DOCUMENT carried the certified rate only if it fell inside the
    # window AND the ceiling still had room for the whole of it. A document
    # dated after the certificate expired benefits from the year's certified
    # slice through the aggregate, but its own 26Q row is at the section rate —
    # which is what happened.
    used_certificate = bool(
        _tds.applies and cert is not None and this_doc_inside and headroom_before > 0)
    fully_certified = used_certificate and headroom_before >= own_base
    rate_bps = _tds.rate_bps if _tds.applies else 0
    if fully_certified and cert is not None:
        rate_bps = cert.rate_bps
    return ResidentWithholding(
        tds_paise=_tds.tds_paise,
        rate_bps=rate_bps,
        why=why,
        advance_adjusted_paise=adjusted,
        is_lower_deduction=used_certificate,
        certificate_no=(cert.certificate_no if used_certificate and cert else None),
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
    #: IT Act §197 — the certificate number that lowered the rate, or None.
    #: `is_lower_deduction` on the register row is exactly "this is not None",
    #: so only one of the two is ever stored.
    certificate_no: Optional[str] = None


def resolve_withholding(
    vendor: dict, taxable_paise: int, on_date: str, firm_id: str, db, *,
    exclude_bill_id: Optional[str] = None,
    exclude_payment_id: Optional[str] = None,
    adjust_against_advances: bool = False,
    event_noun: str = "bill",
    client_id: Optional[str] = None,
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
        # A §197 CERTIFICATE ON A §195 PAYEE IS NOT APPLIED, and is not silent.
        # §197(1) does reach §195, but the §195 engine resolves by NATURE of
        # income against §115A, Part II's surcharge ladders and the DTAA under
        # §90(2) — applying a flat certified rate on top of that would be a
        # fourth rate in a comparison the statute already defines, and getting
        # it wrong disallows the WHOLE expenditure under §40(a)(i). So the
        # figure stands at the §195 rate and the CA is told the certificate was
        # not used, rather than shown a number that quietly ignored it.
        from domain.tds import lower_deduction
        from domain.tds.tds_computer import has_pan as _has_pan
        _fy_start, _fy_end = fy_bounds(on_date)
        _pos = lower_deduction.position_for(
            certificates_for(db, firm_id=firm_id, client_id=client_id,
                             vendor_id=vendor.get("id")),
            section="195", fy_start=_fy_start, fy_end=_fy_end,
            has_pan=_has_pan(vendor.get("pan")))
        _note = None
        if _pos.found and _pos.certificate is not None:
            _note = (
                f"A §197 certificate ({_pos.certificate.certificate_no}) is on "
                f"file for this payee and was NOT applied: §195 is resolved by "
                f"the nature of the income under §115A and Part II of the First "
                f"Schedule, with the DTAA under §90(2), and this software does "
                f"not combine a certified rate with that comparison. Withhold "
                f"the certified amount outside the software if the certificate "
                f"governs.")
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
            why=_note,
        )

    out = resolve_resident_tds(
        vendor, tds_section, taxable_paise, on_date, firm_id, db,
        exclude_bill_id, exclude_payment_id=exclude_payment_id,
        adjust_against_advances=adjust_against_advances,
        event_noun=event_noun, client_id=client_id,
    )
    return Withholding(
        tds_paise=out.tds_paise,
        rate_bps=out.rate_bps,
        section=tds_section,
        why=out.why,
        advance_adjusted_paise=out.advance_adjusted_paise,
        certificate_no=out.certificate_no,
    )


# The vendor columns the two resolvers actually read. Not used to narrow a
# query — both callers select("*"), as the bill path does — but written down so
# a reviewer can see what a withholding decision depends on without reading two
# engines: PAN and residency decide WHICH section, the §195 paperwork decides
# whether a treaty or a nil is available at all.
VENDOR_FIELDS_THAT_DECIDE_WITHHOLDING = (
    "pan", "tds_applicable", "tds_section", "residential_status",
    "country_of_residence", "tax_identification_number", "trc_on_file",
    "form_10f_on_file", "no_pe_declaration_on_file",
    "section_195_nature_of_income", "non_resident_payee_class",
    "treaty_rate_bps", "email", "phone", "address",
)


# The bill states in which the vendor's account has actually been credited —
# transcribed from services/tds_register_service.IN_THE_BOOKS, which says why: a
# draft posts no journal, so nothing has been credited and nothing is owed.
_IN_THE_BOOKS = frozenset({"received", "partially_paid", "paid", "overdue"})


def open_payable_paise(db, *, firm_id: str, client_id: str, vendor_id: str) -> int:
    """What this vendor is still owed on bills already in the books.

    Computed from the parts rather than read from purchase_bills.outstanding_-
    paise, which is a GENERATED column (migration 278) and therefore exists only
    in Postgres — the in-memory source every mock-mode test runs against has the
    parts and not the total. The formula is migration 278's own, character for
    character: net payable + credit notes − paid − debited (CGST Act §34).
    """
    if db is None or not vendor_id:
        return 0
    rows = (db.table("purchase_bills")
            .select("status, net_payable_paise, credit_note_paise, "
                    "paid_paise, debited_paise, deleted_at")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("vendor_id", vendor_id)
            .neq("status", "cancelled")
            .execute().data) or []
    total = 0
    for b in rows:
        if b.get("deleted_at") or (b.get("status") or "").lower() not in _IN_THE_BOOKS:
            continue
        total += (int(b.get("net_payable_paise") or 0)
                  + int(b.get("credit_note_paise") or 0)
                  - int(b.get("paid_paise") or 0)
                  - int(b.get("debited_paise") or 0))
    return max(0, total)


def columns_for_advance(
    vendor: dict, unallocated_paise: int, payment_date: str, firm_id: str, db, *,
    payment_total_paise: int,
    open_payable_paise: int = 0,
    exclude_payment_id: Optional[str] = None,
) -> dict:
    """The TDS columns a vendor payment carries, for the ADVANCE part of it.

    WHAT COUNTS AS AN ADVANCE, WHICH IS THE WHOLE QUESTION

        advance = max(0, unallocated − open payable)

    §194 charges a sum at its CREDIT or its PAYMENT, whichever is EARLIER. So
    the part of a payment that discharges a liability already on the books is
    the LATER event for a sum already charged, and is not charged again — even
    where the CA never linked it to a bill. Only the excess is a sum paid for
    which no credit has yet been made, and only that is charged here.

    Leaving the `unallocated` figure to speak for itself was wrong and the
    end-to-end purchase cycle caught it: a ₹1,08,000 payment settling a
    ₹1,08,000 bill, recorded without a bill link (which that test records as a
    known gap), withheld a second ₹10,800 on money the bill had already
    withheld from. `unallocated` means "not tied to a bill row", not "not owed".

    THE RESIDUAL, NAMED RATHER THAN GUESSED AT. A CA who advances ₹5,00,000,
    never links it, and then pays the whole bill again has paid the vendor
    twice; the second payment discharges a real credit, so it is not charged,
    and the first advance stays unlinked for ever. Charging it would over-deduct
    on every CA who is merely slow to allocate, which is recoverable only by the
    payee claiming a refund. The books show it as a debit balance on the vendor,
    which is where it belongs.

    ONE HELPER BECAUSE THERE ARE TWO PAYMENT PATHS. routers/purchase_payments
    (single-bill, legacy) and services/purchase_payment_service (multi-bill
    allocations) both create payments, and a withholding computed two ways is
    a withholding that will eventually be computed two different ways.

    `advance_paise` is the UNALLOCATED part of the payment and nothing else.
    The allocated part settles bills that were charged when they were credited;
    charging it again here would deduct the same sum twice.

    THE BASE IS RECORDED EVEN WHERE NOTHING IS WITHHELD, and that is the point
    of `tds_base_paise` being separate from `tds_paise`. §194C(5) aggregates
    "the amounts of such sums credited or paid", not the sums that bore tax —
    so a ₹25,000 advance under the ₹30,000 single limb still counts toward the
    year's ₹1,00,000 aggregate, and the advance that eventually crosses it
    carries the whole year's tax. A base of zero would silently forgive it.

    THE DEDUCTION IS BOUNDED BY THE PAYMENT, which is not academic here. The
    charge falls on the YEAR'S AGGREGATE, so the document that crosses a
    threshold carries the whole year's tax and that can exceed its own value: a
    §194J payee advanced ₹49,000 (nil, inside the ₹50,000 limb) and then ₹2,000
    owes ₹5,100 on the ₹51,000 aggregate. Unbounded, the bank leg goes negative
    — a payment that took money OUT of the vendor — and migration 358's own
    CHECK rejects the row AFTER the journal has posted, so the payment cannot be
    recorded at all. The bill path bounds at the bill total for exactly this
    reason; this bounds at the payment total, which is the cash actually leaving
    and therefore what can be held back out of it.

    THE SHORTFALL IS NOT LOST. `tds_base_paise` records the whole advance while
    `tds_paise` records what was actually withheld, so the next document to this
    payee sees the base charged and less tax withheld, and re-charges the
    difference through §200. No state is needed for it.

    Returns the payload keys verbatim so a caller merges rather than maps, plus
    `_tds_why` and `_tds_citation`, which are NOT columns: the first is the
    sentence the CA reads beside the figure, the second is what the register
    quotes as the reason a §195 remittance withheld nothing.
    """
    empty = {
        "tds_paise": 0, "tds_base_paise": 0, "tds_section": None,
        "tds_rate_bps": None, "tds_surcharge_paise": 0, "tds_cess_paise": 0,
        "tds_nature_of_income": None, "tds_basis": None,
        "tds_certificate_no": None,
    }
    advance_paise = max(0, int(unallocated_paise) - int(open_payable_paise))
    if advance_paise <= 0 or not (vendor or {}).get("tds_applicable"):
        return empty

    w = resolve_withholding(
        vendor, advance_paise, payment_date, firm_id, db,
        exclude_payment_id=exclude_payment_id,
        client_id=vendor.get("client_id"),
        # An advance absorbs nothing: it IS the earlier event. Only a bill
        # adjusts, because only a bill can arrive second.
        adjust_against_advances=False,
        event_noun="advance",
    )
    if not w.section:
        return empty
    withheld = min(w.tds_paise, max(0, int(payment_total_paise)))
    return {
        "tds_paise": withheld,
        "tds_base_paise": advance_paise,
        "tds_section": w.section,
        "tds_rate_bps": w.rate_bps,
        "tds_surcharge_paise": w.surcharge_paise,
        "tds_cess_paise": w.cess_paise,
        "tds_nature_of_income": w.nature,
        "tds_basis": w.basis,
        "tds_certificate_no": w.certificate_no,
        "_tds_why": w.why,
        "_tds_citation": w.citation,
    }


def strip_non_columns(payload: dict) -> dict:
    """The same dict without the two underscore keys, ready for an insert.

    PostgREST rejects the WHOLE write with PGRST204 when one key is not a
    column, so the explanation the CA reads must not travel into the row by
    accident.
    """
    return {k: v for k, v in payload.items() if not k.startswith("_")}
