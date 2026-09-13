"""Recurring journals: templates in, DRAFT manual journals out (ACC-06).

WHAT THIS REPLACED

    `/accounting/recurring` kept every template a CA set up in
    `localStorage["practicesync_recurring_templates"]`, worked out the next due
    date in the browser, and POSTED NOTHING. The hub card said "Automate
    monthly, quarterly & yearly entries" while nothing anywhere posted a due
    template, so a CA had every reason to believe the firm's recurring journals
    were configured. A partner who set them up on their laptop found an empty
    screen on the office machine.

    This is the last of ACC-06's three screens and the only genuine build among
    them: the budget went onto `account_budgets` (migration 376) and the
    retainer tracker onto `billing_schedules`, which was already built.

WHAT IT PRODUCES, AND WHAT IT REFUSES TO

    A DRAFT manual journal, through `manual_journal_service.create`, which goes
    through the one posting kernel like everything else. NEVER a posted one.
    This product acts unprompted in exactly one place — a bank rule a Manager
    has marked trusted — and that was a recorded owner decision of 2026-09-03,
    not a default to copy. A recurring journal is a saving of TYPING, not of
    judgement: the amounts repeat, the decision to book them does not.

    A generated entry is stamped `source_type = 'manual'` deliberately. Every
    guard reads that column — `manual_journal_service._is_manual` is
    `(source_type or "") == "manual"` and migrations 275/338 refuse the edit
    and discard paths on anything else — so any other value would hand the CA
    a draft they are invited to review and forbidden to amend. The link back to
    the template lives on `journal_entries.recurring_template_id` and in
    `recurring_journal_runs`, neither of which any guard reads.

IDEMPOTENCY, AND WHY A FAILURE IS RECORDED RATHER THAN RETRIED

    One row in `recurring_journal_runs` per (template, occurrence). It is both
    the history the screen shows and the record that makes generation safe to
    run twice — the same shape `recurring_invoice_runs` has had since Phase
    4.3, and the reason the two features share `domain/recurrence.py` rather
    than each owning a cadence engine.

    A failed occurrence is written with `status='failed'` and its reason, and
    the template does NOT advance. A template that cannot post needs a CA, not
    another attempt at 06:00 tomorrow; and advancing past a failure would skip
    a month silently, which is the one outcome worse than a visible error.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import HTTPException

from core.db_paging import fetch_all
from domain import recurrence as _rec

_logger = logging.getLogger("caflow.recurring_journal")

_USE_MOCK = not os.environ.get("SUPABASE_URL")

_STATUSES = ("active", "paused", "archived")

# Mock stores (mock mode only).
MOCK_JOURNAL_TEMPLATES: list[dict] = []
MOCK_JOURNAL_RUNS: list[dict] = []


def _db():
    from core.supabase_client import get_supabase
    return get_supabase()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> date:
    from core.ist_clock import ist_today
    return ist_today()


# ── validation ───────────────────────────────────────────────────────────────

def _validate(data: dict, lines: list[dict]) -> None:
    """Everything the database would refuse, refused here with a sentence.

    Checked at SAVE time rather than left to generation: generation runs
    unattended at 06:00 IST, which is the worst place to discover that a
    template was never postable.
    """
    if not data.get("client_id"):
        raise HTTPException(status_code=422, detail="client_id is required.")
    if not (data.get("name") or "").strip():
        raise HTTPException(status_code=422, detail="A template needs a name.")
    if data.get("frequency") not in _rec.FREQUENCIES:
        raise HTTPException(status_code=422,
                            detail=f"frequency must be one of {', '.join(_rec.FREQUENCIES)}.")
    # `or 1` would turn a caller's explicit 0 into 1 — the classic falsy-zero
    # slip, and here it would silently accept a day the CHECK refuses.
    raw_day = data.get("day_of_month")
    day = 1 if raw_day is None else int(raw_day)
    if not 1 <= day <= 28:
        # 29, 30 and 31 do not exist in every month. A template that slides to
        # the 28th in February posts on a date nobody chose.
        raise HTTPException(status_code=422, detail="day_of_month must be between 1 and 28.")
    if not data.get("start_date"):
        raise HTTPException(status_code=422, detail="start_date is required.")
    if data.get("end_date") and str(data["end_date"]) < str(data["start_date"]):
        raise HTTPException(status_code=422, detail="end_date cannot precede start_date.")
    status = (data.get("status") or "active").lower()
    if status not in _STATUSES:
        raise HTTPException(status_code=422,
                            detail=f"status must be one of {', '.join(_STATUSES)}.")

    if len(lines) < 2:
        raise HTTPException(status_code=422,
                            detail="A journal template needs at least two lines.")
    debit = credit = 0
    for i, ln in enumerate(lines, start=1):
        if not ln.get("account_id"):
            raise HTTPException(status_code=422, detail=f"Line {i} has no account.")
        d = int(ln.get("debit_paise") or 0)
        c = int(ln.get("credit_paise") or 0)
        if d < 0 or c < 0:
            raise HTTPException(status_code=422, detail=f"Line {i} has a negative amount.")
        if (d == 0) == (c == 0):
            raise HTTPException(
                status_code=422,
                detail=f"Line {i} must be a debit OR a credit, not both and not neither.")
        debit += d
        credit += c
    if debit == 0:
        raise HTTPException(status_code=422, detail="A template cannot be for nil.")
    if debit != credit:
        # Refused HERE, not at the kernel. The kernel's assertion is the last
        # line of defence and its message is about a journal; a CA saving a
        # template needs to be told the template does not balance, while they
        # are looking at it.
        raise HTTPException(
            status_code=422,
            detail=f"Template does not balance: debit {debit} paise != credit {credit} paise.")


# ── CRUD ─────────────────────────────────────────────────────────────────────

def _line_rows(template_id: str, lines: list[dict]) -> list[dict]:
    return [{
        "template_id": template_id,
        "account_id": ln["account_id"],
        "debit_paise": int(ln.get("debit_paise") or 0),
        "credit_paise": int(ln.get("credit_paise") or 0),
        "narration": ln.get("narration"),
        "sort_order": i,
    } for i, ln in enumerate(lines)]


def _insert_lines(db, template_id: str, lines: list[dict]):
    """The ONE place lines are written, and the column names are a LITERAL.

    `tests/test_backend_columns_exist_pg.py` checks a write's columns against
    the real schema only when it can read them, and it cannot read
    `.insert(_line_rows(...))` — a call. A comprehension over dict literals it
    CAN read, so the names are restated here once rather than at both call
    sites, and both create and update go through this.
    """
    rows = _line_rows(template_id, lines)
    return db.table("recurring_journal_template_lines").insert([{
        "template_id": r["template_id"],
        "account_id": r["account_id"],
        "debit_paise": r["debit_paise"],
        "credit_paise": r["credit_paise"],
        "narration": r["narration"],
        "sort_order": r["sort_order"],
    } for r in rows]).execute()


def create_template(firm_id: str, data: dict, created_by: Optional[str] = None,
                    db=None) -> dict:
    lines = list(data.get("lines") or [])
    _validate(data, lines)
    start = str(data["start_date"])[:10]
    # The first occurrence is the start date itself, which is what
    # `next_occurrence(..., after=None)` answers. A caller may pin a later one.
    next_run = str(data.get("next_run_date") or start)[:10]

    if _USE_MOCK and db is None:
        row = {
            "id": str(uuid.uuid4()), "firm_id": firm_id,
            "client_id": data["client_id"], "name": data["name"].strip(),
            "frequency": data["frequency"],
            "day_of_month": int(data.get("day_of_month") or 1),
            "narration": data.get("narration"),
            "start_date": start, "end_date": data.get("end_date"),
            "next_run_date": next_run,
            "status": (data.get("status") or "active").lower(),
            "created_by": created_by, "created_at": _now_iso(), "updated_at": _now_iso(),
        }
        row["lines"] = _line_rows(row["id"], lines)
        MOCK_JOURNAL_TEMPLATES.append(row)
        return row

    db = db or _db()
    created = db.table("recurring_journal_templates").insert({
        "firm_id": firm_id,
        "client_id": data["client_id"],
        "name": data["name"].strip(),
        "frequency": data["frequency"],
        "day_of_month": int(data.get("day_of_month") or 1),
        "narration": data.get("narration"),
        "start_date": start,
        "end_date": data.get("end_date"),
        "next_run_date": next_run,
        "status": (data.get("status") or "active").lower(),
        "created_by": created_by,
    }).execute().data[0]
    _insert_lines(db, created["id"], lines)
    created["lines"] = _line_rows(created["id"], lines)
    return created


def update_template(firm_id: str, template_id: str, data: dict, db=None) -> Optional[dict]:
    """Change a template. Lines are REPLACED wholesale when supplied — a diff
    would have to decide what an unchanged line is, and a journal's lines have
    no natural identity beyond their order."""
    existing = get_template(firm_id, template_id, db=db)
    if not existing:
        return None
    merged = {**existing, **{k: v for k, v in data.items() if v is not None}}
    lines = list(data["lines"]) if data.get("lines") is not None else list(existing.get("lines") or [])
    _validate(merged, lines)

    fields = {k: merged[k] for k in
              ("name", "frequency", "day_of_month", "narration",
               "start_date", "end_date", "next_run_date", "status")
              if k in merged}
    fields["name"] = str(fields.get("name") or "").strip()
    fields["day_of_month"] = int(fields.get("day_of_month") or 1)

    if _USE_MOCK and db is None:
        row = next((t for t in MOCK_JOURNAL_TEMPLATES
                    if t["id"] == template_id and t["firm_id"] == firm_id), None)
        if row is None:
            return None
        row.update(fields)
        row["updated_at"] = _now_iso()
        if data.get("lines") is not None:
            row["lines"] = _line_rows(template_id, lines)
        return row

    db = db or _db()
    fields["updated_at"] = _now_iso()
    res = (db.table("recurring_journal_templates").update(fields)
           .eq("id", template_id).eq("firm_id", firm_id).execute())
    if not res.data:
        return None
    if data.get("lines") is not None:
        db.table("recurring_journal_template_lines").delete().eq(
            "template_id", template_id).execute()
        _insert_lines(db, template_id, lines)
    out = res.data[0]
    out["lines"] = _line_rows(template_id, lines)
    return out


def get_template(firm_id: str, template_id: str, db=None) -> Optional[dict]:
    if _USE_MOCK and db is None:
        return next((t for t in MOCK_JOURNAL_TEMPLATES
                     if t["id"] == template_id and t["firm_id"] == firm_id), None)
    db = db or _db()
    rows = (db.table("recurring_journal_templates").select("*")
            .eq("id", template_id).eq("firm_id", firm_id).limit(1).execute().data) or []
    if not rows:
        return None
    row = rows[0]
    row["lines"] = (db.table("recurring_journal_template_lines")
                    .select("id, template_id, account_id, debit_paise, credit_paise, "
                            "narration, sort_order")
                    .eq("template_id", template_id).order("sort_order")
                    .execute().data) or []
    return row


def list_templates(firm_id: str, client_id: Optional[str] = None,
                   status: Optional[str] = None, db=None) -> list[dict]:
    if _USE_MOCK and db is None:
        out = [t for t in MOCK_JOURNAL_TEMPLATES if t["firm_id"] == firm_id]
        if client_id:
            out = [t for t in out if t["client_id"] == client_id]
        if status:
            out = [t for t in out if t.get("status") == status]
        return sorted(out, key=lambda t: (t.get("next_run_date") or "", t.get("name") or ""))

    db = db or _db()
    def _q():
        q = (db.table("recurring_journal_templates")
             .select("id, firm_id, client_id, name, frequency, day_of_month, narration, "
                     "start_date, end_date, next_run_date, status, created_by, "
                     "created_at, updated_at")
             .eq("firm_id", firm_id))
        if client_id:
            q = q.eq("client_id", client_id)
        if status:
            q = q.eq("status", status)
        return q
    rows = fetch_all(_q, label="recurring_journal_templates.list")
    if not rows:
        return rows
    # One read for every template's lines rather than one per template: the
    # screen renders the accounts on each row, and N+1 round trips to Mumbai is
    # the shape CLAUDE.md's reporting rule exists to prevent.
    ids = [r["id"] for r in rows]
    lines = fetch_all(
        lambda: (db.table("recurring_journal_template_lines")
                 .select("id, template_id, account_id, debit_paise, credit_paise, "
                         "narration, sort_order")
                 .in_("template_id", ids)),
        label="recurring_journal_template_lines.list")
    by_template: dict[str, list[dict]] = {}
    for ln in sorted(lines, key=lambda l: (l["template_id"], l.get("sort_order") or 0)):
        by_template.setdefault(ln["template_id"], []).append(ln)
    for r in rows:
        r["lines"] = by_template.get(r["id"], [])
    return sorted(rows, key=lambda t: (t.get("next_run_date") or "", t.get("name") or ""))


def delete_template(firm_id: str, template_id: str, db=None) -> bool:
    """Remove a template. The journals it already generated are untouched:
    they are ordinary manual journals and deleting the template that suggested
    one has nothing to do with whether it was right."""
    if _USE_MOCK and db is None:
        before = len(MOCK_JOURNAL_TEMPLATES)
        MOCK_JOURNAL_TEMPLATES[:] = [
            t for t in MOCK_JOURNAL_TEMPLATES
            if not (t["id"] == template_id and t["firm_id"] == firm_id)]
        return len(MOCK_JOURNAL_TEMPLATES) < before
    db = db or _db()
    res = (db.table("recurring_journal_templates").delete()
           .eq("id", template_id).eq("firm_id", firm_id).execute())
    return bool(res.data)


# ── what is due ──────────────────────────────────────────────────────────────

def due_occurrences(template: dict, as_of=None) -> list[str]:
    """Every occurrence on or before `as_of` that the template has not passed,
    oldest first, bounded by MAX_CATCHUP_PER_RUN.

    A template dormant for two years must not generate twenty-four drafts on
    the morning somebody switches it on — the bound is the same one the
    recurring invoices use, and it is a bound rather than a silent skip so the
    remainder is generated on the next run rather than lost.
    """
    as_of = _rec.to_date(as_of) if as_of else _today()
    if (template.get("status") or "active") != "active":
        return []
    start = template["start_date"]
    end = _rec.to_date(template["end_date"]) if template.get("end_date") else None
    cur = _rec.to_date(template.get("next_run_date") or start)
    out: list[str] = []
    while cur <= as_of and len(out) < _rec.MAX_CATCHUP_PER_RUN:
        if end and cur > end:
            break
        out.append(cur.isoformat())
        nxt = _rec.next_occurrence(template["frequency"], start, cur)
        if nxt is None or nxt <= cur:
            break
        cur = nxt
    return out


def preview(template: dict, count: int = 5) -> list[str]:
    """The next few dates this template will generate on. Read-only."""
    return _rec.preview_occurrences(template, count=count)


# ── generation ───────────────────────────────────────────────────────────────

def _run_row(firm_id: str, template_id: str, occurrence: str, db=None) -> Optional[dict]:
    if _USE_MOCK and db is None:
        return next((r for r in MOCK_JOURNAL_RUNS
                     if r["template_id"] == template_id
                     and r["occurrence_date"] == occurrence), None)
    db = db or _db()
    rows = (db.table("recurring_journal_runs")
            .select("id, template_id, occurrence_date, journal_entry_id, status, detail")
            .eq("firm_id", firm_id).eq("template_id", template_id)
            .eq("occurrence_date", occurrence).limit(1).execute().data) or []
    return rows[0] if rows else None


def _record_run(firm_id: str, template_id: str, occurrence: str, status: str,
                journal_entry_id: Optional[str], detail: Optional[dict], db=None) -> dict:
    row = {
        "firm_id": firm_id, "template_id": template_id,
        "occurrence_date": occurrence, "journal_entry_id": journal_entry_id,
        "status": status, "detail": detail,
    }
    if _USE_MOCK and db is None:
        row["id"] = str(uuid.uuid4())
        row["created_at"] = _now_iso()
        MOCK_JOURNAL_RUNS.append(row)
        return row
    db = db or _db()
    return db.table("recurring_journal_runs").insert({
        "firm_id": firm_id,
        "template_id": template_id,
        "occurrence_date": occurrence,
        "journal_entry_id": journal_entry_id,
        "status": status,
        "detail": detail,
    }).execute().data[0]


def generate_for_occurrence(firm_id: str, template: dict, occurrence: str,
                            actor_id: Optional[str] = None, db=None) -> dict:
    """One DRAFT manual journal for one occurrence. Idempotent.

    Returns {created, run, journal_entry_id, reason}. `created=False` with a
    run already present is the ordinary re-run case and is not an error.
    """
    existing = _run_row(firm_id, template["id"], occurrence, db=db)
    if existing and existing.get("status") == "generated":
        return {"created": False, "run": existing,
                "journal_entry_id": existing.get("journal_entry_id"),
                "reason": "already generated"}

    lines = list(template.get("lines") or [])
    payload = {
        "client_id": template["client_id"],
        "entry_date": occurrence,
        "narration": template.get("narration") or template.get("name"),
        "entry_type": "Journal",
        # DRAFT, always. See the module docstring: the machine saves the
        # typing, never the judgement.
        "status": "draft",
        "lines": [{"account_id": ln["account_id"],
                   "debit_paise": int(ln.get("debit_paise") or 0),
                   "credit_paise": int(ln.get("credit_paise") or 0),
                   "narration": ln.get("narration")} for ln in lines],
    }

    from services.manual_journal_service import manual_journal_service
    try:
        entry = manual_journal_service.create(
            db if db is not None else (None if _USE_MOCK else _db()),
            firm_id, payload, actor_id=actor_id)
    except HTTPException as e:
        # RECORDED, not retried. A template that cannot post needs a CA — and
        # the template does not advance, so the occurrence is still owed rather
        # than silently skipped.
        run = _record_run(firm_id, template["id"], occurrence, "failed", None,
                          {"error": str(e.detail)}, db=db)
        _logger.warning("recurring journal %s/%s failed: %s",
                        template["id"], occurrence, e.detail)
        return {"created": False, "run": run, "journal_entry_id": None,
                "reason": str(e.detail)}

    entry_id = entry.get("id")
    _stamp_entry(firm_id, entry_id, template["id"], occurrence, db=db)
    run = _record_run(firm_id, template["id"], occurrence, "generated", entry_id, None, db=db)
    return {"created": True, "run": run, "journal_entry_id": entry_id, "reason": None}


def _stamp_entry(firm_id: str, entry_id: Optional[str], template_id: str,
                 occurrence: str, db=None) -> None:
    """Link the entry back to its template WITHOUT touching source_type.

    `source_type` stays 'manual' so the draft remains editable and discardable
    — every guard reads that column (migrations 275/338). These two columns
    (migration 377) are read by nothing but the history screen, which is
    exactly why they are safe to set.
    """
    if not entry_id or (_USE_MOCK and db is None):
        return
    (db or _db()).table("journal_entries").update({
        "recurring_template_id": template_id,
        "recurring_occurrence": occurrence,
    }).eq("id", entry_id).eq("firm_id", firm_id).execute()


def _advance(firm_id: str, template: dict, to_date_iso: str, db=None) -> None:
    if _USE_MOCK and db is None:
        template["next_run_date"] = to_date_iso
        return
    (db or _db()).table("recurring_journal_templates").update({
        "next_run_date": to_date_iso, "updated_at": _now_iso(),
    }).eq("id", template["id"]).eq("firm_id", firm_id).execute()


def run_due(firm_id: str, client_id: Optional[str] = None, as_of=None,
            actor_id: Optional[str] = None, db=None) -> dict:
    """Generate drafts for every active template whose occurrences are due.

    Idempotent and safe to run repeatedly — manually or from the daily sweep.
    Catches up missed occurrences, bounded. Never issues, posts or emails.
    """
    generated, skipped, failed = [], [], []
    for t in list_templates(firm_id, client_id=client_id, status="active", db=db):
        last_ok: Optional[str] = None
        for occ in due_occurrences(t, as_of=as_of):
            out = generate_for_occurrence(firm_id, t, occ, actor_id=actor_id, db=db)
            entry = {"template_id": t["id"], "occurrence": occ,
                     "journal_entry_id": out.get("journal_entry_id")}
            if out["created"]:
                generated.append(entry)
                last_ok = occ
            elif out["reason"] == "already generated":
                skipped.append(entry)
                last_ok = occ
            else:
                # Stop this template at the first failure: advancing past it
                # would skip the occurrence for ever, and the next one is
                # likely to fail the same way.
                failed.append({**entry, "error": out["reason"]})
                break
        if last_ok:
            nxt = _rec.next_occurrence(t["frequency"], t["start_date"], last_ok)
            end = _rec.to_date(t["end_date"]) if t.get("end_date") else None
            if nxt and (end is None or nxt <= end):
                _advance(firm_id, t, nxt.isoformat(), db=db)
            elif end:
                # Past its end date: the template stops rather than being
                # deleted, so the history and the reason survive.
                _set_status(firm_id, t, "archived", db=db)
    return {"generated": generated, "skipped": skipped, "failed": failed,
            "generated_count": len(generated), "skipped_count": len(skipped),
            "failed_count": len(failed)}


def _set_status(firm_id: str, template: dict, status: str, db=None) -> None:
    if _USE_MOCK and db is None:
        template["status"] = status
        return
    (db or _db()).table("recurring_journal_templates").update({
        "status": status, "updated_at": _now_iso(),
    }).eq("id", template["id"]).eq("firm_id", firm_id).execute()


def history(firm_id: str, template_id: str, db=None) -> list[dict]:
    """Every occurrence this template has generated, newest first."""
    if _USE_MOCK and db is None:
        rows = [r for r in MOCK_JOURNAL_RUNS if r["template_id"] == template_id
                and r["firm_id"] == firm_id]
    else:
        db = db or _db()
        rows = fetch_all(
            lambda: (db.table("recurring_journal_runs")
                     .select("id, template_id, occurrence_date, journal_entry_id, "
                             "status, detail, created_at")
                     .eq("firm_id", firm_id).eq("template_id", template_id)),
            label="recurring_journal_runs.history")
    return sorted(rows, key=lambda r: r.get("occurrence_date") or "", reverse=True)
