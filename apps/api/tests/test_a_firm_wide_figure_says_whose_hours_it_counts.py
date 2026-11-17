"""A figure that counts the whole firm says so to a member who sees only some clients, and four firm-wide reads no screen
called are gone (POST-A-453).

WHAT WAS WRONG
    Team Overview (`/work`) and Team Workload (`/team/workload`) show an average utilisation built from every `time_entries`
    row in the firm, while the task counts beside them are narrowed to the caller's clients. No client is named, and a
    person's capacity is the same whoever's client the hour was for, so the hours stay every client's; but a Manager who can
    open five clients read the figure as theirs. Four reads answered for the whole firm and no screen called them: the
    memory's firm profile, the notifications' counts by type for every member, the lifecycle dashboard's lead tallies, and
    the automation executions and counts.

WHAT IS HELD
    * the workload answer carries `utilisation_counts`, one sentence that says it counts every client's hours, and both cards
      draw it under the figure;
    * the five deleted routes are not served, and the browser's API client has no wrapper that would call them.
"""
from __future__ import annotations

import pathlib

import pytest

WEB = pathlib.Path(__file__).resolve().parents[2] / "web"


def test_the_sentence_says_every_client_and_not_only_yours():
    from routers.workload import UTILISATION_COUNTS
    assert "every client of the practice" in UTILISATION_COUNTS
    assert "not only the clients you can open" in UTILISATION_COUNTS
    # The figure has two bases and the sentence names both: hours for a person who logged some, open tasks for one who logged none.
    assert "logged none" in UTILISATION_COUNTS and "open tasks against their task limit" in UTILISATION_COUNTS
    assert "on the clients you can open" in UTILISATION_COUNTS.split("logged none")[1]


@pytest.mark.parametrize("page", ["app/team/workload/page.tsx", "app/work/page.tsx"])
def test_each_card_draws_the_sentence_under_the_figure(page):
    src = (WEB / page).read_text()
    figure = src.index("{workload.avg_utilisation_pct}%")
    sentence = src.index("{workload.utilisation_counts}")
    assert 0 < sentence - figure < 300, f"{page}: the sentence is not drawn under the utilisation figure"


@pytest.mark.parametrize("path", [
    "/api/memory/firm/profile", "/api/notifications/stats", "/api/lifecycle/dashboard",
    "/api/automation/executions", "/api/automation/stats",
])
def test_a_firm_wide_read_no_screen_called_is_not_served(path):
    from main import app
    assert not any(getattr(r, "path", "") == path and "GET" in getattr(r, "methods", set()) for r in app.routes), path
    client = (WEB / "lib" / "api" / "index.ts").read_text()
    assert f'"{path}"' not in client, f"the browser's API client still names {path}"
