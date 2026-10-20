"""The AI memory's firm profile stores what is computed and NOTHING for what is not (POST-A-284).

WHAT WAS WRONG
    `firm_profiles` is a row of figures about the practice. Several were never computed by anything and were filled anyway: a
    portfolio score of 75, a billing recovery rate of 85 and "stable" for the team, revenue and portfolio trends came from the
    database's own column defaults (migration 070) and from the same literals in `memory_repository.upsert_firm_profile`; a pair of
    risk categories (`gst_delay`, `document_missing`) was written as a literal whenever any client was critical, whatever was actually
    wrong; and the portfolio "trend" was the share of critical clients over ALL clients, the unscored included, which is not a trend.
    Nothing on a screen reads the profile today (`GET /api/memory/firm/profile` is listed in the API client and called by no page),
    which is why it was low, and why it was cheap to make true before anything does.

WHAT IS HELD
    * every figure in `NOT_COMPUTED_FIRM_FIGURES` is written as nothing on every run, whatever the clients look like;
    * a profile row that already carries the old defaults is cleared by the next run, not left for ever;
    * a new row starts with nothing for them, in the in-memory repository and in the database branch alike;
    * no later line of `compute_firm_profile` assigns one of them a value again;
    * what IS computed still is: the portfolio figure is the mean of the stored scores and none when nothing is scored.
"""
from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

from domain import memory_pipeline as memory
from repositories import memory_repository as repo_mod
from tests.health_double import StoredScoresFrom

FIRM = "f1"   # the firm the stored-scores double answers for
CLIENTS = [{"id": "c1", "client_name": "One", "status": "active"}, {"id": "c2", "client_name": "Two", "status": "active"}]
NOT_COMPUTED = memory.NOT_COMPUTED_FIRM_FIGURES


class _Clients:
    def __init__(self, rows):
        self.rows = rows

    def find_all(self, **kw):
        return list(self.rows)


class _Store:
    def __init__(self):
        self.saved = []

    def upsert_firm_profile(self, firm_id, data):
        self.saved.append(data)
        return data


@pytest.fixture
def pipeline(monkeypatch):
    """The real pipeline over doubles for its reads, writing to `store`."""
    store = _Store()
    monkeypatch.setattr(memory, "_get_client_repo", lambda: _Clients(CLIENTS))
    monkeypatch.setattr(memory, "_get_memory_repo", lambda: store)

    def compute(scores):
        monkeypatch.setattr(memory, "_get_health_repo", lambda: StoredScoresFrom(scores))
        memory.memory_pipeline.compute_firm_profile(FIRM)
        return store.saved[-1]
    return compute


def test_the_list_is_exactly_the_seven_figures_nothing_computes():
    assert set(NOT_COMPUTED) == {"common_risk_categories", "portfolio_health_trend", "billing_recovery_rate", "team_utilisation_trend",
                                 "revenue_growth_trend", "avg_revenue_per_client_paise", "common_bottleneck_types"}
    assert len(NOT_COMPUTED) == len(set(NOT_COMPUTED))


@pytest.mark.parametrize("scores", [
    [],
    [{"id": "c1", "health_score": 20}, {"id": "c2", "health_score": 20}],
    [{"id": "c1", "health_score": 90}, {"id": "c2", "health_score": 95}],
    [{"id": "c1", "health_score": 30}],
])
def test_every_run_writes_nothing_for_each_figure_nothing_computes(pipeline, scores):
    profile = pipeline(scores)
    for key in NOT_COMPUTED:
        assert key in profile, f"{key} is not written, so a value stored earlier would stay"
        assert profile[key] is None, f"{key} was written as {profile[key]!r}"


def test_the_portfolio_figure_is_still_the_mean_of_the_scores_that_exist_and_none_when_there_are_none(pipeline):
    assert pipeline([{"id": "c1", "health_score": 30}, {"id": "c2", "health_score": 80}])["portfolio_compliance_score"] == 55.0
    assert pipeline([{"id": "c2", "health_score": 80}])["portfolio_compliance_score"] == 80.0
    assert pipeline([])["portfolio_compliance_score"] is None


def test_a_row_that_carries_the_old_defaults_is_cleared_by_the_next_run(monkeypatch):
    """The real in-memory repository: a profile created the old way, then computed."""
    monkeypatch.setattr(repo_mod, "MOCK_FIRM_PROFILES", [])
    monkeypatch.setattr(memory, "_get_client_repo", lambda: _Clients(CLIENTS))
    monkeypatch.setattr(memory, "_get_health_repo", lambda: StoredScoresFrom([{"id": "c1", "health_score": 30}]))
    old = {"id": "x", "firm_id": FIRM, "portfolio_compliance_score": 75, "common_risk_categories": ["gst_delay", "document_missing"],
           "portfolio_health_trend": "declining", "billing_recovery_rate": 85, "team_utilisation_trend": "stable",
           "revenue_growth_trend": "stable", "avg_revenue_per_client_paise": 0, "common_bottleneck_types": []}
    repo_mod.MOCK_FIRM_PROFILES.append(old)
    row = memory.memory_pipeline.compute_firm_profile(FIRM)
    assert row["portfolio_compliance_score"] == 30.0
    for key in NOT_COMPUTED:
        assert row[key] is None, f"{key} still holds {row[key]!r}"
    stored = repo_mod.MOCK_FIRM_PROFILES
    assert len(stored) == 1 and stored[0]["firm_id"] == FIRM, "the old row was updated and not joined by a second"
    assert stored[0]["portfolio_compliance_score"] == 30.0 and all(stored[0][key] is None for key in NOT_COMPUTED), (
        "the stored row, and not only the one returned, is cleared")


def test_a_new_row_starts_with_nothing_for_them_in_memory(monkeypatch):
    monkeypatch.setattr(repo_mod, "MOCK_FIRM_PROFILES", [])
    row = repo_mod.memory_repo.upsert_firm_profile("firm-new-b90", {})
    for key in (*NOT_COMPUTED, "portfolio_compliance_score"):
        assert row[key] is None, f"{key} starts as {row[key]!r}"


def _dict_literals_in(func) -> list[dict]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    return [{k.value: v for k, v in zip(n.keys, n.values, strict=True) if isinstance(k, ast.Constant)}
            for n in ast.walk(tree) if isinstance(n, ast.Dict)]


def test_a_new_row_in_the_database_branch_starts_with_nothing_for_them_too():
    """Both branches of `upsert_firm_profile` build a record; each must start the figures as `None`, not as a number or a list."""
    records = [d for d in _dict_literals_in(repo_mod.MemoryRepository.upsert_firm_profile) if "firm_id" in d and "is_current" in d]
    assert len(records) == 2, "the in-memory branch and the database branch each build a new record"
    for record in records:
        for key in (*NOT_COMPUTED, "portfolio_compliance_score"):
            node = record[key]
            assert isinstance(node, ast.Constant) and node.value is None, f"{key} starts as {ast.dump(node)}"


def test_no_later_line_of_the_computation_gives_one_of_them_a_value():
    tree = ast.parse(textwrap.dedent(inspect.getsource(memory.MemoryPipeline.compute_firm_profile)))
    assigned = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and t.value.id == "profile_data"
                        and isinstance(t.slice, ast.Constant)):
                    assigned.append(t.slice.value)
    assert not set(assigned) & set(NOT_COMPUTED), f"computed again: {sorted(set(assigned) & set(NOT_COMPUTED))}"
    assert "portfolio_compliance_score" in assigned, "the one figure that IS computed from the stored scores"


def test_the_two_invented_literals_are_gone_from_the_pipeline_and_the_repository():
    src = inspect.getsource(memory.MemoryPipeline.compute_firm_profile) + inspect.getsource(repo_mod.MemoryRepository.upsert_firm_profile)
    for literal in ('"gst_delay"', '"document_missing"', '"declining"', '"portfolio_compliance_score": 75', '"billing_recovery_rate": 85',
                    '"team_utilisation_trend": "stable"', '"revenue_growth_trend": "stable"'):
        assert literal not in src, f"{literal} is back"
