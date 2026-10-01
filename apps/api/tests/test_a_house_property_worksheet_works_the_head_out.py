"""The house-property worksheet works the head out (TDS-INCOME-TAX-14).

WHAT WAS WRONG
    House property was one typed figure with a minus sign for a loss. There was
    no rent received, municipal tax, net annual value, 30% under §24(a), §24(b)
    interest (pre-construction instalments included), co-owner share, deemed
    let-out or self-occupied cap, so the CA worked the head out on paper and typed
    the result in. The product could neither show the working nor keep it.

WHAT IS ASSERTED
    Every figure below is hand-worked in rupees from the section:
      * a let-out house: expected rent, rent receivable, the higher of the two,
        municipal tax, the 30%, interest;
      * a self-occupied house: nil value, the ₹2,00,000 and ₹30,000 caps and the
        facts each turns on, the cap shared across both houses, and §115BAC(2)
        withdrawing the interest altogether;
      * a deemed let-out house valued at its expected rent;
      * a co-owned house at its share, with the owner's own interest;
      * the five equal pre-construction instalments, sitting inside the cap;
      * vacancy, standard rent and unrealised rent (Rule 4);
      * the refusals: a third self-occupied house, rent on a deemed let-out house,
        unrealised rent whose conditions nobody stated;
      * persistence, the regime recomputed on every read, and that the figure the
        worksheet hands the computation IS the engine's house-property head.

NEGATIVE CONTROL
    Against the previous code there is no worksheet at all; with the §24(b) cap
    removed from the module the cap tests fail, and with the self-occupied branch
    treated as let-out the nil-value tests fail.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException

from domain.income_tax import house_property as hp
from domain.income_tax.itr_engine import ITRComputeRequest, itr_engine
from models.income_tax_worksheets import HousePropertyPayload
from routers import income_tax_worksheets as wsr
from services import income_tax_worksheet_service as svc

FY = "2025-26"
FIRM = "f1"
CLIENT = "c1"
CALLER = {"id": "u1", "firm_id": FIRM, "role": "Partner"}
P = hp.Property


def rs(rupees: int) -> int:
    return rupees * 100


def run(properties, *, new=False, fy=FY):
    return hp.compute(list(properties), fy=fy, use_new_regime=new)


def rupees(paise: int) -> int:
    assert paise % 100 == 0, paise
    return paise // 100


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    svc._reset_mock_state()
    monkeypatch.setattr(wsr, "assert_client_access", lambda u, c: None)
    yield
    svc._reset_mock_state()


# ══ a let-out house ══════════════════════════════════════════════════════════

LET_OUT = P("a", "Shop, Andheri", hp.USE_LET_OUT,
            municipal_value_paise=rs(300_000), fair_rent_paise=rs(360_000),
            rent_receivable_paise=rs(420_000), municipal_tax_paid_paise=rs(20_000),
            interest_paise=rs(100_000))


def test_a_let_out_house_takes_the_higher_of_expected_and_actual_rent():
    """Expected rent is the higher of municipal value (3,00,000) and fair rent
    (3,60,000) = 3,60,000; rent receivable is 4,20,000 and is higher, so the
    gross annual value is 4,20,000. Less municipal tax 20,000 = net annual value
    4,00,000. 30% = 1,20,000. Interest 1,00,000. Income 4,00,000 - 1,20,000 -
    1,00,000 = 1,80,000."""
    r = run([LET_OUT]).properties[0]
    assert rupees(r.gross_annual_value_paise) == 420_000
    assert rupees(r.municipal_tax_paise) == 20_000
    assert rupees(r.net_annual_value_paise) == 400_000
    assert rupees(r.standard_deduction_paise) == 120_000
    assert rupees(r.interest_allowed_paise) == 100_000
    assert rupees(r.income_paise) == 180_000


def test_the_expected_rent_wins_where_the_actual_rent_is_lower_and_there_was_no_vacancy():
    """Rent receivable 2,00,000 against an expected 3,60,000 with no vacancy:
    §23(1)(a) takes the higher, so the house is valued at 3,60,000."""
    p = P("a", "Flat", hp.USE_LET_OUT, municipal_value_paise=rs(300_000),
          fair_rent_paise=rs(360_000), rent_receivable_paise=rs(200_000))
    assert rupees(run([p]).properties[0].gross_annual_value_paise) == 360_000


def test_a_vacancy_takes_the_actual_rent_instead():
    """§23(1)(c): vacant for part of the year AND that is why the rent fell
    short — the annual value is the rent actually receivable, 2,00,000."""
    p = P("a", "Flat", hp.USE_LET_OUT, municipal_value_paise=rs(300_000),
          fair_rent_paise=rs(360_000), rent_receivable_paise=rs(200_000),
          vacant_part_of_year=True)
    r = run([p]).properties[0]
    assert rupees(r.gross_annual_value_paise) == 200_000
    assert any("§23(1)(c)" in w for w in r.workings)


def test_a_vacancy_does_not_lower_a_rent_that_was_not_below_expectation():
    p = P("a", "Flat", hp.USE_LET_OUT, municipal_value_paise=rs(300_000),
          rent_receivable_paise=rs(420_000), vacant_part_of_year=True)
    assert rupees(run([p]).properties[0].gross_annual_value_paise) == 420_000


def test_the_standard_rent_caps_the_expected_rent():
    """Expected rent is the higher of 3,00,000 and 3,60,000 but not above the
    standard rent of 3,00,000: 3,00,000. Nothing received, so that is the value."""
    p = P("a", "Controlled", hp.USE_LET_OUT, municipal_value_paise=rs(300_000),
          fair_rent_paise=rs(360_000), standard_rent_paise=rs(300_000))
    assert rupees(run([p]).properties[0].gross_annual_value_paise) == 300_000


def test_unrealised_rent_is_deducted_only_where_rule_4_is_stated_as_met():
    base = dict(municipal_value_paise=rs(100_000), rent_receivable_paise=rs(240_000),
                unrealised_rent_paise=rs(60_000))
    met = run([P("a", "Flat", hp.USE_LET_OUT, unrealised_rent_rule_4_met=True, **base)])
    assert rupees(met.properties[0].gross_annual_value_paise) == 180_000
    for stated in (None, False):
        res = run([P("a", "Flat", hp.USE_LET_OUT, unrealised_rent_rule_4_met=stated, **base)])
        assert rupees(res.properties[0].gross_annual_value_paise) == 240_000
        assert any("Rule 4" in g and "NOT deducted" in g for g in res.gaps), res.gaps


def test_municipal_tax_larger_than_the_value_does_not_make_the_value_negative():
    p = P("a", "Flat", hp.USE_LET_OUT, rent_receivable_paise=rs(10_000),
          municipal_tax_paid_paise=rs(50_000))
    r = run([p]).properties[0]
    assert r.net_annual_value_paise == 0 and r.standard_deduction_paise == 0


def test_a_house_with_neither_municipal_value_nor_fair_rent_says_so():
    res = run([P("a", "Flat", hp.USE_LET_OUT, rent_receivable_paise=rs(240_000))])
    assert any("neither municipal value nor fair rent" in g for g in res.gaps)


# ══ a self-occupied house ════════════════════════════════════════════════════

def sop(interest, **kw):
    kw.setdefault("loan_purpose", hp.PURPOSE_ACQUIRE_OR_CONSTRUCT)
    kw.setdefault("loan_taken_on", date(2015, 6, 1))
    kw.setdefault("completed_on", date(2018, 3, 1))
    return P(kw.pop("key", "s"), kw.pop("name", "Home"), hp.USE_SELF_OCCUPIED,
             interest_paise=rs(interest), **kw)


def test_a_self_occupied_house_has_nil_value_and_the_interest_is_capped_at_two_lakh():
    r = run([sop(250_000)]).properties[0]
    assert r.gross_annual_value_paise == 0 and r.standard_deduction_paise == 0
    assert rupees(r.interest_allowed_paise) == 200_000
    assert rupees(r.interest_disallowed_paise) == 50_000
    assert rupees(r.income_paise) == -200_000


def test_municipal_tax_is_not_deducted_on_a_self_occupied_house():
    r = run([sop(0, municipal_tax_paid_paise=rs(30_000))]).properties[0]
    assert r.municipal_tax_paise == 0 and r.income_paise == 0


@pytest.mark.parametrize("facts,why", [
    (dict(loan_purpose=hp.PURPOSE_REPAIR_OR_RECONSTRUCT), "repair"),
    (dict(loan_taken_on=date(1998, 12, 1)), "before 1-4-1999"),
    (dict(completed_on=date(2021, 4, 1)), "after"),
])
def test_the_lower_cap_applies_where_a_condition_for_the_higher_one_fails(facts, why):
    """Borrowed 1-6-2015 -> the window ends 31-3-2021 (five years from the end
    of FY 2015-16). Completed 1-4-2021 is a day late."""
    r = run([sop(250_000, **facts)]).properties[0]
    assert rupees(r.interest_allowed_paise) == 30_000, why


def test_completion_on_the_last_day_of_the_window_keeps_the_higher_cap():
    r = run([sop(250_000, completed_on=date(2021, 3, 31))]).properties[0]
    assert rupees(r.interest_allowed_paise) == 200_000


def test_missing_loan_facts_take_the_lower_cap_and_say_which_are_missing():
    res = run([P("s", "Home", hp.USE_SELF_OCCUPIED, interest_paise=rs(250_000))])
    assert rupees(res.properties[0].interest_allowed_paise) == 30_000
    gap = " ".join(res.gaps)
    assert "what the loan was for" in gap and "the date the loan was taken" in gap
    assert "the date the house was completed" in gap
    assert "cannot understate income" in gap


def test_the_cap_is_shared_across_both_self_occupied_houses():
    """Each house qualifies for ₹2,00,000, but the limit is one assessee's, so
    1,50,000 + 1,50,000 allows 2,00,000 in all: the first takes its 1,50,000
    and the second only the 50,000 that is left."""
    res = run([sop(150_000, key="a", name="Home 1"), sop(150_000, key="b", name="Home 2")])
    assert [rupees(r.interest_allowed_paise) for r in res.properties] == [150_000, 50_000]
    assert rupees(res.head_income_paise) == -200_000


def test_under_the_new_regime_a_self_occupied_houses_interest_is_not_allowed_at_all():
    r = run([sop(250_000)], new=True)
    assert r.properties[0].interest_allowed_paise == 0
    assert r.properties[0].income_paise == 0
    assert any("§115BAC(2)" in w for w in r.properties[0].workings)


def test_a_third_self_occupied_house_is_refused_because_the_choice_is_the_cas():
    houses = [sop(0, key=k, name=f"Home {k}") for k in "abc"]
    with pytest.raises(hp.WorksheetRefused) as e:
        run(houses)
    assert "§23(4)(b)" in str(e.value) and "deemed let-out" in str(e.value)


# ══ a deemed let-out house ═══════════════════════════════════════════════════

def test_a_deemed_let_out_house_is_valued_at_its_expected_rent():
    """Municipal value 5,00,000, municipal tax 10,000: NAV 4,90,000; 30% =
    1,47,000; interest 50,000; income 2,93,000."""
    p = P("d", "Third house", hp.USE_DEEMED_LET_OUT, municipal_value_paise=rs(500_000),
          municipal_tax_paid_paise=rs(10_000), interest_paise=rs(50_000))
    assert rupees(run([p]).head_income_paise) == 293_000


def test_rent_on_a_deemed_let_out_house_is_refused():
    p = P("d", "Third house", hp.USE_DEEMED_LET_OUT, municipal_value_paise=rs(500_000),
          rent_receivable_paise=rs(100_000))
    with pytest.raises(hp.WorksheetRefused) as e:
        run([p])
    assert "let out" in str(e.value)


# ══ interest on a let-out house, and the five instalments ════════════════════

def test_interest_on_a_let_out_house_is_allowed_in_full_and_may_make_a_loss():
    p = P("a", "Flat", hp.USE_LET_OUT, rent_receivable_paise=rs(240_000),
          municipal_value_paise=rs(240_000), interest_paise=rs(500_000))
    r = run([p])
    assert rupees(r.properties[0].interest_allowed_paise) == 500_000
    # 2,40,000 - 72,000 - 5,00,000
    assert rupees(r.head_income_paise) == -332_000 and r.is_loss


def test_pre_construction_interest_is_one_fifth_a_year_from_the_year_of_completion():
    """5,00,000 of pre-construction interest, completed in FY 2023-24: FY
    2025-26 is the third year, so 1,00,000 is allowed this year."""
    p = P("p", "New flat", hp.USE_LET_OUT, municipal_value_paise=rs(300_000),
          pre_construction_interest_paise=rs(500_000), completion_fy="2023-24")
    r = run([p]).properties[0]
    assert r.pre_construction_instalment_number == 3
    assert rupees(r.pre_construction_instalment_paise) == 100_000
    assert rupees(r.interest_allowed_paise) == 100_000


def test_the_five_instalments_add_up_to_exactly_what_was_paid():
    """₹1,00,001 does not divide by five; the odd paise land in the fifth so no
    paisa of interest is lost to rounding."""
    total = rs(100_001)
    parts = []
    for start in range(2023, 2028):
        p = P("p", "Flat", hp.USE_LET_OUT, pre_construction_interest_paise=total,
              completion_fy="2023-24")
        parts.append(run([p], fy=f"{start}-{str(start + 1)[-2:]}").properties[0]
                     .pre_construction_instalment_paise)
    assert sum(parts) == total
    assert parts[:4] == [total // 5] * 4 and parts[4] == total - 4 * (total // 5)


def test_nothing_falls_before_the_year_of_completion_or_after_the_fifth():
    base = dict(pre_construction_interest_paise=rs(500_000), completion_fy="2023-24")
    assert run([P("p", "F", hp.USE_LET_OUT, **base)], fy="2022-23").properties[0] \
        .pre_construction_instalment_paise == 0
    assert run([P("p", "F", hp.USE_LET_OUT, **base)], fy="2028-29").properties[0] \
        .pre_construction_instalment_paise == 0


def test_pre_construction_interest_with_no_completion_year_is_named_not_allowed():
    res = run([P("p", "F", hp.USE_LET_OUT, pre_construction_interest_paise=rs(500_000))])
    assert res.properties[0].pre_construction_instalment_paise == 0
    assert any("Explanation to §24(b)" in g for g in res.gaps)


def test_the_instalment_sits_inside_the_self_occupied_cap():
    """Current interest 1,50,000 + the instalment 1,00,000 = 2,50,000, capped at
    2,00,000; 50,000 is disallowed."""
    p = sop(150_000, pre_construction_interest_paise=rs(500_000), completion_fy="2023-24",
            loan_taken_on=date(2020, 5, 1), completed_on=date(2023, 6, 1))
    r = run([p]).properties[0]
    assert rupees(r.interest_claimed_paise) == 250_000
    assert rupees(r.interest_allowed_paise) == 200_000
    assert rupees(r.interest_disallowed_paise) == 50_000


# ══ co-owners ════════════════════════════════════════════════════════════════

def test_a_co_owned_house_is_taken_at_the_owners_share_with_their_own_interest():
    """50%: municipal value 4,00,000 -> 2,00,000; rent 6,00,000 -> 3,00,000, which
    is higher; tax 20,000 -> 10,000; NAV 2,90,000; 30% = 87,000; interest is this
    owner's own, 1,00,000 and NOT halved. Income 2,90,000 - 87,000 - 1,00,000 =
    1,03,000."""
    p = P("c", "Shared", hp.USE_LET_OUT, share_bps=5_000, municipal_value_paise=rs(400_000),
          rent_receivable_paise=rs(600_000), municipal_tax_paid_paise=rs(20_000),
          interest_paise=rs(100_000))
    r = run([p]).properties[0]
    assert rupees(r.gross_annual_value_paise) == 300_000
    assert rupees(r.net_annual_value_paise) == 290_000
    assert rupees(r.standard_deduction_paise) == 87_000
    assert rupees(r.income_paise) == 103_000
    assert any("Co-owned" in w for w in r.workings)


def test_a_share_outside_one_to_a_hundred_percent_is_refused():
    for bad in (0, 10_001):
        with pytest.raises(hp.WorksheetRefused):
            run([P("c", "Shared", hp.USE_LET_OUT, share_bps=bad)])


# ══ the head, and what it does not do ════════════════════════════════════════

def test_the_head_is_the_sum_of_the_properties_losses_included():
    res = run([LET_OUT, sop(250_000)])
    assert rupees(res.head_income_paise) == 180_000 - 200_000


def test_a_loss_is_reported_as_a_loss_and_the_set_off_rule_is_left_to_the_engine():
    """§71(3A)'s ₹2,00,000 and §115BAC(2)'s nothing are the ENGINE's rules; the
    worksheet states the head's figure as it is and names that."""
    res = run([sop(400_000, completed_on=date(2018, 3, 1))])
    assert rupees(res.head_income_paise) == -200_000 and res.is_loss
    assert any("§71(3A)" in c and "§115BAC(2)" in c for c in res.caveats)
    src = open(hp.__file__, encoding="utf-8").read()
    assert "LIMIT_SET_OFF_71_3A" not in src, "a second copy of the engine's set-off cap"


def test_what_is_not_modelled_is_named_on_every_answer():
    d = run([LET_OUT]).to_dict()
    assert d["verified"] is False
    assert any("§25A" in c for c in d["not_modelled"])


@pytest.mark.parametrize("bad", [
    dict(use="rented_to_a_dog"),
    dict(municipal_value_paise=-1),
    dict(unrealised_rent_paise=rs(10), rent_receivable_paise=rs(5)),
    dict(loan_purpose="to_buy_a_boat"),
])
def test_what_the_domain_cannot_work_on_is_refused(bad):
    kw = dict(key="x", name="Flat", use=hp.USE_LET_OUT)
    kw.update(bad)
    with pytest.raises(hp.WorksheetRefused):
        run([P(**kw)])


def test_two_properties_with_one_key_are_refused():
    with pytest.raises(hp.WorksheetRefused):
        run([P("a", "One", hp.USE_LET_OUT), P("a", "Two", hp.USE_LET_OUT)])


# ══ it feeds the computation, and the engine agrees ══════════════════════════

@pytest.mark.parametrize("new", [False, True])
def test_the_head_figure_is_exactly_what_the_engine_takes_as_house_property(new):
    """The worksheet's `head_income_paise` goes in the box the engine has always
    read. Where it is positive the engine reports it unchanged as the head; where
    it is a loss the engine applies its own rule to the same figure."""
    res = run([LET_OUT], new=new)
    eng = itr_engine.compute(ITRComputeRequest(
        fy=FY, use_new_regime=new, house_property_income_paise=res.head_income_paise,
        other_income_paise=rs(1_000_000)))
    assert eng.income_heads_paise["house_property"] == res.head_income_paise


def test_a_loss_reaches_the_engine_and_its_own_cap_is_applied_there():
    old = run([sop(400_000)], new=False)
    eng = itr_engine.compute(ITRComputeRequest(
        fy=FY, use_new_regime=False, house_property_income_paise=old.head_income_paise,
        other_income_paise=rs(1_000_000)))
    assert eng.income_heads_paise["house_property"] == -rs(200_000)


# ══ it is kept, and recomputed for the regime asked ══════════════════════════

PAYLOAD = {"properties": [
    {"key": "a", "name": "Shop", "use": "let_out", "municipal_value_paise": rs(300_000),
     "rent_receivable_paise": rs(420_000), "municipal_tax_paid_paise": rs(20_000),
     "interest_paise": rs(100_000)},
    {"key": "s", "name": "Home", "use": "self_occupied", "interest_paise": rs(250_000),
     "loan_purpose": "acquire_construct", "loan_taken_on": "2015-06-01",
     "completed_on": "2018-03-01"},
]}


def _save(payload=None, new=False, fy=FY):
    return wsr.save_worksheet(
        "house_property",
        wsr.SaveWorksheetRequest(client_id=CLIENT, financial_year=fy,
                                 use_new_regime=new, payload=payload or PAYLOAD),
        CALLER)["data"]


def _read(new=False, fy=FY, kind="house_property"):
    return wsr.read_worksheet(kind, CLIENT, fy, new, CALLER)["data"]


def test_the_inputs_are_kept_and_read_back_after_the_call_returns():
    saved = _save()
    assert saved["saved"] is True
    back = _read()
    assert back["saved"] is True
    assert back["payload"]["properties"][1]["loan_taken_on"] == "2015-06-01"
    assert back["result"]["head_income_paise"] == rs(180_000) - rs(200_000)


def test_nothing_derived_is_stored_so_a_regime_flip_recomputes():
    _save(new=False)
    old = _read(new=False)["result"]["head_income_paise"]
    new = _read(new=True)["result"]["head_income_paise"]
    assert old == rs(180_000) - rs(200_000)
    assert new == rs(180_000), "under §115BAC(2) the self-occupied interest is not allowed"
    stored = svc._MOCK_ROWS[(FIRM, CLIENT, FY, "house_property")]["payload_json"]
    assert "head_income_paise" not in str(stored) and "income_paise" not in str(stored)


def test_an_unsaved_year_reads_as_an_empty_worksheet_not_an_error():
    d = _read(fy="2024-25")
    assert d["saved"] is False and d["result"]["head_income_paise"] == 0


def test_a_worksheet_the_domain_refuses_is_not_kept():
    bad = {"properties": [
        {"key": k, "name": k, "use": "self_occupied"} for k in "abc"]}
    with pytest.raises(HTTPException) as e:
        _save(bad)
    assert e.value.status_code == 422 and "§23(4)(b)" in e.value.detail
    assert (FIRM, CLIENT, FY, "house_property") not in svc._MOCK_ROWS


def test_a_malformed_payload_is_a_422_that_names_the_field():
    with pytest.raises(HTTPException) as e:
        _save({"properties": [{"key": "a", "name": "x", "use": "let_out",
                               "interest_paise": -5}]})
    assert e.value.status_code == 422 and "interest_paise" in e.value.detail


def test_an_unknown_field_is_refused_rather_than_silently_dropped():
    with pytest.raises(HTTPException) as e:
        _save({"properties": [{"key": "a", "name": "x", "use": "let_out",
                               "rent_recievable_paise": 5}]})
    assert e.value.status_code == 422


def test_an_unknown_kind_is_a_404():
    with pytest.raises(HTTPException) as e:
        _read(kind="capital_wip")
    assert e.value.status_code == 404


def test_a_worksheet_is_one_firms_and_one_clients():
    _save()
    svc_row = svc._find("other-firm", CLIENT, FY, "house_property")
    assert svc_row is None
    assert svc._find(FIRM, "other-client", FY, "house_property") is None


def test_the_payload_model_and_the_domain_agree_on_the_vocabulary():
    assert set(HousePropertyPayload.model_fields["properties"].annotation.__args__[0]
               .model_fields) >= {"use", "share_bps", "loan_purpose"}
    assert set(svc.KINDS) == {"house_property", "salary"}
