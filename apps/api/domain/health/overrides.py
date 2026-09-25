"""A manual health override replaces one dimension's score, and until now it
replaced nothing at all.

WHAT WAS WRONG (3a-4, 25-09-2026). `POST /api/health/scores/{client_id}/override`
has existed since migration 059 and both health screens call it: a CA picks a
dimension, types a score and a reason, and the row lands in `health_overrides`.
Both screens then LIST those rows, over PostgREST, under a heading reading
"Active overrides". And `_calculate_scores_db` never read the table — a
tree-wide grep for `health_overrides` finds the CRUD block in the router, the
two browser reads, and nothing else. So the CA corrected a dimension, saw their
correction listed, and the number they were correcting did not move. The write
succeeded and did nothing, which is worse than a write that fails.

Two more things fell out of the same reading. `DELETE /overrides/{id}` is
written, firm-and-assignment guarded, and has NO caller, so an override with no
expiry could never be withdrawn. And `expires_at` was checked by nothing at
all: `GET /overrides` filters on `is_active` alone, so an override that lapsed
in March was still listed in September as active.

MEASURED BEFORE BUILDING: production holds ZERO `health_overrides` rows, so
none of this is wrong on anybody's screen today — it is wrong the first time a
CA uses the control, which is the same "latent, and on the demo path" shape as
the memory pipeline's retired task-count figures.

⚠️ THIS IS NOT THE HARD OVERRIDE, AND THE TWO MUST NOT BE CONFLATED.
`routers/health._detect_hard_override_db` answers a different question — whether
a Chapter 16 CONDITION (a missed notice deadline, GSTR-3B two months overdue)
forces the grade to Critical whatever the score says. That is derived from the
client's own records and nobody types it. This module is the CA's own manual
correction to one dimension, and it is applied FIRST; the hard override is
applied after and still clamps to 34, so a manual override can never mask a
real Critical. The router's own comment records that masking as the thing to
prevent, and the order is what prevents it.

NOTHING IS GUESSED AND EVERY IGNORED OVERRIDE SAYS WHY. A dimension this model
does not have, a NULL score, a score outside 0–100, an unreadable expiry: each
is named rather than dropped, because an override the CA recorded and that
silently did nothing is the defect this module exists to end. Reporting them is
the point — the screen renders the reason beside the row.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from core.ist_clock import IST
from domain.health.scoring import DIMENSIONS, weighted_score

#: Why an override the caller supplied was not applied. One per row, so a
#: screen can say what to do about it rather than showing a row that appears
#: to be in force and is not.
IGNORED_REASONS: dict[str, str] = {
    "withdrawn": "Withdrawn — this override is no longer active.",
    "expired": "Expired — this override lapsed on its own end date.",
    "unknown_dimension": (
        "Names a dimension this health model does not have, so there is "
        "nothing to replace. Re-record it against one of the seven."
    ),
    "no_score": "No score was recorded, so there is nothing to replace.",
    "out_of_range": "The score recorded is outside 0–100.",
    "unreadable_expiry": (
        "The end date could not be read, so whether this override is still "
        "in force cannot be told. Re-record it with a valid end date."
    ),
    "superseded": (
        "A later override for the same dimension is in force. Only the most "
        "recent one applies."
    ),
}


@dataclass(frozen=True)
class AppliedOverride:
    """A dimension whose score the CA replaced."""
    override_id: str | None
    dimension: str
    computed_score: int
    override_score: int
    reason: str
    expires_at: str | None


@dataclass(frozen=True)
class IgnoredOverride:
    """A recorded override that is NOT in force, and the reason."""
    override_id: str | None
    dimension: str | None
    why: str
    explanation: str


@dataclass(frozen=True)
class OverrideOutcome:
    scores: dict[str, int]
    overall_score: int
    applied: list[AppliedOverride]
    ignored: list[IgnoredOverride]

    @property
    def any_applied(self) -> bool:
        return bool(self.applied)


def _ist_date(value) -> date | None:
    """The Indian calendar date of a stored instant, or of a bare date string.

    `health_overrides.expires_at` is a `timestamptz`, so PostgREST hands it
    back in UTC — and between 18:30 and 24:00 UTC it is already tomorrow in
    India. A firm's day is the Indian one, so the STAMP moves, never the
    question. A bare `YYYY-MM-DD` (what an `<input type="date">` sends) carries
    no instant and is taken as written.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.astimezone(IST).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        if len(text) == 10:
            return date.fromisoformat(text)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.astimezone(IST).date() if parsed.tzinfo else parsed.date()
    except ValueError:
        raise


def _recency_key(row: dict) -> tuple:
    """Latest wins, and the chain is TOTAL so two overrides recorded in the
    same second always resolve the same way on every read."""
    return (
        str(row.get("override_at") or ""),
        str(row.get("created_at") or ""),
        str(row.get("id") or ""),
    )


def apply_overrides(
    computed: dict[str, int],
    overrides: list[dict] | None,
    *,
    as_at: date,
) -> OverrideOutcome:
    """Replace each overridden dimension's score and recompute the composite.

    `as_at` is an IST calendar date and is REQUIRED — there is no default,
    because a clock read inside a pure rule is the thing that makes it
    untestable and makes two callers disagree about which day it is.

    An override is good ON its end date and lapses the day after: a period a
    person picked from a date control runs to the end of the day they picked,
    the same reading `domain/inventory/batches.py` takes of a batch's expiry.
    Reading it the other way withdraws a correction a day early.
    """
    applied: list[AppliedOverride] = []
    ignored: list[IgnoredOverride] = []

    def ignore(row: dict, why: str) -> None:
        ignored.append(IgnoredOverride(
            override_id=row.get("id"),
            dimension=row.get("dimension"),
            why=why,
            explanation=IGNORED_REASONS[why],
        ))

    live_by_dimension: dict[str, dict] = {}

    for row in (overrides or []):
        if not row.get("is_active", True):
            ignore(row, "withdrawn")
            continue

        dimension = row.get("dimension")
        if dimension not in DIMENSIONS:
            ignore(row, "unknown_dimension")
            continue

        score = row.get("override_score")
        if score is None:
            ignore(row, "no_score")
            continue
        try:
            score = int(score)
        except (TypeError, ValueError):
            ignore(row, "no_score")
            continue
        if not 0 <= score <= 100:
            ignore(row, "out_of_range")
            continue

        try:
            expiry = _ist_date(row.get("expires_at"))
        except ValueError:
            ignore(row, "unreadable_expiry")
            continue
        if expiry is not None and expiry < as_at:
            ignore(row, "expired")
            continue

        held = live_by_dimension.get(dimension)
        if held is None or _recency_key(row) > _recency_key(held):
            if held is not None:
                ignore(held, "superseded")
            live_by_dimension[dimension] = row
        else:
            ignore(row, "superseded")

    scores = dict(computed)
    for dimension, row in sorted(live_by_dimension.items()):
        score = int(row["override_score"])
        applied.append(AppliedOverride(
            override_id=row.get("id"),
            dimension=dimension,
            computed_score=int(computed.get(dimension, 100)),
            override_score=score,
            reason=str(row.get("reason") or ""),
            expires_at=row.get("expires_at"),
        ))
        scores[dimension] = score

    return OverrideOutcome(
        scores=scores,
        overall_score=weighted_score(scores),
        applied=applied,
        ignored=ignored,
    )


def as_payload(outcome: OverrideOutcome) -> dict:
    """What the score response carries so a screen can mark an overridden
    dimension and explain an ignored row.

    Both keys are ALWAYS present and empty where there is nothing to say — an
    absent key and an empty list read the same to a screen and are different
    bugs, which is the discipline `domain/accounting/journal_source` records.
    """
    return {
        "overridden_dimensions": [
            {
                "override_id": a.override_id,
                "dimension": a.dimension,
                "computed_score": a.computed_score,
                "override_score": a.override_score,
                "reason": a.reason,
                "expires_at": a.expires_at,
            }
            for a in outcome.applied
        ],
        "ignored_overrides": [
            {
                "override_id": i.override_id,
                "dimension": i.dimension,
                "why": i.why,
                "explanation": i.explanation,
            }
            for i in outcome.ignored
        ],
    }
