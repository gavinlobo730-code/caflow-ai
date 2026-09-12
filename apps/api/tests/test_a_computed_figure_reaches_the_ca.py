"""
Four figures the platform computed correctly and showed nobody, and two fields
a CA could not set.

CLAUDE.md states the rule this file is about: "a figure the computer gets right
and no screen shows is not a fixed bug." Each of these had been through that
door once already — the engine work landed, the surfacing did not — so the
finding files record them closed and the CA still cannot see them.

  IT §2b — `basic_exemption_absorbed_paise` and `basic_exemption_absorption`
      have existed on `ITRComputeResult` since IT-08, the second documented
      as being there "so a CA can see WHICH gain the exemption was set
      against … a choice a reader is entitled to check". `grep -rn
      basic_exemption apps/api/routers apps/web` returned NOTHING. So the tax
      workspace showed ₹20,800 on a ₹5,00,000 STCG and no account at all of
      the ₹4,00,000 that had vanished, on a working the CA is the one who has
      to defend.

  IT §2a — `exempt_income_paise` is rendered as an input on the client Tax
      Computation tab, sent, declared by the router, declared by
      `ITRComputeRequest` — and `compute()` never read it. One grep line, the
      declaration. The TAX is right (a §10 receipt is not part of total
      income), so the fix is not to start taxing it; it is to stop pretending
      the field does something and say what it does.

  IT §2c — `book_to_tax_bridge.py`'s docstring said "NOTHING IN THIS CODEBASE
      IMPLEMENTS THE SECOND ONE" of §32 block depreciation.
      `domain/income_tax/section_32.py` implements it and the bridge endpoint
      feeds it in. Prose, but it is the module's central claim.

  FA §2.5 — `dispose` returns `part_month_depreciation_not_charged` precisely
      so the CA is told the gain is a whole month short. `grep -rn part_month
      apps/web` returned nothing.

  FA §2.3 — asset CREATION was not checked against the client's period lock at
      all, while `correct_asset` and `delete_asset` both were. So a June asset
      could be created after June's GSTR-3B was filed and then not corrected.

  PAY-12 residual — `eps_eligible` (migration 295) and `gratuity_act_covered`
      (298) are both `NOT NULL DEFAULT true`, both read by the engine at six
      sites, and were on no model, in no CSV column and on no form. The
      exception could not be recorded from anywhere in the product.
"""
import pytest


# ---------------------------------------------------------------------------
# IT §2b — the capital-gains working, and the docstring's own worked example.
# ---------------------------------------------------------------------------
from domain.income_tax.itr_engine import ITRComputeRequest, itr_engine   # noqa: E402

USER = {"id": "u1", "firm_id": "F1", "role": "Partner", "auth_user_id": "a1"}


def _compute(**kw):
    return itr_engine.compute(ITRComputeRequest(fy="2026-27", **kw))


def test_the_worked_example_from_the_engines_own_docstring():
    """₹5,00,000 of §111A STCG and no other income: ₹1,04,000 if the proviso
    is ignored, ₹20,800 once the unused ₹4,00,000 exemption is absorbed."""
    r = _compute(capital_gains_stcg_paise=500000_00)
    assert r.total_tax_paise == 20800_00
    assert r.basic_exemption_absorbed_paise == 400000_00


def test_the_absorption_is_explained_and_not_just_totalled():
    r = _compute(capital_gains_stcg_paise=500000_00)
    assert len(r.basic_exemption_absorption) == 1
    line = r.basic_exemption_absorption[0]
    assert "§111A" in line and "4,00,000" in line


def test_every_row_foots_gross_less_exempt_less_absorbed_equals_charged():
    """The invariant that makes the display checkable. Nothing here is
    recomputed for the screen — a second derivation for display is how a
    display and a tax come to disagree — so this holds by construction and
    fails loudly if anybody changes that."""
    r = _compute(capital_gains_stcg_paise=300000_00,
                 capital_gains_ltcg_paise=400000_00,
                 capital_gains_ltcg_other_paise=200000_00,
                 gross_salary_paise=1200000_00)
    assert r.capital_gains_lines
    for line in r.capital_gains_lines:
        assert (line["gross_paise"] - line["exempt_paise"]
                - line["absorbed_paise"]) == line["charged_paise"], line


def test_every_row_is_present_even_at_zero():
    """Three rows always. A section absent and a section at nil are different
    statements, and the reader needs the second."""
    r = _compute(capital_gains_stcg_paise=100000_00)
    assert [l["section"] for l in r.capital_gains_lines] == [
        "§111A (STCG on equity)", "§112A (LTCG on equity)",
        "§112 (LTCG on other assets)"]


def test_the_112a_exemption_is_shown_on_its_own_row_and_nowhere_else():
    """§112A(2)'s annual exemption is not the basic exemption and must not be
    reported as it — they come from different provisions and one is per-year
    while the other is what the slabs did not use."""
    r = _compute(capital_gains_ltcg_paise=300000_00)
    by = {l["section"]: l for l in r.capital_gains_lines}
    assert by["§112A (LTCG on equity)"]["exempt_paise"] > 0
    assert by["§111A (STCG on equity)"]["exempt_paise"] == 0
    assert by["§112 (LTCG on other assets)"]["exempt_paise"] == 0


def test_the_row_taxes_sum_to_the_capital_gains_tax():
    r = _compute(capital_gains_stcg_paise=800000_00,
                 capital_gains_ltcg_paise=600000_00,
                 capital_gains_ltcg_other_paise=400000_00)
    assert sum(l["tax_paise"] for l in r.capital_gains_lines) \
        == r.capital_gains_tax_paise


def test_the_allocation_is_highest_rate_first_and_visible_as_such():
    """§111A is 20% and the two 12.5%, so the exemption goes to §111A. The
    statute fixes no order — that is why it has to be shown."""
    r = _compute(capital_gains_stcg_paise=200000_00,
                 capital_gains_ltcg_other_paise=200000_00)
    by = {l["section"]: l for l in r.capital_gains_lines}
    assert by["§111A (STCG on equity)"]["absorbed_paise"] == 200000_00
    assert by["§112 (LTCG on other assets)"]["absorbed_paise"] == 200000_00


def test_a_company_absorbs_nothing_because_the_provisos_do_not_reach_it():
    r = itr_engine.compute(ITRComputeRequest(
        fy="2026-27", assessee_kind="domestic_company",
        business_income_paise=1000000_00))
    assert r.basic_exemption_absorbed_paise == 0
    assert r.basic_exemption_absorption == []


# ---------------------------------------------------------------------------
# IT §2a — exempt income, echoed rather than silently discarded.
# ---------------------------------------------------------------------------
def test_exempt_income_is_echoed_back():
    r = _compute(gross_salary_paise=1000000_00, exempt_income_paise=45000_00)
    assert r.exempt_income_reported_paise == 45000_00


def test_exempt_income_still_does_not_change_the_tax():
    """§10 income is not part of total income. Echoing it must not start
    taxing it, and must not start deducting it either."""
    without = _compute(gross_salary_paise=1000000_00)
    with_ = _compute(gross_salary_paise=1000000_00, exempt_income_paise=45000_00)
    assert with_.total_tax_paise == without.total_tax_paise
    assert with_.gross_total_income_paise == without.gross_total_income_paise


def test_a_negative_exempt_figure_is_floored_rather_than_echoed():
    r = _compute(exempt_income_paise=-5000_00)
    assert r.exempt_income_reported_paise == 0


# ---------------------------------------------------------------------------
# The route carries all of it out.
# ---------------------------------------------------------------------------
def _endpoint(**kw):
    from routers.income_tax import ComputeITRRequest, compute_itr
    body = ComputeITRRequest(client_id="C1", fy="2026-27", **kw)
    return compute_itr(body, current_user=USER)["data"]


def test_the_endpoint_carries_the_capital_gains_working():
    data = _endpoint(capital_gains_stcg_paise=500000_00)
    cg = data["capital_gains"]
    assert cg["basic_exemption_absorbed_paise"] == 400000_00
    assert len(cg["basic_exemption_absorption"]) == 1
    assert len(cg["lines"]) == 3
    assert cg["tax_paise"] == 2000000            # ₹20,000 before cess


def test_the_endpoint_carries_the_exempt_income_echo_and_says_why():
    data = _endpoint(gross_salary_paise=1000000_00, exempt_income_paise=45000_00)
    assert data["exempt_income"]["reported_paise"] == 45000_00
    assert "not part of total income" in data["exempt_income"]["note"]


# ---------------------------------------------------------------------------
# IT §2c — the bridge's central claim.
# ---------------------------------------------------------------------------
def test_the_bridge_no_longer_says_section_32_is_unimplemented():
    import domain.income_tax.book_to_tax_bridge as bridge
    import domain.income_tax.section_32 as s32
    assert "NOTHING\nIN THIS CODEBASE IMPLEMENTS THE SECOND ONE" not in bridge.__doc__
    assert hasattr(s32, "__doc__") and s32.__doc__
    # And it still refuses rather than defaulting §32 to the book figure,
    # which is the part of that paragraph that IS still true.
    assert "must not happen" in bridge.__doc__


# ---------------------------------------------------------------------------
# PAY-12 residual — the two exceptions, settable at create AND at update.
# ---------------------------------------------------------------------------
from models.payroll import EmployeeIn, EmployeeUpdateIn                  # noqa: E402
from domain.payroll import employee_import                              # noqa: E402


@pytest.mark.parametrize("field", ["eps_eligible", "gratuity_act_covered"])
def test_the_field_is_on_both_models(field):
    """On EmployeeIn as well as EmployeeUpdateIn. Adding it to the update
    model alone leaves it unsettable at create, and
    tests/test_a_field_you_can_create_is_a_field_you_can_correct.py only
    checks create→update, so it would not notice."""
    assert field in EmployeeIn.model_fields
    assert field in EmployeeUpdateIn.model_fields


@pytest.mark.parametrize("field", ["eps_eligible", "gratuity_act_covered"])
def test_the_default_is_the_columns_default(field):
    """Both columns are NOT NULL DEFAULT true (migrations 295, 298). A model
    default of False would silently flip every employee created through the
    API to the exception."""
    assert EmployeeIn(client_id="c1", name="A").model_dump()[field] is True


@pytest.mark.parametrize("field", ["eps_eligible", "gratuity_act_covered"])
def test_false_survives_the_update_dump(field):
    """`exclude_none=True`, not `exclude_unset` — so False must reach the
    UPDATE. This is the one value that matters: True is the default already."""
    sent = EmployeeUpdateIn(**{field: False}).model_dump(exclude_none=True)
    assert sent == {field: False}


@pytest.mark.parametrize("field", ["eps_eligible", "gratuity_act_covered"])
def test_the_field_is_an_import_column(field):
    assert field in [name for name, _required in employee_import.COLUMNS]
    assert field in employee_import.template_csv()


@pytest.mark.parametrize("field", ["eps_eligible", "gratuity_act_covered"])
def test_a_file_that_says_no_records_the_exception(field):
    rows = [{"name": "A", "basic": "50000", field: "no"}]
    out = employee_import.validate(rows, existing_by_code={})
    assert out.ok, out.problems
    assert out.to_create[0][field] is False


@pytest.mark.parametrize("field", ["eps_eligible", "gratuity_act_covered"])
def test_a_file_that_omits_the_column_means_what_it_always_meant(field):
    out = employee_import.validate([{"name": "A", "basic": "50000"}],
                                   existing_by_code={})
    assert out.ok, out.problems
    assert out.to_create[0][field] is True


def test_the_engine_reads_what_the_form_can_now_write():
    """The premise: these are not decorative columns. Both are read on the
    payroll path, and the EPS one decides a figure on the ECR."""
    import inspect
    import routers.payroll as pr
    src = inspect.getsource(pr)
    assert 'emp.get("eps_eligible"' in src
    assert 'emp.get("gratuity_act_covered"' in src


# ---------------------------------------------------------------------------
# FA §2.3 — create was the one asset path not asked about the client's lock.
# ---------------------------------------------------------------------------
def test_asset_creation_asks_the_client_lock_the_way_correction_does():
    """The asymmetry was the defect, whichever way the rule should fall.

    `correct_asset` and `delete_asset` have called
    `period_lock_service.assert_open` on the purchase date since they were
    written; `create_asset` called only `period_validation_service.
    validate_posting_date`, which is firm-FY and takes no client_id, so it
    cannot see a filed return. A CA could create a June asset after June's
    GSTR-3B was filed and then be refused when they tried to fix it.

    It falls on `assert_open` — the whole rule including the filed return —
    because the acquisition journal can debit `%GST Input%` from
    `itc_claimable_paise`, and that figure feeds GSTR-3B Table 4(A). CLAUDE.md
    puts the filed-return branch exactly where a document that FEEDS a return
    is written; a capitalised purchase is one.
    """
    import inspect
    import routers.fixed_assets as fa
    create = inspect.getsource(fa.create_asset)
    assert "period_lock_service.assert_open" in create, (
        "create_asset does not ask the client lock, while correct_asset and "
        "delete_asset both do — so an asset can be created inside a period "
        "whose return is filed and then not corrected")
    # And it did not lose the firm-FY check, which is a different question.
    assert "period_validation_service.validate_posting_date" in create


def test_the_three_asset_paths_all_ask_the_same_question():
    import inspect
    import routers.fixed_assets as fa
    for fn in (fa.create_asset, fa.correct_asset, fa.delete_asset):
        assert "period_lock_service.assert_open" in inspect.getsource(fn), fn.__name__
