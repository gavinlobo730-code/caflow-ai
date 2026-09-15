"""SALES-21 — quotation, proforma invoice, sales order and delivery challan.

WHAT THE PRODUCT COULD NOT DO
    The sales cycle started at the tax invoice. A client quotes, takes an
    order, delivers against it and bills afterwards; none of the first three
    documents existed, so the CA either raised the invoice EARLY — declaring a
    supply that had not happened and paying tax on it a month before the money
    arrived — or kept the quotation in a spreadsheet and re-typed every line.

    The delivery challan is the one that costs money by being absent. CGST
    Rule 55 prescribes it, and two of the movements it covers start a clock
    whose expiry is a DEEMED SUPPLY: s.143(3)/(4) for job work and s.31(7) for
    goods sent on approval. Neither clock is visible in any ledger.

THE TESTS BELOW ARE IN FOUR GROUPS
    1. The statutory module — Rule 55's particulars, the two clocks, and every
       refusal it records rather than guessing.
    2. The commercial chain — what an order still has open, and the two
       over-delivery refusals.
    3. The service — one arithmetic, the firm filter, the answer-proportional
       read, and the tax a non-supply movement must not carry.
    4. The rules that must not be broken later: no journal, no stock, no
       return.
"""
from __future__ import annotations

import ast
import inspect
import pathlib
from decimal import Decimal

import pytest

from domain.gst import delivery_challan as dc
from domain.sales import order_cycle as oc
from domain.sales.line_tax import compute_line_gst

API = pathlib.Path(__file__).resolve().parent.parent


# ══════════════════════════════════════════════════════════════════════════
# 1. CGST Rule 55 and the two clocks
# ══════════════════════════════════════════════════════════════════════════

def test_rule_55_has_nine_clauses_and_all_nine_are_listed():
    rows = dc.particulars(
        challan_no="DC/1", challan_date="2026-04-01",
        consigner_name="A", consigner_gstin=None, consigner_address="X",
        consignee_name="B", consignee_gstin=None, consignee_address="Y",
        reason=dc.REASON_JOB_WORK, is_inter_state=False,
        place_of_supply=None, lines=[{"hsn_sac": "8471", "taxable_amount_paise": 100}])
    clauses = [p.clause for p in rows]
    assert clauses == [f"55(1)({n})" for n in
                       ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix")]


def test_tax_is_required_only_where_the_movement_is_a_supply():
    """Rule 55(1)(vii): the rate and amount are required only "where the
    transportation is for supply to the consignee". A job-work despatch is not
    a supply, so requiring tax on it would report a gap on the commonest
    Rule 55 movement there is."""
    def tax_clause(reason):
        rows = dc.particulars(
            challan_no="DC/1", challan_date="2026-04-01",
            consigner_name="A", consigner_gstin="27AAPFU0939F1ZV",
            consigner_address="X", consignee_name="B", consignee_gstin=None,
            consignee_address="Y", reason=reason, is_inter_state=False,
            place_of_supply=None,
            lines=[{"hsn_sac": "8471", "taxable_amount_paise": 100}])
        return next(p for p in rows if p.clause == "55(1)(vii)")

    assert tax_clause(dc.REASON_JOB_WORK).required is False
    assert tax_clause(dc.REASON_NOT_A_SUPPLY).required is False
    assert tax_clause(dc.REASON_ON_APPROVAL).required is False
    assert tax_clause(dc.REASON_INVOICE_TO_FOLLOW).required is True
    assert tax_clause(dc.REASON_SKD_CKD_OR_LOTS).required is True
    assert tax_clause(dc.REASON_LIQUID_GAS).required is True


def test_place_of_supply_is_required_only_on_an_interstate_movement():
    """Rule 55(1)(viii), in its own words: "in case of inter-State movement"."""
    def pos_clause(inter):
        rows = dc.particulars(
            challan_no="DC/1", challan_date="2026-04-01",
            consigner_name="A", consigner_gstin=None, consigner_address="X",
            consignee_name="B", consignee_gstin=None, consignee_address="Y",
            reason=dc.REASON_JOB_WORK, is_inter_state=inter,
            place_of_supply=None, lines=[{"hsn_sac": "8471"}])
        return next(p for p in rows if p.clause == "55(1)(viii)")

    assert pos_clause(False).required is False
    assert pos_clause(True).required is True


def test_an_interstate_challan_with_no_place_of_supply_is_a_named_gap():
    rows = dc.particulars(
        challan_no="DC/1", challan_date="2026-04-01",
        consigner_name="A", consigner_gstin=None, consigner_address="X",
        consignee_name="B", consignee_gstin=None, consignee_address="Y",
        reason=dc.REASON_JOB_WORK, is_inter_state=True,
        place_of_supply=None, lines=[{"hsn_sac": "8471"}])
    missing = dc.missing_particulars(rows)
    assert any("55(1)(viii)" in m for m in missing)


def test_a_line_with_no_hsn_makes_clause_iv_a_gap():
    """Rule 46(h)'s HSN is required on the challan too, and a PARTIAL answer is
    reported as absent — the officer reads the document line by line, so "four
    of my five lines have a code" is not compliance."""
    rows = dc.particulars(
        challan_no="DC/1", challan_date="2026-04-01",
        consigner_name="A", consigner_gstin=None, consigner_address="X",
        consignee_name="B", consignee_gstin=None, consignee_address="Y",
        reason=dc.REASON_JOB_WORK, is_inter_state=False, place_of_supply=None,
        lines=[{"hsn_sac": "8471"}, {"hsn_sac": ""}])
    assert any("55(1)(iv)" in m for m in dc.missing_particulars(rows))


def test_a_nil_taxable_value_is_an_answer_and_not_a_gap():
    """A challan whose goods carry no value is unusual; a challan whose SUPPLY
    carries no tax is ordinary (exempt, nil-rated, job work). Clause (vi) must
    read "0" rather than absent, or every such movement reports a gap."""
    rows = dc.particulars(
        challan_no="DC/1", challan_date="2026-04-01",
        consigner_name="A", consigner_gstin=None, consigner_address="X",
        consignee_name="B", consignee_gstin=None, consignee_address="Y",
        reason=dc.REASON_INVOICE_TO_FOLLOW, is_inter_state=False,
        place_of_supply=None,
        lines=[{"hsn_sac": "8471", "taxable_amount_paise": 0}])
    seven = next(p for p in rows if p.clause == "55(1)(vii)")
    assert seven.value == "0"
    assert not any("55(1)(vii)" in m for m in dc.missing_particulars(rows))


def test_the_three_copies_carry_the_words_the_rule_prescribes():
    """Rule 55(2) prescribes the LEGEND, not merely that there are three
    copies. An unmarked copy is one an officer at the check-post can object
    to."""
    legends = dict(dc.COPIES)
    assert legends["original"] == "ORIGINAL FOR CONSIGNEE"
    assert legends["duplicate"] == "DUPLICATE FOR TRANSPORTER"
    assert legends["triplicate"] == "TRIPLICATE FOR CONSIGNER"


# ── The s.143 clock ──────────────────────────────────────────────────────

def test_job_work_inputs_run_one_year_and_capital_goods_three():
    a = dc.deemed_supply_clock(reason=dc.REASON_JOB_WORK,
                               challan_date="2025-04-10", as_at="2025-06-01",
                               goods_kind=dc.GOODS_KIND_INPUTS)
    b = dc.deemed_supply_clock(reason=dc.REASON_JOB_WORK,
                               challan_date="2025-04-10", as_at="2025-06-01",
                               goods_kind=dc.GOODS_KIND_CAPITAL_GOODS)
    assert a.months == 12 and a.due_back_by == "2026-04-10"
    assert b.months == 36 and b.due_back_by == "2028-04-10"


def test_goods_sent_on_approval_run_six_months_under_s31_7():
    c = dc.deemed_supply_clock(reason=dc.REASON_ON_APPROVAL,
                               challan_date="2026-01-15", as_at="2026-02-01")
    assert c.months == 6 and c.due_back_by == "2026-07-15"
    assert "31(7)" in c.statute


def test_the_kind_of_goods_is_REFUSED_and_named_never_defaulted():
    """One year and three years differ by a factor of three. Defaulting to
    inputs reports a deemed supply two years early; defaulting to capital goods
    hides one for two years. Both are wrong for two of the three kinds, so
    there is no safe default."""
    c = dc.deemed_supply_clock(reason=dc.REASON_JOB_WORK,
                               challan_date="2025-04-10", as_at="2026-06-01")
    assert c.applies is True
    assert c.months is None
    assert c.due_back_by is None
    assert c.overdue is None, "no clock may be asserted on an unrecorded kind"
    assert any("inputs or capital goods" in g for g in c.gaps)


def test_moulds_dies_jigs_fixtures_and_tools_have_NO_period():
    """The second proviso to s.143(1). Named as its own answer rather than
    modelled as a period of None, because "no clock" and "a clock nobody
    computed" must not look the same on a screen."""
    c = dc.deemed_supply_clock(reason=dc.REASON_JOB_WORK,
                               challan_date="2020-01-01", as_at="2026-09-14",
                               goods_kind=dc.GOODS_KIND_EXCLUDED)
    assert c.applies is False
    assert c.months is None
    assert c.overdue is None
    assert "second proviso" in c.consequence
    assert not c.gaps, "this is a settled answer, not a gap"


def test_a_movement_with_no_clock_says_so_rather_than_answering_zero():
    for reason in (dc.REASON_NOT_A_SUPPLY, dc.REASON_INVOICE_TO_FOLLOW,
                   dc.REASON_SKD_CKD_OR_LOTS, dc.REASON_LIQUID_GAS):
        c = dc.deemed_supply_clock(reason=reason, challan_date="2020-01-01",
                                   as_at="2026-09-14")
        assert c.applies is False, reason
        assert c.overdue is None, reason


def test_the_consequence_says_the_supply_is_deemed_on_the_day_of_DESPATCH():
    """s.143(3) deems the supply made on the day the goods were SENT OUT, not
    on the day the period expired. The difference is a year of s.50(1)
    interest and a return that has already been filed."""
    c = dc.deemed_supply_clock(reason=dc.REASON_JOB_WORK,
                               challan_date="2024-04-10", as_at="2026-09-14",
                               goods_kind=dc.GOODS_KIND_INPUTS)
    assert c.overdue is True
    assert "day they were sent out" in c.consequence
    assert "s.50(1)" in c.consequence


def test_goods_that_came_back_LATE_are_still_recorded_as_late():
    """The clock does not merely stop — whether it was met is the fact. A
    return on 2026-04-11 against a 2026-04-10 deadline IS a deemed supply."""
    late = dc.deemed_supply_clock(
        reason=dc.REASON_JOB_WORK, challan_date="2025-04-10",
        as_at="2026-09-14", goods_kind=dc.GOODS_KIND_INPUTS,
        received_back_on="2026-04-11")
    on_time = dc.deemed_supply_clock(
        reason=dc.REASON_JOB_WORK, challan_date="2025-04-10",
        as_at="2026-09-14", goods_kind=dc.GOODS_KIND_INPUTS,
        received_back_on="2026-04-10")
    assert late.overdue is True
    assert on_time.overdue is False


def test_an_extension_is_honoured_only_when_it_is_LATER_than_the_statute():
    """The proviso to s.143(1) lets the Commissioner EXTEND. A recorded date
    earlier than the Act's own would shorten a period nobody has power to
    shorten, and is far more likely a typo."""
    later = dc.deemed_supply_clock(
        reason=dc.REASON_JOB_WORK, challan_date="2025-04-10",
        as_at="2026-06-01", goods_kind=dc.GOODS_KIND_INPUTS,
        extended_to="2027-04-10")
    earlier = dc.deemed_supply_clock(
        reason=dc.REASON_JOB_WORK, challan_date="2025-04-10",
        as_at="2026-06-01", goods_kind=dc.GOODS_KIND_INPUTS,
        extended_to="2025-12-31")
    assert later.due_back_by == "2027-04-10"
    assert "extended" in later.statute
    assert earlier.due_back_by == "2026-04-10", (
        "an earlier 'extension' must not shorten the statutory period")


@pytest.mark.parametrize("sent,months,expected", [
    # A month-end that has no matching day walks BACK to the month's last day,
    # never forward into the next month — forward would put a deemed-supply
    # deadline a day LATE.
    ("2024-08-31", 6, "2025-02-28"),
    ("2023-08-31", 6, "2024-02-29"),   # a leap February
    ("2025-03-31", 12, "2026-03-31"),
    ("2024-02-29", 36, "2027-02-28"),
    ("2025-01-31", 1, "2025-02-28"),
    ("2025-12-31", 12, "2026-12-31"),
])
def test_a_month_end_deadline_never_lands_in_the_next_month(sent, months, expected):
    from datetime import date
    got = dc._add_months(date.fromisoformat(sent), months)
    assert got.isoformat() == expected


def test_no_date_on_the_challan_is_a_gap_and_not_an_answer():
    c = dc.deemed_supply_clock(reason=dc.REASON_JOB_WORK, challan_date=None,
                               as_at="2026-09-14",
                               goods_kind=dc.GOODS_KIND_INPUTS)
    assert c.due_back_by is None and c.overdue is None
    assert any("no date" in g for g in c.gaps)


# ── Rule 55(5) and ITC-04 ────────────────────────────────────────────────

def test_rule_55_5_names_all_four_steps_and_the_invoice_comes_first():
    steps = " ".join(dc.RULE_55_5_STEPS)
    assert "BEFORE dispatch of the first" in steps
    assert "SUBSEQUENT" in steps
    assert "LAST consignment" in steps
    assert len(dc.RULE_55_5_STEPS) == 4


def test_a_lots_challan_with_no_invoice_is_a_named_gap():
    gaps = dc.rule_55_5_gaps(reason=dc.REASON_SKD_CKD_OR_LOTS,
                             invoice_id=None, is_first_consignment=False)
    assert gaps and "55(5)" in gaps[0]
    assert dc.rule_55_5_gaps(reason=dc.REASON_SKD_CKD_OR_LOTS,
                             invoice_id="INV-1",
                             is_first_consignment=False) == []
    # And a rule that reaches only one reason must not fire on the others.
    assert dc.rule_55_5_gaps(reason=dc.REASON_JOB_WORK, invoice_id=None,
                             is_first_consignment=False) == []


def test_ITC_04_reports_both_readings_and_chooses_neither():
    """Rule 45(3)'s period turns on the principal's own aggregate turnover in
    the preceding FY, which no column holds. A wrong due date on a statutory
    return is worse than none."""
    answer = dc.itc_04_period()
    assert answer["decided"] is False
    assert len(answer["readings"]) == 2
    assert "HALF-YEARLY" in answer["readings"][0]
    assert "ANNUALLY" in answer["readings"][1]
    assert "turnover" in answer["refusal"]


def test_the_statutory_periods_are_pinned_so_a_change_is_deliberate():
    """Every figure here is [S]-graded — written from knowledge, because this
    environment's proxy refuses every .gov.in. Pinned so a later edit is a
    decision somebody took rather than a drift."""
    assert dc.JOB_WORK_INPUT_MONTHS == 12
    assert dc.JOB_WORK_CAPITAL_GOODS_MONTHS == 36
    assert dc.ON_APPROVAL_MONTHS == 6


# ══════════════════════════════════════════════════════════════════════════
# 2. The commercial chain
# ══════════════════════════════════════════════════════════════════════════

def test_none_of_these_documents_is_a_tax_invoice_and_the_module_says_so():
    assert "not a tax invoice" in oc.NOT_A_TAX_INVOICE.lower()
    assert "s.31" in oc.NOT_A_TAX_INVOICE
    assert oc.KIND_TITLES[oc.KIND_PROFORMA] == "Proforma Invoice"


def test_every_kind_draws_from_its_OWN_series_never_the_invoice_series():
    """Rule 46(b) requires a tax invoice's number to be CONSECUTIVE and unique
    for the FY. Consuming one for a document that may never become a supply
    puts a permanent gap in the series — and reusing the number later puts two
    documents on one number."""
    series = {oc.series_kind_of(k) for k in
              (oc.KIND_QUOTATION, oc.KIND_PROFORMA, "sales_order",
               "delivery_challan")}
    assert len(series) == 4, "each kind has its own series"
    assert "sales_invoice" not in series
    assert "invoice" not in series
    with pytest.raises(ValueError):
        oc.series_kind_of("tax_invoice")


def test_a_quotation_with_no_validity_is_not_asserted_to_be_valid():
    assert oc.is_expired(None, "2026-09-14") is None
    assert oc.is_expired("2026-09-13", "2026-09-14") is True
    assert oc.is_expired("2026-09-14", "2026-09-14") is False


def test_delivered_and_invoiced_are_two_clocks_and_an_order_needs_both():
    """Goods delivered on a challan are billed later (Rule 55's whole point),
    and a service is often billed in advance. An order tracking one figure
    would show a fully delivered order as open, or a fully billed one as
    undelivered."""
    lines = [{"id": "L1", "description": "Widget", "quantity": "10"}]
    out = oc.open_quantities(lines, {"L1": Decimal(4)}, {"L1": Decimal(9)})[0]
    assert out.undelivered_qty == Decimal(6)
    assert out.unbilled_qty == Decimal(1)
    d = out.as_dict()
    # Quantities cross the wire as STRINGS: NUMERIC(10,3) does not survive a
    # float round trip and 0.1 + 0.2 is not 0.3 in the browser either.
    assert d["ordered_qty"] == "10.000" and isinstance(d["ordered_qty"], str)


def test_a_quantity_is_never_read_through_a_float():
    """`Decimal(0.1)` is 0.1000000000000000055511151231257827021181583404541015625.
    `Decimal(str(0.1))` is 0.1. The second is the only one this codebase uses
    for money and the same rule holds for a NUMERIC quantity."""
    assert oc.to_decimal("1.005") == Decimal("1.005")
    assert oc.to_decimal(Decimal("2.5")) == Decimal("2.5")
    assert oc.to_decimal(None) == Decimal(0)


def test_over_delivery_is_REFUSED_and_the_message_says_what_to_do():
    line = oc.OpenLine("L1", "Widget", Decimal(10), Decimal(8), Decimal(0))
    ok = oc.over_delivery(line, Decimal(2))
    too_many = oc.over_delivery(line, Decimal("2.001"))
    assert ok is None
    assert too_many and "Amend the order" in too_many
    assert oc.over_delivery(line, Decimal(0)), "a nil delivery is not a delivery"


def test_over_billing_is_refused_on_its_own_figure():
    line = oc.OpenLine("L1", "Widget", Decimal(10), Decimal(10), Decimal(10))
    assert oc.over_delivery(line, Decimal(1)), "nothing left to deliver"
    assert oc.over_billing(line, Decimal(1)), "nothing left to bill"


def test_an_order_status_is_derived_but_a_closed_one_is_not_reopened():
    """`closed` is a DECISION — the customer took less than they ordered —
    and `cancelled` likewise. Recomputing would reopen them on every read."""
    part = [oc.OpenLine("L1", "W", Decimal(10), Decimal(4), Decimal(0))]
    done = [oc.OpenLine("L1", "W", Decimal(10), Decimal(10), Decimal(0))]
    none = [oc.OpenLine("L1", "W", Decimal(10), Decimal(0), Decimal(0))]
    assert oc.order_status_for(part, "confirmed") == "partially_delivered"
    assert oc.order_status_for(done, "confirmed") == "delivered"
    assert oc.order_status_for(none, "confirmed") == "confirmed"
    assert oc.order_status_for(done, "closed") == "closed"
    assert oc.order_status_for(done, "cancelled") == "cancelled"
    assert oc.order_status_for(done, "draft") == "draft"


def test_a_conversion_does_not_carry_the_earlier_documents_DATE():
    """A quotation raised in March and converted in April is an APRIL supply.
    Carrying the date forward would date the invoice into a financial year
    that may already be closed."""
    assert "document_date" not in oc.HEADER_FIELDS_CARRIED
    assert "valid_until" not in oc.HEADER_FIELDS_CARRIED
    assert "id" not in oc.LINE_FIELDS_CARRIED
    assert "quotation_id" not in oc.LINE_FIELDS_CARRIED
    carried = oc.carry_line({"description": "W", "rate_paise": 100,
                             "id": "L1", "quotation_id": "Q1"})
    assert carried == {"description": "W", "rate_paise": 100}


# ══════════════════════════════════════════════════════════════════════════
# 3. The service
# ══════════════════════════════════════════════════════════════════════════

class _Q:
    def __init__(self, store, table):
        self.store = store
        self.table_name = table
        self._rows = list(store.get(table, []))

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self._rows = [r for r in self._rows if r.get(col) == val]
        return self

    def in_(self, col, vals):
        wanted = {str(v) for v in vals}
        self._rows = [r for r in self._rows if str(r.get(col) or "") in wanted]
        return self

    def gt(self, col, val):
        self._rows = [r for r in self._rows if str(r.get(col)) > str(val)]
        return self

    def order(self, col, **k):
        self._rows.sort(key=lambda r: str(r.get(col)))
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def insert(self, payload):
        rows = payload if isinstance(payload, list) else [payload]
        from tests import production_types as pt
        pt.assert_write_fits_production_types(self.table_name, rows)
        out = []
        for row in rows:
            new = {"id": f"{self.table_name}-{len(self.store.setdefault(self.table_name, []))}",
                   **row}
            self.store[self.table_name].append(new)
            out.append(new)
        self._rows = out
        return self

    def update(self, patch):
        self._patch = patch
        return self

    def delete(self):
        self._delete = True
        return self

    def execute(self):
        if getattr(self, "_delete", False):
            doomed = {id(r) for r in self._rows}
            self.store[self.table_name] = [
                r for r in self.store.get(self.table_name, [])
                if id(r) not in doomed]
        patch = getattr(self, "_patch", None)
        if patch is not None:
            for row in self._rows:
                row.update(patch)
        # COPIES, because PostgREST returns freshly decoded JSON. A fake that
        # handed back the stored dicts would let a caller mutate the "database"
        # by decorating a row it read — and then a test asserting that a
        # derived field is never STORED would pass for the wrong reason.
        return type("R", (), {"data": [dict(r) for r in self._rows]})()


class _FakeDB:
    def __init__(self, **tables):
        self.store = {k: list(v) for k, v in tables.items()}

    def table(self, name):
        return _Q(self.store, name)


def _order_db():
    return _FakeDB(
        sales_orders=[{
            "id": "O1", "firm_id": "F1", "client_id": "C1", "customer_id": "X1",
            "document_no": "SO/1", "document_date": "2026-04-01",
            "status": "confirmed", "is_inter_state": False,
        }],
        sales_order_lines=[
            {"id": "L1", "firm_id": "F1", "client_id": "C1", "order_id": "O1",
             "line_order": 0, "description": "Widget", "quantity": "10.000"},
            {"id": "L2", "firm_id": "F1", "client_id": "C1", "order_id": "O1",
             "line_order": 1, "description": "Gadget", "quantity": "5.000"},
        ],
        delivery_challans=[],
        delivery_challan_lines=[],
        sales_quotations=[],
        sales_quotation_lines=[],
    )


def test_the_service_computes_the_same_gst_the_invoice_path_does():
    """ONE implementation. `domain/sales/line_tax.compute_line_gst` is the
    function `shared/gst-parity-vectors.json` pins to the browser mirror, and
    the invoice router now re-exports it rather than owning it."""
    from services import sales_cycle_service as svc
    priced, totals = svc.compute_lines(
        [{"description": "W", "quantity": 3, "rate_paise": 33333,
          "gst_rate_percent": 18}], is_inter_state=False)
    expect = compute_line_gst(99999, 1800, False)
    assert (priced[0]["cgst_paise"], priced[0]["sgst_paise"],
            priced[0]["igst_paise"]) == expect
    assert totals["taxable_paise"] == 99999
    # SGST carries the odd paisa, so CGST + SGST equals what IGST would be.
    assert priced[0]["cgst_paise"] + priced[0]["sgst_paise"] == \
        compute_line_gst(99999, 1800, True)[2]


def test_a_document_level_discount_is_allocated_across_the_lines_before_tax():
    """CGST s.15(3)(a) with the reason `domain/gst/discount.py` records: GST is
    charged PER LINE at the line's own rate, so a bill-level deduction that
    stayed at bill level could not be taxed at all on a mixed-rate document."""
    from services import sales_cycle_service as svc
    priced, totals = svc.compute_lines(
        [{"description": "A", "quantity": 1, "rate_paise": 100000,
          "gst_rate_percent": 18},
         {"description": "B", "quantity": 1, "rate_paise": 100000,
          "gst_rate_percent": 5}],
        is_inter_state=False, document_percent_bps=1000)
    assert totals["taxable_paise"] == 180000
    assert priced[0]["taxable_amount_paise"] == 90000
    assert priced[1]["taxable_amount_paise"] == 90000
    # And the tax followed the discount rather than the gross.
    assert priced[0]["cgst_paise"] + priced[0]["sgst_paise"] == 16200
    assert priced[1]["cgst_paise"] + priced[1]["sgst_paise"] == 4500


def test_a_non_supply_challan_carries_NO_tax_however_the_caller_asks():
    """Rule 55(1)(vii) requires the rate and amount only where the
    transportation is for supply to the consignee. A job-work despatch creates
    no output liability, so a caller who left 18% on the line must not create
    one — the rule is applied here rather than asked of the caller, because it
    is a rule a caller will get wrong."""
    from services import sales_cycle_service as svc
    db = _order_db()
    row = svc.create_challan(db, "F1", {
        "client_id": "C1", "document_no": "DC/1", "document_date": "2026-04-05",
        "reason": dc.REASON_JOB_WORK, "goods_kind": dc.GOODS_KIND_INPUTS,
        "is_inter_state": False,
        "lines": [{"description": "Casting", "quantity": 2,
                   "rate_paise": 500000, "gst_rate_percent": 18,
                   "cess_rate_bps": 1200}],
    })
    assert row["taxable_paise"] == 1000000
    assert row["cgst_paise"] == 0 and row["sgst_paise"] == 0
    assert row["igst_paise"] == 0 and row["cess_paise"] == 0
    assert row["total_paise"] == 1000000


def test_a_supply_challan_DOES_carry_tax():
    from services import sales_cycle_service as svc
    db = _order_db()
    row = svc.create_challan(db, "F1", {
        "client_id": "C1", "document_no": "DC/2", "document_date": "2026-04-05",
        "reason": dc.REASON_INVOICE_TO_FOLLOW, "is_inter_state": False,
        "lines": [{"description": "Widget", "quantity": 1,
                   "rate_paise": 100000, "gst_rate_percent": 18}],
    })
    assert row["cgst_paise"] == 9000 and row["sgst_paise"] == 9000


def test_delivering_more_than_was_ordered_is_refused():
    from fastapi import HTTPException
    from services import sales_cycle_service as svc
    db = _order_db()
    with pytest.raises(HTTPException) as e:
        svc.create_challan(db, "F1", {
            "client_id": "C1", "document_no": "DC/3",
            "document_date": "2026-04-05", "order_id": "O1",
            "reason": dc.REASON_INVOICE_TO_FOLLOW,
            "lines": [{"description": "Widget", "quantity": 11,
                       "rate_paise": 100, "order_line_id": "L1"}],
        })
    assert e.value.status_code == 422
    assert "more than the" in str(e.value.detail)
    assert not db.store["delivery_challans"], (
        "the refusal must happen before the header is written")


def test_a_delivery_moves_the_order_to_partially_delivered_then_delivered():
    from services import sales_cycle_service as svc
    db = _order_db()
    svc.create_challan(db, "F1", {
        "client_id": "C1", "document_no": "DC/4", "document_date": "2026-04-05",
        "order_id": "O1", "reason": dc.REASON_INVOICE_TO_FOLLOW,
        "lines": [{"description": "Widget", "quantity": 10, "rate_paise": 100,
                   "order_line_id": "L1"}],
    })
    assert db.store["sales_orders"][0]["status"] == "partially_delivered"
    svc.create_challan(db, "F1", {
        "client_id": "C1", "document_no": "DC/5", "document_date": "2026-04-06",
        "order_id": "O1", "reason": dc.REASON_INVOICE_TO_FOLLOW,
        "lines": [{"description": "Gadget", "quantity": 5, "rate_paise": 100,
                   "order_line_id": "L2"}],
    })
    assert db.store["sales_orders"][0]["status"] == "delivered"


def test_a_CANCELLED_challan_has_delivered_nothing():
    """The PARENT's status is read, not just the line. A query that forgot it
    would show a fully delivered order for goods that never left — and then
    refuse the real delivery as an over-delivery."""
    from services import sales_cycle_service as svc
    db = _order_db()
    svc.create_challan(db, "F1", {
        "client_id": "C1", "document_no": "DC/6", "document_date": "2026-04-05",
        "order_id": "O1", "reason": dc.REASON_INVOICE_TO_FOLLOW,
        "lines": [{"description": "Widget", "quantity": 10, "rate_paise": 100,
                   "order_line_id": "L1"}],
    })
    db.store["delivery_challans"][0]["status"] = "cancelled"
    position = svc.order_open_position(db, "F1", "O1")
    line = next(ln for ln in position["lines"] if ln["order_line_id"] == "L1")
    assert line["delivered_qty"] == "0.000"
    assert line["undelivered_qty"] == "10.000"


def test_another_firms_challan_never_reaches_this_orders_position():
    """The service-role key bypasses RLS, so `.eq("firm_id", …)` is the
    primary isolation control rather than a narrowing convenience."""
    from services import sales_cycle_service as svc
    db = _order_db()
    db.store["delivery_challans"].append({
        "id": "ZZ", "firm_id": "F2", "client_id": "C1", "status": "issued",
        "document_no": "DC/X", "document_date": "2026-04-05",
        "reason": dc.REASON_INVOICE_TO_FOLLOW})
    db.store["delivery_challan_lines"].append({
        "id": "ZZL", "firm_id": "F2", "client_id": "C1", "challan_id": "ZZ",
        "order_line_id": "L1", "quantity": "10.000", "line_order": 0,
        "description": "Widget"})
    position = svc.order_open_position(db, "F1", "O1")
    line = next(ln for ln in position["lines"] if ln["order_line_id"] == "L1")
    assert line["delivered_qty"] == "0.000"


def test_EVERY_read_and_write_in_the_service_carries_the_firm_filter():
    """The service-role key bypasses RLS, so `.eq("firm_id", …)` is the primary
    isolation control (CLAUDE.md, "Tenancy and access") — "Never write a query
    that omits it".

    STATED AS THE RULE, not as one scenario. The behavioural test below catches
    a dropped filter on the read whose result is USED; a filter dropped on a
    read whose rows are later discarded still crosses the tenant boundary and
    still returns another firm's rows over the wire, and no behavioural
    assertion can see that. So every `db.table(...)` chain in the module is
    walked and required to carry the filter.
    """
    tree = ast.parse((API / "services" / "sales_cycle_service.py")
                     .read_text(encoding="utf-8"))
    missing: list = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "table"):
            continue
        # Walk back OUT to the whole chain this .table(...) call starts, by
        # finding the outermost expression containing it.
        chain = ast.unparse(_outermost_chain(tree, node))
        table = (node.args[0].value if node.args
                 and isinstance(node.args[0], ast.Constant) else "?")
        # An INSERT scopes itself by CARRYING `firm_id` in the row rather than
        # by filtering: there is nothing to filter on a row that does not exist
        # yet. Both forms are required, and neither excuses the other.
        if ".insert(" in chain:
            scoped = "'firm_id'" in chain or _insert_payload_carries_firm(tree, node)
        else:
            scoped = "eq('firm_id'" in chain or 'eq("firm_id"' in chain
        if not scoped:
            missing.append(f"{table}: {chain[:110]}")
    assert not missing, (
        "these queries omit the firm filter:\n" + "\n".join(missing))


def _insert_payload_carries_firm(tree: ast.AST, table_call: ast.Call) -> bool:
    """Whether `.insert(name)` hands over a dict literal carrying `firm_id`.

    Resolves a LOCAL variable assigned a dict literal in the same function —
    the same thing `tests/test_backend_inserts_supply_every_required_column_pg`
    does, and for the same reason: the readable way to write a long row is to
    build it above and insert the name, and a guard that cannot follow one step
    of indirection just pushes every payload out of its own sight.
    """
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(n is table_call for n in ast.walk(fn)):
            continue
        # The .insert(...) call whose receiver chain contains this .table(...).
        for call in ast.walk(fn):
            if not (isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "insert"):
                continue
            if not any(n is table_call for n in ast.walk(call.func)):
                continue
            for arg in call.args:
                if isinstance(arg, ast.Dict):
                    if any(isinstance(k, ast.Constant) and k.value == "firm_id"
                           for k in arg.keys):
                        return True
                elif isinstance(arg, ast.Name):
                    for node in ast.walk(fn):
                        if not isinstance(node, ast.Assign):
                            continue
                        names = {t.id for t in node.targets
                                 if isinstance(t, ast.Name)}
                        if arg.id in names and isinstance(node.value, ast.Dict):
                            if any(isinstance(k, ast.Constant)
                                   and k.value == "firm_id"
                                   for k in node.value.keys):
                                return True
    return False


def _outermost_chain(tree: ast.AST, target: ast.Call) -> ast.AST:
    """The largest expression whose subtree contains `target`."""
    best = target
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Call, ast.Attribute)):
            continue
        if node is target:
            continue
        if any(child is target for child in ast.walk(node)):
            if len(ast.unparse(node)) > len(ast.unparse(best)):
                best = node
    return best


def test_the_gross_is_quantity_times_rate_in_DECIMAL_never_a_float():
    """1.005 units at Rs 100.00 is Rs 100.50 exactly. In binary floating point
    `1.005 * 10000` is 10049.999999999998, and `int()` of that is 10049 — one
    paisa short, on every line whose quantity is not a clean binary fraction.
    That is the same round trip CLAUDE.md forbids for money."""
    from services import sales_cycle_service as svc
    priced, totals = svc.compute_lines(
        [{"description": "Cable", "quantity": "1.005", "rate_paise": 10000,
          "gst_rate_percent": 18}], is_inter_state=False)
    assert priced[0]["taxable_amount_paise"] == 10050
    assert totals["taxable_paise"] == 10050


def test_a_kind_of_goods_belongs_ONLY_to_a_job_work_movement():
    """CGST s.143 reaches goods sent to a job worker and nothing else, so
    recording a kind on any other challan asserts a clock that does not run —
    and would show a deemed supply on a movement the section never touches.
    Refused at the model AND CHECKed in the database; the model refusal exists
    so the CA gets the sentence instead of a constraint-violation 500."""
    from pydantic import ValidationError
    from models.sales_cycle import DeliveryChallanIn
    base = {"client_id": "C1", "document_no": "DC/1",
            "document_date": "2026-04-01",
            "lines": [{"description": "W", "rate_paise": 100}]}
    DeliveryChallanIn(**{**base, "reason": dc.REASON_JOB_WORK,
                         "goods_kind": dc.GOODS_KIND_INPUTS})
    for reason in (dc.REASON_NOT_A_SUPPLY, dc.REASON_ON_APPROVAL,
                   dc.REASON_INVOICE_TO_FOLLOW, dc.REASON_LIQUID_GAS,
                   dc.REASON_SKD_CKD_OR_LOTS):
        with pytest.raises(ValidationError):
            DeliveryChallanIn(**{**base, "reason": reason,
                                 "goods_kind": dc.GOODS_KIND_INPUTS})
        with pytest.raises(ValidationError):
            DeliveryChallanIn(**{**base, "reason": reason,
                                 "extended_to": "2027-01-01"})


def test_the_invoiced_figure_is_ZERO_and_says_why_rather_than_guessing():
    """An invoice line carries no link back to an order line, so pairing them
    would mean matching on description and rate — a guess that silently
    under-bills an order whose invoice line was reworded."""
    from services import sales_cycle_service as svc
    db = _order_db()
    position = svc.order_open_position(db, "F1", "O1")
    assert all(ln["invoiced_qty"] == "0.000" for ln in position["lines"])
    assert position["gaps"] == [svc.INVOICED_QUANTITY_IS_NOT_LINKED]
    assert "not tracked" in svc.INVOICED_QUANTITY_IS_NOT_LINKED


def test_two_documents_may_not_bear_one_number():
    from fastapi import HTTPException
    from services import sales_cycle_service as svc
    db = _order_db()
    payload = {"client_id": "C1", "customer_id": "X1", "kind": "quotation",
               "document_no": "QT/1", "document_date": "2026-04-01",
               "lines": [{"description": "W", "quantity": 1,
                          "rate_paise": 1000, "gst_rate_percent": 18}]}
    svc.create_quotation(db, "F1", payload)
    with pytest.raises(HTTPException) as e:
        svc.create_quotation(db, "F1", dict(payload))
    assert e.value.status_code == 409
    # Case is not a second document either.
    with pytest.raises(HTTPException):
        svc.create_quotation(db, "F1", {**payload, "document_no": "qt/1"})


def test_a_quotation_and_a_proforma_MAY_share_a_number():
    """They are different series. Rule 46(b) reaches neither, and the only rule
    this product imposes is uniqueness per client PER KIND."""
    from services import sales_cycle_service as svc
    db = _order_db()
    base = {"client_id": "C1", "customer_id": "X1", "document_no": "D/1",
            "document_date": "2026-04-01",
            "lines": [{"description": "W", "quantity": 1, "rate_paise": 1000,
                       "gst_rate_percent": 18}]}
    svc.create_quotation(db, "F1", {**base, "kind": "quotation"})
    svc.create_quotation(db, "F1", {**base, "kind": "proforma"})
    assert len(db.store["sales_quotations"]) == 2


def test_recording_the_goods_back_stops_the_clock():
    from services import sales_cycle_service as svc
    db = _order_db()
    svc.create_challan(db, "F1", {
        "client_id": "C1", "document_no": "DC/7", "document_date": "2025-04-10",
        "reason": dc.REASON_JOB_WORK, "goods_kind": dc.GOODS_KIND_INPUTS,
        "lines": [{"description": "Casting", "quantity": 1, "rate_paise": 100}],
    })
    cid = db.store["delivery_challans"][0]["id"]
    before = svc.list_challans(db, "F1", "C1")[0]["clock"]
    assert before["overdue"] is True
    svc.record_goods_back(db, "F1", cid, "2026-03-01")
    after = svc.list_challans(db, "F1", "C1")[0]["clock"]
    assert after["overdue"] is False


def test_an_expired_quotation_is_derived_on_every_read():
    """A quotation does not become expired by anyone DOING anything, so a
    stored status would need a nightly job and would be wrong between runs."""
    from services import sales_cycle_service as svc
    db = _order_db()
    svc.create_quotation(db, "F1", {
        "client_id": "C1", "customer_id": "X1", "kind": "quotation",
        "document_no": "QT/9", "document_date": "2020-01-01",
        "valid_until": "2020-02-01",
        "lines": [{"description": "W", "quantity": 1, "rate_paise": 1,
                   "gst_rate_percent": 18}]})
    row = svc.list_quotations(db, "F1", "C1")[0]
    assert row["is_expired"] is True
    assert row["title"] == "Quotation"
    assert "is_expired" not in db.store["sales_quotations"][0], (
        "derived on read, never written")


def test_amending_the_lines_KEEPS_the_document_level_discount():
    """A CA who edits a line and does not re-send the header discount has not
    withdrawn it. Re-pricing without it would raise every figure on the
    document by the discount — which the customer has already been quoted —
    and CGST s.15(3)(a)'s relief is conditional on the document SHOWING it."""
    from services import sales_cycle_service as svc
    db = _order_db()
    q = svc.create_quotation(db, "F1", {
        "client_id": "C1", "customer_id": "X1", "kind": "quotation",
        "document_no": "QT/7", "document_date": "2026-04-01",
        "discount_percent_bps": 1000,
        "lines": [{"description": "A", "quantity": 1, "rate_paise": 100000,
                   "gst_rate_percent": 18}]})
    assert q["taxable_paise"] == 90000
    assert q["discount_percent_bps"] == 1000, "the figure the CA typed is stored"
    out = svc.update_quotation(db, "F1", q["id"], {
        "lines": [{"description": "A (rev 2)", "quantity": 1,
                   "rate_paise": 100000, "gst_rate_percent": 18}]})
    assert out["taxable_paise"] == 90000, (
        "the stored document discount was dropped on an amendment")
    # And sending a NEW one replaces it.
    out2 = svc.update_quotation(db, "F1", q["id"], {
        "discount_percent_bps": 2000,
        "lines": [{"description": "A", "quantity": 1, "rate_paise": 100000,
                   "gst_rate_percent": 18}]})
    assert out2["taxable_paise"] == 80000


def test_a_CONVERTED_quotation_cannot_be_amended():
    """Its lines are already the order's or the invoice's. Editing it
    afterwards leaves two documents claiming to say the same thing while
    saying different things — and a quotation costs nothing to re-raise."""
    from fastapi import HTTPException
    from services import sales_cycle_service as svc
    db = _order_db()
    q = svc.create_quotation(db, "F1", {
        "client_id": "C1", "customer_id": "X1", "kind": "quotation",
        "document_no": "QT/5", "document_date": "2026-04-01",
        "lines": [{"description": "W", "quantity": 1, "rate_paise": 1000,
                   "gst_rate_percent": 18}]})
    svc.update_quotation(db, "F1", q["id"], {"notes": "chased"})
    db.store["sales_quotations"][0]["status"] = "converted"
    with pytest.raises(HTTPException) as e:
        svc.update_quotation(db, "F1", q["id"], {"notes": "again"})
    assert e.value.status_code == 409


def test_amending_a_quotations_lines_REPLACES_them_and_re_totals():
    """A line taken off the payload is a line the CA took off the document.
    Merging would leave it priced into the totals with no row to show for
    it — the shape that makes a document's own total unexplainable."""
    from services import sales_cycle_service as svc
    db = _order_db()
    q = svc.create_quotation(db, "F1", {
        "client_id": "C1", "customer_id": "X1", "kind": "quotation",
        "document_no": "QT/6", "document_date": "2026-04-01",
        "lines": [{"description": "A", "quantity": 1, "rate_paise": 100000,
                   "gst_rate_percent": 18},
                  {"description": "B", "quantity": 1, "rate_paise": 100000,
                   "gst_rate_percent": 18}]})
    assert q["taxable_paise"] == 200000
    out = svc.update_quotation(db, "F1", q["id"], {
        "lines": [{"description": "A", "quantity": 1, "rate_paise": 100000,
                   "gst_rate_percent": 18}]})
    assert out["taxable_paise"] == 100000
    assert len(svc.quotation_lines(db, "F1", q["id"])) == 1


def test_an_order_with_a_delivery_against_it_keeps_its_lines():
    """Re-pricing them would change the quantity a challan was already checked
    against for over-delivery, and deleting a line out from under a challan
    leaves the challan pointing at nothing."""
    from fastapi import HTTPException
    from services import sales_cycle_service as svc
    db = _order_db()
    # The header is still correctable.
    svc.update_order(db, "F1", "O1", {"customer_po_no": "PO-9"})
    assert db.store["sales_orders"][0]["customer_po_no"] == "PO-9"
    svc.create_challan(db, "F1", {
        "client_id": "C1", "document_no": "DC/8", "document_date": "2026-04-05",
        "order_id": "O1", "reason": dc.REASON_INVOICE_TO_FOLLOW,
        "lines": [{"description": "Widget", "quantity": 1, "rate_paise": 100,
                   "order_line_id": "L1"}]})
    with pytest.raises(HTTPException) as e:
        svc.update_order(db, "F1", "O1", {
            "lines": [{"description": "Widget", "quantity": 99,
                       "rate_paise": 100, "gst_rate_percent": 18}]})
    assert e.value.status_code == 409
    assert "over-delivery" in str(e.value.detail)


def test_the_challan_PATCH_refuses_a_kind_of_goods_on_a_non_job_work_movement():
    """The create door refuses it and so must this one — a validator on one
    door is one PATCH away from being none."""
    from fastapi import HTTPException
    from services import sales_cycle_service as svc
    db = _order_db()
    svc.create_challan(db, "F1", {
        "client_id": "C1", "document_no": "DC/9", "document_date": "2026-04-05",
        "reason": dc.REASON_NOT_A_SUPPLY,
        "lines": [{"description": "Sample", "quantity": 1, "rate_paise": 100}]})
    cid = db.store["delivery_challans"][0]["id"]
    with pytest.raises(HTTPException) as e:
        svc.update_challan(db, "F1", cid,
                           {"goods_kind": dc.GOODS_KIND_INPUTS})
    assert e.value.status_code == 422
    with pytest.raises(HTTPException):
        svc.update_challan(db, "F1", cid, {"extended_to": "2027-01-01"})


def test_the_challan_PATCH_records_the_goods_back_and_stamps_the_status():
    from services import sales_cycle_service as svc
    db = _order_db()
    svc.create_challan(db, "F1", {
        "client_id": "C1", "document_no": "DC/10",
        "document_date": "2025-04-10", "reason": dc.REASON_JOB_WORK,
        "goods_kind": dc.GOODS_KIND_INPUTS,
        "lines": [{"description": "Casting", "quantity": 1, "rate_paise": 100}]})
    cid = db.store["delivery_challans"][0]["id"]
    out = svc.update_challan(db, "F1", cid, {"received_back_on": "2026-01-05"})
    assert out["status"] == "received_back"
    assert svc.list_challans(db, "F1", "C1")[0]["clock"]["overdue"] is False


# ══════════════════════════════════════════════════════════════════════════
# 4. The rules that must not be broken later
# ══════════════════════════════════════════════════════════════════════════

_SIX_TABLES = ("sales_quotations", "sales_quotation_lines", "sales_orders",
               "sales_order_lines", "delivery_challans",
               "delivery_challan_lines")


def _referenced_names(path: pathlib.Path) -> set:
    """Every identifier and string literal the module's CODE uses.

    AST, not a substring scan of the file. The first draft of this guard read
    the raw source and failed on the module's own docstring, which NAMES
    `_create_journal` to say it is not imported — the same shape as the
    migration-rollback test that was satisfied by its own header comment. A
    guard a comment can defeat is a guard a comment can also silently satisfy.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    # Drop every docstring before walking: they are prose ABOUT the rule.
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if (isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                              ast.ClassDef)) and body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            body.pop(0)
    names: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            names.add(node.value)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.name)
                if alias.asname:
                    names.add(alias.asname)
            if isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
    return names


def test_no_pre_invoice_document_posts_a_journal_or_moves_stock():
    """No revenue is earned on an offer and no receivable exists; goods leaving
    on a challan have not been sold. Asserted on the module's CODE, because a
    posting added later would pass every behavioural test here."""
    names = _referenced_names(API / "services" / "sales_cycle_service.py")
    for forbidden in ("_create_journal", "journal_entries", "journal_lines",
                      "inventory_stock_ledger", "apply_stock_adjustment",
                      "apply_purchase_to_inventory",
                      "phase2_journal_service", "inventory_service"):
        assert forbidden not in names, (
            f"{forbidden} reached the pre-invoice service — none of these "
            f"documents posts to the ledger or moves stock")


def test_no_return_builder_reads_any_of_the_six_tables():
    """GSTR-1 and GSTR-3B are built from documents that DECLARE a supply. A
    proforma invoice is the trap: it looks like an invoice and is often
    numbered like one, and a return that picked one up would declare a supply
    that never happened — tax paid on an offer the customer declined."""
    offenders: list = []
    for name in ("services/gst_return_service.py",
                 "services/gstr9_service.py",
                 "services/gst_amendment_service.py",
                 "domain/gst/gstr1_builder.py",
                 "domain/gst/gstr3b_computer.py",
                 "domain/gst/gstr9_builder.py",
                 "domain/gst/exception_report.py"):
        path = API / name
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8")
        for table in _SIX_TABLES:
            if table in src:
                offenders.append(f"{name} reads {table}")
    assert not offenders, "\n".join(offenders)


def test_the_migration_states_every_rule_the_schema_has_to_carry():
    sql = _sql_only((API / "migrations" /
                     "392_the_sales_cycle_before_the_tax_invoice.sql")
                    .read_text(encoding="utf-8"))
    # `goods_kind` nullable with NO default — the s.143 third state.
    assert "goods_kind     TEXT" in sql
    assert "goods_kind" in sql and "DEFAULT" not in sql.split("goods_kind")[1].split(",")[0]
    # Only a job-work movement may carry one, or an extension.
    assert "delivery_challans_goods_kind_is_job_work" in sql
    assert "delivery_challans_extension_is_job_work" in sql
    # Rule 55(1)'s sixteen characters, and Rule 46(b)'s on the documents that
    # become an invoice.
    assert sql.count("length(document_no) <= 16") == 3
    # One number per client, per kind for the quotations.
    assert "uq_sales_quotation_no_per_client_kind" in sql
    assert "uq_sales_order_no_per_client" in sql
    assert "uq_delivery_challan_no_per_client" in sql
    # No stored delivered/invoiced quantity — derived, migration 278's reason.
    assert "delivered_qty" not in sql
    assert "invoiced_qty" not in sql
    # Nor a stored expiry flag: a quotation does not become expired by anyone
    # DOING anything, so a column would need a nightly job to stay true.
    assert "is_expired" not in sql
    # And no journal anywhere near these tables.
    assert "journal_entry_id" not in sql


def test_every_new_table_is_assignment_scoped_and_read_only_from_the_browser():
    """Migration 084's loop has never run again (see 370), so a table created
    now carries only its firm-wide policy unless it says otherwise. All six are
    read from the browser."""
    sql = _sql_only((API / "migrations" /
                     "392_the_sales_cycle_before_the_tax_invoice.sql")
                    .read_text(encoding="utf-8"))
    assert "_assignment_scope" in sql
    assert "can_access_client" in sql
    assert "GRANT SELECT ON public.%1$I TO authenticated" in sql
    assert "INSERT" not in sql.split("TO authenticated")[1].split("service_role")[0]
    for table in _SIX_TABLES:
        assert f"'{table}'" in sql, f"{table} is not in the policy loop"


def test_the_rollback_refuses_while_a_clock_is_still_running():
    """Dropping the table loses the only record either period can be run
    against, and the deemed supply it hides falls due on the challan date — in
    a return already filed."""
    sql = _sql_only((API / "migrations" /
                     "392_the_sales_cycle_before_the_tax_invoice_rollback.sql")
                    .read_text(encoding="utf-8"))
    assert "RAISE EXCEPTION" in sql
    assert "received_back_on IS NULL" in sql
    assert "job_work" in sql and "sale_on_approval" in sql


def _sql_only(text: str) -> str:
    """The statements, with the header comment stripped.

    A guard that reads the whole file passes on a migration whose own header
    merely MENTIONS the thing it is meant to assert — which is how migration
    390's rollback test came to be satisfied by a paragraph of prose.
    """
    return "\n".join(line for line in text.splitlines()
                     if not line.strip().startswith("--"))


def test_the_service_holds_no_exception_swallow_around_a_write():
    """A bare except around an insert is how a document comes to be silently
    half-written. Asserted on the AST rather than on the word `except`, which
    appears in prose."""
    src = (API / "services" / "sales_cycle_service.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    handlers = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)]
    # Exactly one, and it is the ValueError the discount authority raises,
    # turned into a 422 rather than swallowed.
    assert len(handlers) == 1
    assert handlers[0].type is not None, "no bare except"
    body = ast.unparse(handlers[0])
    assert "HTTPException" in body and "pass" not in body


def test_the_models_validate_at_BOTH_doors():
    """A validator on create only is one PATCH away from being none, which is
    the shape ACC-25 and GST-29 both turned out to be."""
    from models import sales_cycle as m
    create_fields = set(m.DeliveryChallanIn.model_fields)
    update_fields = set(m.DeliveryChallanUpdateIn.model_fields)
    shared = create_fields & update_fields
    for field in ("document_no", "consignee_gstin", "place_of_supply",
                  "goods_kind"):
        assert field in shared
    src = inspect.getsource(m)
    # Both classes reach the same validators by name.
    assert src.count("_document_no(v)") >= 2
    assert src.count("return _gstin(v)") >= 4


def test_a_malformed_counterparty_gstin_is_refused_at_the_model():
    """GST-29's lesson on the document that BECOMES the invoice: a
    valid-shaped wrong GSTIN sends the credit to a stranger, correctable only
    by an amendment inside the s.37(3) window."""
    from pydantic import ValidationError
    from models.sales_cycle import QuotationIn
    good = {"client_id": "C1", "customer_id": "X1", "document_no": "QT/1",
            "document_date": "2026-04-01",
            "lines": [{"description": "W", "rate_paise": 100}]}
    QuotationIn(**{**good, "customer_gstin": "27AAPFU0939F1ZV"})
    with pytest.raises(ValidationError):
        # Right shape, wrong check digit.
        QuotationIn(**{**good, "customer_gstin": "27AAPFU0939F1ZZ"})


def test_a_document_number_the_invoice_series_would_reject_is_refused_now():
    """A quotation becomes an invoice. A number that cannot be a tax-invoice
    number is a conversion that fails at the last step — after the customer
    has the quotation."""
    from pydantic import ValidationError
    from models.sales_cycle import QuotationIn
    good = {"client_id": "C1", "customer_id": "X1",
            "document_date": "2026-04-01",
            "lines": [{"description": "W", "rate_paise": 100}]}
    QuotationIn(**{**good, "document_no": "QT/2026-27/0001"})
    for bad in ("QT#2026/0001", "A" * 17, "   "):
        with pytest.raises(ValidationError):
            QuotationIn(**{**good, "document_no": bad})


def test_the_two_state_fields_may_not_disagree():
    """SALES-31's rule, on the document that becomes the invoice."""
    from pydantic import ValidationError
    from models.sales_cycle import SalesOrderIn
    good = {"client_id": "C1", "customer_id": "X1", "document_no": "SO/1",
            "document_date": "2026-04-01",
            "lines": [{"description": "W", "rate_paise": 100}]}
    SalesOrderIn(**{**good, "place_of_supply": "27", "supply_state_code": "27"})
    with pytest.raises(ValidationError):
        SalesOrderIn(**{**good, "place_of_supply": "27",
                        "supply_state_code": "29"})


def test_a_quantity_beyond_three_decimals_is_refused_not_rounded():
    """Every quantity column is NUMERIC(10,3) and Postgres rounds a fourth
    decimal away silently — INV-09's rule, applied to the new documents."""
    from pydantic import ValidationError
    from models.sales_cycle import PreInvoiceLineIn
    PreInvoiceLineIn(description="W", quantity=1.234, rate_paise=100)
    with pytest.raises(ValidationError):
        PreInvoiceLineIn(description="W", quantity=1.2345, rate_paise=100)


def test_the_router_serves_the_vocabulary_so_no_screen_holds_statute():
    from routers import sales_cycle as r
    src = inspect.getsource(r)
    assert "def vocabulary" in src
    for token in ("not_a_tax_invoice", "challan_reasons", "goods_kinds",
                  "rule_55_5_steps", "copies", "itc_04"):
        assert token in src
