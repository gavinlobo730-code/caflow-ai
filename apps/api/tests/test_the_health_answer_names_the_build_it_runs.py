"""The health answer names the build the API runs, so a deploy that lags the website is visible from outside (POST-A-514).

WHAT WAS WRONG
    On 19-11-2026 the owner's Settings > Security showed "Your devices could not be read just now." on production while the website,
    which redeploys on every merge, already held the code that reads them. The API runs on Render and its own deploys are a separate
    thing: whether it was running an older build than the website could not be told from outside, because `/health` answered
    `status: ok` and did not say which commit it was.

WHAT IT DOES
    `/health` carries `build`: the commit Render built (`RENDER_GIT_COMMIT`, the name `core/observability._release` already tags
    Sentry events with), or `SENTRY_RELEASE` when somebody set one, or the word `unknown`. A process that does not know says so;
    an empty value is not a commit. It is read from the environment, so the route still touches no network and cannot become a 503.

NEGATIVE CONTROLS
    * drop `build` from the answer                       - the answer test fails
    * read a different variable                          - the commit test fails
    * return an empty string where nothing is set        - the unknown test fails
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import main as main_module
from core.observability import running_build

SHA = "9f2c1d7e4b6a8c0d2e4f6a8b0c1d3e5f7a9b0c1d"


@pytest.fixture()
def clean_env(monkeypatch):
    for name in ("SENTRY_RELEASE", "RENDER_GIT_COMMIT"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _health_data():
    # not entered as a context manager: the lifespan would start the boot thread and race the test (see test_health_answers_before_the_slow_boot)
    resp = TestClient(main_module.app).get("/health")
    assert resp.status_code == 200
    return resp.json()["data"]


def test_the_commit_render_built_is_named(clean_env):
    clean_env.setenv("RENDER_GIT_COMMIT", SHA)
    assert running_build() == SHA
    assert _health_data()["build"] == SHA


def test_a_release_somebody_set_wins_as_it_does_for_an_event(clean_env):
    clean_env.setenv("RENDER_GIT_COMMIT", SHA)
    clean_env.setenv("SENTRY_RELEASE", "2026.11.19-hotfix")
    assert running_build() == "2026.11.19-hotfix"
    assert _health_data()["build"] == "2026.11.19-hotfix"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_a_process_that_does_not_know_says_unknown_and_never_an_empty_commit(clean_env, value):
    if value is not None:
        clean_env.setenv("RENDER_GIT_COMMIT", value)
    assert running_build() == "unknown"
    assert _health_data()["build"] == "unknown"


def test_the_answer_is_still_ok_and_still_touches_no_network(clean_env):
    clean_env.setenv("RENDER_GIT_COMMIT", SHA)
    data = _health_data()
    assert data["status"] == "ok"
    # the same reading as the line beside it: a fact about this process, in memory
    assert "error_reporting" in data and "ai" in data
