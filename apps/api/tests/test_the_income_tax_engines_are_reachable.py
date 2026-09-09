"""IT-13, IT-16, IT-17 — three finished engines that no endpoint reached.

Each was complete, tested and imported by nothing outside its own test file:

  §234A / §234B   advance_tax_interest_engine had all three sections; this
                  router imported only compute_234c_interest. A CA saw the
                  instalment-shortfall interest and neither of the other two —
                  and they are not alternatives. A return filed late on
                  fully-paid tax owes 234A and nothing else; one filed on time
                  on half-paid tax owes 234B and nothing else.

  §44AD/ADA/AE    the presumptive engines are covered by
                  tests/test_presumptive_taxation.py, and ITRComputeRequest
                  already honours their output — but no request model carried
                  the inputs, so the branch was unreachable.

  field placements  "this figure goes in this field", every path checked
                  against the Department's own committed schemas, imported
                  nowhere but its test.

Every test here fails against the previous code with 404 or ImportError: the
endpoints did not exist.
"""
from datetime import date

import pytest
from fastapi import HTTPException

import routers.income_tax as it

CALLER = {"firm_id": "F1", "id": "u1", "auth_user_id": "a1",
          "email": "ca@f.test", "role": "Partner"}
L = 1_00_000_00        # one lakh, in paise


# ─────────────────────────── §234A and §234B ───────────────────────────

def _234ab(**kw):
    body = {"fy": "2025-26", "tax_on_total_income_paise": 10 * L}
    body.update(kw)
    return it.compute_234ab_interest(it.ComputeSection234ABRequest(**body), CALLER)


def test_both_sections_come_back_and_neither_is_the_other():
    res = _234ab(tds_tcs_paise=1 * L, return_furnished_on="2026-11-15")
    assert res["success"] is True
    d = res["data"]
    assert d["section_234a"]["section"] == "234A"
    assert d["section_234b"]["section"] == "234B"
    assert d["total_interest_paise"] == (
        d["section_234a"]["interest_paise"] + d["section_234b"]["interest_paise"])


def test_a_late_return_on_all_but_paid_tax_owes_234a_and_not_234b():
    """The distinction the CA could not see. 95% paid clears §234B's 90% line
    entirely — but the return is four months late, and §234A charges the delay
    on what is still outstanding.

    Note §234A nets off advance tax too, so a return that is late AND fully
    paid owes neither: the delay itself is not what is taxed."""
    res = _234ab(advance_tax_paid_paise=int(9.5 * L), return_furnished_on="2026-11-15")
    d = res["data"]
    assert d["section_234b"]["applies"] is False
    assert d["section_234a"]["applies"] is True
    assert d["section_234a"]["months"] == 4
    assert d["section_234a"]["base_paise"] == 10 * L - int(9.5 * L)


def test_a_late_return_on_fully_paid_tax_owes_nothing_at_all():
    """§234A charges tax NET of advance tax, TDS and relief. Where nothing is
    outstanding there is no amount for it to charge interest on."""
    res = _234ab(advance_tax_paid_paise=10 * L, return_furnished_on="2026-11-15")
    assert res["data"]["total_interest_paise"] == 0
    assert any("not what is taxed" in r for r in res["data"]["section_234a"]["reasons"])


def test_a_timely_return_on_half_paid_tax_owes_234b_and_not_234a():
    res = _234ab(advance_tax_paid_paise=5 * L, return_furnished_on="2026-07-31",
                 assessment_date="2026-11-15")
    d = res["data"]
    assert d["section_234a"]["applies"] is False
    assert d["section_234b"]["applies"] is True
    assert d["section_234b"]["base_paise"] == 5 * L


def test_a_return_not_yet_furnished_still_accrues():
    """Reporting nil for an unfiled return would tell a CA the cheapest moment
    to file is never."""
    res = _234ab(return_furnished_on=None, assessment_date="2026-12-01")
    assert res["data"]["section_234a"]["applies"] is True


def test_the_due_date_is_derived_and_its_provenance_comes_back():
    """§234A's whole charge hangs on the §139(1) due date, and that date is
    NOT accepted from the caller — compliance_obligation_service decides it or
    refuses, and the refusal has to reach the screen."""
    undecided = _234ab(entity_type="Partnership", return_furnished_on="2026-11-15")
    due = undecided["data"]["itr_due_date"]
    assert due["decided"] is False
    assert due["statutory_gaps"], "an undecided date must name what would settle it"
    assert due["due_date"].endswith("-07-31"), "the EARLIER date is taken when undecided"

    company = _234ab(entity_type="Private Limited", return_furnished_on="2026-11-15")
    settled = company["data"]["itr_due_date"]
    assert settled["decided"] is True
    assert settled["due_date"].endswith("-10-31")
    assert not settled["statutory_gaps"]


def test_an_audit_client_is_charged_from_the_later_date_so_owes_less():
    """The date is not decoration: it is the from-date of the charge."""
    plain = _234ab(entity_type="Partnership", return_furnished_on="2026-11-15")
    audit = _234ab(entity_type="Private Limited", return_furnished_on="2026-11-15")
    assert (audit["data"]["section_234a"]["interest_paise"]
            < plain["data"]["section_234a"]["interest_paise"])


def test_assessed_tax_is_its_own_field_and_defaults_to_the_tax_on_total_income():
    same = _234ab(advance_tax_paid_paise=1 * L, return_furnished_on="2026-07-31")
    apart = _234ab(assessed_tax_paise=20 * L, advance_tax_paid_paise=1 * L,
                   return_furnished_on="2026-07-31")
    assert apart["data"]["section_234b"]["base_paise"] > same["data"]["section_234b"]["base_paise"]


def test_a_date_that_is_not_a_date_is_refused():
    with pytest.raises(Exception):
        it.ComputeSection234ABRequest(fy="2025-26", tax_on_total_income_paise=0,
                                      return_furnished_on="15-11-2026")


# ───────────────────────────── presumptive ─────────────────────────────

def test_44ad_reaches_the_engine_and_the_digital_split_changes_the_answer():
    """The split is not cosmetic: the ceiling and the rate both turn on how
    much came through a bank."""
    cash = it.compute_presumptive_44ad(it.Compute44ADRequest(
        fy="2025-26", turnover_paise=50_00_000_00), CALLER)["data"]
    digital = it.compute_presumptive_44ad(it.Compute44ADRequest(
        fy="2025-26", turnover_paise=50_00_000_00,
        digital_turnover_paise=50_00_000_00), CALLER)["data"]
    assert cash["section"] == "44AD"
    assert digital["presumptive_income_paise"] < cash["presumptive_income_paise"]
    assert digital["workings"], "the arithmetic has to be shown, not just the total"


def test_44ada_reaches_the_engine():
    res = it.compute_presumptive_44ada(it.Compute44ADARequest(
        fy="2025-26", gross_receipts_paise=40_00_000_00), CALLER)
    assert res["success"] is True
    assert res["data"]["section"] == "44ADA"
    assert res["data"]["presumptive_income_paise"] == 20_00_000_00     # 50%


def test_44ae_charges_a_heavy_vehicle_by_its_weight():
    """1,000 rupees per ton is exactly 1 rupee per kilogram, so a 16,500 kg
    vehicle earns 16,500 rupees a month."""
    res = it.compute_presumptive_44ae(it.Compute44AERequest(
        fy="2025-26",
        vehicles=[it.GoodsCarriageInput(gross_vehicle_weight_kg=16_500, months_owned=12)]),
        CALLER)
    assert res["data"]["presumptive_income_paise"] == 16_500 * 12 * 100


def test_a_turnover_over_the_ceiling_is_refused_with_the_reason():
    res = it.compute_presumptive_44ad(it.Compute44ADRequest(
        fy="2025-26", turnover_paise=5_00_00_000_00), CALLER)
    assert res["data"]["eligible"] is False
    assert res["data"]["reasons"], "an ineligible scheme must say why"


# ─────────────────────────── field placements ──────────────────────────

def _placements(form="ITR-1", **kw):
    body = {"form": form, "total_income_paise": 8_00_000_00,
            "tax_on_total_income_paise": 72_500_00}
    body.update(kw)
    return it.itr_field_placements_endpoint(it.ITRFieldPlacementsRequest(**body), CALLER)


def test_every_figure_comes_back_with_where_it_goes():
    res = _placements()
    assert res["success"] is True
    rows = res["data"]["placements"]
    assert rows
    for r in rows:
        assert {"key", "label", "schedule", "amount_paise", "amount_rupees",
                "json_path", "not_on_this_form"} <= set(r)


def test_rupees_are_rounded_at_the_boundary_and_not_before():
    """This is the statutory payload boundary — the same place domain/gst/
    money.py rounds for GSTR-1 and GSTR-3B."""
    rows = _placements(total_income_paise=8_00_000_49)["data"]["placements"]
    ti = next(r for r in rows if r["amount_paise"] == 8_00_000_49)
    assert ti["amount_rupees"] == 8_00_000
    assert isinstance(ti["amount_rupees"], int)


def test_a_field_that_is_not_on_this_form_says_so_rather_than_going_missing():
    """§87A has no home on ITR-6. A silent omission would send a CA hunting
    for a field that does not exist."""
    rows = _placements(form="ITR-6", rebate_87a_paise=12_500_00)["data"]["placements"]
    rebate = next(r for r in rows if "87a" in r["key"].lower())
    assert rebate["not_on_this_form"] is True
    assert rebate["json_path"] is None


def test_the_endpoint_returns_placements_and_never_a_file():
    """The useful half without the dangerous half. generate_itr_json refuses
    until the Third Party Software Utility Developer registration exists, and
    that refusal is right — so this endpoint does not call it, and nothing in
    the response is or resembles a return file.

    `can_emit_file` is NOT that gate: itr_json.py sets it from the same
    `verified` flag as schema_is_verified, so it says the paths are
    trustworthy, not that a file may be produced."""
    data = _placements()["data"]
    assert set(data) == {"form", "assessment_year", "placements",
                         "schema_is_verified", "can_emit_file", "notes"}
    assert data["can_emit_file"] == data["schema_is_verified"]

    # Checked as a BINDING, not as a string in the source: the router's own
    # comment explains why it does not call the generator, and a substring scan
    # finds the explanation rather than a call. (The same shape as the
    # apostrophe-in-a-comment that hid a database write from the frontend
    # column scanner in Phase 5.)
    assert not hasattr(it, "generate_itr_json"), (
        "this router must not import the generator — the registration gate is "
        "the whole reason it refuses")


def test_an_invented_form_is_refused():
    with pytest.raises(Exception):
        it.ITRFieldPlacementsRequest(form="ITR-9")


def test_every_real_form_is_accepted():
    for form in ("ITR-1", "ITR-2", "ITR-3", "ITR-4", "ITR-5", "ITR-6", "ITR-7"):
        assert _placements(form=form)["success"] is True
