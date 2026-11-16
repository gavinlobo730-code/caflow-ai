"""The demo's companies make a profit, carry assets their trade can support, and keep their banks above nothing (POST-A-269).

A real seed of 19-10-2026 showed five of the eight demo clients making a loss before tax (Anand Textiles turned over
Rs 26.2 lakh on a Rs 4.2 crore factory, its depreciation alone larger than its sales), and on 2-11-2026 six of the
eight bank ledgers below nothing on 31 March. A CA shown those books believes nothing else on the screen. These tests
hold the fixture to the opposite, through `domain/demo/year_estimate`, which works each client's year out from the
same data the seeder writes; reproduced against the real seed's figures before the change (Anand Textiles: revenue
Rs 26.2 lakh, cost of goods Rs 20.8 lakh, depreciation Rs 44.0 lakh against the seed's Rs 43.5 lakh, a loss of Rs 38.6
lakh against Rs 38.1 lakh).

THE YEAR IS THE ONE THE DEMO IS SEEDED FOR. Profit does not depend on it (the documents are the same in every year),
but the bank does: the settlement draw is seeded from the first document's date, so another year pays its invoices in
another pattern, and its opening balances were not chosen for it.
"""
from __future__ import annotations

import pytest

from domain.demo import fixture
from domain.demo.year_estimate import estimate
from domain.gst import irn_scope
from domain.income_tax import presumptive, tax_audit

SEEDED_YEAR = "2025-26"
FIRM = fixture.build(SEEDED_YEAR)
CLIENTS = {c.name: c for c in FIRM.clients}
YEAR = {c.name: estimate(c, SEEDED_YEAR) for c in FIRM.clients}

#: What a CA reads as an ordinary year for these businesses: in profit, and not by an implausible margin.
LOWEST_MARGIN_BPS = 300
HIGHEST_MARGIN_BPS = 3_000


def _rupees(paise: int) -> str:
    return f"Rs {paise / 100:,.0f}"


@pytest.mark.parametrize("name", sorted(CLIENTS))
def test_every_client_makes_a_profit_before_and_after_the_queue_is_passed(name):
    y = YEAR[name]
    assert y.profit_before_tax_paise > 0, f"{name} makes a loss as seeded: {_rupees(y.profit_before_tax_paise)}"
    assert y.profit_after_the_queue_paise > 0, (
        f"{name} makes a loss once the bank queue's rent and power are passed: {_rupees(y.profit_after_the_queue_paise)}")


@pytest.mark.parametrize("name", sorted(CLIENTS))
def test_every_margin_is_one_a_ca_would_believe(name):
    y = YEAR[name]
    margin = y.profit_after_the_queue_paise * 10_000 // y.turnover_paise
    assert LOWEST_MARGIN_BPS <= margin <= HIGHEST_MARGIN_BPS, (
        f"{name}: profit after the queue is {margin / 100:.1f}% of a turnover of {_rupees(y.turnover_paise)}")


@pytest.mark.parametrize("name", sorted(CLIENTS))
def test_no_client_carries_assets_its_trade_cannot_support(name):
    y = YEAR[name]
    held = y.fixed_assets_paise + y.projects_paise
    assert held <= y.turnover_paise, (
        f"{name}: assets at cost and projects under construction {_rupees(held)} against a turnover of "
        f"{_rupees(y.turnover_paise)}")
    assert y.depreciation_paise * 10 <= y.turnover_paise, (
        f"{name}: depreciation {_rupees(y.depreciation_paise)} is more than a tenth of its turnover")


@pytest.mark.parametrize("name", sorted(CLIENTS))
def test_no_bank_goes_below_nothing_in_the_seeded_year(name):
    y = YEAR[name]
    assert y.bank_lowest_paise >= 0, f"{name}'s bank falls to {_rupees(y.bank_lowest_paise)}"
    assert y.bank_lowest_after_the_queue_paise >= 0, (
        f"{name}'s bank falls to {_rupees(y.bank_lowest_after_the_queue_paise)} once the queue is passed")
    assert y.statement_lowest_paise >= 0, (
        f"{name}'s imported statement prints a balance of {_rupees(y.statement_lowest_paise)}")


def _whole_year_turnover(c) -> int:
    """Every month, the draft one included: what the client will have turned over once March is posted."""
    return sum(fixture.document_taxable_paise(d) for d in c.sales)


def test_no_registered_client_turns_over_the_figure_the_e_invoice_rule_holds():
    """Above it the client would owe an IRN on every B2B invoice of the next year, which the demo does not show."""
    limit = irn_scope.THRESHOLDS[-1][1]
    over = {c.name: _rupees(_whole_year_turnover(c)) for c in FIRM.clients
            if c.gstin and _whole_year_turnover(c) >= limit}
    assert not over, f"over {_rupees(limit)}: {over}"


def test_the_presumptive_client_stays_inside_the_section_44ad_figure():
    limits = presumptive.limits_for(SEEDED_YEAR)
    meher = CLIENTS["Meher Enterprises"]
    assert meher.income_tax and meher.income_tax.presumptive_44ad
    assert _whole_year_turnover(meher) < limits.s44ad_turnover_limit_paise


def test_the_firms_and_the_llp_stay_under_the_lowest_tax_audit_figure_the_code_holds():
    """A partnership, an LLP, a proprietor or an individual whose turnover crosses the section 44AB figure would owe a
    tax audit the demo does not show. The LLP sells advice, so it is kept under the profession figure as well."""
    t = tax_audit.THRESHOLDS_BY_FY[SEEDED_YEAR]
    for c in FIRM.clients:
        if c.entity_type == "LLP":
            limit = t.profession_limit_paise
        elif c.entity_type in ("Partnership", "Proprietorship", "Individual"):
            limit = t.business_limit_paise
        else:
            continue
        assert _whole_year_turnover(c) < limit, f"{c.name} turns over {_rupees(_whole_year_turnover(c))}"


def test_a_purchase_costs_less_than_the_sale_it_supports():
    """The defect behind the losses: a purchase line was priced at the same catalogue rate as a sale line."""
    for c in FIRM.clients:
        y = YEAR[c.name]
        assert y.goods_cost_paise + y.services_bought_paise < y.turnover_paise, c.name


def test_every_asset_bought_before_the_books_open_is_paid_for_by_capital_the_day_before():
    """The bank's ledger runs below nothing from the day of the purchase unless the money that paid for it is recorded."""
    from datetime import date, timedelta

    start = f"{SEEDED_YEAR[:4]}-04-01"
    for c in FIRM.clients:
        introduced = [(ci.on, ci.amount_paise, ci.narration) for ci in fixture.capital_introductions(c, SEEDED_YEAR)]
        for a in c.assets:
            if a.purchase_date < start:
                day_before = (date.fromisoformat(a.purchase_date) - timedelta(days=1)).isoformat()
                match = [i for i in introduced if i[0] == day_before and a.name in i[2]]
                assert len(match) == 1 and match[0][1] == fixture.paid_from_the_bank_paise(a), (c.name, a.name, match)


def test_what_the_bank_pays_for_an_asset_follows_the_door():
    """The door posts the invoice's tax only where the asset says whether the credit is available."""
    from dataclasses import replace

    a = CLIENTS["Anand Textiles"].assets[0]
    taxed = replace(a, igst_paise=0, cgst_paise=9_00, sgst_paise=9_00)
    assert fixture.paid_from_the_bank_paise(replace(taxed, itc_eligible=None)) == a.cost_paise
    assert fixture.paid_from_the_bank_paise(replace(taxed, itc_eligible=True)) == a.cost_paise + 18_00
    assert fixture.paid_from_the_bank_paise(replace(taxed, itc_eligible=False)) == a.cost_paise + 18_00


def test_each_project_under_construction_is_funded_at_its_approved_cost_on_the_day_it_starts():
    """For the cost `_cwip` sends the engine: the bills' taxable value as the bill engine computes it from what the
    seeder sends (`routers/purchase_bills._compute_bill_lines_and_totals`: `int(Decimal(str(qty)) * rate_paise)`, the
    quantity sent as a float), which a whole quantity and a whole-rupee rate make exact."""
    from decimal import Decimal

    def compute_line_gst(ln):
        return {"taxable_paise": int(Decimal(str(float(ln.quantity))) * ln.rate_paise)}

    vaibhav = CLIENTS["Vaibhav Infra"]
    draft = fixture.draft_month(SEEDED_YEAR)
    bills = {n: d for n, d in enumerate(vaibhav.purchases, start=1) if d.doc_date[:7] != draft}
    introduced = fixture.capital_introductions(vaibhav, SEEDED_YEAR)
    for p in vaibhav.cwip_projects:
        engine = sum(compute_line_gst(ln)["taxable_paise"] for n in p.bills if n in bills for ln in bills[n].lines)
        assert engine == sum(fixture.document_taxable_paise(bills[n]) for n in p.bills if n in bills), p.name
        match = [ci for ci in introduced if ci.on == p.started_on and p.name in ci.narration]
        assert len(match) == 1 and match[0].amount_paise == p.approved_cost_paise(engine), (p.name, match)


def test_the_resizing_moves_no_document():
    """Quantities and rates change; the count, the dates, the parties and the lines do not (the trap `_documents`
    records). Measured against the fixture with every client left at the size it was drawn."""
    import dataclasses
    from unittest import mock

    def as_drawn(client, size, financial_year):
        return client

    with mock.patch.object(fixture, "_in_proportion", as_drawn):
        drawn = fixture.build(SEEDED_YEAR)
    for before, after in zip(drawn.clients, FIRM.clients, strict=True):
        for kind in ("sales", "purchases"):
            b, a = getattr(before, kind), getattr(after, kind)
            assert len(a) == len(b), (after.name, kind)
            for x, y in zip(b, a, strict=True):
                assert (x.doc_date, x.party, x.place_of_supply, x.is_reverse_charge, x.settlement) == \
                       (y.doc_date, y.party, y.place_of_supply, y.is_reverse_charge, y.settlement)
                assert [(ln.description, ln.hsn_sac_code, ln.unit, ln.gst_rate_percent) for ln in x.lines] == \
                       [(ln.description, ln.hsn_sac_code, ln.unit, ln.gst_rate_percent) for ln in y.lines]
        assert [dataclasses.astuple(e) for e in before.employees] == [dataclasses.astuple(e) for e in after.employees]


def test_a_good_bought_is_brought_to_what_the_year_sells():
    """A trader buys about what it sells: no client sells a year's goods out of its opening stock."""
    draft = fixture.draft_month(SEEDED_YEAR)
    for c in FIRM.clients:
        sold = sum(float(ln.quantity) for d in c.sales if d.doc_date[:7] != draft
                   for ln in d.lines if not ln.hsn_sac_code.startswith("99"))
        bought = sum(float(ln.quantity) for d in c.purchases if d.doc_date[:7] != draft
                     for ln in d.lines if not ln.hsn_sac_code.startswith("99"))
        if sold:
            assert 0.8 <= bought / sold <= 1.25, (c.name, sold, bought)


class _Api:
    """Answers the chart read and records every write."""

    def __init__(self, chart):
        self.chart, self.posts = chart, []

    def get(self, path):
        return {"success": True, "error": None, "data": self.chart}

    def post(self, path, body):
        self.posts.append((path, body))
        return {"success": True, "error": None, "data": {"id": f"je-{len(self.posts)}"}}


def test_the_seeder_posts_each_introduction_as_a_balanced_journal_into_the_clients_own_bank():
    import scripts.seed_demo_firm as seeder

    anand = CLIENTS["Anand Textiles"]
    api = _Api([{"id": "cap-1", "account_name": "Capital Account"}, {"id": "other", "account_name": "Sales"}])
    written = {"capital_introductions": 0}
    seeder._capital(api, anand, "client-1", "bank-ledger-1", SEEDED_YEAR, written)
    expected = fixture.capital_introductions(anand, SEEDED_YEAR)
    assert written["capital_introductions"] == len(expected) == len(api.posts) > 0
    for (path, body), ci in zip(api.posts, expected, strict=True):
        assert path == "/api/accounting/journal" and body["status"] == "posted"
        assert body["client_id"] == "client-1" and body["entry_date"] == ci.on
        dr, cr = body["lines"]
        assert (dr["account_id"], dr["debit_paise"], dr["credit_paise"]) == ("bank-ledger-1", ci.amount_paise, 0)
        assert (cr["account_id"], cr["debit_paise"], cr["credit_paise"]) == ("cap-1", 0, ci.amount_paise)
    assert len({b["reference_no"] for _, b in api.posts}) == len(api.posts), "a reference repeated is a duplicate"


@pytest.mark.parametrize("bank_ledger, chart", [
    (None, [{"id": "cap-1", "account_name": "Capital Account"}]),
    ("bank-ledger-1", [{"id": "x", "account_name": "Sales"}]),
])
def test_the_seeder_refuses_rather_than_leaving_a_bank_below_nothing(bank_ledger, chart):
    import scripts.seed_demo_firm as seeder

    api = _Api(chart)
    with pytest.raises(SystemExit):
        seeder._capital(api, CLIENTS["Anand Textiles"], "client-1", bank_ledger, SEEDED_YEAR, {"capital_introductions": 0})
    assert api.posts == []


def test_a_client_with_nothing_bought_before_its_year_posts_no_capital():
    import scripts.seed_demo_firm as seeder

    api = _Api([])
    seeder._capital(api, CLIENTS["Deshmukh & Sons"], "client-1", None, SEEDED_YEAR, {"capital_introductions": 0})
    assert api.posts == []
