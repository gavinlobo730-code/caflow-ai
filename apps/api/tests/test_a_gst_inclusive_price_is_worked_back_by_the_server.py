"""POST-A-490: a GST-inclusive price is worked back by the server, and the answer is the invoice's own arithmetic.

WHAT WAS MISSING
    While raising a sales invoice a person often knows only the price including GST. Nothing in the product took such a
    figure: the line asks for a unit rate before tax, so the working was done on a calculator. A tester asked for it on
    18-11-2026 and the owner said on 21-11-2026 to build it.

WHAT THESE TESTS HOLD
    The rule in `domain/sales/inclusive_price.py` and the route in front of it:
      * CGST s.15: the value of supply is the price before tax, so the answer is a unit RATE before GST and the line is
        then an ordinary line; nothing new is stored;
      * the rate answered is the NEAREST one, the lower on a tie, and where no rate reaches the typed figure the answer
        says by how much and why, never a silent difference;
      * THE ANSWER IS THE INVOICE'S OWN ARITHMETIC: the real create route is driven with the answered rate, over a grid
        of prices, quantities, rates and discounts, and the line it stores is compared with the answer figure for figure;
      * a discount on the line comes off the value before tax (CGST s.15(3)(a)) and the typed figure is the price before it;
      * what cannot be answered is refused in a sentence: a line with compensation cess, a figure too small to hold, a
        quantity the column cannot store;
      * the route writes nothing and asks whose client it is.
"""
from __future__ import annotations

import itertools
from decimal import Decimal

import pytest
from fastapi import HTTPException

from domain.sales import inclusive_price as ip
from models.invoices import SalesInvoiceIn, SalesInvoiceLineIn
from tests.e2e_harness import FakeDB, seed_standard_coa, wire_e2e

FIRM = "FIRM-A"
CALLER = {"firm_id": FIRM, "auth_user_id": "u1", "id": "u1", "email": "ca@firma.test", "role": "Partner"}


def _ask(**kw):
    base = dict(inclusive_paise=1_180_000, basis="line", quantity=1, gst_rate_bps=1800)
    return ip.rate_for_inclusive(**{**base, **kw})


# ── the rule ─────────────────────────────────────────────────────────────────

def test_the_plain_case_is_exact_and_says_so():
    a = _ask()
    assert (a.rate_paise, a.list_value_paise, a.list_tax_paise, a.list_total_paise) == (1_000_000, 1_000_000, 180_000, 1_180_000)
    assert a.exact and a.difference_paise == 0
    assert (a.taxable_paise, a.tax_paise, a.total_paise, a.discount_paise) == (1_000_000, 180_000, 1_180_000, 0)
    assert "gives exactly the ₹11,800.00 you typed" in a.sentence


def test_a_price_per_unit_is_multiplied_out_the_way_a_rate_is():
    a = _ask(inclusive_paise=11_800, basis="unit", quantity=3)
    assert a.typed_total_paise == 35_400
    assert (a.rate_paise, a.list_total_paise, a.exact) == (10_000, 35_400, True)
    # A fractional quantity truncates, as `int(Decimal(q) * rate)` does on a line.
    assert _ask(inclusive_paise=333, basis="unit", quantity=2.5, gst_rate_bps=0).typed_total_paise == 832


def test_a_total_no_rate_reaches_is_answered_with_the_nearest_rate_and_the_difference_in_words():
    # Rs 999.00 at 18%: 846.61 gives 998.99 and 846.62 gives 999.01. Both are one paisa out; the lower is chosen.
    a = _ask(inclusive_paise=99_900)
    assert a.rate_paise == 84_661 and a.list_total_paise == 99_899
    assert not a.exact and a.difference_paise == -1
    assert "₹0.01 less than the ₹999.00 you typed" in a.sentence
    assert "rounded down to the paisa" in a.sentence


def test_a_large_quantity_makes_the_gap_large_and_the_answer_says_how_large():
    # One paisa on the rate moves a line of 1,000 units by ten rupees before tax.
    a = _ask(inclusive_paise=10_000, quantity=1000)
    assert a.rate_paise == 8 and a.list_total_paise == 9_440 and a.difference_paise == -560
    assert "₹5.60 less than the ₹100.00 you typed" in a.sentence


def test_the_rate_chosen_is_the_nearest_and_the_lower_on_a_tie():
    for typed, qty, bps in itertools.product(range(100, 60_000, 977), (1, 2, 3, 0.5, 7.25, 12), (500, 1200, 1800, 2800)):
        try:
            a = _ask(inclusive_paise=typed, quantity=qty, gst_rate_bps=bps)
        except ip.CannotWorkBack:
            continue
        gap = abs(a.difference_paise)
        q = Decimal(str(qty))
        for other in (a.rate_paise - 1, a.rate_paise + 1):
            if other <= 0:
                continue
            other_gap = abs(ip._list_total(q, other, bps) - a.typed_total_paise)
            assert gap <= other_gap, f"{typed} x {qty} at {bps}: rate {other} is nearer than {a.rate_paise}"
            if other < a.rate_paise:
                assert gap < other_gap, f"{typed} x {qty} at {bps}: a lower rate is equally near and was not chosen"


def test_where_several_rates_give_the_same_line_the_lowest_is_answered():
    # Half a unit: Rs 1.90 and Rs 1.91 both come to 95 paise before tax. The lower rate multiplies out to the line exactly.
    a = _ask(inclusive_paise=95, quantity=0.5, gst_rate_bps=0)
    assert a.rate_paise == 190 and a.list_total_paise == 95 and a.exact


def test_a_nil_rate_answers_the_price_itself():
    a = _ask(inclusive_paise=50_000, quantity=2.5, gst_rate_bps=0)
    assert (a.rate_paise, a.list_tax_paise, a.list_total_paise, a.exact) == (20_000, 0, 50_000, True)
    assert "nil rate of GST" in a.sentence


def test_a_line_discount_comes_off_the_value_before_tax_and_the_typed_figure_is_the_price_before_it():
    """CGST s.15(3)(a): a discount recorded on the invoice reduces the value of supply, and the tax is on what is left."""
    a = _ask(discount_percent_bps=1000)
    assert (a.rate_paise, a.list_total_paise, a.exact) == (1_000_000, 1_180_000, True)
    assert (a.discount_paise, a.taxable_paise, a.tax_paise, a.total_paise) == (100_000, 900_000, 162_000, 1_062_000)
    assert "taken as the price before this line's discount" in a.sentence and "₹10,620.00 in all" in a.sentence
    flat = _ask(discount_paise=25_000)
    assert (flat.discount_paise, flat.taxable_paise, flat.tax_paise) == (25_000, 975_000, 175_500)


@pytest.mark.parametrize("kw,words", [
    (dict(has_cess=True), "compensation cess"),
    (dict(inclusive_paise=0), "more than zero"),
    (dict(inclusive_paise=-5), "more than zero"),
    (dict(inclusive_paise=True), "more than zero"),
    (dict(inclusive_paise=ip.MAX_INCLUSIVE_PAISE + 1), "too large"),
    (dict(basis="each"), "one unit or of the whole line"),
    (dict(quantity=0), "more than zero"),
    (dict(quantity=-1), "more than zero"),
    (dict(quantity=1.2345), "decimal"),
    (dict(gst_rate_bps=-1), "GST rate"),
    (dict(gst_rate_bps=10_001), "GST rate"),
    (dict(inclusive_paise=1, quantity=1000), "less than one paisa"),
    (dict(discount_paise=2_000_000), "exceeds the line value"),
])
def test_what_cannot_be_answered_is_refused_in_a_sentence(kw, words):
    with pytest.raises(ip.CannotWorkBack) as refused:
        _ask(**kw)
    assert words in str(refused.value), str(refused.value)


# ── the answer is the invoice's own arithmetic ───────────────────────────────

def _setup(monkeypatch):
    import routers.sales_invoices as si
    import services.sales_numbering_service as sn
    db = FakeDB()
    wire_e2e(monkeypatch, db, [si, sn])
    db.seed("clients", {"id": "CLI", "firm_id": FIRM, "gstin": "27ABCDE1234F1Z5"})
    seed_standard_coa(db, FIRM, "CLI")
    db.seed("service_catalogue", {"id": "SVC-1", "firm_id": FIRM, "client_id": "CLI", "name": "Consulting", "kind": "service"})
    return si, db


class _Body:
    """Mimics the FastAPI-parsed body for a direct call of a route function."""
    def __init__(self, model):
        self._d = model.model_dump()
        self.client_id = self._d["client_id"]

    def model_dump(self):
        return dict(self._d)


def _stored_line_for(monkeypatch, *, customer_state, rate_paise, quantity, gst_percent, discount):
    si, db = _setup(monkeypatch)
    db.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": "CLI", "name": "Buyer",
                          "state_code": customer_state, "is_active": True})
    line = dict(service_catalogue_id="SVC-1", description="Consulting", hsn_sac="998313", quantity=quantity,
                rate_paise=rate_paise, gst_rate_percent=gst_percent, **discount)
    body = SalesInvoiceIn(client_id="CLI", customer_id="CUST", invoice_date="2026-04-10", due_date="2026-05-10",
                          invoice_no="INV/2026-27/001", lines=[SalesInvoiceLineIn(**line)])
    res = si.create_invoice(_Body(body), CALLER)
    assert res["success"] is True, res
    rows = db.rows("client_sales_invoice_lines")
    assert len(rows) == 1
    return rows[0]


GRID = [
    # (typed inclusive paise, basis, quantity, GST percent, line discount)
    (1_180_000, "line", 1, 18.0, {}),
    (99_900, "line", 1, 18.0, {}),
    (11_800, "unit", 3, 18.0, {}),
    (49_999, "line", 7, 5.0, {}),
    (250_000, "line", 2.5, 12.0, {}),
    (1_234_567, "line", 12, 28.0, {}),
    (10_000, "line", 1000, 18.0, {}),
    (1_180_000, "line", 1, 18.0, {"discount_percent_bps": 1000}),
    (333_333, "line", 3, 18.0, {"discount_paise": 10_000}),
    (50_000, "line", 4, 0.0, {}),
]


@pytest.mark.parametrize("customer_state", ["27", "29"], ids=["intra-State", "inter-State"])
@pytest.mark.parametrize("typed,basis,quantity,gst_percent,discount", GRID)
def test_the_line_the_invoice_stores_at_the_answered_rate_is_the_line_the_answer_showed(
        monkeypatch, customer_state, typed, basis, quantity, gst_percent, discount):
    """The claim "as the invoice will compute it", held against the route that computes it, for a supply within the State
    (CGST and SGST) and across States (IGST): the total tax is the same either way, because the full tax is taken first
    and only then halved."""
    answer = ip.rate_for_inclusive(inclusive_paise=typed, basis=basis, quantity=quantity,
                                   gst_rate_bps=int(round(gst_percent * 100)), **discount)
    stored = _stored_line_for(monkeypatch, customer_state=customer_state, rate_paise=answer.rate_paise,
                              quantity=quantity, gst_percent=gst_percent, discount=discount)
    tax = int(stored["cgst_paise"]) + int(stored["sgst_paise"]) + int(stored["igst_paise"])
    assert int(stored["taxable_amount_paise"]) == answer.taxable_paise
    assert tax == answer.tax_paise
    assert int(stored["taxable_amount_paise"]) + tax == answer.total_paise
    assert int(stored["discount_paise"] or 0) == answer.discount_paise and int(stored["rate_paise"]) == answer.rate_paise
    if customer_state == "29":
        assert int(stored["igst_paise"]) == tax and int(stored["cgst_paise"]) == 0


# ── the route ────────────────────────────────────────────────────────────────

def _route(monkeypatch, **kw):
    si, db = _setup(monkeypatch)
    before = {name: len(db.rows(name)) for name in ("client_sales_invoices", "client_sales_invoice_lines", "journal_entries")}
    body = si.InclusiveRateIn(**{**dict(client_id="CLI", inclusive_paise=1_180_000, basis="line", quantity=1, gst_rate_bps=1800), **kw})
    try:
        return si.inclusive_rate(body, CALLER), db, before
    finally:
        after = {name: len(db.rows(name)) for name in before}
        assert after == before, "the route that only computes wrote a row"


def test_the_route_answers_the_rule_and_writes_nothing(monkeypatch):
    res, _db, _before = _route(monkeypatch)
    assert res["success"] is True and res["error"] is None
    assert res["data"] == ip.rate_for_inclusive(inclusive_paise=1_180_000, basis="line", quantity=1, gst_rate_bps=1800).as_dict()
    assert set(res["data"]) >= {"rate_paise", "typed_total_paise", "list_total_paise", "difference_paise", "exact",
                                "discount_paise", "taxable_paise", "tax_paise", "total_paise", "sentence"}


def test_the_route_refuses_in_the_rules_own_sentence(monkeypatch):
    with pytest.raises(HTTPException) as refused:
        _route(monkeypatch, has_cess=True)
    assert refused.value.status_code == 422 and "compensation cess" in refused.value.detail


def test_the_route_asks_whose_client_it_is_before_it_answers(monkeypatch):
    import routers.sales_invoices as si
    seen = []

    def refuse(user, client_id):
        seen.append(client_id)
        raise HTTPException(status_code=404, detail="Client not found")

    monkeypatch.setattr(si, "assert_client_access", refuse)
    body = si.InclusiveRateIn(client_id="SOMEBODY-ELSES", inclusive_paise=1_180_000, basis="line", gst_rate_bps=1800)
    with pytest.raises(HTTPException) as refused:
        si.inclusive_rate(body, CALLER)
    assert refused.value.status_code == 404 and seen == ["SOMEBODY-ELSES"]


def test_the_route_is_a_tool_of_whoever_may_raise_an_invoice():
    import main
    route = next(r for r in main.app.routes if getattr(r, "path", "") == "/api/sales-invoices/inclusive-rate")
    assert route.methods == {"POST"}
    create = next(r for r in main.app.routes if getattr(r, "path", "") == "/api/sales-invoices/" and "POST" in r.methods)

    def pairs(r):
        return sorted(str(getattr(d.call, "__closure__", None) and [c.cell_contents for c in d.call.__closure__])
                      for d in r.dependant.dependencies)

    assert pairs(route) == pairs(create), "the price tool asks a different permission from the invoice it is a tool of"
