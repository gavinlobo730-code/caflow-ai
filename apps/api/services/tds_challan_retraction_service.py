"""Retracting a TDS challan recorded in error (POST-A-362).

WHAT WAS WRONG
    The challan register had list, create and read-by-id and nothing else. A challan keyed under the wrong quarter, the wrong
    amount or the wrong date therefore stayed in the register for good: it counted toward the deposit worksheet, Form 3CD
    clause 34 and the 24Q/26Q build, and, since the TDS deposit closer reads the register on every save, it could close a
    monthly deposit obligation again after a person reopened it (POST-A-267, item 3). A deduction could be deleted; a challan,
    the record of money that left the bank, could not.

WHAT THIS DOES
    `retract` removes ONE challan, at `tds:write` (Manager and above, the tier migration 345 gives DELETE on this table), with a
    required written reason, in this order and for these reasons:

      1. the row is read, scoped to the caller's firm and client, and a row that is not there is "not found";
      2. the whole row and the reason go into `audit_log` FIRST and a failure to write that REFUSES the retraction. `log_event`
         swallows its own failures, which is right for an edit log and wrong here: a statutory register row that is deleted is
         kept only in that entry (retention, Companies Act s.128(5) and the Rules' edit-log proviso: "the log is what is
         immutable, not the entry"), so a retraction with no entry behind it would be the loss of the record;
      3. the row is deleted with its id, firm and client in the filter and answers whether it did, so two Managers pressing the
         button on one challan retract it once and the second is told it is gone.

    It does NOT reopen a monthly deposit obligation the challan helped to close: the register does not record which challan
    closed which month (it pairs challans to months by order), so the answer SAYS which months of the quarter still read filed
    and that a Manager or Partner can reopen any of them (`POST /api/compliance/obligations/{id}/reopen`), exactly as the ESI
    retraction does. A retraction that silently reopened months would be a guess about which ones.

    It does NOT change a TDS statement already recorded as filed either, and says so: the statement is the CA's record of what
    went to the portal, and the register behind it has just changed, so when one for the challan's quarter is recorded as filed
    (or revised) the answer carries `statement_note` saying the two may now disagree. Whether this challan was reported in it is
    not something the register records, so the sentence says "if".

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT: this edits the practice's own register. It transmits nothing.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from core.db_provider import privileged_for
from domain.tds import deposit_due
from repositories.compliance_records_repository import compliance_records_repo
from services import tds_deposit_closes_obligation as deposit_closer

_logger = logging.getLogger("caflow.tds.challan_retraction")

MAX_REASON_CHARS = 500


class RetractionRefused(Exception):
    """A retraction that must not go ahead, with the sentence to show. `status` is the HTTP status the route answers."""

    def __init__(self, sentence: str, status: int = 422):
        super().__init__(sentence)
        self.sentence = sentence
        self.status = status


def clean_reason(reason: Optional[str]) -> str:
    """The reason as it will be kept, or a refusal in words."""
    why = (reason or "").strip()
    if not why:
        raise RetractionRefused("Say why this challan is being retracted. The reason is kept with the challan in the audit log.")
    if len(why) > MAX_REASON_CHARS:
        raise RetractionRefused(f"The reason is too long: keep it to {MAX_REASON_CHARS} characters.")
    return why


def write_audit_or_refuse(*, firm_id: str, challan: dict, reason: str, actor: dict) -> None:
    """Keep the whole challan and the reason in the audit log, or refuse. Not `audit_service.log_event`, which swallows its failures:
    once the row is deleted this entry is the only copy of it."""
    from core.supabase_client import get_service_supabase
    try:
        get_service_supabase().table("audit_log").insert({
            "firm_id": firm_id,
            "actor_id": actor.get("auth_user_id"),          # the AUTH id: that is the audit log's flavour of actor
            "actor_email": actor.get("email"),
            "entity_type": "tds_challan",
            "entity_id": challan.get("id"),
            "action": "retract",
            "old_data": dict(challan),
            "new_data": {"retracted": True, "reason": reason},
            "metadata": {"client_id": challan.get("client_id"), "financial_year": challan.get("financial_year"),
                         "quarter": challan.get("quarter")},
        }).execute()
    except Exception as exc:                                # noqa: BLE001
        from core.observability import capture_soft_failure
        capture_soft_failure(exc, operation="tds.challan_retraction.audit", firm_id=firm_id, client_id=challan.get("client_id"))
        raise RetractionRefused(
            "The challan was not retracted, because the audit log could not be written just now and the audit log is the only "
            "record of a retracted challan. Nothing changed; try again in a moment.", status=503) from exc


def delete_row(db, *, firm_id: str, client_id: str, challan_id: str) -> bool:
    """Delete the challan, filtered by its id, firm and client; True when a row went."""
    res = (privileged_for(db).table("tds_challans").delete()
           .eq("id", challan_id).eq("firm_id", firm_id).eq("client_id", client_id).execute().data)
    return bool(res)


def calendar_note(*, firm_id: str, client_id: str, challan: dict) -> Optional[str]:
    """The sentence to add to the answer when a month of the challan's quarter still reads filed on the compliance calendar, or
    None. NEVER FAILS THE RETRACTION: the challan is already gone, and a failure to read the calendar is reported and answered
    with nothing."""
    if deposit_due.is_salary(str(challan.get("section") or "")):
        return None                         # a salary challan is not what the monthly non-salary deposit obligations close from
    try:
        months = deposit_closer.months_of(str(challan.get("financial_year") or ""), str(challan.get("quarter") or ""))
        wanted = {date(y, m, 1).isoformat(): (y, m) for y, m in months}
        filed = []
        for rec in compliance_records_repo.find_all(firm_id=firm_id, client_id=client_id,
                                                    compliance_type=deposit_closer.COMPLIANCE_TYPE):
            start = str(rec.get("period_start") or "")[:10]
            if rec.get("obligation_type") == deposit_closer.OBLIGATION_TYPE and start in wanted \
                    and rec.get("status") in ("Filed", "Completed"):
                y, m = wanted[start]
                filed.append(f"{deposit_closer._MONTH_NAMES[m - 1]} {y}")                       # noqa: SLF001
    except Exception as exc:                                # noqa: BLE001
        from core.observability import capture_soft_failure
        capture_soft_failure(exc, operation="tds.challan_retraction.calendar_note", firm_id=firm_id, client_id=client_id)
        return None
    if not filed:
        return None
    return (f"The compliance calendar still shows the monthly TDS deposit (non-salary) for {', '.join(filed)} as filed. Retracting "
            "the challan does not reopen it, because the register does not record which challan closed which month. If this "
            "challan closed one of them, a Manager or Partner can reopen it, with a reason, from Deadlines or the client's "
            "Compliance tab.")


#: A statement the CA has recorded as sent to the portal. `revised` is a later version of one that was.
FILED_STATEMENT_STATUSES = ("filed", "revised")

#: The salary statement. Every other form reports a non-salary deposit (resident, non-resident or tax collected at source).
SALARY_STATEMENT = "24Q"


def statement_note(db, *, firm_id: str, client_id: str, challan: dict) -> Optional[str]:
    """The sentence to add when a TDS statement for the challan's quarter, of the kind this deposit is reported on, is recorded as
    filed or revised, or None. NEVER FAILS THE RETRACTION, for the reason `calendar_note` gives."""
    try:
        salary = deposit_due.is_salary(str(challan.get("section") or ""))
        rows = (privileged_for(db).table("tds_returns").select("return_type, status")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .eq("financial_year", challan.get("financial_year")).eq("quarter", challan.get("quarter"))
                .in_("status", list(FILED_STATEMENT_STATUSES)).execute().data) or []
    except Exception as exc:                                # noqa: BLE001
        from core.observability import capture_soft_failure
        capture_soft_failure(exc, operation="tds.challan_retraction.statement_note", firm_id=firm_id, client_id=client_id)
        return None
    if not any((r.get("return_type") == SALARY_STATEMENT) == salary for r in rows):
        return None
    return ("The TDS statement for this quarter is recorded as filed. Retracting a challan changes the register and does not change a "
            "statement already filed, so if this challan was reported in it, the register and the filed statement now disagree.")


def retract(db, *, firm_id: str, client_id: str, challan: dict, reason: str, actor: dict) -> dict[str, Any]:
    """Retract the challan already read for this firm and client. Returns what to answer: the retracted challan's identifying
    facts, and the calendar and statement sentences when there are any. Raises `RetractionRefused`."""
    why = clean_reason(reason)
    write_audit_or_refuse(firm_id=firm_id, challan=challan, reason=why, actor=actor)
    if not delete_row(db, firm_id=firm_id, client_id=client_id, challan_id=challan["id"]):
        # The audit entry says "retract" for a row another request had already removed. That is a true entry about a request, and
        # the answer is the honest one: it is gone.
        raise RetractionRefused("That challan is no longer in the register: somebody retracted it just now.", status=404)
    return {
        "retracted": challan["id"],
        "challan_no": challan.get("challan_no"),
        "payment_date": challan.get("payment_date"),
        "total_paise": challan.get("total_paise"),
        "calendar_note": calendar_note(firm_id=firm_id, client_id=client_id, challan=challan),
        "statement_note": statement_note(db, firm_id=firm_id, client_id=client_id, challan=challan),
    }
