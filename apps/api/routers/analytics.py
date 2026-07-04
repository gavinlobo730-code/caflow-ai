from fastapi import APIRouter, Depends
from models.common import api_response
from core.permissions import rbac
from datetime import date, timedelta
from repositories.time_tracking_analytics_repository import time_tracking_analytics_repo
from repositories.invoice_repository import invoice_repo
from repositories.engagement_repository import engagement_repo
from repositories.user_repository import user_repo
from repositories.client_repository import client_repo

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _get_db():
    from core.supabase_client import get_supabase
    return get_supabase()


def _period_range(period: str) -> tuple[str, str, str]:
    today = date.today()
    if period == "week":
        start = today - timedelta(days=today.weekday())
        label = f"Week of {start.strftime('%d %b %Y')}"
    elif period == "quarter":
        month = today.month
        q_start_month = ((month - 1) // 3) * 3 + 1
        start = today.replace(month=q_start_month, day=1)
        label = f"Q{(q_start_month - 1) // 3 + 1} {today.year}"
    else:  # month
        start = today.replace(day=1)
        label = today.strftime("%B %Y")
    return start.isoformat(), today.isoformat(), label


@router.get("/team")
def team_analytics(
    period: str = "month",
    current_user: dict = Depends(rbac("analytics", "read")),
):
    firm_id = current_user.get("firm_id")
    db = _get_db()
    date_from, date_to, label = _period_range(period)
    today = date.today().isoformat()

    # All users in firm
    users_result = db.table("users").select("id, full_name, email, role").eq("firm_id", firm_id).execute()
    users = users_result.data or []

    # Completed tasks in period
    completed_result = db.table("tasks").select("id, assigned_to, assignee_id, updated_at").eq("firm_id", firm_id).eq("status", "completed").gte("updated_at", date_from).lte("updated_at", f"{date_to}T23:59:59Z").execute()
    completed_tasks = completed_result.data or []

    # Open and overdue tasks
    open_result = db.table("tasks").select("id, assigned_to, assignee_id, status, due_date").eq("firm_id", firm_id).neq("status", "completed").execute()
    open_tasks = open_result.data or []

    def get_uid(t: dict) -> str:
        return t.get("assignee_id") or t.get("assigned_to") or ""

    completed_by_user: dict[str, int] = {}
    for t in completed_tasks:
        uid = get_uid(t)
        completed_by_user[uid] = completed_by_user.get(uid, 0) + 1

    in_progress_by_user: dict[str, int] = {}
    overdue_by_user: dict[str, int] = {}
    for t in open_tasks:
        uid = get_uid(t)
        if t.get("status") == "in_progress":
            in_progress_by_user[uid] = in_progress_by_user.get(uid, 0) + 1
        if t.get("due_date") and t["due_date"] < today:
            overdue_by_user[uid] = overdue_by_user.get(uid, 0) + 1

    total_open_by_user: dict[str, int] = {}
    for t in open_tasks:
        uid = get_uid(t)
        total_open_by_user[uid] = total_open_by_user.get(uid, 0) + 1

    members = []
    for u in users:
        uid = u["id"]
        c = completed_by_user.get(uid, 0)
        o = total_open_by_user.get(uid, 0)
        rate = round((c / (c + o) * 100), 1) if (c + o) > 0 else 0.0
        members.append({
            "user_id": uid,
            "user_name": u.get("full_name") or u.get("email") or "Unknown",
            "role": u.get("role", ""),
            "tasks_completed": c,
            "tasks_in_progress": in_progress_by_user.get(uid, 0),
            "overdue_tasks": overdue_by_user.get(uid, 0),
            "avg_completion_rate": rate,
        })

    # Get hours by employee from time tracking
    hours_by_employee = time_tracking_analytics_repo.get_hours_by_employee(firm_id, date_from, date_to)

    enriched_members = [{
        "user_id": m["user_id"],
        "user_name": m["user_name"],
        "role": m["role"],
        "total_minutes": hours_by_employee.get(m["user_id"], {}).get("total_minutes", 0),
        "billable_minutes": hours_by_employee.get(m["user_id"], {}).get("billable_minutes", 0),
        "tasks_completed": m["tasks_completed"],
        "tasks_active": total_open_by_user.get(m["user_id"], 0),
        "utilisation_pct": m["avg_completion_rate"],
    } for m in members]

    enriched_members.sort(key=lambda m: m["tasks_completed"], reverse=True)
    avg_util = round(sum(m["utilisation_pct"] for m in enriched_members) / len(enriched_members), 1) if enriched_members else 0.0

    # Get total firm hours
    firm_hours = time_tracking_analytics_repo.get_firm_hours(firm_id, date_from, date_to)

    return api_response(True, {
        "period": label,
        "members": enriched_members,
        "total_minutes": firm_hours["total_minutes"],
        "billable_minutes": firm_hours["billable_minutes"],
        "avg_utilisation_pct": avg_util,
    })


@router.get("/clients")
def client_analytics(
    period: str = "month",
    current_user: dict = Depends(rbac("analytics", "read")),
):
    firm_id = current_user.get("firm_id")
    db = _get_db()
    date_from, date_to, label = _period_range(period)
    today = date.today().isoformat()

    # Guardrail G2: exclude the internal practice client from analytics.
    clients_result = db.table("clients").select("id, client_name").eq("firm_id", firm_id).eq("is_internal", False).execute()
    clients = clients_result.data or []

    # Bounded to the period, not the firm's entire task history (same pattern
    # already used correctly by team_analytics above) — completed tasks from
    # years ago were previously fetched in full just to be filtered out here.
    completed_result = db.table("tasks").select("id, client_id, status, due_date, updated_at").eq("firm_id", firm_id).eq("status", "completed").gte("updated_at", date_from).lte("updated_at", f"{date_to}T23:59:59Z").execute()
    completed_tasks = completed_result.data or []

    open_result = db.table("tasks").select("id, client_id, status, due_date, updated_at").eq("firm_id", firm_id).neq("status", "completed").execute()
    open_tasks = open_result.data or []

    # M6 #6: per-client analytics must respect assignment — a non-Partner must not
    # infer activity for clients they cannot access directly. effective set None
    # (Partner) ⇒ no filtering.
    from core.authz import effective_client_ids
    _eff = effective_client_ids(current_user)
    if _eff is not None:
        clients = [c for c in clients if str(c["id"]) in _eff]
        completed_tasks = [t for t in completed_tasks if str(t.get("client_id")) in _eff]
        open_tasks = [t for t in open_tasks if str(t.get("client_id")) in _eff]

    stats: dict[str, dict] ={c["id"]: {"client_id": c["id"], "client_name": c["client_name"], "tasks_completed": 0, "tasks_overdue": 0, "open_tasks": 0} for c in clients}
    for t in completed_tasks:
        cid = t.get("client_id")
        if cid in stats:
            stats[cid]["tasks_completed"] += 1
    for t in open_tasks:
        cid = t.get("client_id")
        if cid in stats:
            stats[cid]["open_tasks"] += 1
            if t.get("due_date") and t["due_date"] < today:
                stats[cid]["tasks_overdue"] += 1

    result_list = []
    for s in stats.values():
        c = s["tasks_completed"]
        o = s["open_tasks"]
        rate = round((c / (c + o) * 100), 1) if (c + o) > 0 else 0.0
        result_list.append({**s, "completion_rate": rate})

    # Get hours by client from time tracking
    hours_by_client = time_tracking_analytics_repo.get_hours_by_client(firm_id, date_from, date_to)

    enriched_clients = [{
        "client_id": s["client_id"],
        "client_name": s["client_name"],
        "total_minutes": hours_by_client.get(s["client_id"], {}).get("total_minutes", 0),
        "billable_minutes": hours_by_client.get(s["client_id"], {}).get("billable_minutes", 0),
        "tasks_completed": s["tasks_completed"],
        "tasks_active": s["open_tasks"],
        "revenue_paise": 0,
    } for s in result_list]

    enriched_clients.sort(key=lambda x: x["tasks_completed"], reverse=True)

    # Get total firm hours
    firm_hours = time_tracking_analytics_repo.get_firm_hours(firm_id, date_from, date_to)

    return api_response(True, {
        "period": label,
        "clients": enriched_clients,
        "total_minutes": firm_hours["total_minutes"],
        "total_revenue_paise": 0,
    })


@router.get("/firm")
def firm_analytics(
    period: str = "month",
    current_user: dict = Depends(rbac("analytics", "read")),
):
    firm_id = current_user.get("firm_id")
    db = _get_db()
    date_from, date_to, label = _period_range(period)
    today = date.today().isoformat()

    # Bounded to the period, not the firm's entire task history (same pattern
    # already used correctly by team_analytics above) — completed tasks from
    # years ago were previously fetched in full just to be filtered out here.
    completed_result = db.table("tasks").select("id, client_id, status, due_date, updated_at, assigned_to").eq("firm_id", firm_id).eq("status", "completed").gte("updated_at", date_from).lte("updated_at", f"{date_to}T23:59:59Z").execute()
    completed = completed_result.data or []

    open_result = db.table("tasks").select("id, client_id, status, due_date, updated_at, assigned_to").eq("firm_id", firm_id).neq("status", "completed").execute()
    open_tasks = open_result.data or []

    # Guardrail G2: the internal practice client is not part of the active-client KPI.
    clients_result = db.table("clients").select("id").eq("firm_id", firm_id).eq("status", "active").eq("is_internal", False).execute()
    active_clients = len(clients_result.data or [])

    overdue = [t for t in open_tasks if t.get("due_date") and t["due_date"] < today]

    total_c = len(completed)
    total_ov = len(overdue)
    total_open = len(open_tasks)
    total = total_c + total_open
    completion_rate = round((total_c / total * 100), 1) if total > 0 else 0.0
    overdue_rate = round((total_ov / total * 100), 1) if total > 0 else 0.0
    tasks_per_client = round(total / active_clients, 1) if active_clients > 0 else 0.0

    # Revenue analytics — gracefully handle missing fee tables
    revenue_paise = 0
    outstanding_paise = 0
    invoices_issued = 0
    invoices_paid = 0
    try:
        inv_result = db.table("fee_invoices").select("total_paise, invoice_date, status").eq("firm_id", firm_id).gte("invoice_date", date_from).execute()
        inv_list = inv_result.data or []
        invoices_issued = len(inv_list)
        invoices_paid = sum(1 for i in inv_list if i.get("status") == "Paid")
        revenue_paise = sum(i["total_paise"] for i in inv_list if i.get("status") == "Paid")
        outstanding_paise = sum(i["total_paise"] for i in inv_list if i.get("status") not in ("Paid", "Draft"))
    except Exception:
        pass

    # Get firm hours from time tracking
    firm_hours = time_tracking_analytics_repo.get_firm_hours(firm_id, date_from, date_to)

    return api_response(True, {
        "period": label,
        "total_minutes": firm_hours["total_minutes"],
        "billable_minutes": firm_hours["billable_minutes"],
        "utilisation_pct": completion_rate,
        "tasks_completed": total_c,
        "tasks_active": total_open,
        "tasks_overdue": total_ov,
        "revenue_paise": revenue_paise,
        "outstanding_paise": outstanding_paise,
        "invoices_issued": invoices_issued,
        "invoices_paid": invoices_paid,
    })


@router.get("/profitability")
def profitability_analytics(
    period: str = "month",
    include_by_client: bool = True,
    include_by_engagement: bool = False,
    include_by_team: bool = False,
    current_user: dict = Depends(rbac("analytics", "read")),
):
    """
    Get profitability analytics for the firm.
    Profitability = Revenue - Cost
    Cost = effort_minutes * hourly_rate_paise / 60
    All calculations in integer paise arithmetic.
    """
    firm_id = current_user.get("firm_id")
    date_from, date_to, label = _period_range(period)
    db = _get_db()

    # Get all clients for lookup
    all_clients = client_repo.find_all(firm_id=firm_id)
    client_map = {c["id"]: c.get("client_name", "Unknown") for c in all_clients}

    # Get all users for lookup
    all_users = user_repo.find_all(firm_id=firm_id)
    user_map = {u["id"]: u.get("full_name") or u.get("name") or u.get("email", "Unknown") for u in all_users}

    # Get all engagements for lookup
    all_engagements = engagement_repo.find_all(firm_id=firm_id)
    engagement_map = {e["id"]: {
        "service_type": e.get("service_type", "Unknown"),
        "client_id": e.get("client_id"),
    } for e in all_engagements}

    # Get revenue and cost data
    revenue_by_client = invoice_repo.get_revenue_by_client(firm_id, date_from, date_to)
    cost_by_client = time_tracking_analytics_repo.get_cost_by_client(firm_id, date_from, date_to)

    # Firm-level metrics
    total_revenue_paise = sum(revenue_by_client.values())
    total_cost_paise = sum(cost_by_client.values())
    total_profit_paise = total_revenue_paise - total_cost_paise
    total_profit_margin_pct = (total_profit_paise / total_revenue_paise * 100) if total_revenue_paise > 0 else 0.0
    num_clients_billed = len(revenue_by_client)
    avg_profit_per_client = (total_profit_paise // num_clients_billed) if num_clients_billed > 0 else 0

    firm_metrics = {
        "total_revenue_paise": total_revenue_paise,
        "total_cost_paise": total_cost_paise,
        "profit_paise": total_profit_paise,
        "profit_margin_pct": round(total_profit_margin_pct, 2),
        "num_clients_billed": num_clients_billed,
        "avg_profit_per_client_paise": avg_profit_per_client,
    }

    result = {
        "period": label,
        "firm_metrics": firm_metrics,
    }

    # Client-level profitability
    if include_by_client:
        by_client = []
        for client_id in revenue_by_client:
            revenue_paise = revenue_by_client.get(client_id, 0)
            cost_paise = cost_by_client.get(client_id, 0)
            profit_paise = revenue_paise - cost_paise
            profit_margin_pct = (profit_paise / revenue_paise * 100) if revenue_paise > 0 else 0.0

            # Health status based on margin
            if profit_margin_pct >= 25:
                status = "healthy"
            elif profit_margin_pct >= 15:
                status = "fair"
            else:
                status = "at_risk"

            by_client.append({
                "client_id": client_id,
                "client_name": client_map.get(client_id, "Unknown"),
                "revenue_paise": revenue_paise,
                "cost_paise": cost_paise,
                "profit_paise": profit_paise,
                "profit_margin_pct": round(profit_margin_pct, 2),
                "status": status,
            })

        by_client.sort(key=lambda x: x["profit_paise"], reverse=True)
        result["by_client"] = by_client

    # Engagement-level profitability
    if include_by_engagement:
        revenue_by_engagement = invoice_repo.get_revenue_by_engagement(firm_id, date_from, date_to)
        cost_by_engagement = time_tracking_analytics_repo.get_cost_by_engagement(firm_id, date_from, date_to)

        by_engagement = []
        for engagement_id in revenue_by_engagement:
            revenue_paise = revenue_by_engagement[engagement_id].get("revenue_paise", 0)
            cost_paise = cost_by_engagement.get(engagement_id, 0)
            profit_paise = revenue_paise - cost_paise
            profit_margin_pct = (profit_paise / revenue_paise * 100) if revenue_paise > 0 else 0.0

            engagement_details = engagement_map.get(engagement_id, {})
            client_id = engagement_details.get("client_id") or revenue_by_engagement[engagement_id].get("client_id")

            by_engagement.append({
                "engagement_id": engagement_id,
                "service_type": engagement_details.get("service_type", "Unknown"),
                "client_id": client_id,
                "client_name": client_map.get(client_id, "Unknown"),
                "revenue_paise": revenue_paise,
                "cost_paise": cost_paise,
                "profit_paise": profit_paise,
                "profit_margin_pct": round(profit_margin_pct, 2),
            })

        by_engagement.sort(key=lambda x: x["profit_paise"], reverse=True)
        result["by_engagement"] = by_engagement

    # Team member profitability and utilisation
    if include_by_team:
        team_metrics = time_tracking_analytics_repo.get_metrics_by_team_member(firm_id, date_from, date_to)

        by_team_member = []
        for user_id in team_metrics:
            metrics = team_metrics[user_id]
            effort_minutes = metrics.get("effort_minutes", 0)
            billable_minutes = metrics.get("billable_minutes", 0)
            cost_paise = metrics.get("cost_paise", 0)

            # Calculate utilisation as billable minutes / total effort minutes
            utilisation_pct = (billable_minutes / effort_minutes * 100) if effort_minutes > 0 else 0.0

            # Team members don't have direct revenue, so profit = -cost (opportunity cost)
            # This shows how much they "cost" the firm
            by_team_member.append({
                "user_id": user_id,
                "user_name": user_map.get(user_id, "Unknown"),
                "revenue_paise": 0,  # Team members don't directly generate revenue
                "effort_minutes": effort_minutes,
                "cost_paise": cost_paise,
                "profit_paise": -cost_paise,  # Negative because it's a cost
                "profit_margin_pct": 0.0,  # Not applicable for team members
                "utilisation_pct": round(utilisation_pct, 2),
            })

        by_team_member.sort(key=lambda x: x["cost_paise"], reverse=True)
        result["by_team_member"] = by_team_member

    return api_response(True, result)


@router.get("/revenue-vs-effort")
def revenue_vs_effort(
    period: str = "month",
    client_id: str = None,
    engagement_id: str = None,
    current_user: dict = Depends(rbac("analytics", "read")),
):
    """
    Analyze revenue vs effort (billable hours) to calculate realization rates.
    Returns revenue metrics, billable minutes, and calculated efficiency ratios.
    """
    firm_id = current_user.get("firm_id")
    db = _get_db()
    date_from, date_to, label = _period_range(period)

    # Get revenue by engagement
    revenue_by_engagement = invoice_repo.get_revenue_by_period(
        firm_id=firm_id,
        date_from=date_from,
        date_to=date_to,
        statuses=['Issued', 'Paid'],
    )

    # Get effort by engagement
    effort_by_engagement = time_tracking_analytics_repo.get_effort_by_engagement(
        firm_id=firm_id,
        date_from=date_from,
        date_to=date_to,
    )

    # Fetch all engagements for metadata
    all_engagements = engagement_repo.find_all(firm_id=firm_id)
    engagement_map = {e["id"]: e for e in all_engagements}

    # Fetch all clients for metadata. Was previously `client_repo =
    # ClientRepository()` — ClientRepository is never imported (only the
    # client_repo singleton, imported at module scope), which raised
    # NameError on every call and 500'd this endpoint unconditionally.
    all_clients = client_repo.find_all(firm_id=firm_id)
    client_map = {c["id"]: c for c in all_clients}

    # Helper function to calculate realization rate
    def calc_realization_rate(revenue_paise: int, effort_minutes: int, hourly_rate_paise: int) -> float:
        """
        Realization rate = revenue_paise / (effort_minutes * hourly_rate_paise / 60)
        If denominator is 0, return 0.0
        """
        if effort_minutes <= 0 or hourly_rate_paise <= 0:
            return 0.0
        billed_amount = (effort_minutes * hourly_rate_paise) // 60
        if billed_amount <= 0:
            return 0.0
        return round(revenue_paise / billed_amount, 2)

    # Helper function to calculate revenue per hour
    def calc_revenue_per_hour(revenue_paise: int, effort_minutes: int) -> int:
        """
        Revenue per hour (in paise) = revenue_paise / (effort_minutes / 60)
        Returns integer paise
        """
        if effort_minutes <= 0:
            return 0
        return (revenue_paise * 60) // effort_minutes

    # Aggregate data
    total_revenue_paise = sum(r["revenue_paise"] for r in revenue_by_engagement.values())
    total_billable_minutes = sum(e["billable_minutes"] for e in effort_by_engagement.values())
    total_billed_revenue_paise = sum(
        (e["billable_minutes"] * e["avg_hourly_rate_paise"]) // 60
        for e in effort_by_engagement.values()
        if e["avg_hourly_rate_paise"] > 0
    )

    avg_revenue_per_hour_paise = calc_revenue_per_hour(total_revenue_paise, total_billable_minutes)

    # Overall realization rate
    overall_realization_rate = 0.0
    if total_billable_minutes > 0 and total_billed_revenue_paise > 0:
        overall_realization_rate = round(total_revenue_paise / total_billed_revenue_paise, 2)

    # Build by_engagement list
    by_engagement_list = []
    for eng_id, revenue_data in revenue_by_engagement.items():
        effort_data = effort_by_engagement.get(eng_id, {
            "billable_minutes": 0,
            "total_minutes": 0,
            "avg_hourly_rate_paise": 0,
        })

        engagement = engagement_map.get(eng_id, {})
        service_type = engagement.get("service_type", "Unknown")

        billable_minutes = effort_data["billable_minutes"]
        revenue_paise = revenue_data["revenue_paise"]
        hourly_rate_paise = effort_data["avg_hourly_rate_paise"]

        revenue_per_hour = calc_revenue_per_hour(revenue_paise, billable_minutes)
        realization_rate = calc_realization_rate(revenue_paise, billable_minutes, hourly_rate_paise)

        by_engagement_list.append({
            "engagement_id": eng_id,
            "service_type": service_type,
            "revenue_paise": revenue_paise,
            "effort_minutes": billable_minutes,
            "revenue_per_hour_paise": revenue_per_hour,
            "realization_rate": realization_rate,
        })

    # Build by_client list
    by_client_dict: dict[str, dict] = {}
    for eng_id, revenue_data in revenue_by_engagement.items():
        engagement = engagement_map.get(eng_id, {})
        client_id = engagement.get("client_id")
        if not client_id:
            continue

        if client_id not in by_client_dict:
            by_client_dict[client_id] = {
                "client_id": client_id,
                "client_name": client_map.get(client_id, {}).get("client_name", "Unknown"),
                "revenue_paise": 0,
                "effort_minutes": 0,
                "hourly_rate_paise": 0,
                "effort_count": 0,
            }

        effort_data = effort_by_engagement.get(eng_id, {})
        by_client_dict[client_id]["revenue_paise"] += revenue_data["revenue_paise"]
        by_client_dict[client_id]["effort_minutes"] += effort_data.get("billable_minutes", 0)
        by_client_dict[client_id]["hourly_rate_paise"] += effort_data.get("avg_hourly_rate_paise", 0)
        by_client_dict[client_id]["effort_count"] += 1

    # Calculate per-client metrics
    by_client_list = []
    for client_id, client_data in by_client_dict.items():
        revenue_paise = client_data["revenue_paise"]
        effort_minutes = client_data["effort_minutes"]
        avg_hourly_rate = client_data["hourly_rate_paise"] // client_data["effort_count"] if client_data["effort_count"] > 0 else 0

        revenue_per_hour = calc_revenue_per_hour(revenue_paise, effort_minutes)
        realization_rate = calc_realization_rate(revenue_paise, effort_minutes, avg_hourly_rate)

        by_client_list.append({
            "client_id": client_id,
            "client_name": client_data["client_name"],
            "revenue_paise": revenue_paise,
            "effort_minutes": effort_minutes,
            "revenue_per_hour_paise": revenue_per_hour,
            "realization_rate": realization_rate,
        })

    # Filter by client_id or engagement_id if requested
    if client_id:
        by_client_list = [c for c in by_client_list if c["client_id"] == client_id]
        by_engagement_list = [e for e in by_engagement_list if engagement_map.get(e["engagement_id"], {}).get("client_id") == client_id]

    if engagement_id:
        by_engagement_list = [e for e in by_engagement_list if e["engagement_id"] == engagement_id]
        eng = engagement_map.get(engagement_id, {})
        eng_client_id = eng.get("client_id")
        if eng_client_id:
            by_client_list = [c for c in by_client_list if c["client_id"] == eng_client_id]

    # Sort by revenue descending
    by_engagement_list.sort(key=lambda x: x["revenue_paise"], reverse=True)
    by_client_list.sort(key=lambda x: x["revenue_paise"], reverse=True)

    return api_response(True, {
        "period": label,
        "total_revenue_paise": total_revenue_paise,
        "total_billable_minutes": total_billable_minutes,
        "total_billed_revenue_paise": total_billed_revenue_paise,
        "avg_revenue_per_hour_paise": avg_revenue_per_hour_paise,
        "realization_rate": overall_realization_rate,
        "by_client": by_client_list,
        "by_engagement": by_engagement_list,
    })
