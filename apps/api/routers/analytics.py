from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from models.common import api_response
from models.fy import OptionalFYLabel
from core.permissions import rbac
from datetime import timedelta
from repositories.time_tracking_analytics_repository import time_tracking_analytics_repo
from domain.practice import profitability as rule_profit
from domain.practice import realization as rule_real
from services import billing_service
from repositories.invoice_repository import invoice_repo
from repositories.engagement_repository import engagement_repo
from repositories.user_repository import user_repo
from repositories.client_repository import client_repo
from core.ist_clock import fy_bounds, fy_quarters, ist_fy_label, ist_today
from core import db_provider

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


_get_db = db_provider.request_db


#: The windows the three analytics endpoints answer for. `fy` is one whole financial year (`financial_year`, to today for the
#: one that is running). An unknown word is a 422 at the door and never read as `month`, which is what it used to be.
PeriodWord = Literal["week", "month", "quarter", "fy"]


def _period_range(period: str, financial_year: Optional[str] = None) -> tuple[str, str, str]:
    """`(first day, last day, label)` of the window an analytics endpoint answers for: the one resolver for all three.

    POST-A-427. The screen offered this week, this month and this quarter to date, each ending today, and any other word
    was read as `month`, so last financial year could not be opened at all and the seeded FY 2025-26 firm showed an empty
    screen from 1 April 2026. `fy` is a whole financial year (`models.fy.FYLabel`, from `fy_bounds`, the one authority for
    its first and last day); for the year that is running it ends today, because nothing has happened after today, and the
    label says "to date". A year that has not started is refused in words, and so is a `financial_year` with any other
    window, which would be ignored and read as the month."""
    today = ist_today()
    if period != "fy" and financial_year:
        raise HTTPException(status_code=422, detail="A financial year can be asked for only with the window 'fy'.")
    if period == "fy":
        fy = financial_year or ist_fy_label(today)
        first, last = fy_bounds(fy)
        if first > today.isoformat():
            raise HTTPException(status_code=422, detail=f"Financial year {fy} has not started yet.")
        if last > today.isoformat():
            return first, today.isoformat(), f"FY {fy} (to date)"
        return first, last, f"FY {fy}"
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
    elif period == "month":
        start = today.replace(day=1)
        label = today.strftime("%B %Y")
    else:
        # Reached only by a caller that skips the route's `PeriodWord` (a test, another module): the door answers 422 for
        # an unknown word, and this does too rather than reading it as the month, which is what it used to do.
        raise HTTPException(status_code=422, detail=f"Unknown window {period!r}: use week, month, quarter or fy.")
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
    period: PeriodWord = "month",
    financial_year: Annotated[OptionalFYLabel, Query()] = None,
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
    date_from, date_to, label = _period_range(period, financial_year)

    # Get all clients for lookup. ARCHIVED ONES TOO: a client archived during the period still has its fees and its hours in
    # it, and without its name the row would read "Unknown" beside real money.
    client_map = client_repo.names_by_id(firm_id, include_archived=True)

    # Get all users for lookup
    all_users = user_repo.find_all(firm_id=firm_id)
    user_map = {u["id"]: u.get("full_name") or u.get("name") or u.get("email", "Unknown") for u in all_users}

    # Get all engagements for lookup
    # Read only for the engagement view: the map is used nowhere else, and it is one request per page of the firm's engagements.
    engagement_map = engagement_repo.services_by_id(firm_id) if include_by_engagement else {}

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
    period: PeriodWord = "month",
    financial_year: Annotated[OptionalFYLabel, Query()] = None,
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
    date_from, date_to, label = _period_range(period, financial_year)

    client_map = client_repo.names_by_id(firm_id, include_archived=True)
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
    period: PeriodWord = "month",
    financial_year: Annotated[OptionalFYLabel, Query()] = None,
    client_id: str = None,
    engagement_id: str = None,
    current_user: dict = Depends(rbac("analytics", "read")),
    _fees: dict = Depends(rbac("billing", "read")),  # revenue is the practice's fee economics (POST-B-024)
):
    """
    Revenue against the worth of the billable time (realization), per engagement, per client and for the firm.

    Revenue is the fee BEFORE GST on invoices that are issued, the one definition `/profitability` and `/concentration`
    use (POST-B-321). The worth is each billable entry priced from its own rate, `billable_rate_paise` first and the
    legacy `hourly_rate_paise` second, floored per entry; an entry nobody priced is named and never worth 0, and a row
    with one has no realization (POST-A-426). An engagement with time and no invoice is a row with a realization of 0.0.
    A client's and the firm's ratio is taken on the engagements that have billable time: fees on one with none, fees on an
    invoice naming no engagement and time naming no engagement are named beside it and left out of it.
    `domain/practice/realization` is the rule; all arithmetic is integer paise.
    """
    firm_id = current_user.get("firm_id")
    date_from, date_to, label = _period_range(period, financial_year)

    invoices = invoice_repo.fee_revenue_rows(firm_id, date_from, date_to)
    entries = time_tracking_analytics_repo.get_worth_entries(firm_id, date_from, date_to)

    # M2: by_client / by_engagement below name every client (client_name plus revenue, effort and realization rate).
    # Narrow BEFORE any total is made, on the CLIENT each invoice and each entry itself names, so an assigned caller's
    # figures (the firm's included, and the minutes with no engagement) are of their own book and nothing else. The
    # lists below carry NAMES and nothing a figure depends on: a list cut short by the database's row cap costs a label
    # ("Unknown"), never a fee or an hour. A firm-wide role (_eff is None) is unchanged.
    from core.authz import effective_client_ids
    _eff = effective_client_ids(current_user)
    if _eff is not None:
        invoices = [i for i in invoices if str(i.get("client_id")) in _eff]
        entries = [e for e in entries if str(e.get("client_id")) in _eff]

    revenue_by_engagement = rule_profit.revenue_by_engagement(invoices)
    revenue_paise_by_engagement = {k: v["revenue_paise"] for k, v in revenue_by_engagement.items()}
    worth_by_engagement = rule_real.fold_worth(entries, "engagement_id")
    # Which client an engagement is, from the rows themselves (an invoice and an entry each carry their client).
    client_of_engagement: dict[str, str] = {}
    for eng_id, v in revenue_by_engagement.items():
        if v.get("client_id"):
            client_of_engagement[eng_id] = v["client_id"]
    for e in entries:
        if e.get("engagement_id") and e.get("client_id"):
            client_of_engagement.setdefault(e["engagement_id"], e["client_id"])

    engagement_rows = rule_real.rows(revenue_paise_by_engagement, worth_by_engagement)
    firm = rule_real.combine("firm", engagement_rows)
    fees_outside = rule_real.revenue_outside_engagements(invoices)
    minutes_outside = rule_real.minutes_outside_engagements(entries)

    engagement_map = engagement_repo.services_by_id(firm_id)
    # ARCHIVED CLIENTS TOO, as `/profitability` reads them: a client archived during the period still has its fees and
    # hours in it, and without its name the row would read "Unknown" beside real money.
    client_map = client_repo.names_by_id(firm_id, include_archived=True)

    # Build by_engagement list
    by_engagement_list = []
    for row in engagement_rows:
        by_engagement_list.append({
            "engagement_id": row.key,
            "service_type": engagement_map.get(row.key, {}).get("service_type", "Unknown"),
            "revenue_paise": row.revenue_paise,
            "revenue_without_time_paise": row.revenue_without_time_paise,
            "effort_minutes": row.worth.billable_minutes,
            "unpriced_minutes": row.worth.unpriced_minutes,
            "billable_time_value_paise": row.worth.priced_value_paise,
            "revenue_per_hour_paise": row.revenue_per_hour_paise,
            "realization_rate": row.realization_rate,
        })

    # Build by_client list: the engagements' rows added up per client.
    #
    # ⚠️ `row_client_id`, NOT `client_id`. This block used to bind the loop variable to the PARAMETER's name, and the
    # filter at the foot of this function reads `if client_id:` — so by the time it ran, the name held the LAST client
    # iterated rather than what the caller asked for. See that filter's own note; the rebinding is the whole defect.
    rows_by_client: dict[str, list[rule_real.Row]] = {}
    for row in engagement_rows:
        row_client_id = client_of_engagement.get(row.key)
        if row_client_id:
            rows_by_client.setdefault(row_client_id, []).append(row)
    client_rows = sorted(
        (rule_real.combine(cid, parts) for cid, parts in rows_by_client.items()),
        key=lambda r: (-r.revenue_paise, r.key))

    by_client_list = []
    for row in client_rows:
        by_client_list.append({
            "client_id": row.key,
            "client_name": client_map.get(row.key, "Unknown"),
            "revenue_paise": row.revenue_paise,
            "revenue_without_time_paise": row.revenue_without_time_paise,
            "revenue_without_engagement_paise": fees_outside.get(row.key, 0),
            "minutes_without_engagement": minutes_outside.get(row.key, 0),
            "effort_minutes": row.worth.billable_minutes,
            "unpriced_minutes": row.worth.unpriced_minutes,
            "billable_time_value_paise": row.worth.priced_value_paise,
            "revenue_per_hour_paise": row.revenue_per_hour_paise,
            "realization_rate": row.realization_rate,
        })

    # Filter by client_id or engagement_id if requested.
    #
    # ⚠️ THIS FILTER FIRED FOR EVERY CALLER AND KEPT ONE ARBITRARY CLIENT, once, because the loops above bound their
    # row's client to `client_id`, the PARAMETER's own name (see `test_realization_reports_the_whole_book`). The loops are
    # renamed rather than the parameter, so `client_id` means the caller's value everywhere in this function. The TOTALS
    # are the firm's (or the caller's book's) whatever the filter says, as they always were.
    if client_id:
        by_client_list = [c for c in by_client_list if c["client_id"] == client_id]
        by_engagement_list = [e for e in by_engagement_list if client_of_engagement.get(e["engagement_id"]) == client_id]

    if engagement_id:
        by_engagement_list = [e for e in by_engagement_list if e["engagement_id"] == engagement_id]
        eng_client_id = client_of_engagement.get(engagement_id)
        if eng_client_id:
            by_client_list = [c for c in by_client_list if c["client_id"] == eng_client_id]

    return api_response(True, {
        "period": label,
        "total_revenue_paise": firm.revenue_paise,
        "revenue_without_time_paise": firm.revenue_without_time_paise,
        "revenue_without_engagement_paise": sum(fees_outside.values()),
        "total_billable_minutes": firm.worth.billable_minutes,
        "unpriced_minutes": firm.worth.unpriced_minutes,
        "billable_time_value_paise": firm.worth.priced_value_paise,
        "minutes_without_engagement": sum(minutes_outside.values()),
        "avg_revenue_per_hour_paise": firm.revenue_per_hour_paise,
        "realization_rate": firm.realization_rate,
        "by_client": by_client_list,
        "by_engagement": by_engagement_list,
        "not_measured": list(rule_real.NOT_MEASURED),
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

    # ARCHIVED CLIENTS TOO: the nightly sweep stores a row for every client of the firm, so the benchmark's list of clients with no figure names an archived one, and
    # without its name that line would read "Unknown" beside a stored row (the other three practice screens name them for the same reason).
    names = {str(k): v for k, v in client_repo.names_by_id(firm_id, include_archived=True).items()}

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
