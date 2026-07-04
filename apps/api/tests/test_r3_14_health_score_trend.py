"""
R3.14 — health score persistence fix, mock/e2e-mode coverage.

Companion to test_r3_14_health_scores_schema_pg.py (which proves the real
Postgres schema now accepts the router's payload). This file covers the two
pure-Python behaviour changes that a schema-only proof can't exercise:
  1. trend is now a genuinely computed signed delta against the previous
     overall_score, not the hardcoded "+0" placeholder it used to always be.
  2. the calculate_score() write path is a single upsert — the old
     insert/update fallback chain (which could silently return an unpersisted
     row as if it had saved, on the update branch matching zero rows) is gone.

Uses the FakeDB e2e harness. Note: FakeDB's upsert() is a plain insert (it
does not implement ON CONFLICT dedup — see e2e_harness.py) — real upsert
replace-in-place semantics on the (firm_id, client_id) key are proven against
real Postgres in test_r3_14_health_scores_schema_pg.py instead. This file
isolates the trend arithmetic itself, by seeding an existing health_scores
row directly and monkeypatching _calculate_scores_db for full determinism.
"""
import routers.health as health
from tests.e2e_harness import FakeDB


FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "email": "ca@f.test", "role": "Partner"}


def _wire(monkeypatch, db: FakeDB):
    monkeypatch.setattr(health, "_db", lambda: db)
    monkeypatch.setattr(health.timeline_service, "log", lambda *a, **k: None)


def _fixed_scores(overall_score: int, trend_default: str = "+0") -> dict:
    """A minimal, deterministic stand-in for _calculate_scores_db()'s return
    shape — only the keys calculate_score() actually reads/writes matter here."""
    return {
        "overall_score": overall_score,
        "grade": "Healthy" if overall_score >= 80 else "Needs Attention",
        "health_grade": "Healthy" if overall_score >= 80 else "Needs Attention",
        "trend": trend_default,
        "hard_override": None,
        "hard_override_reason": None,
        "is_critical": overall_score < 35,
        "is_at_risk": 35 <= overall_score < 50,
    }


def test_first_calculate_has_no_prior_score_to_diff_against(monkeypatch):
    db = FakeDB()
    _wire(monkeypatch, db)
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "client_name": "Acme", "is_internal": False})
    monkeypatch.setattr(health, "_calculate_scores_db", lambda db, cid, fid: _fixed_scores(85))

    resp = health.calculate_score("CLI", CALLER)
    saved = resp["data"]
    assert saved["overall_score"] == 85
    assert saved["trend"] == "+0"                      # no prior row ⇒ untouched default


def test_second_calculate_computes_a_real_signed_delta(monkeypatch):
    db = FakeDB()
    _wire(monkeypatch, db)
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "client_name": "Acme", "is_internal": False})
    db.seed("health_scores", {"client_id": "CLI", "firm_id": FIRM, "overall_score": 70})

    monkeypatch.setattr(health, "_calculate_scores_db", lambda db, cid, fid: _fixed_scores(85))
    resp = health.calculate_score("CLI", CALLER)
    assert resp["data"]["trend"] == "+15"               # 85 - 70


def test_declining_score_gets_a_negative_trend(monkeypatch):
    db = FakeDB()
    _wire(monkeypatch, db)
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "client_name": "Acme", "is_internal": False})
    db.seed("health_scores", {"client_id": "CLI", "firm_id": FIRM, "overall_score": 85})

    monkeypatch.setattr(health, "_calculate_scores_db", lambda db, cid, fid: _fixed_scores(70))
    resp = health.calculate_score("CLI", CALLER)
    assert resp["data"]["trend"] == "-15"


def test_unchanged_score_gets_a_zero_trend_not_dropped(monkeypatch):
    db = FakeDB()
    _wire(monkeypatch, db)
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "client_name": "Acme", "is_internal": False})
    db.seed("health_scores", {"client_id": "CLI", "firm_id": FIRM, "overall_score": 85})

    monkeypatch.setattr(health, "_calculate_scores_db", lambda db, cid, fid: _fixed_scores(85))
    resp = health.calculate_score("CLI", CALLER)
    assert resp["data"]["trend"] == "+0"


def test_calculate_write_path_is_a_single_upsert_no_silent_fallback(monkeypatch):
    """Regression guard for the removed insert/update fallback chain: the
    saved row must come straight from the upsert call, not a synthesized
    unpersisted dict from a later fallback branch."""
    db = FakeDB()
    _wire(monkeypatch, db)
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "client_name": "Acme", "is_internal": False})
    monkeypatch.setattr(health, "_calculate_scores_db", lambda db, cid, fid: _fixed_scores(90))

    health.calculate_score("CLI", CALLER)
    rows = db.rows("health_scores")
    assert len(rows) == 1 and rows[0]["overall_score"] == 90
