"""The salary worksheet is Schedule S, and feeds the engine (TDS-INCOME-TAX-15).

WHAT WAS WRONG
    Gross salary was one typed figure. An HRA helper existed and payroll has a
    perquisites module, but neither fed a Schedule S view: allowances, §17(2)
    perquisites including ESOP and RSU, §10 exemptions and a previous employer's
    salary were not itemised, so the return asked for the parts and the product
    held a total. A client with two employers in a year was the common case and
    the one it could not show.

WHAT IS ASSERTED, HAND-WORKED IN RUPEES
    Two employers (one the previous employer), a motor-car perquisite, an RSU
    exercise, LTA, professional tax and HRA:

        employer 1   salary 12,00,000 + perquisite 30,000 + RSU 100 x ₹500 =
                     50,000                                    = 12,80,000
        employer 2   salary 4,00,000                           =  4,00,000
        gross                                                    16,80,000

    OLD REGIME. LTA 20,000 and professional tax 2,400 come off, leaving
    16,57,600 — the engine's one salary box. HRA (basic 6,00,000, HRA received
    2,00,000, rent 2,40,000, not metro) is the least of 2,00,000, 40% of basic =
    2,40,000 and rent less 10% of basic = 1,80,000, so 1,80,000. The standard
    deduction is 50,000, taken ONCE. Income chargeable 16,57,600 - 1,80,000 -
    50,000 = 14,27,600.

    NEW REGIME. LTA, professional tax and HRA are withdrawn by §115BAC(2): none is
    deducted, the standard deduction is 75,000, income chargeable 16,05,000.

    And the reconciliation with the engine: Schedule S's income equals the
    engine's salary head LESS the HRA exemption, because the engine reports
    salary before HRA and takes HRA off gross total income separately.

NEGATIVE CONTROL
    There was no worksheet before. With the regime gate removed from the
    exemption branch the new-regime tests fail; with the standard deduction taken
    per employer the 'once' test fails; with the ESOP perquisite allowed to go
    negative the below-price test fails.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from domain.income_tax import schedule_s as ss
from domain.income_tax.itr_engine import HRADetails, ITRComputeRequest, itr_engine
from models.income_tax_worksheets import SalaryPayload
from routers import income_tax_worksheets as wsr
from services import income_tax_worksheet_service as svc

FY = "2025-26"
FIRM = "f1"
CLIENT = "c1"
CALLER = {"id": "u1", "firm_id": FIRM, "role": "Partner"}


def rs(rupees: int) -> int:
    return rupees * 100


def rupees(paise: int) -> int:
    assert paise % 100 == 0, paise
    return paise // 100


EMPLOYERS = [
    ss.Employer(
        "e1", "Zenith Systems", salary_17_1_paise=rs(1_200_000),
        perquisites=(ss.PerquisiteLine("motor_car", rs(30_000), "Company car"),),
        esop_exercises=(ss.EsopExercise("RSU vest", 100, rs(500), 0),),
        professional_tax_paise=rs(2_400),
        exemptions=(ss.ExemptionLine("lta_10_5", rs(20_000)),)),
    ss.Employer("e0", "Kaveri Traders", is_previous_employer=True,
                salary_17_1_paise=rs(400_000)),
]
HRA = ss.Hra(basic_salary_paise=rs(600_000), hra_received_paise=rs(200_000),
             rent_paid_paise=rs(240_000))


def run(employers=EMPLOYERS, *, new=False, hra=HRA):
    return ss.compute(list(employers), fy=FY, use_new_regime=new, hra=hra)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    svc._reset_mock_state()
    monkeypatch.setattr(wsr, "assert_client_access", lambda u, c: None)
    yield
    svc._reset_mock_state()


# ══ the blocks ═══════════════════════════════════════════════════════════════

def test_each_employer_is_its_own_block_with_the_forms_lines():
    r = run()
    first, prev = r.employers
    assert rupees(first.salary_17_1_paise) == 1_200_000
    assert rupees(first.perquisites_17_2_paise) == 30_000
    assert rupees(first.esop_perquisite_paise) == 50_000
    assert rupees(first.gross_salary_paise) == 1_280_000
    assert prev.is_previous_employer and rupees(prev.gross_salary_paise) == 400_000
    assert rupees(r.gross_salary_paise) == 1_680_000


def test_profits_in_lieu_of_salary_are_a_line_of_their_own():
    e = ss.Employer("e", "Acme", salary_17_1_paise=rs(500_000),
                    profits_in_lieu_17_3_paise=rs(100_000))
    assert rupees(run([e], hra=ss.Hra()).employers[0].gross_salary_paise) == 600_000


# ══ ESOP and RSU ═════════════════════════════════════════════════════════════

def test_an_esop_perquisite_is_fair_value_less_the_price_paid_times_the_shares():
    """200 shares, FMV ₹1,500, exercise price ₹400: 200 x 1,100 = 2,20,000."""
    ex = ss.EsopExercise("ESOP 2023", 200, rs(1_500), rs(400))
    assert rupees(ss.esop_perquisite_paise(ex)) == 220_000


def test_a_grant_exercised_at_or_above_its_fair_value_gives_no_perquisite_not_a_negative_one():
    """A negative perquisite would reduce the salary a second time."""
    for price in (rs(500), rs(800)):
        ex = ss.EsopExercise("underwater", 100, rs(500), price)
        assert ss.esop_perquisite_paise(ex) == 0
    e = ss.Employer("e", "Acme", salary_17_1_paise=rs(500_000),
                    esop_exercises=(ss.EsopExercise("underwater", 100, rs(500), rs(800)),))
    r = run([e], hra=ss.Hra()).employers[0]
    assert r.esop_perquisite_paise == 0 and rupees(r.gross_salary_paise) == 500_000
    assert any("no perquisite" in w for w in r.workings)


def test_an_rsu_is_an_esop_with_nothing_paid():
    assert rupees(ss.esop_perquisite_paise(ss.EsopExercise("RSU", 100, rs(500), 0))) == 50_000


def test_the_start_up_deferment_is_named_not_modelled():
    assert any("§192(1C)" in c for c in run().caveats)


# ══ the old regime ═══════════════════════════════════════════════════════════

def test_the_old_regime_schedule_s_works_out_as_hand_calculated():
    r = run(new=False)
    assert rupees(r.exemptions_allowed_paise) == 20_000
    assert rupees(r.professional_tax_paise) == 2_400
    assert rupees(r.hra_exemption_paise) == 180_000
    assert rupees(r.standard_deduction_paise) == 50_000
    assert rupees(r.income_chargeable_paise) == 1_427_600
    assert rupees(r.engine_inputs["gross_salary_paise"]) == 1_657_600


def test_the_standard_deduction_is_taken_once_across_the_employers_not_per_employer():
    r = run(new=False)
    # Two employers each large enough to carry ₹50,000: once means 50,000, not
    # 1,00,000.
    assert rupees(r.standard_deduction_paise) == 50_000


def test_the_standard_deduction_is_never_more_than_the_salary_it_comes_from():
    e = ss.Employer("e", "Tiny", salary_17_1_paise=rs(30_000))
    r = run([e], hra=ss.Hra())
    assert rupees(r.standard_deduction_paise) == 30_000
    assert r.income_chargeable_paise == 0


# ══ the new regime ═══════════════════════════════════════════════════════════

def test_the_new_regime_withdraws_lta_professional_tax_and_hra_and_says_so():
    r = run(new=True)
    assert r.exemptions_allowed_paise == 0 and r.professional_tax_paise == 0
    assert r.hra_exemption_paise == 0
    assert rupees(r.standard_deduction_paise) == 75_000
    assert rupees(r.income_chargeable_paise) == 1_605_000
    first = r.employers[0]
    assert any("Leave travel concession" in w and "§115BAC(2)" in w for w in first.workings)
    assert any("Professional tax" in w for w in first.workings)
    assert any("House rent allowance is not exempt" in g for g in r.gaps)


def test_the_retirement_exemptions_survive_the_new_regime():
    e = ss.Employer("e", "Acme", salary_17_1_paise=rs(2_000_000),
                    exemptions=(ss.ExemptionLine("gratuity_10_10", rs(500_000)),
                                ss.ExemptionLine("leave_encashment_10_10aa", rs(100_000)),
                                ss.ExemptionLine("official_duty_allowance_10_14_i", rs(10_000)),
                                ss.ExemptionLine("education_hostel_10_14_ii", rs(9_600))))
    r = run([e], new=True, hra=ss.Hra())
    assert rupees(r.exemptions_allowed_paise) == 610_000  # the last is withdrawn
    old = run([e], new=False, hra=ss.Hra())
    assert rupees(old.exemptions_allowed_paise) == 619_600


def test_an_exemption_larger_than_the_salary_is_limited_and_named():
    e = ss.Employer("e", "Acme", salary_17_1_paise=rs(100_000),
                    exemptions=(ss.ExemptionLine("gratuity_10_10", rs(250_000)),))
    r = run([e], hra=ss.Hra())
    assert rupees(r.employers[0].exemptions_allowed_paise) == 100_000
    assert any("exceed this employer's gross salary" in g for g in r.gaps)
    assert r.income_chargeable_paise == 0


# ══ it is the engine's salary income ═════════════════════════════════════════

def _engine(sal, new):
    return itr_engine.compute(ITRComputeRequest(
        fy=FY, use_new_regime=new,
        gross_salary_paise=sal.engine_inputs["gross_salary_paise"],
        hra=HRADetails(**sal.engine_inputs["hra"])))


@pytest.mark.parametrize("new", [False, True])
def test_schedule_s_income_is_the_engines_salary_head_less_the_hra_exemption(new):
    """The verification the finding asks for: a fixture with two employers, an
    RSU perquisite and HRA produces a Schedule S whose head total equals the
    engine's salary income — less HRA, which the engine takes off gross total
    income separately and which this module names rather than hides."""
    sal = run(new=new)
    eng = _engine(sal, new)
    assert sal.income_chargeable_paise == (
        eng.income_heads_paise["salary"] - eng.deduction_hra_paise)
    assert eng.standard_deduction_paise == sal.standard_deduction_paise


def test_the_engines_hra_is_the_same_function_so_the_two_cannot_disagree():
    sal = run(new=False)
    eng = _engine(sal, False)
    assert eng.deduction_hra_paise == sal.hra_exemption_paise == HRADetails(
        basic_salary_paise=HRA.basic_salary_paise, hra_received_paise=HRA.hra_received_paise,
        rent_paid_paise=HRA.rent_paid_paise).exemption_paise()


def test_with_no_hra_the_head_total_is_exactly_the_engines():
    sal = run(hra=ss.Hra(), new=False)
    eng = _engine(sal, False)
    assert sal.income_chargeable_paise == eng.income_heads_paise["salary"]


# ══ refusals ═════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("bad", [
    dict(salary_17_1_paise=-1),
    dict(professional_tax_paise=-1),
    dict(perquisites=(ss.PerquisiteLine("a_pony", 100),)),
    dict(exemptions=(ss.ExemptionLine("a_gift", 100),)),
    dict(esop_exercises=(ss.EsopExercise("x", -1, 1, 1),)),
])
def test_what_the_domain_cannot_work_on_is_refused(bad):
    with pytest.raises(ss.WorksheetRefused):
        run([ss.Employer("e", "Acme", **bad)], hra=ss.Hra())


def test_two_employers_with_one_key_are_refused():
    with pytest.raises(ss.WorksheetRefused):
        run([ss.Employer("e", "A"), ss.Employer("e", "B")], hra=ss.Hra())


def test_the_hra_figures_cannot_be_negative():
    with pytest.raises(ss.WorksheetRefused):
        run([ss.Employer("e", "A")], hra=ss.Hra(rent_paid_paise=-1))


def test_every_answer_says_it_is_unverified_and_names_what_it_leaves_out():
    d = run().to_dict()
    assert d["verified"] is False
    assert any("§16(ii)" in c for c in d["not_modelled"])


def test_the_exemption_vocabulary_says_which_survive_the_new_regime():
    """Pinned exactly — every row is [S]-graded."""
    assert {k: v[1] for k, v in ss.EXEMPTION_KINDS.items()} == {
        "gratuity_10_10": True, "leave_encashment_10_10aa": True,
        "commuted_pension_10_10a": True, "vrs_10_10c": True,
        "official_duty_allowance_10_14_i": True, "lta_10_5": False,
        "education_hostel_10_14_ii": False, "other_10": False,
    }


# ══ it is kept, and recomputed for the regime asked ══════════════════════════

PAYLOAD = {
    "employers": [
        {"key": "e1", "name": "Zenith Systems", "tan": "mumz12345a",
         "salary_17_1_paise": rs(1_200_000),
         "perquisites": [{"kind": "motor_car", "amount_paise": rs(30_000), "description": "Company car"}],
         "esop_exercises": [{"description": "RSU vest", "shares": 100,
                             "fmv_per_share_paise": rs(500), "exercise_price_per_share_paise": 0}],
         "professional_tax_paise": rs(2_400),
         "exemptions": [{"kind": "lta_10_5", "amount_paise": rs(20_000)}]},
        {"key": "e0", "name": "Kaveri Traders", "is_previous_employer": True,
         "salary_17_1_paise": rs(400_000)},
    ],
    "hra": {"basic_salary_paise": rs(600_000), "hra_received_paise": rs(200_000),
            "rent_paid_paise": rs(240_000), "is_metro": False},
}


def _save(payload=None, new=False):
    return wsr.save_worksheet(
        "salary",
        wsr.SaveWorksheetRequest(client_id=CLIENT, financial_year=FY, use_new_regime=new,
                                 payload=payload or PAYLOAD), CALLER)["data"]


def _read(new=False):
    return wsr.read_worksheet("salary", CLIENT, FY, new, CALLER)["data"]


def test_the_inputs_are_kept_and_read_back_and_a_tan_is_normalised():
    _save()
    back = _read()
    assert back["saved"] is True
    assert back["payload"]["employers"][0]["tan"] == "MUMZ12345A"
    assert back["result"]["income_chargeable_paise"] == rs(1_427_600)


def test_the_regime_is_recomputed_on_every_read_and_never_stored():
    _save(new=False)
    assert _read(new=False)["result"]["income_chargeable_paise"] == rs(1_427_600)
    assert _read(new=True)["result"]["income_chargeable_paise"] == rs(1_605_000)
    stored = str(svc._MOCK_ROWS[(FIRM, CLIENT, FY, "salary")]["payload_json"])
    assert "income_chargeable" not in stored and "standard_deduction" not in stored


def test_a_malformed_tan_or_kind_is_a_422_naming_the_field():
    bad = {"employers": [{"key": "e", "name": "A", "tan": "NOT-A-TAN"}]}
    with pytest.raises(HTTPException) as e:
        _save(bad)
    assert e.value.status_code == 422 and "tan" in e.value.detail
    bad = {"employers": [{"key": "e", "name": "A",
                          "exemptions": [{"kind": "a_gift", "amount_paise": 1}]}]}
    with pytest.raises(HTTPException) as e:
        _save(bad)
    assert e.value.status_code == 422 and "kind" in e.value.detail
    assert (FIRM, CLIENT, FY, "salary") not in svc._MOCK_ROWS


def test_a_negative_amount_or_an_unknown_field_is_refused_at_the_door():
    for bad in ({"employers": [{"key": "e", "name": "A", "salary_17_1_paise": -5}]},
                {"employers": [{"key": "e", "name": "A", "salary": 5}]}):
        with pytest.raises(HTTPException) as e:
            _save(bad)
        assert e.value.status_code == 422


def test_the_salary_and_house_property_worksheets_do_not_share_a_row():
    _save()
    assert wsr.read_worksheet("house_property", CLIENT, FY, False, CALLER)["data"]["saved"] is False


def test_the_kinds_the_service_the_router_and_the_migration_agree_on():
    import re
    from pathlib import Path
    sql = (Path(__file__).resolve().parents[1] / "migrations"
           / "455_income_tax_worksheets_and_ais_decisions.sql").read_text(encoding="utf-8")
    m = re.search(r"worksheet_kind IN \((.*?)\)\)", sql, re.S)
    assert m
    assert set(re.findall(r"'([^']+)'", m.group(1))) == set(svc.KINDS) == set(wsr.KINDS)
