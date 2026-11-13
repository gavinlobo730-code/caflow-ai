"""A manual run's day is a real day, judged after the caller's access and by one rule (POST-A-380, the manual-run `as_of` and the journal's `occurrence`).

WHAT WAS WRONG
    The recurring invoices' two manual-run doors had been fixed with a private copy of a few lines. Four more doors that take the day a run is for in the query string handed it to the date
    parser, so `?as_of=soon` was a 500 with no sentence for a script: the recurring purchase bills' two (`POST /api/recurring-purchase-bills/run` and `/{id}/run`) and the recurring journals'
    two (`POST /api/recurring-journals/run` and `/{id}/generate`, whose day is called `occurrence`). The fee billing's two (`POST /api/billing/preview-run` and `/run`) never reached a parser:
    the service compared the raw text with each schedule's stored day, and any text that sorts after a digit ("soon", "30/09/2026") made EVERY schedule due, so `/run` drafted invoices for
    schedules not due for months, with a 200. A late-interest preview (`GET /api/late-interest/preview`) carried a shape-only `pattern`, which admits `2026-02-30`, and answered 500.
    The screens send a real day or nothing.

WHAT IS HELD
    `core/query_day.query_day` is the one rule: nothing or a blank is no day (the run is for today; for the journal's one occurrence, the template's own next day), a real day is kept in its
    canonical form, anything else is a 422 naming the query parameter. A text with a time after the day, which the recurrence reader and the billing comparison used to take by its first ten
    characters, is refused too, as the recurring invoices' pair already did. A door that acts on a template asks the caller's access to it FIRST (a template that is not theirs is a 404 before
    any day is judged), a door that takes a `client_id` asks access to that client first, and the day reaches the service as the canonical text or None, never as what was typed. The invoices' pair
    now calls the same rule, and its existing test (`test_the_last_forms_the_date_drive_reached...`) still holds it.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import routers.billing as billing
import routers.late_interest as late_interest
import routers.recurring_invoices as r_invoices
import routers.recurring_journals as r_journals
import routers.recurring_purchase_bills as r_bills
from core.auth import get_current_user
from core.query_day import query_day

PARTNER = {"id": "u1", "firm_id": "F1", "role": "Partner", "email": "p@f1.test", "auth_user_id": "auth-partner"}
BAD = ["30/09/2026", "2026-02-30", "soon", "2026-07-01T10:00:00", "２０２６-07-01"]


@pytest.fixture
def client():
    app = FastAPI()
    for r in (r_invoices.router, r_bills.router, r_journals.router, billing.router, late_interest.router):
        app.include_router(r)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def seen(monkeypatch):
    """Every service the six doors call is replaced by a recorder, and the template scope checks let the call through, so what reaches the service is what is asserted."""
    calls: dict[str, list] = {}

    def recorder(name, result=None):
        def f(*a, **k):
            calls.setdefault(name, []).append((a, k))
            return result if result is not None else {"generated": [], "skipped": [], "failed": []}
        return f

    monkeypatch.setattr(r_bills.recurring, "run_for_template", recorder("bills_one"))
    monkeypatch.setattr(r_bills.recurring, "generate_due_recurring_bills", recorder("bills_all"))
    monkeypatch.setattr(r_bills, "_assert_template_scope", lambda *a, **k: None)
    monkeypatch.setattr(r_journals.svc, "run_due", recorder("journals_all"))
    monkeypatch.setattr(r_journals.svc, "generate_for_occurrence", recorder("journals_one", {"created": False}))
    monkeypatch.setattr(r_journals, "_scoped", lambda *a, **k: {"id": "t1", "next_run_date": "2026-07-01"})
    monkeypatch.setattr(r_journals.svc, "due_occurrences", lambda t: [])
    monkeypatch.setattr(billing.billing_service, "preview_due", recorder("billing_preview", {"due": []}))
    monkeypatch.setattr(billing.billing_service, "run_due", recorder("billing_run", {"generated": []}))
    return calls


# (method, path, the query parameter that carries the day)
DOORS = [
    ("/api/recurring-purchase-bills/run", "as_of"),
    ("/api/recurring-purchase-bills/t1/run", "as_of"),
    ("/api/recurring-journals/run", "as_of"),
    ("/api/recurring-journals/t1/generate", "occurrence"),
    ("/api/billing/preview-run", "as_of"),
    ("/api/billing/run", "as_of"),
]

IDS = [p for p, _ in DOORS]


@pytest.mark.parametrize("bad", BAD)
@pytest.mark.parametrize("path,name", DOORS, ids=IDS)
def test_a_day_that_is_not_one_is_a_422_naming_the_parameter_and_nothing_runs(client, seen, path, name, bad):
    r = client.post(path, params={name: bad})
    assert r.status_code == 422, (path, bad, r.text)
    assert f"{name} must be a date written YYYY-MM-DD." in r.text
    assert seen == {}, "a service ran for a day that is not one"


@pytest.mark.parametrize("path,name,key", [
    ("/api/recurring-purchase-bills/run", "as_of", "bills_all"),
    ("/api/recurring-purchase-bills/t1/run", "as_of", "bills_one"),
    ("/api/recurring-journals/run", "as_of", "journals_all"),
    ("/api/billing/preview-run", "as_of", "billing_preview"),
    ("/api/billing/run", "as_of", "billing_run"),
])
def test_a_blank_or_absent_day_reaches_the_service_as_none_and_a_real_one_as_the_canonical_day(client, seen, path, name, key):
    assert client.post(path).status_code == 200
    assert client.post(path, params={name: "  "}).status_code == 200
    assert client.post(path, params={name: " 2026-07-15 "}).status_code == 200
    days = [(c[1].get("as_of") if c[1] else (c[0][-1] if c[0] else None)) for c in seen[key]]
    if key.startswith("billing"):                     # the billing services take the day positionally
        days = [c[0][-1] for c in seen[key]]
    assert days == [None, None, "2026-07-15"], (key, days)


def test_the_journals_occurrence_reaches_the_service_as_the_canonical_day(client, seen):
    assert client.post("/api/recurring-journals/t1/generate", params={"occurrence": " 2026-07-15 "}).status_code == 200
    assert seen["journals_one"][0][0][2] == "2026-07-15"
    assert client.post("/api/recurring-journals/t1/generate").status_code == 200       # none given: the template's own next day, as before
    assert seen["journals_one"][1][0][2] == "2026-07-01"


@pytest.mark.parametrize("path", ["/api/recurring-purchase-bills/no-such-template/run", "/api/recurring-journals/no-such-template/generate"])
def test_the_templates_access_is_asked_before_the_day_is_judged(client, path):
    """A template that is not there for this caller is refused as it always was, whatever day was asked for (the order `tests/test_recurring_client_scope.py` holds for every template route)."""
    name = "occurrence" if path.endswith("generate") else "as_of"
    r = client.post(path, params={name: "soon"})
    assert r.status_code in (403, 404), f"the day was judged before the caller's access ({r.status_code}: {r.text})"


def test_the_one_rule_judges_nothing_a_blank_a_real_day_and_text():
    assert query_day(None, "as_of") is None and query_day("", "as_of") is None and query_day("   ", "as_of") is None
    assert query_day(" 2026-07-15 ", "as_of") == "2026-07-15" and query_day("20260715", "as_of") == "2026-07-15"
    for bad in BAD:
        with pytest.raises(HTTPException) as caught:
            query_day(bad, "occurrence")
        assert caught.value.status_code == 422 and "occurrence must be a date written YYYY-MM-DD." in caught.value.detail


def test_the_invoices_pair_uses_the_same_rule():
    assert r_invoices._as_of(" 2026-07-15 ") == "2026-07-15"
    assert r_invoices._as_of("") is None and r_invoices._as_of(None) is None
    for bad in BAD:
        with pytest.raises(HTTPException) as caught:
            r_invoices._as_of(bad)
        assert caught.value.status_code == 422 and "as_of must be a date written YYYY-MM-DD." in caught.value.detail


# ── the late-interest preview: a shape-only pattern admits 2026-02-30 (POST-A-380, an independent read) ──────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def preview_seen(monkeypatch):
    calls = []
    monkeypatch.setattr(late_interest, "_db", lambda: object())
    monkeypatch.setattr(late_interest, "assert_client_access", lambda *a, **k: None)
    monkeypatch.setattr(late_interest.service, "preview", lambda *a, **k: calls.append(a) or {"parties": []})
    return calls


@pytest.mark.parametrize("bad", ["2026-02-30", "2026-13-45", "9999-99-99"])
def test_the_late_interest_previews_day_is_a_real_day_not_just_four_two_two_digits(client, preview_seen, bad):
    r = client.get("/api/late-interest/preview", params={"client_id": "c1", "as_of": bad})
    assert r.status_code == 422 and "as_of must be a date written YYYY-MM-DD." in r.text, (bad, r.status_code, r.text)
    assert preview_seen == []


def test_the_late_interest_preview_still_takes_no_day_or_a_real_one(client, preview_seen):
    assert client.get("/api/late-interest/preview", params={"client_id": "c1"}).status_code == 200
    assert client.get("/api/late-interest/preview", params={"client_id": "c1", "as_of": "2026-07-15"}).status_code == 200
    assert [str(a[3]) for a in preview_seen] == ["None", "2026-07-15"]


def test_the_late_interest_previews_client_access_is_asked_before_the_day(client, monkeypatch, preview_seen):
    def refuse(user, client_id, *a, **k):
        raise HTTPException(status_code=404, detail="Client not found.")
    monkeypatch.setattr(late_interest, "assert_client_access", refuse)
    # the route's own four-two-two pattern is checked by FastAPI before any handler runs, as it always was; the calendar (2026-02-30) is judged by query_day, after the access
    r = client.get("/api/late-interest/preview", params={"client_id": "not-mine", "as_of": "2026-02-30"})
    assert r.status_code == 404, f"the day was judged before the caller's access ({r.status_code}: {r.text})"


# ── the bulk run doors that name a client ask access to it before they judge the day ────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("module,path", [(r_bills, "/api/recurring-purchase-bills/run"), (r_journals, "/api/recurring-journals/run")])
def test_a_bulk_run_for_a_client_the_caller_cannot_reach_is_the_access_refusal_whatever_the_day(client, seen, monkeypatch, module, path):
    def refuse(user, client_id, *a, **k):
        raise HTTPException(status_code=404, detail="Client not found.")
    monkeypatch.setattr(module, "assert_client_access", refuse)
    r = client.post(path, params={"client_id": "not-mine", "as_of": "soon"})
    assert r.status_code == 404, f"the day was judged before the caller's access ({r.status_code}: {r.text})"
    assert seen == {}


@pytest.mark.parametrize("module,path", [(r_bills, "/api/recurring-purchase-bills/run"), (r_journals, "/api/recurring-journals/run")])
def test_a_bulk_run_for_a_client_the_caller_can_reach_then_judges_the_day(client, seen, monkeypatch, module, path):
    monkeypatch.setattr(module, "assert_client_access", lambda *a, **k: None)
    r = client.post(path, params={"client_id": "mine", "as_of": "soon"})
    assert r.status_code == 422 and "as_of must be a date written YYYY-MM-DD." in r.text
    assert seen == {}

