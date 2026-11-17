"""What a firm says one filing of each obligation type takes (POST-A-212, migration 671).

Every read and every write goes through the privileged client, naming the firm, because a signed-in session holds no privilege on the
table at all (migration 671 grants it nothing). Mock mode keeps rows in memory for tests and local development."""
from __future__ import annotations

import os
import uuid
from typing import Optional

from core import db_provider
from repositories.base import BaseRepository

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_MOCK_ROWS: list[dict] = []


class ComplianceEffortRepository(BaseRepository[dict]):

    def find_all(self, firm_id: Optional[str] = None, **filters) -> list[dict]:
        if not firm_id:
            raise ValueError("compliance effort estimates are read for a firm")
        if _USE_MOCK:
            return sorted((dict(r) for r in _MOCK_ROWS if r.get("firm_id") == firm_id), key=lambda r: r["compliance_type"])
        rows = (db_provider.service_db().table("compliance_effort_estimates").select("*").eq("firm_id", firm_id)
                .order("compliance_type").execute().data) or []
        return rows

    def upsert(self, firm_id: str, compliance_type: str, minutes: int, updated_by: Optional[str]) -> dict:
        if not firm_id:
            raise ValueError("an estimate belongs to a firm")
        payload = {"estimated_minutes": minutes, "updated_by": updated_by, "updated_at": self.now_iso()}
        if _USE_MOCK:
            for r in _MOCK_ROWS:
                if r["firm_id"] == firm_id and r["compliance_type"] == compliance_type:
                    r.update(payload)
                    return dict(r)
            row = {"id": str(uuid.uuid4()), "firm_id": firm_id, "compliance_type": compliance_type,
                   "created_at": self.now_iso(), **payload}
            _MOCK_ROWS.append(row)
            return dict(row)
        # Written inline with literal keys, not a spread of `payload`, so every column it writes is checked against the real schema
        # (tests/test_backend_columns_exist_pg.py cannot read a `**spread`).
        result = (db_provider.service_db().table("compliance_effort_estimates")
                  .upsert({"firm_id": firm_id, "compliance_type": compliance_type, "estimated_minutes": minutes,
                           "updated_by": updated_by, "updated_at": payload["updated_at"]}, on_conflict="firm_id,compliance_type")
                  .execute())
        return (result.data or [{}])[0]

    def delete(self, firm_id: str, compliance_type: str) -> bool:
        if not firm_id:
            raise ValueError("an estimate belongs to a firm")
        if _USE_MOCK:
            before = len(_MOCK_ROWS)
            _MOCK_ROWS[:] = [r for r in _MOCK_ROWS if not (r["firm_id"] == firm_id and r["compliance_type"] == compliance_type)]
            return len(_MOCK_ROWS) < before
        result = (db_provider.service_db().table("compliance_effort_estimates").delete()
                  .eq("firm_id", firm_id).eq("compliance_type", compliance_type).execute())
        return bool(result.data)


compliance_effort_repo = ComplianceEffortRepository()
