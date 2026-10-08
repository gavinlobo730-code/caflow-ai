"""The demo practice's stock never goes below nil, and its tax deduction is real.

WHAT WAS WRONG (found by running the seeder over a migrated Postgres + PostgREST stack, PRE-A-004)
    * STOCK. The seeder wrote every sale of a client before any purchase, and dated the opening stock to the
      financial year the CLOCK is in (2026-27) rather than the books' (2025-26). A stock ledger is a chain in the order
      it was written, so five of eight clients' running quantity went negative (Anand: 56 of 183 ledger rows, as low
      as -403 units), and four items ended the year below nil. `domain/demo/fixture`'s own docstring and
      docs/plan/THE-PLAN.md said the first sale "relieves real stock"; it did not.
    * TDS. The seeder set `vendors.tds_section` and never `tds_applicable`, which the purchase-bill engine asks first,
      so none of 114 bills under 194C and 194J carried any TDS; no TAN was recorded for any client, so the deductor
      block could not be built. The TDS register, challans, returns, certificates and deposit worksheets were empty.

THE RULES (and why the stock walk is its own)
    * No goods item goes below nil when the year's documents are written in date order (a purchase before a sale on
      the same day; the last month is a draft and moves nothing). The walk below sorts the documents ITSELF and does
      not call `fixture.documents_in_order` or `fixture.stock_floor`, because a test that asked the code under test
      for its own answer would pass whatever it said.
    * A client that deducts tax (not an individual, with at least one vendor carrying a section) has a TAN in the
      Department's shape, and no other client does. A vendor's PAN is read out of its GSTIN (characters 3 to 12), and
      an unregistered vendor has none -- the s.206AA case.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from core.validators import validate_pan as pan_problem
from core.validators import validate_tan as tan_problem
from domain.demo import fixture

FY = "2025-26"
FIRM = fixture.build(FY)


def _running_positions(client, financial_year=FY):
    """{hsn: [(when, running quantity), ...]} from the client's opening stock and the documents that post."""
    draft = f"{int(financial_year[:4]) + 1}-03"
    goods = {i.hsn_sac_code: i for i in client.catalogue if i.kind == "good"}
    events = []
    for d in client.sales:
        if d.doc_date[:7] != draft:
            events += [(d.doc_date, 1, ln.hsn_sac_code, -Decimal(ln.quantity))
                       for ln in d.lines if ln.hsn_sac_code in goods]
    for d in client.purchases:
        if d.doc_date[:7] != draft:
            events += [(d.doc_date, 0, ln.hsn_sac_code, Decimal(ln.quantity))
                       for ln in d.lines if ln.hsn_sac_code in goods]
    events.sort(key=lambda e: (e[0], e[1]))
    running = {h: Decimal(str(i.opening_qty_units)) for h, i in goods.items()}
    out = {h: [("opening", running[h])] for h in goods}
    for when, _kind, hsn, delta in events:
        running[hsn] += delta
        out[hsn].append((when, running[hsn]))
    return out


# ── Stock ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("client", FIRM.clients, ids=lambda c: c.name)
def test_no_goods_item_goes_below_nil_in_the_year(client):
    for hsn, steps in _running_positions(client).items():
        low = min(steps, key=lambda s: s[1])
        assert low[1] >= 0, (
            f"{client.name}: item {hsn} is {low[1]} on {low[0]} -- the opening stock does not cover what the "
            "year sells before it is bought")


def test_an_item_is_opened_no_higher_than_the_year_needs_when_it_was_raised():
    """The floor is a floor and not an excuse for a warehouse: where the fixture raised an opening above the
    catalogue's default, the position touches nil at its lowest. Anything higher would hide a sizing mistake."""
    defaults = {hsn: qty for _n, hsn, _u, _r, _g, qty, _ro, _gr in (*fixture._GOODS, *fixture._SERVICES)}
    raised = 0
    for client in FIRM.clients:
        for hsn, steps in _running_positions(client).items():
            item = next(i for i in client.catalogue if i.hsn_sac_code == hsn)
            if item.opening_qty_units > defaults[hsn]:
                raised += 1
                assert min(s[1] for s in steps) == 0, (
                    f"{client.name} {item.name}: opened at {item.opening_qty_units}, above the default, but the "
                    "year never draws it to nil")
    assert raised, "no item needed raising: the sizing is not exercised by this fixture"


def test_a_default_opening_is_never_reduced():
    defaults = {hsn: qty for _n, hsn, _u, _r, _g, qty, _ro, _gr in fixture._GOODS}
    for client in FIRM.clients:
        for item in client.catalogue:
            if item.kind == "good":
                assert item.opening_qty_units >= defaults[item.hsn_sac_code], (client.name, item.name)


def test_the_opening_cost_is_still_a_cost_and_not_a_price():
    for c in FIRM.clients:
        for i in c.catalogue:
            if i.kind == "good":
                assert 0 < i.opening_cost_paise < i.rate_paise * i.opening_qty_units, (
                    f"{c.name} {i.name}: opening stock is valued at or above its price")


def test_the_order_the_documents_are_written_in_is_by_date_with_a_purchase_first():
    for c in FIRM.clients:
        steps = fixture.documents_in_order(c)
        assert len(steps) == len(c.sales) + len(c.purchases)
        keys = [(s.doc.doc_date, 0 if s.kind == "purchase" else 1) for s in steps]
        assert keys == sorted(keys), c.name
        # Interleaving changes neither numbering: `n` is the position in the client's OWN list, which is
        # what the invoice number and the vendor's bill number are built from.
        assert sorted(s.n for s in steps if s.kind == "sale") == list(range(1, len(c.sales) + 1))
        assert sorted(s.n for s in steps if s.kind == "purchase") == list(range(1, len(c.purchases) + 1))


def test_the_draft_month_is_the_last_month_of_the_year():
    assert fixture.draft_month("2025-26") == "2026-03"
    assert fixture.draft_month("2026-27") == "2027-03"


def test_changing_the_year_moves_the_sizing_with_it():
    """Nothing in the sizing is pinned to 2025-26."""
    other = fixture.build("2026-27")
    for client in other.clients:
        for hsn, steps in _running_positions(client, "2026-27").items():
            assert min(s[1] for s in steps) >= 0, (client.name, hsn)


# ── Who deducts tax, and under which number ──────────────────────────────────

def test_a_client_that_deducts_tax_has_a_tan_in_the_departments_shape_and_no_other_does():
    deductors = [c for c in FIRM.clients if c.deducts_tax]
    assert deductors, "no client deducts tax: the TDS screens are empty again"
    for c in FIRM.clients:
        if c.deducts_tax:
            assert c.tan and tan_problem(c.tan) is None, f"{c.name}: {c.tan!r}"
        else:
            assert c.tan is None, f"{c.name} has a TAN but deducts from nobody"
    assert len({c.tan for c in deductors}) == len(deductors), "two clients share a TAN"


def test_a_natural_person_deducts_nothing_and_a_company_or_firm_with_a_section_does():
    by_name = {c.name: c for c in FIRM.clients}
    assert not by_name["Priya Sharma"].deducts_tax          # an individual
    assert not by_name["Meher Enterprises"].deducts_tax     # the s.44AD presumptive proprietor
    for company in ("Anand Textiles", "Kavya Consulting", "Sunrise Foods", "Deshmukh & Sons"):
        assert by_name[company].deducts_tax, company


def test_a_vendors_pan_is_read_out_of_its_gstin_and_an_unregistered_one_has_none():
    vendors = [v for c in FIRM.clients for v in c.vendors]
    assert [v for v in vendors if v.gstin is None], "no unregistered vendor: s.206AA is unshown"
    for v in vendors:
        if v.gstin:
            assert v.pan == v.gstin[2:12] and pan_problem(v.pan) is None, v
        else:
            assert v.pan is None, v


def test_building_the_fixture_twice_gives_the_same_tans_and_openings():
    again = fixture.build(FY)
    assert [c.tan for c in FIRM.clients] == [c.tan for c in again.clients]
    assert [c.catalogue for c in FIRM.clients] == [c.catalogue for c in again.clients]
