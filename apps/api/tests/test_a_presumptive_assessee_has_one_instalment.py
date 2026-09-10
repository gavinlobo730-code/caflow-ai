"""
IT-06: §234C charged a presumptive assessee for three instalments never due.

WHAT WAS WRONG

`INSTALLMENT_RULES` applied the §208 four-instalment schedule — 15%/45%/75%/100%
on 15 June, 15 September, 15 December and 15 March — to every caller.
`compute_234c_interest` had no assessee parameter and `ComputeAdvanceTaxRequest`
had no field for one. The module's own header said the presumptive case was "out
of scope here" and then computed it anyway, on the wrong schedule.

The PROVISO to §211(1) says it plainly: an eligible assessee in respect of an
eligible business under §44AD, or an eligible profession under §44ADA, "shall
pay the whole amount of such advance tax during each financial year on or before
the 15th day of March". There are no earlier instalments to defer, so §234C has
nothing to charge on those dates. §234C(1)(b) is the matching charging limb and
it is a different sentence from §234C(1)(a): 1% on the shortfall from the tax
due on the returned income, one month, no tolerance.

THE PROBE, from the finding, reproduced below: ₹1,00,000 of estimated tax paid
in full on 15 March 2026 — exactly what the statute requires — came back with
₹450 + ₹1,350 + ₹2,250 = ₹4,050 of interest.

WHAT IT IS NOW

One flag, supplied and never inferred: whether §44AD or §44ADA is opted into is
the CA's determination, and no figure either endpoint receives decides it. It
selects the schedule for the interest computation AND for the stored register,
because four rows beside a one-instalment interest figure is worse than either
being wrong alone. The answer carries `basis` and names the LIMB, not just the
section.
"""
from datetime import date

import pytest

from domain.income_tax.advance_tax_interest_engine import (
    INSTALLMENT_RULES, PRESUMPTIVE_INSTALLMENT_RULES, InstallmentPayment,
    compute_234c_interest, installment_rules, installment_schedule,
)

FY = "2025-26"
LAKH = 1_00_000_00


def _paid_on_15_march(amount=LAKH):
    return [InstallmentPayment(4, amount, date(2026, 3, 15))]


# ══════════════════════════════════════════════════════════════════════════════
# The probe from the finding
# ══════════════════════════════════════════════════════════════════════════════

def test_the_general_schedule_charges_4050_on_a_full_15_march_payment():
    """Kept as the control, because it is CORRECT for an ordinary assessee: they
    owed 15% by 15 June and paid nothing until March."""
    got = compute_234c_interest(FY, LAKH, _paid_on_15_march())
    assert got.total_interest_paise == 4_050_00
    assert [i.interest_paise for i in got.installments] == [450_00, 1_350_00, 2_250_00, 0]


def test_a_presumptive_assessee_who_pays_in_full_on_15_march_owes_nothing():
    """The statute's own deadline, met exactly. Anything but zero is interest on
    an obligation that did not exist."""
    got = compute_234c_interest(FY, LAKH, _paid_on_15_march(),
                                is_presumptive_44ad_44ada=True)
    assert got.total_interest_paise == 0
    assert len(got.installments) == 1
    assert got.installments[0].due_date == date(2026, 3, 15)


# ══════════════════════════════════════════════════════════════════════════════
# The schedule
# ══════════════════════════════════════════════════════════════════════════════

def test_there_is_exactly_one_instalment_and_it_is_15_march():
    assert installment_schedule(FY, is_presumptive_44ad_44ada=True) == [
        (4, date(2026, 3, 15))]
    assert len(installment_schedule(FY)) == 4


def test_the_single_instalment_keeps_number_4():
    """Not 1. It is the same 15 March date as the general schedule's fourth, and
    a stored advance_tax_payments row is keyed on (client, FY,
    installment_number) — numbering it 1 would put a presumptive client's
    15 March payment in a general client's 15 June slot in every query that
    reads the number."""
    (rule,) = PRESUMPTIVE_INSTALLMENT_RULES
    assert rule.number == 4
    assert rule.number == INSTALLMENT_RULES[-1].number


def test_it_has_no_tolerance_and_one_month():
    """§234C(1)(a)'s 12%/36% tolerance belongs to the first two instalments of
    the four-instalment schedule. §234C(1)(b) has none."""
    (rule,) = PRESUMPTIVE_INSTALLMENT_RULES
    assert rule.cumulative_required_percent == 100
    assert rule.trigger_percent == 100
    assert rule.interest_months == 1


def test_installment_rules_picks_the_schedule():
    assert installment_rules() is INSTALLMENT_RULES
    assert installment_rules(is_presumptive_44ad_44ada=True) is PRESUMPTIVE_INSTALLMENT_RULES


# ══════════════════════════════════════════════════════════════════════════════
# What it still charges
# ══════════════════════════════════════════════════════════════════════════════

def test_a_short_payment_on_15_march_is_charged_1_percent_for_one_month():
    """§234C(1)(b): 1% on the shortfall from 100%, one month. ₹40,000 short of
    ₹1,00,000 → ₹400."""
    got = compute_234c_interest(FY, LAKH, _paid_on_15_march(60_000_00),
                                is_presumptive_44ad_44ada=True)
    assert got.installments[0].shortfall_paise == 40_000_00
    assert got.total_interest_paise == 400_00


def test_paying_nothing_is_charged_on_the_whole_liability():
    got = compute_234c_interest(FY, LAKH, [], is_presumptive_44ad_44ada=True)
    assert got.installments[0].shortfall_paise == LAKH
    assert got.total_interest_paise == 1_000_00


def test_paying_late_is_charged_the_same_fixed_one_month():
    """§234C prescribes a FIXED period, not the actual delay — that is §234B's
    shape, and conflating them is the defect this module's header records the
    frontend having made. A payment on 30 June is still one month."""
    late = [InstallmentPayment(4, LAKH, date(2026, 6, 30))]
    got = compute_234c_interest(FY, LAKH, late, is_presumptive_44ad_44ada=True)
    assert got.installments[0].interest_months == 1
    assert got.total_interest_paise == 1_000_00, (
        "the payment landed after 15 March, so nothing counts toward it")


def test_an_earlier_payment_counts_toward_the_15_march_total():
    """Paying early is not a default. Advance tax paid in September is advance
    tax paid before 15 March."""
    early = [InstallmentPayment(2, LAKH, date(2025, 9, 15))]
    got = compute_234c_interest(FY, LAKH, early, is_presumptive_44ad_44ada=True)
    assert got.total_interest_paise == 0


def test_no_liability_is_no_interest_on_either_basis():
    for flag in (False, True):
        got = compute_234c_interest(FY, 0, [], is_presumptive_44ad_44ada=flag)
        assert got.total_interest_paise == 0 and got.installments == tuple()
        assert got.is_presumptive_44ad_44ada is flag, (
            "even an empty answer has to say which schedule it was empty under")


# ══════════════════════════════════════════════════════════════════════════════
# The answer says which branch it took
# ══════════════════════════════════════════════════════════════════════════════

def test_the_basis_names_the_proviso_and_the_limb():
    got = compute_234c_interest(FY, LAKH, [], is_presumptive_44ad_44ada=True)
    assert got.is_presumptive_44ad_44ada is True
    assert "211(1)" in got.basis and "44AD" in got.basis and "234C(1)(b)" in got.basis
    assert "15 March" in got.basis


def test_the_general_basis_names_the_other_limb():
    got = compute_234c_interest(FY, LAKH, [])
    assert got.is_presumptive_44ad_44ada is False
    assert "§208" in got.basis and "234C(1)(a)" in got.basis


# ══════════════════════════════════════════════════════════════════════════════
# The endpoints — the half that makes it reachable
# ══════════════════════════════════════════════════════════════════════════════

def test_the_compute_endpoint_carries_the_flag_and_names_the_limb():
    import routers.income_tax as it
    body = it.ComputeAdvanceTaxRequest(
        fy=FY, estimated_tax_paise=LAKH,
        installments=[it.AdvanceTaxInstallmentInput(
            installment_number=4, paid_amount_paise=LAKH, paid_date=date(2026, 3, 15))],
        is_presumptive_44ad_44ada=True)
    got = it._at_response(body.estimated_tax_paise, body.installments, body.fy,
                          is_presumptive_44ad_44ada=body.is_presumptive_44ad_44ada)
    assert got["total_interest_paise"] == 0
    assert got["section_ref"] == "Section 234C(1)(b)"
    assert got["is_presumptive_44ad_44ada"] is True
    assert len(got["installments"]) == 1

    ordinary = it._at_response(body.estimated_tax_paise, body.installments, body.fy)
    assert ordinary["total_interest_paise"] == 4_050_00
    assert ordinary["section_ref"] == "Section 234C(1)(a)"


def test_the_flag_defaults_to_the_general_schedule():
    """Nobody's interest changes because a field was added. The presumptive
    scheme is opted into, so the default has to be the other one."""
    import routers.income_tax as it
    assert it.ComputeAdvanceTaxRequest(
        fy=FY, estimated_tax_paise=LAKH).is_presumptive_44ad_44ada is False
    assert compute_234c_interest(FY, LAKH, []).is_presumptive_44ad_44ada is False


def test_the_save_endpoint_writes_one_row_and_clears_the_other_three(monkeypatch):
    """The register and the interest must not disagree. Four stored rows beside
    a one-instalment computation is worse than either being wrong alone — and an
    upsert alone would leave the §208 rows behind, where a real paid_date reads
    as a payment against a live obligation."""
    import routers.income_tax as it
    from tests.e2e_harness import FakeDB, wire_e2e

    db = FakeDB()
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    wire_e2e(monkeypatch, db, [it])
    db.seed("clients", {"id": "cli-1", "firm_id": "firm-1"})
    caller = {"firm_id": "firm-1", "id": "u-1", "auth_user_id": "auth-1",
              "role": "Partner"}

    general = it.SaveAdvanceTaxRequest(client_id="cli-1", fy=FY,
                                       estimated_tax_paise=LAKH, installments=[])
    it.save_advance_tax(req=general, current_user=caller)
    assert sorted(r["installment_number"] for r in db.rows("advance_tax_payments")) == [1, 2, 3, 4]

    presumptive = it.SaveAdvanceTaxRequest(client_id="cli-1", fy=FY,
                                           estimated_tax_paise=LAKH, installments=[],
                                           is_presumptive_44ad_44ada=True)
    it.save_advance_tax(req=presumptive, current_user=caller)
    rows = db.rows("advance_tax_payments")
    assert [r["installment_number"] for r in rows] == [4], rows
    assert rows[0]["required_percent"] == 100
    assert rows[0]["due_date"] == "2026-03-15"
