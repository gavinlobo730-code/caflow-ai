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

    THE BALANCE ON EACH LATE DAY IS THE BALANCE THAT DAY (POST-A-101). The figure used to be the balance as it stands
    TODAY applied to the whole late period. Where a part-payment arrived during that period today's balance is LOWER than
    what was owed before it, so the figure UNDERSTATED the interest the client's own terms allow (the old caveat said it
    overstated, which was the wrong way round); only a debit note that raised the balance during the period made it
    overstate, and an as-at date earlier than today used balances after payments that had not yet been made. Now a
    document carries the history of what moved its balance (`BalanceChange`): money the customer paid reduces the balance
    from the date it arrived (a receipt allocated to it, a posted bank line matched to it); an amount credited by a credit
    note or applied from the customer's credit is treated as never owed (`FROM_THE_START`, the reading that cannot
    overstate, since nothing records why or when it was credited); and what a debit note adds bears no interest here
    (`OUTSIDE_THE_WINDOW`: it is a separate demand on its own terms). On the day a
    payment arrives the balance before it is still owed (the day it is received is a late day on the amount it pays, as
    the as-at date is), so the base for a late day is today's balance plus every change dated that day or later. An as-at
    date earlier than today therefore uses the balances as they were then. The history is used only when it accounts for
    the whole of what the invoice shows as settled (`history_ties`); otherwise the document falls back to today's balance
    and SAYS so, because a history that misses a payment would understate.

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

from domain.money_sentence import rupee_text

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


#: A change dated FROM_THE_START has already happened on every late day (an amount treated as never owed); one dated
#: OUTSIDE_THE_WINDOW never happens inside it (an amount that bears no interest here). See `BalanceChange`.
FROM_THE_START = date.min
OUTSIDE_THE_WINDOW = date.max


@dataclass(frozen=True)
class BalanceChange:
    """Something that moved a document's balance on a date. `amount_paise` > 0 REDUCES it (a receipt allocated to it, a credit
    note); < 0 increases it (a debit note)."""

    on: date
    amount_paise: int


def history_ties(*, total_paise: int, outstanding_paise: int, changes: Iterable[BalanceChange]) -> bool:
    """Whether the changes account for exactly what the document shows as settled: total less what is open today."""
    return sum(int(c.amount_paise) for c in changes) == int(total_paise) - int(outstanding_paise)


def balance_paise_days(outstanding_paise: int, changes: Iterable[BalanceChange], after: date, through: date) -> int:
    """Σ over the days AFTER `after` up to and including `through` of the balance that day, in paise-days.

    The balance on a day is today's balance plus every change dated that day or later (a change has not happened yet on the
    days before it, and a payment received on a day still leaves that day owed). Never below nil. Integer arithmetic only, so
    the interest is rounded once, on the whole product, as the convention says.
    """
    if through <= after:
        return 0
    points = sorted(changes, key=lambda c: c.on)
    pending = sum(int(c.amount_paise) for c in points if c.on > after)
    i = next((k for k, c in enumerate(points) if c.on > after), len(points))
    total, day = 0, after + timedelta(days=1)
    while day <= through:
        while i < len(points) and points[i].on < day:
            pending -= int(points[i].amount_paise)
            i += 1
        end = through if i >= len(points) else min(through, points[i].on)
        total += max(0, int(outstanding_paise) + pending) * ((end - day).days + 1)
        day = end + timedelta(days=1)
    return total


def as_date(value) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        # Not a date. A DATE or timestamp column always reads back as ISO text, so a stored one never lands here: this is an absent value or text that
        # was never a date, and None says there is none.
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
    #: "history" when the balance was followed day by day, "today" when today's balance was applied to the whole period.
    balance_basis: str = "today"


def document_interest(
    *, outstanding_paise: int, invoice_date, due_date, terms: Terms, as_of: date,
    charged_through: Optional[date] = None, history: Optional[tuple[BalanceChange, ...]] = None,
) -> DocumentInterest:
    """One overdue invoice's interest, or the reason there is none.

    `charged_through` is the as-at date a STANDING draft already covers: the
    next period starts the day after it, so the same days are never charged
    twice. It is the caller's to derive, because whether a draft still stands
    is a fact about another invoice.

    `history` is what moved the balance, by date (`BalanceChange`); given, the base on each late day is the balance that day,
    and None means today's balance over the whole period (the caller passes None when the history does not tie).
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
    basis = "today" if history is None else "history"
    if days == 0:
        return DocumentInterest(status=COVERED, days_charged=0, balance_basis=basis, **base)
    if terms.rate_bps == 0:
        return DocumentInterest(status=WAIVED, days_charged=days, balance_basis=basis, **base)
    if history is None:
        amount = interest_paise(int(outstanding_paise), int(terms.rate_bps), days)
    else:
        paise_days = balance_paise_days(int(outstanding_paise), history, period_from, as_of)
        amount = round_half_up(paise_days * int(terms.rate_bps), 10_000 * YEAR_DAYS) if paise_days > 0 else 0
    if amount == 0:
        return DocumentInterest(status=ROUNDS_TO_NIL, days_charged=days, balance_basis=basis, **base)
    return DocumentInterest(status=CHARGE, interest_paise=amount, days_charged=days, balance_basis=basis, **base)


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
    #: What moved the balance, by date, when it ties to what the invoice shows as settled; None = today's balance.
    history: Optional[tuple[BalanceChange, ...]] = None
    #: Why the history was not used, in a sentence, when it was read and did not tie (or could not be read).
    history_note: Optional[str] = None
    #: Which: "untied" (read, and it does not account for what is settled) or "unread" (the reads failed).
    history_reason: Optional[str] = None


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
            "invoice's balance outstanding on each late day (today's balance where "
            "a row says so), in actual days over a 365-day year, from "
            "the day after the start date and any grace up to and including the "
            f"as-at date ({as_of.isoformat()}); half a paisa and over rounds up, once "
            "on the whole sum."),
    }


#: Said on every answer that carries a figure. The first is a limitation of the
#: method and the second is the statutory reading, graded.
CAVEAT_BALANCE_FOLLOWED = (
    "The base on each late day is the invoice's balance on that day. A receipt allocated to it, or a bank line settling it, "
    "reduces the balance from the date the money arrived, and the day it arrives is still a late day on the amount it pays. "
    "An amount credited to it by a credit note, or applied from the customer's credit, is treated as never owed: whether it "
    "corrected the price or recorded a later return, or when the credited money arrived, is not recorded, and this reading "
    "cannot overstate. The amount a debit note adds bears no interest here; it is a separate demand with its own terms. An "
    "as-at date earlier than today uses the balances as they were then. Only invoices still open today are listed.")


#: What today's balance applied to every late day gets wrong, the right way round: a payment during the period makes today's
#: balance lower than what was owed before it, and today's balance carries what a debit note added, which bears no interest here.
TODAYS_BALANCE_ERRS = ("Today's balance applied to every late day UNDERSTATES the interest where a payment arrived during the late "
                       "period, and OVERSTATES it where a debit note added to the balance, since that amount bears no interest here.")


def caveat_balance_is_todays(untied: int = 0, unread: int = 0) -> str:
    """Said when one or more charged documents fell back to today's balance, naming how many and why."""
    parts = []
    if untied:
        parts.append(f"for {untied} invoice(s) the receipts, bank lines, credits and notes recorded against it do not account for "
                     "everything it shows as settled")
    if unread:
        parts.append(f"for {unread} invoice(s) the receipts, bank lines, credits and notes against it could not be read")
    return ("; ".join(parts)[:1].upper() + "; ".join(parts)[1:] + ", so its interest is on today's balance over the whole late "
            f"period, and the row says why. {TODAYS_BALANCE_ERRS}")


STATUTORY_READING = {
    "section": "CGST Act s.15(2)(d)",
    "grade": "[S]",
    "text": (
        "Interest charged for delayed payment of consideration forms part of "
        "the value of the supply it arises from, so GST is chargeable on it at "
        "the rate of that supply. The draft therefore carries the GST rate of "
        "the invoice it relates to. Whether to raise it as an invoice or as a "
        "debit note, and its time of supply, are the CA's decisions. The "
        "section has not been read against the Act itself; check it before "
        "raising the document."),
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
            charged_through=doc.charged_through, history=doc.history)
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
            "balance_basis": result.balance_basis,
            "balance_note": (doc.history_note if result.balance_basis == "today" else None),
            "balance_reason": (doc.history_reason if result.balance_basis == "today" else None),
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
    # Counted only where the basis can move the figure: a covered row charges nothing new and a waived one charges nothing.
    charged = [d for p in out for d in p["documents"] if d.get("status") in (CHARGE, ROUNDS_TO_NIL) and d.get("balance_basis") == "today"]
    untied = sum(1 for d in charged if d.get("balance_reason") != "unread")
    unread = sum(1 for d in charged if d.get("balance_reason") == "unread")
    caveats = ([CAVEAT_BALANCE_FOLLOWED] + ([caveat_balance_is_todays(untied, unread)] if (untied or unread) else [])
               + [CAVEAT_NOT_POSTED])
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
    #: "history" when the base was the balance on each day, "today" when today's balance was applied to every day.
    balance_basis: str = "today"
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
    base = ("on the balance outstanding on each of those days" if doc.balance_basis == "history"
            else f"on the balance of {rupee_text(doc.outstanding_paise, 'Rs.')}")
    return (f"Interest for delayed payment of invoice {doc.invoice_no}: "
            f"{doc.days} days from {doc.period_from} to {doc.period_to} at {pct}% a year {base}")
