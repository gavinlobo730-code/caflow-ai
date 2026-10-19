"""A GST return recorded as filed in the workspace closes the compliance obligation it stands for (POST-A-264).

WHAT WAS WRONG
    There are two places a CA records that a GSTR-1 or GSTR-3B was filed. The GST workspace's own status door writes the
    return row and the `filings` row that locks the period. The compliance door (`ComplianceRecordService.mark_filed`,
    which Mark Filed on Deadlines and the client's Compliance tab calls) closes the obligation and writes the same
    `filings` row. Only the second knew about the first: it warns when the workspace return is not submitted
    (`routers/compliance._unsubmitted_workspace_return`), and nothing went the other way. So a CA who filed eleven months
    in the workspace saw eleven Filed returns beside a calendar that called the same eleven overdue: on a seeded year, all
    25 GST obligations of one client read Not Started and the firm dashboard counted 384 of 403 overdue.

WHAT THIS DOES
    Once the workspace has recorded a return as filed it asks this module to close the matching obligation THROUGH
    `mark_filed`, so the walk through the lifecycle, the audit and timeline rows and the `filings` write stay the one path
    they always were (the filing row is idempotent on its window, so the second write refreshes the first).

    THE OBLIGATION IS THE ONE WITH THE RETURN'S OWN WINDOW: same type, same first day AND same last day. A QRMP quarter's
    return and its obligation are both keyed by the quarter's first month, but a monthly obligation left behind by a switch
    of frequency starts on the same day and ends a month later, and closing that one for a quarterly return would write a
    second, narrower `filings` row beside the quarter's.

    Things it deliberately does not do, each said in the answer rather than silently:
      * it does not touch an obligation already Filed or Completed (its ARN and date are the CA's);
      * it does not close the obligation while another registration of the same client still has this period's return to
        file: the obligation is per client and the returns are per registration, so closing it on the first would call the
        client filed with a registration outstanding. Only registrations LIVE in the window count (a cancelled one, or one
        that starts later, files nothing for it), and only when they file on the same cycle: a monthly registration and a
        quarterly one beside each other have returns that do not line up with one obligation, so it declines and the CA
        marks it from Compliance when every registration has filed;
      * it does not act for a caller without compliance access, because closing an obligation is a compliance write and the
        GST approval that got us here is a different permission, decided per person;
      * it never fails the filing. The return IS filed; whatever stops the obligation closing is reported in the answer and
        to the error reporter, and the CA can still mark it from Compliance.
    A walk through the lifecycle that stops part way (a database failure at the last step) is answered with the status the
    obligation was really left in, never with "nothing changed". Reopening a return does not reopen its obligation: that is
    a decision for the CA, the same as the period lock it leaves.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT: this records a filing the CA has already made on the portal. It transmits
    nothing.
"""
from __future__ import annotations

from typing import Any, Optional

from core.exceptions import NotFoundError, ValidationError
from core.observability import capture_soft_failure
from domain.gst import return_period
from repositories.compliance_records_repository import compliance_records_repo
from services import client_gst_registration_service as registrations

#: The answer's `state`, one word a screen can branch on. Only CLOSED means this call moved the obligation.
CLOSED = "closed"
ALREADY_FILED = "already_filed"
WAITING_FOR_OTHER_REGISTRATIONS = "waiting_for_other_registrations"
REGISTRATIONS_ON_DIFFERENT_CYCLES = "registrations_on_different_cycles"
NOT_ON_THE_CALENDAR = "not_on_the_calendar"
NOT_ALLOWED = "not_allowed"
NOT_CLOSED = "not_closed"

_LABEL = {"GSTR1": "GSTR-1", "GSTR3B": "GSTR-3B"}
_FROM_COMPLIANCE = "It can be marked filed from Compliance."


def _answer(state: str, message: str, obligation_id: Optional[str] = None) -> dict:
    return {"state": state, "closed": state == CLOSED, "obligation_id": obligation_id, "message": message}


def _submitted_gstins(db, firm_id: str, client_id: str, obligation_type: str, period: str) -> set[str]:
    """The GSTINs whose return of this type for this period is recorded as filed. Each table is a literal."""
    if obligation_type == "GSTR1":
        rows = (db.table("gstr1_returns").select("gstin").eq("firm_id", firm_id).eq("client_id", client_id)
                .eq("period", period).eq("status", "submitted").execute().data) or []
    else:
        rows = (db.table("gstr3b_returns").select("gstin").eq("firm_id", firm_id).eq("client_id", client_id)
                .eq("period", period).eq("status", "submitted").execute().data) or []
    return {str(r.get("gstin") or "").strip().upper() for r in rows}


def _live_in(registration, start: str, end: str) -> bool:
    """Whether the registration was live at any point of [start, end] (ISO dates). A bound it does not carry is open."""
    effective_from = str(registration.effective_from or "")[:10]
    effective_to = str(registration.effective_to or "")[:10]
    return (not effective_from or effective_from <= end) and (not effective_to or effective_to >= start)


def _status_now(firm_id: str, client_id: str, record_id: str) -> Optional[str]:
    """The obligation's status as the database holds it now, or None if it cannot be read. Read through the same
    firm-and-client-scoped listing that found it, not by id alone."""
    try:
        rows = compliance_records_repo.find_all(firm_id=firm_id, client_id=client_id, compliance_type="GST")
    except Exception:                                           # noqa: BLE001
        return None
    return next((r.get("status") for r in rows if r.get("id") == record_id), None)


def close_for_filed_return(
    db, *, firm_id: str, client_id: str, obligation_type: str, period: str, frequency: Optional[str],
    filed_date: Optional[str], arn: Optional[str], actor: Optional[dict], may_write_compliance: bool,
) -> dict[str, Any]:
    """Close the client's `obligation_type` ('GSTR1' or 'GSTR3B') obligation for the return of `period` ('MMYYYY') filed
    under a registration on `frequency`, if it should be.

    Returns `{state, closed, obligation_id, message}`; the message is a sentence for the CA. Ordinary reasons (no
    obligation, already filed, not allowed, another registration to wait for) are states, not exceptions. An unexpected
    failure reading the calendar or the registrations propagates, and the router reports it without failing the filing.
    """
    label = _LABEL.get(obligation_type, obligation_type)
    if not firm_id or not client_id:
        return _answer(NOT_CLOSED, f"The {label} obligation was not matched: the return names no client.")
    if not may_write_compliance:
        return _answer(NOT_ALLOWED, f"Your access does not include Compliance, so the {label} obligation was left open. "
                                    "Someone with Compliance access can mark it filed there.")
    try:
        window = return_period.resolve(period, frequency)
    except ValueError:
        return _answer(NOT_CLOSED, f"The return's period ({period!r}) is not one this can match to the calendar, "
                                   f"so the {label} obligation was left open. {_FROM_COMPLIANCE}")
    what = f"{label} obligation for {window.label}"

    matches = [r for r in compliance_records_repo.find_all(firm_id=firm_id, client_id=client_id, compliance_type="GST")
               if r.get("obligation_type") == obligation_type
               and str(r.get("period_start") or "")[:10] == window.start
               and str(r.get("period_end") or "")[:10] == window.end]
    if not matches:
        return _answer(NOT_ON_THE_CALENDAR, f"No {what} is on the compliance calendar, so none was closed.")
    open_ones = [r for r in matches if r.get("status") not in ("Filed", "Completed")]
    if not open_ones:
        return _answer(ALREADY_FILED, f"The {what} was already recorded as filed, so it was left as it is.",
                       matches[0].get("id"))
    record = open_ones[0]

    filers = [r for r in registrations.held(db, firm_id, client_id)
              if r.files_gstr1_and_3b and _live_in(r, window.start, window.end)]
    if len(filers) > 1:
        if any(return_period.normalise_frequency(r.filing_frequency) != window.frequency for r in filers):
            return _answer(
                REGISTRATIONS_ON_DIFFERENT_CYCLES,
                f"This client has registrations that file {label} on different cycles (monthly and quarterly), whose "
                f"returns do not line up with one obligation, so the {what} was left open. Mark it filed from "
                "Compliance once every registration has filed.", record.get("id"))
        done = _submitted_gstins(db, firm_id, client_id, obligation_type, window.key)
        waiting = sorted(r.gstin for r in filers if str(r.gstin or "").strip().upper() not in done)
        if waiting:
            return _answer(
                WAITING_FOR_OTHER_REGISTRATIONS,
                f"This client files {label} under {len(filers)} registrations. The {what} stays open until "
                f"{', '.join(waiting)} {'is' if len(waiting) == 1 else 'are'} also recorded as filed for it. "
                f"{_FROM_COMPLIANCE}", record.get("id"))

    # Imported here: the domain module imports repositories and services lazily in places, and this module is imported by
    # the router at load.
    from domain.compliance_record_service import compliance_record_service
    try:
        compliance_record_service.mark_filed(
            record["id"], firm_id=firm_id, actor=actor, acknowledgement_no=arn or None, filed_date=filed_date)
    except ValidationError as refusal:
        # A refusal can arrive because the obligation was filed a moment ago by someone else; say what is true now.
        if _status_now(firm_id, client_id, record["id"]) in ("Filed", "Completed"):
            return _answer(ALREADY_FILED, f"The {what} was recorded as filed just now by someone else, so it was left "
                                          "as it is.", record.get("id"))
        return _answer(NOT_CLOSED, f"The {what} was left open: {str(refusal).partition(': ')[2] or refusal}",
                       record.get("id"))
    except NotFoundError:
        return _answer(NOT_ON_THE_CALENDAR, f"The {what} could not be found to update, so none was closed.",
                       record.get("id"))
    except Exception as exc:                                    # noqa: BLE001
        # The walk through the lifecycle is several writes. A failure part way leaves the obligation where the last
        # successful step put it, and the answer says where, not "nothing changed".
        capture_soft_failure(exc, operation="gst_return_closes_obligation.mark_filed", firm_id=firm_id, client_id=client_id)
        now = _status_now(firm_id, client_id, record["id"])
        if now in ("Filed", "Completed"):
            return _answer(CLOSED, f"The {what} is now marked filed on the compliance calendar.", record.get("id"))
        return _answer(NOT_CLOSED, f"The {what} could not be completed"
                                   f"{f' (it now reads {now})' if now else ''}. {_FROM_COMPLIANCE}", record.get("id"))
    return _answer(CLOSED, f"The {what} is now marked filed on the compliance calendar.", record.get("id"))
