"""Recurring journal entries that are missing this month (the rule, moved).

`services/intelligence_service.compute_journal_suggestions` held this logic
inline and read the firm's posted entries to apply it. The nightly books check
needs the same answer per client from the ledger it already holds (POST-A-050),
and two copies of a pattern rule drift, so it lives here once and both callers
use it.

THE RULE. An entry pattern (same client, same narration folded to lower case,
same set of accounts) that appeared in at least two PRIOR months of the window
and is missing from the current month is suggested for this month. A suggestion
is a prompt for a human and nothing is posted.

WHAT IT CANNOT KNOW. A narration is typed free text, so a monthly entry whose
words change every month never forms a pattern, and an entry that is
legitimately not due this month (a seasonal one, a loan that was repaid) is
suggested anyway. The count is therefore "entries that look due", never "entries
that are owed".

Pure: no database, no clock beyond the `today` the caller passes.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

#: Prior months an entry must have appeared in before it is called recurring.
MIN_PRIOR_MONTHS = 2

#: How far back the pattern is read: the first of this month, less 92 days
#: (three calendar months and a little).
LOOKBACK_DAYS = 92


def lookback_start(today: date) -> date:
    return today.replace(day=1) - timedelta(days=LOOKBACK_DAYS)


def suggest(posted: Iterable[dict], *, today: date) -> list[dict]:
    """Suggestions for `today`'s month from POSTED entries given as dicts with
    `client_id`, `narration`, `entry_date`, `entry_type`, `id` and `lines` (each
    with `account_id`, and optionally `account_name`, `debit_paise`,
    `credit_paise`, `narration`)."""
    current_month = today.strftime("%Y-%m")
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
    for (cid, _narration, _accounts), p in patterns.items():
        prior_months = {m for m in p["months"] if m < current_month}
        if len(prior_months) >= MIN_PRIOR_MONTHS and current_month not in p["months"]:
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
                "reason": (f"Recurring entry seen in {len(prior_months)} prior months, "
                           f"missing for {current_month}"),
            })
    return suggestions
