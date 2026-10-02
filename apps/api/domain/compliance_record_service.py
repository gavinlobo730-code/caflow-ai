"""
Compliance Record Engine.
Manages compliance records lifecycle: Not Started → Filed.
Risk scoring and client health scores.
"""
from datetime import date, timedelta
from typing import Optional

from core.exceptions import ValidationError, NotFoundError
from core.ist_clock import ist_now, ist_today
from repositories.compliance_records_repository import compliance_records_repo
from repositories.client_repository import client_repo
from core import db_provider

# Valid status transitions. Phase 4.4 adds the terminal Filed -> Completed step
# (Module D progression: ... -> Ready To File -> Filed -> Completed).
VALID_TRANSITIONS: dict[str, list[str]] = {
    "Not Started": ["Awaiting Documents", "In Progress", "Overdue"],
    "Awaiting Documents": ["In Progress", "Overdue"],
    "In Progress": ["Ready For Review", "Awaiting Documents", "Overdue"],
    "Ready For Review": ["Ready To File", "In Progress"],
    "Ready To File": ["Filed"],
    "Filed": ["Completed"],
    "Completed": [],
    "Overdue": ["In Progress", "Awaiting Documents"],
}


def _assert_return_period_has_ended(record: dict) -> None:
    """apex-overview-practice-02: a RETURN cannot be marked Filed before its
    own period has ended — a June GSTR-3B filed in May is nonsensical however
    the button was reached. `RETURN_OBLIGATION_TYPES` (services/
    compliance_obligation_service.py, the obligation-type vocabulary's home)
    is the one list of which obligation types this reaches; PMT-06, the
    monthly TDS deposit and advance tax are deliberately not in it, because
    those are lawfully paid mid-period.

    A manual record (no `obligation_type` — Module D's own create_record
    never sets one) is never a return by this test, so a CA's own free-form
    compliance_type entries are untouched."""
    # Lazy import: services/compliance_obligation_service.py already imports
    # this module (lazily, inside its own functions, for exactly this
    # reason), so this mirrors the existing services-from-domain pattern
    # `_audit_transition` uses two functions below for audit_service/
    # timeline_service rather than adding a new module-level cross-import.
    from services.compliance_obligation_service import RETURN_OBLIGATION_TYPES
    obligation_type = record.get("obligation_type")
    if obligation_type not in RETURN_OBLIGATION_TYPES:
        return
    period_end = record.get("period_end")
    if not period_end:
        return  # compliance_records.period_end is DATE NOT NULL; nothing to check if a row somehow lacks one
    period_end_d = date.fromisoformat(str(period_end)[:10])
    if ist_today() < period_end_d:
        raise ValidationError(
            "status",
            f"Cannot mark this {obligation_type} record Filed before its own "
            f"period ends on {period_end_d.isoformat()}. A return declares a "
            f"period that has not closed yet."
        )


def clean_filed_date(v: object) -> str:
    """YYYY-MM-DD, a real date, and not in the future (IST).

    The shape check keeps a typo out of `filings.filed_date`, which is a DATE
    column — without it a malformed value is a 500 from Postgres rather than a
    422 the CA can act on. The future check is the same reasoning as the value
    itself: a return cannot have been filed tomorrow, and this is the field the
    audit reads to say when it went. IST, because a filing date is an Indian
    calendar date. Raises ValueError with the sentence, so a Pydantic validator
    and the service can both use it — the two doors that take a date."""
    try:
        when = date.fromisoformat(str(v or "").strip())
    except ValueError:
        raise ValueError("filed_date must be YYYY-MM-DD")
    if when > ist_today():
        raise ValueError("filed_date cannot be in the future")
    return when.isoformat()


def _closes_a_gst_period(record: dict) -> bool:
    """Whether recording this obligation as filed closes a GST period — the
    two returns of supplies, GSTR-1 and GSTR-3B. Asked of the service that owns
    the map, never restated here."""
    from services.gst_filing_record_service import FILING_TYPE_FOR_RETURN
    return str(record.get("obligation_type") or "") in FILING_TYPE_FOR_RETURN


def _filed_date_for(record: dict, data: dict) -> Optional[str]:
    """The date this obligation was filed on, as the CA said it.

    For a GSTR-1 or GSTR-3B the date is REQUIRED and is never defaulted. The
    filing is what `journal_period_lock_reason` reads, and the lock message
    tells the CA "this return was filed on <date>" — a date the software made up
    because nobody typed one is a fact about the portal it does not hold. The
    calendar path (`PATCH /calendar/{id}/filed`) has always required it; this
    path used to stamp today and lock nothing. Every other obligation keeps the
    old behaviour (the caller may omit it and today is recorded), because it
    closes no period and the date is a convenience there.

    A return cannot be filed before the period it declares has ended, so a date
    earlier than `period_end` is refused for every return type — the same rule
    `_assert_return_period_has_ended` applies to the clock, applied to the date
    somebody typed."""
    given = data.get("filed_date")
    if given:
        try:
            filed = clean_filed_date(given)
        except ValueError as e:
            raise ValidationError("filed_date", str(e))
    else:
        filed = record.get("filed_date") or None
    if filed is None:
        if _closes_a_gst_period(record):
            raise ValidationError(
                "filed_date",
                f"Say the date this {record.get('obligation_type')} was filed on the "
                f"portal. Recording it closes the period for new entries, and the "
                f"lock message quotes the date — so it is asked for, not assumed.")
        return None
    from services.compliance_obligation_service import RETURN_OBLIGATION_TYPES
    period_end = record.get("period_end")
    if (record.get("obligation_type") in RETURN_OBLIGATION_TYPES and period_end
            and str(filed)[:10] < str(period_end)[:10]):
        raise ValidationError(
            "filed_date",
            f"A return cannot have been filed on {str(filed)[:10]}, before the "
            f"period it declares ended on {str(period_end)[:10]}.")
    return str(filed)[:10]


# The handle the `filings` row is written through, or None where there is
# no database (mock mode). One function so a test can hand in a double.
_filing_db = db_provider.request_db_or_none


def _close_the_period(record: dict, filed_date: Optional[str], arn: Optional[str]) -> dict:
    """Record the filing this obligation stands for, so the books inside its
    period stop moving — and say what happened either way.

    WHAT WAS WRONG (gst-27, practice_management-15, frontend_ux-26)
        Mark Filed on /deadlines and on the client's Compliance tab walked a
        `compliance_records` row to Filed and wrote nothing else. The only
        table `journal_period_lock_reason` reads is `public.filings`, so a
        return the CA had just told the product was filed did NOT lock its
        period — the books could still move under a return already at the
        government. GST-14 fixed that for the `/gst` tracker
        (`compliance_calendar`) and left these two doors, which are the ones a
        CA uses, open. Two trackers, one return, opposite answers.

    It is asked from `update_record`, the ONE place an obligation becomes
    Filed, so `mark-filed`, `transition` and `PATCH /compliance-records` all
    record the filing rather than each remembering to.

    The result is ALWAYS a dict with the same four keys, `recorded` false where
    nothing was written and `reason` saying why — a tick that closed nothing has
    to be visible, per type, exactly as on the calendar path. Nothing is
    swallowed: a failure to write the row propagates and the obligation stays
    where it was, because "Filed but unlocked" is the defect and an open
    obligation the CA can retry is not.
    """
    from services import gst_filing_record_service as filings
    otype = str(record.get("obligation_type") or "")
    if not _closes_a_gst_period(record):
        return {"recorded": False, "reason": filings.not_recorded_reason(otype),
                "locked_from": None, "locked_to": None}
    db = _filing_db()
    if db is None:
        return {"recorded": False,
                "reason": "Recording a filing needs the database, so no period was locked.",
                "locked_from": None, "locked_to": None}
    row = filings.record_obligation_filing(db, record=record, filed_date=filed_date or "", arn=arn)
    if not row:
        return {"recorded": False,
                "reason": "This obligation carries no period dates, so there is no period to lock.",
                "locked_from": None, "locked_to": None}
    return {"recorded": True, "reason": None,
            "locked_from": row["period_start"], "locked_to": row["period_end"]}


def _compute_risk_score(record: dict) -> int:
    """Compute risk score (0-100) integer. Never float."""
    status = record["status"]
    due = record["due_date"]
    updated = record.get("updated_at", record["created_at"])

    if status == "Filed":
        return 0
    if status == "Ready To File":
        return 20

    today_d = ist_today()
    due_d = date.fromisoformat(due[:10])
    days_until_due = (due_d - today_d).days

    if status == "Overdue" or days_until_due < 0:
        return 90  # CRITICAL

    if days_until_due <= 7:
        return 75  # HIGH

    if status == "Awaiting Documents":
        try:
            updated_d = date.fromisoformat(updated[:10])
            days_waiting = (today_d - updated_d).days
            if days_waiting >= 14:
                return 60  # AT RISK
        except (ValueError, TypeError):
            pass

    if status in ("Not Started", "In Progress"):
        if days_until_due <= 14:
            return 50
        return 25

    return 30


def _audit_transition(record: dict, old_status: str, new_status: str,
                      firm_id: Optional[str], actor: Optional[dict]) -> None:
    """Record a compliance status transition in the firm audit log + client timeline.
    Best-effort: never raises (compliance work must not be blocked by logging)."""
    actor = actor or {}
    try:
        from services.audit_service import log_event
        log_event(firm_id or record.get("firm_id") or "", "compliance_record", record["id"],
                  "status_change", actor_id=actor.get("auth_user_id"), actor_email=actor.get("email"),
                  old_data={"status": old_status}, new_data={"status": new_status},
                  metadata={"compliance_type": record.get("compliance_type"),
                            "obligation_type": record.get("obligation_type")})
    except Exception:  # pragma: no cover - audit is non-fatal
        pass
    try:
        from services.timeline_service import timeline_service
        timeline_service.log(record.get("client_id", ""), "compliance",
                             f"Compliance {new_status}",
                             f"{record.get('obligation_type') or record.get('compliance_type','')} "
                             f"{record.get('period_label','')}: {old_status} → {new_status}",
                             "success" if new_status in ("Filed", "Completed") else "info",
                             firm_id=firm_id or record.get("firm_id", ""),
                             entity_type="compliance_record", entity_id=record["id"])
    except Exception:  # pragma: no cover
        pass


class ComplianceRecordService:

    def list_records(
        self,
        firm_id: Optional[str] = None,
        client_id: Optional[str] = None,
        status: Optional[str] = None,
        compliance_type: Optional[str] = None,
        exclude_statuses: Optional[list[str]] = None,
        due_from: Optional[str] = None,
        due_to: Optional[str] = None,
    ) -> list[dict]:
        records = compliance_records_repo.find_all(
            firm_id=firm_id,
            client_id=client_id,
            status=status,
            compliance_type=compliance_type,
            exclude_statuses=exclude_statuses,
            due_from=due_from,
            due_to=due_to,
        )
        return [{**r, "risk_score": _compute_risk_score(r)} for r in records]

    def get_record(self, record_id: str, firm_id: Optional[str] = None) -> dict:
        r = compliance_records_repo.find_by_id(record_id)
        if not r:
            raise NotFoundError("ComplianceRecord", record_id)
        # Tenant isolation: reject cross-firm access
        if firm_id and r.get("firm_id") and r["firm_id"] != firm_id:
            raise NotFoundError("ComplianceRecord", record_id)
        return {**r, "risk_score": _compute_risk_score(r)}

    def create_record(self, data: dict, firm_id: str) -> dict:
        client_id = data["client_id"]
        compliance_type = data["compliance_type"]
        period_start = data.get("period_start") or ""
        # App-level dedup for the manual-create path: the generator's
        # (obligation_type, period_start) uniqueness (migration 108) doesn't
        # apply here since manual records never set obligation_type — without
        # this check a CA could freely create duplicate periods for the same
        # client/compliance_type. Only enforced when a real period is supplied
        # (an empty period carries no dedup meaning). DB-backed by migration
        # 168's partial index.
        if period_start:
            existing = compliance_records_repo.find_all(
                firm_id=firm_id, client_id=client_id, compliance_type=compliance_type)
            if any(str(r.get("period_start") or "")[:10] == str(period_start)[:10] for r in existing):
                raise ValidationError(
                    "period_start",
                    f"A {compliance_type} compliance record for this client and period already exists.")
        # compliance_records.period_start and period_end are DATE NOT NULL
        # (migration 003). This wrote "" for a missing period, which Postgres
        # answers with 22007 invalid_input_syntax_for_type_date and rejects the
        # WHOLE insert — and None would fail the same insert with 23502. So a
        # manual record with no period has never been creatable against the
        # real database, in either direction; the mock suite asserted that it
        # was because an in-memory dict takes any value. Refusing here is what
        # production has always enforced, said out loud.
        period_end = data.get("period_end") or ""
        missing = [n for n, v in (("period_start", period_start),
                                  ("period_end", period_end)) if not v]
        if missing:
            raise ValidationError(
                missing[0],
                "A compliance record needs a period: give period_start and "
                "period_end as dates (YYYY-MM-DD). The obligation generator "
                "derives them from the financial year; a record created by hand "
                "has to state them, because the table requires them."
            )
        # A record is not BORN filed. `update_record` is the one place an
        # obligation becomes Filed, because that is where the filing is recorded
        # and the period closed; creating a record already in a terminal status
        # would be a second way to "Filed" that writes no filing and locks
        # nothing — the defect this service's Filed path was rewritten to end.
        if data.get("status") in ("Filed", "Completed"):
            raise ValidationError(
                "status",
                f"A compliance record cannot be created as {data['status']}. Create it "
                f"open and mark it filed, which records the filing date and closes the "
                f"period.")
        payload = {
            "firm_id": firm_id,  # Always from current_user, never from request body
            "client_id": client_id,
            # client_name is deliberately NOT written: production's
            # compliance_records has no such column, and PostgREST answers
            # PGRST204 to the whole insert rather than ignoring the key. It only
            # ever reached here as None — which the repository's None-filter
            # dropped — so it was one caller away from breaking every create.
            "compliance_type": compliance_type,
            "period_label": data.get("period_label", ""),
            "period_start": period_start,
            "period_end": period_end,
            "status": data.get("status", "Not Started"),
            "due_date": data["due_date"],
            "assigned_to": data.get("assigned_to"),
            "priority": data.get("priority", "medium"),
            "notes": data.get("notes"),
            "filed_date": None,
            "acknowledgement_no": None,
        }
        record = compliance_records_repo.create(payload)
        return {**record, "risk_score": _compute_risk_score(record)}

    def update_record(self, record_id: str, data: dict, firm_id: Optional[str] = None,
                      actor: Optional[dict] = None) -> dict:
        record = self.get_record(record_id, firm_id=firm_id)
        updates: dict = {}
        old_status = record["status"]
        new_status = None
        filing_date: Optional[str] = None

        if "status" in data:
            new_status = data["status"]
            allowed = VALID_TRANSITIONS.get(old_status, [])
            if new_status not in allowed:
                raise ValidationError(
                    "status",
                    f"Cannot transition from '{old_status}' to '{new_status}'. Allowed: {allowed}"
                )
            if new_status == "Filed":
                _assert_return_period_has_ended(record)
                filing_date = _filed_date_for(record, data)
            updates["status"] = new_status
            if new_status == "Filed":
                if filing_date:
                    updates["filed_date"] = filing_date
                elif not record.get("filed_date"):
                    # filed_date IS a date column, and a filing date is a date —
                    # a return is filed on a day, not at an instant. Reached
                    # only by an obligation that closes no GST period: for
                    # GSTR-1 and GSTR-3B the date was required above.
                    updates["filed_date"] = ist_today().isoformat()
            if new_status == "Completed" and not record.get("completed_at"):
                # completed_at is timestamptz, and this wrote a bare date.
                # Postgres accepts that — it parses '2026-09-08' as midnight in
                # the session's timezone — so nothing failed and the column
                # quietly recorded 00:00 UTC instead of when the work was
                # actually finished. Not a rejected write; a fabricated one,
                # which is harder to notice. ist_now() carries a real instant,
                # and its offset, so the stored UTC value is right and the
                # presentation rule (CLAUDE.md: report in IST) still applies at
                # the point of display.
                updates["completed_at"] = ist_now().isoformat()

        for field in ("notes", "assigned_to", "priority", "acknowledgement_no"):
            if field in data:
                updates[field] = data[field]

        # The filing is recorded BEFORE the obligation moves, so a failure
        # leaves the obligation open for a retry rather than Filed with its
        # period unlocked. record_filing is idempotent on the period, so the
        # retry writes the same row.
        filing_lock = None
        if new_status == "Filed":
            filing_lock = _close_the_period(
                record, updates.get("filed_date") or record.get("filed_date"),
                (updates.get("acknowledgement_no") or record.get("acknowledgement_no") or None))

        updated = compliance_records_repo.update(record_id, updates)
        if not updated:
            raise NotFoundError("ComplianceRecord", record_id)

        # Module D/H: every status transition is audited + timelined (best-effort,
        # never blocks the mutation). Reuses the firm-wide audit_log + client timeline.
        if new_status and new_status != old_status:
            _audit_transition(record, old_status, new_status, firm_id, actor)
        out = {**updated, "risk_score": _compute_risk_score(updated)}
        if filing_lock is not None:
            # A RESPONSE-only key, never a column: what the caller must be able
            # to see about whether the period closed.
            out["filing_lock"] = filing_lock
        return out

    # Deterministic path from any open status to Filed, skipping the
    # documents-waiting branch (not applicable when a CA is asserting the
    # simple, terminal fact "this was filed").
    _FAST_FORWARD_PATH = ["In Progress", "Ready For Review", "Ready To File", "Filed"]

    def mark_filed(self, record_id: str, firm_id: Optional[str] = None,
                   actor: Optional[dict] = None, acknowledgement_no: Optional[str] = None,
                   filed_date: Optional[str] = None) -> dict:
        """R3.13e: one-click "mark as filed" for callers migrating off
        compliance_calendar's simple pending/filed model — walks the real
        multi-step workflow (VALID_TRANSITIONS) via its shortest path rather
        than bypassing it, so every intermediate step is still individually
        valid and still audited/timelined. A no-op if already Filed/Completed.

        Everything that can refuse the LAST step is asked BEFORE the first, so a
        refusal never leaves the obligation half-walked at "Ready To File". The
        date and the ARN ride on that last step — one update, one filings row —
        rather than the ARN being written afterwards, which is too late for the
        filing record that carries it."""
        record = self.get_record(record_id, firm_id=firm_id)
        if record["status"] in ("Filed", "Completed"):
            updated = {**record, "filing_lock": {
                "recorded": False, "locked_from": None, "locked_to": None,
                "reason": "This obligation was already recorded as filed, so nothing "
                          "was recorded this time."}}
            if acknowledgement_no:
                updated = {**self.update_record(record_id, {"acknowledgement_no": acknowledgement_no},
                                                firm_id=firm_id, actor=actor),
                           "filing_lock": updated["filing_lock"]}
        else:
            _assert_return_period_has_ended(record)
            _filed_date_for(record, {"filed_date": filed_date})
            start = self._FAST_FORWARD_PATH.index(record["status"]) \
                if record["status"] in self._FAST_FORWARD_PATH else -1
            for step in self._FAST_FORWARD_PATH[start + 1:]:
                step_data: dict = {"status": step}
                if step == "Filed":
                    if filed_date:
                        step_data["filed_date"] = filed_date
                    if acknowledgement_no:
                        step_data["acknowledgement_no"] = acknowledgement_no
                updated = self.update_record(record_id, step_data, firm_id=firm_id, actor=actor)
        return updated

    @staticmethod
    def score_from_records(records: list[dict]) -> tuple[int, list[dict]]:
        """Pure health-score math over an already-fetched record set (100,
        minus deductions). Factored out so callers who already have the
        firm's full compliance_records in memory (e.g. a dashboard summing
        risk across many clients) can score every client without an extra
        DB round trip per client — see domain/task_service.py."""
        overdue_records = [r for r in records if r["status"] == "Overdue"]
        high_risk_records = [r for r in records if r["risk_score"] >= 70 and r["status"] != "Overdue"]
        missing_docs = len([r for r in records if r["status"] == "Awaiting Documents"])

        score: int = 100
        breakdown = []

        for _ in overdue_records:
            score -= 20
            breakdown.append({"label": "Overdue compliance record", "deduction": 20})

        for _ in high_risk_records:
            score -= 10
            breakdown.append({"label": "High-risk compliance record", "deduction": 10})

        for _ in range(missing_docs):
            score -= 5
            breakdown.append({"label": "Missing/awaited document", "deduction": 5})

        return max(0, score), breakdown

    def get_client_health_score(self, client_id: str, firm_id: Optional[str] = None) -> dict:
        """Client health score 0-100. Start at 100, subtract for risks. Integer arithmetic only."""
        client = client_repo.find_by_id(client_id)
        if not client:
            raise NotFoundError("Client", client_id)
        # Tenant isolation
        if firm_id and client.get("firm_id") and client["firm_id"] != firm_id:
            raise NotFoundError("Client", client_id)

        records = self.list_records(client_id=client_id, firm_id=firm_id)
        overdue_records = [r for r in records if r["status"] == "Overdue"]
        missing_docs = len([r for r in records if r["status"] == "Awaiting Documents"])
        score, breakdown = self.score_from_records(records)
        risk_level = (
            "critical" if score < 40 else
            "high" if score < 60 else
            "medium" if score < 80 else
            "low"
        )

        return {
            "client_id": client_id,
            "client_name": client["client_name"],
            "health_score": score,
            "risk_level": risk_level,
            "overdue_records": len(overdue_records),
            "missing_documents": missing_docs,
            "breakdown": breakdown,
        }

    def get_firm_summary(self, firm_id: Optional[str] = None, allowed_client_ids: Optional[set] = None) -> dict:
        """Firm-wide compliance summary. F2: when allowed_client_ids is provided
        (a non firm-wide caller), aggregate only over those assigned clients;
        None ⇒ firm-wide (unscoped). Default None preserves existing callers."""
        all_records = self.list_records(firm_id=firm_id)
        if allowed_client_ids is not None:
            all_records = [r for r in all_records if str(r.get("client_id")) in allowed_client_ids]
        today_d = ist_today()
        week_end = (today_d + timedelta(days=7)).isoformat()
        today_str = today_d.isoformat()
        this_month_start = today_d.replace(day=1).isoformat()

        due_this_week = len([
            r for r in all_records
            if r["status"] != "Filed" and today_str <= r["due_date"] <= week_end
        ])
        overdue = len([r for r in all_records if r["status"] == "Overdue"])
        ready_for_review = len([r for r in all_records if r["status"] == "Ready For Review"])
        ready_to_file = len([r for r in all_records if r["status"] == "Ready To File"])
        filed_this_month = len([
            r for r in all_records
            if r["status"] == "Filed" and (r.get("filed_date") or "") >= this_month_start
        ])

        clients = client_repo.find_all(firm_id=firm_id)
        if allowed_client_ids is not None:
            clients = [c for c in clients if str(c.get("id")) in allowed_client_ids]
        high_risk_clients = sum(
            1 for c in clients
            if self.get_client_health_score(c["id"], firm_id=firm_id)["health_score"] < 50
        )

        return {
            "due_this_week": due_this_week,
            "overdue": overdue,
            "ready_for_review": ready_for_review,
            "ready_to_file": ready_to_file,
            "filed_this_month": filed_this_month,
            "high_risk_clients": high_risk_clients,
        }


compliance_record_service = ComplianceRecordService()
