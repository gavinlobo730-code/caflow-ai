"""
The Income-tax Act 2025 renumbering: both vocabularies, permanently.

WHAT THESE PROTECT

The 2025 Act changed the LABELS and left the NUMBERS alone. That is the
dangerous shape: every rate in domain/tds/section_rates.py is still right, so
nothing fails, and a statement goes out under a form number the portal rejects
or a section code that draws a correction statement.

So the weight here is on the two directions the fix could go wrong:

  * treating this as a MIGRATION — the old names must keep working for old
    periods for ever, because a belated or revised FY 2025-26 return is still
    Form 24Q citing s. 192, and there is no date after which that stops;
  * treating it as COSMETIC — the section code that reaches a deductee row and
    the form number on a working paper are both statutory content, not labels.

And on the refusals. The s. 393 payment-code table is not held, s. 393(1) has no
reverse, and a form number derived from today's date instead of the period is
exactly the bug this module exists to prevent — so each is asserted to refuse
rather than to guess.
"""
from __future__ import annotations

from datetime import date

import pytest

from domain.tds import vocabulary as v
from domain.tds.vocabulary import (
    ACT_1961, ACT_2025, NON_RESIDENT, RESIDENT_NON_SALARY, SALARY, TCS,
    VocabularyError,
)


# ── Which Act governs ────────────────────────────────────────────────────────

def test_commencement_is_the_first_of_april_2026():
    assert v.COMMENCEMENT == date(2026, 4, 1)


@pytest.mark.parametrize("d,expect", [
    (date(2026, 3, 31), ACT_1961),   # the last day of the old Act
    (date(2026, 4, 1), ACT_2025),    # commencement itself is the new Act
    (date(2020, 1, 1), ACT_1961),
    (date(2030, 1, 1), ACT_2025),
])
def test_the_act_is_decided_by_the_event_date(d, expect):
    assert v.act_for_date(d) == expect


def test_no_financial_year_straddles_commencement():
    """Why act_for_fy is sound rather than an approximation: 1 April 2026 IS an
    FY boundary, so a whole return is always on one side."""
    assert v.act_for_fy("2025-26") == ACT_1961
    assert v.act_for_fy("2026-27") == ACT_2025


def test_the_fy_rule_and_the_event_rule_agree():
    """A bill credited 25-03-2026 and paid 10-04-2026 has its event on the
    EARLIER of the two — 25 March — which is FY 2025-26, which is the 1961 Act.
    Both rules must say so, for the same reason."""
    assert v.act_for_date(date(2026, 3, 25)) == v.act_for_fy("2025-26")


def test_a_label_that_is_not_a_financial_year_is_refused():
    with pytest.raises(VocabularyError):
        v.act_for_fy("last year")


# ── The old names never stop working ─────────────────────────────────────────

@pytest.mark.parametrize("kind,expect", [
    (SALARY, "24Q"), (RESIDENT_NON_SALARY, "26Q"),
    (NON_RESIDENT, "27Q"), (TCS, "27EQ"),
])
def test_an_old_period_keeps_its_own_forms_indefinitely(kind, expect):
    """A belated or revised FY 2025-26 statement filed today is still 24Q.
    Commencement does not disturb obligations that arose under the 1961 Act,
    and there is no date after which this stops being true."""
    assert v.statement_form(kind, fy_label="2025-26") == expect


def test_an_old_period_keeps_its_own_section_codes():
    for section in ("192", "194C", "194J", "195", "206C"):
        assert v.section_code(section, fy_label="2025-26") == section


# ── The new names ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind,expect", [
    (SALARY, "138"), (RESIDENT_NON_SALARY, "140"),
    (NON_RESIDENT, "144"), (TCS, "143"),
])
def test_a_current_period_uses_the_2025_act_forms(kind, expect):
    assert v.statement_form(kind, fy_label="2026-27") == expect


@pytest.mark.parametrize("old,new", [
    ("192", "392"),
    ("195", "393(2)"),     # NOT 400 — s. 400(2) is the unrelated DTAA-circular
                           # provision, and one secondary source had this wrong
    ("206C", "394"),
    ("139", "263"),
])
def test_the_one_to_one_section_moves(old, new):
    assert v.section_code(old, fy_label="2026-27") == new


@pytest.mark.parametrize("section", ["194A", "194C", "194H", "194I", "194J", "194Q"])
def test_the_whole_194_series_collapses_into_one_umbrella(section):
    assert v.section_code(section, fy_label="2026-27") == "393(1)"


def test_195_did_not_become_400():
    """Pinned on its own because a widely-copied source says 400 and getting it
    wrong puts an invented section on a filed statement."""
    assert v.section_code("195", fy_label="2026-27") == "393(2)"
    assert v.section_code("195", fy_label="2026-27") != "400"


# ── The certificates, and what changed BESIDES the number ────────────────────

@pytest.mark.parametrize("kind,old,new", [
    ("salary_certificate", "16", "130"),
    ("non_salary_certificate", "16A", "131"),
    ("tax_credit_statement", "26AS", "168"),
    ("no_deduction_declaration", "15G/15H", "121"),
])
def test_the_certificates_are_renumbered(kind, old, new):
    assert v.certificate_form(kind, fy_label="2025-26") == old
    assert v.certificate_form(kind, fy_label="2026-27") == new


def test_form_131_is_quarterly_and_says_so():
    """The trap: renumber 16A to 131 and keep the annual cadence, and you issue
    one certificate where four are due. The number is not the whole change."""
    note = v.certificate_note("non_salary_certificate", fy_label="2026-27")
    assert note and "QUARTERLY" in note


def test_form_130_has_three_parts_and_says_so():
    note = v.certificate_note("salary_certificate", fy_label="2026-27")
    assert note and "THREE" in note


def test_the_old_certificates_carry_no_change_note():
    assert v.certificate_note("salary_certificate", fy_label="2025-26") is None


# ── The refusals ─────────────────────────────────────────────────────────────

def test_a_form_cannot_be_asked_for_without_a_period():
    """Defaulting to today would file a belated FY 2025-26 statement on Form
    138. Refusing is the entire point of the parameter."""
    with pytest.raises(VocabularyError) as exc:
        v.statement_form(SALARY)
    assert "exactly one" in str(exc.value)


def test_giving_both_a_period_and_a_date_is_also_refused():
    with pytest.raises(VocabularyError):
        v.statement_form(SALARY, fy_label="2026-27", event_date=date(2025, 5, 1))


def test_393_1_has_no_reverse():
    """The 194-series collapsed into it, so asking which of 194C, 194J or 194H a
    line was means inventing one."""
    with pytest.raises(VocabularyError) as exc:
        v.section_1961_for("393(1)")
    assert "no single 1961-Act section" in str(exc.value)


@pytest.mark.parametrize("new,old", [("392", "192"), ("393(2)", "195"), ("394", "206C")])
def test_the_one_to_one_moves_do_reverse(new, old):
    assert v.section_1961_for(new) == old


def test_an_unknown_section_is_refused_rather_than_passed_through():
    """Passing an unmapped code straight through would put a 1961-Act section on
    a 2025-Act statement while looking like it had been translated."""
    with pytest.raises(VocabularyError):
        v.section_code("196D", fy_label="2026-27")


def test_the_payment_code_table_is_named_as_a_gap_not_invented():
    """Sixty-seven guessed codes would be sixty-seven wrong labels — and a wrong
    payment code is ACCEPTED and then wrong, which is worse than a rejection."""
    gap = v.payment_code_gap()
    assert gap.field == "tds_payment_code"
    assert "1001-1067" in gap.note
    assert "does not hold" in gap.note


def test_only_a_2025_act_period_carries_the_payment_code_gap():
    assert v.vocabulary_for("2025-26").gaps() == []
    assert [g.field for g in v.vocabulary_for("2026-27").gaps()] == ["tds_payment_code"]


# ── The bundle ───────────────────────────────────────────────────────────────

def test_the_bundle_cannot_mix_halves():
    """Naming a statement Form 138 and then citing s. 192 on its lines is only
    possible if the two are resolved separately. The bundle resolves the Act
    once."""
    old = v.vocabulary_for("2025-26")
    assert (old.statement(SALARY), old.section("192")) == ("24Q", "192")
    new = v.vocabulary_for("2026-27")
    assert (new.statement(SALARY), new.section("192")) == ("138", "392")


def test_the_bundle_names_the_act():
    assert v.vocabulary_for("2025-26").act_name == "Income-tax Act, 1961"
    assert v.vocabulary_for("2026-27").act_name == "Income-tax Act, 2025"
    assert v.vocabulary_for("2026-27").is_2025_act


# ── What must NOT have changed ───────────────────────────────────────────────

def test_the_rate_registry_is_still_keyed_by_1961_sections():
    """Rekeying section_rates.py would destroy the older half of history. The
    rates are unchanged and the keys stay; vocabulary.py translates at the
    boundary instead."""
    from domain.tds.section_rates import tds_rates_for
    sections = tds_rates_for("2026-27").sections
    assert "194C" in sections and "192" in sections
    assert "393(1)" not in sections


def test_the_rates_themselves_did_not_move():
    """Substantively unchanged, which is exactly why nothing failed loudly."""
    from domain.tds.section_rates import tds_rates_for
    before = tds_rates_for("2025-26").sections["194C"]
    after = tds_rates_for("2026-27").sections["194C"]
    assert (before.individual_rate_bps, before.company_rate_bps,
            before.single_threshold_paise) == (
           after.individual_rate_bps, after.company_rate_bps,
           after.single_threshold_paise)


def test_itr_forms_are_not_renumbered():
    """CBDT notified ITR-1..7 for AY 2026-27 under the 1961 Act, because
    AY 2026-27 covers FY 2025-26. Nothing in domain/income_tax/ moves here, and
    a vocabulary that claimed otherwise would rename seven schemas that are
    still current."""
    from domain.income_tax.itr_schema import SCHEMA_FILES
    assert SCHEMA_FILES, "no ITR schemas registered — the import is wrong"
    assert all(str(k).upper().startswith("ITR") for k in SCHEMA_FILES)


# ── Where the vocabulary meets stored data ───────────────────────────────────

def _challan(section):
    return {"section": section, "tds_paise": 15_000_00, "challan_no": "1",
            "bsr_code": "0510308", "payment_date": "2026-05-05"}


@pytest.mark.parametrize("stored_section", ["192", "392"])
def test_a_salary_challan_is_found_under_either_section_label(stored_section):
    """A challan is a record of a deposit somebody typed in, and which label
    they used depends on when they typed it and what the portal showed them —
    not on which Act governs the quarter it is matched to. Accepting only the
    period's own name would drop the deposit and raise "no challan recorded"
    against a quarter that was paid on time."""
    from domain.payroll import form24q as f24

    class _Row:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    src = f24.build_24q_from_payroll(
        slips_by_month={"2026-04": [{"employee_id": "E1",
                                     "gross_paise": 30_000_00,
                                     "tds_paise": 15_000_00}]},
        employees_by_id={"E1": {"id": "E1", "name": "Asha Rao",
                                "pan": "ABCDE1234F"}},
        challans=[_challan(stored_section)],
        record_cls=_Row,
        financial_year="2026-27",
    )
    assert len(src.challans) == 1, f"a challan stored as {stored_section!r} was dropped"
    assert not any("challan" in p.lower() for p in src.problems)


def test_the_working_paper_names_the_periods_form_and_section():
    """The CSV outlives the screen that produced it. A working paper headed
    "Form 24Q" for a 2026-27 quarter is a document a CA would take to the portal
    and have rejected."""
    from domain.payroll import form24q as f24
    text = f24.to_csv(f24.Form24QSource(),
                      financial_year="2026-27", quarter="Q1").decode("utf-8-sig")
    assert "Form 138" in text and "s.392" in text
    assert "Form 24Q" not in text
    # And the gap rides on the file, because nothing else tells the CA a column
    # is missing.
    assert "1001-1067" in text


def test_an_old_period_working_paper_still_says_24q():
    from domain.payroll import form24q as f24
    text = f24.to_csv(f24.Form24QSource(),
                      financial_year="2025-26", quarter="Q4").decode("utf-8-sig")
    assert "Form 24Q" in text and "s.192" in text
    assert "1001-1067" not in text
