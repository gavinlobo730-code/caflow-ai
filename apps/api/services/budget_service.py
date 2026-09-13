"""Budget versus actuals, for one client and one financial year.

WHAT THIS REPLACED, AND WHY IT IS A SERVICE AND NOT A TABLE (ACC-06)

    `/accounting/budget` kept every figure a CA typed in
    `localStorage["practicesync_budget_<fy>"]` and computed the actuals in the
    browser. Three things were wrong and only the first was in the finding.

    1. The budgets reached no database. Another device, another user or a
       cleared site-data and the year was gone.

    2. THE ACTUALS WERE SILENTLY TRUNCATED. `fetchActualsForQuarter` read
       `journal_lines` joined to `journal_entries`, firm-wide, once per
       quarter, with no paging. PostgREST caps a response at ~1000 rows
       (`db-max-rows`) and reports nothing when it does, so on any client with
       real volume every actual was short by an unknown amount and every
       variance was wrong — confidently, with no error. That is the rule in
       CLAUDE.md: no report may fetch rows proportional to transaction volume.
       The answer here is one row per Revenue/Expense account, about fifty, so
       it comes from `account_period_balances` through
       `ReportingService.period_net_by_account` — ONE bucket read for all four
       quarters.

    3. It was FIRM-WIDE. The chart was fetched on `firm_id` alone, so the grid
       listed every client's Revenue and Expense accounts against firm-wide
       actuals. `account_period_balances.client_id` is NOT NULL and every other
       report in this product is client-scoped; a budget that is not cannot be
       compared with anything.

WHAT IT DOES NOT DO

    Post, close, or carry forward. A budget is a management figure: no
    statutory return reads it, nothing is journalised from it, and a wrong one
    misstates nothing. That is also why the row is Executive+ to write
    (migration 376) rather than Partner-only.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from core.db_paging import fetch_all
from core.ist_clock import fy_quarters

_logger = logging.getLogger("caflow.budget")

_USE_MOCK = not os.environ.get("SUPABASE_URL")

# Mock-mode store, keyed exactly as the unique index is
# (firm_id, client_id, account_id, fy) — so a mock-mode double cannot accept a
# duplicate the database would refuse.
MOCK_BUDGETS: dict[tuple[str, str, str, str], dict] = {}

# Only these two types are budgeted. A balance-sheet account has no annual
# "spend", and offering one would invite a CA to budget cash.
BUDGETABLE_TYPES = ("Revenue", "Income", "Expense")


def _db():
    from core.supabase_client import get_supabase
    return get_supabase()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── the stored figures ──────────────────────────────────────────────────────

def list_budgets(firm_id: str, client_id: str, fy: str, db=None) -> dict[str, int]:
    """{account_id: budget_paise} for one client-year. Missing means the CA has
    not budgeted that account — which is a DIFFERENT fact from a budget of
    zero, and the two are kept apart all the way to the screen."""
    if _USE_MOCK and db is None:
        return {k[2]: int(v["budget_paise"])
                for k, v in MOCK_BUDGETS.items()
                if k[0] == firm_id and k[1] == client_id and k[3] == fy}
    db = db or _db()
    rows = fetch_all(
        lambda: db.table("account_budgets")
                  .select("id, account_id, budget_paise")
                  .eq("firm_id", firm_id).eq("client_id", client_id).eq("fy", fy),
        label="account_budgets.list",
    )
    return {r["account_id"]: int(r.get("budget_paise") or 0) for r in rows}


def set_budget(firm_id: str, client_id: str, account_id: str, fy: str,
               budget_paise: int, actor_id: Optional[str] = None, db=None) -> dict:
    """Record one account's budget for the year. Upsert on the unique key, so
    a CA correcting a figure updates the row rather than accumulating rows —
    the same shape the screen's inline edit has always had."""
    key = (firm_id, client_id, account_id, fy)
    if _USE_MOCK and db is None:
        row = MOCK_BUDGETS.get(key) or {
            "id": str(uuid.uuid4()), "firm_id": firm_id, "client_id": client_id,
            "account_id": account_id, "fy": fy, "created_by": actor_id,
            "created_at": _now(),
        }
        row.update({"budget_paise": int(budget_paise), "updated_by": actor_id,
                    "updated_at": _now()})
        MOCK_BUDGETS[key] = row
        return row
    db = db or _db()
    existing = (db.table("account_budgets").select("id")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .eq("account_id", account_id).eq("fy", fy).limit(1).execute())
    # BOTH payloads are written out as dict LITERALS rather than built once and
    # passed by name. `tests/test_backend_columns_exist_pg.py` parses these
    # call sites to check every column against the real schema, and it can only
    # read a literal — a variable, or a `**spread` inside one, counts against
    # the unreadable budget and the write goes unchecked. A wrong key here does
    # not fail one column: PostgREST rejects the WHOLE row with PGRST204.
    if existing.data:
        return (db.table("account_budgets").update({
            "firm_id": firm_id, "client_id": client_id, "account_id": account_id,
            "fy": fy, "budget_paise": int(budget_paise),
            "updated_by": actor_id, "updated_at": _now(),
        }).eq("id", existing.data[0]["id"]).execute().data[0])
    return db.table("account_budgets").insert({
        "firm_id": firm_id, "client_id": client_id, "account_id": account_id,
        "fy": fy, "budget_paise": int(budget_paise),
        "created_by": actor_id, "updated_by": actor_id, "updated_at": _now(),
    }).execute().data[0]


def clear_budget(firm_id: str, client_id: str, account_id: str, fy: str,
                 db=None) -> bool:
    """Remove one account's budget. Clearing the box DELETES rather than
    writing zero: "not budgeted" and "budgeted at nil" are different
    statements, and a variance against a nil budget is not the same as no
    variance at all."""
    key = (firm_id, client_id, account_id, fy)
    if _USE_MOCK and db is None:
        return MOCK_BUDGETS.pop(key, None) is not None
    db = db or _db()
    res = (db.table("account_budgets").delete()
           .eq("firm_id", firm_id).eq("client_id", client_id)
           .eq("account_id", account_id).eq("fy", fy).execute())
    return bool(res.data)


# ── the screen's answer ─────────────────────────────────────────────────────

def budget_vs_actuals(reporting, firm_id: str, client_id: str, fy: str,
                      db=None) -> dict:
    """One row per budgetable account: the budget, the four quarters' actuals,
    the year's actual and the variance.

    `reporting` is a `ReportingService` built with the caller's own scope — the
    router passes the one `_reporting_service(current_user)` makes, so an
    Executive cannot read a client they are not assigned to by asking for its
    budget.

    THE SIGN. `trial_balance` and the passbook both work in debit-minus-credit,
    so a Revenue account's actual comes out NEGATIVE (revenue is credit-normal)
    and an Expense account's positive. The screen wants both as positive
    magnitudes to set against a positive budget, so the revenue side is
    negated ONCE, here, by the account's own type — not `abs()`, which would
    silently turn a contra-revenue debit into revenue earned and a credit
    balance on an expense head into money spent.
    """
    quarters = fy_quarters(fy)
    measured = reporting.period_net_by_account(
        firm_id, client_id, [(q[0], q[1], q[2]) for q in quarters])
    accounts = measured["accounts"]
    nets = measured["net_paise"]
    budgets = list_budgets(firm_id, client_id, fy, db=db)

    rows = []
    for account_id, meta in accounts.items():
        if meta.get("account_type") not in BUDGETABLE_TYPES:
            continue
        is_income = meta.get("account_type") in ("Revenue", "Income")
        actuals = {}
        for label, _s, _e in quarters:
            net = int(nets.get(label, {}).get(account_id, 0))
            actuals[label] = -net if is_income else net
        total = sum(actuals.values())
        budget = budgets.get(account_id)
        rows.append({
            "account_id": account_id,
            "account_code": meta.get("account_code"),
            "account_name": meta.get("account_name"),
            "account_type": meta.get("account_type"),
            # None, not 0 — see clear_budget. The screen renders an empty box.
            "budget_paise": budget,
            "actuals": actuals,
            "actual_paise": total,
            # Only where a budget exists. A variance against nothing is not a
            # variance, and showing the actual as the whole overspend is how a
            # CA is told they are 100% over on an account they never budgeted.
            "variance_paise": None if budget is None else total - budget,
        })

    rows.sort(key=lambda r: ((r["account_type"] or ""), (r["account_code"] or "")))
    return {
        "fy": fy,
        "client_id": client_id,
        "quarters": [{"label": q[0], "start": q[1], "end": q[2]} for q in quarters],
        "rows": rows,
        "totals": {
            "budget_paise": sum(r["budget_paise"] or 0 for r in rows),
            "actual_paise": sum(r["actual_paise"] for r in rows),
        },
    }
