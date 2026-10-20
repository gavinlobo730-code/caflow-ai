"""A client's health score, from the health engine's stored result, or none.

`clients.health_score` is `INTEGER DEFAULT 100` (migration 003) and nothing writes it, so a roll-up that read it called every client
healthy: the executive dashboard said a firm health of 100 and every client Healthy beside a Deadlines screen with 220 overdue
filings and a client Health screen that scored one of them 34 and Critical. The engine's own result lives in `health_scores`
(`repositories/health_scores_repository`), and a client that has never been calculated has no row there: its Health screen answers
"no score yet", and every roll-up must say the same, "not yet scored", and never a number.

Pure: no database handle. `attach` is the one place the two meet.
"""
from __future__ import annotations

from typing import Iterable


def attach(clients: Iterable[dict], score_rows: Iterable[dict]) -> list[dict]:
    """Copies of `clients`, each with `health_score` set to the engine's stored overall score for it, or None when it has none.

    The client row's own `health_score` is overwritten either way: it is the column nothing writes, and a copy that kept it for an
    unscored client would put the default back. A row whose score is not a number is not a score."""
    by_client: dict[str, int] = {}
    for row in score_rows:
        score = row.get("overall_score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            continue
        by_client[str(row.get("client_id"))] = int(score)
    return [{**client, "health_score": by_client.get(str(client.get("id")))} for client in clients]
