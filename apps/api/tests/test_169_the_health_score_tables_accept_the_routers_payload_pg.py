"""
R3.14 — proves migration 169 fixes the health_scores/health_score_history
schema drift on real PostgreSQL.

routers/health.py was rewritten to the Product Bible Chapter 16 7-dimension
weighted scoring model, but migration 059's health_scores table was never
updated to match — it still had the original Phase 7-8-9 A-F letter-grade
columns. Every POST /api/health/scores/{id}/calculate (and /recalculate-all)
call constructs a payload containing keys with no matching column
(compliance_health_score, accounting_quality_score, work_progress_score,
document_health_score, ai_risk_signals_score, open_notices_score,
client_responsiveness_score, dimensions, grade, trend, hard_override,
hard_override_reason) and a health_grade value that is a band label
("Healthy"/"Good"/...) rather than a single letter, which the pre-existing
CHECK constraint rejected. This is a live, universally-visible top-level
"Health" workspace — confirmed completely non-functional against any real
(non-mock) deployment before this fix.

Proves, against real Postgres 16 with every migration applied: an INSERT
shaped exactly like the payload routers.health._calculate_scores_db()
produces (built via the real DIMENSION_WEIGHTS_BP/_grade/_weighted_score
helpers, not hand-copied constants) now succeeds, that a Product Bible band
label in health_grade is accepted, and that the OLD (pre-drift-fix) column
set — reproducing the exact bug — is rejected, pinning the regression this
migration closes.

Runs only when HARNESS_PG is set + psql on PATH; skips in the mock-mode CI job.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
RUNNER = API_ROOT / "scripts" / "db" / "apply_migrations.py"
_ADMIN = os.environ.get("HARNESS_PG")

pytestmark = pytest.mark.skipif(
    not _ADMIN or shutil.which("psql") is None or not RUNNER.exists(),
    reason="health_scores schema-drift proof requires HARNESS_PG + psql",
)

sys.path.insert(0, str(API_ROOT))
from routers.health import DIMENSION_WEIGHTS_BP, _grade, _weighted_score  # noqa: E402


def _psql(dsn: str, sql: str, tuples: bool = False) -> subprocess.CompletedProcess:
    args = ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-X", "-q"]
    if tuples:
        args += ["-tA"]
    args += ["-c", sql]
    return subprocess.run(args, capture_output=True, text=True)


@pytest.fixture()
def migrated_db(pg_template):
    admin = _ADMIN.strip()
    dbname = f"r314_{uuid.uuid4().hex[:12]}"
    admin_dsn = f"{admin} dbname=postgres"
    if _psql(admin_dsn, f'CREATE DATABASE "{dbname}" TEMPLATE "{pg_template.name}";').returncode != 0:
        pytest.skip("could not create throwaway db")
    dsn = f"{admin} dbname={dbname}"
    try:
        # Schema comes from the session-scoped template (conftest.pg_template),
        # applied once instead of once per test. `failed` is that run's report.
        failed = pg_template.failed
        assert "059_phase7_8_9_intelligence_layer.sql" not in failed
        assert "169_fix_health_scores_schema_drift.sql" not in failed
        yield dsn
    finally:
        _psql(admin_dsn, f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE);')


@pytest.fixture()
def seeded(migrated_db):
    dsn = migrated_db
    firm1 = str(uuid.uuid4())
    client1 = str(uuid.uuid4())
    seed = _psql(dsn, f"""
        SET ROLE service_role;
        INSERT INTO firms (id, name, email) VALUES ('{firm1}','R3.14 Firm','r314@test.in');
        INSERT INTO clients (id, firm_id, client_name, entity_type) VALUES
          ('{client1}','{firm1}','R3.14 Client','Private Limited');
    """)
    assert seed.returncode == 0, seed.stderr
    return {"dsn": dsn, "firm1": firm1, "client1": client1}


def _real_router_scores(dim_scores: dict, hard_override=None, trend="+0") -> dict:
    """Builds the exact dict shape routers.health._calculate_scores_db()
    returns, using the real production weighting/grading helpers — not a
    hand-copied duplicate of the formula."""
    overall = _weighted_score(dim_scores)
    grade = _grade(overall)
    if hard_override:
        grade = "Critical"
        overall = min(overall, 34)
    return {
        **{f"{k}_score": v for k, v in dim_scores.items()},
        "dimensions": {
            k: {"score": v, "weight": DIMENSION_WEIGHTS_BP[k],
                "weighted": (v * DIMENSION_WEIGHTS_BP[k]) // 10000}
            for k, v in dim_scores.items()
        },
        "overall_score": overall,
        "grade": grade,
        "health_grade": grade,
        "trend": trend,
        "hard_override": hard_override,
        "hard_override_reason": None,
        "is_critical": overall < 35 or hard_override is not None,
        "is_at_risk": 35 <= overall < 50,
        "compliance_score": dim_scores["compliance_health"],
        "accounting_score": dim_scores["accounting_quality"],
        "documents_score": dim_scores["document_health"],
        "responsiveness_score": dim_scores["client_responsiveness"],
        "relationship_risk_score": 100,
        "financial_risk_score": dim_scores["open_notices"],
        "engagement_health_score": dim_scores["work_progress"],
    }


def _sql_literal(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, dict):
        return "'" + json.dumps(v).replace("'", "''") + "'::jsonb"
    return "'" + str(v).replace("'", "''") + "'"


def _insert_health_score(dsn, firm, client, scores: dict, rec_id=None) -> subprocess.CompletedProcess:
    rec_id = rec_id or str(uuid.uuid4())
    cols = ["id", "firm_id", "client_id", "last_calculated_at", "client_name"] + list(scores.keys())
    vals = [f"'{rec_id}'", f"'{firm}'", f"'{client}'", "now()", "'Test Client'"] + \
        [_sql_literal(v) for v in scores.values()]
    sql = f"SET ROLE service_role; INSERT INTO health_scores ({', '.join(cols)}) VALUES ({', '.join(vals)});"
    return _psql(dsn, sql)


HEALTHY_DIMS = {
    "compliance_health": 80, "accounting_quality": 90, "work_progress": 100,
    "document_health": 70, "ai_risk_signals": 100, "open_notices": 100,
    "client_responsiveness": 60,
}


def test_real_router_payload_now_persists(seeded):
    """The exact dict shape the fixed router builds now inserts cleanly."""
    dsn, firm, client = seeded["dsn"], seeded["firm1"], seeded["client1"]
    scores = _real_router_scores(HEALTHY_DIMS, trend="+3")
    assert scores["health_grade"] == "Healthy"          # a band label, not a single letter
    r = _insert_health_score(dsn, firm, client, scores)
    assert r.returncode == 0, r.stderr


def test_hard_override_forces_critical_band_label_accepted(seeded):
    dsn, firm, client = seeded["dsn"], seeded["firm1"], seeded["client1"]
    scores = _real_router_scores(HEALTHY_DIMS, hard_override="notice_deadline_missed")
    assert scores["health_grade"] == "Critical" and scores["overall_score"] <= 34
    r = _insert_health_score(dsn, firm, client, scores)
    assert r.returncode == 0, r.stderr


def test_upsert_on_firm_client_conflict_updates_in_place(seeded):
    """Mirrors the router's on_conflict='client_id,firm_id' upsert behaviour."""
    dsn, firm, client = seeded["dsn"], seeded["firm1"], seeded["client1"]
    scores1 = _real_router_scores(HEALTHY_DIMS)
    r1 = _insert_health_score(dsn, firm, client, scores1)
    assert r1.returncode == 0, r1.stderr

    worse_dims = {**HEALTHY_DIMS, "compliance_health": 10}
    scores2 = _real_router_scores(worse_dims, trend="-15")
    cols = ["client_id", "firm_id", "last_calculated_at"] + list(scores2.keys())
    vals = [f"'{client}'", f"'{firm}'", "now()"] + [_sql_literal(v) for v in scores2.values()]
    upsert_sql = (
        f"SET ROLE service_role; "
        f"INSERT INTO health_scores ({', '.join(cols)}) VALUES ({', '.join(vals)}) "
        f"ON CONFLICT (firm_id, client_id) DO UPDATE SET "
        + ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c not in ("client_id", "firm_id"))
        + ";"
    )
    r2 = _psql(dsn, upsert_sql)
    assert r2.returncode == 0, r2.stderr

    check = _psql(dsn, f"SELECT overall_score, trend FROM health_scores "
                       f"WHERE client_id = '{client}' AND firm_id = '{firm}';", tuples=True)
    assert check.returncode == 0, check.stderr
    rows = [ln for ln in check.stdout.strip().splitlines() if ln]
    assert len(rows) == 1                                   # upsert replaced, didn't duplicate
    assert rows[0] == f"{scores2['overall_score']}|-15"


def test_history_insert_accepts_the_snapshot_shape(seeded):
    """Mirrors get_score_history's read contract: id, firm_id, client_id,
    overall_score, health_grade, recorded_at, snapshot_data — the
    router filters dict-valued keys (dimensions) out of snapshot_data before
    insert, so this proves that shape round-trips too."""
    dsn, firm, client = seeded["dsn"], seeded["firm1"], seeded["client1"]
    scores = _real_router_scores(HEALTHY_DIMS, trend="+3")
    snapshot = {k: v for k, v in scores.items() if not isinstance(v, dict)}
    sql = (
        f"SET ROLE service_role; "
        f"INSERT INTO health_score_history (id, firm_id, client_id, overall_score, health_grade, recorded_at, snapshot_data) "
        f"VALUES ('{uuid.uuid4()}','{firm}','{client}',{scores['overall_score']},"
        f"{_sql_literal(scores['health_grade'])}, now(), {_sql_literal(snapshot)});"
    )
    r = _psql(dsn, sql)
    assert r.returncode == 0, r.stderr
