"""ESI contributions round UP to the next whole rupee, not to the paise.

THE RULE AND WHERE IT COMES FROM

ESIC's own user manual for filing the monthly contribution, describing the
figure the portal computes for you on the online-entry screen:

    "Employee Contribution will be calculated and displayed.
     This is rounded to next higher rupee."

The same rounding has applied to the EMPLOYER's share since October 2004.
"Next higher rupee" is a ceiling: any fraction of a rupee goes up, so 1 paise
over rounds exactly like 99 paise over.

WHAT WAS WRONG

_compute_esi floored to the paise — `math.floor(gross * bps / 10000)` — and the
paise is not a unit ESI works in. On ₹15,500 of wages the employee share is
₹116.25 exactly: we deducted and posted ₹116.25 while the portal raises the
challan for ₹117.

That is short, in the same direction, on every employee whose wages are not a
clean multiple, every month. Under-remitted ESI is the employer's liability
with interest — the same reasoning the Rule 50 fix in _compute_esi rests on.

These cases are worked by hand from the rates in domain/payroll/statutory.py
(employee 0.75%, employer 3.25%), NOT by re-running the implementation.
"""
import math

import pytest

from routers.payroll import _compute_esi, _esi_share_paise

FY = "2026-27"


def _rs(paise: int) -> str:
    return f"₹{paise / 100:,.2f}"


# (gross rupees, employee rupees, employer rupees), each computed by hand.
#   15,500 -> 0.75% = 116.25 -> 117 ; 3.25% = 503.75 -> 504
#   18,750 -> 0.75% = 140.625 -> 141 ; 3.25% = 609.375 -> 610
#   12,345 -> 0.75% =  92.5875 -> 93 ; 3.25% = 401.2125 -> 402
#    9,999 -> 0.75% =  74.9925 -> 75 ; 3.25% = 324.9675 -> 325
CASES = [
    (15_500, 117, 504),
    (18_750, 141, 610),
    (12_345, 93, 402),
    (9_999, 75, 325),
]


@pytest.mark.parametrize("gross_rs,employee_rs,employer_rs", CASES)
def test_both_shares_round_up_to_the_next_rupee(gross_rs, employee_rs, employer_rs):
    got = _compute_esi(gross_rs * 100, FY)
    assert got["employee"] == employee_rs * 100, (
        f"employee share on {_rs(gross_rs * 100)}: expected {_rs(employee_rs * 100)}, "
        f"got {_rs(got['employee'])}")
    assert got["employer"] == employer_rs * 100, (
        f"employer share on {_rs(gross_rs * 100)}: expected {_rs(employer_rs * 100)}, "
        f"got {_rs(got['employer'])}")


@pytest.mark.parametrize("gross_rs", [20_000, 12_000, 4_000])
def test_an_exact_rupee_is_not_bumped(gross_rs):
    """A ceiling that rounds an exact figure up is not a ceiling, it is +1.

    0.75% and 3.25% of a multiple of ₹400 are both whole rupees, so these come
    out exact and must stay where they are.
    """
    got = _compute_esi(gross_rs * 100, FY)
    # gross_rs x 100 paise x bps / 10000 == gross_rs x bps / 100, in paise.
    assert got["employee"] == gross_rs * 75 // 100
    assert got["employer"] == gross_rs * 325 // 100


@pytest.mark.parametrize("bps", [75, 325])
def test_every_share_is_a_whole_number_of_rupees(bps):
    """The property, not four examples of it.

    Whatever the wages, an ESI share never carries paise. Swept across a range
    that crosses many rupee boundaries so a rounding rule that happens to work
    on the four hand-worked cases cannot pass by luck.
    """
    for wages_rs in range(1, 21_001, 7):
        share = _esi_share_paise(wages_rs * 100, bps)
        assert share % 100 == 0, f"{wages_rs} at {bps}bps gave {_rs(share)}"


@pytest.mark.parametrize("bps", [75, 325])
def test_the_share_is_never_below_the_exact_amount(bps):
    """Rounding UP is the direction that cannot under-remit.

    The employer carries the shortfall on an under-remittance, with interest.
    So the invariant worth pinning is not "close to exact" but "never under",
    and never more than 99 paise over it either.
    """
    for wages_rs in range(1, 21_001, 13):
        wages_paise = wages_rs * 100
        exact = wages_paise * bps / 10_000
        share = _esi_share_paise(wages_paise, bps)
        assert share >= exact, f"{wages_rs} at {bps}bps: {_rs(share)} < exact {exact}"
        assert share - exact < 100, f"{wages_rs} at {bps}bps rounded up too far"
        assert share == math.ceil(exact / 100) * 100


def test_nothing_is_due_above_the_ceiling_for_someone_not_already_covered():
    """The rounding change must not disturb the Rule 50 behaviour around it.

    Zero is zero; a ceiling applied to nothing must not produce a rupee.
    """
    assert _compute_esi(30_000 * 100, FY) == {"employee": 0, "employer": 0}
    assert _compute_esi(0, FY) == {"employee": 0, "employer": 0}
