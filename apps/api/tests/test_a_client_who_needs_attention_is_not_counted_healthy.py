"""The dashboard's green count is the engine's Healthy and Good bands, and the band between it and the flags has a count of its own (POST-A-286).

WHAT WAS WRONG
    `executive_dashboard.client_risk` put every scored client the engine flagged neither critical nor at risk in the bucket called
    `healthy`, which drew the green "Healthy" bar, filled the AI summary's "Healthy: N" and the payload's `healthy_clients`. The
    engine's grade ladder (`domain/health/scoring.GRADE_BANDS`) has FIVE words, and the third, Needs Attention (50 to 64), is the
    engine's own early warning: a client scoring 55 was badged "Needs Attention" on its own Health page and sat in the green bar.

WHAT IS HELD
    * every score from 0 to 100 lands in exactly one bucket, and the bucket is the one the engine's grade word names: Critical
      and At Risk are the engine's flags, Needs Attention has its own count, and Healthy and Good are the green one;
    * the band is derived from `GRADE_BANDS` (`scoring.NEEDS_ATTENTION_BELOW`), not written as a second pair of numbers;
    * a CA-marked status and a hard override still outrank the score; an unscored client is in none of the four;
    * the payload carries `needs_attention_clients`, the summary sentence and the model's figures carry the count, and the cached
      payload of the previous version (which counted those clients as healthy) is not served.
"""
from __future__ import annotations

import asyncio

import pytest

import domain.ai_copilot_service as mod
from domain.health import scoring
from domain.health.client_scores import attach
from domain.practice import executive_dashboard as ed
from tests.health_double import StoredScoresFrom
from tests.test_the_executive_dashboard_tells_the_truth import FIRM, _dash, _world

#: The bucket the engine's grade word puts a score in.
BUCKET_OF_GRADE = {"Healthy": "healthy", "Good": "healthy", "Needs Attention": "needs_attention",
                   "At Risk": "at_risk", "Critical": "critical"}


def _risk_for(score: int, **extra) -> dict:
    clients = [{"id": "c", "client_name": "C", "status": "active"}]
    rows = StoredScoresFrom([{"id": "c", "health_score": score, **extra}]).find_all(FIRM)
    return ed.client_risk(attach(clients, rows))


# ── the band ────────────────────────────────────────────────────────────────

def test_the_band_is_derived_from_the_engines_bands_and_not_written_twice():
    floors = {band: floor for floor, band in scoring.GRADE_BANDS}
    assert scoring.NEEDS_ATTENTION_BELOW == floors["Good"] == 65
    assert (scoring.AT_RISK_BELOW, scoring.NEEDS_ATTENTION_BELOW) == (floors["Needs Attention"], floors["Good"]) == (50, 65)


@pytest.mark.parametrize("score, bucket", [(49, "at_risk"), (50, "needs_attention"), (55, "needs_attention"), (64, "needs_attention"),
                                           (65, "healthy"), (79, "healthy"), (80, "healthy"), (100, "healthy")])
def test_the_green_count_starts_at_the_floor_of_good_and_not_a_number_written_here(score, bucket):
    assert _risk_for(score)[bucket] == 1


def test_a_scored_client_under_the_line_that_no_flag_accounts_for_is_never_healthy():
    """Hand-built rows only (`attach` derives a flag from the score when the stored one is not a boolean), but the contract is the
    dashboard's own: "Healthy" means the engine's Healthy and Good bands and nothing else. A row whose stored flags disagree with its
    score is counted needing attention, the one bucket that asks for a look without claiming a verdict the engine did not give."""
    flags_off = {"health_critical": False, "health_at_risk": False}
    for score in (0, 20, 34, 49, 50, 64):
        risk = ed.client_risk([{"id": "x", "status": "active", "health_score": score, **flags_off}])
        assert risk == {"critical": 0, "at_risk": 0, "needs_attention": 1, "healthy": 0, "unscored": 0}, score
    for score in (65, 80, 100):
        assert ed.client_risk([{"id": "x", "status": "active", "health_score": score, **flags_off}])["healthy"] == 1, score
    assert ed.client_risk([{"id": "x", "status": "active", "health_score": 49}])["needs_attention"] == 1, "no flag keys at all"


@pytest.mark.parametrize("score", range(0, 101))
def test_every_score_lands_in_exactly_the_bucket_the_engines_grade_word_names(score):
    risk = _risk_for(score)
    assert sum(risk.values()) == 1, f"{score} must be counted once, got {risk}"
    named = BUCKET_OF_GRADE[scoring.grade(score)]
    assert risk[named] == 1, f"{score} is {scoring.grade(score)!r}, so it belongs in {named!r}, got {risk}"


def test_the_five_buckets_are_the_four_the_screen_draws_and_the_unscored():
    assert set(ed.client_risk([])) == {"critical", "at_risk", "needs_attention", "healthy", "unscored"}
    assert set(BUCKET_OF_GRADE.values()) | {"unscored"} == set(ed.client_risk([]))


def test_a_client_scoring_55_is_not_in_the_green_count():
    """The finding's own number."""
    risk = _risk_for(55)
    assert (risk["needs_attention"], risk["healthy"]) == (1, 0)


def test_a_recorded_status_and_a_hard_override_still_outrank_the_score():
    clients = [
        {"id": "a", "client_name": "A", "status": "at_risk", "health_score": 60},
        {"id": "b", "client_name": "B", "status": "critical", "health_score": 60},
        {"id": "c", "client_name": "C", "status": "active", "health_score": 60},
        {"id": "d", "client_name": "D", "status": "active"},
    ]
    rows = StoredScoresFrom([{"id": "c", "health_score": 60}, {"id": "a", "health_score": 60}, {"id": "b", "health_score": 60}]).find_all(FIRM)
    assert ed.client_risk(attach(clients, rows)) == {"critical": 1, "at_risk": 1, "needs_attention": 1, "healthy": 0, "unscored": 1}


def test_a_hard_override_is_critical_whatever_band_the_score_is_in():
    risk = _risk_for(80, health_is_critical=True, health_is_at_risk=False)
    assert (risk["critical"], risk["needs_attention"], risk["healthy"]) == (1, 0, 0)


def test_an_unscored_client_needs_nothing_and_is_not_healthy():
    risk = ed.client_risk([{"id": "x", "client_name": "X", "status": "active", "health_score": None}])
    assert risk == {"critical": 0, "at_risk": 0, "needs_attention": 0, "healthy": 0, "unscored": 1}


def test_a_score_that_is_not_a_number_is_no_score_and_not_a_band():
    assert ed.client_risk([{"health_score": "55"}])["unscored"] == 1
    assert ed.client_risk([{"health_score": True}])["unscored"] == 1


# ── the payload, the summary and the model's figures ────────────────────────

def _clients(*scores):
    return [{"id": f"c{i}", "client_name": f"Client {i}", "health_score": 100, "status": "active"} for i, _ in enumerate(scores)], [
        {"id": f"c{i}", "health_score": s} for i, s in enumerate(scores)]


def test_the_dashboard_payload_carries_the_count_and_the_green_count_excludes_it(monkeypatch):
    clients, rows = _clients(30, 45, 55, 62, 70, 95)
    svc, _ = _world(monkeypatch, clients=clients)
    monkeypatch.setattr(mod, "_get_health_repo", lambda: StoredScoresFrom(rows))
    risk = _dash(svc)["client_risk_insights"]
    assert (risk["critical_clients"], risk["at_risk_clients"], risk["needs_attention_clients"], risk["healthy_clients"],
            risk["unscored_clients"]) == (1, 1, 2, 2, 0)
    assert (risk["critical_clients"] + risk["at_risk_clients"] + risk["needs_attention_clients"] + risk["healthy_clients"]
            + risk["unscored_clients"]) == 6, "every client is in one bucket"


def test_the_payload_is_a_new_version_and_the_old_cached_one_is_not_served(monkeypatch):
    assert ed.DASHBOARD_VERSION >= 7
    clients, rows = _clients(55)
    stale = {"metadata": {"dashboard_version": 6, "dashboard": {"client_risk_insights": {"healthy_clients": 1}}},
             "generated_at": "2026-10-20T00:00:00+00:00", "expires_at": "2999-01-01T00:00:00+00:00"}
    svc, repo = _world(monkeypatch, clients=clients, cached=stale)
    monkeypatch.setattr(mod, "_get_health_repo", lambda: StoredScoresFrom(rows))
    risk = _dash(svc)["client_risk_insights"]
    assert (risk["needs_attention_clients"], risk["healthy_clients"]) == (1, 0), "the version-6 row said this client was healthy"


def test_the_plain_sentence_names_the_band_only_when_a_client_is_in_it():
    base = {"clients": 4, "critical": 1, "at_risk": 1, "overdue_filings": 0, "overdue_tasks": 0}
    assert "Needs Attention band" not in ed.template_summary({**base, "needs_attention": 0})
    assert "Needs Attention band" not in ed.template_summary(base)
    said = ed.template_summary({**base, "needs_attention": 2})
    assert "4 clients in view: 1 critical, 1 at risk, 2 in the Needs Attention band." in said


def _model_dashboard(monkeypatch, reply: str):
    """41 clients, 40 of them in the Needs Attention band and one healthy, with a model that answers `reply`. 40 cannot be the day of
    the month, the year or the average score, so a reply quoting it is grounded only because the dashboard gave the model the count."""
    clients, rows = _clients(*([55] * 40 + [90]))
    svc, _ = _world(monkeypatch, clients=clients)
    monkeypatch.setattr(mod, "_get_health_repo", lambda: StoredScoresFrom(rows))
    seen: list[str] = []

    async def _model(messages, **kw):
        seen.append(messages[-1]["content"])
        return reply, 7
    monkeypatch.setattr(svc, "_call_groq", _model)
    return asyncio.run(svc.get_executive_dashboard(FIRM)), seen


def test_the_model_is_given_the_count_under_the_engines_words(monkeypatch):
    _, seen = _model_dashboard(monkeypatch, "40 clients need attention.")
    assert "Needs attention: 40" in seen[0] and "Healthy or good: 1" in seen[0]
    assert "Healthy: " not in seen[0].replace("Healthy or good: ", ""), "the old label is gone"


def test_a_reply_quoting_the_count_is_grounded_and_one_quoting_another_is_not(monkeypatch):
    out, _ = _model_dashboard(monkeypatch, "40 clients need attention.")
    assert out["summary_source"] == "model", "the count is one of the figures the model may use"
    out, _ = _model_dashboard(monkeypatch, "39 clients need attention.")
    assert out["summary_source"] == "template", "a figure that is not one of the dashboard's is not quoted"
    assert "40 in the Needs Attention band" in out["ai_summary"]
