"""
The Schedule III ratio note, served.

Schedule III Division I, General Instructions — Additional Regulatory
Information, clause (Q), inserted by MCA Notification G.S.R. 207(E) of
24-03-2021. Eleven ratios, the numerator and denominator disclosed with each,
and an explanation required for any change over 25% from the preceding year.

WHERE THE NUMBERS COME FROM, AND WHY THAT MATTERS
    Both years are read through ReportingService.profit_loss / .balance_sheet,
    the same engine the statements use, and bucketed by
    schedule_iii.bucket_amounts, the same function build_schedule_iii uses. A
    ratio note is a note TO the balance sheet — if its Trade Receivables differ
    from the Trade Receivables on the face of the statement, the CA signs two
    numbers that contradict each other.

REPORTING PERFORMANCE
    Two P&L reads and two balance-sheet reads, each already served from
    account_period_balances (migrations 227/228), plus two small keyed lookups.
    Nothing here scales with transaction volume: the second year costs exactly
    what the first does, which is why the preceding-year comparison the statute
    requires is computed rather than left to the CA.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException

from core.ist_clock import ist_fy_label
from domain.reporting import ratios as ratio_rules

_logger = logging.getLogger("caflow.ratios")


def fy_bounds(fy_label: str) -> tuple[str, str]:
    """('2026-04-01', '2027-03-31') for '2026-27'. The Indian financial year is
    1 April to 31 March (CLAUDE.md), and the ratio note is annual because
    clause (Q) compares with "the preceding year"."""
    try:
        start_year = int(str(fy_label).split("-")[0])
        if not (1900 <= start_year <= 2999):
            raise ValueError(start_year)
    except (ValueError, IndexError, AttributeError):
        raise HTTPException(status_code=422,
                            detail=f"fy must look like '2026-27', got {fy_label!r}")
    return f"{start_year}-04-01", f"{start_year + 1}-03-31"


def preceding_fy(fy_label: str) -> str:
    start_year = int(str(fy_label).split("-")[0]) - 1
    return f"{start_year}-{str(start_year + 1)[2:]}"


def _components_for(reporting, firm_id: str, client_id: Optional[str],
                    fy: str) -> ratio_rules.Components:
    start, end = fy_bounds(fy)
    pl = reporting.profit_loss(firm_id, client_id, start, end, basis="accrual")
    bs = reporting.balance_sheet(firm_id, client_id, end, basis="accrual")
    return ratio_rules.components_from(pl, bs)


def _has_activity(c: ratio_rules.Components) -> bool:
    """Whether a year has anything in it at all.

    A client's first year on the platform has a preceding year that is all
    zeros, and comparing against it makes every ratio a >25% move needing an
    explanation the CA cannot write. An empty preceding year is treated as no
    preceding year, which is what it is."""
    return any((c.total_revenue, c.total_expenses, c.current_assets,
                c.current_liabilities, c.shareholders_funds))


def _explanations(db, firm_id: str, client_id: str, fy: str) -> dict[str, str]:
    if db is None:
        return {}
    try:
        rows = (db.table("schedule_iii_ratio_explanations")
                .select("ratio_key, explanation")
                .eq("firm_id", firm_id).eq("client_id", client_id).eq("fy_label", fy)
                .execute().data) or []
    except Exception as e:                                        # noqa: BLE001
        _logger.error("ratio explanations unavailable (%s %s %s): %s",
                      firm_id, client_id, fy, e)
        return {}
    return {r["ratio_key"]: r.get("explanation") or "" for r in rows if r.get("ratio_key")}


def _principal_repaid(db, firm_id: str, client_id: str, fy: str) -> Optional[int]:
    if db is None:
        return None
    try:
        rows = (db.table("schedule_iii_ratio_inputs")
                .select("principal_repaid_paise")
                .eq("firm_id", firm_id).eq("client_id", client_id).eq("fy_label", fy)
                .limit(1).execute().data) or []
    except Exception as e:                                        # noqa: BLE001
        _logger.error("ratio inputs unavailable (%s %s %s): %s", firm_id, client_id, fy, e)
        return None
    if not rows:
        return None
    v = rows[0].get("principal_repaid_paise")
    return None if v is None else int(v)


def ratio_note(reporting, db, firm_id: str, client_id: str,
               fy: Optional[str] = None) -> dict:
    """The clause (Q) table for one client and one financial year."""
    if not client_id:
        raise HTTPException(status_code=422,
                            detail="client_id is required — the ratio note is a note to "
                                   "one client's balance sheet")
    fy = fy or ist_fy_label()
    fy_bounds(fy)                                  # validates, and 422s if it does not
    prior_fy = preceding_fy(fy)

    current = _components_for(reporting, firm_id, client_id, fy)
    prior = _components_for(reporting, firm_id, client_id, prior_fy)
    if not _has_activity(prior):
        prior = None

    out = ratio_rules.build(
        current, prior,
        principal_repaid_paise=_principal_repaid(db, firm_id, client_id, fy),
        explanations=_explanations(db, firm_id, client_id, fy),
    )
    out["fy"] = fy
    out["preceding_fy"] = prior_fy if prior is not None else None
    out["period"] = dict(zip(("start", "end"), fy_bounds(fy)))
    return out


# ── Recording what the CA supplies ───────────────────────────────────────────

def valid_ratio_keys() -> frozenset:
    """The keys the note actually produces. Derived from the rules module rather
    than listed here, so adding a ratio cannot leave this behind."""
    return frozenset(r["key"] for r in
                     ratio_rules.build(ratio_rules.Components())["ratios"])


def save_explanation(db, firm_id: str, client_id: str, fy: str, ratio_key: str,
                     explanation: str, actor_id: Optional[str] = None) -> dict:
    """Record why a ratio moved. Clause (Q) requires this for a change over 25%,
    and it is the CA's sentence, not a derivation."""
    fy_bounds(fy)
    if ratio_key not in valid_ratio_keys():
        raise HTTPException(
            status_code=422,
            detail=f"unknown ratio {ratio_key!r}; expected one of "
                   f"{sorted(valid_ratio_keys())}")
    text = (explanation or "").strip()
    if not text:
        raise HTTPException(status_code=422,
                            detail="an explanation cannot be blank — delete it instead")
    if db is None:
        raise HTTPException(status_code=503,
                            detail="No database configured — an explanation cannot be recorded")

    # The payload is written INLINE with literal keys, not built above the call:
    # tests/test_backend_columns_exist_pg.py can only check the columns of a
    # query it can read, and a dict held in a variable hides every one of them.
    # Same choice as services/ageing_schedule_service._write.
    db.table("schedule_iii_ratio_explanations").upsert(
        {"firm_id": firm_id, "client_id": client_id, "fy_label": fy,
         "ratio_key": ratio_key, "explanation": text,
         "recorded_by": actor_id, "updated_at": _now()},
        on_conflict="firm_id,client_id,fy_label,ratio_key").execute()
    return {"fy": fy, "ratio_key": ratio_key, "explanation": text}


def delete_explanation(db, firm_id: str, client_id: str, fy: str, ratio_key: str) -> dict:
    fy_bounds(fy)
    if db is None:
        raise HTTPException(status_code=503, detail="No database configured")
    (db.table("schedule_iii_ratio_explanations").delete()
     .eq("firm_id", firm_id).eq("client_id", client_id)
     .eq("fy_label", fy).eq("ratio_key", ratio_key).execute())
    return {"fy": fy, "ratio_key": ratio_key, "explanation": None}


def save_principal_repaid(db, firm_id: str, client_id: str, fy: str,
                          principal_repaid_paise: Optional[int],
                          actor_id: Optional[str] = None) -> dict:
    """The principal repaid on long-term borrowings during the year — the one
    figure Debt Service Coverage needs that the ledger cannot supply.

    None is a legitimate value: it puts the ratio back into its gap, which a CA
    who entered a wrong figure must be able to do. Zero is NOT the same thing —
    zero principal repaid means debt service is finance costs alone, and the
    ratio is computed."""
    fy_bounds(fy)
    if principal_repaid_paise is not None:
        if not isinstance(principal_repaid_paise, int) or isinstance(principal_repaid_paise, bool):
            raise HTTPException(status_code=422,
                                detail="principal_repaid_paise must be an integer number of paise")
        if principal_repaid_paise < 0:
            raise HTTPException(status_code=422,
                                detail="principal repaid cannot be negative")
    if db is None:
        raise HTTPException(status_code=503,
                            detail="No database configured — the figure cannot be recorded")

    db.table("schedule_iii_ratio_inputs").upsert(
        {"firm_id": firm_id, "client_id": client_id, "fy_label": fy,
         "principal_repaid_paise": principal_repaid_paise,
         "recorded_by": actor_id, "updated_at": _now()},
        on_conflict="firm_id,client_id,fy_label").execute()
    return {"fy": fy, "principal_repaid_paise": principal_repaid_paise}


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
