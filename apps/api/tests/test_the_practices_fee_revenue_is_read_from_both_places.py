"""Profitability, fee concentration and realization count the fees billed from the firm's own books (POST-B-193).

WHAT WAS WRONG
    The firm bills its clients in two places: the earlier fee tables, and (the surviving engine, decided 20 November 2026) sales
    invoices in the practice's own books. The three figures a Partner judges clients by read the earlier tables alone, so a fee
    billed from My practice was income in the firm's ledger and nothing on Profitability.

WHAT IS ASSERTED
    * the rule (`domain/practice/fee_sources`): a customer is a client only through its link; an unlinked customer's total is in
      no client's revenue and is named; a net below nil is carried as it is; the sentences are made from the rows they are given;
    * the service: one answer per customer from the Reports page's own function, asked for the practice's client alone; no
      practice, or no database, is "not set up" and the earlier bills still answer; a failed read raises;
    * the three routes: a client billed in both places has both in its revenue; a member assigned to some clients is told the
      split of their own book and nothing of an unlinked customer; a client with a negative net does not break concentration;
    * the rule over the router: no analytics route reads the earlier fee tables directly any more.

NOT ASSERTED HERE: `report_party_totals` itself (its parity test is `tests/test_report_party_totals_parity_pg.py`), and nothing
was run against the live site.
"""
from __future__ import annotations

import ast
import inspect

import pytest

import routers.analytics as an
import services.practice_fee_revenue_service as svc
from domain.practice import fee_sources as rule
from tests._capped_postgrest import CappedDB

FIRM, PRACTICE = "firm-fr-1", "client-practice"
A, B = "client-a", "client-b"
PARTNER = {"id": "u-p", "firm_id": FIRM, "role": "Partner", "auth_user_id": "a-p"}
LINKS = {"cust-a": A, "cust-b": B}


def _line(party, total, documents=1):
    return {"party_id": party, "party_name": None, "total_paise": total, "documents": documents}


# ── the rule ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_customer_is_a_client_only_through_its_link_and_the_rest_is_named():
    rows, unlinked, customers = rule.books_rows(
        [_line("cust-a", 500_000, 2), _line("cust-b", 100_000), _line("cust-x", 70_000), _line(None, 5_000)],
        LINKS, "2026-11-30")
    assert [(r["client_id"], r["amount_paise"], r["documents"]) for r in rows] == [(A, 500_000, 2), (B, 100_000, 1)]
    assert all(r["source"] == rule.SOURCE_BOOKS and r["engagement_id"] is None and r["status"] == "Issued" for r in rows)
    assert (unlinked, customers) == (75_000, 2), "an unlinked customer's fee was dropped, or put on a client"


def test_a_net_below_nil_is_carried_and_not_floored():
    rows, unlinked, _ = rule.books_rows([_line("cust-a", -40_000)], LINKS, "2026-11-30")
    assert rows[0]["amount_paise"] == -40_000 and unlinked == 0


def test_the_rupee_sentence_is_made_from_the_rows_it_is_given():
    rows = [*rule.tagged([{"client_id": A, "amount_paise": 150_000}], rule.SOURCE_EARLIER),
            {"client_id": A, "amount_paise": 12_34_567_50, "source": rule.SOURCE_BOOKS}]
    said = rule.sentences(rows, rule.BOOKS_READ, view=rule.FOR_PROFITABILITY, unlinked_paise=0)
    assert len(said) == 1
    assert "₹12,34,567.50 from the fee bills in the firm's own books" in said[0], said[0]
    assert "₹1,500.00 from the earlier fee bills" in said[0]
    assert rule.split(rows) == {"earlier_fee_bills_paise": 150_000, "practice_books_paise": 12_34_567_50}


def test_an_unlinked_fee_is_told_to_a_firm_wide_caller_and_to_nobody_else():
    told = rule.sentences([], rule.BOOKS_READ, view=rule.FOR_PROFITABILITY, unlinked_paise=75_000, unlinked_customers=2)
    assert any("₹750.00" in s and "2 customers that are not one of the firm's clients" in s for s in told)
    not_told = rule.sentences([], rule.BOOKS_READ, view=rule.FOR_PROFITABILITY, unlinked_paise=None, unlinked_customers=2)
    assert not any("not one of the firm's clients" in s for s in not_told)
    assert rule.summary([], rule.BOOKS_READ, unlinked_paise=None, unlinked_customers=2)["unlinked_customers"] is None


def test_each_answer_says_what_is_true_of_its_own_figures():
    assert "not set up" in rule.sentences([], rule.BOOKS_NOT_SET_UP, view=rule.FOR_PROFITABILITY)[0]
    assert "earlier fee bills alone" in rule.sentences([], rule.BOOKS_NOT_SET_UP, view=rule.FOR_CONCENTRATION)[0]
    assert rule.sentences([], rule.BOOKS_NOT_SET_UP, view=rule.FOR_REALIZATION) == []
    assert "names no engagement" in rule.sentences([], rule.BOOKS_READ, view=rule.FOR_REALIZATION)[0]
    with pytest.raises(ValueError):
        rule.sentences([], rule.BOOKS_READ, view="something else")


# ── the service ───────────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def books(monkeypatch):
    """The practice's books answering two linked customers and one that is no client, and one earlier fee bill."""
    db = CappedDB({"client_firm_customer_links": [
        {"id": "l1", "firm_id": FIRM, "client_id": A, "internal_customer_id": "cust-a"},
        {"id": "l2", "firm_id": FIRM, "client_id": B, "internal_customer_id": "cust-b"},
        {"id": "l3", "firm_id": "another-firm", "client_id": "theirs", "internal_customer_id": "cust-x"},
    ]})
    asked = {}

    def party_totals(db_, firm_id, *, client_ids=None, date_from=None, date_to=None):
        asked.update(db=db_, firm=firm_id, client_ids=client_ids, window=(date_from, date_to))
        return {"revenue": [_line("cust-a", 500_000), _line("cust-b", -20_000), _line("cust-x", 70_000)], "expenses": []}

    monkeypatch.setattr(svc.db_provider, "service_db_or_none", lambda: db)
    monkeypatch.setattr(svc, "get_internal_client_id", lambda firm_id: PRACTICE if firm_id == FIRM else None)
    monkeypatch.setattr(svc.report_transactions_service, "party_totals", party_totals)
    monkeypatch.setattr(svc.invoice_repo, "fee_revenue_rows", lambda firm, a, b: [
        {"id": "f1", "client_id": A, "engagement_id": "e1", "status": "Issued", "invoice_date": a, "amount_paise": 100_000}])
    return asked


def test_the_service_reads_the_practices_own_client_and_nothing_else_of_the_firm(books):
    out = svc.fee_revenue(FIRM, "2026-11-01", "2026-11-30")
    assert books["client_ids"] == [PRACTICE] and books["firm"] == FIRM and books["window"] == ("2026-11-01", "2026-11-30")
    by = {(r["client_id"], r["source"]): r["amount_paise"] for r in out.rows}
    assert by == {(A, rule.SOURCE_EARLIER): 100_000, (A, rule.SOURCE_BOOKS): 500_000, (B, rule.SOURCE_BOOKS): -20_000}
    # cust-x is linked in ANOTHER firm only: here it is no client's, and is named.
    assert (out.books_state, out.unlinked_paise, out.unlinked_customers) == (rule.BOOKS_READ, 70_000, 1)


def test_a_firm_with_no_practice_or_no_database_still_answers_from_the_earlier_bills(books, monkeypatch):
    monkeypatch.setattr(svc, "get_internal_client_id", lambda firm_id: None)
    out = svc.fee_revenue(FIRM, "2026-11-01", "2026-11-30")
    assert out.books_state == rule.BOOKS_NOT_SET_UP and [r["source"] for r in out.rows] == [rule.SOURCE_EARLIER]
    assert "client_ids" not in books, "the practice's books were read for a firm that has none"
    monkeypatch.setattr(svc.db_provider, "service_db_or_none", lambda: None)
    assert svc.fee_revenue(FIRM, "2026-11-01", "2026-11-30").books_state == rule.BOOKS_NOT_SET_UP


def test_a_failed_read_of_the_books_is_a_failure_and_not_half_a_figure(books, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("the books could not be read")
    monkeypatch.setattr(svc.report_transactions_service, "party_totals", broken)
    with pytest.raises(RuntimeError):
        svc.fee_revenue(FIRM, "2026-11-01", "2026-11-30")


def test_the_figure_is_the_reports_pages_own_function():
    """One rule for "what was billed, net of notes, before GST": the service asks `party_totals` and adds nothing of its own."""
    src = inspect.getsource(svc.fee_revenue)
    assert "report_transactions_service.party_totals(" in src and "client_ids=[str(practice)]" in src
    tables = [c.args[0].value for c in ast.walk(ast.parse(inspect.getsource(svc)))
              if isinstance(c, ast.Call) and getattr(c.func, "attr", None) == "table" and c.args and isinstance(c.args[0], ast.Constant)]
    assert tables == ["client_firm_customer_links"], f"the service reads a document table itself: {tables}"


# ── the three routes ──────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def firm(monkeypatch):
    import core.authz as authz
    scope = {"eff": None}
    fees = svc.FeeRevenue(
        rows=[
            {"id": "f1", "client_id": A, "engagement_id": "e1", "status": "Issued", "invoice_date": "2026-11-05",
             "amount_paise": 100_000, "source": rule.SOURCE_EARLIER},
            {"id": "practice-books:a", "client_id": A, "engagement_id": None, "status": "Issued", "invoice_date": "2026-11-30",
             "amount_paise": 500_000, "source": rule.SOURCE_BOOKS},
            {"id": "practice-books:b", "client_id": B, "engagement_id": None, "status": "Issued", "invoice_date": "2026-11-30",
             "amount_paise": -20_000, "source": rule.SOURCE_BOOKS},
        ],
        books_state=rule.BOOKS_READ, unlinked_paise=70_000, unlinked_customers=1)
    monkeypatch.setattr(an.practice_fee_revenue_service, "fee_revenue", lambda firm_id, a, b: fees)
    monkeypatch.setattr(an.time_tracking_analytics_repo, "get_cost_entries", lambda *a, **k: [])
    monkeypatch.setattr(an.time_tracking_analytics_repo, "get_worth_entries", lambda *a, **k: [])
    monkeypatch.setattr(an.billing_service, "cost_rates_by_user", lambda firm_id: {})
    monkeypatch.setattr(an.client_repo, "names_by_id", lambda firm_id, **k: {A: "Client A", B: "Client B"})
    monkeypatch.setattr(an.user_repo, "find_all", lambda **k: [])
    monkeypatch.setattr(authz, "effective_client_ids", lambda user: scope["eff"])
    return scope


def _profit():
    return an.profitability_analytics(period="month", current_user=PARTNER, _fees=PARTNER)["data"]


def test_a_client_billed_in_both_places_has_both_in_its_revenue(firm):
    data = _profit()
    by_client = {c["client_id"]: c for c in data["by_client"]}
    assert by_client[A]["revenue_paise"] == 600_000
    assert data["revenue_sources"] == {
        "earlier_fee_bills_paise": 100_000, "practice_books_paise": 480_000, "practice_books": "read",
        "unlinked_paise": 70_000, "unlinked_customers": 1}
    said = " ".join(data["not_measured"])
    assert "₹4,800.00 from the fee bills in the firm's own books" in said and "₹1,000.00 from the earlier fee bills" in said
    assert "₹700.00 billed in the firm's own books to 1 customer that is not one of the firm's clients" in said


def test_a_member_assigned_to_some_clients_is_told_their_own_split_and_nothing_of_an_unlinked_customer(firm):
    firm["eff"] = {B}
    data = _profit()
    assert data["revenue_sources"] == {
        "earlier_fee_bills_paise": 0, "practice_books_paise": -20_000, "practice_books": "read",
        "unlinked_paise": None, "unlinked_customers": None}
    said = " ".join(data["not_measured"])
    assert "₹1,000.00" not in said and "₹4,800.00" not in said and "₹700.00" not in said, (
        "a member assigned to one client was told a figure of the firm's whole book")


def test_a_client_with_a_net_below_nil_does_not_break_concentration(firm):
    data = an.fee_concentration(period="month", current_user=PARTNER, _fees=PARTNER)["data"]
    assert [s["client_id"] for s in data["shares"]] == [A] and data["total_revenue_paise"] == 600_000
    assert any("fee bills in the firm's own books" in s for s in data["not_measured"])
    assert data["revenue_sources"]["practice_books_paise"] == 480_000


def test_realization_names_the_fees_that_carry_no_engagement_and_says_why(firm):
    data = an.revenue_vs_effort(period="month", current_user=PARTNER, _fees=PARTNER)["data"]
    assert data["revenue_without_engagement_paise"] == 480_000
    assert any("names no engagement" in s for s in data["not_measured"])


def test_no_analytics_route_reads_the_earlier_fee_tables_directly():
    """The rule over the router: revenue comes through the one service that reads both places. A route that went back to
    `invoice_repo.fee_revenue_rows` would silently stop counting every fee billed from My practice."""
    tree = ast.parse(inspect.getsource(an))
    direct = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in ("fee_revenue_rows", "get_revenue_by_client")]
    assert not direct, f"routers/analytics.py reads the earlier fee bills directly at lines {direct}"
    through = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "fee_revenue"
               and isinstance(n.value, ast.Name) and n.value.id == "practice_fee_revenue_service"]
    assert len(through) == 3, f"expected the three revenue answers to read through the service, found {len(through)}"
