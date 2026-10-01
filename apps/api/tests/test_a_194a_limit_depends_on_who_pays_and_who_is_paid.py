"""Section 194A's limit depends on who PAYS and who is PAID, not on the payee alone
(TDS-30).

WHAT THE REGISTRY SAID

    One ₹10,000 limit for every §194A payment, and a comment recording the
    Finance Act 2025 limits for a deposit with a bank (₹50,000) and for a senior
    citizen's deposit (₹1,00,000) as "not modelled — payer type isn't modelled,
    so the lowest applies". Safe, and over-withholding where the section does not
    charge: a co-operative bank withheld on ₹30,000 of deposit interest.

WHAT THE FINDING SUGGESTED, AND WHY THIS IS NOT THAT

    "Bank, senior citizen, other" read as three PAYEE classes. §194A(3)(i)'s
    senior-citizen limit exists only INSIDE the bank-deposit limb — the payer is a
    bank, a co-operative bank or a post office. A company paying a pensioner
    interest on an unsecured loan withholds at ₹10,000 whoever is paid, so
    granting ₹1,00,000 on the payee's age alone would have UNDER-deducted on the
    commonest §194A payment a practice sees, and an under-deduction disallows 30%
    of the expenditure under §40(a)(ia) where an over-deduction is the payee's to
    reclaim. The class is the PRODUCT of the two facts, and `senior` alone is not
    an answer — it is refused.

WHICH CLIENTS' FIGURES CHANGE

    None on the day this lands. The class is a new nullable supplier column
    (migration 454, no backfill) and NULL takes the section's own ₹10,000. A
    figure moves only for a supplier a CA explicitly records as a deposit with a
    bank, and never for a financial year before 2025-26, where the raised limits
    did not exist.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import routers.vendors as ve
from domain.tds import section_rates as sr
from domain.tds.tds_computer import TDSComputer
from models.parties import VendorIn, VendorUpdateIn
from services import vendor_tds

FY = "2025-26"
ENGINE = TDSComputer()


def _rs(n: int) -> int:
    return n * 100


def _resolve(amount_rs: int, klass, fy=FY, **kw):
    return ENGINE.resolve_tds("194A", _rs(amount_rs), fy=fy, threshold_class=klass, **kw)


# ── the three limits, at the amounts the finding names ───────────────────────

@pytest.mark.parametrize("klass,limit_rs", [
    (None, 10_000),
    ("ordinary", 10_000),
    ("bank_deposit", 50_000),
    ("bank_deposit_senior", 1_00_000),
])
def test_each_class_is_tested_against_its_own_limit(klass, limit_rs):
    """At the limit nothing is withheld (the section charges a sum that EXCEEDS
    it); one rupee over, the whole payment is charged — which is the shape of
    §194A(3)(i)'s own wording and not a marginal-slice rule."""
    at = _resolve(limit_rs, klass)
    over = _resolve(limit_rs + 1, klass)
    assert at.applies is False and at.tds_paise == 0
    assert over.applies is True
    assert over.tds_paise == _rs(limit_rs + 1) * 1000 // 10000
    assert at.threshold_paise == _rs(limit_rs)


@pytest.mark.parametrize("amount_rs,expected_by_class", [
    (9_999, {None: 0, "ordinary": 0, "bank_deposit": 0, "bank_deposit_senior": 0}),
    (50_000, {None: 5_000, "ordinary": 5_000, "bank_deposit": 0,
              "bank_deposit_senior": 0}),
    (1_00_000, {None: 10_000, "ordinary": 10_000, "bank_deposit": 10_000,
                "bank_deposit_senior": 0}),
])
def test_the_amounts_the_finding_names(amount_rs, expected_by_class):
    for klass, expected_rs in expected_by_class.items():
        assert _resolve(amount_rs, klass).tds_paise == _rs(expected_rs), (
            klass, amount_rs)


def test_a_payee_that_is_a_senior_citizen_is_not_an_answer_by_itself():
    """The part of the finding that would under-deduct: the senior-citizen limit
    only exists where the payer is a bank. A bare 'senior' is refused rather
    than read as ₹1,00,000."""
    with pytest.raises(ValueError, match="no threshold class 'senior'"):
        _resolve(60_000, "senior")
    assert sr.threshold_class_problem("194A", "senior")


def test_the_default_for_a_supplier_nobody_classified_is_the_lowest_limit():
    """Every supplier that existed before the column did."""
    assert _resolve(30_000, None).applies is True
    assert sr.tds_rates_for(FY).sections["194A"].single_threshold_paise == _rs(10_000)


# ── the FY aggregate moves with the class ────────────────────────────────────

def test_the_aggregate_limb_takes_the_class_limit_too():
    """§194A(3)(i) names one amount for 'the amount or ... the aggregate of the
    amounts', so the class replaces BOTH limbs. Two ₹30,000 payments to a
    deposit-holder stay under ₹50,000 individually and cross it together: the
    second one carries the year's tax."""
    first = _resolve(30_000, "bank_deposit")
    assert first.applies is False
    second = _resolve(30_000, "bank_deposit",
                      fy_prior_taxable_paise=_rs(30_000), fy_prior_tds_paise=0)
    assert second.applies is True
    assert second.tds_paise == _rs(60_000) * 1000 // 10000


def test_an_ordinary_supplier_crosses_the_aggregate_earlier():
    """Same two payments, no class: ₹10,000 is crossed by the first."""
    assert _resolve(30_000, None).applies is True


# ── a class belongs to a section that has it ─────────────────────────────────

def test_a_raising_class_on_a_section_with_one_limit_is_refused_not_ignored():
    with pytest.raises(ValueError, match="has no threshold class"):
        ENGINE.resolve_tds("194J", _rs(60_000), fy=FY, threshold_class="bank_deposit")


def test_ordinary_is_inert_on_every_section():
    plain = ENGINE.resolve_tds("194J", _rs(60_000), fy=FY)
    said = ENGINE.resolve_tds("194J", _rs(60_000), fy=FY, threshold_class="ordinary")
    assert said.tds_paise == plain.tds_paise and said.applies == plain.applies


@pytest.mark.parametrize("section,klass,refused", [
    ("194A", "bank_deposit", False),
    ("194a", "bank_deposit_senior", False),
    ("194J", "bank_deposit", True),
    ("194J(B)", "bank_deposit_senior", True),
    ("194C", "bank_deposit", True),
    ("194J", "ordinary", False),
    ("194J", None, False),
    (None, "bank_deposit", False),   # judged when the section arrives
    ("194A", "bank_deposit_senor", True),
])
def test_the_one_question_every_door_asks(section, klass, refused):
    assert bool(sr.threshold_class_problem(section, klass)) is refused


# ── years before the raised limits ───────────────────────────────────────────

def test_a_class_is_ignored_for_a_year_before_the_raised_limits():
    """Finance Act 2025 raised these from 01-04-2025. `tds_rates_for` SUBSTITUTES
    the latest year for an earlier one, so without this a bill for FY 2024-25
    would take FY 2025-26's ₹50,000 from a year that had ₹40,000. The figure is
    exactly what it was before the class existed."""
    plain = _resolve(30_000, None, fy="2024-25")
    classed = _resolve(30_000, "bank_deposit_senior", fy="2024-25")
    assert classed.tds_paise == plain.tds_paise > 0
    assert classed.threshold_class is None, "reports what was APPLIED, not asked"
    assert _resolve(30_000, "bank_deposit", fy=FY).threshold_class == "bank_deposit"


def test_the_first_year_is_a_named_constant_and_the_figures_are_pinned():
    """Every figure here is `[S]`-graded — egress is refused in this environment,
    so §194A(3)(i) and the Finance Act could not be opened — and says so."""
    assert sr.SECTION_194A_CLASS_THRESHOLDS_FIRST_FY == "2025-26"
    assert sr.THRESHOLD_CLASSES_194A_VERIFIED is False
    assert sr.tds_rates_for(FY).sections["194A"].class_thresholds_paise == {
        "bank_deposit": 50_000_00, "bank_deposit_senior": 1_00_000_00}
    assert sr.ALL_THRESHOLD_CLASSES == ("ordinary", "bank_deposit",
                                        "bank_deposit_senior")


def test_only_194a_carries_classes():
    carrying = [s for s, r in sr.tds_rates_for(FY).sections.items()
                if r.class_thresholds_paise]
    assert carrying == ["194A"]


def test_the_screens_are_served_the_classes_and_never_spell_a_limit():
    served = sr.threshold_classes_for("194A", FY)
    assert [c["key"] for c in served] == ["ordinary", "bank_deposit",
                                          "bank_deposit_senior"]
    assert [c["threshold_paise"] for c in served] == [10_000_00, 50_000_00, 1_00_000_00]
    assert sr.threshold_classes_for("194J", FY) == []
    assert sr.threshold_classes_for("not-a-section", FY) == []


# ── the supplier doors ───────────────────────────────────────────────────────

def _vendor(**over):
    base = dict(client_id="C1", name="Depositor", tds_applicable=True,
                tds_section="194A", pan="AAAPB1234C")
    base.update(over)
    return base


def test_create_normalises_and_accepts_a_class_on_194a():
    v = VendorIn(**_vendor(interest_threshold_class=" Bank_Deposit "))
    assert v.interest_threshold_class == "bank_deposit"


def test_create_refuses_a_class_on_another_section_and_a_made_up_one():
    with pytest.raises(ValidationError, match="only s.194A carries"):
        VendorIn(**_vendor(tds_section="194J", interest_threshold_class="bank_deposit"))
    with pytest.raises(ValidationError, match="must be one of"):
        VendorIn(**_vendor(interest_threshold_class="senior"))


def test_update_door_refuses_the_same_two_things():
    with pytest.raises(ValidationError, match="only s.194A carries"):
        VendorUpdateIn(tds_section="194C", interest_threshold_class="bank_deposit_senior")
    with pytest.raises(ValidationError, match="must be one of"):
        VendorUpdateIn(interest_threshold_class="senior_citizen")


@pytest.fixture
def stored(monkeypatch):
    monkeypatch.setattr(ve, "can_access_client", lambda u, c: True)
    monkeypatch.setattr(ve, "assert_client_access", lambda u, c: None)
    monkeypatch.setattr(ve, "_USE_MOCK", True)
    row = {"id": "V1", "firm_id": "F", "client_id": "C1", "name": "Depositor",
           "tds_section": "194A", "interest_threshold_class": "bank_deposit"}
    monkeypatch.setattr(ve, "MOCK_VENDORS", [row])
    return row


USER = {"id": "u", "firm_id": "F", "role": "Partner", "auth_user_id": "a"}


def test_a_patch_moving_the_section_off_194a_is_refused_while_a_class_stands(stored):
    """The model sees only the request. A PATCH carrying just the section would
    leave a stale 'bank_deposit' on a row whose section cannot honour it, and
    every later bill would refuse — so the merged row is asked."""
    with pytest.raises(HTTPException) as e:
        ve.update_vendor("V1", VendorUpdateIn(tds_section="194J"), current_user=USER)
    assert e.value.status_code == 422
    assert "only s.194A carries" in e.value.detail
    assert stored["tds_section"] == "194A"


def test_a_patch_can_take_a_class_back_with_the_word_for_it(stored):
    """PATCH drops a null, so 'ordinary' is how a wrong class is withdrawn."""
    out = ve.update_vendor("V1", VendorUpdateIn(interest_threshold_class="ordinary"),
                           current_user=USER)
    assert out["data"]["interest_threshold_class"] == "ordinary"
    # ...and with the class withdrawn the section may move.
    out = ve.update_vendor("V1", VendorUpdateIn(tds_section="194J"), current_user=USER)
    assert out["data"]["tds_section"] == "194J"


# ── the bill path ────────────────────────────────────────────────────────────

def _withhold(vendor, amount_rs, on="2025-08-10"):
    return vendor_tds.resolve_resident_tds(
        vendor, vendor.get("tds_section"), _rs(amount_rs), on, "F", None)


def test_a_bill_reads_the_class_off_the_supplier():
    base = {"id": "V1", "pan": "AAAPB1234C", "tds_section": "194A"}
    ordinary = _withhold(base, 30_000)
    deposit = _withhold({**base, "interest_threshold_class": "bank_deposit"}, 30_000)
    assert ordinary.tds_paise == _rs(3_000)
    assert deposit.tds_paise == 0
    assert "₹50,000" in deposit.why and "bank, co-operative bank or post office" in deposit.why


def test_a_bill_over_the_class_limit_says_which_limit_it_was_tested_against():
    out = _withhold({"id": "V1", "pan": "AAAPB1234C", "tds_section": "194A",
                     "interest_threshold_class": "bank_deposit_senior"}, 1_50_000)
    assert out.tds_paise == _rs(15_000)
    assert "₹1,00,000" in out.why and "senior citizen" in out.why


def test_a_bill_dated_before_the_raised_limits_ignores_the_class():
    v = {"id": "V1", "pan": "AAAPB1234C", "tds_section": "194A",
         "interest_threshold_class": "bank_deposit_senior"}
    assert (_withhold(v, 30_000, on="2024-08-10").tds_paise
            == _withhold({**v, "interest_threshold_class": None}, 30_000,
                         on="2024-08-10").tds_paise > 0)


def test_a_stale_class_on_another_section_refuses_the_bill_with_the_sentence():
    with pytest.raises(HTTPException) as e:
        _withhold({"id": "V1", "pan": "AAAPB1234C", "tds_section": "194J",
                   "interest_threshold_class": "bank_deposit"}, 60_000)
    assert e.value.status_code == 422
    assert "has no threshold class" in e.value.detail
