"""IT-17 — every computed figure, and the box on the form it goes in.

WHAT WAS WRONG

    `itr_json.itr_field_placements` has said "this number goes in this field"
    since IT-17's first half, every path checked against the Department's own
    committed schemas, and `POST /api/income-tax/itr/field-placements` exposed
    it. A grep across `apps/web` returned NOTHING: no screen reached it, so a
    CA transcribing a return into the offline utility was doing it from memory.
    The `capital_wip` / `fx_revaluation_service` / §115BAC(6) shape again.

    And the answer covered the fourteen TAX-COMPUTATION totals alone — no head
    of income and no Chapter VI-A section had a field mapping at all, which is
    most of Part B-TI and the whole of Schedule VI-A.

THE THREE STATES, AND THE TWO DEFECTS THE SPLIT FOUND

    `not_on_this_form` used to mean "no path", full stop, which was safe while
    the only two absences were real (§87A on ITR-5/6/7, surcharge on ITR-1/4).
    With twenty more keys it stops being safe: an unmapped key would tell a CA
    the form has no box for their house-property income and they would leave it
    blank.

    Splitting it found two things that had been reported as absences and were
    not:

      * `tds_tcs` is mapped on NO form and every form HAS the boxes — two of
        them, `TaxPaid.TaxesPaid.TDS` and `.TCS`, and this figure is their sum.
      * `total_deductions` on ITR-7, which is a real absence but had never been
        declared as one.

NEGATIVE CONTROLS — all six run against the code and reverted:
  * Collapse the three states back to two (`not_on_this_form = path is None`)
    -> 1 fails. ⚠️ THE FIRST DRAFT OF THAT TEST PASSED, because every key is
    currently in one of the first two states and the collapse is behaviourally
    identical today. The rule needed a SYNTHETIC case — a key deliberately put
    into the third state — which is what `monkeypatch` builds below.
  * Emit an unsupplied head as 0 instead of omitting it -> 1 fails. A zero on a
    keying sheet is an instruction to key zero.
  * Take the heads from the request's own inputs rather than
    `income_heads_paise` -> 2 fail, by the standard deduction.
  * Guess an unknown §80 section into a neighbouring box -> 1 fails.
  * Point one head path at a container rather than an integer leaf ->
    test_itr_schema_paths fails.
  * Delete the panel from the filing screen -> 2 fail. ⚠️ Only ONE failed at
    first: the `Placement` interface names all three state keys, so the
    file-wide scan stayed green on a screen with no panel. Narrowed to the
    panel itself.
"""
from __future__ import annotations

import pytest

from domain.income_tax import keying_sheet as ks
from domain.income_tax.itr_json import (
    ABSENCE_REASONS, CHAPTER_VI_A_KEYS, FIELD_MAPPINGS, INCOME_HEAD_KEYS,
    build_itr_payload, itr_field_placements)

FORMS = ["ITR-1", "ITR-2", "ITR-3", "ITR-4", "ITR-5", "ITR-6", "ITR-7"]

#: The fourteen tax figures, which were the whole payload before this.
TAX_KEYS = (
    "gross_total_income", "total_deductions", "total_income",
    "tax_on_total_income", "rebate_87a", "surcharge", "cess", "total_tax",
    "tds_tcs", "advance_tax_paid", "self_assessment_tax",
    "interest_234a", "interest_234b", "interest_234c",
)
ALL_KEYS = tuple(INCOME_HEAD_KEYS) + tuple(CHAPTER_VI_A_KEYS) + TAX_KEYS


# ── the three states ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("form", FORMS)
def test_every_key_is_in_exactly_one_state(form):
    """Mapped, deliberately absent, or not mapped — never two and never none.

    This is the rule the whole IT-17 extension rests on, so it is asserted over
    the DATA rather than over one rendered answer: a key added later cannot
    silently read as "the form has no such field"."""
    paths = FIELD_MAPPINGS[form].paths
    absences = ABSENCE_REASONS[form]
    for key in ALL_KEYS:
        mapped, absent = key in paths, key in absences
        assert mapped != absent, (
            f"{form}: {key} is "
            + ("both mapped and declared absent" if mapped
               else "neither mapped nor declared absent"))


@pytest.mark.parametrize("form", FORMS)
def test_every_declared_absence_gives_a_reason(form):
    for key, reason in ABSENCE_REASONS[form].items():
        assert isinstance(reason, str) and len(reason) > 30, (form, key)


def test_the_placement_reports_the_three_states_apart():
    payload = build_itr_payload(
        form="ITR-5", income_heads_paise={"salary": 1, "house_property": 2},
        chapter_vi_a_paise={"deduction_80dd": 3, "deduction_80g": 4})
    by_key = {p["key"]: p for p in itr_field_placements(payload)}

    placed = by_key["house_property"]
    assert placed["json_path"] and not placed["not_on_this_form"]
    assert not placed["not_mapped"] and placed["absence_reason"] is None

    absent = by_key["salary"]
    assert absent["json_path"] is None and absent["not_on_this_form"]
    assert not absent["not_mapped"] and "no salary head" in absent["absence_reason"]


def test_an_undeclared_key_reads_as_NOT_MAPPED_and_never_as_an_absence(monkeypatch):
    """THE RULE THE WHOLE SPLIT EXISTS FOR, and it needs a SYNTHETIC case.

    Every key is currently in one of the first two states, so collapsing the
    three back to two is behaviourally identical today and a test written
    against real data would pass against the collapsed code — which is exactly
    what happened on the first negative control of this finding. The rule has
    to be exercised on a key deliberately put into the third state.

    Rendering that key as "this form has no such field" tells a CA to leave a
    box blank that the form does have."""
    import domain.income_tax.itr_json as j
    trimmed = {k: v for k, v in j.ABSENCE_REASONS["ITR-5"].items()
               if k != "salary"}
    monkeypatch.setitem(j.ABSENCE_REASONS, "ITR-5", trimmed)

    payload = build_itr_payload(form="ITR-5", income_heads_paise={"salary": 1})
    row = next(p for p in itr_field_placements(payload) if p["key"] == "salary")
    assert row["json_path"] is None
    assert row["not_mapped"] is True
    assert row["not_on_this_form"] is False, (
        "an unmapped key must never read as an absence")
    assert row["absence_reason"] is None


def test_tds_and_tcs_are_two_boxes_and_the_reason_says_so():
    """THE DEFECT THE SPLIT FOUND. Every form has TaxPaid.TaxesPaid.TDS and
    .TCS; `tds_tcs` is their SUM and fits neither. The old two-state answer
    told a CA the form had no TDS box at all."""
    for form in FORMS:
        reason = ABSENCE_REASONS[form]["tds_tcs"]
        assert "TDS" in reason and "TCS" in reason
        assert "separate" in reason or "two" in reason.lower()
        assert "tds_tcs" not in FIELD_MAPPINGS[form].paths


def test_a_firm_and_a_company_get_only_section_80g():
    """Every other section in the list reaches an individual or a HUF alone, so
    the schema carries no field — which is an ANSWER, not a gap."""
    for form in ("ITR-5", "ITR-6"):
        paths = FIELD_MAPPINGS[form].paths
        assert "deduction_80g" in paths
        for key in CHAPTER_VI_A_KEYS:
            if key == "deduction_80g":
                continue
            assert key not in paths, (form, key)
            assert "individual" in ABSENCE_REASONS[form][key]


def test_a_trust_has_no_schedule_vi_a_at_all():
    paths = FIELD_MAPPINGS["ITR-7"].paths
    for key in CHAPTER_VI_A_KEYS:
        assert key not in paths, key
        assert "Schedule VI-A" in ABSENCE_REASONS["ITR-7"][key]
    assert "Schedule VI-A" in ABSENCE_REASONS["ITR-7"]["total_deductions"]


# ── the payload ──────────────────────────────────────────────────────────────

def test_an_unsupplied_head_is_omitted_and_not_sent_as_zero():
    """A zero on a keying sheet is an INSTRUCTION to key zero. A caller that
    does not hold the house-property figure must not be telling the CA it is
    nil."""
    payload = build_itr_payload(form="ITR-2", income_heads_paise={"salary": 100})
    keys = {v.key for v in payload.values}
    assert "salary" in keys
    assert "house_property" not in keys


def test_a_supplied_zero_head_is_kept():
    payload = build_itr_payload(form="ITR-2", income_heads_paise={"house_property": 0})
    assert any(v.key == "house_property" and v.amount_paise == 0
               for v in payload.values)


@pytest.mark.parametrize("field, bad", [
    ("income_heads_paise", {"capital_gains_shortterm": 1}),
    ("chapter_vi_a_paise", {"deduction_80ccd2": 1}),
])
def test_an_unknown_key_is_refused_rather_than_dropped(field, bad):
    """These arrive as dicts, so a typo would otherwise vanish in silence — a
    head simply missing from the sheet, on a return the CA then transcribes
    believing it complete."""
    with pytest.raises(ValueError) as exc:
        build_itr_payload(form="ITR-2", **{field: bad})
    assert "unknown" in str(exc.value)


def test_the_heads_come_first_because_that_is_the_order_of_the_form():
    payload = build_itr_payload(
        form="ITR-2", income_heads_paise={"salary": 1},
        chapter_vi_a_paise={"deduction_80c": 2}, gross_total_income_paise=3)
    keys = [v.key for v in payload.values]
    assert keys.index("salary") < keys.index("deduction_80c")
    assert keys.index("deduction_80c") < keys.index("gross_total_income")


# ── the heads are the engine's, not the request's ────────────────────────────

def test_the_salary_head_is_after_the_standard_deduction():
    """§16(ia). The form's head line asks for income CHARGEABLE UNDER THE HEAD,
    so keying the gross would be the wrong figure under the right label — and
    the two are only ₹50,000 or ₹75,000 apart, which is the kind of wrong that
    survives a review."""
    from domain.income_tax.itr_engine import ITRComputeRequest, itr_engine
    gross = 15_00_000_00
    r = itr_engine.compute(ITRComputeRequest(
        fy="2025-26", gross_salary_paise=gross, use_new_regime=False))
    assert r.income_heads_paise["salary"] == gross - r.standard_deduction_paise
    assert r.income_heads_paise["salary"] != gross


def test_the_capital_head_is_after_the_brought_forward_loss_it_absorbed():
    from domain.income_tax.itr_engine import ITRComputeRequest, itr_engine
    r = itr_engine.compute(ITRComputeRequest(
        fy="2025-26", capital_gains_stcg_paise=5_00_000_00,
        use_new_regime=False,
        brought_forward_losses=[{
            "loss_type": "capital_short_term", "amount_paise": 2_00_000_00,
            "assessment_year": "2023-24"}]))
    assert r.brought_forward_set_off_paise == 2_00_000_00
    assert r.income_heads_paise["capital_gains_short_term"] == 3_00_000_00


def test_the_long_term_head_is_both_buckets():
    """The form's long-term TOTAL is one figure; the split by rate lives in
    Schedule CG, which this payload does not carry."""
    from domain.income_tax.itr_engine import ITRComputeRequest, itr_engine
    r = itr_engine.compute(ITRComputeRequest(
        fy="2025-26", capital_gains_ltcg_paise=1_00_000_00,
        capital_gains_ltcg_other_paise=3_00_000_00, use_new_regime=False))
    assert r.income_heads_paise["capital_gains_long_term"] == 4_00_000_00


def test_an_entity_has_no_heads_at_all():
    from domain.income_tax.itr_engine import ITRComputeRequest, itr_engine
    r = itr_engine.compute(ITRComputeRequest(
        fy="2025-26", assessee_kind="domestic_company",
        business_income_paise=50_00_000_00))
    assert r.income_heads_paise == {}


# ── the sheet ────────────────────────────────────────────────────────────────

def _computation(**kw):
    import routers.income_tax as it
    caller = {"firm_id": "F1", "id": "u1", "auth_user_id": "a1",
              "email": "ca@f.test", "role": "Partner"}
    body = {"fy": "2025-26", "use_new_regime": False}
    body.update(kw)
    return it.compute_itr(it.ComputeITRRequest(**body), caller)["data"]


def test_the_sheet_places_what_the_computation_computed():
    comp = _computation(
        gross_salary_paise=15_00_000_00, house_property_income_paise=2_00_000_00,
        s80c={"ppf_paise": 1_50_000_00},
        chapter_vi_a={"education_loan_interest_paise": 60_000_00,
                      "education_loan_year": 2})
    sheet = ks.keying_sheet(form="ITR-2", assessment_year="2026-27",
                            computation=comp, snapshot={})
    by_key = {p["key"]: p for p in sheet["placements"]}
    assert by_key["salary"]["amount_rupees"] == 14_50_000
    assert by_key["house_property"]["amount_rupees"] == 2_00_000
    assert by_key["deduction_80c"]["amount_rupees"] == 1_50_000
    assert by_key["deduction_80e"]["amount_rupees"] == 60_000
    assert by_key["deduction_80e"]["json_path"].endswith("Section80E")


def test_the_two_payments_come_off_the_snapshot_and_not_the_computation():
    """The compute response reports only their SUM (`tds_and_advance_paise`),
    and the form keeps them in two different schedules."""
    comp = _computation(gross_salary_paise=15_00_000_00,
                        tds_deducted_paise=1_00_000_00,
                        advance_tax_paid_paise=50_000_00)
    sheet = ks.keying_sheet(
        form="ITR-2", assessment_year="2026-27", computation=comp,
        snapshot={"tds_deducted_paise": 1_00_000_00,
                  "advance_tax_paid_paise": 50_000_00})
    by_key = {p["key"]: p for p in sheet["placements"]}
    assert by_key["tds_tcs"]["amount_rupees"] == 1_00_000
    assert by_key["advance_tax_paid"]["amount_rupees"] == 50_000


def test_the_sheet_names_the_two_figures_it_cannot_fill_in():
    """A zero a CA has been told about is a box to fill in; a zero they have
    not is a figure they will file."""
    sheet = ks.keying_sheet(form="ITR-2", assessment_year="2026-27",
                            computation=_computation(), snapshot={})
    joined = " ".join(sheet["gaps"])
    assert "§234A" in joined and "Advance Tax" in joined
    assert "§140A" in joined and "Challan 280" in joined


def test_no_computation_is_refused_rather_than_answered_with_zeros():
    sheet = ks.keying_sheet(form="ITR-2", assessment_year="2026-27",
                            computation=None)
    assert sheet["placements"] == []
    assert sheet["gaps"] == [ks.NO_COMPUTATION_STORED]


def test_a_section_the_module_cannot_place_is_named_not_guessed():
    comp = {"deductions": {"chapter_vi_a_lines": [
        {"section": "80QQB", "allowed_paise": 3_00_000_00}]}}
    via, unplaced = ks.chapter_vi_a_from_computation(comp)
    assert unplaced == ["80QQB"]
    assert 3_00_000_00 not in via.values(), (
        "a section with no box must not land in a neighbouring one")


def test_the_module_derives_nothing():
    """Every figure on the sheet was computed by `itr_engine`. A derivation
    here would be a second income-tax engine, reachable from a screen, agreeing
    with the first until it did not."""
    import ast
    import inspect
    src = inspect.getsource(ks)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(
                node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv)):
            # A `+` on two strings is prose, not arithmetic. Anything numeric
            # is what this asserts against.
            assert not any(isinstance(n, ast.Constant) and isinstance(n.value, (int, float))
                           for n in (node.left, node.right)), ast.dump(node)


# ── the door, and the screen that has to reach it ────────────────────────────

def test_the_router_serves_it_off_the_pinned_snapshot():
    import inspect
    import routers.itr_workspace as w
    src = inspect.getsource(w.filing_keying_sheet)
    assert "computation_snapshot_id" in src
    assert "_assert_filing_scope" in src and "_assert_snapshot_scope" in src
    assert "NO_SNAPSHOT_PINNED" in src


def test_the_endpoint_refuses_a_filing_that_pins_nothing():
    """A sheet of zeros reads as a computed return."""
    import routers.itr_workspace as w
    from domain.income_tax.keying_sheet import NO_SNAPSHOT_PINNED

    caller = {"firm_id": "F1", "id": "u1", "auth_user_id": "a1",
              "email": "ca@f.test", "role": "Partner"}
    import domain.income_tax.itr_workflow as wf
    created = wf.create_itr_filing(
        firm_id="F1", client_id="C1", financial_year="2025-26",
        assessment_year="2026-27", itr_form="ITR-6", created_by="u1")
    res = w.filing_keying_sheet(created["id"], caller)
    assert res["success"] is False
    assert res["error"] == NO_SNAPSHOT_PINNED


_SCREEN = "web/app/clients/[id]/tax/filing/page.tsx"


def _screen_source() -> str:
    import pathlib
    return (pathlib.Path(__file__).resolve().parents[2] / _SCREEN
            ).read_text(encoding="utf-8")


def test_the_filing_screen_fetches_the_sheet():
    src = _screen_source()
    assert "/keying-sheet" in src
    assert "KeyingSheetPanel" in src


def test_the_screen_renders_all_three_states():
    """Rendering `not_mapped` as an absence would tell a CA to leave blank a
    box the form does have — which is the defect the split exists to end.

    Matched inside the PANEL, not anywhere in the file. The `Placement`
    interface names all three keys, so a file-wide scan stays green when the
    panel is deleted and only the type survives — which is what the negative
    control for this actually did. The same shape as PAY-13's form state, and
    the third time this file's family of guards has had to be narrowed from a
    file to the thing that does the work."""
    src = _screen_source()
    start = src.index("function KeyingSheetPanel")
    panel = src[start:]
    for key in ("not_on_this_form", "absence_reason", "not_mapped"):
        assert key in panel, key


def test_the_screen_computes_nothing_and_files_nothing():
    src = _screen_source()
    # The sheet is served in whole rupees; a conversion here would be a second
    # rounding convention in a codebase that has exactly one.
    assert "amount_paise / 100" not in src
    # Matched as a CALL, because the panel's own docstring names the function
    # it is explaining that it does not reach. A guard that forbids the NAME
    # forbids talking about it, which is how prose gets deleted to keep a test
    # green.
    assert "generate_itr_json(" not in src
