"""PUR-25 — purchase orders, goods receipts and the three-way match.

WHAT THE PRODUCT COULD NOT DO
    The purchase cycle started at the bill. A client raises a purchase order,
    receives the goods against it and only then books the supplier's invoice;
    neither of the first two documents existed, so there was nothing to check
    the bill against — a supplier who short-shipped or over-charged was paid in
    full unless somebody remembered.

    And, worse, no record at all of WHEN the goods arrived. That absence is
    statutory twice over:

      * CGST s.16(2)(b) allows the input tax credit only where the recipient
        has RECEIVED the goods. A March invoice for goods that arrive in April
        carries credit that belongs to April, and nothing could test it.
      * MSMED s.15 runs its fifteen days from the day of ACCEPTANCE, which
        s.2(b)'s Explanation makes the day of ACTUAL DELIVERY.
        `domain/income_tax/section_43b_h.py` has had to use the BILL date as a
        proxy and said so in a caveat on every answer — and the proxy is
        EARLIER, so it manufactures disallowances on bills paid in time.
"""
from __future__ import annotations

import ast
import inspect
import pathlib
from datetime import date
from decimal import Decimal

import pytest

from domain.income_tax import section_43b_h as s43
from domain.purchases import order_cycle as oc
from domain.purchases import three_way_match as twm

API = pathlib.Path(__file__).resolve().parent.parent


# ══════════════════════════════════════════════════════════════════════════
# 1. The commercial chain
# ══════════════════════════════════════════════════════════════════════════

def test_nothing_in_the_chain_posts_and_the_module_says_so():
    assert "posts a journal" in oc.POSTS_NOTHING
    assert "when the supplier's bill is received" in oc.POSTS_NOTHING


def test_received_and_billed_are_two_clocks_and_an_order_needs_both():
    """Goods arrive on a challan and the invoice follows a month later; a
    service is often billed before it is performed. An order tracking one
    figure would show a fully received order as open, or a fully billed one as
    never delivered — and the second matters, because s.16(2)(b) conditions
    the credit on RECEIPT and not on the bill."""
    lines = [{"id": "L1", "description": "Casting", "quantity": "10"}]
    out = oc.open_quantities(lines, {"L1": Decimal(4)}, {"L1": Decimal(9)})[0]
    assert out.unreceived_qty == Decimal(6)
    assert out.unbilled_qty == Decimal(1)
    d = out.as_dict()
    assert d["ordered_qty"] == "10.000" and isinstance(d["ordered_qty"], str)


def test_a_quantity_is_never_read_through_a_float():
    assert oc.to_decimal("1.005") == Decimal("1.005")
    assert oc.to_decimal(Decimal("2.5")) == Decimal("2.5")
    assert oc.to_decimal(None) == Decimal(0)


def test_over_receipt_is_REFUSED_and_says_what_to_do():
    """Goods on the premises in excess of what was ordered mean the ORDER is
    wrong. Clamping would take the ordered quantity in and lose the rest with
    no record of stock that physically exists."""
    line = oc.OpenLine("L1", "Casting", Decimal(10), Decimal(8), Decimal(0))
    assert oc.over_receipt(line, Decimal(2)) is None
    problem = oc.over_receipt(line, Decimal("2.001"))
    assert problem and "Amend the order" in problem
    assert oc.over_receipt(line, Decimal(0)), "a nil receipt is not a receipt"


def test_an_order_status_is_derived_but_a_closed_one_is_not_reopened():
    part = [oc.OpenLine("L1", "C", Decimal(10), Decimal(4), Decimal(0))]
    done = [oc.OpenLine("L1", "C", Decimal(10), Decimal(10), Decimal(0))]
    none = [oc.OpenLine("L1", "C", Decimal(10), Decimal(0), Decimal(0))]
    assert oc.order_status_for(part, "approved") == "partially_received"
    assert oc.order_status_for(done, "approved") == "received"
    assert oc.order_status_for(none, "approved") == "approved"
    assert oc.order_status_for(done, "closed") == "closed"
    assert oc.order_status_for(done, "cancelled") == "cancelled"
    assert oc.order_status_for(done, "draft") == "draft"


def test_a_conversion_carries_the_s17_5_decision_and_not_the_date():
    """`itc_eligible` and `expense_account_id` are decisions the CA made ONCE,
    on the order — the same reasoning migration 379's recurring template
    records. The DATE is not carried: an order raised in March and billed in
    April is an April bill, and carrying the date forward would date it into a
    year that may already be closed."""
    assert "itc_eligible" in oc.LINE_FIELDS_CARRIED
    assert "expense_account_id" in oc.LINE_FIELDS_CARRIED
    assert "tds_applicable" in oc.LINE_FIELDS_CARRIED
    assert "document_date" not in oc.HEADER_FIELDS_CARRIED
    assert "id" not in oc.LINE_FIELDS_CARRIED
    assert oc.carry_line({"description": "C", "rate_paise": 100, "id": "L1"}) \
        == {"description": "C", "rate_paise": 100}


def test_each_kind_has_its_own_series():
    assert oc.series_kind_of("purchase_order") != oc.series_kind_of("goods_receipt")
    with pytest.raises(ValueError):
        oc.series_kind_of("purchase_bill")


# ══════════════════════════════════════════════════════════════════════════
# 2. The three-way match
# ══════════════════════════════════════════════════════════════════════════

def _matched(**kw):
    base = dict(
        bill_id="B1",
        bill_lines=[{"id": "BL1", "description": "Casting", "quantity": "10",
                     "rate_paise": 10000, "order_line_id": "OL1"}],
        order_lines=[{"id": "OL1", "description": "Casting", "quantity": "10",
                      "rate_paise": 10000}],
        received_by_order_line={"OL1": Decimal(10)},
        receipt_dates=["2026-04-05"])
    base.update(kw)
    return twm.match(**base)


def test_a_clean_match_reports_no_difference():
    r = _matched()
    assert r.matched is True
    assert r.differences == []
    assert r.has_order and r.has_receipt


def test_billed_for_more_than_arrived_names_s16_2_b():
    """The credit on the excess is not available until the goods are received
    — that is the whole reason this comparison is statutory and not a control."""
    r = _matched(received_by_order_line={"OL1": Decimal(7)})
    assert r.matched is False
    assert any("s.16(2)(b)" in d for d in r.differences)
    assert any("3.000 more than arrived" in d for d in r.differences)


def test_received_and_not_yet_billed_is_reported_the_other_way_round():
    r = _matched(bill_lines=[{"id": "BL1", "description": "Casting",
                              "quantity": "6", "rate_paise": 10000,
                              "order_line_id": "OL1"}])
    assert any("received and not yet billed" in d for d in r.differences)
    # And it is NOT a s.16(2)(b) point: the goods are here, the bill is short.
    assert not any("s.16(2)(b)" in d for d in r.differences)


def test_a_rate_difference_is_reported_in_rupees_and_in_direction():
    over = _matched(bill_lines=[{"id": "BL1", "description": "Casting",
                                 "quantity": "10", "rate_paise": 11000,
                                 "order_line_id": "OL1"}])
    under = _matched(bill_lines=[{"id": "BL1", "description": "Casting",
                                  "quantity": "10", "rate_paise": 9000,
                                  "order_line_id": "OL1"}])
    assert any("Rs 10.00 above" in d for d in over.differences)
    assert any("Rs 10.00 below" in d for d in under.differences)


def test_no_tolerance_is_applied_and_every_answer_says_so():
    """'Within 2%' is a firm's procurement policy, not a rule. A tolerance
    written into the engine would silently pass a discrepancy somebody has to
    look at."""
    r = _matched(bill_lines=[{"id": "BL1", "description": "Casting",
                              "quantity": "10", "rate_paise": 10001,
                              "order_line_id": "OL1"}])
    assert r.differences, "a one-paisa difference is still a difference"
    assert twm.NO_TOLERANCE_IS_APPLIED in r.caveats


def test_a_bill_with_no_order_is_NOT_a_finding():
    """Most purchases a practice sees — fees, rent, utilities — are never
    ordered, and reporting each as unmatched would bury the ones that matter."""
    r = twm.match(bill_id="B1",
                  bill_lines=[{"id": "BL1", "description": "Audit fee",
                               "quantity": "1", "rate_paise": 5000000}])
    assert r.differences == []
    assert r.has_order is False
    assert any("never ordered" in g for g in r.gaps)


def test_an_order_with_no_receipt_names_the_bill_to_ship_to_proviso():
    """The first proviso to s.16(2) deems the recipient to have received goods
    delivered to a third party on their direction, and no column here holds
    whether an arrangement is one — so the absence is REPORTED rather than
    treated as an unmet condition."""
    r = _matched(received_by_order_line={}, receipt_dates=[])
    assert r.has_receipt is False
    assert twm.BILL_TO_SHIP_TO_NOT_MODELLED in r.gaps
    assert "bill to ship to" in twm.BILL_TO_SHIP_TO_NOT_MODELLED


def test_a_bill_line_naming_an_order_line_that_is_not_there_is_a_gap():
    r = _matched(bill_lines=[{"id": "BL1", "description": "Casting",
                              "quantity": "10", "rate_paise": 10000,
                              "order_line_id": "GHOST"}])
    assert any("not on this order" in g for g in r.gaps)


def test_the_match_BLOCKS_nothing_and_posts_nothing():
    """A supplier who short-ships has still sent a bill, and the CA still has
    to book what arrived. Refusing would push the entry outside the system,
    which is the one outcome worse than a mismatch nobody looked at."""
    d = _matched(received_by_order_line={"OL1": Decimal(1)}).as_dict()
    assert d["ca_review_required"] is True
    assert "blocked" not in d and "refused" not in d
    src = (API / "domain" / "purchases" / "three_way_match.py").read_text(
        encoding="utf-8")
    assert "HTTPException" not in src, (
        "the match module raises nothing — it reports")


# ── The MSMED s.2(b) acceptance date ─────────────────────────────────────

def test_acceptance_is_the_LAST_receipt_not_the_first():
    """A part-shipped order is accepted when the goods the bill covers have all
    arrived. Taking the earliest would start the clock before the supply was
    complete and report a disallowance on a bill paid in time."""
    day, why = twm.acceptance_date(["2026-04-05", "2026-04-20", "2026-04-12"])
    assert day == "2026-04-20"
    assert "LAST goods receipt" in why


def test_an_objection_REMOVED_displaces_the_delivery_date():
    """MSMED s.2(b), Explanation, second limb. It is LATER than delivery, so
    it lengthens the period and cannot manufacture a disallowance."""
    day, why = twm.acceptance_date(["2026-04-05"],
                                   objection_removed_on="2026-05-01")
    assert day == "2026-05-01"
    assert "second limb" in why


def test_no_receipt_returns_NONE_and_never_the_bill_date():
    """Substituting the bill date silently is what `section_43b_h` already does
    WITH A CAVEAT; doing it again here would hide that it happened."""
    day, why = twm.acceptance_date([])
    assert day is None
    assert "falls back to the bill date and says so" in why


def test_days_between_counts_CALENDAR_days():
    """MSMED s.2(b) counts fifteen DAYS, never months."""
    assert twm.days_between("2026-04-05", "2026-04-20") == 15
    assert twm.days_between(None, "2026-04-20") is None
    assert twm.days_between("nonsense", "2026-04-20") is None


# ══════════════════════════════════════════════════════════════════════════
# 3. s.43B(h) now runs from acceptance
# ══════════════════════════════════════════════════════════════════════════

def _bill(**kw):
    base = dict(bill_id="b1", bill_no="INV-1", vendor_id="v1",
                vendor_name="Acme Tools", msme_status="micro",
                bill_date=date(2025, 5, 1), total_paise=1_18_000,
                deductible_paise=1_00_000)
    base.update(kw)
    return s43.Bill(**base)


def test_the_acceptance_date_REMOVES_a_disallowance_the_proxy_manufactured():
    """Goods arrive after the invoice as often as before, so the real date is
    usually LATER — which lengthens the period. The proxy is the EARLIER date
    and therefore the LARGER disallowance."""
    settled = (s43.Payment(date(2025, 6, 2), 1_18_000),)
    on_proxy = s43.compute([_bill(payments=settled)], financial_year="2025-26")
    on_real = s43.compute(
        [_bill(payments=settled, acceptance_date=date(2025, 5, 20))],
        financial_year="2025-26")
    assert on_proxy.disallowed_paise == 1_00_000
    assert on_real.disallowed_paise == 0


def test_an_acceptance_date_can_never_CREATE_a_disallowance():
    """A receipt dated before the bill is possible — goods arrive, the invoice
    follows — and would SHORTEN the period. It is used as given rather than
    clamped, because the Act says acceptance and not "the later of"; the test
    exists so that behaviour is a decision somebody took rather than a
    surprise."""
    settled = (s43.Payment(date(2025, 5, 16), 1_18_000),)
    early = s43.compute(
        [_bill(payments=settled, acceptance_date=date(2025, 4, 25))],
        financial_year="2025-26")
    assert early.disallowed_paise == 1_00_000, (
        "a receipt dated before the bill shortens the period, as the Act's own "
        "words do")


def test_the_caveat_is_emitted_only_for_the_bills_that_used_the_proxy():
    assert s43.ACCEPTANCE_DATE_NOT_HELD in s43.compute(
        [_bill(payments=())], financial_year="2025-26").caveats
    assert s43.ACCEPTANCE_DATE_NOT_HELD not in s43.compute(
        [_bill(payments=(), acceptance_date=date(2025, 5, 20))],
        financial_year="2025-26").caveats


def test_the_working_says_WHICH_date_it_measured_from():
    proxied = s43.compute([_bill(payments=())],
                          financial_year="2025-26").bills[0]
    real = s43.compute([_bill(payments=(),
                              acceptance_date=date(2025, 5, 20))],
                       financial_year="2025-26").bills[0]
    assert "no goods receipt records the day of acceptance" in proxied.limit_source
    assert "day of acceptance, 2025-05-20" in real.limit_source


# ══════════════════════════════════════════════════════════════════════════
# 4. The service
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
            new = {"id": f"{self.table_name}-"
                         f"{len(self.store.setdefault(self.table_name, []))}",
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
        # COPIES, because PostgREST returns freshly decoded JSON.
        return type("R", (), {"data": [dict(r) for r in self._rows]})()


class _FakeDB:
    def __init__(self, **tables):
        self.store = {k: list(v) for k, v in tables.items()}

    def table(self, name):
        return _Q(self.store, name)


def _order_db():
    return _FakeDB(
        purchase_orders=[{
            "id": "O1", "firm_id": "F1", "client_id": "C1", "vendor_id": "V1",
            "document_no": "PO/1", "document_date": "2026-04-01",
            "status": "approved", "is_inter_state": False,
        }],
        purchase_order_lines=[
            {"id": "L1", "firm_id": "F1", "client_id": "C1", "order_id": "O1",
             "line_order": 0, "description": "Casting", "quantity": "10.000",
             "rate_paise": 10000},
            {"id": "L2", "firm_id": "F1", "client_id": "C1", "order_id": "O1",
             "line_order": 1, "description": "Bracket", "quantity": "5.000",
             "rate_paise": 20000},
        ],
        goods_receipt_notes=[], goods_receipt_lines=[],
        purchase_bills=[], purchase_bill_lines=[],
    )


def test_a_receipt_moves_the_order_to_partially_received_then_received():
    from services import purchase_cycle_service as svc
    db = _order_db()
    svc.create_receipt(db, "F1", {
        "client_id": "C1", "vendor_id": "V1", "document_no": "GRN/1",
        "received_on": "2026-04-05", "order_id": "O1",
        "lines": [{"description": "Casting", "quantity": 10,
                   "order_line_id": "L1"}]})
    assert db.store["purchase_orders"][0]["status"] == "partially_received"
    svc.create_receipt(db, "F1", {
        "client_id": "C1", "vendor_id": "V1", "document_no": "GRN/2",
        "received_on": "2026-04-09", "order_id": "O1",
        "lines": [{"description": "Bracket", "quantity": 5,
                   "order_line_id": "L2"}]})
    assert db.store["purchase_orders"][0]["status"] == "received"


def test_receiving_more_than_was_ordered_is_refused_before_anything_is_written():
    from fastapi import HTTPException
    from services import purchase_cycle_service as svc
    db = _order_db()
    with pytest.raises(HTTPException) as e:
        svc.create_receipt(db, "F1", {
            "client_id": "C1", "vendor_id": "V1", "document_no": "GRN/3",
            "received_on": "2026-04-05", "order_id": "O1",
            "lines": [{"description": "Casting", "quantity": 11,
                       "order_line_id": "L1"}]})
    assert e.value.status_code == 422
    assert "more than the" in str(e.value.detail)
    assert not db.store["goods_receipt_notes"]


def test_a_REJECTED_quantity_does_not_count_as_received():
    """s.16(2)(b) asks what was RECEIVED and MSMED s.2(b) what was ACCEPTED.
    Stock rejected on arrival was received and not accepted, and what the order
    still owes is measured on what was kept — so eight kept out of ten
    delivered leaves two outstanding, and a further two may be received."""
    from services import purchase_cycle_service as svc
    db = _order_db()
    svc.create_receipt(db, "F1", {
        "client_id": "C1", "vendor_id": "V1", "document_no": "GRN/4",
        "received_on": "2026-04-05", "order_id": "O1",
        "lines": [{"description": "Casting", "quantity": 10,
                   "rejected_qty": 2, "rejection_reason": "Cracked",
                   "order_line_id": "L1"}]})
    position = svc.order_open_position(db, "F1", "O1")
    line = next(ln for ln in position["lines"] if ln["order_line_id"] == "L1")
    assert line["received_qty"] == "8.000"
    assert line["unreceived_qty"] == "2.000"


def test_a_CANCELLED_receipt_has_received_nothing():
    from services import purchase_cycle_service as svc
    db = _order_db()
    svc.create_receipt(db, "F1", {
        "client_id": "C1", "vendor_id": "V1", "document_no": "GRN/5",
        "received_on": "2026-04-05", "order_id": "O1",
        "lines": [{"description": "Casting", "quantity": 10,
                   "order_line_id": "L1"}]})
    db.store["goods_receipt_notes"][0]["status"] = "cancelled"
    position = svc.order_open_position(db, "F1", "O1")
    line = next(ln for ln in position["lines"] if ln["order_line_id"] == "L1")
    assert line["received_qty"] == "0.000"


def test_another_firms_receipt_never_reaches_this_orders_position():
    from services import purchase_cycle_service as svc
    db = _order_db()
    db.store["goods_receipt_notes"].append({
        "id": "ZZ", "firm_id": "F2", "client_id": "C1", "status": "recorded",
        "document_no": "GRN/X", "received_on": "2026-04-05", "order_id": "O1"})
    db.store["goods_receipt_lines"].append({
        "id": "ZZL", "firm_id": "F2", "client_id": "C1", "receipt_id": "ZZ",
        "order_line_id": "L1", "quantity": "10.000", "rejected_qty": "0.000",
        "line_order": 0, "description": "Casting"})
    position = svc.order_open_position(db, "F1", "O1")
    line = next(ln for ln in position["lines"] if ln["order_line_id"] == "L1")
    assert line["received_qty"] == "0.000"


#: Tables with no `firm_id` of their own, scoped through their parent instead.
#: Each entry needs the parent read, in the same function, to carry the filter
#: — which `test_the_parent_read_carries_the_filter_the_child_cannot` asserts.
SCOPED_THROUGH_A_PARENT = {"purchase_bill_lines"}


def test_the_parent_read_carries_the_filter_the_child_cannot():
    """The exemption above is only safe if the PARENT is filtered. A line
    survives into the billed figure solely because its bill is in `live_bills`,
    and that set is built from a firm-filtered read."""
    src = (API / "services" / "purchase_cycle_service.py").read_text(
        encoding="utf-8")
    assert '.select("id, status").eq("firm_id", firm_id)\n' in src or (
        '.select("id, status").eq("firm_id", firm_id)' in src), (
        "the purchase_bills parent read lost its firm filter")
    assert "live_bills" in src
    assert 'if str(r.get("bill_id")) not in live_bills:' in src, (
        "a bill line is counted without checking its parent is this firm's")


def test_EVERY_read_and_write_in_the_service_carries_the_firm_filter():
    """The service-role key bypasses RLS, so `.eq("firm_id", …)` is the primary
    isolation control rather than a narrowing convenience — CLAUDE.md: "Never
    write a query that omits it". Stated as the rule and not as one scenario:
    a filter dropped on a read whose rows are later discarded still crosses the
    tenant boundary, and no behavioural assertion can see that."""
    tree = ast.parse((API / "services" / "purchase_cycle_service.py")
                     .read_text(encoding="utf-8"))
    missing: list = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "table"):
            continue
        chain = ast.unparse(_outermost_chain(tree, node))
        table = (node.args[0].value if node.args
                 and isinstance(node.args[0], ast.Constant) else "?")
        if table in SCOPED_THROUGH_A_PARENT:
            # `purchase_bill_lines` carries NO firm_id — it is scoped through
            # its parent bill, and the parent read in the same function does
            # carry the filter. Naming the column here would be PGRST204 and
            # NO read, which the real-Postgres column check catches; this
            # exemption is NAMED so the two guards cannot both be satisfied by
            # dropping the tenant check altogether.
            continue
        if ".insert(" in chain:
            scoped = "'firm_id'" in chain
        else:
            scoped = "eq('firm_id'" in chain or 'eq("firm_id"' in chain
        if not scoped:
            missing.append(f"{table}: {chain[:110]}")
    assert not missing, (
        "these queries omit the firm filter:\n" + "\n".join(missing))


def _outermost_chain(tree: ast.AST, target: ast.Call) -> ast.AST:
    best = target
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Call, ast.Attribute)) or node is target:
            continue
        if any(child is target for child in ast.walk(node)):
            if len(ast.unparse(node)) > len(ast.unparse(best)):
                best = node
    return best


def test_the_acceptance_date_fetch_is_per_CLIENT_and_not_per_bill():
    """`msme_43bh_service` walks every live bill, and a per-bill lookup would
    be a Singapore-to-Mumbai round trip each. What crosses the wire is
    proportional to the ANSWER (CLAUDE.md, "Reporting performance")."""
    from services import purchase_cycle_service as svc
    sig = inspect.signature(svc.acceptance_dates_by_bill)
    assert set(sig.parameters) == {"db", "firm_id", "client_id"}
    db = _order_db()
    db.store["purchase_bills"] = [
        {"id": "B1", "firm_id": "F1", "client_id": "C1",
         "purchase_order_id": "O1"},
        {"id": "B2", "firm_id": "F1", "client_id": "C1",
         "purchase_order_id": None},
    ]
    db.store["goods_receipt_notes"] = [
        {"id": "G1", "firm_id": "F1", "client_id": "C1", "order_id": "O1",
         "received_on": "2026-04-05", "status": "recorded"},
        {"id": "G2", "firm_id": "F1", "client_id": "C1", "order_id": "O1",
         "received_on": "2026-04-20", "status": "recorded"},
    ]
    out = svc.acceptance_dates_by_bill(db, "F1", "C1")
    assert out == {"B1": "2026-04-20"}, "the LAST receipt, and only for a bill"


def test_a_cancelled_receipt_supplies_no_acceptance_date():
    from services import purchase_cycle_service as svc
    db = _order_db()
    db.store["purchase_bills"] = [
        {"id": "B1", "firm_id": "F1", "client_id": "C1",
         "purchase_order_id": "O1"}]
    db.store["goods_receipt_notes"] = [
        {"id": "G1", "firm_id": "F1", "client_id": "C1", "order_id": "O1",
         "received_on": "2026-04-05", "status": "cancelled"}]
    assert svc.acceptance_dates_by_bill(db, "F1", "C1") == {}


def test_an_objection_removal_wins_over_the_delivery_date_in_the_fetch_too():
    from services import purchase_cycle_service as svc
    db = _order_db()
    db.store["purchase_bills"] = [
        {"id": "B1", "firm_id": "F1", "client_id": "C1",
         "purchase_order_id": "O1"}]
    db.store["goods_receipt_notes"] = [
        {"id": "G1", "firm_id": "F1", "client_id": "C1", "order_id": "O1",
         "received_on": "2026-04-05", "status": "recorded",
         "objection_removed_on": "2026-05-02"}]
    assert svc.acceptance_dates_by_bill(db, "F1", "C1") == {"B1": "2026-05-02"}


def test_two_documents_may_not_bear_one_number():
    from fastapi import HTTPException
    from services import purchase_cycle_service as svc
    db = _order_db()
    payload = {"client_id": "C1", "vendor_id": "V1", "document_no": "PO/9",
               "document_date": "2026-04-01",
               "lines": [{"description": "C", "quantity": 1,
                          "rate_paise": 1000, "gst_rate_percent": 18}]}
    svc.create_order(db, "F1", payload)
    with pytest.raises(HTTPException) as e:
        svc.create_order(db, "F1", dict(payload))
    assert e.value.status_code == 409
    with pytest.raises(HTTPException):
        svc.create_order(db, "F1", {**payload, "document_no": "po/9"})


def test_the_order_computes_the_same_gst_the_invoice_path_does():
    from domain.sales.line_tax import compute_line_gst
    from services import purchase_cycle_service as svc
    priced, totals = svc.compute_lines(
        [{"description": "C", "quantity": 3, "rate_paise": 33333,
          "gst_rate_percent": 18}], is_inter_state=False)
    assert (priced[0]["cgst_paise"], priced[0]["sgst_paise"],
            priced[0]["igst_paise"]) == compute_line_gst(99999, 1800, False)
    assert totals["taxable_paise"] == 99999


def test_the_gross_is_quantity_times_rate_in_DECIMAL_never_a_float():
    from services import purchase_cycle_service as svc
    priced, _ = svc.compute_lines(
        [{"description": "Cable", "quantity": "1.005", "rate_paise": 10000,
          "gst_rate_percent": 18}], is_inter_state=False)
    assert priced[0]["taxable_amount_paise"] == 10050


def test_an_order_with_a_receipt_against_it_keeps_its_lines():
    from fastapi import HTTPException
    from services import purchase_cycle_service as svc
    db = _order_db()
    svc.update_order(db, "F1", "O1", {"notes": "chased"})
    svc.create_receipt(db, "F1", {
        "client_id": "C1", "vendor_id": "V1", "document_no": "GRN/6",
        "received_on": "2026-04-05", "order_id": "O1",
        "lines": [{"description": "Casting", "quantity": 1,
                   "order_line_id": "L1"}]})
    with pytest.raises(HTTPException) as e:
        svc.update_order(db, "F1", "O1", {
            "lines": [{"description": "Casting", "quantity": 99,
                       "rate_paise": 100, "gst_rate_percent": 18}]})
    assert e.value.status_code == 409
    assert "over-receipt" in str(e.value.detail)


def test_removing_an_objection_that_was_never_raised_is_refused_at_BOTH_doors():
    """A validator on one door is one PATCH away from being none."""
    from fastapi import HTTPException
    from pydantic import ValidationError
    from models.purchase_cycle import GoodsReceiptIn
    from services import purchase_cycle_service as svc
    with pytest.raises(ValidationError):
        GoodsReceiptIn(client_id="C1", vendor_id="V1", document_no="G/1",
                       received_on="2026-04-05",
                       objection_removed_on="2026-05-01",
                       lines=[{"description": "C"}])
    db = _order_db()
    svc.create_receipt(db, "F1", {
        "client_id": "C1", "vendor_id": "V1", "document_no": "GRN/7",
        "received_on": "2026-04-05",
        "lines": [{"description": "Casting", "quantity": 1}]})
    rid = db.store["goods_receipt_notes"][0]["id"]
    with pytest.raises(HTTPException) as e:
        svc.update_receipt(db, "F1", rid, {"objection_removed_on": "2026-05-01"})
    assert e.value.status_code == 422
    assert "there has to be an objection" in str(e.value.detail)


def test_an_objection_removed_before_it_was_raised_is_refused():
    from fastapi import HTTPException
    from services import purchase_cycle_service as svc
    db = _order_db()
    svc.create_receipt(db, "F1", {
        "client_id": "C1", "vendor_id": "V1", "document_no": "GRN/8",
        "received_on": "2026-04-05",
        "lines": [{"description": "Casting", "quantity": 1}]})
    rid = db.store["goods_receipt_notes"][0]["id"]
    with pytest.raises(HTTPException):
        svc.update_receipt(db, "F1", rid, {
            "objection_raised_on": "2026-04-10",
            "objection_removed_on": "2026-04-08"})


def test_more_rejected_than_arrived_is_refused_at_the_model():
    from pydantic import ValidationError
    from models.purchase_cycle import GoodsReceiptLineIn
    GoodsReceiptLineIn(description="C", quantity=10, rejected_qty=10)
    with pytest.raises(ValidationError):
        GoodsReceiptLineIn(description="C", quantity=10, rejected_qty=10.001)


def test_a_quantity_beyond_three_decimals_is_refused_not_rounded():
    from pydantic import ValidationError
    from models.purchase_cycle import GoodsReceiptLineIn, PurchaseOrderLineIn
    PurchaseOrderLineIn(description="C", quantity=1.234, rate_paise=100)
    with pytest.raises(ValidationError):
        PurchaseOrderLineIn(description="C", quantity=1.2345, rate_paise=100)
    with pytest.raises(ValidationError):
        GoodsReceiptLineIn(description="C", quantity=1, rejected_qty=0.2345)


def test_a_malformed_vendor_gstin_is_refused_at_the_model():
    from pydantic import ValidationError
    from models.purchase_cycle import PurchaseOrderIn
    good = {"client_id": "C1", "vendor_id": "V1", "document_no": "PO/1",
            "document_date": "2026-04-01",
            "lines": [{"description": "C", "rate_paise": 100}]}
    PurchaseOrderIn(**{**good, "vendor_gstin": "27AAPFU0939F1ZV"})
    with pytest.raises(ValidationError):
        PurchaseOrderIn(**{**good, "vendor_gstin": "27AAPFU0939F1ZZ"})


# ══════════════════════════════════════════════════════════════════════════
# 5. The rules that must not be broken later
# ══════════════════════════════════════════════════════════════════════════

_FOUR_TABLES = ("purchase_orders", "purchase_order_lines",
                "goods_receipt_notes", "goods_receipt_lines")


def _referenced_names(path: pathlib.Path) -> set:
    """Every identifier and string literal the module's CODE uses — AST, not a
    substring scan, so a docstring that NAMES the forbidden thing to say it is
    absent cannot satisfy or defeat the guard."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
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


def test_neither_document_posts_a_journal_or_moves_stock():
    """The expense, the input credit and the payable all arise when the BILL is
    received. And INV-05a costs a receipt at the BILL's taxable value, so
    moving stock here would cost it at a price the supplier has not yet
    invoiced — or move it twice."""
    names = _referenced_names(API / "services" / "purchase_cycle_service.py")
    for forbidden in ("_create_journal", "journal_entries", "journal_lines",
                      "inventory_stock_ledger", "apply_purchase_to_inventory",
                      "apply_stock_adjustment", "phase2_journal_service",
                      "inventory_service"):
        assert forbidden not in names, (
            f"{forbidden} reached the pre-bill service — neither document "
            f"posts to the ledger or moves stock")


def test_no_return_builder_reads_any_of_the_four_tables():
    """A purchase order is not a supply and a goods receipt is not a document
    the Act knows. GSTR-3B's Table 4 is built from BILLS."""
    offenders: list = []
    for name in ("services/gst_return_service.py",
                 "services/gstr9_service.py",
                 "services/gst_2b_reconciliation_service.py",
                 "domain/gst/gstr3b_computer.py",
                 "domain/gst/gstr9_builder.py"):
        path = API / name
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8")
        for table in _FOUR_TABLES:
            if table in src:
                offenders.append(f"{name} reads {table}")
    assert not offenders, "\n".join(offenders)


def _sql_only(text: str) -> str:
    """The statements, with the comments stripped. A guard that reads the whole
    file passes on a migration whose HEADER merely mentions the thing it is
    meant to assert."""
    return "\n".join(line for line in text.splitlines()
                     if not line.strip().startswith("--"))


def test_the_migration_states_every_rule_the_schema_has_to_carry():
    sql = _sql_only((API / "migrations" /
                     "393_the_purchase_cycle_before_the_bill.sql")
                    .read_text(encoding="utf-8"))
    # The date both statutes turn on is REQUIRED.
    assert "received_on    DATE NOT NULL" in sql
    # The objection is the Explanation's second limb and is ordered.
    assert "goods_receipt_notes_objection_order" in sql
    # A rejection cannot exceed what arrived.
    assert "goods_receipt_lines_rejected_within_received" in sql
    # Nothing stored that is derivable.
    assert "received_qty" not in sql
    assert "billed_qty" not in sql
    # And no journal anywhere near these tables.
    assert "journal_entry_id" not in sql
    # The bill's link back, nullable with no backfill.
    assert "purchase_order_line_id UUID" in sql
    assert "UPDATE public.purchase_bill_lines" not in sql, (
        "an existing bill predates this column; filling it in would be a guess")


def test_every_new_table_is_assignment_scoped_and_read_only_from_the_browser():
    sql = _sql_only((API / "migrations" /
                     "393_the_purchase_cycle_before_the_bill.sql")
                    .read_text(encoding="utf-8"))
    assert "_assignment_scope" in sql
    assert "can_access_client" in sql
    assert "GRANT SELECT ON public.%1$I TO authenticated" in sql
    for table in _FOUR_TABLES:
        assert f"'{table}'" in sql, f"{table} is not in the policy loop"


def test_the_rollback_refuses_while_a_goods_receipt_exists():
    """Without it s.43B(h) falls back to the earlier BILL date, turning bills
    paid in time into disallowances with nothing saying the date moved."""
    sql = _sql_only((API / "migrations" /
                     "393_the_purchase_cycle_before_the_bill_rollback.sql")
                    .read_text(encoding="utf-8"))
    assert "RAISE EXCEPTION" in sql
    assert "goods_receipt_notes" in sql
    assert "status <> 'cancelled'" in sql


def test_the_service_swallows_nothing_around_a_write():
    src = (API / "services" / "purchase_cycle_service.py").read_text(
        encoding="utf-8")
    handlers = [n for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.ExceptHandler)]
    assert len(handlers) == 1
    assert handlers[0].type is not None, "no bare except"
    assert "HTTPException" in ast.unparse(handlers[0])


def test_the_router_serves_the_statutory_sentences():
    from routers import purchase_cycle as r
    src = inspect.getsource(r)
    assert "def vocabulary" in src
    for token in ("section_16_2_b", "bill_to_ship_to", "msmed_acceptance",
                  "no_tolerance", "posts_nothing"):
        assert token in src
