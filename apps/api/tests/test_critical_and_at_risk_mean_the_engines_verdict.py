"""CRITICAL and AT RISK mean the health engine's verdict wherever the product counts clients by those words (POST-A-285).

WHAT WAS WRONG
    Four places drew the two lines at four different scores. The engine stores `is_critical` (under 35) and `is_at_risk` (35 to 49)
    beside every score, and the Health pages' "Critical clients" and "At-risk clients" lists are exactly those flags. The executive
    dashboard split the book at 40 and 70, the assistant counted under 40 and under 60 and the AI memory profile 40 and 70, and the two
    list pages themselves dropped everything under 40 in the browser, so a client scoring 38 was "At Risk" on its own Health page and
    counted critical on the dashboard, and one scoring 67 was "Good" there and "at risk" on the dashboard. It was latent while every
    roll-up read a column that said 100 (POST-A-279); once the roll-ups read the engine's stored scores it was on the screen.

WHAT IS HELD
    * `domain/health/scoring` owns the two lines, DERIVED from `GRADE_BANDS` (the floor of "At Risk" and the floor of "Needs
      Attention"), so the flags cannot drift from the bands, and the router asks it for both flags it stores.
    * `domain/health/client_scores.attach` carries the engine's stored verdict onto each client; the stored flag wins over the one the
      score would give, and one that is not a boolean is not a verdict. (A hard override clamps the engine's score to 34, so the two
      agree today; the fixtures that store a critical flag beside a score of 80 describe a row the engine cannot write now, and test
      that the stored verdict, not the score, is what the readers ask.)
    * The dashboard, the assistant and the memory profile count by that verdict; the dashboard agrees with the Health router's own
      roll-up on the same stored rows. The two web list pages show exactly the flags
      (`apps/web/scripts/the-health-lists-are-the-engines-flags.test.ts`).
    * Other graded numbers (the relationship health in `services/intelligence_service`, the compliance risk level) are other measures
      with their own lines and are not under this rule.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

import domain.ai_copilot_service as mod
import domain.memory_pipeline as memory
from domain.health import scoring
from domain.health.client_scores import attach
from domain.practice import executive_dashboard as ed
from tests.health_double import StoredScoresFrom

FIRM = "f1"
API_ROOT = pathlib.Path(__file__).resolve().parents[1]


# ── the two lines ────────────────────────────────────────────────────────────

def test_the_two_lines_are_the_floors_of_the_bands_they_come_from():
    floors = {name: floor for floor, name in scoring.GRADE_BANDS}
    assert scoring.CRITICAL_BELOW == floors["At Risk"] == 35
    assert scoring.AT_RISK_BELOW == floors["Needs Attention"] == 50


@pytest.mark.parametrize("score, critical, at_risk", [
    (0, True, False), (34, True, False), (35, False, True), (49, False, True), (50, False, False), (100, False, False)])
def test_the_boundaries(score, critical, at_risk):
    assert scoring.is_critical(score) is critical
    assert scoring.is_at_risk(score) is at_risk


def test_a_hard_override_is_critical_at_any_score_the_function_is_asked_about():
    assert scoring.is_critical(95, "gstin_cancelled") is True
    assert scoring.is_critical(95, None) is False


def test_the_router_stores_the_flags_the_scoring_module_gives_and_no_threshold_of_its_own():
    """No dict in the Health router stores `is_critical` / `is_at_risk` from a comparison of its own, and the two score builders (the
    mock and the database one) store them by asking the module. Written as the rule (no threshold beside the flag, one call to the one
    definition) and not as a spelling of the old comparison."""
    tree = ast.parse((API_ROOT / "routers" / "health.py").read_text(encoding="utf-8"))
    calls = {"is_critical": 0, "is_at_risk": 0}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=True):
            if not (isinstance(key, ast.Constant) and key.value in calls):
                continue
            assert not any(isinstance(n, ast.Compare) for n in ast.walk(value)), (
                f"routers/health.py line {value.lineno} stores {key.value} from a comparison of its own")
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == key.value:
                calls[key.value] += 1
                # A hard override is what only the stored flag can say, so the builder must hand it over.
                handed = [a.id for a in value.args if isinstance(a, ast.Name)]
                assert handed == (["overall_score", "hard_override"] if key.value == "is_critical" else ["overall_score"]), (
                    f"routers/health.py line {value.lineno} asks {key.value} with {handed}")
    assert calls == {"is_critical": 2, "is_at_risk": 2}, "the mock and the database builders both ask the module for both flags"


def test_a_cached_dashboard_from_before_the_verdict_was_the_engines_is_not_served():
    assert ed.DASHBOARD_VERSION >= 5, "version 4 payloads counted critical and at risk at 40 and 70"


# ── attach ───────────────────────────────────────────────────────────────────

def test_a_stored_verdict_wins_over_the_scores_own():
    got = attach([{"id": "a"}], [{"client_id": "a", "overall_score": 80, "is_critical": True, "is_at_risk": False}])[0]
    assert (got["health_score"], got["health_critical"], got["health_at_risk"]) == (80, True, False)


def test_a_stored_verdict_that_is_not_a_boolean_is_not_a_verdict_and_the_score_stands_in():
    got = attach([{"id": "a"}, {"id": "b"}], [
        {"client_id": "a", "overall_score": 34, "is_critical": None, "is_at_risk": "yes"},
        {"client_id": "b", "overall_score": 45}])
    assert [(c["health_critical"], c["health_at_risk"]) for c in got] == [(True, False), (False, True)]


def test_a_stored_verdict_that_is_a_number_is_not_a_boolean_either():
    """`True == 1` in Python, so an integer column read back as 0 or 1 must not pass as a verdict."""
    got = attach([{"id": "a"}], [{"client_id": "a", "overall_score": 34, "is_critical": 0, "is_at_risk": 1}])[0]
    assert (got["health_critical"], got["health_at_risk"]) == (True, False), "the score's own verdict stands in for both"


def test_a_client_without_a_score_has_no_verdict_either():
    got = attach([{"id": "a", "health_critical": True, "health_at_risk": True}], [])[0]
    assert (got["health_score"], got["health_critical"], got["health_at_risk"]) == (None, None, None), "the caller's own keys do not survive"


# ── the dashboard ────────────────────────────────────────────────────────────

def _client(cid, score, **extra):
    return {"id": cid, "client_name": cid.upper(), "status": "active", "health_score": score, **extra}


def _risk(clients):
    rows = StoredScoresFrom(clients).find_all(FIRM)
    return ed.client_risk(attach(clients, rows)), ed.churn_signals(attach(clients, rows))


def test_the_dashboard_counts_a_client_scoring_38_at_risk_because_the_engine_does():
    risk, _ = _risk([_client("a", 38), _client("b", 67), _client("c", 39), _client("d", 69)])
    assert risk == {"critical": 0, "at_risk": 2, "needs_attention": 0, "healthy": 2, "unscored": 0}, "38 and 39 are at risk (the old split at 40 called them critical), 67 and 69 are not (the old split at 70 called them at risk)"


def test_the_dashboard_counts_by_the_stored_verdict_whatever_the_score_would_say_and_says_so():
    clients = [_client("a", 80, health_is_critical=True, health_is_at_risk=False), _client("b", 20), _client("c", 40)]
    risk, signals = _risk(clients)
    assert risk == {"critical": 2, "at_risk": 1, "needs_attention": 0, "healthy": 0, "unscored": 0}
    assert [(s["client_name"], s["signal"], s["risk"]) for s in signals] == [
        ("B", "Health score 20 — Critical", "high"), ("A", "Health score 80 — Critical", "high"), ("C", "Health score 40 — At Risk", "medium")]


def test_a_stored_verdict_that_says_neither_beats_a_threshold_the_score_alone_would_cross():
    """The stored verdict outranks the score for the two FLAGS: no critical or at-risk count, no churn signal. It does not make a 40 a
    healthy client: the green count is the engine's Healthy and Good bands only (POST-A-286), so the client is counted needing a look."""
    risk, signals = _risk([_client("a", 40, health_is_critical=False, health_is_at_risk=False)])
    assert (risk["critical"], risk["at_risk"], risk["needs_attention"], risk["healthy"]) == (0, 0, 1, 0) and signals == []


def test_a_recorded_status_still_counts_and_the_more_severe_of_status_and_verdict_wins():
    clients = [dict(_client("a", 90), status="critical"), dict(_client("b", 90), status="at_risk"), dict(_client("c", 20), status="at_risk")]
    risk, _ = _risk(clients)
    assert risk == {"critical": 2, "at_risk": 1, "needs_attention": 0, "healthy": 0, "unscored": 0}, "a is critical by status, b at risk by status, c critical by verdict"


def test_the_churn_signals_are_worst_first_and_carry_no_scratch_keys():
    _, signals = _risk([_client("a", 44), _client("b", 12), _client("c", 30), _client("d", 49)])
    assert [s["client_name"] for s in signals] == ["B", "C", "A", "D"]
    assert all(set(s) == {"client_name", "signal", "risk"} for s in signals)


def test_a_client_flagged_but_without_a_score_is_not_a_signal_and_a_flag_must_be_true_itself():
    """Hand-built rows only (`attach` gives an unscored client no verdict), but the contract is: a signal quotes a score, and a flag is
    the boolean True and not anything truthy."""
    assert ed.churn_signals([{"client_name": "X", "health_critical": True}]) == []
    scored = {"client_name": "Y", "health_score": 20, "health_critical": "yes", "health_at_risk": 1}
    assert ed.churn_signals([scored]) == []
    assert ed.client_risk([scored]) == {"critical": 0, "at_risk": 0, "needs_attention": 1, "healthy": 0, "unscored": 0}, (
        "no verdict, but a score of 20 is not healthy")
    assert mod._flagged({"health_critical": "yes"}, "health_critical") is False
    assert mod._flagged({"health_critical": True}, "health_at_risk", "health_critical") is True


def test_a_client_scoring_zero_is_a_signal_and_a_client_flagged_both_ways_is_critical():
    """Zero is a score and the worst one; a client both flags name is the more severe."""
    clients = [_client("z", 0), dict(_client("b", 30), health_is_at_risk=True, health_is_critical=True)]
    _, signals = _risk(clients)
    assert [(s["client_name"], s["signal"], s["risk"]) for s in signals] == [
        ("Z", "Health score 0 — Critical", "high"), ("B", "Health score 30 — Critical", "high")]
    assert ed.client_risk(attach(clients, StoredScoresFrom(clients).find_all(FIRM)))["critical"] == 2


def test_a_signal_for_a_client_with_no_name_says_unknown_and_a_non_numeric_score_is_no_score():
    assert ed.churn_signals([{"health_score": 20, "health_critical": True}])[0]["client_name"] == "Unknown"
    assert ed.client_risk([{"health_score": "high", "health_critical": None, "health_at_risk": None}]) == {
        "critical": 0, "at_risk": 0, "needs_attention": 0, "healthy": 0, "unscored": 1}


def test_the_churn_signals_stop_at_the_limit():
    _, signals = _risk([_client(f"c{i}", 10 + i) for i in range(9)])
    assert len(signals) == 5 and signals[0]["signal"] == "Health score 10 — Critical"


# ── the dashboard agrees with the Health page ────────────────────────────────

def test_the_dashboard_counts_the_same_clients_the_health_page_lists(monkeypatch):
    """One set of stored rows, read by the Health page's own roll-up (`/api/health/dashboard`: critical = `is_critical`, at risk = `is_at_risk`
    and not critical) and by the executive dashboard. They disagreed for every score from 35 to 39 and from 50 to 69."""
    import routers.health as hl

    scores = [(34, True, False), (35, False, True), (38, False, True), (49, False, True), (50, False, False), (55, False, False),
              (67, False, False), (90, False, False), (80, True, False)]
    rows = {f"c{i}": {"client_id": f"c{i}", "firm_id": FIRM, "overall_score": s, "is_critical": crit, "is_at_risk": risk,
                      "grade": scoring.grade(s)} for i, (s, crit, risk) in enumerate(scores)}
    monkeypatch.setattr(hl, "_db", lambda: None)
    monkeypatch.setattr(hl, "_MOCK_SCORES", rows)
    monkeypatch.setattr(hl, "_MOCK_ALERTS", [])
    monkeypatch.setattr(hl, "filter_by_client", lambda user, items: items)
    page = hl.health_dashboard(current_user={"id": "u", "firm_id": FIRM, "role": "Partner"})["data"]

    clients = [{"id": cid, "client_name": cid, "status": "active"} for cid in rows]
    attached = attach(clients, list(rows.values()))
    risk = ed.client_risk(attached)
    assert (risk["critical"], risk["at_risk"]) == (len(page["critical_clients"]), len(page["at_risk_clients"])) == (2, 3)
    assert (risk["needs_attention"], risk["healthy"]) == (2, 2), "50 and 55 need attention; 67 and 90 are healthy or good"
    assert sum(risk[k] for k in ("critical", "at_risk", "needs_attention", "healthy", "unscored")) == len(rows)


# ── the assistant ────────────────────────────────────────────────────────────

def _assistant(monkeypatch, clients):
    class _Clients:
        def find_all(self, **kw):
            return list(clients)

        def find_by_id(self, cid, **kw):
            return next((c for c in clients if c["id"] == cid), None)

    class _Compliance:
        def find_all(self, **kw):
            return []

    monkeypatch.setattr(mod, "_get_client_repo", lambda: _Clients())
    monkeypatch.setattr(mod, "_get_health_repo", lambda: StoredScoresFrom(clients))
    monkeypatch.setattr(mod, "_get_compliance_records_repo", lambda: _Compliance())
    return mod.ai_copilot_service


def test_a_clients_recorded_critical_status_still_counts_critical_in_the_assistant(monkeypatch):
    clients = [{"id": "a", "status": "critical"}, {"id": "b", "status": "critical"}, {"id": "c", "status": "active"}]
    context = _assistant(monkeypatch, clients)._build_context(FIRM, "global", None, None)
    assert "CRITICAL CLIENTS: 2" in context and "AT-RISK CLIENTS: 2" in context


def test_the_assistant_counts_by_the_stored_verdict_and_a_38_is_at_risk_not_critical(monkeypatch):
    clients = [_client("a", 80, health_is_critical=True), _client("b", 38), _client("c", 67), _client("d", 20)]
    context = _assistant(monkeypatch, clients)._build_context(FIRM, "global", None, None)
    assert "CRITICAL CLIENTS: 2" in context, "the stored critical verdict and the 20"
    assert "AT-RISK CLIENTS: 3" in context, "those two, and the 38 the Health page lists as at risk; the 67 is neither"


# ── the memory profile ───────────────────────────────────────────────────────

class _Memory:
    def __init__(self):
        self.saved: list = []

    def upsert_firm_profile(self, firm_id, data):
        self.saved.append(data)
        return data


def _profile(monkeypatch, clients):
    class _Clients:
        def find_all(self, **kw):
            return list(clients)

    store = _Memory()
    monkeypatch.setattr(memory, "_get_client_repo", lambda: _Clients())
    monkeypatch.setattr(memory, "_get_health_repo", lambda: StoredScoresFrom(clients))
    monkeypatch.setattr(memory, "_get_memory_repo", lambda: store)
    memory.memory_pipeline.compute_firm_profile(FIRM)
    return store.saved[-1]


def test_the_memory_profile_states_no_risk_category_or_trend_whatever_the_engines_verdicts_are(monkeypatch):
    """The profile used to write a literal pair of risk categories whenever the engine called any client critical (and a "declining"
    trend when more than a fifth were), so this test asserted that 36 and 38 (at risk) did not trigger them and 34 or a stored critical
    verdict did. Nothing computes either figure now (POST-A-284), so no verdict may produce a value for them."""
    for clients in ([_client("a", 36), _client("b", 38), _client("c", 90)], [_client("a", 34), _client("b", 90)],
                    [_client("a", 90, health_is_critical=True), _client("b", 90)]):
        profile = _profile(monkeypatch, clients)
        assert profile["common_risk_categories"] is None and profile["portfolio_health_trend"] is None
    assert _profile(monkeypatch, [_client("a", 36), _client("b", 38), _client("c", 90)])["portfolio_compliance_score"] == 54.7
