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

    It REOPENS the monthly deposit obligations the challan closed, when it can tell which they are and the caller may. Since migration
    569 the closer records, on each obligation it closes, the ids of the challans that covered the month (`closing_tds_challan_ids`),
    so the months to reopen are exactly the filed ones that name this challan, wherever in the register's order it was paired.
    The caller must hold `compliance.approve`, the tier that undoes a filing (`POST /api/compliance/obligations/{id}/reopen`); a
    caller who does not has the months NAMED instead, with who can reopen them, and nothing is reopened for them. Each month goes
    back to Ready To File through `compliance_record_service.reopen_record` (the reason on the row, the audit log and the timeline
    as for any reopening, in the caller's name), and a month that cannot be reopened is named with the sentence, never failing
    the retraction. A month that reads filed in the challan's quarter with NO record of what closed it (closed before the record
    existed, or by a person from Compliance) is named and left, as before: the register cannot say whether this challan was one of
    them. A filed month that names OTHER challans only is not mentioned: this challan did not close it.

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


def _month_label(record: dict) -> str:
    start = str(record.get("period_start") or "")[:10]
    try:
        d = date.fromisoformat(start)
    except ValueError:
        return str(record.get("period_label") or "a month")
    return f"{deposit_closer._MONTH_NAMES[d.month - 1]} {d.year}"                      # noqa: SLF001


def _join(labels: list[str]) -> str:
    return ", ".join(labels[:-1]) + " and " + labels[-1] if len(labels) > 1 else labels[0]


def calendar_effect(*, firm_id: str, client_id: str, challan: dict, reason: Optional[str] = None,
                    actor: Optional[dict] = None) -> dict[str, Any]:
    """What the retraction did to the compliance calendar, and the one sentence for it: `{reopened, named, unknown, failed, note}`.

    `reopened`, `named` and `failed` are the months (as "July 2025") the challan closed, which are recorded on the obligation; `unknown`
    are filed months of its quarter with no record of what closed them. With `actor` the months the challan closed are reopened (the
    caller has checked that this person may approve Compliance); without it they are only named. NEVER FAILS THE RETRACTION: the
    challan is already gone, and a failure to read the calendar is reported and answered with nothing."""
    empty: dict[str, Any] = {"reopened": [], "reopened_ids": [], "named": [], "unknown": [], "failed": [], "note": None}
    if deposit_due.is_salary(str(challan.get("section") or "")):
        return empty                        # a salary challan is not what the monthly non-salary deposit obligations close from
    try:
        quarter_starts = {date(y, m, 1).isoformat() for y, m in deposit_closer.months_of(
            str(challan.get("financial_year") or ""), str(challan.get("quarter") or ""))}
        filed = [rec for rec in compliance_records_repo.find_all(firm_id=firm_id, client_id=client_id,
                                                                 compliance_type=deposit_closer.COMPLIANCE_TYPE)
                 if rec.get("obligation_type") == deposit_closer.OBLIGATION_TYPE and rec.get("status") in ("Filed", "Completed")]
    except Exception as exc:                                # noqa: BLE001
        from core.observability import capture_soft_failure
        capture_soft_failure(exc, operation="tds.challan_retraction.calendar_note", firm_id=firm_id, client_id=client_id)
        return empty
    mine, unknown = [], []
    for rec in filed:
        recorded = deposit_closer.closed_on(rec)
        if recorded is not None and str(challan.get("id")) in recorded:
            mine.append(rec)
        elif recorded is None and str(rec.get("period_start") or "")[:10] in quarter_starts:
            unknown.append(rec)
    out = {**empty, "unknown": [_month_label(r) for r in unknown]}
    for rec in mine:
        label = _month_label(rec)
        if actor is None:
            out["named"].append(label)
            continue
        problem = _reopen(rec, challan=challan, reason=reason or "", actor=actor, firm_id=firm_id, client_id=client_id)
        if problem is None:
            out["reopened"].append(label)
            out["reopened_ids"].append(rec["id"])
        else:
            out["failed"].append(f"{label} ({problem})")
    out["note"] = _calendar_sentence(out)
    return out


def _reopen(rec: dict, *, challan: dict, reason: str, actor: dict, firm_id: str, client_id: str) -> Optional[str]:
    """Reopen one obligation the retracted challan closed. None when it was reopened, otherwise the sentence for why not."""
    from core.exceptions import NotFoundError, ValidationError
    from domain.compliance_record_service import MAX_REOPEN_REASON_CHARS, compliance_record_service
    why = (f"The TDS challan {challan.get('challan_no') or 'recorded for it'} that this month was closed on was retracted: "
           f"{reason}")[:MAX_REOPEN_REASON_CHARS]
    try:
        compliance_record_service.reopen_record(rec["id"], why, firm_id=firm_id, actor=actor)
    except ValidationError as refusal:
        return str(getattr(refusal, "message", None) or refusal)
    except NotFoundError:
        return "it could not be found to update"
    except Exception as exc:                                # noqa: BLE001
        from core.observability import capture_soft_failure
        capture_soft_failure(exc, operation="tds.challan_retraction.reopen", firm_id=firm_id, client_id=client_id)
        return "it could not be reopened just now"
    return None


_WHO = "a Manager or Partner can reopen it, with a reason, from Deadlines or the client's Compliance tab"


def _calendar_sentence(effect: dict[str, Any]) -> Optional[str]:
    parts = []
    if effect["reopened"]:
        parts.append(f"The monthly TDS deposit (non-salary) on the compliance calendar for {_join(effect['reopened'])} was closed on "
                     "this challan, so it has been reopened and reads Ready To File again. It is closed again when the challans "
                     "recorded for the quarter cover it in full and on time.")
    if effect["named"]:
        parts.append(f"The monthly TDS deposit (non-salary) for {_join(effect['named'])} was closed on this challan and still reads "
                     f"filed on the compliance calendar. Your access does not include approving Compliance, so it was not reopened; "
                     f"{_WHO}.")
    if effect["failed"]:
        parts.append(f"The monthly TDS deposit (non-salary) for {_join(effect['failed'])} was closed on this challan and could not be "
                     f"reopened; {_WHO}.")
    if effect["unknown"]:
        parts.append(f"The compliance calendar still shows the monthly TDS deposit (non-salary) for {_join(effect['unknown'])} as "
                     "filed. Retracting the challan does not reopen it, because nothing recorded which challan closed that month. "
                     f"If this challan closed one of them, {_WHO}.")
    return " ".join(parts) or None


def calendar_note(*, firm_id: str, client_id: str, challan: dict) -> Optional[str]:
    """The calendar sentence for a retraction that reopens nothing (the months are named). Kept as the plain question the tests and
    the older callers ask; `retract` asks `calendar_effect` with the caller so the months can be reopened."""
    return calendar_effect(firm_id=firm_id, client_id=client_id, challan=challan)["note"]


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


def retract(db, *, firm_id: str, client_id: str, challan: dict, reason: str, actor: dict,
            may_reopen: bool = False) -> dict[str, Any]:
    """Retract the challan already read for this firm and client. Returns what to answer: the retracted challan's identifying
    facts, the obligations it reopened (`may_reopen`: the caller holds `compliance.approve`), and the calendar and statement
    sentences when there are any. Raises `RetractionRefused`."""
    why = clean_reason(reason)
    write_audit_or_refuse(firm_id=firm_id, challan=challan, reason=why, actor=actor)
    if not delete_row(db, firm_id=firm_id, client_id=client_id, challan_id=challan["id"]):
        # The audit entry says "retract" for a row another request had already removed. That is a true entry about a request, and
        # the answer is the honest one: it is gone.
        raise RetractionRefused("That challan is no longer in the register: somebody retracted it just now.", status=404)
    effect = calendar_effect(firm_id=firm_id, client_id=client_id, challan=challan, reason=why,
                             actor=actor if may_reopen else None)
    return {
        "retracted": challan["id"],
        "challan_no": challan.get("challan_no"),
        "payment_date": challan.get("payment_date"),
        "total_paise": challan.get("total_paise"),
        "reopened_obligation_ids": effect["reopened_ids"],
        "calendar_note": effect["note"],
        "statement_note": statement_note(db, firm_id=firm_id, client_id=client_id, challan=challan),
    }
