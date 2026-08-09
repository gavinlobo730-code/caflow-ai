"""
Phase 1.3 Intelligence Layer.

Deterministic scoring engines built directly on the existing repositories —
no separate AI architecture. The Groq-backed copilot (routers/ai_copilot.py)
consumes these scores as context; all numbers here are computed, not
hallucinated, so they are safe to surface in dashboards.

Engines:
  - Predictive compliance: per-client filing risk scores + missed-deadline
    prediction from overdue history and upcoming due dates
  - Relationship intelligence: client relationship / engagement health scoring
  - Auto journal suggestions: pattern recognition over posted journal entries
    (recurring monthly entries missing in the current month), surfaced as
    draft suggestions requiring explicit user approval
  - Proactive recommendations: rule-based compliance / client / operational
    recommendations

All monetary figures are integer paise.
"""
import logging
from datetime import date, datetime, timedelta
from typing import Optional

logger = logging.getLogger("caflow.services")


# ── Predictive compliance ────────────────────────────────────────────────────

def compute_compliance_risk(
    firm_id: str, allowed_client_ids: Optional[set[str]] = None
) -> dict:
    """
    Per-client compliance risk scoring (0-100, higher = riskier).

    Score components:
      +25 per currently overdue compliance record (capped at 50)
      +10 per record due within 7 days (capped at 30)
      +20 if the client has any history of late filing
    """
    from repositories.client_repository import client_repo
    from repositories.compliance_records_repository import compliance_records_repo

    clients = client_repo.find_all(firm_id=firm_id)
    # M2: every row below NAMES its client (client_name + per-client risk
    # score), so a firm-wide read here hands an unassigned Executive the whole
    # client list. None = firm-wide role, nothing to narrow (the F2 convention).
    if allowed_client_ids is not None:
        clients = [c for c in clients if str(c.get("id")) in allowed_client_ids]
    records = compliance_records_repo.find_all(firm_id=firm_id)

    today = date.today()
    week_ahead = today + timedelta(days=7)

    by_client: dict[str, list[dict]] = {}
    for r in records:
        cid = r.get("client_id")
        if cid:
            by_client.setdefault(cid, []).append(r)

    results = []
    for client in clients:
        cid = client["id"]
        crecords = by_client.get(cid, [])

        overdue = []
        due_soon = []
        late_history = 0
        for r in crecords:
            status = (r.get("status") or "").lower()
            due_raw = r.get("due_date")
            due = None
            if due_raw:
                try:
                    due = date.fromisoformat(str(due_raw)[:10])
                except ValueError:
                    due = None
            if status in ("overdue",) or (due and due < today and status not in ("filed", "not_applicable")):
                overdue.append(r)
            elif due and today <= due <= week_ahead and status not in ("filed", "not_applicable"):
                due_soon.append(r)
            # Late history: filed after the due date
            if status == "filed" and due and r.get("filed_at"):
                try:
                    filed = date.fromisoformat(str(r["filed_at"])[:10])
                    if filed > due:
                        late_history += 1
                except ValueError:
                    pass

        score = min(50, len(overdue) * 25) + min(30, len(due_soon) * 10)
        if late_history > 0:
            score += 20
        score = min(100, score)

        level = "low"
        if score >= 70:
            level = "critical"
        elif score >= 40:
            level = "high"
        elif score >= 20:
            level = "medium"

        predicted_misses = [
            {
                "record_id": r.get("id"),
                "compliance_type": r.get("compliance_type") or r.get("type"),
                "due_date": r.get("due_date"),
                "reason": "Client has overdue items and/or a history of late filing",
            }
            for r in due_soon
        ] if (overdue or late_history) else []

        results.append({
            "client_id": cid,
            "client_name": client.get("client_name"),
            "risk_score": score,
            "risk_level": level,
            "overdue_count": len(overdue),
            "due_soon_count": len(due_soon),
            "late_filing_history": late_history,
            "predicted_misses": predicted_misses,
        })

    results.sort(key=lambda r: r["risk_score"], reverse=True)
    return {
        "clients": results,
        "high_risk_count": sum(1 for r in results if r["risk_level"] in ("high", "critical")),
        "computed_at": datetime.now().isoformat(),
    }


# ── Relationship intelligence ────────────────────────────────────────────────

def compute_relationship_health(
    firm_id: str, allowed_client_ids: Optional[set[str]] = None
) -> dict:
    """
    Client relationship / engagement health scoring (0-100, higher = healthier).

    Components:
      Task delivery (40): on-time vs overdue open tasks
      Payment behaviour (40): paid vs overdue invoices
      Engagement activity (20): recent task or invoice activity
    """
    from repositories.client_repository import client_repo
    from repositories.task_repository import task_repo
    from repositories.invoice_repository import invoice_repo

    clients = client_repo.find_all(firm_id=firm_id)
    # M2: same shape as compute_compliance_risk — each row names its client.
    if allowed_client_ids is not None:
        clients = [c for c in clients if str(c.get("id")) in allowed_client_ids]
    tasks = task_repo.find_all(firm_id=firm_id)
    invoices = invoice_repo.find_all(firm_id=firm_id)

    today = date.today().isoformat()
    ninety_days_ago = (date.today() - timedelta(days=90)).isoformat()

    tasks_by_client: dict[str, list[dict]] = {}
    for t in tasks:
        cid = t.get("client_id")
        if cid:
            tasks_by_client.setdefault(cid, []).append(t)

    invoices_by_client: dict[str, list[dict]] = {}
    for i in invoices:
        cid = i.get("client_id")
        if cid:
            invoices_by_client.setdefault(cid, []).append(i)

    results = []
    for client in clients:
        cid = client["id"]
        ctasks = tasks_by_client.get(cid, [])
        cinvoices = invoices_by_client.get(cid, [])

        open_tasks = [t for t in ctasks if t.get("status") != "completed"]
        overdue_tasks = [t for t in open_tasks if t.get("due_date") and t["due_date"] < today]
        task_score = 40
        if open_tasks:
            task_score = round(40 * (1 - len(overdue_tasks) / len(open_tasks)))

        relevant_invoices = [i for i in cinvoices if i.get("status") in ("Issued", "Paid", "Overdue")]
        overdue_invoices = [i for i in relevant_invoices if i.get("status") == "Overdue"]
        payment_score = 40
        if relevant_invoices:
            payment_score = round(40 * (1 - len(overdue_invoices) / len(relevant_invoices)))

        recent_activity = any(
            (t.get("updated_at") or t.get("created_at") or "") >= ninety_days_ago for t in ctasks
        ) or any((i.get("invoice_date") or "") >= ninety_days_ago for i in cinvoices)
        activity_score = 20 if recent_activity else 0

        score = task_score + payment_score + activity_score
        level = "healthy" if score >= 70 else ("at_risk" if score >= 40 else "critical")

        outstanding_paise = sum(
            i.get("total_paise", 0) for i in relevant_invoices if i.get("status") in ("Issued", "Overdue")
        )

        results.append({
            "client_id": cid,
            "client_name": client.get("client_name"),
            "health_score": score,
            "health_level": level,
            "open_tasks": len(open_tasks),
            "overdue_tasks": len(overdue_tasks),
            "overdue_invoices": len(overdue_invoices),
            "outstanding_paise": outstanding_paise,
            "recent_activity": recent_activity,
        })

    results.sort(key=lambda r: r["health_score"])
    return {
        "clients": results,
        "at_risk_count": sum(1 for r in results if r["health_level"] != "healthy"),
        "computed_at": datetime.now().isoformat(),
    }


# ── Auto journal suggestions ─────────────────────────────────────────────────

def compute_journal_suggestions(
    firm_id: str,
    client_id: Optional[str] = None,
    allowed_client_ids: Optional[set[str]] = None,
) -> dict:
    """
    Pattern recognition over posted journal entries.

    An entry pattern (same client + narration + account set) that appeared in
    at least 2 of the last 3 months, but is missing in the current month, is
    suggested for this month. Suggestions are drafts only — they are created
    as journal entries solely through the explicit approval endpoint, which
    writes a 'draft' status entry for normal posting review (Partner approval
    per accounting.approve RBAC).
    """
    from domain.accounting_service import accounting_service

    today = date.today()
    current_month = today.strftime("%Y-%m")
    lookback_start = (today.replace(day=1) - timedelta(days=92)).isoformat()

    entries = accounting_service.list_journal_entries(
        firm_id=firm_id, client_id=client_id, start_date=lookback_start,
    )
    posted = [e for e in entries if e.get("status") == "posted"]
    # M2: with no client_id the read spans the whole firm and every suggestion
    # carries the client_id it was derived from, so narrow before patterning.
    if allowed_client_ids is not None:
        posted = [e for e in posted if str(e.get("client_id")) in allowed_client_ids]

    patterns: dict[tuple, dict] = {}
    for e in posted:
        account_ids = tuple(sorted(ln.get("account_id", "") for ln in e.get("lines", [])))
        key = (e.get("client_id"), (e.get("narration") or "").strip().lower(), account_ids)
        month = str(e.get("entry_date", ""))[:7]
        p = patterns.setdefault(key, {"months": set(), "last_entry": e})
        p["months"].add(month)
        if str(e.get("entry_date", "")) >= str(p["last_entry"].get("entry_date", "")):
            p["last_entry"] = e

    suggestions = []
    for (cid, narration, _accounts), p in patterns.items():
        prior_months = {m for m in p["months"] if m < current_month}
        if len(prior_months) >= 2 and current_month not in p["months"]:
            last = p["last_entry"]
            suggestions.append({
                "client_id": cid,
                "narration": last.get("narration"),
                "entry_type": last.get("entry_type", "Journal"),
                "suggested_date": today.isoformat(),
                "based_on_entry_id": last.get("id"),
                "occurrences": len(prior_months),
                "lines": [
                    {
                        "account_id": ln.get("account_id"),
                        "account_name": ln.get("account_name"),
                        "debit_paise": ln.get("debit_paise", 0),
                        "credit_paise": ln.get("credit_paise", 0),
                        "narration": ln.get("narration", ""),
                    }
                    for ln in last.get("lines", [])
                ],
                "reason": f"Recurring entry seen in {len(prior_months)} prior months, missing for {current_month}",
            })

    return {"suggestions": suggestions, "month": current_month}


def approve_journal_suggestion(firm_id: str, suggestion: dict, user_id: Optional[str] = None) -> dict:
    """
    Create a DRAFT journal entry from an approved suggestion.
    Posting still requires the normal accounting.approve flow (Partner) —
    suggestions never post directly to the ledger.
    """
    from domain.accounting_service import accounting_service

    entry = accounting_service.create_journal_entry({
        "firm_id": firm_id,
        "client_id": suggestion.get("client_id"),
        "entry_date": suggestion.get("suggested_date") or date.today().isoformat(),
        "narration": suggestion.get("narration", ""),
        "entry_type": suggestion.get("entry_type", "Journal"),
        "status": "draft",
        "lines": suggestion.get("lines", []),
        "created_by": user_id,
    })
    return entry


# ── Proactive recommendations ────────────────────────────────────────────────

def compute_recommendations(
    firm_id: str, allowed_client_ids: Optional[set[str]] = None
) -> dict:
    """Rule-based compliance / client / operational recommendations."""
    recommendations: list[dict] = []

    # Compliance recommendations from the risk engine above
    try:
        risk = compute_compliance_risk(firm_id, allowed_client_ids)
        for c in risk["clients"]:
            if c["risk_level"] in ("high", "critical"):
                recommendations.append({
                    "category": "compliance",
                    "priority": "high" if c["risk_level"] == "critical" else "medium",
                    "title": f"Review filings for {c['client_name']}",
                    "detail": (
                        f"{c['overdue_count']} overdue and {c['due_soon_count']} due within 7 days. "
                        f"Risk score {c['risk_score']}/100."
                    ),
                    "client_id": c["client_id"],
                    "action": "open_compliance",
                })
    except Exception as e:
        logger.warning(f"Compliance recommendations failed: {e}")

    # Client recommendations from relationship health
    try:
        health = compute_relationship_health(firm_id, allowed_client_ids)
        for c in health["clients"]:
            if c["health_level"] == "critical":
                recommendations.append({
                    "category": "client",
                    "priority": "high",
                    "title": f"Re-engage {c['client_name']}",
                    "detail": (
                        f"Health score {c['health_score']}/100 — "
                        f"{c['overdue_tasks']} overdue tasks, {c['overdue_invoices']} overdue invoices, "
                        f"₹{c['outstanding_paise'] // 100:,} outstanding."
                    ),
                    "client_id": c["client_id"],
                    "action": "open_client",
                })
            elif c["outstanding_paise"] > 0 and c["overdue_invoices"] > 0:
                recommendations.append({
                    "category": "client",
                    "priority": "medium",
                    "title": f"Follow up on payment — {c['client_name']}",
                    "detail": f"₹{c['outstanding_paise'] // 100:,} outstanding with {c['overdue_invoices']} overdue invoice(s).",
                    "client_id": c["client_id"],
                    "action": "open_invoices",
                })
    except Exception as e:
        logger.warning(f"Client recommendations failed: {e}")

    # Operational recommendations from journal patterns
    try:
        journal = compute_journal_suggestions(firm_id, allowed_client_ids=allowed_client_ids)
        if journal["suggestions"]:
            recommendations.append({
                "category": "operational",
                "priority": "low",
                "title": f"{len(journal['suggestions'])} recurring journal entries pending for {journal['month']}",
                "detail": "Recurring entry patterns detected from prior months are not yet recorded this month.",
                "action": "open_journal_suggestions",
            })
    except Exception as e:
        logger.warning(f"Journal recommendations failed: {e}")

    priority_order = {"high": 0, "medium": 1, "low": 2}
    recommendations.sort(key=lambda r: priority_order.get(r["priority"], 3))
    return {"recommendations": recommendations, "total": len(recommendations)}


# ── Workload insights ────────────────────────────────────────────────────────

def compute_workload_insights(firm_id: str) -> dict:
    """Team workload insights built on the capacity-aware workload engine."""
    from repositories.user_repository import user_repo
    from repositories.task_repository import task_repo
    from repositories.capacity_repository import capacity_repo, DEFAULT_MAX_TASKS

    users = user_repo.find_all(firm_id=firm_id)
    tasks = task_repo.find_all(firm_id=firm_id)
    open_tasks = [t for t in tasks if t.get("status") != "completed"]
    capacity_map = capacity_repo.capacity_map(firm_id)

    per_user: dict[str, int] = {}
    for t in open_tasks:
        uid = t.get("assignee_id") or t.get("assigned_to")
        if uid:
            per_user[uid] = per_user.get(uid, 0) + 1

    insights = []
    for u in users:
        uid = u["id"]
        active = per_user.get(uid, 0)
        max_tasks = capacity_map.get(uid, {}).get("max_concurrent_tasks", DEFAULT_MAX_TASKS)
        if active > max_tasks:
            insights.append({
                "type": "overload",
                "user_id": uid,
                "user_name": u.get("full_name") or u.get("email"),
                "detail": f"{active} active tasks against a configured limit of {max_tasks}.",
            })
        elif active == 0:
            insights.append({
                "type": "idle",
                "user_id": uid,
                "user_name": u.get("full_name") or u.get("email"),
                "detail": "No active tasks assigned.",
            })

    unassigned = sum(1 for t in open_tasks if not (t.get("assignee_id") or t.get("assigned_to")))
    if unassigned:
        insights.append({
            "type": "unassigned_backlog",
            "detail": f"{unassigned} open tasks have no assignee.",
        })

    return {"insights": insights, "open_tasks": len(open_tasks), "team_size": len(users)}
