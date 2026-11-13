"""The three practice analytics endpoints can be asked for a custom range of days (POST-A-427, the server half).

WHAT WAS LEFT
    The running financial year and the two before it are offered (`period=fy`), but a window that is neither a running week, month or quarter nor a whole
    year (a half year, a quarter of last year, the month before last) could not be asked for at all, and an unknown word is a 422. A CA who asks what a part of a
    year earned had to read a whole year and subtract.

WHAT IS HELD
    `period=custom` with `date_from` and `date_to`:
      * both are required, and neither is guessed (one alone would be a window with an end nobody named);
      * each is a real day written YYYY-MM-DD, judged in the handler by the query-string rule (`core.query_day`), so a text that is not a day is a 422 whose sentence NAMES the
        parameter (`date_to must be a date written YYYY-MM-DD.`), a blank one is no day, and a padded or compact one is read as the day;
      * the later is not after India's today (nothing has happened after today) and the earlier is not after the later; a one-day window is allowed;
      * a day asked for with any other window is refused in words rather than ignored, as a financial year with a window other than `fy` is;
      * the label is the two days (the year in four digits), and the window the three endpoints read is exactly the two days, for the invoices AND for the hours each endpoint reads.
    The other windows are unchanged (the neighbouring tests hold them).

NOT DONE HERE
    The screen has no way to ask yet: two date boxes, each held by the date drive's matrix (bounds judged against India's today, one reading rule, a drive row each), are the
    other half of the ledger line.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import routers.analytics as an
from core import authz
from core.auth import get_current_user

TODAY = date(2026, 11, 13)
PARTNER = {"id": "u1", "firm_id": "F1", "role": "Partner", "email": "p@f1.test", "auth_user_id": "auth-partner"}


@pytest.fixture(autouse=True)
def _india_today_is_fixed(monkeypatch):
    monkeypatch.setattr(an, "ist_today", lambda: TODAY)


# ── the resolver, alone ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_custom_window_is_exactly_the_two_days_asked_for_and_the_label_names_them():
    assert an._period_range("custom", None, "2026-04-01", "2026-09-30") == ("2026-04-01", "2026-09-30", "01 Apr 2026 to 30 Sep 2026")
    assert an._period_range("custom", None, "2025-04-01", "2025-06-30")[2] == "01 Apr 2025 to 30 Jun 2025", "a window in an earlier year is allowed"


def test_a_year_before_1000_is_headed_in_four_digits_and_a_window_may_span_years():
    assert an._period_range("custom", None, "0026-04-01", "2026-09-30") == ("0026-04-01", "2026-09-30", "01 Apr 0026 to 30 Sep 2026")
    assert an._period_range("custom", None, "2020-04-01", "2026-11-13") == ("2020-04-01", "2026-11-13", "01 Apr 2020 to 13 Nov 2026")


def test_the_unknown_word_is_a_422_that_lists_custom():
    with pytest.raises(HTTPException) as caught:
        an._period_range("decade")
    assert caught.value.status_code == 422 and "use week, month, quarter, fy or custom." in str(caught.value.detail)


def test_the_window_may_end_today_and_may_be_one_day():
    assert an._period_range("custom", None, "2026-11-01", "2026-11-13")[:2] == ("2026-11-01", "2026-11-13")
    assert an._period_range("custom", None, "2026-11-13", "2026-11-13") == ("2026-11-13", "2026-11-13", "13 Nov 2026 to 13 Nov 2026")
    assert an._period_range("custom", None, "2026-11-10", "2026-11-10")[:2] == ("2026-11-10", "2026-11-10")


@pytest.mark.parametrize("frm,to,words", [
    ("2026-04-01", "2026-11-14", "date_to is 2026-11-14, after today in India (2026-11-13): nothing has happened after today."),
    ("2026-11-14", "2026-11-14", "after today in India"),
    ("2026-09-30", "2026-04-01", "date_from (2026-09-30) is after date_to (2026-04-01)."),
])
def test_a_window_that_runs_past_today_or_backwards_is_a_422_in_words(frm, to, words):
    with pytest.raises(HTTPException) as caught:
        an._period_range("custom", None, frm, to)
    assert caught.value.status_code == 422 and words in str(caught.value.detail)


@pytest.mark.parametrize("frm,to", [("2026-04-01", None), (None, "2026-09-30"), (None, None), ("", "2026-09-30"), ("2026-04-01", "")])
def test_a_custom_window_needs_both_days(frm, to):
    with pytest.raises(HTTPException) as caught:
        an._period_range("custom", None, frm, to)
    assert caught.value.status_code == 422 and "needs both days: date_from and date_to." in str(caught.value.detail)


@pytest.mark.parametrize("period", ["week", "month", "quarter", "fy"])
def test_a_day_asked_for_with_any_other_window_is_refused_and_not_ignored(period):
    for frm, to in (("2026-04-01", None), (None, "2026-09-30"), ("2026-04-01", "2026-09-30")):
        with pytest.raises(HTTPException) as caught:
            an._period_range(period, None, frm, to)
        assert caught.value.status_code == 422 and "only with the window 'custom'" in str(caught.value.detail), (period, frm, to)


def test_a_financial_year_with_a_custom_window_is_still_refused_in_the_existing_words():
    with pytest.raises(HTTPException) as caught:
        an._period_range("custom", "2025-26", "2026-04-01", "2026-09-30")
    assert caught.value.status_code == 422 and "only with the window 'fy'" in str(caught.value.detail)


def test_the_other_windows_are_unchanged():
    assert an._period_range("month") == ("2026-11-01", "2026-11-13", "November 2026")
    assert an._period_range("fy", "2025-26") == ("2025-04-01", "2026-03-31", "FY 2025-26")
    assert an._period_range("quarter")[1] == "2026-11-13" and an._period_range("week")[1] == "2026-11-13"


# ── the three endpoints, over HTTP ────────────────────────────────────────────────────────────────────────────────────────────────────────

ENDPOINTS = ["/api/analytics/profitability", "/api/analytics/concentration", "/api/analytics/revenue-vs-effort"]


@pytest.fixture
def served(monkeypatch):
    reads: list[tuple] = []
    monkeypatch.setattr(an.invoice_repo, "fee_revenue_rows", lambda firm, a, b: reads.append(("invoices", firm, a, b)) or [])
    monkeypatch.setattr(an.time_tracking_analytics_repo, "get_cost_entries", lambda firm, a, b: reads.append(("entries", firm, a, b)) or [])
    # /revenue-vs-effort reads its hours through this one instead, so it is observed too: without it a wrong window on that read goes unseen.
    monkeypatch.setattr(an.time_tracking_analytics_repo, "get_worth_entries", lambda firm, a, b: reads.append(("worth", firm, a, b)) or [])
    monkeypatch.setattr(an.billing_service, "cost_rates_by_user", lambda firm: {})
    monkeypatch.setattr(an.client_repo, "names_by_id", lambda firm, include_archived=False: {})
    monkeypatch.setattr(an.user_repo, "find_all", lambda firm_id=None, **kw: [])
    monkeypatch.setattr(an.engagement_repo, "services_by_id", lambda firm: {})
    monkeypatch.setattr(authz, "effective_client_ids", lambda user: None)
    app = FastAPI()
    app.include_router(an.router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    return TestClient(app, raise_server_exceptions=False), reads


@pytest.mark.parametrize("path", ENDPOINTS)
def test_each_endpoint_reads_exactly_the_two_days_and_says_so(served, path):
    client, reads = served
    r = client.get(path, params={"period": "custom", "date_from": " 2026-04-01 ", "date_to": "20260930"})
    assert r.status_code == 200, r.text
    assert ("invoices", "F1", "2026-04-01", "2026-09-30") in reads, reads
    assert {kind for kind, *_ in reads} >= {"invoices"} and len(reads) >= 2, f"the hours were not read: {reads}"
    assert all(read[2:] == ("2026-04-01", "2026-09-30") for read in reads), f"a read used another window than the two days: {reads}"
    assert "01 Apr 2026 to 30 Sep 2026" in r.text, "the answer does not name the window it was read for"


@pytest.mark.parametrize("path", ENDPOINTS)
@pytest.mark.parametrize("params,words", [
    ({"period": "custom", "date_from": "2026-04-01"}, "needs both days"),
    ({"period": "custom", "date_from": "2026-04-01", "date_to": "2026-11-14"}, "after today in India"),
    ({"period": "custom", "date_from": "2026-09-30", "date_to": "2026-04-01"}, "is after date_to"),
    ({"period": "month", "date_from": "2026-04-01", "date_to": "2026-09-30"}, "only with the window 'custom'"),
    ({"period": "month", "date_from": "soon"}, "date_from must be a date written YYYY-MM-DD."),
    ({"period": "custom", "financial_year": "2025-26", "date_from": "2026-04-01", "date_to": "2026-09-30"}, "only with the window 'fy'"),
])
def test_a_refused_window_is_a_422_in_words_and_reads_nothing(served, path, params, words):
    client, reads = served
    r = client.get(path, params=params)
    assert r.status_code == 422 and words in r.text, (path, params, r.status_code, r.text)
    assert reads == [], "a refused window read the books"


@pytest.mark.parametrize("path", ENDPOINTS)
@pytest.mark.parametrize("which", ["date_from", "date_to"])
@pytest.mark.parametrize("bad", ["soon", "30/09/2026", "2026-02-30", "2026-09-30T10:00:00"])
def test_a_day_that_is_not_a_day_is_refused_in_a_sentence_that_names_the_parameter(served, path, which, bad):
    client, reads = served
    params = {"period": "custom", "date_from": "2026-04-01", "date_to": "2026-09-30", which: bad}
    r = client.get(path, params=params)
    assert r.status_code == 422 and reads == [], (path, which, bad, r.status_code, r.text[:200])
    assert f"{which} must be a date written YYYY-MM-DD." in r.text, "the refusal does not say which day is wrong"


@pytest.mark.parametrize("path", ENDPOINTS)
def test_a_blank_day_is_no_day_and_a_blank_one_with_another_window_changes_nothing(served, path):
    client, reads = served
    assert client.get(path, params={"period": "month", "date_from": "", "date_to": "  "}).status_code == 200
    assert client.get(path, params={"period": "custom", "date_from": "", "date_to": "2026-09-30"}).status_code == 422
    assert all(read[2:] == ("2026-11-01", "2026-11-13") for read in reads), reads


@pytest.mark.parametrize("path", ENDPOINTS)
def test_the_unknown_word_is_still_a_422_and_custom_is_a_word(served, path):
    client, _ = served
    assert client.get(path, params={"period": "decade"}).status_code == 422
    assert client.get(path, params={"period": "custom", "date_from": "2026-11-01", "date_to": "2026-11-13"}).status_code == 200
