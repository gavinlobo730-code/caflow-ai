"""
Interest a client charges its own customer on an overdue balance — accounting-22,
migration 461.

WHAT IT IS, AND WHAT IT IS NOT

    A COMMERCIAL term between a client and the customer who owes it money,
    agreed in a conversation: "18% a year on anything more than seven days
    late". The product computes STATUTORY interest in a dozen places (TDS
    s.201(1A), GST s.50, advance tax s.234A-C) and each of them is a rule
    somebody can cite; this one is not, and says so. It is the
    `credit_limit` module's sibling and lives beside it in `domain/sales/` for
    the same reason: a later reader looking for the section number will not
    find one because there is not one.

    Two sentences ARE statutory and are carried on every answer, graded `[S]`
    because egress is refused here and they could not be read against the Act:

    CGST Act s.15(2)(d) — "interest or late fee or penalty for delayed payment
    of any consideration for any supply" is INCLUDED in the value of that
    supply. So interest on a late invoice is not a separate, untaxed receipt:
    it carries the tax of the supply it arises from, which is why a prepared
    draft takes the GST rate of the invoice it relates to and REFUSES to guess
    one where that invoice's lines carry several.

THE CONVENTION IS STATED ON EVERY ANSWER, because two CAs given the same
facts and "18%" will otherwise produce two figures:

    SIMPLE interest — never compound. Compounding is a different agreement and
    is not offered; an interest invoice is also excluded from the base of the
    next preview, so interest is never charged on interest by accident.

    ACTUAL DAYS over a 365-DAY YEAR (actual/365). A leap year is not 366: the
    divisor is a constant, so the same loan costs the same per day in every
    year and nobody has to ask which year a day fell in.

    THE DAY COUNT: interest runs for the days AFTER the start date plus the
    grace period, up to and including the as-at date. An invoice due on 1
    September with no grace, looked at on 11 October, is 40 days late and
    carries 40 days of interest — the due date itself is not a late day.

    ROUNDING: to the paisa, half a paisa and over rounding UP, done once on the
    whole product and never per day.

THE BALANCE IS READ, NEVER RE-SUBTRACTED

    The base is each invoice's `outstanding_paise` — migration 278's GENERATED
    column, which carries the CGST s.34 note terms that `total - paid` omits
    (and the credit note ADDS to a purchase bill and SUBTRACTS from an
    invoice). This module takes the figure it is given.

    ⚠️ IT IS THE BALANCE AS IT STANDS TODAY, applied to the whole late period.
    A part-payment received midway reduced the balance from its own date and
    not before, so where one was received late this figure OVERSTATES the
    interest, and an as-at date earlier than today does not restate balances as
    they were then. Rebuilding the balance on every day from receipt
    allocations is a different and much larger report; the overstatement is the
    direction a CA can see and correct, and every answer says it.

NOTHING IS POSTED, AND NOTHING IS BILLED BY ITSELF

    A figure and a PREPARED DRAFT. The draft is an ordinary draft sales invoice
    raised through the sales engine; it posts no journal until somebody issues
    it, and it is never issued, emailed or reminded about here.

THREE STATES FOR "NO FIGURE" THAT MUST NOT LOOK ALIKE

    NO TERMS    the customer has no rate on record — nothing is computed and the
                party is NAMED, with the overdue balance it would apply to.
    WAIVED      a recorded rate of 0 — a decision ("interest is waived"), not a
                missing one, and shown as such.
    NOT OVERDUE / COVERED / NOTHING TO ROUND — a rate exists and the answer is
                nil for a stated reason (not yet late; a draft already covers
                the days; the interest is under half a paisa).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable, Optional

from domain.money_text import rupees_paise

#: The one day-count convention, named on every answer.
DAY_COUNT = "actual/365"
YEAR_DAYS = 365

FROM_DUE_DATE = "due_date"
FROM_INVOICE_DATE = "invoice_date"
BASES = (FROM_DUE_DATE, FROM_INVOICE_DATE)

#: An annual rate above 100% is a unit slip (typing 1800 for 18, or 18 for
#: 18%), not a commercial term — migration 461's CHECK says the same.
MAX_RATE_BPS = 10_000
MAX_GRACE_DAYS = 365

# ── what a document's line says ──────────────────────────────────────────────
CHARGE = "charge"                    # interest is due for days_charged > 0
NOT_OVERDUE = "not_overdue"          # on or before start + grace
COVERED = "covered"                  # a standing draft already covers through as_of
ROUNDS_TO_NIL = "rounds_to_nil"      # late, but under half a paisa
WAIVED = "waived"                    # the customer's recorded rate is 0
NO_TERMS = "no_terms"                # nobody has stated a rate
INTEREST_INVOICE = "interest_invoice"  # an interest draft is never a base
UNDATED = "undated"                  # no date to count from

#: A document that cannot carry a draft, and why (see `plan_drafts`).
BLOCK_NOT_REGULAR = "not_a_regular_taxable_supply"
BLOCK_MIXED_RATE = "lines_carry_several_gst_rates"
BLOCK_NO_RATE = "no_gst_rate_to_follow"


@dataclass(frozen=True)
class Terms:
    """A customer's interest terms. `rate_bps is None` means NOT STATED."""

    rate_bps: Optional[int] = None
    grace_days: int = 0
    basis: str = FROM_DUE_DATE


def terms_problem(rate_bps, grace_days, basis) -> Optional[str]:
    """What is wrong with these terms, in a sentence — or None.

    The one rule BOTH doors ask (the API model and the service), so the browser
    holds none of it. `rate_bps=None` is valid: it CLEARS the terms.
    """
    if rate_bps is not None:
        if isinstance(rate_bps, bool) or not isinstance(rate_bps, int):
            return "The interest rate must be a whole number of basis points (1800 is 18% a year)."
        if rate_bps < 0 or rate_bps > MAX_RATE_BPS:
            return ("The interest rate must be between 0% and 100% a year "
                    f"(0 to {MAX_RATE_BPS} basis points); {rate_bps} is outside that. "
                    "1800 means 18% a year.")
    if isinstance(grace_days, bool) or not isinstance(grace_days, int):
        return "Grace days must be a whole number."
    if grace_days < 0 or grace_days > MAX_GRACE_DAYS:
        return f"Grace days must be between 0 and {MAX_GRACE_DAYS}."
    if basis not in BASES:
        return "Interest is counted from the due_date or the invoice_date."
    return None


def round_half_up(numerator: int, denominator: int) -> int:
    """`numerator / denominator` to the nearest whole number, halves rounding up.

    Integer arithmetic only. Both arguments are non-negative here (an
    outstanding balance, a rate and a day count are), which is what makes
    `(2n + d) // 2d` the half-up rule.
    """
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    if numerator < 0:
        raise ValueError("numerator must be non-negative")
    return (2 * numerator + denominator) // (2 * denominator)


def interest_paise(outstanding_paise: int, rate_bps: int, days: int) -> int:
    """Simple interest, actual/365, to the paisa, half rounding up.

    `outstanding * rate_bps / 10_000 * days / 365` is ONE division of an exact
    integer product — never a per-day or per-month rounding, which would drift
    from the stated convention by a paisa every few documents.
    """
    if outstanding_paise <= 0 or rate_bps <= 0 or days <= 0:
        return 0
    return round_half_up(outstanding_paise * rate_bps * days, 10_000 * YEAR_DAYS)


def as_date(value) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


@dataclass(frozen=True)
class DocumentInterest:
    status: str
    interest_paise: int = 0
    counted_from: Optional[str] = None      # the start date interest counts from
    start_note: Optional[str] = None
    days_late: int = 0                       # after grace, to the as-at date
    days_charged: int = 0                    # of those, not yet covered by a draft
    period_from: Optional[str] = None        # interest is for the days AFTER this
    period_to: Optional[str] = None          # ... up to and including this
    already_charged_through: Optional[str] = None
    note: Optional[str] = None


def document_interest(
    *, outstanding_paise: int, invoice_date, due_date, terms: Terms, as_of: date,
    charged_through: Optional[date] = None,
) -> DocumentInterest:
    """One overdue invoice's interest, or the reason there is none.

    `charged_through` is the as-at date a STANDING draft already covers: the
    next period starts the day after it, so the same days are never charged
    twice. It is the caller's to derive, because whether a draft still stands
    is a fact about another invoice.
    """
    if terms.rate_bps is None:
        return DocumentInterest(status=NO_TERMS)
    inv_d, due_d = as_date(invoice_date), as_date(due_date)
    note = None
    if terms.basis == FROM_INVOICE_DATE:
        start = inv_d
    else:
        start = due_d
        if start is None and inv_d is not None:
            start = inv_d
            note = ("No due date is recorded for this invoice, so the days are "
                    "counted from the invoice date.")
    if start is None:
        return DocumentInterest(status=UNDATED, note="This invoice has no date to count from.")

    accrues_after = start + timedelta(days=terms.grace_days)
    days_late = max((as_of - accrues_after).days, 0)
    if days_late == 0:
        return DocumentInterest(
            status=NOT_OVERDUE, counted_from=start.isoformat(), start_note=note,
            period_from=accrues_after.isoformat(), period_to=as_of.isoformat())
    if int(outstanding_paise) <= 0:
        # The read filters these out; a caller with a stale row gets nil.
        return DocumentInterest(status=NOT_OVERDUE, counted_from=start.isoformat())

    period_from = accrues_after
    if charged_through is not None and charged_through > period_from:
        period_from = charged_through
    days = max((as_of - period_from).days, 0)
    base = dict(
        counted_from=start.isoformat(), start_note=note, days_late=days_late,
        period_from=period_from.isoformat(), period_to=as_of.isoformat(),
        already_charged_through=charged_through.isoformat() if charged_through else None)
    if days == 0:
        return DocumentInterest(status=COVERED, days_charged=0, **base)
    if terms.rate_bps == 0:
        return DocumentInterest(status=WAIVED, days_charged=days, **base)
    amount = interest_paise(int(outstanding_paise), int(terms.rate_bps), days)
    if amount == 0:
        return DocumentInterest(status=ROUNDS_TO_NIL, days_charged=days, **base)
    return DocumentInterest(status=CHARGE, interest_paise=amount, days_charged=days, **base)


# ── The preview over a whole customer book ───────────────────────────────────

@dataclass(frozen=True)
class DocInput:
    """One open invoice, already fetched. `outstanding_paise` is the column."""

    invoice_id: str
    invoice_no: str
    invoice_date: Optional[str]
    due_date: Optional[str]
    outstanding_paise: int
    charged_through: Optional[date] = None
    #: True for an invoice that IS a prepared interest draft: never a base.
    is_interest_invoice: bool = False


@dataclass(frozen=True)
class PartyInput:
    customer_id: str
    name: str
    terms: Terms
    documents: tuple[DocInput, ...] = ()


def convention(as_of: date) -> dict:
    """The convention, in words and in fields, on every answer."""
    return {
        "interest": "simple",
        "compounding": "not offered",
        "day_count": DAY_COUNT,
        "year_days": YEAR_DAYS,
        "rounding": "to the paisa, half a paisa and over rounds up, once on the whole product",
        "as_of": as_of.isoformat(),
        "counting": (
            "Interest runs for the days after the start date plus any grace, up "
            "to and including the as-at date; the start date itself is not a "
            "late day. The start date is the due date unless the customer's "
            "terms say the invoice date."),
        "statement": (
            "Simple interest at the customer's annual rate on each overdue "
            "invoice's open balance, in actual days over a 365-day year, from "
            "the day after the start date and any grace up to and including the "
            f"as-at date ({as_of.isoformat()}); half a paisa and over rounds up."),
    }


#: Said on every answer that carries a figure. The first is a limitation of the
#: method and the second is the statutory reading, graded.
CAVEAT_BALANCE_IS_TODAYS = (
    "The base is each invoice's open balance AS IT STANDS TODAY, applied to the "
    "whole late period. A part-payment received during that period reduced the "
    "balance only from its own date, so where one was received late the figure "
    "OVERSTATES the interest; and an as-at date earlier than today does not "
    "restate balances as they were then.")
STATUTORY_READING = {
    "section": "CGST Act s.15(2)(d)",
    "grade": "[S]",
    "text": (
        "Interest charged for delayed payment of consideration forms part of "
        "the value of the supply it arises from, so GST is chargeable on it at "
        "the rate of that supply. The draft therefore carries the GST rate of "
        "the invoice it relates to. Whether to raise it as an invoice or as a "
        "debit note, and its time of supply, are the CA's decisions. Egress is "
        "refused here, so the section could not be read against the Act."),
}
CAVEAT_NOT_POSTED = (
    "Nothing here is posted or invoiced. A prepared draft is an ordinary draft "
    "sales invoice and changes no ledger until somebody issues it.")


def party_preview(party: PartyInput, as_of: date) -> dict:
    """One customer's overdue documents and the interest on them.

    Only documents that are LATE appear, plus the interest drafts that were
    excluded from the base (named, so a reader knows why a document they can
    see on the receivables screen is missing).
    """
    rows: list[dict] = []
    total = 0
    overdue_base = 0
    for doc in party.documents:
        if doc.is_interest_invoice:
            rows.append({
                "invoice_id": doc.invoice_id, "invoice_no": doc.invoice_no,
                "outstanding_paise": doc.outstanding_paise, "status": INTEREST_INVOICE,
                "interest_paise": 0, "days_late": 0, "days_charged": 0,
                "note": ("This is an interest invoice. Interest is simple, so it is "
                         "never charged on interest."),
            })
            continue
        result = document_interest(
            outstanding_paise=doc.outstanding_paise, invoice_date=doc.invoice_date,
            due_date=doc.due_date, terms=party.terms, as_of=as_of,
            charged_through=doc.charged_through)
        late = result.status != NOT_OVERDUE
        if party.terms.rate_bps is None:
            # No rate: nothing is computed, but the reader needs to know how
            # much is overdue for the rate to apply to. Lateness needs a rate's
            # grace, so it is judged on the due date alone here.
            due = as_date(doc.due_date) or as_date(doc.invoice_date)
            late = due is not None and as_of > due
            if not late:
                continue
            overdue_base += int(doc.outstanding_paise)
            rows.append({
                "invoice_id": doc.invoice_id, "invoice_no": doc.invoice_no,
                "invoice_date": doc.invoice_date, "due_date": doc.due_date,
                "outstanding_paise": doc.outstanding_paise, "status": NO_TERMS,
                "interest_paise": 0, "days_late": (as_of - due).days, "days_charged": 0,
                "note": "No interest rate is recorded for this customer.",
            })
            continue
        if not late:
            continue
        overdue_base += int(doc.outstanding_paise)
        total += result.interest_paise
        rows.append({
            "invoice_id": doc.invoice_id, "invoice_no": doc.invoice_no,
            "invoice_date": doc.invoice_date, "due_date": doc.due_date,
            "outstanding_paise": doc.outstanding_paise, "status": result.status,
            "counted_from": result.counted_from, "start_note": result.start_note,
            "days_late": result.days_late, "days_charged": result.days_charged,
            "period_from": result.period_from, "period_to": result.period_to,
            "already_charged_through": result.already_charged_through,
            "interest_paise": result.interest_paise, "note": result.note,
        })
    rows.sort(key=lambda r: (-int(r.get("days_late") or 0), str(r.get("invoice_no") or "")))
    terms = party.terms
    return {
        "customer_id": party.customer_id,
        "customer_name": party.name,
        "terms_set": terms.rate_bps is not None,
        "terms": ({"rate_bps": terms.rate_bps, "grace_days": terms.grace_days,
                   "basis": terms.basis} if terms.rate_bps is not None else None),
        "overdue_outstanding_paise": overdue_base,
        "interest_paise": total,
        "documents": rows,
    }


def build_preview(parties: Iterable[PartyInput], as_of: date) -> dict:
    """Interest due per party as at a date, with the convention stated.

    A party with nothing overdue is omitted: this is a worklist, not a roll of
    every customer. A party with overdue invoices and no rate on record IS
    listed, with no figure and the balance the rate would apply to — a nil that
    means "we cannot tell" must not look like a nil that means "none".
    """
    out = []
    for party in parties:
        p = party_preview(party, as_of)
        if p["documents"]:
            out.append(p)
    out.sort(key=lambda p: (-p["interest_paise"], -p["overdue_outstanding_paise"],
                            str(p["customer_name"] or "")))
    with_interest = [p for p in out if p["interest_paise"] > 0]
    without_terms = [p for p in out if not p["terms_set"]]
    caveats = [CAVEAT_BALANCE_IS_TODAYS, CAVEAT_NOT_POSTED]
    gaps = []
    if without_terms:
        gaps.append(
            f"{len(without_terms)} customer(s) have overdue invoices and no interest "
            "rate on record, so no interest is computed for them: "
            + ", ".join(sorted(str(p["customer_name"] or p["customer_id"])
                               for p in without_terms)[:20])
            + ("…" if len(without_terms) > 20 else "") + ".")
    return {
        "as_of": as_of.isoformat(),
        "convention": convention(as_of),
        "statutory_reading": STATUTORY_READING,
        "parties": out,
        "totals": {
            "interest_paise": sum(p["interest_paise"] for p in out),
            "parties_with_interest": len(with_interest),
            "parties_without_terms": len(without_terms),
            "overdue_outstanding_paise": sum(p["overdue_outstanding_paise"] for p in out),
        },
        "caveats": caveats,
        "gaps": gaps,
    }


# ── What may be drafted, and as how many invoices ────────────────────────────

@dataclass(frozen=True)
class ChargeableDoc:
    """An invoice with interest due, plus the facts its tax follows."""

    invoice_id: str
    invoice_no: str
    customer_id: str
    interest_paise: int
    period_from: str
    period_to: str
    days: int
    outstanding_paise: int
    #: The CUSTOMER's annual interest rate this was computed at, in basis
    #: points — what the line says in words. Not the GST rate below.
    interest_rate_bps: int = 0
    #: What the invoice's own lines say. `None` means "not one rate".
    gst_rate_bps: Optional[int] = None
    rate_state: str = "single"               # single | mixed | none
    is_interstate: bool = False
    supply_state_code: Optional[str] = None
    supply_type: Optional[str] = "taxable"
    invoice_type: Optional[str] = "Regular"
    is_reverse_charge: bool = False
    hsn_sac: Optional[str] = None


@dataclass(frozen=True)
class DraftGroup:
    """Documents whose interest can sit on ONE draft invoice: the same GST rate
    and the same place of supply, which is what makes one invoice's tax right."""

    gst_rate_bps: int
    is_interstate: bool
    supply_state_code: Optional[str]
    documents: tuple[ChargeableDoc, ...] = field(default_factory=tuple)

    @property
    def interest_paise(self) -> int:
        return sum(d.interest_paise for d in self.documents)


def block_reason(doc: ChargeableDoc) -> Optional[tuple[str, str]]:
    """(code, sentence) when a draft must NOT be prepared for this document.

    Three refusals, each its own, because what the CA does next differs:

      * NOT A REGULAR TAXABLE SUPPLY. s.15(2)(d) puts the interest in the value
        of the supply, so it follows that supply's treatment — and an export, an
        SEZ supply, an exempt or nil-rated one and a reverse-charge one each
        has its own. A draft built with ordinary domestic tax would declare the
        wrong thing on a return, so it is raised by hand.
      * SEVERAL RATES. An invoice whose lines carry different GST rates would
        need the interest apportioned across them, which is a judgement and not
        a computation; picking one rate is the guess this refuses.
      * NO RATE TO FOLLOW. An invoice with no lines gives nothing to follow.
    """
    if (doc.supply_type or "taxable") != "taxable" \
            or (doc.invoice_type or "Regular") != "Regular" or doc.is_reverse_charge:
        return (BLOCK_NOT_REGULAR,
                f"Invoice {doc.invoice_no} is not an ordinary domestic taxable supply "
                "(export, SEZ, exempt, nil-rated or reverse charge). Interest follows the "
                "treatment of the supply it arises from (CGST Act s.15(2)(d) [S]), which a "
                "draft cannot reproduce — raise it by hand.")
    if doc.rate_state == "mixed":
        return (BLOCK_MIXED_RATE,
                f"Invoice {doc.invoice_no} has lines at more than one GST rate, so the "
                "interest would have to be apportioned between them. That is a "
                "judgement, not a computation — raise it by hand.")
    if doc.rate_state == "none" or doc.gst_rate_bps is None:
        return (BLOCK_NO_RATE,
                f"Invoice {doc.invoice_no} has no lines to take a GST rate from.")
    return None


def plan_drafts(chargeable: Iterable[ChargeableDoc]) -> tuple[list[DraftGroup], list[dict]]:
    """Group what can be drafted and name what cannot.

    A group is documents sharing (GST rate, inter-state flag, place of supply):
    one draft invoice is one tax computation, and putting a 5% line and an 18%
    line on one invoice is fine for the engine but a choice for the CA, so they
    are separate drafts the CA can see side by side. Deterministic order.
    """
    groups: dict[tuple, list[ChargeableDoc]] = {}
    blocked: list[dict] = []
    for doc in chargeable:
        why = block_reason(doc)
        if why:
            blocked.append({"invoice_id": doc.invoice_id, "invoice_no": doc.invoice_no,
                            "interest_paise": doc.interest_paise,
                            "reason_code": why[0], "reason": why[1]})
            continue
        key = (int(doc.gst_rate_bps), bool(doc.is_interstate), doc.supply_state_code or "")
        groups.setdefault(key, []).append(doc)
    out = [
        DraftGroup(gst_rate_bps=k[0], is_interstate=k[1], supply_state_code=(k[2] or None),
                   documents=tuple(sorted(docs, key=lambda d: d.invoice_no)))
        for k, docs in sorted(groups.items())
    ]
    return out, blocked


def line_description(doc: ChargeableDoc) -> str:
    """The words on one line of a draft. NO RUPEE SIGN: this reaches a PDF, and
    ReportLab's core fonts have no glyph for U+20B9 (it prints a black box)."""
    bps = doc.interest_rate_bps
    pct = f"{bps // 100}.{bps % 100:02d}".rstrip("0").rstrip(".")
    return (f"Interest for delayed payment of invoice {doc.invoice_no}: "
            f"{doc.days} days from {doc.period_from} to {doc.period_to} at {pct}% a year "
            f"on the balance of Rs.{rupees_paise(doc.outstanding_paise)}")
