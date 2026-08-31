"""
The EPFO Electronic Challan cum Return.

ECR 2.0 is a text file, one line per member, eleven `#~#`-separated fields in
whole rupees:

    UAN, MEMBER_NAME, GROSS_WAGES, EPF_WAGES, EPS_WAGES, EDLI_WAGES,
    EPF_CONTRI_REMITTED, EPS_CONTRI_REMITTED, EPF_EPS_DIFF_REMITTED,
    NCP_DAYS, REFUND_OF_ADVANCES

THE ONE ROW WORTH KNOWING BY HEART

An employee on ₹15,000 PF wages and ₹25,000 gross, present all month:

    …#~#25000#~#15000#~#15000#~#15000#~#2350#~#1250#~#1100#~#0#~#0

EPF remitted is 2350 because it is the EMPLOYEE's ₹1,800 PLUS the employer's
₹550 EPF half — not the employee's alone, which is the mistake this format
invites. EPS is ₹1,250 and the difference is ₹1,100.

WHAT THIS MODULE DOES NOT DO, AND WHY THAT IS THE POINT

It computes nothing. Every figure is read off the payslip that was finalised and
posted to the ledger, so the return and the books cannot disagree. The only
derived field is the EPF−EPS difference, which EPFO asks for explicitly.

THE REFUSALS MATTER AS MUCH AS THE FILE

The portal rejects a malformed batch after upload, by which time the CA has lost
the round trip. Each rule below is checked here and named per member instead.
"""
from __future__ import annotations

import pytest

from domain.payroll.ecr import build_ecr, ECRMember, DELIMITER

CEILING = 15_000_00          # paise
R = 100


def _slip(**over) -> dict:
    base = dict(
        employee_id="e1",
        basic_paise=15_000_00, da_paise=0, gross_paise=25_000_00,
        pf_employee_paise=1_800_00,
        pf_employer_paise=1_800_00,
        pf_employer_eps_paise=1_250_00,
        pf_employer_epf_paise=550_00,
        lop_days=0,
    )
    base.update(over)
    return base


def _emp(**over) -> dict:
    base = dict(id="e1", name="Asha Kumar", uan="100200300400",
                pf_applicable=True, eps_eligible=True)
    base.update(over)
    return base


def _build(slips=None, emps=None, days=30):
    slips = slips or [_slip()]
    emps = emps or [_emp()]
    return build_ecr(slips=slips, employees_by_id={e["id"]: e for e in emps},
                     days_in_month=days, wage_ceiling_paise=CEILING)


# ── the canonical line ───────────────────────────────────────────────────────

def test_the_reference_line_is_exactly_right():
    f = _build()
    assert f.problems == []
    assert f.to_text() == DELIMITER.join([
        "100200300400", "ASHA KUMAR", "25000", "15000", "15000", "15000",
        "2350", "1250", "1100", "0", "0",
    ])


def test_epf_remitted_is_employee_plus_employer_epf_not_employee_alone():
    """The mistake this format invites. 1800 + 550, not 1800."""
    f = _build()
    assert f.to_text().split(DELIMITER)[6] == "2350"


def test_the_difference_field_is_epf_minus_eps():
    m = ECRMember(uan="1", name="X", gross_wages=25000, epf_wages=15000,
                  eps_wages=15000, edli_wages=15000, epf_contribution=2350,
                  eps_contribution=1250, ncp_days=0)
    assert m.epf_eps_difference == 1100


def test_wages_are_capped_at_the_ceiling_but_gross_is_not():
    """Gross wages are the real gross — EPFO wants what the member was paid.
    Only the three statutory wage fields take the ceiling."""
    f = _build([_slip(basic_paise=40_000_00, gross_paise=60_000_00)])
    parts = f.to_text().split(DELIMITER)
    assert parts[2] == "60000"                      # gross, uncapped
    assert parts[3] == parts[4] == parts[5] == "15000"


# ── EPS exclusion ────────────────────────────────────────────────────────────

def test_a_member_outside_the_pension_scheme_files_zero_eps_wages():
    """EPS 1995 para 6 as amended by GSR 609(E): joined on or after 01-09-2014
    above the ceiling, so the whole employer share is EPF. Claiming EPS WAGES
    against a nil EPS CONTRIBUTION is a line the portal rejects."""
    f = _build([_slip(pf_employer_eps_paise=0, pf_employer_epf_paise=1_800_00)],
               [_emp(eps_eligible=False)])
    assert f.problems == []
    parts = f.to_text().split(DELIMITER)
    assert parts[4] == "0", "EPS wages must be nil when there is no EPS contribution"
    assert parts[7] == "0"
    assert parts[6] == "3600"        # employee 1800 + employer EPF 1800


# ── what it refuses ──────────────────────────────────────────────────────────

def test_a_member_without_a_uan_is_refused_by_name():
    f = _build(emps=[_emp(uan=None)])
    assert f.members == []
    assert any("Asha Kumar" in p and "UAN" in p for p in f.problems), f.problems
    assert not f.is_filable


@pytest.mark.parametrize("bad", ["1234", "10020030040A", "1002003004000"])
def test_a_uan_that_is_not_twelve_digits_is_refused(bad):
    f = _build(emps=[_emp(uan=bad)])
    assert f.members == []
    assert any("12 digits" in p for p in f.problems), f.problems


def test_a_split_that_does_not_reconcile_is_refused():
    """The check that catches a slip written before migration 295, where both
    halves default to zero — which would otherwise file a nil contribution
    against a real employer payment."""
    f = _build([_slip(pf_employer_eps_paise=0, pf_employer_epf_paise=0)])
    assert f.members == []
    assert any("does not equal" in p for p in f.problems), f.problems


def test_more_non_contributory_days_than_the_month_has_is_refused():
    f = _build([_slip(lop_days=31)], days=30)
    assert f.members == []
    assert any("31 non-contributory days in a 30-day month" in p for p in f.problems)


def test_absent_all_month_but_contributing_is_refused():
    """EPFO's own rule: NCP equal to the days in the month means no
    contribution can be shown."""
    f = _build([_slip(lop_days=30)], days=30)
    assert f.members == []
    assert any("absent the whole month" in p for p in f.problems), f.problems


def test_absent_all_month_with_no_contribution_is_accepted():
    f = _build([_slip(lop_days=30, pf_employee_paise=0, pf_employer_paise=0,
                      pf_employer_eps_paise=0, pf_employer_epf_paise=0)], days=30)
    assert f.problems == []
    assert f.to_text().split(DELIMITER)[9] == "30"


def test_a_non_contributory_employee_is_left_off_entirely():
    """The ECR is a return of contributions. Someone who is not a PF member is
    not a nil row on it — they are absent."""
    f = _build([_slip(pf_employee_paise=0, pf_employer_paise=0,
                      pf_employer_eps_paise=0, pf_employer_epf_paise=0)],
               [_emp(pf_applicable=False)])
    assert f.members == []
    assert f.problems == []          # not an error, just not a member


# ── the file as a whole ──────────────────────────────────────────────────────

def test_one_bad_member_makes_the_whole_file_unfilable():
    """A partial upload is worse than none: the portal takes the batch, and the
    missing member is discovered a quarter later."""
    f = _build([_slip(), _slip(employee_id="e2")],
               [_emp(), _emp(id="e2", name="Bad One", uan=None)])
    assert len(f.members) == 1
    assert not f.is_filable


def test_totals_are_reported_for_the_challan():
    f = _build([_slip(), _slip(employee_id="e2")],
               [_emp(), _emp(id="e2", name="Second")])
    t = f.totals()
    assert t["members"] == 2
    assert t["eps_contribution"] == 2500        # 1250 x 2
    assert t["epf_contribution"] == 4700        # 2350 x 2


def test_a_name_carrying_the_delimiter_cannot_shift_the_columns():
    """Found by this test. "Odd#~#Name" produced a twelfth field, so every
    column after the name moved by one and the wages landed in the contribution
    columns — a well-formed line carrying the wrong numbers, which the portal
    would happily accept."""
    f = _build(emps=[_emp(name="Odd#~#Name")])
    line = f.to_text()
    assert line.count(DELIMITER) == 10, "eleven fields means exactly ten delimiters"
    assert line.split(DELIMITER)[1] == "ODD NAME"
    assert line.split(DELIMITER)[2] == "25000", "gross must still be in field 3"


@pytest.mark.parametrize("raw,expect", [
    ("Odd#~#Name", "ODD NAME"),
    ("Two\nLines", "TWO LINES"),
    ("Carriage\rReturn", "CARRIAGE RETURN"),
    ("  spaced   out  ", "SPACED OUT"),
    ("Hash#Only", "HASH ONLY"),
])
def test_names_are_sanitised_without_being_second_guessed(raw, expect):
    f = _build(emps=[_emp(name=raw)])
    assert f.to_text().split(DELIMITER)[1] == expect


def test_a_newline_in_a_name_cannot_split_one_member_into_two():
    """The file is one line per member; a name with a newline in it would make
    the second half a malformed extra row."""
    f = _build(emps=[_emp(name="Two\nLines")])
    assert len(f.to_text().splitlines()) == 1
