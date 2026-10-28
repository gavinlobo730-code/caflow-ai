"""The health engine's stored scores: one row per client, written by `POST /api/health/scores/{client_id}/calculate`, by
`POST /api/health/recalculate-all` and by the nightly sweep (`routers/health.recalculate_clients`, `jobs/health_scores_job`), and by
nothing else.

This is what a client's health IS, everywhere a figure is shown: the client's own Health screen reads this table, and so does every
roll-up built on it (`domain/health/client_scores.attach`). `clients.health_score` was not a second copy of it: it was an INTEGER
DEFAULT 100 (migration 003) that no code path wrote, so reading it said every client was healthy; migration 554 dropped it.
"""
import os
from typing import Optional

from core import db_provider
from core.db_paging import fetch_all
from repositories.base import BaseRepository

_USE_MOCK = not os.environ.get("SUPABASE_URL")

_get_db = db_provider.request_db


class HealthScoresRepository(BaseRepository[dict]):

    def find_all(self, firm_id: str, client_id: Optional[str] = None) -> list[dict]:
        """The stored score of every client in the firm that has one (or of the one client asked for): `client_id`, `overall_score`,
        `is_critical`, `is_at_risk`, `last_calculated_at`. A client with no row has not been scored; it is simply absent.

        A firm is required: a read that named none would be a read of every firm's scores, so it raises rather than answering.
        There is no in-memory twin of the table. Without a database nothing is scored, which is what an empty list says, and
        the tests hand the readers their scores through `tests/health_double.StoredScoresFrom`."""
        if not firm_id:
            raise ValueError("the stored health scores are read for a firm")
        if _USE_MOCK:
            return []

        def query():
            q = (_get_db().table("health_scores")
                 .select("id, client_id, overall_score, is_critical, is_at_risk, last_calculated_at")
                 .eq("firm_id", firm_id))
            return q.eq("client_id", client_id) if client_id else q

        return fetch_all(query, key="id", label="health_scores.find_all")


health_scores_repo = HealthScoresRepository()
