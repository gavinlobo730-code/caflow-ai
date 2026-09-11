"""The seven year-end schedule tabs, which have never rendered (FA-09).

FIVE THINGS WERE WRONG AND THEY STACK, which is why fixing any one alone makes
the screen worse rather than better:

  1. THE URL. The page fetched `/api/year-end/engagements/{id}/schedules/{type}`
     against a route declared `/{engagement_id}/schedules/{schedule_type}` under
     a `/year-end` prefix — five path segments against four. All seven tabs
     404'd, and have since they were written.

  2. THE SHAPE. The page reads `columns`, `rows` and `totals`; the endpoint has
     always answered `line_items` and `total_paise`. So fixing (1) alone would
     have replaced seven 404s with a crash on `rows.length`.

  3. MOCK ≠ LIVE. The mock branch answered a different shape per schedule
     (`net_gst_payable_paise`, `total_net_block_paise`, `total_paise`) while the
     live branch always answers the same one. No caller could be written
     against both.

  4. NOTHING IS MAPPED. `account_group_mappings` decides which ledgers belong
     on which schedule, and MEASURED ON PRODUCTION IT HOLDS ZERO ROWS — its
     full CRUD API (routers/year_end_mappings.py) is called by no screen. So
     every schedule is empty for every client, and an empty `line_items` with
     no explanation is the claim "this client has no fixed assets".

  5. NO OPENING BALANCE. The figure was `debit - credit` over
     `entry_date BETWEEN fy_start AND fy_end` — the year's MOVEMENT, not the
     balance. A client carrying ₹5,00,000 of receivables into the year and
     billing ₹1,00,000 in it was shown ₹1,00,000.

(4) is the one that cannot be fixed here: a mapping screen is a build. What is
fixed is that the endpoint SAYS SO instead of answering an empty list silently.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = API_ROOT.parents[1] / "apps" / "web"
PAGE = (WEB_ROOT / "app" / "clients" / "[id]" / "year-end" / "[engagementId]"
        / "schedules" / "_page.tsx")


# ── (1) the URL ──────────────────────────────────────────────────────────────

def test_the_page_fetches_the_path_the_router_declares():
    """Asserted by BUILDING the route from the router and looking for it in the
    page, rather than by spelling it out here — a third copy of the path would
    be free to drift from both, which is the defect."""
    import routers.year_end_statements as mod

    # `route.path` already carries the router's own prefix; `/api` is where
    # main.py mounts it.
    path = next(r.path for r in mod.router.routes
                if "schedules" in r.path and "{schedule_type}" in r.path)
    segments = [s for s in f"/api{path}".split("/") if s]
    assert segments == ["api", "year-end", "{engagement_id}", "schedules",
                        "{schedule_type}"], segments

    src = PAGE.read_text()
    fetched = re.search(r"\$\{BASE_URL\}(/api/year-end/[^`]*)`", src)
    assert fetched, "the schedules page no longer fetches a /api/year-end path"
    fetched_segments = [s for s in fetched.group(1).split("/") if s]
    assert len(fetched_segments) == len(segments), (
        f"The page fetches {len(fetched_segments)} path segments "
        f"({fetched.group(1)}) against a {len(segments)}-segment route. That is "
        f"a 404 on every tab, which is exactly how this went unnoticed: no "
        f"error reaches the figures because the figures never arrive.")
    assert "engagements/" not in fetched.group(1), (
        "the `engagements/` segment is back — the route has no such segment")


# ── (2)(3) one shape, and the page reads it ──────────────────────────────────

def _schedule(schedule_type: str = "cash_bank") -> dict:
    """The mock branch's answer, which is what a deployment without a database
    returns and what the page is written against."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.auth import get_current_user
    import routers.year_end_statements as mod

    import unittest.mock as m

    app = FastAPI()
    app.include_router(mod.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "u1", "firm_id": "F1", "role": "Partner",
        "email": "p@f1.test", "auth_user_id": "auth-partner"}
    # The engagement lookup is not what is under test — the SHAPE of the answer
    # is — and in mock mode there is no engagement to find.
    eng = {"id": "ENG1", "firm_id": "F1", "client_id": "C1",
           "financial_year": "2026-27", "fy_start": "2026-04-01",
           "fy_end": "2027-03-31"}
    with m.patch.object(mod, "_assert_engagement_scope", return_value=eng):
        res = TestClient(app, raise_server_exceptions=False).get(
            f"/api/year-end/ENG1/schedules/{schedule_type}")
    assert res.status_code == 200, res.text
    return res.json()["data"]


@pytest.mark.parametrize("schedule_type", [
    "cash_bank", "receivables", "payables", "fixed_assets", "gst", "tds", "loans",
])
def test_every_schedule_answers_the_same_shape(schedule_type):
    """All seven, because the mock branch had a different shape for three of
    them and a per-schedule total key for each — `net_gst_payable_paise`,
    `net_tds_payable_paise`, `total_net_block_paise`."""
    data = _schedule(schedule_type)
    assert set(data) >= {"engagement_id", "financial_year", "schedule_type",
                         "line_items", "total_paise", "gaps"}, sorted(data)
    assert data["schedule_type"] == schedule_type
    assert isinstance(data["line_items"], list)
    assert isinstance(data["total_paise"], int)
    assert isinstance(data["gaps"], list)


def test_no_schedule_still_carries_its_own_private_total_key():
    """The keys that made the shapes differ. If one comes back, a caller
    written against `total_paise` is silently reading nothing for it."""
    private = {"net_gst_payable_paise", "net_tds_payable_paise",
               "total_net_block_paise"}
    for schedule_type in ("gst", "tds", "fixed_assets"):
        assert not (private & set(_schedule(schedule_type))), schedule_type


def test_the_total_is_the_sum_of_the_lines():
    """Summed from the lines rather than restated beside them, so the two
    cannot disagree."""
    for schedule_type in ("cash_bank", "receivables", "payables", "loans"):
        data = _schedule(schedule_type)
        assert data["total_paise"] == sum(
            int(i.get("amount_paise") or i.get("net_block_paise") or 0)
            for i in data["line_items"]), schedule_type


def test_the_page_reads_line_items_and_not_rows_off_the_wire():
    """The page still renders `rows` — that is its own vocabulary — but it must
    BUILD them from the endpoint's `line_items` rather than expect the server
    to send them."""
    src = PAGE.read_text()
    assert "line_items" in src, (
        "the page no longer reads `line_items`, which is what the endpoint "
        "sends — it is back to expecting `rows` off the wire")
    assert "total_paise" in src


def test_the_page_shows_the_server_s_gaps_on_an_empty_schedule():
    """An empty schedule with the generic 'data will appear when transactions
    are posted' line is a CLAIM. Where the server says why it is empty, that is
    what the CA needs to see."""
    src = PAGE.read_text()
    assert "gaps" in src
    assert "data.gaps" in src or "gaps.map" in src


# ── (4) nothing is mapped, and it says so ────────────────────────────────────

def test_an_unmapped_schedule_is_reported_rather_than_returned_empty():
    """`account_group_mappings` holds ZERO rows in production and no screen
    writes it, so this is every schedule for every client today."""
    from routers.year_end_statements import _fetch_schedule_from_db

    class _Empty:
        def table(self, name):
            return self
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def in_(self, *a, **k): return self
        def lte(self, *a, **k): return self
        def execute(self): return type("R", (), {"data": []})()

    eng = {"id": "ENG1", "firm_id": "F1", "client_id": "C1",
           "financial_year": "2026-27", "fy_start": "2026-04-01",
           "fy_end": "2027-03-31"}
    out = _fetch_schedule_from_db(_Empty(), eng, "fixed_assets")
    assert out["line_items"] == []
    assert out["gaps"], (
        "an empty schedule came back with no explanation — which reads as "
        "'this client has no fixed assets' rather than 'nothing is mapped'")
    assert "mapped" in out["gaps"][0]


# ── (5) the balance, not the movement ────────────────────────────────────────

def test_the_figure_is_the_closing_balance_not_the_year_s_movement():
    """₹5,00,000 brought forward, ₹1,00,000 billed in the year: the schedule
    shows ₹6,00,000. Before this it showed ₹1,00,000 — the opening balance was
    simply not in the query."""
    from routers.year_end_statements import _fetch_schedule_from_db

    class _DB:
        #: Which filters were applied to the balances read. A `gte` on
        #: period_month would window OUT the opening balance, which is the
        #: defect — and a stub that answers the same rows whatever it is asked
        #: cannot tell a windowed query from an unwindowed one by its VALUE.
        #: So the filter itself is recorded.
        balance_filters: list = []

        def table(self, name):
            self._t = name
            return self
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def lte(self, *a, **k): return self
        def gte(self, *a, **k):
            if self._t == "account_period_balances":
                _DB.balance_filters.append("gte")
            return self
        def in_(self, *a, **k): return self
        def execute(self):
            if self._t == "account_group_mappings":
                return type("R", (), {"data": [
                    {"account_id": "A1", "schedule_line": "trade_receivables"}]})()
            if self._t == "accounts":
                return type("R", (), {"data": [
                    {"id": "A1", "account_name": "Trade Receivables",
                     "account_code": "1200", "account_type": "Asset"}]})()
            if self._t == "account_period_balances":
                return type("R", (), {"data": [
                    # Brought forward — a month BEFORE this financial year.
                    {"account_id": "A1", "debit_paise": 500_000_00,
                     "credit_paise": 0},
                    # This year's billing.
                    {"account_id": "A1", "debit_paise": 100_000_00,
                     "credit_paise": 0},
                ]})()
            return type("R", (), {"data": []})()

    eng = {"id": "ENG1", "firm_id": "F1", "client_id": "C1",
           "financial_year": "2026-27", "fy_start": "2026-04-01",
           "fy_end": "2027-03-31"}
    _DB.balance_filters = []
    out = _fetch_schedule_from_db(_DB(), eng, "receivables")
    assert out["total_paise"] == 600_000_00
    assert out["line_items"][0]["description"] == "Trade Receivables"
    assert out["gaps"] == []
    assert _DB.balance_filters == [], (
        "the balances read is windowed from the start of the financial year, "
        "which excludes every month that carried the opening balance — the "
        "defect, in the other table. A balance as at a date is every month UP "
        "TO it, which is why the only bound is the upper one.")


def test_the_balances_are_read_in_one_query_not_one_per_account():
    """CLAUDE.md's reporting rule. The loop this replaced made ONE QUERY PER
    ACCOUNT against journal_lines, each shipping that account's whole year to
    Python — N Singapore-to-Mumbai round trips for a document a few rows long.
    Asserted on the source, because a mock that counts calls would pass just as
    well against a loop that made one call per account into a cache."""
    src = (API_ROOT / "routers" / "year_end_statements.py").read_text()
    body = src[src.index("def _fetch_schedule_from_db"):]
    body = body[:body.index("\ndef ", 1)] if "\ndef " in body[1:] else body
    # COMMENTS AND DOCSTRINGS STRIPPED FIRST. A guard whose subject is CODE has
    # to be given code: the function's own explanation names journal_lines (it
    # says what it stopped doing), and reading that as a violation is a mistake
    # this file made on its first run — and the third time this codebase has
    # made it.
    body = re.sub(r"#[^\n]*", "", body)
    body = re.sub(r'"""[\s\S]*?"""', "", body)
    assert "journal_lines" not in body, (
        "_fetch_schedule_from_db reads journal_lines again — the pre-aggregated "
        "account_period_balances is what a balance comes from (migrations "
        "227/228), and per-row reads are what the reporting rule forbids")
    assert body.count('table("account_period_balances")') == 1
