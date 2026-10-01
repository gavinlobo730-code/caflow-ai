"""Feeding AIS figures into the computation, a line at a time
(TDS-INCOME-TAX-10) — IT Act §285BB.

WHAT THIS CLOSES
    The AIS import is built and keeps its readings honest: an unreadable amount
    is a problem, never a zero, and it deliberately computes no difference
    (`domain/income_tax/ais.py`). The computation screen read only the 26AS
    claim, so a CA who had uploaded what the department already knows about the
    client still copied it into the computation by hand.

    This is the line-level prefill. For each of the three lines the computation
    has a box for — salary, interest, dividend — it OFFERS the statement's total
    with its SOURCES (every payer that makes it up), and the CA accepts or
    rejects it. An accepted line fills its box when the box is EMPTY; a typed
    figure that differs from the statement is FLAGGED and KEPT, because the CA
    may know something the statement does not (an account closed, income
    reported under the wrong PAN) and silently replacing their number would be
    worse than not helping.

    AN AIS FIGURE IS WHAT OTHERS REPORTED, NOT THE CLIENT'S INCOME. That is why
    nothing is applied by this module: it computes the suggestion and records the
    decision, and the screen decides whether a box is empty.

WHAT IS REFUSED A PREFILL, AND EACH WITH ITS OWN REASON
    A sale of securities and a property sale carry a CONSIDERATION, not a gain —
    the gain needs the cost and the dates, which the statement does not carry
    (`SUGGESTIONS_REFUSED`). Rent is a gross figure for the house-property
    worksheet, whose income needs the municipal tax, the 30% and the interest. A
    foreign remittance is not income by itself. The reasons are not
    interchangeable and the screen prints the one that applies.

A DECISION IS MADE ON A FIGURE, AND A DIFFERENT FIGURE ASKS AGAIN
    `ais_computation_decisions.amount_paise` is the total the CA was looking at.
    A fresh statement can change a line, and a standing "accepted" against a
    number the CA has not seen would carry onto it silently, so a decision whose
    figure no longer matches is reported as `accepted_stale` / `rejected_stale`
    and is not applied. `ais_service._carry_forward` makes the same choice for a
    reconciliation line, for the same reason.

THE TWO STATEMENT FACTS THAT TRAVEL WITH EVERY ANSWER
    A statement that parsed with problems is SHORT by whatever it could not
    read, so the answer says how many rows are unaccounted for rather than
    presenting a total as complete; and a manual line is labelled, because it is
    not the same evidence as one the department published.

Nothing is posted or filed, and no tax is computed here.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from core.ist_clock import assessment_year_for
from services import ais_service

_logger = logging.getLogger("caflow.ais_computation")
_USE_MOCK = not os.environ.get("SUPABASE_URL")

_MOCK_DECISIONS: dict[tuple, dict] = {}

#: line_key -> (the AIS bucket it totals, the computation box it feeds, and that
#: box's label). The bucket names are `ais.TRANSACTION_TYPES`' own.
SUGGESTABLE: dict[str, tuple[str, str, str]] = {
    "salary": ("Salary", "gross_salary_paise", "Gross Salary"),
    "interest": ("Interest", "other_income_paise", "Other Income"),
    "dividend": ("Dividend", "other_income_paise", "Other Income"),
}

DECISIONS = ("accepted", "rejected")

#: A bucket the statement can carry that the computation takes no box for, and
#: why it is not offered. Each reason names where the figure goes instead.
SUGGESTIONS_REFUSED: dict[str, str] = {
    "Stock Sale": (
        "A sale of securities is a consideration, not a gain. The gain needs "
        "the cost of acquisition and the dates, which the statement does not "
        "carry — work it in the capital gains register and enter the gain."),
    "Property Sale": (
        "A sale of property is a consideration, not a gain. The gain needs the "
        "cost, the indexation or the holding period and any §54 reinvestment, "
        "none of which the statement carries — work it in the capital gains "
        "register."),
    "Rent Received": (
        "Rent is a gross figure. The income from house property needs the "
        "municipal tax, the 30% deduction and the interest as well — work it "
        "in the house-property worksheet, where this is the rent to start from."),
    "Foreign Remittance": (
        "A foreign remittance is a movement of money and is not income by "
        "itself; whether any of it is taxable depends on what it was for."),
    "Other": (
        "These lines are not classified as salary, interest or dividend, so no "
        "box is offered for them. Read each against its own wording."),
}


class DecisionRefused(ValueError):
    """The decision cannot be recorded; the message says why."""


def _supabase():
    from core.supabase_client import get_supabase
    return get_supabase()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── The suggestion ──────────────────────────────────────────────────────────

def _lines_from(records: list[dict]) -> dict[str, dict]:
    """Each suggestable line's total and the payers behind it."""
    out: dict[str, dict] = {}
    for key, (bucket, target, label) in SUGGESTABLE.items():
        recs = [r for r in records if r.get("transaction_type") == bucket]
        if not recs:
            continue
        out[key] = {
            "line_key": key,
            "bucket": bucket,
            "target": target,
            "target_label": label,
            "amount_paise": sum(int(r.get("amount_paise") or 0) for r in recs),
            "tds_paise": sum(int(r.get("tds_deducted_paise") or 0) for r in recs),
            "sources": [{
                "payer": r.get("payer") or r.get("information_source") or "",
                "label": r.get("information_label") or "",
                "amount_paise": int(r.get("amount_paise") or 0),
                # A line the CA added is not a line the department published.
                "source": r.get("source") or "json",
            } for r in sorted(recs, key=lambda x: -int(x.get("amount_paise") or 0))],
        }
    return out


def _state(line: dict, decision: Optional[dict]) -> str:
    """suggested | accepted | rejected | accepted_stale | rejected_stale.

    A decision made on a different figure is STALE and is not applied."""
    if not decision:
        return "suggested"
    current = int(decision.get("amount_paise") or 0) == line["amount_paise"]
    return decision["decision"] + ("" if current else "_stale")


def suggestions(*, firm_id: str, client_id: str, fy: str,
                typed: Optional[dict] = None) -> dict:
    """The computation's AIS lines for this client and year.

    `typed` is what the CA has already put in the boxes, by target
    (`gross_salary_paise`, `other_income_paise`); a target they have not typed
    is absent, which is NOT the same as typed zero.
    """
    typed = typed or {}
    ay = assessment_year_for(fy)
    statement = ais_service.get_statement(
        firm_id=firm_id, client_id=client_id, assessment_year=ay)
    upload = statement.get("upload")
    base = {"financial_year": fy, "assessment_year": ay, "has_statement": upload is not None}
    if upload is None:
        return {**base, "upload": None, "lines": [], "targets": [], "refused": [],
                "gaps": [
                    f"No AIS statement is recorded for AY {ay}. Upload the AIS "
                    "JSON from the income-tax portal and its lines are offered "
                    "here."],
                }

    records = statement.get("records") or []
    lines = _lines_from(records)
    decisions = {d["line_key"]: d for d in _decisions_for(firm_id, client_id, ay)}
    for key, line in lines.items():
        line["state"] = _state(line, decisions.get(key))
        d = decisions.get(key)
        line["decided_at"] = d.get("decided_at") if d else None
        line["decided_amount_paise"] = int(d["amount_paise"]) if d else None

    targets = []
    for target in dict.fromkeys(l["target"] for l in lines.values()):
        own = [l for l in lines.values() if l["target"] == target]
        # What the statement says, over every line NOT rejected on its current
        # figure: a rejected line is one the CA has said does not belong.
        considered = [l for l in own if l["state"] != "rejected"]
        # None where every line was rejected: there is no statement figure
        # left to differ FROM, and a typed figure must not be flagged against a
        # nil the CA themselves said does not apply.
        ais = sum(l["amount_paise"] for l in considered) if considered else None
        applies = sum(l["amount_paise"] for l in own if l["state"] == "accepted")
        t = typed.get(target)
        both = t is not None and ais is not None
        targets.append({
            "target": target,
            "label": own[0]["target_label"],
            "ais_paise": ais,
            # What an EMPTY box may be filled with: accepted lines on their
            # current figure only. A stale acceptance is not applied.
            "accept_paise": applies,
            "typed_paise": t,
            "differs": both and t != ais,
            "difference_paise": (t - ais) if both else None,
        })

    refused = []
    present = {r.get("transaction_type") for r in records}
    for bucket, reason in SUGGESTIONS_REFUSED.items():
        if bucket in present:
            refused.append({
                "bucket": bucket,
                "amount_paise": sum(int(r.get("amount_paise") or 0) for r in records
                                    if r.get("transaction_type") == bucket),
                "reason": reason,
            })

    gaps: list[str] = []
    problems = upload.get("problems") or []
    if problems:
        gaps.append(
            f"This statement parsed with {len(problems)} problem(s), so the "
            "figures below may be SHORT of what the department holds: "
            + " ".join(str(p) for p in problems[:3]))
    if any(s["source"] == "manual" for l in lines.values() for s in l["sources"]):
        gaps.append(
            "At least one line was added by hand rather than read from the "
            "statement the department published.")
    return {**base,
            "upload": {"id": upload.get("id"), "file_name": upload.get("file_name"),
                       "created_at": upload.get("created_at")},
            "lines": list(lines.values()), "targets": targets,
            "refused": refused, "gaps": gaps}


# ── The decision ────────────────────────────────────────────────────────────

def decide(*, firm_id: str, client_id: str, fy: str, line_key: str,
           decision: str, user_id: str) -> dict:
    """Record that the CA accepted or rejected one line — or take the decision
    back (`undecided`), which removes the row.

    The figure recorded is the line's CURRENT total, so what is stored is what
    the CA was looking at."""
    if line_key not in SUGGESTABLE:
        raise DecisionRefused(
            f"{line_key!r} is not a line the computation takes. Expected one of "
            f"{', '.join(SUGGESTABLE)}.")
    if decision not in (*DECISIONS, "undecided"):
        raise DecisionRefused(
            f"A decision is accepted, rejected or undecided, not {decision!r}.")
    ay = assessment_year_for(fy)
    statement = ais_service.get_statement(
        firm_id=firm_id, client_id=client_id, assessment_year=ay)
    line = _lines_from(statement.get("records") or []).get(line_key)
    if line is None:
        raise DecisionRefused(
            f"The statement for AY {ay} carries no {SUGGESTABLE[line_key][0]} "
            "line, so there is nothing to accept or reject.")
    if decision == "undecided":
        _delete_decision(firm_id, client_id, ay, line_key)
    else:
        _upsert_decision({
            "firm_id": firm_id, "client_id": client_id, "assessment_year": ay,
            "line_key": line_key, "decision": decision,
            "amount_paise": line["amount_paise"], "decided_by": user_id,
        })
    d = next((x for x in _decisions_for(firm_id, client_id, ay)
              if x["line_key"] == line_key), None)
    line["state"] = _state(line, d)
    line["decided_at"] = d.get("decided_at") if d else None
    line["decided_amount_paise"] = int(d["amount_paise"]) if d else None
    return line


# ── I/O, both backends ──────────────────────────────────────────────────────

def _decisions_for(firm_id: str, client_id: str, ay: str) -> list[dict]:
    if _USE_MOCK:
        return [dict(d) for k, d in _MOCK_DECISIONS.items()
                if k[0] == firm_id and k[1] == client_id and k[2] == ay]
    return (_supabase().table("ais_computation_decisions").select("*")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("assessment_year", ay).execute().data) or []


def _upsert_decision(row: dict) -> None:
    if _USE_MOCK:
        _MOCK_DECISIONS[(row["firm_id"], row["client_id"],
                         row["assessment_year"], row["line_key"])] = {
            "id": str(uuid4()), "decided_at": _now(), **row}
        return
    (_supabase().table("ais_computation_decisions")
     .upsert({
         "firm_id": row["firm_id"],
         "client_id": row["client_id"],
         "assessment_year": row["assessment_year"],
         "line_key": row["line_key"],
         "decision": row["decision"],
         "amount_paise": row["amount_paise"],
         "decided_by": row["decided_by"],
         "decided_at": _now(),
     }, on_conflict="firm_id,client_id,assessment_year,line_key")
     .execute())


def _delete_decision(firm_id: str, client_id: str, ay: str, line_key: str) -> None:
    if _USE_MOCK:
        _MOCK_DECISIONS.pop((firm_id, client_id, ay, line_key), None)
        return
    (_supabase().table("ais_computation_decisions").delete()
     .eq("firm_id", firm_id).eq("client_id", client_id)
     .eq("assessment_year", ay).eq("line_key", line_key).execute())


def _reset_mock_state() -> None:
    """Tests only."""
    _MOCK_DECISIONS.clear()
