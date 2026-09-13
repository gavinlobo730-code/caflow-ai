"""Budget versus actuals, on the database and off the browser (ACC-06).

THREE THINGS WERE WRONG WITH `/accounting/budget` AND THE FINDING NAMED ONE.

  1. Every figure a CA typed went into
     `localStorage["practicesync_budget_<fy>"]`. Another device, another user,
     or a cleared site-data, and the year was gone.

  2. THE ACTUALS WERE SILENTLY TRUNCATED. `fetchActualsForQuarter` read
     `journal_lines` joined to `journal_entries`, firm-wide, once per quarter,
     unpaged. PostgREST caps a response at ~1000 rows and reports nothing when
     it does, so on any real client every actual was short and every variance
     wrong — with no error anywhere.

  3. IT WAS FIRM-WIDE. The chart came back on `firm_id` alone, so one grid
     mixed every client's Revenue and Expense accounts and set them against
     firm-wide actuals.

What holds the line here is the SHAPE, not the numbers: the actuals come from
`ReportingService.period_net_by_account`, which reads the pre-aggregated
buckets ONCE for all four quarters, and the endpoint refuses to answer without
a client.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = API_ROOT.parents[1] / "apps" / "web"


# ── the quarters ────────────────────────────────────────────────────────────

def test_the_four_quarters_are_the_financial_years():
    from core.ist_clock import fy_quarters
    assert fy_quarters("2026-27") == [
        ("Q1", "2026-04-01", "2026-06-30"),
        ("Q2", "2026-07-01", "2026-09-30"),
        ("Q3", "2026-10-01", "2026-12-31"),
        ("Q4", "2027-01-01", "2027-03-31"),
    ]


def test_every_quarter_bound_is_a_month_boundary():
    """The property `period_net_by_account`'s fast path depends on: a
    month-aligned window is answered exactly from the monthly buckets with no
    edge month to replay. A quarter that started on the 2nd would still be
    correct and would cost a round trip per quarter."""
    import calendar
    from core.ist_clock import fy_quarters
    for _label, start, end in fy_quarters("2025-26"):
        assert start[8:] == "01", start
        y, m = int(end[:4]), int(end[5:7])
        assert int(end[8:]) == calendar.monthrange(y, m)[1], end


def test_the_quarters_are_derived_from_fy_bounds_not_restated():
    """A change to what a financial year IS must move the quarters with it."""
    src = (API_ROOT / "core" / "ist_clock.py").read_text()
    body = src.split("def fy_quarters(")[1].split("\ndef ")[0]
    assert "fy_bounds(" in body, "fy_quarters must derive from fy_bounds"


# ── the stored figures ──────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_store():
    from services import budget_service
    budget_service.MOCK_BUDGETS.clear()
    yield
    budget_service.MOCK_BUDGETS.clear()


def test_a_budget_is_recorded_and_read_back():
    from services import budget_service
    budget_service.set_budget("F1", "C1", "A1", "2026-27", 5_00_000, actor_id="u1")
    assert budget_service.list_budgets("F1", "C1", "2026-27") == {"A1": 5_00_000}


def test_a_second_write_updates_rather_than_duplicating():
    from services import budget_service
    budget_service.set_budget("F1", "C1", "A1", "2026-27", 5_00_000)
    budget_service.set_budget("F1", "C1", "A1", "2026-27", 7_00_000)
    assert budget_service.list_budgets("F1", "C1", "2026-27") == {"A1": 7_00_000}


def test_another_client_and_another_year_are_separate():
    from services import budget_service
    budget_service.set_budget("F1", "C1", "A1", "2026-27", 100)
    budget_service.set_budget("F1", "C2", "A1", "2026-27", 200)
    budget_service.set_budget("F1", "C1", "A1", "2025-26", 300)
    budget_service.set_budget("F2", "C1", "A1", "2026-27", 400)
    assert budget_service.list_budgets("F1", "C1", "2026-27") == {"A1": 100}
    assert budget_service.list_budgets("F1", "C2", "2026-27") == {"A1": 200}
    assert budget_service.list_budgets("F1", "C1", "2025-26") == {"A1": 300}
    assert budget_service.list_budgets("F2", "C1", "2026-27") == {"A1": 400}


def test_clearing_removes_the_row_rather_than_writing_zero():
    """"Not budgeted" and "budgeted at nil" are different statements, and only
    the second produces a variance."""
    from services import budget_service
    budget_service.set_budget("F1", "C1", "A1", "2026-27", 5_00_000)
    assert budget_service.clear_budget("F1", "C1", "A1", "2026-27") is True
    assert budget_service.list_budgets("F1", "C1", "2026-27") == {}
    budget_service.set_budget("F1", "C1", "A1", "2026-27", 0)
    assert budget_service.list_budgets("F1", "C1", "2026-27") == {"A1": 0}


# ── the answer ──────────────────────────────────────────────────────────────

class _Reporting:
    """A ReportingService double that records the windows it was asked for."""

    def __init__(self, accounts, nets):
        self.accounts, self.nets, self.calls = accounts, nets, []

    def period_net_by_account(self, firm_id, client_id, windows, basis="accrual"):
        self.calls.append(windows)
        return {"accounts": self.accounts,
                "net_paise": {label: self.nets.get(label, {}) for label, _s, _e in windows}}


_ACCOUNTS = {
    "REV": {"account_code": "4001", "account_name": "Sales", "account_type": "Revenue",
            "account_subtype": "Revenue from Operations"},
    "EXP": {"account_code": "5001", "account_name": "Rent", "account_type": "Expense",
            "account_subtype": "Other Expenses"},
    "BANK": {"account_code": "1001", "account_name": "Bank", "account_type": "Asset",
             "account_subtype": "Cash and Bank"},
}


def _answer(nets=None, budgets=None):
    from services import budget_service
    for account_id, paise in (budgets or {}).items():
        budget_service.set_budget("F1", "C1", account_id, "2026-27", paise)
    rep = _Reporting(_ACCOUNTS, nets or {})
    return rep, budget_service.budget_vs_actuals(rep, "F1", "C1", "2026-27")


def test_the_buckets_are_read_once_for_all_four_quarters():
    """One call carrying four windows, not four calls. Four would be eight
    Singapore-to-Mumbai round trips for one screen."""
    rep, out = _answer()
    assert len(rep.calls) == 1
    assert [w[0] for w in rep.calls[0]] == ["Q1", "Q2", "Q3", "Q4"]
    assert [q["label"] for q in out["quarters"]] == ["Q1", "Q2", "Q3", "Q4"]


def test_only_revenue_and_expense_accounts_are_budgeted():
    _rep, out = _answer()
    assert {r["account_id"] for r in out["rows"]} == {"REV", "EXP"}


def test_revenue_is_shown_as_a_positive_magnitude():
    """The passbook works in debit-minus-credit, so revenue nets NEGATIVE. The
    grid sets it against a positive budget, so the sign is flipped once, by the
    account's own type — never with abs(), which would turn a contra-revenue
    debit into revenue earned."""
    _rep, out = _answer(nets={"Q1": {"REV": -10_00_000, "EXP": 3_00_000}})
    rev = next(r for r in out["rows"] if r["account_id"] == "REV")
    exp = next(r for r in out["rows"] if r["account_id"] == "EXP")
    assert rev["actuals"]["Q1"] == 10_00_000
    assert exp["actuals"]["Q1"] == 3_00_000


def test_a_contra_revenue_debit_stays_negative():
    """abs() would report a sales return as sales made."""
    _rep, out = _answer(nets={"Q1": {"REV": 2_00_000}})
    rev = next(r for r in out["rows"] if r["account_id"] == "REV")
    assert rev["actuals"]["Q1"] == -2_00_000


def test_the_year_is_the_sum_of_its_quarters():
    _rep, out = _answer(nets={
        "Q1": {"EXP": 1_00_000}, "Q2": {"EXP": 2_00_000},
        "Q3": {"EXP": 3_00_000}, "Q4": {"EXP": 4_00_000}})
    exp = next(r for r in out["rows"] if r["account_id"] == "EXP")
    assert exp["actual_paise"] == 10_00_000


def test_an_unbudgeted_account_has_no_variance():
    """A variance against nothing is not a variance — reporting the whole
    actual as an overspend tells a CA they are 100% over on an account they
    never budgeted."""
    _rep, out = _answer(nets={"Q1": {"EXP": 5_00_000}})
    exp = next(r for r in out["rows"] if r["account_id"] == "EXP")
    assert exp["budget_paise"] is None
    assert exp["variance_paise"] is None


def test_a_budgeted_account_carries_the_variance():
    _rep, out = _answer(nets={"Q1": {"EXP": 5_00_000}}, budgets={"EXP": 4_00_000})
    exp = next(r for r in out["rows"] if r["account_id"] == "EXP")
    assert exp["budget_paise"] == 4_00_000
    assert exp["variance_paise"] == 1_00_000


def test_a_nil_budget_is_a_real_budget_and_computes_a_variance():
    _rep, out = _answer(nets={"Q1": {"EXP": 5_00_000}}, budgets={"EXP": 0})
    exp = next(r for r in out["rows"] if r["account_id"] == "EXP")
    assert exp["budget_paise"] == 0
    assert exp["variance_paise"] == 5_00_000


# ── the endpoint ────────────────────────────────────────────────────────────

def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.auth import get_current_user
    import routers.accounting as mod

    app = FastAPI()
    app.include_router(mod.router)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "u1", "firm_id": "F1", "role": "Partner",
        "email": "p@f1.test", "auth_user_id": "auth-partner"}
    return TestClient(app, raise_server_exceptions=False)


def test_the_endpoint_refuses_without_a_client():
    """account_period_balances.client_id is NOT NULL, so a firm-wide budget has
    nothing to be compared against — unlike the reporting endpoints, where a
    missing client_id legitimately means "all clients"."""
    res = _client().get("/api/accounting/budgets?fy=2026-27")
    assert res.status_code == 422, res.text


def test_the_endpoint_answers_the_screens_shape():
    res = _client().get("/api/accounting/budgets?client_id=client-001&fy=2026-27")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["success"] is True
    data = body["data"]
    assert data["fy"] == "2026-27"
    assert data["client_id"] == "client-001"
    assert [q["label"] for q in data["quarters"]] == ["Q1", "Q2", "Q3", "Q4"]
    assert isinstance(data["rows"], list)
    for row in data["rows"]:
        assert set(row["actuals"]) == {"Q1", "Q2", "Q3", "Q4"}


def test_a_budget_is_written_and_cleared_through_the_endpoint():
    c = _client()
    body = {"client_id": "client-001", "fy": "2026-27",
            "account_id": "A1", "budget_paise": 5_00_000}
    assert c.put("/api/accounting/budgets", json=body).status_code == 200
    from services import budget_service
    assert budget_service.list_budgets("F1", "client-001", "2026-27") == {"A1": 5_00_000}

    body["budget_paise"] = None
    res = c.put("/api/accounting/budgets", json=body)
    assert res.status_code == 200, res.text
    assert res.json()["data"]["removed"] is True
    assert budget_service.list_budgets("F1", "client-001", "2026-27") == {}


def test_a_malformed_financial_year_is_refused():
    """`2026-28` passes a shape regex and then means 2026-27 — FYLabel is what
    stops it, and the endpoint must be annotated so FastAPI keeps the
    validator."""
    c = _client()
    assert c.get("/api/accounting/budgets?client_id=client-001&fy=2026-28").status_code == 422
    assert c.put("/api/accounting/budgets", json={
        "client_id": "client-001", "fy": "2026-28",
        "account_id": "A1", "budget_paise": 1}).status_code == 422


# ── the browser does not compute this any more ──────────────────────────────

def _code(src: str) -> str:
    """Source with comments stripped.

    The FY-choices guard learnt this the hard way and its own docstring says
    so: a scan that does not strip comments fires on the paragraph EXPLAINING
    the defect it forbids, which is the one paragraph that has to stay.
    """
    src = re.sub(r"/\*[\s\S]*?\*/", " ", src)
    return re.sub(r"^\s*//.*$", " ", src, flags=re.M)


def test_the_budget_screen_no_longer_reads_journal_lines():
    """The truncation defect, stated as a rule rather than a spelling: the
    budget screen may not query the ledger at all. Its answer is ~50 rows and
    comes from the backend."""
    page = WEB_ROOT / "app" / "accounting" / "budget" / "page.tsx"
    src = _code(page.read_text())
    assert "journal_lines" not in src, (
        "the budget screen is reading the ledger again — the actuals come from "
        "GET /api/accounting/budgets, which reads account_period_balances")
    assert "getSupabaseClient" not in src, (
        "the budget screen is back on the direct PostgREST path, where rbac() "
        "never runs and a read is capped at ~1000 rows with no error")
    assert not re.search(r"localStorage\.(getItem|setItem)", src), (
        "budgets are rows in account_budgets now, not this browser's storage")


def test_the_budget_screen_asks_for_a_client():
    """It was firm-wide, so one grid mixed every client's Revenue and Expense
    accounts against firm-wide actuals."""
    page = WEB_ROOT / "app" / "accounting" / "budget" / "page.tsx"
    src = _code(page.read_text())
    assert "ClientLookup" in src
    assert "api.accounting.budgets(" in src


def test_the_screen_no_longer_carries_the_browser_only_notice():
    """The notice was the honest interim while the figures were local. Leaving
    it on a screen that now writes to the database would be a false warning,
    which is its own kind of wrong."""
    page = WEB_ROOT / "app" / "accounting" / "budget" / "page.tsx"
    assert "BrowserOnlyNotice" not in page.read_text()
