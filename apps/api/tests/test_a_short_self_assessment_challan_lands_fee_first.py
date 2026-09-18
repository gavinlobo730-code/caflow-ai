"""§140A self-assessment tax, and the order a short payment lands in (IT-13).

WHAT WAS MISSING
    §140A(1) makes the tax, interest and fee on a return payable BEFORE the
    return is furnished and requires the return to be "accompanied by proof of
    payment". That proof is a Challan 280, and nothing in this product recorded
    one: Schedule IT was keyed off a bank receipt, and the ITR keying sheet
    (IT-17) printed §140A as a structural nil with a sentence saying why.

WHAT THIS MODULE HOLDS
    The appropriation order, which is the only arithmetic in the domain module
    and the one thing a reader would plausibly get wrong; that the challan's own
    five boxes do NOT drive it; the three-state absence of the dues; and the
    reachability half — the endpoints, the screen, and the keying sheet's two
    different sentences about where its §140A figure came from.
"""
from __future__ import annotations

import re
import inspect
import pathlib

import pytest

from domain.income_tax import self_assessment as sa


# ── §140A(1)'s Explanation ───────────────────────────────────────────────────

def test_a_full_payment_settles_every_head():
    a = sa.appropriate(paid_paise=97_000_00, tax_due_paise=80_000_00,
                       interest_due_paise=12_000_00, fee_due_paise=5_000_00)
    assert a.is_fully_paid
    assert (a.towards_fee_paise, a.towards_interest_paise, a.towards_tax_paise) \
        == (5_000_00, 12_000_00, 80_000_00)
    assert a.tax_outstanding_paise == 0


def test_a_short_payment_settles_the_fee_first_then_the_interest():
    """NOT pro rata. ₹50,000 against ₹80,000 tax + ₹12,000 interest + ₹5,000
    fee clears the fee and the interest in full and leaves ₹47,000 of TAX
    outstanding — which is the figure §234A and §234B go on charging on.

    A proportional split would put ₹41,237 towards the tax and report ₹38,763
    outstanding, understating what is still owed by over eight thousand rupees
    and understating the interest still running with it."""
    a = sa.appropriate(paid_paise=50_000_00, tax_due_paise=80_000_00,
                       interest_due_paise=12_000_00, fee_due_paise=5_000_00)
    assert a.towards_fee_paise == 5_000_00
    assert a.towards_interest_paise == 12_000_00
    assert a.towards_tax_paise == 33_000_00
    assert a.tax_outstanding_paise == 47_000_00
    assert not a.is_fully_paid


def test_a_payment_smaller_than_the_fee_reaches_neither_interest_nor_tax():
    a = sa.appropriate(paid_paise=2_000_00, tax_due_paise=80_000_00,
                       interest_due_paise=12_000_00, fee_due_paise=5_000_00)
    assert a.towards_fee_paise == 2_000_00
    assert a.towards_interest_paise == 0 and a.towards_tax_paise == 0
    assert a.fee_outstanding_paise == 3_000_00
    assert a.tax_outstanding_paise == 80_000_00


def test_an_overpayment_is_not_spread_and_the_excess_simply_does_not_appear():
    """Where the excess goes is the assessment's business (§143(1)), not this
    return's. Reporting a negative outstanding would read as a credit."""
    a = sa.appropriate(paid_paise=1_00_000_00, tax_due_paise=10_000_00)
    assert a.towards_tax_paise == 10_000_00
    assert a.total_applied_paise == 10_000_00
    assert a.tax_outstanding_paise == 0 and a.is_fully_paid


def test_nothing_paid_leaves_every_head_exactly_where_it_was():
    a = sa.appropriate(paid_paise=0, tax_due_paise=80_000_00,
                       interest_due_paise=12_000_00, fee_due_paise=5_000_00)
    assert a.total_applied_paise == 0
    assert (a.fee_outstanding_paise, a.interest_outstanding_paise,
            a.tax_outstanding_paise) == (5_000_00, 12_000_00, 80_000_00)


def test_the_challans_own_split_does_not_bind_the_appropriation():
    """The Explanation overrides the payer's own labelling — that is what it
    is for. Two clients pay ₹50,000 on the same day against the same dues and
    label the boxes differently; the outstanding TAX must be the same, or a
    mis-typed box would change §234A and §234B interest on identical money."""
    labelled_as_tax = [{"challan_serial_no": "1", "total_paise": 50_000_00,
                        "tax_paise": 50_000_00}]
    labelled_as_interest = [{"challan_serial_no": "1", "total_paise": 50_000_00,
                             "interest_paise": 50_000_00}]
    dues = dict(tax_due_paise=80_000_00, interest_due_paise=12_000_00,
                fee_due_paise=5_000_00)
    one = sa.position(financial_year="2025-26", challans=labelled_as_tax, **dues)
    two = sa.position(financial_year="2025-26", challans=labelled_as_interest, **dues)
    assert one.appropriation is not None and two.appropriation is not None
    assert one.appropriation.to_dict() == two.appropriation.to_dict()
    assert one.appropriation.tax_outstanding_paise == 47_000_00


def test_the_appropriation_reads_no_challan_row_at_all():
    """Stated as the RULE, not as a spelling of it. `appropriate` takes four
    scalars and must never reach into a challan row — a future reader adding
    `c["tax_paise"]` would pass the equality test above for one fixture and
    break the rule for the next.

    Written against the AST because the obvious string check is vacuous: the
    function's own OUTPUT fields are called `towards_tax_paise` and
    `tax_outstanding_paise`, so a scan for "tax_paise" fails on correct code.
    That is the guard-names-a-spelling shape this repository keeps finding."""
    import ast
    tree = ast.parse(inspect.getsource(sa.appropriate).strip())
    fn = tree.body[0]
    assert [a.arg for a in fn.args.kwonlyargs] == [
        "paid_paise", "tax_due_paise", "interest_due_paise", "fee_due_paise"]
    assert not fn.args.args, "the four figures are the whole input"
    for node in ast.walk(fn):
        assert not isinstance(node, ast.Subscript), ast.dump(node)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr != "get", ast.dump(node)


# ── §140A(1)'s own tax figure ────────────────────────────────────────────────

def test_the_tax_payable_is_net_of_every_credit_the_section_names():
    assert sa.tax_payable_on_return(
        tax_on_total_income_paise=2_00_000_00, tds_tcs_paise=60_000_00,
        advance_tax_paid_paise=50_000_00, relief_paise=10_000_00,
        mat_amt_credit_paise=5_000_00) == 75_000_00


def test_more_credit_than_tax_is_a_refund_and_floors_at_nil():
    """A negative "tax payable" would appropriate a payment against it and
    report a credit as settled. The refund is §143(1)'s business."""
    assert sa.tax_payable_on_return(
        tax_on_total_income_paise=10_000_00, tds_tcs_paise=40_000_00) == 0


def test_the_section_140a_figure_is_served_beside_the_interest():
    """It is the API's, not the screen's: the panel passes it straight through
    rather than subtracting TDS and advance tax in the browser."""
    import routers.income_tax as r
    src = inspect.getsource(r.compute_234ab_interest)
    assert "section_140a_tax_due_paise" in src
    assert "tax_payable_on_return" in src


# ── the position, and what it refuses ────────────────────────────────────────

_CHALLAN = {
    "id": "ch1", "challan_serial_no": "00123", "bsr_code": "0510308",
    "deposit_date": "2026-07-28", "total_paise": 50_000_00,
    "tax_paise": 50_000_00, "minor_head": "300",
}


def test_with_no_tax_due_nothing_is_appropriated_and_the_absence_is_named():
    p = sa.position(financial_year="2025-26", challans=[dict(_CHALLAN)])
    assert p.appropriation is None
    assert p.total_paid_paise == 50_000_00
    assert any("nothing is appropriated" in g for g in p.gaps)


def test_a_challan_under_the_wrong_minor_head_is_named():
    row = dict(_CHALLAN, minor_head=sa.MINOR_HEAD_ADVANCE_TAX)
    p = sa.position(financial_year="2025-26", challans=[row])
    assert any("minor head other than" in g for g in p.gaps)


def test_a_split_that_does_not_foot_is_reported_and_neither_figure_moves():
    row = dict(_CHALLAN, total_paise=50_000_00, tax_paise=40_000_00,
               interest_paise=5_000_00)
    p = sa.position(financial_year="2025-26", challans=[row],
                    tax_due_paise=60_000_00)
    assert any("add up to" in g for g in p.gaps)
    # The TOTAL is what §140A appropriates and what Schedule IT declares.
    assert p.total_paid_paise == 50_000_00
    assert p.appropriation is not None
    assert p.appropriation.towards_tax_paise == 50_000_00


def test_a_challan_recording_only_its_total_is_not_a_mismatch():
    """A bank receipt showing only what left the account is exactly the case
    the table exists to keep recordable."""
    row = {"challan_serial_no": "7", "total_paise": 50_000_00, "minor_head": "300"}
    p = sa.position(financial_year="2025-26", challans=[row])
    assert not any("add up to" in g for g in p.gaps)


def test_an_unpaid_balance_names_section_140a_3_and_never_scores_it():
    p = sa.position(financial_year="2025-26", challans=[dict(_CHALLAN)],
                    tax_due_paise=80_000_00)
    joined = " ".join(p.gaps)
    assert "§140A(3)" in joined and "assessee in default" in joined
    assert "§221" in joined
    assert "discretion, not a formula" in joined


def test_the_interest_is_never_derived_here_and_the_answer_says_so():
    p = sa.position(financial_year="2025-26", challans=[dict(_CHALLAN)],
                    tax_due_paise=80_000_00)
    assert any("§234F is not modelled" in c for c in p.caveats)
    assert any("not read off the Act" in c for c in p.caveats)
    assert p.to_dict()["verified"] is False


def test_no_interest_engine_is_restated_in_this_module():
    """§234A/B/C are `advance_tax_interest_engine`'s. A rate here would be a
    second engine that agrees with the first until it does not."""
    src = pathlib.Path(inspect.getfile(sa)).read_text(encoding="utf-8")
    for rate in ("234A", "234B", "234C"):
        assert f"compute_{rate.lower()}" not in src
    assert "_INTEREST_RATE" not in src


# ── the doors ────────────────────────────────────────────────────────────────

def test_the_three_endpoints_are_mounted_and_client_scoped():
    import routers.income_tax as r
    paths = {(tuple(sorted(x.methods)), x.path) for x in r.router.routes
             if "self-assessment" in getattr(x, "path", "")}
    assert (("GET",), "/api/income-tax/self-assessment") in paths
    assert (("POST",), "/api/income-tax/self-assessment") in paths
    assert (("DELETE",), "/api/income-tax/self-assessment/{challan_id}") in paths
    for fn in (r.list_self_assessment_challans, r.create_self_assessment_challan,
               r.delete_self_assessment_challan):
        assert "assert_client_access" in inspect.getsource(fn), fn.__name__


def test_the_delete_resolves_the_client_off_the_row_and_not_the_request():
    """A challan id alone must not authorise a read of somebody else's client,
    and the firm filter is the primary isolation control."""
    import routers.income_tax as r
    src = inspect.getsource(r.delete_self_assessment_challan)
    before = src.index('assert_client_access')
    assert src.index('.select("id, client_id")') < before
    assert src.count('.eq("firm_id", current_user["firm_id"])') >= 2


@pytest.mark.parametrize("bad", ["051030", "05103088", "05103O8", "", "abcdefg"])
def test_a_bsr_code_that_is_not_seven_digits_is_refused(bad):
    from pydantic import ValidationError
    import routers.income_tax as r
    with pytest.raises(ValidationError):
        r.SelfAssessmentChallanIn(
            client_id="c1", financial_year="2025-26", bsr_code=bad,
            deposit_date="2026-07-28", challan_serial_no="00123",
            total_paise=50_000_00)


@pytest.mark.parametrize("field,bad", [
    ("major_head", "0022"), ("minor_head", "200"),
])
def test_a_head_outside_challan_280s_own_vocabulary_is_refused(field, bad):
    from pydantic import ValidationError
    import routers.income_tax as r
    kw = dict(client_id="c1", financial_year="2025-26", bsr_code="0510308",
              deposit_date="2026-07-28", challan_serial_no="00123",
              total_paise=50_000_00)
    kw[field] = bad
    with pytest.raises(ValidationError):
        r.SelfAssessmentChallanIn(**kw)


def test_a_well_formed_challan_defaults_to_self_assessment_tax():
    import routers.income_tax as r
    c = r.SelfAssessmentChallanIn(
        client_id="c1", financial_year="2025-26", bsr_code=" 0510308 ",
        deposit_date="2026-07-28", challan_serial_no=" 00123 ",
        total_paise=50_000_00)
    assert c.bsr_code == "0510308" and c.challan_serial_no == "00123"
    assert c.minor_head == sa.MINOR_HEAD_SELF_ASSESSMENT
    assert c.major_head == sa.MAJOR_HEAD_OTHER


# ── the service ──────────────────────────────────────────────────────────────

class _DB:
    """Minimal PostgREST double — records the filters and returns the rows."""

    def __init__(self, rows):
        self._rows = rows
        self.filters: dict = {}
        self.projection = ""
        self.inserted: list = []

    def table(self, name):
        assert name == "self_assessment_challans", name
        self.filters = {}
        return self

    def select(self, expr):
        self.projection = expr
        return self

    def insert(self, row):
        self.inserted.append(row)
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def order(self, col):
        self.filters.setdefault("_order", []).append(col)
        return self

    def limit(self, n):
        return self

    def execute(self):
        return type("R", (), {"data": list(self._rows)})()


def test_the_service_filters_on_the_firm_the_client_and_the_year():
    from services import self_assessment_service as svc
    db = _DB([dict(_CHALLAN)])
    svc.list_challans(db, firm_id="F1", client_id="C1", financial_year="2025-26")
    assert db.filters["firm_id"] == "F1"
    assert db.filters["client_id"] == "C1"
    assert db.filters["financial_year"] == "2025-26"


def test_the_projection_names_minor_head_or_the_wrong_head_check_is_a_no_op():
    """The `is_opening` trap: the position reads the key off the ROW, so a
    narrow select that omits it makes the check silently pass.

    Read off the function's own source because the projection is a LITERAL at
    the call site — a module constant would be invisible to
    `test_backend_columns_exist_pg`, which checks every `.select()` as a
    string."""
    from services import self_assessment_service as svc
    src = inspect.getsource(svc.list_challans)
    body = src[src.index('.select('):]
    for column in ("minor_head", "major_head", "total_paise",
                   "challan_serial_no", "bsr_code", "deposit_date",
                   "tax_paise", "surcharge_paise", "cess_paise",
                   "interest_paise", "fee_paise"):
        assert column in body, column


def test_the_service_orders_by_the_deposit_date_not_by_when_it_was_typed():
    """§140A's appropriation walks the payments as they were MADE. A CA
    entering an old receipt after a recent one must not change what settled
    first."""
    from services import self_assessment_service as svc
    db = _DB([])
    svc.list_challans(db, firm_id="F1", client_id="C1", financial_year="2025-26")
    assert db.filters["_order"] == ["deposit_date", "challan_serial_no"]


def test_the_challan_total_has_exactly_one_definition():
    """It was about to have three — the domain module's `position`, the
    service, and the keying-sheet endpoint — each summing `total_paise` by
    hand. `sum()` is the cheapest thing in the world to write twice, and two
    of them agree until somebody decides a voided challan should not count."""
    from services import self_assessment_service as svc
    assert svc.total_paise_of is sa.total_paise_of
    for module, fn in ((svc, svc.list_challans), (svc, svc.total_paid_paise)):
        assert "sum(" not in inspect.getsource(fn), fn.__name__
    import routers.itr_workspace as w
    assert "total_paise_of" in inspect.getsource(w.filing_keying_sheet)
    assert 'int(c.get("total_paise")' not in inspect.getsource(w.filing_keying_sheet)


def test_the_total_is_the_whole_challan_and_not_its_tax_box():
    """Schedule IT's Amount column is what left the bank account."""
    from services import self_assessment_service as svc
    rows = [{"total_paise": 50_000_00, "tax_paise": 30_000_00,
             "interest_paise": 20_000_00, "minor_head": "300"}]
    db = _DB(rows)
    assert svc.total_paid_paise(
        db, firm_id="F1", client_id="C1", financial_year="2025-26") == 50_000_00


def test_no_database_answers_an_empty_position_rather_than_raising():
    from services import self_assessment_service as svc
    out = svc.position(None, firm_id="F1", client_id="C1",
                       financial_year="2025-26")
    assert out["challans"] == [] and out["total_paid_paise"] == 0


# ── the keying sheet's §140A line (IT-17's other half) ───────────────────────

def _computation():
    return {"income": {"gross_total_paise": 10_00_000_00,
                       "total_deductions_paise": 1_50_000_00,
                       "taxable_income_paise": 8_50_000_00},
            "tax": {"tax_before_cess_paise": 82_500_00, "total_tax_paise": 85_800_00}}


def test_with_no_challan_the_sheet_says_nothing_records_one():
    from domain.income_tax import keying_sheet as ks
    sheet = ks.keying_sheet(form="ITR-2", assessment_year="2026-27",
                            computation=_computation())
    assert ks.SELF_ASSESSMENT_TAX_HAS_NO_SOURCE in sheet["gaps"]
    by_key = {p["key"]: p for p in sheet["placements"]}
    assert by_key["self_assessment_tax"]["amount_rupees"] == 0


def test_with_challans_the_sheet_carries_their_total_and_says_where_it_came_from():
    from domain.income_tax import keying_sheet as ks
    sheet = ks.keying_sheet(form="ITR-2", assessment_year="2026-27",
                            computation=_computation(),
                            self_assessment_tax_paise=50_000_00,
                            self_assessment_challan_count=2)
    by_key = {p["key"]: p for p in sheet["placements"]}
    assert by_key["self_assessment_tax"]["amount_rupees"] == 50_000
    assert ks.SELF_ASSESSMENT_TAX_HAS_NO_SOURCE not in sheet["gaps"]
    assert any("2 Challan 280 record(s)" in g for g in sheet["gaps"])


def test_a_challan_recorded_for_nil_is_still_a_challan():
    """The two sentences are told apart by the COUNT, never by the amount — a
    sheet reading "no challan is recorded" over a record somebody entered is
    the kind of wrong that survives a review."""
    from domain.income_tax import keying_sheet as ks
    sheet = ks.keying_sheet(form="ITR-2", assessment_year="2026-27",
                            computation=_computation(),
                            self_assessment_tax_paise=0,
                            self_assessment_challan_count=1)
    assert ks.SELF_ASSESSMENT_TAX_HAS_NO_SOURCE not in sheet["gaps"]
    assert any("1 Challan 280 record(s)" in g for g in sheet["gaps"])


def test_the_keying_sheet_still_derives_nothing():
    """The total is summed in the SERVICE and passed in. A `sum()` here would
    make this module a reader of rows."""
    import ast
    from domain.income_tax import keying_sheet as ks
    src = inspect.getsource(ks)
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.BinOp) and isinstance(
                node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv)):
            assert not any(isinstance(n, ast.Constant)
                           and isinstance(n.value, (int, float))
                           for n in (node.left, node.right)), ast.dump(node)
    assert "self_assessment_challans" not in src


def test_the_endpoint_reads_the_filings_own_client_and_year():
    import routers.itr_workspace as w
    src = inspect.getsource(w.filing_keying_sheet)
    assert "self_assessment_service.list_challans" in src
    assert 'filing.get("financial_year")' in src
    assert 'filing.get("client_id")' in src


def test_what_the_service_returned_actually_reaches_the_sheet():
    """THE RULE, NOT A NAME. The first version of this guard asserted that
    `list_challans` appeared in the endpoint's source — and the negative
    control that deleted the two keyword arguments PASSED, because the read
    was still there and its result was simply dropped on the floor. A name
    left behind is not a behaviour.

    So this walks the AST: whatever `list_challans` is bound to must appear
    inside BOTH §140A keywords of the `keying_sheet` call."""
    import ast
    import routers.itr_workspace as w

    fn = ast.parse(inspect.getsource(w.filing_keying_sheet).strip()).body[0]
    bound: set[str] = set()
    sheet_call = None
    for node in ast.walk(fn):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr == "list_challans"):
            bound |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "keying_sheet"):
            sheet_call = node
    assert bound, "nothing is bound from list_challans"
    assert sheet_call is not None, "the sheet is not built here"
    keywords = {k.arg: k.value for k in sheet_call.keywords}
    for arg in ("self_assessment_tax_paise", "self_assessment_challan_count"):
        assert arg in keywords, arg
        names = {n.id for n in ast.walk(keywords[arg]) if isinstance(n, ast.Name)}
        assert names & bound, (
            f"{arg} does not read what list_challans returned: {names}")


# ── the screen ───────────────────────────────────────────────────────────────

_SCREEN = "web/app/income-tax/advance-tax/page.tsx"


def _screen_source() -> str:
    return (pathlib.Path(__file__).resolve().parents[2] / _SCREEN
            ).read_text(encoding="utf-8")


def test_the_screen_records_a_challan_and_lists_them():
    src = _screen_source()
    for name in ("getSelfAssessmentPosition", "createSelfAssessmentChallan",
                 "deleteSelfAssessmentChallan"):
        assert name in src, name


def test_the_screen_subtracts_nothing_of_its_own_for_the_tax_due():
    """§140A(1)'s credits are the API's subtraction. The panel passes the
    served figure through — a `- tdsTcsPaise` here would be a second rule."""
    src = _screen_source()
    start = src.index("const section140aTaxDuePaise")
    end = src.index("async function handleSave", start)
    block = src[start:end]
    assert "section_140a_tax_due_paise" in block
    assert "tdsTcsPaise" not in block and "estimatedTaxPaise" not in block


def test_the_screen_sends_no_234f_fee():
    """Nothing in this product computes one, and a zero would appropriate a
    payment against a fee that may be due."""
    src = _screen_source()
    assert "feeDuePaise" not in src


def test_every_typed_amount_goes_through_the_one_money_parser():
    src = _screen_source()
    start = src.index("async function handleAddChallan")
    end = src.index("async function handleRemoveChallan", start)
    block = src[start:end]
    for field in ("tax_rs", "surcharge_rs", "cess_rs", "interest_rs",
                  "fee_rs", "total_rs"):
        assert f"paiseFromRupeeInput(saForm.{field}" in block, field
    assert "parseFloat" not in block and "Number(" not in block


def test_the_panel_renders_the_appropriation_and_calls_it_not_pro_rata():
    src = _screen_source()
    start = src.index("{/* §140A — the Challan 280")
    end = src.index("Interest computed under IT Act Section 234C", start)
    panel = src[start:end]
    for key in ("towards_fee_paise", "towards_interest_paise", "towards_tax_paise"):
        assert key in panel, key
    assert "not split proportionally" in panel


def test_the_panel_tells_a_gap_from_a_caveat():
    """A mis-headed challan needs doing something about; the statement that
    the module is unverified needs reading once.

    THE RULE, NOT A SPELLING OF IT. This asserted `saPosition?.gaps.map` and
    `saPosition?.caveats.map` — one spelling of "the two lists are rendered
    apart" — and broke on 18 September when the pair became a single
    `<StatutoryNotes gaps={…} caveats={…}>`, the component that EXISTS to keep
    them apart and gives the caller no way to collapse them. The comment this
    screen carries ("GAPS ARE ACTIONABLE AND CAVEATS ARE NOT") is what that
    component was built from.

    That is the twelfth time in this repository a guard has named a spelling
    rather than its rule; CLAUDE.md records the earlier ones. What this needs
    is that BOTH arrays reach a renderer and that nothing merges them.
    """
    src = _screen_source()
    start = src.index("{/* §140A — the Challan 280")
    end = src.index("Interest computed under IT Act Section 234C", start)
    panel = src[start:end]
    assert re.search(r"gaps=\{saPosition\??\.?gaps|saPosition\?\.gaps\.map", panel), (
        "the §140A gaps reach no renderer")
    assert re.search(r"caveats=\{saPosition\??\.?caveats|saPosition\?\.caveats\.map", panel), (
        "the §140A caveats reach no renderer")
    # And they must not be poured into one list: a caveat rendered as a gap is
    # exactly what this test is named for.
    assert not re.search(r"\[\s*\.\.\.\s*saPosition\??\.?gaps.{0,40}caveats", panel), (
        "the gaps and the caveats have been merged into one list")
