"""Closing a compliance obligation because the return it stands for was recorded as filed elsewhere in the product.

WHY THIS IS ONE MODULE
    A return can be recorded as filed in a WORKSPACE (the GST workspace, the ITR workspace) and an obligation can be
    marked filed on the COMPLIANCE calendar. They are separate trackers that agreed only by luck: a CA who filed a year
    of returns in a workspace saw every one of them Filed beside a calendar that called the same returns overdue
    (POST-A-264 for GST, and the same for the ITR). Each workspace finds ITS obligation by its own rule (a GST return's
    window and its registrations, an ITR's financial year); what happens AFTER the obligation is found is the same, and
    is here so that the two cannot drift apart:

      * it closes the obligation THROUGH `ComplianceRecordService.mark_filed`, the one walk through the lifecycle, so the
        audit and timeline rows and any `filings` write stay the one path they always were;
      * a refusal from that walk is a sentence for the CA and not a failure of the filing, and an obligation filed a
        moment ago by somebody else is reported as already filed;
      * a walk that stops part way is answered with the status the obligation was really left in, never with "nothing
        changed";
      * the obligation's status is re-read through the same firm-and-client listing that found it, never by id alone.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT: this records a filing the CA has already made on the portal. It transmits
    nothing.
"""
from __future__ import annotations

from typing import Any, Optional

from core.exceptions import NotFoundError, ValidationError
from core.observability import capture_soft_failure
from repositories.compliance_records_repository import compliance_records_repo

#: The answer's `state`, one word a screen can branch on. Only CLOSED means this call moved the obligation.
CLOSED = "closed"
ALREADY_FILED = "already_filed"
NOT_ON_THE_CALENDAR = "not_on_the_calendar"
NOT_ALLOWED = "not_allowed"
NOT_CLOSED = "not_closed"

FROM_COMPLIANCE = "It can be marked filed from Compliance."


def answer(state: str, message: str, obligation_id: Optional[str] = None) -> dict[str, Any]:
    return {"state": state, "closed": state == CLOSED, "obligation_id": obligation_id, "message": message}


def status_now(firm_id: str, client_id: str, compliance_type: str, record_id: str) -> Optional[str]:
    """The obligation's status as the database holds it now, or None if it cannot be read. Read through the same
    firm-and-client-scoped listing that found it, not by id alone."""
    try:
        rows = compliance_records_repo.find_all(firm_id=firm_id, client_id=client_id, compliance_type=compliance_type)
    except Exception:                                           # noqa: BLE001
        return None
    return next((r.get("status") for r in rows if r.get("id") == record_id), None)


def mark_filed_and_answer(
    record: dict, *, what: str, operation: str, firm_id: str, client_id: str, compliance_type: str,
    filed_date: Optional[str], arn: Optional[str], actor: Optional[dict],
) -> dict[str, Any]:
    """Walk `record` (an open obligation of this firm and client) to Filed and say what happened.

    `what` is the obligation as the CA reads it ("GSTR-3B obligation for June 2026"); `operation` names the caller for
    the error reporter. An unexpected failure is reported and answered; it never propagates, because the return IS
    filed and the CA can still mark the obligation from Compliance."""
    # Imported here: the domain module imports repositories and services lazily in places, and this module is imported
    # by routers at load.
    from domain.compliance_record_service import compliance_record_service
    try:
        compliance_record_service.mark_filed(
            record["id"], firm_id=firm_id, actor=actor, acknowledgement_no=arn or None, filed_date=filed_date)
    except ValidationError as refusal:
        # A refusal can arrive because the obligation was filed a moment ago by someone else; say what is true now.
        if status_now(firm_id, client_id, compliance_type, record["id"]) in ("Filed", "Completed"):
            return answer(ALREADY_FILED, f"The {what} was recorded as filed just now by someone else, so it was left "
                                         "as it is.", record.get("id"))
        return answer(NOT_CLOSED, f"The {what} was left open: {str(refusal).partition(': ')[2] or refusal}",
                      record.get("id"))
    except NotFoundError:
        return answer(NOT_ON_THE_CALENDAR, f"The {what} could not be found to update, so none was closed.",
                      record.get("id"))
    except Exception as exc:                                    # noqa: BLE001
        # The walk through the lifecycle is several writes. A failure part way leaves the obligation where the last
        # successful step put it, and the answer says where, not "nothing changed".
        capture_soft_failure(exc, operation=operation, firm_id=firm_id, client_id=client_id)
        now = status_now(firm_id, client_id, compliance_type, record["id"])
        if now in ("Filed", "Completed"):
            return answer(CLOSED, f"The {what} is now marked filed on the compliance calendar.", record.get("id"))
        return answer(NOT_CLOSED, f"The {what} could not be completed"
                                  f"{f' (it now reads {now})' if now else ''}. {FROM_COMPLIANCE}", record.get("id"))
    return answer(CLOSED, f"The {what} is now marked filed on the compliance calendar.", record.get("id"))
