"""`/api/analytics/revenue-vs-effort` returns every client, not the last one.

THE DEFECT. `revenue_vs_effort` takes a `client_id` filter, and two loops in
its body bound their row's client to that same name:

    for eng_id, revenue_data in revenue_by_engagement.items():
        client_id = engagement.get("client_id")          # <- rebinds
    ...
    for client_id, client_data in by_client_dict.items():  # <- rebinds again

By the time the filter ran, `client_id` held the LAST key of `by_client_dict`
— truthy whenever any client had revenue — so

    if client_id:
        by_client_list = [c for c in by_client_list if c["client_id"] == client_id]

fired for EVERY caller and kept exactly one row, chosen by dict iteration
order. The realization report has never once shown the firm.

⚠️ THE COMMENT IN THE CODE SAID THE OPPOSITE and is why this survived: it read
"the `client_id` PARAMETER on this endpoint is dead ... and never filters
anything". A reader checking that claim would look at the filter's own line,
see the parameter named there, conclude it was about scope rather than
correctness, and move on. Dead would have been harmless; what it actually did
was drop most of the answer.

The LOOPS are renamed rather than the parameter, so `client_id` means the
caller's value everywhere in the function and the filter works as its name
says. Both facts are asserted below, because fixing only the first would leave
a parameter that silently ignores you.
"""
import pytest

import routers.analytics as an

FIRM = "firm-1"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Partner"}

A, B, C = "client-a", "client-b", "client-c"
ENG = {"eng-a": A, "eng-b": B, "eng-c": C}


@pytest.fixture
def three_clients(monkeypatch):
    import repositories.client_repository as cr
    import repositories.engagement_repository as er
    import repositories.invoice_repository as ir
    import core.authz as authz

    monkeypatch.setattr(authz, "effective_client_ids", lambda user: None)
    monkeypatch.setattr(an, "_get_db", lambda: None)
    monkeypatch.setattr(
        cr.client_repo, "find_all",
        lambda **kw: [{"id": c, "client_name": c.upper()} for c in (A, B, C)],
    )
    monkeypatch.setattr(
        er.engagement_repo, "find_all",
        lambda **kw: [{"id": e, "client_id": c, "service_type": "Audit"}
                      for e, c in ENG.items()],
    )
    monkeypatch.setattr(
        ir.invoice_repo, "get_revenue_by_period",
        lambda **kw: {e: {"revenue_paise": 100_00, "client_id": c}
                      for e, c in ENG.items()},
    )
    monkeypatch.setattr(
        an.time_tracking_analytics_repo, "get_effort_by_engagement",
        lambda **kw: {e: {"billable_minutes": 600, "total_minutes": 600,
                          "avg_hourly_rate_paise": 1000_00}
                      for e in ENG},
    )


def test_no_filter_means_every_client(three_clients):
    """The headline. Three clients in, three clients out — before the fix this
    came back with ONE, whichever `by_client_dict` happened to yield last."""
    resp = an.revenue_vs_effort(period="month", current_user=USER)
    assert {c["client_id"] for c in resp["data"]["by_client"]} == {A, B, C}
    assert len(resp["data"]["by_engagement"]) == 3


def test_the_filter_the_parameter_promises(three_clients):
    """And the parameter is not merely harmless now — it does what it says.
    Renaming the loops alone would have left it silently ignored, which is the
    defect the old comment mistakenly described."""
    resp = an.revenue_vs_effort(period="month", client_id=B, current_user=USER)
    assert [c["client_id"] for c in resp["data"]["by_client"]] == [B]
    assert [e["engagement_id"] for e in resp["data"]["by_engagement"]] == ["eng-b"]


def test_the_engagement_filter_still_narrows_to_its_client(three_clients):
    """Untouched by the rename, and pinned so a later tidy cannot fold the two
    filters together — they answer different questions and the engagement one
    also narrows the client list, deliberately."""
    resp = an.revenue_vs_effort(period="month", engagement_id="eng-c",
                                current_user=USER)
    assert [e["engagement_id"] for e in resp["data"]["by_engagement"]] == ["eng-c"]
    assert [c["client_id"] for c in resp["data"]["by_client"]] == [C]


def test_the_firm_totals_cover_every_client(three_clients):
    """The totals were always summed BEFORE the filter, so they were right
    while the list beside them was not — the worst shape for a reader, because
    a per-client table that does not foot to its own total reads as a rounding
    problem rather than as missing rows."""
    d = an.revenue_vs_effort(period="month", current_user=USER)["data"]
    assert d["total_revenue_paise"] == 300_00
    assert sum(c["revenue_paise"] for c in d["by_client"]) == d["total_revenue_paise"]
