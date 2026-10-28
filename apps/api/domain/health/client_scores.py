"""A client's health score, from the health engine's stored result, or none.

`clients.health_score` was `INTEGER DEFAULT 100` (migration 003; dropped by migration 556 on 28-10-2026) and nothing ever wrote it, so a
roll-up that read it called every client healthy: the executive dashboard said a firm health of 100 and every client Healthy beside a Deadlines screen with 220 overdue
filings and a client Health screen that scored one of them 34 and Critical. The engine's own result lives in `health_scores`
(`repositories/health_scores_repository`), and a client that has never been calculated has no row there: its Health screen answers
"no score yet", and every roll-up must say the same, "not yet scored", and never a number.

THE VERDICT TRAVELS WITH THE SCORE. The engine stores `is_critical` and `is_at_risk` beside the score, and the Health pages' "Critical
clients" and "At-risk clients" are exactly those flags, so a roll-up that wants to count the same clients asks the flags and does not
re-derive them from the score with a threshold of its own: the dashboard split at 40 and 70, the assistant at 40 and 60 and the memory
profile at 40 and 70 while the engine said 35 and 50, so one client was "critical" on one screen and "at risk" on another. A stored
flag that is not a boolean is not a verdict, and the one the score gives (`domain/health/scoring`) stands in for it. (A hard override
clamps the engine's score to 34, so the stored flag and the score's own agree today; the stored one still wins, so the roll-ups and the
Health pages stay the same clients if that ever changes.)

Pure: no database handle. `attach` is the one place the two meet.
"""
from __future__ import annotations

from typing import Iterable, Optional

from domain.health.scoring import is_at_risk, is_critical


def _verdict(stored: object, derived: bool) -> bool:
    return stored if isinstance(stored, bool) else derived


def attach(clients: Iterable[dict], score_rows: Iterable[dict]) -> list[dict]:
    """Copies of `clients`, each with `health_score` set to the engine's stored overall score for it, or None when it has none, and
    `health_critical` / `health_at_risk` set to the engine's stored verdict and `health_calculated_at` to the instant it was calculated
    (all None for a client without a score).

    The key is set either way: a client row has no `health_score` of its own any more (the column nothing wrote was dropped), and a copy
    that carried one for an unscored client would put a default back. A row whose score is not a number is not a score."""
    by_client: dict[str, tuple[int, bool, bool, Optional[str]]] = {}
    for row in score_rows:
        score = row.get("overall_score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            continue
        score = int(score)
        stamp = row.get("last_calculated_at")
        by_client[str(row.get("client_id"))] = (
            score, _verdict(row.get("is_critical"), is_critical(score)), _verdict(row.get("is_at_risk"), is_at_risk(score)),
            stamp if isinstance(stamp, str) and stamp else None)
    out = []
    for client in clients:
        score, critical, at_risk, calculated = by_client.get(str(client.get("id")), (None, None, None, None))
        out.append({**client, "health_score": score, "health_critical": critical, "health_at_risk": at_risk,
                    "health_calculated_at": calculated})
    return out
