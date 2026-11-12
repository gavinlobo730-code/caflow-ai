from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query
from models.common import api_response
from models.fy import OptionalFYLabel
from core.permissions import rbac
from datetime import timedelta
from repositories.time_tracking_analytics_repository import time_tracking_analytics_repo
from domain.practice import profitability as rule_profit
from services import billing_service
from repositories.invoice_repository import invoice_repo
from repositories.engagement_repository import engagement_repo
from repositories.user_repository import user_repo
from repositories.client_repository import client_repo
from core.ist_clock import fy_quarters, ist_fy_label, ist_today
from core import db_provider

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


_get_db = db_provider.request_db


def _period_range(period: str) -> tuple[str, str, str]:
    today = ist_today()
    if period == "week":
        start = today - timedelta(days=today.weekday())
        label = f"Week of {start.strftime('%d %b %Y')}"
    elif period == "quarter":
        # ⚠️ THE BUCKET WAS ALREADY THE INDIAN ONE AND THE LABEL WAS THE
        # CALENDAR ONE. `((month - 1) // 3) * 3 + 1` gives January, April, July
        # or October — which happen to be exactly the four quarters of an
        # Indian financial year, so no window ever moved. But the label was
        # `f"Q{(q_start_month - 1) // 3 + 1} {today.year}"`, so January to
        # March read as "Q1 2026" where a CA in this market reads Q1 as
        # April-June and calls that window Q4 of FY 2025-26. Two endpoints
        # carry this label — /profitability and /revenue-vs-effort (it also sat
        # on /team, /clients and /firm until those no-screen roll-ups were deleted,
        # POST-A-185).
        #
        # `core.ist_clock.fy_quarters` is the one authority for which months a
        # quarter is, and the LABEL is taken from it rather than recomputed:
        # the START stays exactly as it was, because this window is
        # quarter-TO-DATE and `fy_quarters`' own docstring refuses that
        # variant. So this changes a string and no figure.
        month = today.month
        q_start_month = ((month - 1) // 3) * 3 + 1
        start = today.replace(month=q_start_month, day=1)
        fy = ist_fy_label(today)
        iso = today.isoformat()
        label = next(
            (f"{q} {fy}" for q, q_start, q_end in fy_quarters(fy)
             if q_start <= iso <= q_end),
            f"{fy}",
        )
    else:  # month
        start = today.replace(day=1)
        label = today.strftime("%B %Y")
    return start.isoformat(), today.isoformat(), label


def _unrated_people(entries: list[dict], rates: dict, user_map: dict) -> list[dict]:
    """The members whose recorded hours have no cost rate, the most hours first, named for the screen that asks the
    Partner to set one."""
    return [
        {"user_id": uid,
         "user_name": user_map.get(uid, "A member no longer on the team") if uid else "A member no longer on the team",
         "minutes": minutes}
        for uid, minutes in rule_profit.unrated_people(entries, rates)
    ]


@router.get("/profitability")
def profitability_analytics(
    period: str = "month",
    include_by_client: bool = True,
    include_by_engagement: bool = False,
    include_by_team: bool = False,
    current_user: dict = Depends(rbac("analytics", "read")),
    _fees: dict = Depends(rbac("billing", "read")),  # revenue is the practice's fee economics (POST-B-024)
):
    """
    Profitability for the firm: fee revenue less what the time spent on it cost.

    Revenue is the fee BEFORE GST on invoices that are issued, in the period of the invoice's own date (Draft and Cancelled count for nothing). Cost is each
    member's cost rate (`users.cost_rate_paise`) times the hours they recorded; a member with no rate is UNKNOWN, and a
    client with any such hours, or with no hours at all, has no profit and no margin shown (POST-B-321). A client the
    practice recorded time on and never billed is on the list with revenue 0. `domain/practice/profitability` is the
    rule; all arithmetic is integer paise.
    """
    firm_id = current_user.get("firm_id")
    date_from, date_to, label = _period_range(period)

    # Get all clients for lookup. ARCHIVED ONES TOO: a client archived during the period still has its fees and its hours in
    # it, and without its name the row would read "Unknown" beside real money.
    all_clients = client_repo.find_all(firm_id=firm_id, include_archived=True)
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

    # The two reads the answer is built from, each read in full: the issued fee invoices and the ended time entries.
    invoices = invoice_repo.fee_revenue_rows(firm_id, date_from, date_to)
    entries = time_tracking_analytics_repo.get_cost_entries(firm_id, date_from, date_to)
    rates = billing_service.cost_rates_by_user(firm_id)

    # M2: by_client / by_engagement below NAME every client (client_name plus
    # revenue, cost, margin and a health status), so an unassigned Executive
    # could read the commercial position of the firm's entire book.
    #
    # Narrowing here happens BEFORE firm_metrics is summed, so on this endpoint
    # the totals narrow too — deliberately, and unlike client_analytics above,
    # whose total_minutes comes from a SEPARATE firm-wide query rather than
    # from the per-client data being filtered. Leaving these totals firm-wide
    # would mean deriving them from rows the caller is not allowed to see, and
    # would let an Executive read the firm's aggregate commercial position by
    # subtracting their own book. A firm-wide role (_eff is None) is unchanged.
    #
    # THE TIME ENTRIES ARE NARROWED TOO, which the member view never was: `include_by_team` summed every entry of the
    # firm for whoever asked, so an Executive with fee access read each colleague's hours and cost on clients they are
    # not assigned to. Time recorded against no client belongs to no client of the caller and is left out for them.
    from core.authz import effective_client_ids
    _eff = effective_client_ids(current_user)
    if _eff is not None:
        client_map = {k: v for k, v in client_map.items() if str(k) in _eff}
        engagement_map = {
            k: v for k, v in engagement_map.items()
            if str(v.get("client_id")) in _eff
        }
        invoices = [i for i in invoices if str(i.get("client_id")) in _eff]
        entries = [e for e in entries if str(e.get("client_id")) in _eff]

    revenue_by_client = rule_profit.revenue_by_client(invoices)
    effort_by_client = rule_profit.fold_effort(entries, rates, "client_id")
    rows = rule_profit.positions(revenue_by_client, effort_by_client)
    tot = rule_profit.totals(rows)
    without_client = effort_by_client.get(None)

    firm_metrics = {
        "total_revenue_paise": tot.revenue_paise,
        # What the hours that HAVE a cost rate cost: short of the whole cost while `unrated_minutes` or
        # `clients_without_cost` is above 0 (`cost_is_complete` says which), and None when no hour has a rate at all:
        # a sum of nothing is not a cost of 0.
        "total_cost_paise": tot.priced_cost_paise,
        "cost_is_complete": tot.cost_is_complete,
        "unrated_minutes": tot.unrated_minutes,
        # None while any client's cost is unknown. `profit_on_known_paise` is the profit of the `clients_with_cost`
        # clients alone, so the screen can still say something true with its scope named.
        "profit_paise": tot.profit_paise,
        "profit_margin_pct": tot.margin_pct,
        "profit_on_known_paise": tot.profit_on_known_paise,
        "clients_with_cost": tot.clients_with_cost,
        "clients_without_cost": tot.clients_without_cost,
        "num_clients_billed": tot.clients_billed,
        "num_clients_not_billed": tot.clients_not_billed,
        "avg_profit_per_client_paise": tot.avg_profit_per_billed_client_paise,
        # None for a caller assigned to some clients only: time with no client is not theirs to see, and 0 would say "none".
        "minutes_without_client": (without_client.minutes if without_client else 0) if _eff is None else None,
    }

    result = {
        "period": label,
        "firm_metrics": firm_metrics,
        "cost_rates_missing": _unrated_people(entries, rates, user_map),
        "not_measured": list(rule_profit.NOT_MEASURED),
    }

    # Client-level profitability
    if include_by_client:
        result["by_client"] = [
            {
                "client_id": p.key,
                "client_name": client_map.get(p.key, "Unknown"),
                "revenue_paise": p.revenue_paise,
                "cost_paise": p.priced_cost_paise,
                "cost_is_complete": p.cost_is_known,
                "unrated_minutes": p.unrated_minutes,
                "effort_minutes": p.effort.minutes,
                "profit_paise": p.profit_paise,
                "profit_margin_pct": p.margin_pct,
                "status": p.status,
            }
            for p in rows
        ]

    # Engagement-level profitability
    if include_by_engagement:
        revenue_by_engagement = rule_profit.revenue_by_engagement(invoices)
        effort_by_engagement = rule_profit.fold_effort(entries, rates, "engagement_id")
        by_engagement = []
        for p in rule_profit.positions(
            {eid: row["revenue_paise"] for eid, row in revenue_by_engagement.items()}, effort_by_engagement,
        ):
            details = engagement_map.get(p.key, {})
            client_id = details.get("client_id") or (revenue_by_engagement.get(p.key) or {}).get("client_id")
            by_engagement.append({
                "engagement_id": p.key,
                "service_type": details.get("service_type", "Unknown"),
                "client_id": client_id,
                "client_name": client_map.get(client_id, "Unknown"),
                "revenue_paise": p.revenue_paise,
                "cost_paise": p.priced_cost_paise,
                "cost_is_complete": p.cost_is_known,
                "unrated_minutes": p.unrated_minutes,
                "effort_minutes": p.effort.minutes,
                "profit_paise": p.profit_paise,
                "profit_margin_pct": p.margin_pct,
            })
        result["by_engagement"] = by_engagement

    # Team member profitability and utilisation
    if include_by_team:
        by_team_member = []
        for user_id, effort in rule_profit.fold_effort(entries, rates, "user_id").items():
            if user_id is None:
                continue
            # A member either has a cost rate or has not, so their cost is known or it is not: never a 0 for the second.
            cost_paise = effort.cost_paise if effort.cost_is_known else None
            utilisation_pct = (effort.billable_minutes / effort.minutes * 100) if effort.minutes > 0 else 0.0

            # Team members don't have direct revenue, so profit = -cost (opportunity cost)
            # This shows how much they "cost" the firm
            by_team_member.append({
                "user_id": user_id,
                "user_name": user_map.get(user_id, "Unknown"),
                "revenue_paise": 0,  # Team members don't directly generate revenue
                "effort_minutes": effort.minutes,
                "cost_paise": cost_paise,
                "profit_paise": -cost_paise if cost_paise is not None else None,
                "profit_margin_pct": None,  # Not applicable for team members
                "utilisation_pct": round(utilisation_pct, 2),
            })

        by_team_member.sort(key=lambda x: (x["cost_paise"] is None, -(x["cost_paise"] or 0), x["user_id"]))
        result["by_team_member"] = by_team_member

    return api_response(True, result)


@router.get("/concentration")
def fee_concentration(
    period: str = "month",
    current_user: dict = Depends(rbac("analytics", "read")),
    _fees: dict = Depends(rbac("billing", "read")),  # revenue is the practice's fee economics (POST-B-024)
):
    """How much of the practice rests on one client, and where each one sits.

    `/profitability` above computes fee revenue, cost and margin per client and
    renders the list. What no screen could say is the thing that keeps a sole
    practitioner or a three-partner firm awake: **if this client leaves, what
    happens.** A book where one client is 40% of fees is a different business
    from one where the largest is 6%, and the two look identical on a list
    sorted by revenue.

    `domain/practice/concentration` is the rule and NAMES the ICAI
    fee-dependence threat without stating a threshold — icai.org is refused at
    this environment's proxy, and a percentage written from memory on an
    INDEPENDENCE question would hand a firm a clean bill of health nobody
    issued.

    THE SAME TWO READS `/profitability` MAKES, and deliberately no more: this
    is the other half of one fetch, so the two screens cannot disagree about
    the same client. Assignment-scoped identically — an Executive sees the
    concentration of their own book, which is the honest answer to a question
    about the firm they can see."""
    from core.authz import effective_client_ids
    from domain.practice import concentration as rule

    firm_id = current_user.get("firm_id")
    date_from, date_to, label = _period_range(period)

    all_clients = client_repo.find_all(firm_id=firm_id, include_archived=True)
    client_map = {c["id"]: c.get("client_name", "Unknown") for c in all_clients}
    invoices = invoice_repo.fee_revenue_rows(firm_id, date_from, date_to)
    entries = time_tracking_analytics_repo.get_cost_entries(firm_id, date_from, date_to)
    rates = billing_service.cost_rates_by_user(firm_id)

    # Narrowed BEFORE the shares are computed, for `/profitability`'s recorded
    # reason: leaving the total firm-wide would let an unassigned Executive
    # read the firm's aggregate position by subtracting their own book. A
    # firm-wide role (_eff is None) is unchanged.
    _eff = effective_client_ids(current_user)
    if _eff is not None:
        invoices = [i for i in invoices if str(i.get("client_id")) in _eff]
        entries = [e for e in entries if str(e.get("client_id")) in _eff]

    revenue_by_client = rule_profit.revenue_by_client(invoices)
    position_of = {
        p.key: p for p in rule_profit.positions(
            revenue_by_client, rule_profit.fold_effort(entries, rates, "client_id"))
    }

    answer = rule.concentration([
        rule.ClientFees(
            client_id=str(cid),
            client_name=client_map.get(cid, "Unknown"),
            revenue_paise=int(rev or 0),
            # None, not 0, where the cost is not known (no time recorded, or time with no cost rate).
            cost_paise=position_of[cid].cost_paise if position_of[cid].cost_is_known else None,
        )
        for cid, rev in revenue_by_client.items()
    ])

    return api_response(True, {
        "period": label,
        "shares": [
            {
                "client_id": sh.client_id, "client_name": sh.client_name,
                "revenue_paise": sh.revenue_paise, "share_bps": sh.share_bps,
                "rank": sh.rank, "profit_paise": sh.profit_paise,
                "margin_bps": sh.margin_bps,
            }
            for sh in answer.shares
        ],
        "total_revenue_paise": answer.total_revenue_paise,
        "clients_billed": answer.clients_billed,
        "largest_share_bps": answer.largest_share_bps,
        "top_3_share_bps": answer.top_3_share_bps,
        "top_5_share_bps": answer.top_5_share_bps,
        "median_revenue_paise": answer.median_revenue_paise,
        "median_margin_bps": answer.median_margin_bps,
        "icai_fee_dependence": answer.icai_fee_dependence,
        "not_measured": list(answer.not_measured),
    })


@router.get("/revenue-vs-effort")
def revenue_vs_effort(
    period: str = "month",
    client_id: str = None,
    engagement_id: str = None,
    current_user: dict = Depends(rbac("analytics", "read")),
    _fees: dict = Depends(rbac("billing", "read")),  # revenue is the practice's fee economics (POST-B-024)
):
    """
    Analyze revenue vs effort (billable hours) to calculate realization rates.
    Returns revenue metrics, billable minutes, and calculated efficiency ratios.
    """
    firm_id = current_user.get("firm_id")
    date_from, date_to, label = _period_range(period)

    # Get revenue by engagement
    # The same revenue `/profitability` and `/concentration` use (POST-B-321): the fee BEFORE GST on invoices that were
    # issued. This read `total_paise`, which includes the 18% GST, and only 'Issued' and 'Paid', so an issued invoice
    # that fell overdue dropped out and every other one was overstated by the tax.
    revenue_by_engagement = invoice_repo.get_revenue_by_engagement(firm_id, date_from, date_to)

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

    # M2: by_client / by_engagement below name every client (client_name plus
    # revenue, effort and realization rate). Narrow at the engagement map, which
    # is what both lists are keyed off. NOTE the `client_id` PARAMETER on this
    # endpoint is dead — it is shadowed by a loop variable of the same name in
    # the by_client build below and never filters anything — so the mount-level
    # guard firing on it would not have scoped this read either.
    from core.authz import effective_client_ids
    _eff = effective_client_ids(current_user)
    if _eff is not None:
        client_map = {k: v for k, v in client_map.items() if str(k) in _eff}
        engagement_map = {
            k: v for k, v in engagement_map.items()
            if str(v.get("client_id")) in _eff
        }
        revenue_by_engagement = {
            k: v for k, v in revenue_by_engagement.items() if k in engagement_map
        }
        effort_by_engagement = {
            k: v for k, v in effort_by_engagement.items() if k in engagement_map
        }

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
    #
    # ⚠️ `row_client_id`, NOT `client_id`. This block and the one below used to
    # bind the loop variable to the PARAMETER's name, and the filter at the
    # foot of this function reads `if client_id:` — so by the time it ran, the
    # name held the LAST client iterated rather than what the caller asked for.
    # See that filter's own note; the two rebindings are the whole defect.
    by_client_dict: dict[str, dict] = {}
    for eng_id, revenue_data in revenue_by_engagement.items():
        engagement = engagement_map.get(eng_id, {})
        row_client_id = engagement.get("client_id")
        if not row_client_id:
            continue

        if row_client_id not in by_client_dict:
            by_client_dict[row_client_id] = {
                "client_id": row_client_id,
                "client_name": client_map.get(row_client_id, {}).get("client_name", "Unknown"),
                "revenue_paise": 0,
                "effort_minutes": 0,
                "hourly_rate_paise": 0,
                "effort_count": 0,
            }

        effort_data = effort_by_engagement.get(eng_id, {})
        by_client_dict[row_client_id]["revenue_paise"] += revenue_data["revenue_paise"]
        by_client_dict[row_client_id]["effort_minutes"] += effort_data.get("billable_minutes", 0)
        by_client_dict[row_client_id]["hourly_rate_paise"] += effort_data.get("avg_hourly_rate_paise", 0)
        by_client_dict[row_client_id]["effort_count"] += 1

    # Calculate per-client metrics
    by_client_list = []
    for row_client_id, client_data in by_client_dict.items():
        revenue_paise = client_data["revenue_paise"]
        effort_minutes = client_data["effort_minutes"]
        avg_hourly_rate = client_data["hourly_rate_paise"] // client_data["effort_count"] if client_data["effort_count"] > 0 else 0

        revenue_per_hour = calc_revenue_per_hour(revenue_paise, effort_minutes)
        realization_rate = calc_realization_rate(revenue_paise, effort_minutes, avg_hourly_rate)

        by_client_list.append({
            "client_id": row_client_id,
            "client_name": client_data["client_name"],
            "revenue_paise": revenue_paise,
            "effort_minutes": effort_minutes,
            "revenue_per_hour_paise": revenue_per_hour,
            "realization_rate": realization_rate,
        })

    # Filter by client_id or engagement_id if requested.
    #
    # ⚠️ THIS FILTER FIRED FOR EVERY CALLER AND KEPT ONE ARBITRARY CLIENT.
    # Both loops above bound their row's client to `client_id`, the PARAMETER's
    # own name, so on reaching this line the name held the last key of
    # `by_client_dict` — truthy whenever any client had revenue. So
    # `by_client_list` came back with exactly ONE row, chosen by dict iteration
    # order, and `by_engagement_list` with that client's engagements, whether
    # or not anybody asked for a client. The endpoint has never once returned
    # the firm's realization.
    #
    # The comment that used to sit here said the parameter "is dead ... and
    # never filters anything", which is the opposite of what it did and is why
    # this survived: a reader checking the claim would have found the
    # parameter unused in the filter's own line and stopped. The loops are
    # renamed rather than the parameter, so `client_id` means the caller's
    # value everywhere in this function.
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


@router.get("/benchmark")
def tax_benchmark(
    financial_year: Annotated[OptionalFYLabel, Query()] = None,
    client_id: Optional[str] = None,
    current_user: dict = Depends(rbac("analytics", "read")),
):
    """Where each client sits in the firm's own tax and cost distribution.

    `/concentration` above answers the FEE question — if this client leaves,
    what happens — because fee revenue and cost are already aggregated one read
    each. This is the other half, and it could not be built the same way: a
    client's effective tax rate or ITC-to-purchases ratio is derived from that
    client's whole ledger, so computing it for every client to compare one
    against them is CLAUDE.md's reporting rule broken twice over, on an
    endpoint a Partner would leave open.

    So it reads STORED aggregates — `client_period_metrics`, migration 417,
    re-derived nightly by the 06:00 IST sweep. A few dozen rows, and the trends
    are free because a year of rows IS the trend.

    ⚠️ A CLIENT WITH NO FIGURE IS LEFT OUT OF THE STATISTIC, NEVER COUNTED AS
    NIL, and the answer names them. `domain/practice/client_metrics` has the
    argument: in a distribution an absent figure read as zero moves every
    median it is in and makes the client it belongs to read as the firm's best
    performer on a ratio nobody computed for them.

    ASSIGNMENT-SCOPED like every report here — an Executive sees the
    distribution of their own book, which is the honest answer to a question
    about the firm they can see. It is also NOT the only control: migration
    417's RESTRICTIVE assignment-scope policy says the same thing in SQL, for
    the rows the browser could otherwise reach over PostgREST.
    """
    from core.authz import effective_client_ids
    from domain.practice import client_metrics as rule

    firm_id = current_user.get("firm_id")
    fy = financial_year or ist_fy_label()

    rows = _benchmark_rows(firm_id, fy, effective_client_ids(current_user))
    answer = rule.benchmark(rows, fy, subject_client_id=client_id)

    def dist(d) -> dict:
        return {
            "key": d.key, "n": d.n, "median": d.median,
            "lowest": d.lowest, "highest": d.highest,
            "not_measured": list(d.not_measured),
        }

    return api_response(True, {
        "financial_year": answer.financial_year,
        "clients": answer.clients,
        "figures": [dist(d) for d in answer.figures],
        "ratios": [dist(d) for d in answer.ratios],
        "subject_client_id": answer.subject_client_id,
        "subject_positions": [
            {"key": p.key, "value": p.value, "rank": p.rank, "of": p.of}
            for p in answer.subject_positions
        ],
        # The vocabulary travels with the answer so the screen holds no copy of
        # it — the Schedule III caption lesson. `figure_meaning` is what a CA
        # reads under each heading; `money_figures` is which ones format as
        # rupees, because `employee_count` shown as ₹12.00 is twelve people.
        "figure_meaning": dict(rule.FIGURE_MEANING),
        "money_figures": list(rule.MONEY_FIGURES),
        "notes": list(answer.notes),
    })


def _benchmark_rows(firm_id: str, fy: str, allowed) -> list:
    """The stored rows for one firm-year, narrowed to the caller's own book."""
    from domain.practice import client_metrics as rule

    all_clients = client_repo.find_all(firm_id=firm_id)
    names = {str(c["id"]): c.get("client_name", "Unknown") for c in all_clients}

    stored = _client_period_metrics(firm_id, fy)
    out = []
    for r in stored:
        cid = str(r.get("client_id"))
        if allowed is not None and cid not in allowed:
            continue
        out.append(rule.ClientPeriod(
            client_id=cid,
            client_name=names.get(cid, "Unknown"),
            financial_year=fy,
            figures={f: r.get(f) for f in rule.FIGURES},
            gaps=tuple(
                rule.MetricGap(figure=g.get("figure", ""), why=g.get("why", ""))
                for g in (r.get("gaps") or [])
            ),
        ))
    return out


def _client_period_metrics(firm_id: str, fy: str) -> list[dict]:
    """One firm-year of stored rows, or [] in mock mode.

    Mock mode has no sweep and so no rows: the benchmark answers an empty
    distribution rather than inventing one, which is the same posture every
    other report takes there.
    """
    import os
    if not os.environ.get("SUPABASE_URL"):
        return []
    from core.supabase_client import get_supabase
    from core.db_paging import fetch_all
    from domain.practice import client_metrics as rule

    # ⚠️ A LITERAL, not `", ".join(rule.FIGURES)`, for the reason
    # `client_metrics_service` records at its own projection: a `.select()`
    # reached through a name is invisible to
    # `tests/test_backend_columns_exist_pg`, which checks every projection
    # against the real schema as a STRING. A test asserts these are exactly
    # `FIGURES`, so the one list stays the authority and this stays checkable.
    db = get_supabase()
    return fetch_all(
        lambda: db.table("client_period_metrics").select(
            "id, client_id, financial_year, gaps, turnover_paise, "
            "profit_before_tax_paise, tax_expense_paise, purchases_paise, "
            "output_tax_paise, itc_availed_paise, itc_reversed_paise, "
            "gst_cash_paid_paise, tds_deducted_paise, tds_deposited_paise, "
            "payroll_cost_paise, employee_count")
        .eq("firm_id", firm_id).eq("financial_year", fy),
        label="analytics.client_period_metrics",
    )
