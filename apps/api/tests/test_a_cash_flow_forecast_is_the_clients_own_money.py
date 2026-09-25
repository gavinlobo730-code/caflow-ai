"""The cash-flow forecast is built from the CLIENT's documents, not the firm's.

WHAT WAS THERE (3b-2). `/reports/cash-flow` was 352 lines of browser
arithmetic over four PostgREST reads, and three things about it were wrong in
kind rather than in detail:

  · ITS ONLY INFLOW WAS `fee_invoices` — the PRACTICE'S OWN FEE NOTES to that
    client (migration 014: `engagement_id` to `fee_engagements`, GST on SAC
    998211, which is accounting services). A client turning over crores was
    shown a forecast whose entire income was the fee they pay their
    accountant; their own `client_sales_invoices` never appeared.
  · ITS OPENING BALANCE WAS TYPED BY THE USER, and every closing figure on a
    six-month statement is carried forward from it.
  · Its only outflow was loan EMIs. No supplier payables at all.

`domain/cash_flow/forecast.py` is the rule, `services/cash_flow_service.py`
fetches, `routers/cash_flow_forecast.py` decides nothing, and the screen
renders. The three judgements the rule makes are each tested here, because
each could reasonably have gone the other way.
"""
from __future__ import annotations

import inspect
import io
import pathlib
from datetime import date

import pytest

from domain.cash_flow import forecast as rule
from domain.cash_flow.forecast import ExpectedFlow, UndatedFlow, build
from services import cash_flow_service as svc

_API = pathlib.Path(__file__).resolve().parents[1]
_SCREEN = _API.parents[1] / "apps" / "web" / "app" / "reports" / "cash-flow" / "page.tsx"

TODAY = date(2026, 9, 20)


def _flow(day: date, amount: int, kind: str = "receivable") -> ExpectedFlow:
    return ExpectedFlow(due_on=day, amount_paise=amount, kind=kind, reference="X")


# ── Judgement 1: an overdue document is not future cash ──────────────────────

def test_an_overdue_receivable_is_reported_apart_and_reaches_no_month():
    f = build(as_at=TODAY, opening_paise=0, months=3, flows=[
        _flow(date(2026, 3, 1), 500_000),
        _flow(date(2026, 9, 25), 100_000),
    ])
    assert f.overdue_in_paise == 500_000
    assert [m.inflows_paise for m in f.months] == [100_000, 0, 0]
    assert f.months[-1].closing_paise == 100_000, (
        "the overdue receivable must not be in any closing balance"
    )


def test_an_overdue_payable_is_reported_apart_too():
    f = build(as_at=TODAY, opening_paise=0, months=2, flows=[
        _flow(date(2026, 1, 9), 700_000, "payable"),
    ])
    assert f.overdue_out_paise == 700_000
    assert all(m.outflows_paise == 0 for m in f.months)


def test_the_current_month_counts_only_from_today_forward():
    """An invoice due on the 3rd when today is the 20th is overdue, not this
    month's inflow. A forecast that counts money whose date has passed is
    reporting the past as the future."""
    f = build(as_at=TODAY, opening_paise=0, months=1,
              flows=[_flow(date(2026, 9, 3), 900_000)])
    assert f.months[0].inflows_paise == 0
    assert f.overdue_in_paise == 900_000


def test_a_document_due_today_is_in_this_month():
    f = build(as_at=TODAY, opening_paise=0, months=1,
              flows=[_flow(TODAY, 900_000)])
    assert f.months[0].inflows_paise == 900_000
    assert f.overdue_in_paise == 0


# ── Judgement 2: no due date is named, never bucketed ────────────────────────

def test_an_undated_document_is_carried_through_and_lands_in_no_month():
    f = build(as_at=TODAY, opening_paise=0, months=3, flows=[],
              undated=[UndatedFlow(amount_paise=400_000, kind="payable",
                                   reference="BILL/9")])
    assert [u.reference for u in f.undated] == ["BILL/9"]
    assert all(m.inflows_paise == 0 and m.outflows_paise == 0 for m in f.months)


def test_the_service_names_an_undated_document_rather_than_deriving_one():
    dated, undated = svc._collect(
        [{"outstanding_paise": 5000, "invoice_no": "INV/1", "due_date": None,
          "invoice_date": "2026-01-01"}],
        kind="receivable", ref_keys=("invoice_no",))
    assert dated == []
    assert [u.reference for u in undated] == ["INV/1"]


# ── The arithmetic ───────────────────────────────────────────────────────────

def test_the_balance_carries_forward_through_a_month_with_nothing_in_it():
    f = build(as_at=TODAY, opening_paise=250_000, months=3, flows=[])
    assert [m.closing_paise for m in f.months] == [250_000] * 3
    assert f.months[1].opening_paise == f.months[0].closing_paise


def test_the_first_shortfall_is_the_first_negative_closing():
    f = build(as_at=TODAY, opening_paise=100_000, months=4, flows=[
        _flow(date(2026, 10, 5), 300_000, "payable"),
        _flow(date(2026, 12, 5), 900_000, "payable"),
    ])
    assert f.first_shortfall == "2026-10"
    assert [m.is_shortfall for m in f.months] == [False, True, True, True]


def test_no_shortfall_answers_none_rather_than_an_empty_string():
    f = build(as_at=TODAY, opening_paise=10, months=2, flows=[])
    assert f.first_shortfall is None


def test_by_kind_adds_up_to_the_month_it_is_on():
    f = build(as_at=TODAY, opening_paise=0, months=1, flows=[
        _flow(date(2026, 9, 25), 100, "receivable"),
        _flow(date(2026, 9, 26), 200, "payable"),
        _flow(date(2026, 9, 27), 300, "loan_emi"),
    ])
    m = f.months[0]
    assert m.by_kind == {"loan_emi": 300, "payable": 200, "receivable": 100}
    assert m.inflows_paise == 100
    assert m.outflows_paise == 500


def test_money_past_the_horizon_is_named_rather_than_dropped():
    f = build(as_at=TODAY, opening_paise=0, months=2,
              flows=[_flow(date(2027, 6, 1), 123_456)])
    assert all(m.inflows_paise == 0 for m in f.months)
    assert any("123456" in g for g in f.gaps), f.gaps


def test_a_settled_document_reaches_nothing_and_is_not_a_gap():
    f = build(as_at=TODAY, opening_paise=0, months=2,
              flows=[_flow(date(2026, 10, 1), 0), _flow(date(2026, 10, 1), -5)])
    assert all(m.inflows_paise == 0 for m in f.months)
    assert f.gaps == []


def test_every_figure_is_an_integer():
    f = build(as_at=TODAY, opening_paise=1, months=2,
              flows=[_flow(date(2026, 10, 1), 333)])
    for m in f.months:
        for value in (m.opening_paise, m.inflows_paise,
                      m.outflows_paise, m.closing_paise):
            assert isinstance(value, int) and not isinstance(value, bool)


def test_the_clock_and_the_opening_are_both_required():
    """The date because a rule that reads the clock is untestable; the opening
    because every closing balance is carried forward from it and a default of
    nil would state a position nobody measured — the defect being replaced."""
    params = inspect.signature(build).parameters
    for name in ("as_at", "opening_paise"):
        assert params[name].default is inspect.Parameter.empty
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY


def test_a_window_crosses_a_year_boundary():
    assert rule.month_windows(date(2026, 11, 8), 4) == [
        ("2026-11", "Nov 2026"), ("2026-12", "Dec 2026"),
        ("2027-01", "Jan 2027"), ("2027-02", "Feb 2027"),
    ]


def test_a_forecast_covers_at_least_one_month():
    with pytest.raises(ValueError):
        rule.month_windows(TODAY, 0)


# ── Loans ────────────────────────────────────────────────────────────────────

def test_maturity_binds_so_a_closing_loan_stops_paying():
    """The browser version spread the EMI over every month unconditionally, so
    a loan maturing next month still showed five more payments."""
    months = rule.emi_months(as_at=TODAY, months=6,
                             disbursed_on=date(2020, 1, 1),
                             matures_on=date(2026, 10, 31))
    assert [(d.year, d.month) for d in months] == [(2026, 9), (2026, 10)]


def test_a_loan_not_yet_disbursed_pays_nothing_until_it_is():
    months = rule.emi_months(as_at=TODAY, months=4,
                             disbursed_on=date(2026, 11, 14), matures_on=None)
    assert [(d.year, d.month) for d in months] == [(2026, 11), (2026, 12)]


def test_a_mid_month_disbursement_counts_for_its_own_month():
    months = rule.emi_months(as_at=TODAY, months=2,
                             disbursed_on=date(2026, 9, 28), matures_on=None)
    assert [(d.year, d.month) for d in months] == [(2026, 9), (2026, 10)]


# ── What the service reads, and what it deliberately does not ────────────────

def test_the_service_never_reads_the_practices_own_fee_notes():
    """`fee_invoices` is what the PRACTICE bills this client. It is not the
    client's income and has no business in their cash-flow forecast."""
    src = io.open(_API / "services" / "cash_flow_service.py", encoding="utf-8").read()
    body = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert 'table("fee_invoices")' not in body
    assert "client_sales_invoices" in body, "the client's own receivables ARE read"
    assert "purchase_bills" in body, "and their own payables"


def test_a_draft_invoice_is_not_forecast_cash():
    """`outstanding_paise` is GENERATED from total less paid less credited, so
    a draft — total set, nothing paid — reports its whole value as outstanding
    and would NOT fall out on its own. Nobody has been billed."""
    assert "draft" not in svc._OPEN_SALES_STATUSES
    assert "draft" not in svc._OPEN_BILL_STATUSES
    assert "paid" not in svc._OPEN_SALES_STATUSES
    assert "cancelled" not in svc._OPEN_BILL_STATUSES


def test_the_open_statuses_are_migration_050s_own_vocabulary():
    """A status this table cannot hold reads as a filter and matches nothing."""
    sql = io.open(_API / "migrations" / "050_sales_purchase_cycle.sql",
                  encoding="utf-8").read()
    for status in svc._OPEN_SALES_STATUSES + svc._OPEN_BILL_STATUSES:
        assert f"'{status}'" in sql, f"{status} is in no CHECK in migration 050"


def test_the_statutory_and_payroll_legs_are_named_on_every_answer():
    """A dip a CA is reading has to say what it excludes. Not conditional on
    there being anything else to report."""
    f = build(as_at=TODAY, opening_paise=0, months=1, flows=[])
    legs = {u["leg"] for u in f.unpriced}
    assert legs == {"statutory", "payroll"}
    assert all(u["why"].strip() for u in f.unpriced)


def test_no_unpriced_reason_states_a_figure():
    """Naming a leg is not the same as guessing at it."""
    import re
    for _, why in rule.UNPRICED_LEGS:
        assert not re.search(r"\d", why), why


# ── Only bank and cash count as cash ─────────────────────────────────────────

class _Svc:
    """A reporting engine double: one window, four accounts, one of which is
    the client's receivables ledger and must NOT be read as cash."""
    def __init__(self, nets):
        self._nets = nets

    def period_net_by_account(self, firm_id, client_id, windows, basis="accrual"):
        return {
            "accounts": {
                "a1": {"account_code": "1001", "account_name": "HDFC Bank",
                       "account_type": "Asset", "account_subtype": "Bank"},
                "a2": {"account_code": "1002", "account_name": "Cash in Hand",
                       "account_type": "Asset", "account_subtype": "Cash"},
                "a3": {"account_code": "1200", "account_name": "Trade Receivables",
                       "account_type": "Asset", "account_subtype": "Receivable"},
                "a4": {"account_code": "2100", "account_name": "Bank Loan",
                       "account_type": "Liability", "account_subtype": "Borrowing"},
            },
            "net_paise": {windows[0][0]: self._nets},
        }


def test_the_opening_position_is_the_bank_and_cash_ledgers_only():
    total, gaps = svc.opening_cash_paise(
        _Svc({"a1": 500_000, "a2": 25_000, "a3": 9_000_000, "a4": -4_000_000}),
        "firm", "client", TODAY)
    assert total == 525_000, (
        "receivables are not cash, and a bank LOAN is borrowing"
    )
    assert gaps == []


def test_a_chart_with_no_bank_ledger_says_so():
    total, gaps = svc.opening_cash_paise(
        _Svc({"a3": 9_000_000}), "firm", "client", TODAY)
    assert total == 0
    assert gaps and "opening position is nil" in gaps[0]


def test_the_window_reaches_back_to_inception():
    """A later start would silently drop the opening balances
    `opening_balance_service` posts, and it is month-aligned so the
    pre-aggregated path stays exact."""
    seen = {}

    class _Capture(_Svc):
        def period_net_by_account(self, firm_id, client_id, windows, basis="accrual"):
            seen["windows"] = windows
            return super().period_net_by_account(firm_id, client_id, windows, basis)

    svc.opening_cash_paise(_Capture({}), "firm", "client", TODAY)
    (_, start, end), = seen["windows"]
    assert start == "1900-01-01"
    assert start.endswith("-01-01"), "month-aligned, so the fast path is exact"
    assert end == TODAY.isoformat()


# ── The screen ───────────────────────────────────────────────────────────────

def test_the_screen_no_longer_computes_the_forecast_itself():
    src = io.open(_SCREEN, encoding="utf-8").read()
    assert 'from("fee_invoices")' not in src, "the practice's fee notes are back"
    assert 'from("loans")' not in src
    assert "getSupabaseClient" not in src, "it reads no table directly any more"
    assert "cashFlowForecast" in src, "it asks the endpoint"


def test_the_screen_does_not_ask_for_a_typed_opening_balance():
    """Every closing figure is carried forward from it, so a keystroke moved
    the whole statement. It comes off the ledger now."""
    src = io.open(_SCREEN, encoding="utf-8").read()
    assert "openingBalanceInput" not in src
    assert "paiseFromRupeeInput" not in src


def test_no_document_read_names_a_column_that_is_not_there():
    """⚠️ THE FIRST DRAFT SELECTED `customer_name` AND `vendor_name`, WHICH
    EXIST ON NEITHER TABLE, and the local suite passed — the guard that reads
    every `.select()` against the real schema,
    `test_backend_columns_exist_pg`, needs a Postgres and SKIPS without one,
    so CI caught it and the working copy did not. Those tables carry
    `customer_id` and `vendor_id`; naming the party means a second read per
    party for a label the document number already locates."""
    import ast
    tree = ast.parse(io.open(_API / "services" / "cash_flow_service.py",
                             encoding="utf-8").read())
    projections: list[str] = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "select"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            projections.append(node.args[0].value)
    assert projections, "the AST walk found no .select() to judge"
    joined = " ".join(projections)
    for absent in ("customer_name", "vendor_name"):
        assert absent not in joined, f"{absent} is not a column of either table"
    assert "lender_name" in joined, "loans DOES carry one, and it is selected"


def test_the_screen_narrows_the_payload_before_it_maps_over_it():
    """A 200 with an unusable payload leaves loading false, error null and
    state set — and the next `.map` throws over a heading already rendered."""
    src = io.open(_SCREEN, encoding="utf-8").read()
    assert "objectWithLists" in src
    for field in ("months", "undated", "unpriced", "gaps"):
        assert f'"{field}"' in src, f"{field} is not narrowed at the setter"
