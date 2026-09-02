"""
Compliance Obligation orchestration (Phase 4.4).

The OPERATIONAL compliance layer — generation, assignment, escalation, dashboard,
and calendar projection — built strictly on top of what already exists:
  • Due dates           → services/compliance_engine.py (pure, statutory)
  • Obligation entity    → compliance_records (canonical, Decision 1) via compliance_records_repo
  • Lifecycle/transitions→ domain/compliance_record_service.py (Decision 2; +Completed)
  • Engagements          → fee_engagements via engagement_repo (Decision 3)
  • Audit / timeline     → services/audit_service + services/timeline_service (Module H)

NOT a filing engine: it never submits anything, never touches GST/accounting/banking
schemas, and never emails clients (escalations are internal only). All money/date
logic is server-side; the pure helpers here are deterministic and unit-tested.
"""
import os
import logging
from calendar import month_name
from datetime import date, datetime, timezone, timedelta
from typing import Optional

from fastapi import HTTPException

from core.ist_clock import ist_today, ist_fy_label
from services import compliance_engine as ce
from repositories.compliance_records_repository import compliance_records_repo
from repositories.client_repository import client_repo
from repositories.engagement_repository import engagement_repo

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.compliance_ops")

# Engagement statuses whose obligations are actively generated/tracked.
_ACTIVE_ENGAGEMENT_STATUSES = ("Active", "In Progress", "Review")
_OPEN_OBLIGATION = lambda s: s not in ("Filed", "Completed")  # noqa: E731


# ── Pure helpers (deterministic; no I/O) ─────────────────────────────────────

def fy_end_year(financial_year: str) -> int:
    """'2025-26' → 2026 (the calendar year in which 31 Mar falls)."""
    start = int(str(financial_year)[:4])
    return start + 1


def fy_months(financial_year: str) -> list[tuple[int, int]]:
    """The 12 (year, month) pairs of an Indian FY, Apr→Mar."""
    start = int(str(financial_year)[:4])
    out = [(start, m) for m in range(4, 13)] + [(start + 1, m) for m in range(1, 4)]
    return out


def _spec(obligation_type, compliance_type, period_label, period_start, period_end, due) -> dict:
    return {
        "obligation_type": obligation_type,
        "compliance_type": compliance_type,
        "period_label": period_label,
        "period_start": period_start if isinstance(period_start, str) else period_start.isoformat(),
        "period_end": period_end if isinstance(period_end, str) else period_end.isoformat(),
        "due_date": due if isinstance(due, str) else due.isoformat(),
    }


def fy_quarters(financial_year: str) -> list[tuple[int, int, int, int]]:
    """The four GST quarters of an Indian FY as (start_year, start_month,
    end_year, end_month): Apr-Jun, Jul-Sep, Oct-Dec, Jan-Mar."""
    start = int(str(financial_year)[:4])
    return [
        (start, 4, start, 6),
        (start, 7, start, 9),
        (start, 10, start, 12),
        (start + 1, 1, start + 1, 3),
    ]


_QUARTER_LABEL = {4: "Q1 Apr-Jun", 7: "Q2 Jul-Sep", 10: "Q3 Oct-Dec", 1: "Q4 Jan-Mar"}


def _gst_obligations(financial_year: str,
                     frequency: str = ce.MONTHLY,
                     state_code: Optional[str] = None) -> list[dict]:
    """The GST obligations one client owes for one FY.

    A QRMP (quarterly) client owes a DIFFERENT SET, not the same set less
    often: four GSTR-1s and four GSTR-3Bs instead of twelve each, plus eight
    PMT-06 challans, because tax is still paid monthly under Rule 61A. Emitting
    twelve monthly returns for a quarterly filer would put eight deadlines in
    their calendar that do not exist, and omit the eight that do.

    IFF is deliberately NOT generated. It is optional — nothing is due if it is
    not used — and an obligation nobody owes, appearing every month, is how a
    compliance calendar stops being read.
    """
    fye = fy_end_year(financial_year)
    out: list[dict] = []

    if frequency == ce.QUARTERLY:
        for (sy, sm, ey, em) in fy_quarters(financial_year):
            ps = date(sy, sm, 1)
            pe = ce.last_day_of_month(ey, em)
            lbl = f"{_QUARTER_LABEL[sm]} {ey}"
            out.append(_spec("GSTR1", "GST", f"GSTR-1 {lbl}", ps, pe,
                             ce.gstr1_due_date(sy, sm, ce.QUARTERLY)))
            out.append(_spec("GSTR3B", "GST", f"GSTR-3B {lbl}", ps, pe,
                             ce.gstr3b_due_date(sy, sm, ce.QUARTERLY, state_code)))
        # Rule 61A — months 1 and 2 of each quarter are paid by challan.
        for (y, m) in fy_months(financial_year):
            due = ce.pmt06_due_date(y, m)
            if due is None:
                continue
            out.append(_spec("PMT06", "GST", f"PMT-06 {month_name[m]} {y}",
                             date(y, m, 1), ce.last_day_of_month(y, m), due))
    else:
        for (y, m) in fy_months(financial_year):
            ps = date(y, m, 1)
            pe = ce.last_day_of_month(y, m)
            lbl = f"{month_name[m]} {y}"
            out.append(_spec("GSTR1", "GST", f"GSTR-1 {lbl}", ps, pe,
                             ce.gstr1_due_date(y, m)))
            out.append(_spec("GSTR3B", "GST", f"GSTR-3B {lbl}", ps, pe,
                             ce.gstr3b_due_date(y, m)))

    # Annual GSTR-9, the same either way.
    out.append(_spec("GSTR9", "GST", f"GSTR-9 FY {financial_year}",
                     date(fye - 1, 4, 1), date(fye, 3, 31), ce.gstr9_due_date(fye)))
    return out


def gst_profile_for(client_id: str, firm_id: Optional[str] = None) -> tuple[str, Optional[str]]:
    """(frequency, state_code) for a client, defaulting to monthly.

    Monthly is the safe default for an unset field: it is what a client above
    the Rs 5 crore turnover threshold must file, and its due dates (11th/20th)
    fall EARLIER than QRMP's, so a client wrongly treated as monthly is chased
    early rather than late. §47 charges Rs 50 a day for late; nothing for early.
    """
    try:
        c = client_repo.find_by_id(client_id, firm_id=firm_id) or {}
    except Exception:  # noqa: BLE001 - a missing client must not stop generation
        _logger.warning("gst_profile_for: could not read client %s", client_id)
        return ce.MONTHLY, None
    freq = (c.get("gst_filing_frequency") or ce.MONTHLY).strip().lower()
    if freq not in (ce.MONTHLY, ce.QUARTERLY):
        freq = ce.MONTHLY
    return freq, c.get("state_code")


def _tds_obligations(financial_year: str,
                     has_non_resident_vendors: bool = False) -> list[dict]:
    """The TDS statements one client owes for one FY.

    26Q ALWAYS, and 27Q ONLY IF THE CLIENT PAYS A NON-RESIDENT. Rule 31A(4)
    splits the quarterly statement by the payee's residence: (a) 26Q for
    non-salary payments to residents, (b) 27Q for payments to non-residents.
    They are separate returns filed separately, on the same due dates —
    Rule 31A(2) sets one date per quarter regardless of form.

    Generating 27Q unconditionally would put four deadlines a year in the
    calendar of every client that has never paid a foreign supplier, which is
    most of them. That is the reasoning _gst_obligations already applies to
    IFF: an obligation nobody owes, appearing every quarter, is how a
    compliance calendar stops being read.

    So it is conditional on a fact somebody recorded — a vendor marked
    non-resident (migration 308) — not on a guess. And the condition is worth
    having precisely BECAUSE the software cannot compute the return: s.195's
    rate depends on nature of income, treaty and surcharge band, so a CA
    deducting on a foreign remittance is doing it outside this system. A
    reminder is the most this can offer for 27Q, and it is most valuable for
    exactly the return it cannot prepare.
    """
    fye = fy_end_year(financial_year)
    quarters = {
        "Q1": (date(fye - 1, 4, 1), date(fye - 1, 6, 30)),
        "Q2": (date(fye - 1, 7, 1), date(fye - 1, 9, 30)),
        "Q3": (date(fye - 1, 10, 1), date(fye - 1, 12, 31)),
        "Q4": (date(fye, 1, 1), date(fye, 3, 31)),
    }
    out = []
    for q, (ps, pe) in quarters.items():
        due = ce.tds_return_due_date(q, fye)
        out.append(_spec("TDS26Q", "TDS", f"TDS 26Q {q} FY {financial_year}",
                         ps, pe, due))
        if has_non_resident_vendors:
            out.append(_spec("TDS27Q", "TDS", f"TDS 27Q {q} FY {financial_year}",
                             ps, pe, due))
    return out


def has_non_resident_vendors(client_id: str, firm_id: Optional[str] = None) -> bool:
    """Whether this client has any vendor recorded as a non-resident payee.

    False on any failure, and logged — the same defensive shape as
    gst_profile_for, but the safe direction is the OPPOSITE one and it is worth
    saying why. There, an unknown filing frequency defaults to monthly because
    monthly due dates fall earlier, so a wrongly-classified client is chased
    early and s.47 charges nothing for early. Here the choice is between a
    missing reminder and a phantom obligation on every client in the firm, and
    a calendar full of deadlines nobody owes is the failure that makes the
    real ones invisible.

    NULL residential_status does NOT count. It means nobody has established the
    vendor's residence, which the register already reports as a statutory gap;
    treating it as non-resident here would generate 27Q for every client whose
    vendor master predates migration 308, which is all of them.
    """
    try:
        if _USE_MOCK:
            from routers.vendors import MOCK_VENDORS
            return any(
                v.get("client_id") == client_id
                and (firm_id is None or v.get("firm_id") == firm_id)
                and v.get("residential_status") == "non_resident"
                for v in MOCK_VENDORS
            )
        from core.supabase_client import get_supabase
        q = (get_supabase().table("vendors").select("id")
             .eq("client_id", client_id)
             .eq("residential_status", "non_resident")
             .limit(1))
        if firm_id:
            q = q.eq("firm_id", firm_id)
        # limit(1): this is an existence question, and the calendar must not
        # read a row per vendor to answer it.
        return bool(q.execute().data)
    except Exception:  # noqa: BLE001 - a vendor read must not stop generation
        _logger.warning(
            "has_non_resident_vendors: could not read vendors for client %s — "
            "no 27Q obligation will be generated this run", client_id)
        return False


def _itr_obligation(financial_year: str, is_audit: bool = False) -> list[dict]:
    fye = fy_end_year(financial_year)
    return [_spec("ITR", "Income Tax", f"ITR FY {financial_year}",
                  date(fye - 1, 4, 1), date(fye, 3, 31), ce.itr_due_date(fye, is_audit))]


def _advance_tax_obligations(financial_year: str) -> list[dict]:
    fye = fy_end_year(financial_year)
    out = []
    for inst in ce.advance_tax_due_dates(fye):
        due = inst["due_date"]
        out.append(_spec("ADVANCE_TAX", "Income Tax",
                         f"Advance Tax {inst['cumulative_percentage']}% (FY {financial_year})",
                         due, due, due))   # period_start = due date → distinct per installment
    return out


def _roc_obligations(financial_year: str, agm_date: Optional[str] = None) -> list[dict]:
    """ROC annual filings. AOC-4 within 30 days of AGM, MGT-7 within 60 (Companies Act
    §137/§92). When the AGM date is unknown, fall back to the statutory latest AGM
    (30 Sep following FY end)."""
    fye = fy_end_year(financial_year)
    agm = ce_date(agm_date) if agm_date else date(fye, 9, 30)
    ps, pe = date(fye - 1, 4, 1), date(fye, 3, 31)
    return [
        _spec("MCA_AOC4", "MCA", f"AOC-4 FY {financial_year}", ps, pe, ce.mca_due_date(agm, "AOC-4")),
        _spec("MCA_MGT7", "MCA", f"MGT-7 FY {financial_year}", ps, pe, ce.mca_due_date(agm, "MGT-7")),
    ]


def _tax_audit_obligation(financial_year: str) -> list[dict]:
    fye = fy_end_year(financial_year)
    return [_spec("TAX_AUDIT", "Income Tax", f"Tax Audit FY {financial_year}",
                  date(fye - 1, 4, 1), date(fye, 3, 31), ce.itr_due_date(fye, is_audit=True))]


def ce_date(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


def obligations_for_service(service_type: str, financial_year: str,
                            agm_date: Optional[str] = None,
                            gst_frequency: str = ce.MONTHLY,
                            gst_state_code: Optional[str] = None,
                            client_has_non_resident_vendors: bool = False) -> list[dict]:
    """Deterministic, pure: the statutory obligations a service engagement implies for
    one FY. Keyword-matched on service_type. Non-statutory services (accounting /
    bookkeeping / payroll) imply no filing obligations and return [].

    client_has_non_resident_vendors is passed IN rather than looked up here, so
    this stays pure and unit-testable — the same reason gst_frequency and
    gst_state_code are parameters. has_non_resident_vendors() does the reading.
    Defaults to False, so every existing caller keeps generating exactly the
    obligations it generated before.
    """
    s = (service_type or "").lower()
    specs: list[dict] = []
    if "gst" in s:
        specs += _gst_obligations(financial_year, gst_frequency, gst_state_code)
    if "tds" in s:
        specs += _tds_obligations(financial_year, client_has_non_resident_vendors)
    if "advance tax" in s:
        specs += _advance_tax_obligations(financial_year)
    elif "itr" in s or "income tax" in s:
        specs += _itr_obligation(financial_year)
    if "roc" in s or "mca" in s:
        specs += _roc_obligations(financial_year, agm_date)
    if "audit" in s:
        specs += _tax_audit_obligation(financial_year)
    return specs


def escalation_tier(days_to_due: int) -> Optional[str]:
    """Most-urgent applicable escalation tier, or None. (overdue / due tomorrow /
    due in 3 / due in 7)."""
    if days_to_due < 0:
        return "overdue"
    if days_to_due <= 1:
        return "due_1"
    if days_to_due <= 3:
        return "due_3"
    if days_to_due <= 7:
        return "due_7"
    return None


def aggregate_dashboard(records: list[dict], today: Optional[date] = None) -> dict:
    """Pure aggregation for the Practice → Compliance dashboard."""
    today = today or ist_today()
    week_end = (today + timedelta(days=7)).isoformat()
    month_end = ce.last_day_of_month(today.year, today.month).isoformat()
    today_s = today.isoformat()

    def _due(r):
        return str(r.get("due_date", ""))[:10]

    open_recs = [r for r in records if _OPEN_OBLIGATION(r.get("status"))]
    overdue = [r for r in open_recs if _due(r) and _due(r) < today_s]
    due_week = [r for r in open_recs if today_s <= _due(r) <= week_end]
    due_month = [r for r in open_recs if today_s <= _due(r) <= month_end]

    by_staff: dict = {}
    by_client: dict = {}
    for r in open_recs:
        staff = r.get("preparer_id") or r.get("assigned_to") or "unassigned"
        cl = r.get("client_id") or "unknown"
        is_overdue = _due(r) and _due(r) < today_s
        for bucket, key in ((by_staff, staff), (by_client, cl)):
            slot = bucket.setdefault(key, {"key": key, "obligations": 0, "overdue": 0})
            slot["obligations"] += 1
            if is_overdue:
                slot["overdue"] += 1

    return {
        "summary": {
            "total_obligations": len(records),
            "open_obligations": len(open_recs),
            "due_this_week": len(due_week),
            "due_this_month": len(due_month),
            "overdue": len(overdue),
        },
        "by_staff": sorted(by_staff.values(), key=lambda x: (-x["overdue"], -x["obligations"])),
        "by_client": sorted(by_client.values(), key=lambda x: (-x["overdue"], -x["obligations"])),
    }


# ── DB-backed operations (reuse mock-aware repos) ────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _records_for(firm_id: str, client_id: Optional[str] = None) -> list[dict]:
    from domain.compliance_record_service import compliance_record_service
    return compliance_record_service.list_records(firm_id=firm_id, client_id=client_id)


def _audit_timeline_generate(firm_id: str, rec: dict, actor: Optional[dict]) -> None:
    actor = actor or {}
    try:
        from services.audit_service import log_event
        log_event(firm_id, "compliance_record", rec.get("id"), "create",
                  actor_id=actor.get("auth_user_id"), actor_email=actor.get("email"),
                  new_data={"obligation_type": rec.get("obligation_type"),
                            "due_date": rec.get("due_date"), "engagement_id": rec.get("engagement_id")},
                  metadata={"source": "compliance_generation"})
    except Exception:  # pragma: no cover
        pass
    try:
        from services.timeline_service import timeline_service
        timeline_service.log(rec.get("client_id", ""), "compliance", "Compliance Obligation Created",
                             f"{rec.get('obligation_type', '')} {rec.get('period_label', '')} "
                             f"due {str(rec.get('due_date'))[:10]}", "info",
                             firm_id=firm_id, entity_type="compliance_record", entity_id=rec.get("id"))
    except Exception:  # pragma: no cover
        pass


def generate_for_engagement(firm_id: str, engagement: dict, financial_year: str,
                            actor: Optional[dict] = None, agm_date: Optional[str] = None) -> dict:
    """Idempotently generate obligations for one engagement + FY. One obligation per
    (obligation_type, period_start); re-running creates no duplicates."""
    client_id = engagement["client_id"]
    freq, state_code = gst_profile_for(client_id, firm_id)
    # Read once per engagement, not once per obligation — Rule 31A(4)(b)'s 27Q
    # is generated only for a client that actually pays a non-resident.
    non_resident = has_non_resident_vendors(client_id, firm_id)
    specs = obligations_for_service(engagement.get("service_type", ""), financial_year,
                                    agm_date, freq, state_code, non_resident)
    existing = compliance_records_repo.find_all(firm_id=firm_id, client_id=client_id)
    seen = {(r.get("obligation_type"), str(r.get("period_start"))[:10])
            for r in existing if r.get("obligation_type")}
    generated: list[str] = []
    skipped = 0
    now = _now_iso()
    for s in specs:
        key = (s["obligation_type"], s["period_start"])
        if key in seen:
            skipped += 1
            continue
        payload = {
            "firm_id": firm_id, "client_id": client_id, "engagement_id": engagement["id"],
            "compliance_type": s["compliance_type"], "obligation_type": s["obligation_type"],
            "period_label": s["period_label"], "period_start": s["period_start"],
            "period_end": s["period_end"], "due_date": s["due_date"],
            "status": "Not Started", "priority": "medium",
            "preparer_id": engagement.get("assigned_to"),
            "reviewer_id": engagement.get("reviewer_id"),
            "approver_id": engagement.get("partner_id"),
            "assigned_to": engagement.get("assigned_to"),
            "assigned_at": now if engagement.get("assigned_to") else None,
        }
        rec = compliance_records_repo.create(payload)
        seen.add(key)
        generated.append(rec["id"])
        _audit_timeline_generate(firm_id, rec, actor)
    return {"generated": len(generated), "skipped": skipped, "generated_ids": generated}


def generate_default_for_client(firm_id: str, client_id: str, financial_year: str,
                                actor: Optional[dict] = None) -> dict:
    """No-engagement fallback. A client with zero active fee_engagements rows still
    gets baseline GST obligations (GSTR-1 + GSTR-3B at the client's own filing
    frequency, PMT-06 where quarterly, GSTR-9 annual) generated
    directly against the client, engagement_id left NULL. This matches the
    pre-consolidation behaviour of the frontend's seedComplianceCalendar()/
    generateGSTDeadlines() — which seeded every visited client unconditionally,
    with no engagement concept at all — so client onboarding doesn't regress to
    "silently generates nothing" once the frontend is repointed at this generator.
    ITR/TDS/MCA/tax-audit obligations remain engagement-scoped (a client whose
    engagement genuinely excludes GST should not receive it as a side effect of
    this fallback; see generate_due, which only applies this to clients with no
    ACTIVE engagement at all). Idempotent via the same dedup as generate_for_engagement."""
    freq, state_code = gst_profile_for(client_id, firm_id)
    specs = _gst_obligations(financial_year, freq, state_code)
    existing = compliance_records_repo.find_all(firm_id=firm_id, client_id=client_id)
    seen = {(r.get("obligation_type"), str(r.get("period_start"))[:10])
            for r in existing if r.get("obligation_type")}
    generated: list[str] = []
    skipped = 0
    for s in specs:
        key = (s["obligation_type"], s["period_start"])
        if key in seen:
            skipped += 1
            continue
        payload = {
            "firm_id": firm_id, "client_id": client_id, "engagement_id": None,
            "compliance_type": s["compliance_type"], "obligation_type": s["obligation_type"],
            "period_label": s["period_label"], "period_start": s["period_start"],
            "period_end": s["period_end"], "due_date": s["due_date"],
            "status": "Not Started", "priority": "medium",
        }
        rec = compliance_records_repo.create(payload)
        seen.add(key)
        generated.append(rec["id"])
        _audit_timeline_generate(firm_id, rec, actor)
    return {"generated": len(generated), "skipped": skipped, "generated_ids": generated}


def generate_due(firm_id: str, client_id: Optional[str] = None, financial_year: Optional[str] = None,
                 actor: Optional[dict] = None, allowed_client_ids: Optional[set] = None) -> dict:
    """Generate obligations for every active engagement (optionally one client) for the
    given FY (defaults to the current Indian FY), then apply the no-engagement
    fallback to any in-scope client that has no ACTIVE engagement at all. Idempotent.

    allowed_client_ids confines a firm-wide run (client_id=None) to a non
    firm-wide caller's assigned clients — mirrors get_firm_summary's F2
    convention. None means unrestricted (firm-wide role, or a single
    client_id already checked by the caller)."""
    fy = financial_year or _current_fy()
    engagements = engagement_repo.find_all(firm_id=firm_id, client_id=client_id)
    if allowed_client_ids is not None:
        engagements = [e for e in engagements if str(e.get("client_id")) in allowed_client_ids]
    active = [e for e in engagements if e.get("status") in _ACTIVE_ENGAGEMENT_STATUSES]
    total_gen = total_skip = 0
    per_engagement = []
    covered_client_ids = set()
    for e in active:
        res = generate_for_engagement(firm_id, e, fy, actor=actor)
        total_gen += res["generated"]
        total_skip += res["skipped"]
        per_engagement.append({"engagement_id": e["id"], **{k: res[k] for k in ("generated", "skipped")}})
        covered_client_ids.add(e["client_id"])

    if client_id is not None:
        fallback_client_ids = [] if client_id in covered_client_ids else [client_id]
    else:
        from repositories.client_repository import client_repo
        fallback_client_ids = [c["id"] for c in client_repo.find_all(firm_id=firm_id)
                               if c["id"] not in covered_client_ids]
        if allowed_client_ids is not None:
            fallback_client_ids = [c for c in fallback_client_ids if c in allowed_client_ids]
    for cid in fallback_client_ids:
        res = generate_default_for_client(firm_id, cid, fy, actor=actor)
        total_gen += res["generated"]
        total_skip += res["skipped"]
        per_engagement.append({"engagement_id": None, "client_id": cid,
                               **{k: res[k] for k in ("generated", "skipped")}})

    return {"financial_year": fy, "generated": total_gen, "skipped": total_skip,
            "engagements": per_engagement}


def assign(firm_id: str, record_id: str, preparer_id: Optional[str] = None,
           reviewer_id: Optional[str] = None, approver_id: Optional[str] = None,
           actor: Optional[dict] = None) -> dict:
    """Set/replace the preparer / reviewer / approver on an obligation. Audited + timelined."""
    rec = compliance_records_repo.find_by_id(record_id)
    if not rec or (rec.get("firm_id") and rec["firm_id"] != firm_id):
        raise HTTPException(status_code=404, detail="Compliance obligation not found.")
    updates: dict = {}
    if preparer_id is not None:
        updates["preparer_id"] = preparer_id
        updates["assigned_to"] = preparer_id
    if reviewer_id is not None:
        updates["reviewer_id"] = reviewer_id
    if approver_id is not None:
        updates["approver_id"] = approver_id
    if not updates:
        raise HTTPException(status_code=422, detail="No assignment fields supplied.")
    updates["reassigned_at" if rec.get("assigned_at") else "assigned_at"] = _now_iso()
    updated = compliance_records_repo.update(record_id, updates)

    actor = actor or {}
    try:
        from services.audit_service import log_event
        log_event(firm_id, "compliance_record", record_id, "assignment_change",
                  actor_id=actor.get("auth_user_id"), actor_email=actor.get("email"),
                  old_data={"preparer_id": rec.get("preparer_id"), "reviewer_id": rec.get("reviewer_id"),
                            "approver_id": rec.get("approver_id")},
                  new_data={k: v for k, v in updates.items() if k.endswith("_id")})
    except Exception:  # pragma: no cover
        pass
    try:
        from services.timeline_service import timeline_service
        timeline_service.log(rec.get("client_id", ""), "compliance", "Compliance Reassigned",
                             f"{rec.get('obligation_type', '')} {rec.get('period_label', '')} assignment updated",
                             "info", firm_id=firm_id, entity_type="compliance_record", entity_id=record_id)
    except Exception:  # pragma: no cover
        pass
    return updated


def transition(firm_id: str, record_id: str, new_status: str, actor: Optional[dict] = None) -> dict:
    """Move an obligation through its lifecycle. Reuses the canonical transition
    validation + audit/timeline in compliance_record_service (rejects invalid)."""
    from domain.compliance_record_service import compliance_record_service
    return compliance_record_service.update_record(record_id, {"status": new_status},
                                                   firm_id=firm_id, actor=actor)


def _notify_internal(firm_id: str, rec: dict, tier: str, actor: Optional[dict]) -> None:
    """Internal-only escalation: client timeline + audit, plus a best-effort
    in-app notification to preparer/reviewer/approver. NEVER emails the client."""
    severity = "critical" if tier in ("overdue", "due_1") else "warning"
    label = {"overdue": "OVERDUE", "due_1": "due tomorrow",
             "due_3": "due in 3 days", "due_7": "due in 7 days"}.get(tier, tier)
    try:
        from services.timeline_service import timeline_service
        timeline_service.log(rec.get("client_id", ""), "compliance", f"Compliance {label}",
                             f"{rec.get('obligation_type', '')} {rec.get('period_label', '')} "
                             f"is {label} (due {str(rec.get('due_date'))[:10]})", severity,
                             firm_id=firm_id, entity_type="compliance_record", entity_id=rec.get("id"))
    except Exception:  # pragma: no cover
        pass
    try:
        from services.audit_service import log_event
        log_event(firm_id, "compliance_record", rec.get("id"), "escalation",
                  actor_id=(actor or {}).get("auth_user_id"),
                  new_data={"tier": tier, "due_date": rec.get("due_date")},
                  metadata={"recipients": [rec.get("preparer_id"), rec.get("reviewer_id"),
                                           rec.get("approver_id")]})
    except Exception:  # pragma: no cover
        pass
    # Best-effort in-app notifications (internal). Guarded — never fatal.
    try:
        from repositories.notifications_repository import notifications_repo
        recipients = {r for r in (rec.get("preparer_id"), rec.get("reviewer_id"),
                                  rec.get("approver_id"), rec.get("assigned_to")) if r}
        for uid in recipients:
            notifications_repo.create({
                "firm_id": firm_id, "user_id": uid, "type": "compliance_due",
                "title": f"Compliance {label}: {rec.get('obligation_type', '')}",
                "body": f"{rec.get('period_label', '')} due {str(rec.get('due_date'))[:10]}",
                "severity": "critical" if tier in ("overdue", "due_1") else "high",
                "metadata": {"compliance_record_id": rec.get("id"), "tier": tier},
            })
    except Exception:  # pragma: no cover - notifications are best-effort
        pass


def escalate(firm_id: str, today: Optional[date] = None, actor: Optional[dict] = None,
            allowed_client_ids: Optional[set] = None) -> dict:
    """Escalate open obligations on the 7/3/1-day + overdue cadence to the internal
    team. Idempotent per (record, tier, day) via last_escalated_tier/on. Internal only.

    allowed_client_ids confines the run to a non firm-wide caller's assigned
    clients (F2 convention, as in generate_due/dashboard). None means every
    obligation in the firm — the scheduler's unrestricted nightly run."""
    today = today or ist_today()
    today_s = today.isoformat()
    counts = {"due_7": 0, "due_3": 0, "due_1": 0, "overdue": 0}
    # Pushed server-side: escalate() only ever acts on open obligations, so
    # there's no reason to also fetch every Filed/Completed row just to
    # discard it in Python.
    for r in compliance_records_repo.find_all(firm_id=firm_id, exclude_statuses=("Filed", "Completed")):
        if allowed_client_ids is not None and str(r.get("client_id")) not in allowed_client_ids:
            continue
        due = str(r.get("due_date", ""))[:10]
        if not due:
            continue
        tier = escalation_tier((ce_date(due) - today).days)
        if tier is None:
            continue
        if str(r.get("last_escalated_on") or "")[:10] == today_s and r.get("last_escalated_tier") == tier:
            continue  # already escalated at this tier today (anti-spam / idempotent)
        _notify_internal(firm_id, r, tier, actor)
        compliance_records_repo.update(r["id"], {"last_escalated_tier": tier, "last_escalated_on": today_s})
        counts[tier] += 1
    return {"escalated": sum(counts.values()), **counts}


def dashboard(firm_id: str, today: Optional[date] = None, allowed_client_ids: Optional[set] = None) -> dict:
    """allowed_client_ids confines the dashboard — including the raw `queue`
    of obligation rows, not just the aggregate counts — to a non firm-wide
    caller's assigned clients. Without this, an Executive assigned to two
    clients saw every client's obligations and named `by_client` figures,
    unlike the aggregate-only dashboards (tasks/lifecycle) this pattern was
    deliberately left unscoped for."""
    records = _records_for(firm_id)
    if allowed_client_ids is not None:
        records = [r for r in records if str(r.get("client_id")) in allowed_client_ids]
    agg = aggregate_dashboard(records, today)
    return {**agg, "queue": records}


def calendar(firm_id: str, client_id: Optional[str] = None, today: Optional[date] = None) -> dict:
    """Calendar projection over the canonical obligations (compliance_records).
    compliance_calendar remains; this is the read view, not a second source of truth."""
    today = today or ist_today()
    today_s = today.isoformat()
    records = _records_for(firm_id, client_id)
    upcoming, overdue, completed = [], [], []
    for r in records:
        due = str(r.get("due_date", ""))[:10]
        if r.get("status") in ("Filed", "Completed"):
            completed.append(r)
        elif due and due < today_s:
            overdue.append(r)
        else:
            upcoming.append(r)
    upcoming.sort(key=lambda r: str(r.get("due_date", "")))
    overdue.sort(key=lambda r: str(r.get("due_date", "")))
    return {"upcoming": upcoming, "overdue": overdue, "completed": completed}


def _current_fy() -> str:
    return ist_fy_label()
