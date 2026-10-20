"""What the Executive Dashboard may say, and what it must say it does not know.

WHY THIS EXISTS (ai-08)
    `get_executive_dashboard` was sold on the page as "AI-powered firm
    intelligence" and about half of it was made up:

      * outstanding invoices, outstanding amount and average collection days were
        three literal zeroes;
      * team utilisation was `min(100, overdue * 5 + 50)` — a number that rises
        when the team is behind and has never seen a timesheet — beside two more
        literal zeroes for overloaded and underutilised staff;
      * the average health score was `75` when no client had a score, which is a
        reading of nothing presented as a reading of "pretty good";
      * every inactive client was worth Rs 5,000 and every client without a GSTIN
        Rs 3,000, stated as "estimated value"; and
      * "compliance coverage" was `100 - overdue * 5`.

    A CA would never forgive any of these in a ledger. This module holds the
    replacements, and every one of them is either computed from records or says
    it is not known.

THE RULE: AN UNKNOWN IS NEVER RENDERED AS A VALUE
    Each function returns `None` (or a payload with `available: False` and a
    reason) where the records cannot answer, and the page renders "No data" with
    the reason. A genuine 0 stays 0 — nothing overdue is a reading.

WHAT IS DELIBERATELY NOT HERE
    * No team-utilisation percentage. Utilisation is time logged against a
      configured weekly capacity, `routers/workload.get_team_workload` already
      computes it from time entries, and a second formula here would be a second
      authority on who is overloaded — the reason `/team/workload` keeps the one.
      The dashboard links to it and states the one thing it can derive from the
      tasks it already reads.
    * No rupee value on a growth opportunity. What an inactive client is worth is
      a fact about the client's fees, which `/practice/profitability` computes;
      a constant per head is not an estimate, it is a guess with a unit.
    * No `billing_trend`. Nothing computed it; the page never rendered it.

Pure: no database handle, no model call.
"""
from __future__ import annotations

from typing import Iterable, Optional

#: Bumped whenever the SHAPE OR MEANING of the stored payload changes. The
#: dashboard is cached for an hour in `ai_summaries.metadata`; a row written by
#: the old code carries the invented figures above, and serving it after a
#: deploy would put them back on the screen for up to an hour. A cached row of an
#: older version is treated as absent. 3: `compliance_failures` counts the obligations that are late by their date (it asked for a
#: stored word nothing writes, so every cached 0 from before is a number the screen must not serve). 4: a client's health is the health engine's
#: stored score (`domain/health/client_scores`) or none; it was `clients.health_score`, which defaults to 100 and which nothing writes, so a
#: cached row from before says every client is healthy and the firm's ring says 100. 5: critical and at risk are the health engine's own verdict
#: (`domain/health/scoring`), the same clients the Health pages list, and no longer a split of the book at 40 and 70 of this module's own.
DASHBOARD_VERSION = 5

#: Compliance statuses that mean the obligation is done.
FILED = ("Filed", "Completed")


def score_of(client: dict) -> Optional[int]:
    """A client's health score, or None where there is none.

    The caller hands in clients whose `health_score` is the health engine's stored result (`domain/health/client_scores.attach`),
    and None where the client has not been scored. An ABSENT or null one — a row built without it, a failed read, a client nobody
    has calculated — is not a score and must not be read as 100.
    """
    v = client.get("health_score")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return int(v)


def client_risk(clients: Iterable[dict]) -> dict:
    """Critical / at-risk / healthy, and the ones nobody has scored.

    CRITICAL AND AT RISK ARE THE ENGINE'S VERDICT, not a threshold of this module's: the clients the Health pages list under those two
    words (`health_critical` / `health_at_risk`, `domain/health/client_scores`). This split the book at 40 and 70 while the engine said
    35 and 50, so a client scoring 38 was "At Risk" on its own Health page and counted critical here. "Healthy" is what is left of the
    scored clients: the engine flagged neither (its bands Healthy, Good and Needs Attention).

    Each client lands in ONE bucket, and the more severe of the recorded status (`critical` or `at_risk`, which a CA marked) and the
    engine's verdict decides it. A client with
    neither a score nor a risk status is `unscored` — not healthy. The old code
    counted them healthy by subtraction (`len(clients) - critical - at_risk`),
    which made "no information" read as "no problem".
    """
    critical = at_risk = healthy = unscored = 0
    for c in clients:
        status = c.get("status")
        if status == "critical" or c.get("health_critical") is True:
            critical += 1
        elif status == "at_risk" or c.get("health_at_risk") is True:
            at_risk += 1
        elif score_of(c) is None:
            unscored += 1
        else:
            healthy += 1
    return {"critical": critical, "at_risk": at_risk, "healthy": healthy,
            "unscored": unscored}


def average_health(clients: Iterable[dict]) -> Optional[int]:
    """The mean of the scores that exist, or None when none do (never 75)."""
    scores = [s for s in (score_of(c) for c in clients) if s is not None]
    if not scores:
        return None
    return sum(scores) // len(scores)


def churn_signals(clients: Iterable[dict], limit: int = 5) -> list[dict]:
    """The clients the engine calls critical or at risk, worst first. Names are the caller's own
    clients — the caller has already narrowed to them.

    The signal says which verdict and what score. It names the engine's verdict and does not claim a threshold of its own ("below
    threshold (50)" was a line this module drew while the engine drew another)."""
    out = []
    for c in clients:
        s = score_of(c)
        if s is None:
            continue
        if c.get("health_critical") is True:
            verdict, risk = "Critical", "high"
        elif c.get("health_at_risk") is True:
            verdict, risk = "At Risk", "medium"
        else:
            continue
        out.append({
            "client_name": c.get("client_name", "Unknown"),
            "signal": f"Health score {s} — {verdict}",
            "risk": risk,
            "_score": s,
        })
    out.sort(key=lambda x: (0 if x["risk"] == "high" else 1, x["_score"]))
    for x in out:
        del x["_score"]
    return out[:limit]


def compliance_coverage(records: Iterable[dict], fy_start: str, today: str) -> dict:
    """Of the filings whose due date has passed this financial year, how many
    are filed.

    `percent` is None when nothing has fallen due yet (1 April, or a client
    with no calendar) — "0% covered" would say they all failed. Integer maths,
    floored: a coverage of 99.6% is not 100%.

    The old figure was `100 - overdue_tasks * 5`: a task count, scaled by a
    constant, labelled as compliance.
    """
    due = filed = 0
    for r in records:
        d = str(r.get("due_date") or "")[:10]
        if not d or not (fy_start <= d <= today):
            continue
        due += 1
        if r.get("status") in FILED:
            filed += 1
    return {
        "percent": (filed * 100) // due if due else None,
        "due": due,
        "filed": filed,
        "basis": "filings whose due date has passed this financial year",
    }


def growth_opportunities(clients: Iterable[dict]) -> list[dict]:
    """Two COUNTS, each with the rule that produced it and no rupee value.

    Labelled rule-based on the row, because that is what they are: a count of
    clients matching a condition. "No GSTIN recorded" is not the same as "not
    registered" — a client below the threshold legitimately has none — so the
    sentence says what was observed and leaves the opportunity to the CA.
    """
    clients = list(clients)
    out = []
    inactive = [c for c in clients if c.get("status") == "inactive"]
    if inactive:
        out.append({
            "type": "reactivation",
            "description": f"{len(inactive)} inactive clients could be re-engaged",
            "count": len(inactive),
            "basis": "rule-based: clients whose status is inactive",
        })
    no_gstin = [c for c in clients
                if c.get("status") == "active" and not c.get("gstin")]
    if no_gstin:
        out.append({
            "type": "advisory",
            "description": (f"{len(no_gstin)} active clients have no GSTIN recorded "
                            f"— check whether each is below the registration "
                            f"threshold or not yet registered"),
            "count": len(no_gstin),
            "basis": "rule-based: active clients with no GSTIN on file",
        })
    return out


def overdue_task_facts(tasks: Iterable[dict]) -> dict:
    """What the overdue tasks say about the team, using only what they carry.

    Three counts and no verdict: how many are overdue, how many of those nobody
    owns, and how many people hold the rest. `assignee_id` is the current column
    and `assigned_to` the older one; either names an owner.
    """
    overdue = unassigned = 0
    holders: set = set()
    for t in tasks:
        overdue += 1
        owner = t.get("assignee_id") or t.get("assigned_to")
        if owner:
            holders.add(owner)
        else:
            unassigned += 1
    return {"overdue_tasks": overdue, "unassigned_overdue_tasks": unassigned,
            "staff_holding_overdue": len(holders)}


def template_summary(facts: dict) -> str:
    """The sentence the dashboard shows when no model wrote one.

    Built only from `facts`, which is what the model would have been given, so a
    model failure costs style and never substance. Says "none in view" rather
    than "0 clients" for an empty scope.
    """
    n = facts["clients"]
    if n == 0:
        return "No clients are in view for this scope, so there is nothing to summarise."
    parts = [f"{n} clients in view: {facts['critical']} critical, "
             f"{facts['at_risk']} at risk."]
    if facts.get("unscored"):
        parts.append(f"{facts['unscored']} have no health score yet.")
    parts.append(f"{facts['overdue_filings']} filings are overdue and "
                 f"{facts['overdue_tasks']} tasks are overdue.")
    if facts.get("workflow_failures") or facts.get("pending_approvals"):
        parts.append(f"{facts['workflow_failures']} workflow failures and "
                     f"{facts['pending_approvals']} approvals are waiting.")
    return " ".join(parts)
