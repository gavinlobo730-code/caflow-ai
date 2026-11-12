"""
POST-A-428 — the client and engagement NAMES on the practice analytics screens are read in pages, so past the row cap a name is not "Unknown".

WHAT WAS WRONG
    `/profitability`, `/concentration`, `/revenue-vs-effort` and `/benchmark` took a client's name, and `/profitability` and `/revenue-vs-effort` an engagement's
    service, from `client_repo.find_all` and `engagement_repo.find_all`. Each ends in ONE request, and PostgREST answers at most its row cap, so in a firm with more
    clients or engagements than that the later ones were named "Unknown" beside real money. (Since POST-A-426 no FIGURE depends on those lists: a fee and an hour each
    carry their client, so the cost was a label and not a number.)

WHAT THIS ASSERTS
    * `client_repo.names_by_id` and `engagement_repo.services_by_id` return EVERY row of a table larger than the cap, in more than one request, naming the firm on each
      and asking for the columns they need and no others;
    * the client reader has `find_all`'s population: live, not the firm's own practice, and archived ones only when asked;
    * the four endpoints, over those real readers and a database that has the cap, name a client and an engagement that sit past the first page;
    * the callers read through the new readers and no longer through the capped `find_all` (an AST check over the router).
"""
from __future__ import annotations

import ast
import inspect

import pytest

import routers.analytics as an
from tests._capped_postgrest import DB_MAX_ROWS, CappedDB

FIRM = "firm-paged"
OTHER_FIRM = "firm-other"
N = DB_MAX_ROWS + 237
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Partner"}
LAST_CLIENT = f"c{N - 1:05d}"
LAST_ENGAGEMENT = f"e{N - 1:05d}"


def _clients():
    rows = [{"id": f"c{i:05d}", "firm_id": FIRM, "client_name": f"Client {i}", "status": "active", "deleted_at": None,
             "is_internal": False} for i in range(N)]
    rows[5]["status"] = "archived"
    rows[6]["deleted_at"] = "2026-01-01T00:00:00Z"
    rows[7]["is_internal"] = True
    rows.append({"id": "c-other", "firm_id": OTHER_FIRM, "client_name": "Another firm's", "status": "active",
                 "deleted_at": None, "is_internal": False})
    return rows


def _engagements():
    rows = [{"id": f"e{i:05d}", "firm_id": FIRM, "client_id": f"c{i:05d}", "service_type": f"Service {i}"} for i in range(N)]
    rows.append({"id": "e-other", "firm_id": OTHER_FIRM, "client_id": "c-other", "service_type": "Not ours"})
    return rows


@pytest.fixture
def db(monkeypatch):
    import repositories.client_repository as cr
    import repositories.engagement_repository as er

    capped = CappedDB({"clients": _clients(), "fee_engagements": _engagements()})
    for mod in (cr, er):
        monkeypatch.setattr(mod, "_USE_MOCK", False)
        monkeypatch.setattr(mod, "_get_db", lambda: capped)
    return capped


# ── the readers ──────────────────────────────────────────────────────────────────────────────────────────────

def test_every_client_name_of_a_table_larger_than_the_cap_comes_back_in_pages(db):
    import repositories.client_repository as cr

    names = cr.client_repo.names_by_id(FIRM, include_archived=True)

    assert len(names) == N - 2, "everyone but the deleted client and the firm's own practice"
    assert names[LAST_CLIENT] == f"Client {N - 1}", "the client past the first page is named"
    assert "c-other" not in names, "another firm's client is not read"
    assert len(db.requests["clients"]) >= 2, "more than one request was made"
    assert all(("eq", "firm_id", FIRM) in ops for ops in db.requests["clients"]), "every page names the firm"
    assert set(db.selects["clients"]) == {"id, client_name"}, "only the two columns it needs"


def test_archived_clients_are_named_only_when_asked_for(db):
    import repositories.client_repository as cr

    live = cr.client_repo.names_by_id(FIRM)
    both = cr.client_repo.names_by_id(FIRM, include_archived=True)

    assert "c00005" not in live and "c00005" in both
    assert len(live) == len(both) - 1
    assert "c00006" not in both, "a deleted client is in neither"
    assert "c00007" not in both, "the firm's own practice is in neither"
    assert set(db.selects["clients"]) == {"id, client_name"}, "both branches ask for the two columns and no others"
    assert all(("eq", "firm_id", FIRM) in ops for ops in db.requests["clients"]), "and name the firm on every page"
    assert len(live) == N - 3 and live[LAST_CLIENT] == f"Client {N - 1}", "the live branch pages as well"


def test_every_engagement_of_a_table_larger_than_the_cap_comes_back_in_pages(db):
    import repositories.engagement_repository as er

    services = er.engagement_repo.services_by_id(FIRM)

    assert len(services) == N
    assert services[LAST_ENGAGEMENT] == {"service_type": f"Service {N - 1}", "client_id": LAST_CLIENT}
    assert "e-other" not in services
    assert len(db.requests["fee_engagements"]) >= 2
    assert all(("eq", "firm_id", FIRM) in ops for ops in db.requests["fee_engagements"])
    assert set(db.selects["fee_engagements"]) == {"id, client_id, service_type"}


def test_the_mock_readers_answer_from_find_all(monkeypatch):
    import repositories.client_repository as cr
    import repositories.engagement_repository as er

    seen = {}
    monkeypatch.setattr(cr, "_USE_MOCK", True)
    monkeypatch.setattr(er, "_USE_MOCK", True)
    monkeypatch.setattr(cr.client_repo, "find_all", lambda **kw: seen.setdefault("c", kw) and [{"id": "a", "client_name": "A"}])
    monkeypatch.setattr(er.engagement_repo, "find_all", lambda **kw: [{"id": "e", "client_id": "a", "service_type": "Audit"}])

    assert cr.client_repo.names_by_id("f", include_archived=True) == {"a": "A"}
    assert seen["c"] == {"firm_id": "f", "include_archived": True}
    assert er.engagement_repo.services_by_id("f") == {"e": {"service_type": "Audit", "client_id": "a"}}


# ── the endpoints, over the real readers ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def screens(db, monkeypatch):
    import core.authz as authz

    monkeypatch.setattr(authz, "effective_client_ids", lambda user: None)
    monkeypatch.setattr(an.invoice_repo, "fee_revenue_rows", lambda *a, **k: [
        {"client_id": LAST_CLIENT, "engagement_id": LAST_ENGAGEMENT, "status": "Issued", "amount_paise": 500_000}])
    monkeypatch.setattr(an.time_tracking_analytics_repo, "get_cost_entries", lambda *a, **k: [
        {"id": "t1", "user_id": "u1", "client_id": LAST_CLIENT, "engagement_id": LAST_ENGAGEMENT, "duration_minutes": 60, "is_billable": True}])
    monkeypatch.setattr(an.time_tracking_analytics_repo, "get_worth_entries", lambda *a, **k: [
        {"id": "t1", "user_id": "u1", "client_id": LAST_CLIENT, "engagement_id": LAST_ENGAGEMENT, "duration_minutes": 60, "is_billable": True,
         "billable_rate_paise": 100_000, "hourly_rate_paise": None}])
    monkeypatch.setattr(an.billing_service, "cost_rates_by_user", lambda firm_id: {"u1": 40_000})
    monkeypatch.setattr(an.user_repo, "find_all", lambda **kw: [])
    monkeypatch.setattr(an, "_get_db", lambda: None)


def test_profitability_names_a_client_and_an_engagement_past_the_first_page(screens):
    data = an.profitability_analytics(period="month", include_by_engagement=True, current_user=USER)["data"]

    assert [c["client_name"] for c in data["by_client"]] == [f"Client {N - 1}"]
    assert [e["client_name"] for e in data["by_engagement"]] == [f"Client {N - 1}"]
    assert [e["service_type"] for e in data["by_engagement"]] == [f"Service {N - 1}"]


def test_concentration_names_a_client_past_the_first_page(screens):
    data = an.fee_concentration(period="month", current_user=USER)["data"]

    names = {c["client_name"] for c in data["shares"]}
    assert names == {f"Client {N - 1}"}


def test_revenue_vs_effort_names_a_client_and_an_engagement_past_the_first_page(screens):
    data = an.revenue_vs_effort(period="month", current_user=USER)["data"]

    assert [c["client_name"] for c in data["by_client"]] == [f"Client {N - 1}"]
    assert [e["service_type"] for e in data["by_engagement"]] == [f"Service {N - 1}"]


def test_the_benchmark_names_a_client_past_the_first_page(screens, monkeypatch):
    monkeypatch.setattr(an, "_client_period_metrics", lambda firm_id, fy: [{"client_id": LAST_CLIENT}])

    [row] = an._benchmark_rows(FIRM, "2026-27", None)

    assert row.client_name == f"Client {N - 1}"


# ── the callers ──────────────────────────────────────────────────────────────────────────────────────────────

def test_the_analytics_router_reads_names_through_the_paged_readers_and_not_through_find_all():
    """The capped `find_all` is what these screens used; the rule is that none of them reads a NAME through it."""
    tree = ast.parse(inspect.getsource(an))
    offenders = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "find_all"
                and isinstance(node.func.value, ast.Name) and node.func.value.id in ("client_repo", "engagement_repo")):
            offenders.append((node.func.value.id, node.lineno))
    assert offenders == [], f"a name is read through a capped list: {offenders}"
    src = inspect.getsource(an)
    assert src.count("client_repo.names_by_id(") == 4 and src.count("engagement_repo.services_by_id(") == 2
    assert src.count("names_by_id(firm_id, include_archived=True)") == 4, "an archived client keeps its name on every one of the four screens"


# ── an archived client, through the real reader ──────────────────────────────────────────────────────────────

ARCHIVED = "c00005"


def _bill_the_archived_client(monkeypatch):
    monkeypatch.setattr(an.invoice_repo, "fee_revenue_rows", lambda *a, **k: [
        {"client_id": ARCHIVED, "engagement_id": "e00005", "status": "Issued", "amount_paise": 500_000}])
    monkeypatch.setattr(an.time_tracking_analytics_repo, "get_cost_entries", lambda *a, **k: [])
    monkeypatch.setattr(an.time_tracking_analytics_repo, "get_worth_entries", lambda *a, **k: [])


def test_the_three_fee_screens_name_a_client_archived_during_the_period(screens, monkeypatch):
    _bill_the_archived_client(monkeypatch)

    assert [c["client_name"] for c in an.profitability_analytics(period="month", current_user=USER)["data"]["by_client"]] == ["Client 5"]
    assert [c["client_name"] for c in an.fee_concentration(period="month", current_user=USER)["data"]["shares"]] == ["Client 5"]
    assert [c["client_name"] for c in an.revenue_vs_effort(period="month", current_user=USER)["data"]["by_client"]] == ["Client 5"]


def test_the_benchmark_names_an_archived_client_that_has_a_stored_row(screens, monkeypatch):
    """The nightly sweep stores a row for every client of the firm, archived or not, so the benchmark's list of clients with no figure can name one."""
    monkeypatch.setattr(an, "_client_period_metrics", lambda firm_id, fy: [{"client_id": ARCHIVED}])

    [row] = an._benchmark_rows(FIRM, "2026-27", None)

    assert row.client_name == "Client 5"


def test_the_engagement_view_is_read_only_when_it_is_asked_for(screens, monkeypatch, db):
    _bill_the_archived_client(monkeypatch)

    an.profitability_analytics(period="month", current_user=USER)
    assert "fee_engagements" not in db.requests or db.requests["fee_engagements"] == [], "the default view reads no engagements"

    an.profitability_analytics(period="month", include_by_engagement=True, current_user=USER)
    assert len(db.requests["fee_engagements"]) >= 2
