"""
Which invoices owe an IRN and have none, and how long is left (GST-20).

WHAT WAS MISSING

    `irn_scope.assess` decides, invoice by invoice, whether CGST Rule 48(4)
    reaches a supply — but only for the invoice somebody has open. Nothing in the
    product listed, across a client or a practice, the in-scope invoices that
    have no recorded IRN. That matters more than most omissions because of
    Rule 48(5): an invoice Rule 48(4) reaches, issued without an IRN, "shall not
    be treated as an invoice" — so the RECIPIENT's input tax credit goes with it,
    and the supplier finds out when a customer asks why their credit is gone.

    The router's own header (`routers/einvoice.py`) records the second half: for
    a taxpayer whose aggregate turnover is ₹10 crore or more, the IRP refuses to
    REGISTER an invoice more than thirty days old (from 01-04-2025). Past that
    the IRN cannot simply be obtained, so a clock matters as much as a list.

WHAT THIS DOES

    It applies `irn_scope.assess` (WHO owes an IRN — never re-derived here) to a
    set of invoices, drops the ones that already carry a live IRN, and for each of
    the rest says where it stands against the IRP's reporting window. It reports.
    It mints no IRN, reaches no portal and files nothing: an IRN is obtained on
    the IRP by a human and RECORDED afterwards (`routers/einvoice.py`).
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT.

THE REPORTING WINDOW IS NOT RULE 48(4) AND IS KEPT APART FROM IT

    Rule 48(4) says which supplies need an IRN, at ₹5 crore and over. The thirty
    days is the IRP's own validation, for ₹10 crore and over — a different
    threshold from a different instrument. So an in-scope invoice of a ₹7 crore
    client OWES an IRN and has NO reporting clock: it is listed, with
    `no_reporting_limit`, rather than dropped (it still has no IRN and Rule 48(5)
    still bites) and rather than given a deadline nobody imposes.

    Four states, and none stands in for another:

        within_window        days left, counted to the day the IRP stops accepting
        last_day             today is the last day
        past_window          the IRP will refuse it; what a CA does next is theirs
        no_reporting_limit   below the ₹10 crore floor; owed, but no clock
        window_unknown       the turnover is unrecorded; the clock is SHOWN as if it
                             applied (the strict reading) and the answer says it
                             is assumed

    An unrecorded turnover is never read as "below the floor": that would hide a
    clock from exactly the client nobody has looked at. `irn_scope.assess` takes
    the same strict reading for the same reason, and it costs a glance.

DAYS, COUNTED INCLUSIVELY

    "Older than thirty days" is read as: an invoice dated on day D can still be
    reported on D + 30 and not on D + 31. So `deadline = D + 30`, `days_left` is
    `deadline - today` (a 29-day-old invoice has one day left, a 30-day-old one has
    none and is on its LAST day, a 31-day-old one is past). The boundary is the
    one place the figure could be off by a day, and the error is stated: it fails
    toward telling the CA sooner, which is the direction that costs a glance.

⚠️  GRADING. The thirty days, the ₹10 crore floor and the 01-04-2025 start are all
    `[S]` — the repo's own note in `routers/einvoice.py` and secondary sources,
    nothing read off the IRP's advisory (every `.gov.in` is refused at this
    environment's proxy). They are NAMED CONSTANTS with `VERIFIED = False`, never
    inline figures, and `tests/test_the_invoices_that_owe_an_irn_and_have_none_are_listed.py`
    pins each so a later correction is deliberate. The turnover that decides
    whether the floor is met is the HIGHEST recorded across `irn_scope`'s own
    qualifying years — the same figure the Rule 48(4) limb uses, which is an
    assumption about which AATO the portal reads and is named as one.

WHAT IT DOES NOT COVER, said on every answer
    * Credit and debit notes. The IRP's limit reaches them too, and
      `einvoice_records` links to a sales invoice only, so there is no record to
      look for. Not guessed at.
    * The first proviso's exempted classes — `irn_scope.EXEMPTED_CLASSES`, which
      it names. Nothing records which class a client is in.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, Optional

from domain.gst import irn_scope, treatment as _treatment

#: Everything about the reporting window is `[S]`: see the header.
VERIFIED = False

#: The IRP refuses to register an invoice older than this. `[S]`.
REPORTING_WINDOW_DAYS = 30

#: The window has been enforced from this date. `[S]`.
WINDOW_IN_FORCE_FROM = "2025-04-01"

#: It binds a taxpayer whose aggregate turnover is at or above this — ₹10 crore.
#: Deliberately its own constant and NOT `irn_scope.THRESHOLDS`: Rule 48(4)'s
#: ₹5 crore and the IRP's ₹10 crore are different instruments. `[S]`.
WINDOW_TURNOVER_FLOOR_PAISE = 10_00_00_000_00

#: How far back the worklist looks unless asked for more. An unbounded look-back
#: is a read proportional to the ledger; and an invoice that lapsed years ago is
#: past any action this list could prompt. `since` widens it and the answer
#: always says what it covered.
DEFAULT_LOOKBACK_DAYS = 120

WITHIN_WINDOW = "within_window"
LAST_DAY = "last_day"
PAST_WINDOW = "past_window"
NO_REPORTING_LIMIT = "no_reporting_limit"
NOT_IN_FORCE = "not_in_force"

IRN_NONE = "none"
IRN_RECORD_PREPARED = "record_prepared_not_generated"
IRN_CANCELLED = "irn_cancelled"

WINDOW_SOURCE = (
    "The thirty-day limit, its ₹10 crore floor and its 01-04-2025 start are "
    "[S]-graded here — taken from the e-invoice router's own note and secondary "
    "sources, not read off the IRP's advisory. The IRP is authoritative: an "
    "invoice this list calls within the window may already be refused there."
)
WINDOW_TURNOVER_BASIS = (
    "Whether the ₹10 crore floor is met is judged on the highest aggregate "
    "turnover recorded for the client across the years Rule 48(4) reads on — "
    "the same figure that decides whether an IRN is owed at all. Which AATO the "
    "IRP itself reads for the limit could not be confirmed."
)
NOT_COVERED = (
    "Credit notes and debit notes are not listed. The IRP's limit reaches them "
    "too, but an e-invoice record here links to a sales invoice only, so there "
    "is nothing to look for. Check them on the portal."
)
PAST_WINDOW_IS_NOT_OURS_TO_DECIDE = (
    "Past the window the IRP will refuse the invoice, and Rule 48(5) then treats "
    "it as no invoice at all. What to do about that — cancel and reissue, or "
    "seek relief — is a decision for the CA; this product does not take it."
)
UNKNOWN_TURNOVER_WINDOW = (
    "No aggregate turnover is recorded for this client, so whether the IRP's "
    "thirty-day limit binds is not known. The clock is shown as if it did — the "
    "strict reading — and is marked assumed."
)


def _iso(value) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def reporting_window(invoice_date: str, highest_aato_paise: Optional[int],
                     as_at: date) -> dict:
    """Where this invoice stands against the IRP's reporting window.

    `highest_aato_paise` is None where nobody has recorded one, which is a
    THIRD state and never 0: 0 is a client who turned over nothing and is below
    the floor; None is nobody having said, and is shown strictly.
    """
    issued = _iso(invoice_date)
    base = {
        "days": REPORTING_WINDOW_DAYS,
        "floor_paise": WINDOW_TURNOVER_FLOOR_PAISE,
        "in_force_from": WINDOW_IN_FORCE_FROM,
        "deadline": None, "days_left": None, "assumed": False,
        "applies": None, "status": NO_REPORTING_LIMIT,
    }
    if highest_aato_paise is not None:
        applies = int(highest_aato_paise) >= WINDOW_TURNOVER_FLOOR_PAISE
        base["applies"] = applies
        if not applies:
            return base                       # owed, with no clock
    else:
        base["assumed"] = True                # strict, and said so
    if issued is None:
        # An invoice with no usable date cannot be run against a clock, and
        # inventing one would be the failure this module exists to stop.
        base["status"] = WITHIN_WINDOW
        base["assumed"] = True
        return base

    in_force = _iso(WINDOW_IN_FORCE_FROM)
    if in_force and as_at < in_force:
        base["status"] = NOT_IN_FORCE
        return base
    deadline = issued + timedelta(days=REPORTING_WINDOW_DAYS)
    left = (deadline - as_at).days
    base["deadline"] = deadline.isoformat()
    base["days_left"] = left
    base["status"] = (PAST_WINDOW if left < 0
                      else LAST_DAY if left == 0 else WITHIN_WINDOW)
    return base


def irn_state(records: Iterable[dict]) -> Optional[str]:
    """What the e-invoice records matched to ONE invoice say — None if it has a
    live IRN, otherwise which kind of "no IRN" this is.

    A LIVE IRN is a `generated` record that carries one. A `cancelled` record
    carried an IRN once and no longer does — the invoice is back to having none,
    and the CA needs to know it is that case and not a never-attempted one. A
    `draft` record is a prepared record with nothing obtained from the portal.
    """
    rows = list(records or [])
    for r in rows:
        if str(r.get("status") or "").lower() == "generated" and str(r.get("irn") or "").strip():
            return None
    if any(str(r.get("status") or "").lower() == "cancelled" for r in rows):
        return IRN_CANCELLED
    if rows:
        return IRN_RECORD_PREPARED
    return IRN_NONE


def assess_invoice(inv: dict, records: Iterable[dict],
                   highest_aato_paise: Optional[int],
                   as_at: date) -> Optional[dict]:
    """One worklist row, or None where the invoice is not on the list.

    Not on the list: Rule 48(4) does not reach it (asked of `irn_scope`, whose
    supply limb short-circuits first, so a B2C invoice never even reaches the
    turnover), or it already carries a live IRN.
    """
    kind = _treatment.treatment_for_invoice(
        supply_type=inv.get("supply_type"),
        invoice_type=inv.get("invoice_type"),
        igst_paise=int(inv.get("igst_paise") or 0),
    )
    scope = irn_scope.assess(
        treatment=kind,
        recipient_gstin=(inv.get("customers") or {}).get("gstin"),
        invoice_date=str(inv.get("invoice_date") or ""),
        highest_aato_paise=highest_aato_paise,
    )
    if scope.verdict != "required":
        return None
    state = irn_state(records)
    if state is None:
        return None
    window = reporting_window(str(inv.get("invoice_date") or ""),
                              highest_aato_paise, as_at)
    return {
        "invoice_id": inv.get("id"),
        "client_id": inv.get("client_id"),
        "invoice_no": inv.get("invoice_no"),
        "invoice_date": str(inv.get("invoice_date") or "")[:10],
        "customer_name": (inv.get("customers") or {}).get("name"),
        "total_paise": int(inv.get("total_paise") or 0),
        "treatment": kind,
        "irn_state": state,
        "why_in_scope": scope.supply_reason,
        "turnover_unknown": bool(scope.turnover_unknown),
        "window": window,
        # `irn_scope`'s own gap sentences. Carried so the caller can say each
        # ONCE rather than per row, and never worded again here.
        "scope_gaps": list(scope.gaps),
    }


#: Most urgent first within an equal date: a lapsed invoice is the one nothing
#: can be done about by waiting, so it sorts with the rest by AGE, not apart.
def sort_oldest_first(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: (r.get("invoice_date") or "",
                                       str(r.get("invoice_no") or "")))


def counts(rows: list[dict]) -> dict:
    out = {WITHIN_WINDOW: 0, LAST_DAY: 0, PAST_WINDOW: 0, NO_REPORTING_LIMIT: 0,
           NOT_IN_FORCE: 0, "window_assumed": 0, "total": len(rows)}
    for r in rows:
        w = r["window"]
        out[w["status"]] = out.get(w["status"], 0) + 1
        if w.get("assumed"):
            out["window_assumed"] += 1
    return out
