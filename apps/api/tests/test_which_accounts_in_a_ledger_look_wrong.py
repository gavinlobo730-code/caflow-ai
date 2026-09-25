"""
`domain/accounting/ledger_anomalies` — which accounts a CA should go and look at.

EVERY ASSERTION HERE IS ABOUT A JUDGEMENT CALL, so the tests are written to pin
the EXCLUSIONS as hard as the detections. A check of this kind fails in one of
two ways and only one of them is visible: it can miss a misposting, or it can
flag forty ordinary accounts until the CA stops reading the screen. The second
is the likelier and the more expensive, and it is what the contra and
bank-overdraft carve-outs exist for.
"""
from __future__ import annotations

import pytest

from domain.accounting import ledger_anomalies as la


def acct(**kw) -> la.LedgerAccount:
    base = dict(id="a1", code="1100", name="Trade Receivables",
                type="Asset", subtype="Receivable", system_key=None)
    base.update(kw)
    return la.LedgerAccount(**base)


def months(*nets: int, start_month: int = 4, year: int = 2025) -> list[la.MonthlyMovement]:
    out = []
    m, y = start_month, year
    for n in nets:
        out.append(la.MonthlyMovement(period_month=f"{y}-{m:02d}-01", net_paise=n))
        m += 1
        if m == 13:
            m, y = 1, y + 1
    return out


def kinds(anomalies) -> list[str]:
    return [a.kind for a in anomalies]


# ── The normal side of an account type ───────────────────────────────────────

@pytest.mark.parametrize("account_type,expected", [
    ("Asset", "Dr"), ("Expense", "Dr"),
    ("Liability", "Cr"), ("Equity", "Cr"), ("Revenue", "Cr"),
    # The legacy mock's spelling, which domain/reporting/model.INCOME_TYPES
    # carries beside "Revenue" — this module reads that constant rather than
    # restating the pair.
    ("Income", "Cr"),
])
def test_each_account_type_has_a_normal_side(account_type, expected):
    assert la.normal_side(account_type) == expected


def test_an_unrecognised_type_is_a_third_state_and_never_read_as_debit():
    """`chart_of_accounts.account_type` has a CHECK over five values, so an
    unrecognised one means the vocabulary MOVED. Guessing "Dr" would flag every
    account of the new type as contra on the day it is added."""
    assert la.normal_side("Contingency") is None
    assert la.normal_side(None) is None
    assert la.normal_side("") is None

    a = acct(type="Contingency")
    assert kinds(la.scan([a], {"a1": months(-5_000_00)})) == []


# ── 1. A balance on the side its type does not carry ─────────────────────────

def test_an_asset_closing_in_credit_is_flagged():
    found = la.scan([acct()], {"a1": months(-5_000_00)})
    assert kinds(found) == [la.CONTRA_BALANCE]
    assert found[0].amount_paise == -5_000_00


def test_a_liability_closing_in_debit_is_flagged():
    a = acct(id="l1", code="2100", name="Trade Payables",
             type="Liability", subtype="Payable")
    found = la.scan([a], {"l1": months(7_000_00)})
    assert kinds(found) == [la.CONTRA_BALANCE]


def test_an_ordinary_balance_says_nothing():
    assert la.scan([acct()], {"a1": months(5_000_00)}) == ()


def test_accumulated_depreciation_is_not_flagged_under_either_of_its_seeded_subtypes():
    """Migration 054 gives it the subtype 'Contra Asset'; migration 093's chart
    gives the SAME account 'Fixed Asset'. A subtype test alone is right about
    one of them and silent on the other, so the name is tested too — and this
    account is in permanent credit, so getting it wrong would put a finding on
    every client, every month, for ever."""
    for subtype in ("Contra Asset", "Fixed Asset"):
        a = acct(id="d1", code="1520", name="Accumulated Depreciation",
                 type="Asset", subtype=subtype)
        assert la.scan([a], {"d1": months(-40_00_000)}) == (), subtype


@pytest.mark.parametrize("name", [
    "Accumulated Depreciation", "Accumulated Amortisation",
    "Accumulated Amortization", "Provision for Doubtful Debts",
    "Allowance for Credit Losses", "Partner's Drawings",
])
def test_every_contra_name_fragment_suppresses_the_flag(name):
    a = acct(id="c1", name=name, type="Asset", subtype="Current Asset")
    assert la.scan([a], {"c1": months(-9_00_000)}) == ()


def test_a_bank_account_in_overdraft_is_not_a_finding():
    """A current account goes overdrawn; the bank prints it as a negative
    balance (BANK-21). A client running a separate OD or card facility has a
    LIABILITY ledger for it, which is credit-normal and was never a candidate."""
    for subtype, key in (("Bank", None), ("Cash", None), ("Current Asset", "bank")):
        a = acct(id="b1", code="1010", name="HDFC Current Account",
                 type="Asset", subtype=subtype, system_key=key)
        assert la.scan([a], {"b1": months(-3_00_000)}) == (), (subtype, key)


def test_a_credit_card_ledger_is_credit_normal_so_nothing_special_is_needed():
    """domain/banking/account_kind._LEDGER_SHAPES makes the card's ledger a
    Liability, so its credit balance is its normal side and no carve-out is
    involved — asserted so a later reader does not add one."""
    a = acct(id="cc", code="2210", name="HDFC Credit Card",
             type="Liability", subtype="Credit Card")
    assert la.scan([a], {"cc": months(-1_50_000)}) == ()


def test_a_contra_balance_below_the_floor_is_a_rounding_artefact():
    below = la.DEFAULT_MATERIALITY_PAISE - 1
    assert la.scan([acct()], {"a1": months(-below)}) == ()
    at = la.DEFAULT_MATERIALITY_PAISE
    assert kinds(la.scan([acct()], {"a1": months(-at)})) == [la.CONTRA_BALANCE]


def test_the_floor_is_a_parameter_the_caller_can_raise():
    found = la.scan([acct()], {"a1": months(-5_000_00)},
                    materiality_paise=10_000_00)
    assert found == ()


def test_every_anomaly_carries_the_innocent_reading():
    """An anomaly with no benign explanation would be a defect and would belong
    in one of the engine's other, invariant-asserting checks."""
    a = acct()
    b = acct(id="s1", code="5001", name="Salaries", type="Expense",
             subtype="Employee Benefits")
    found = la.scan(
        [a, b],
        {"a1": months(-5_000_00),
         "s1": months(50_000_00, 50_000_00, 50_000_00, 50_000_00,
                      50_000_00, 500_000_00)},
    )
    assert len(found) == 2
    for anomaly in found:
        assert len(anomaly.also_could_be) >= 60
        assert anomaly.summary.endswith(".")


# ── 2. Carries a balance and has been still for a year ──────────────────────
#
# ⚠️ THE FIRST DRAFT OF THIS CHECK COULD NEVER FIRE, and these tests are what
# said so. It asked for a material closing balance AND every month nil — but
# the closing balance IS the sum of the months, so the two conditions are
# contradictory and the branch was unreachable. The tests written against it
# were passing by asserting the emptiness, which is the shape to watch for: a
# test that pins a dead branch reads exactly like a test that pins a narrow
# rule. Each one below now asserts the rule the check was always about — the
# balance is inception-to-date, the silence is recent.

def test_a_deposit_nobody_has_touched_for_a_year_is_flagged():
    dep = acct(id="d1", code="1190", name="Sundry Deposits",
               type="Asset", subtype="Current Asset")
    sal = acct(id="s1", code="5001", name="Salaries", type="Expense")
    found = la.scan(
        [dep, sal],
        {"d1": [la.MonthlyMovement("2024-04-01", 9_00_000)],
         "s1": months(*([50_000_00] * 6))},
    )
    dormant = [x for x in found if x.kind == la.DORMANT_BALANCE]
    assert len(dormant) == 1
    assert dormant[0].account_id == "d1"
    assert dormant[0].amount_paise == 9_00_000
    assert "2024-04" in dormant[0].summary


def test_dormancy_is_measured_against_the_end_of_the_BOOKS_not_the_account():
    """Per account it would be circular — an account's own last movement is
    zero months before itself, so nothing could ever be dormant. The question
    is "the client kept trading and this account did not"."""
    dep = acct(id="d1", name="Sundry Deposits", type="Asset", subtype="Current Asset")
    alone = la.scan([dep], {"d1": [la.MonthlyMovement("2024-04-01", 9_00_000)]})
    assert [x for x in alone if x.kind == la.DORMANT_BALANCE] == [], (
        "with nothing else in the ledger, April 2024 IS the end of the books")


def test_an_account_still_for_less_than_a_year_says_nothing():
    """Shorter than twelve months would flag the ordinary annual rhythm — an
    insurance prepayment, a yearly licence, an audit-fee accrual."""
    dep = acct(id="d1", name="Sundry Deposits", type="Asset", subtype="Current Asset")
    sal = acct(id="s1", name="Salaries", type="Expense")
    eleven = {"d1": [la.MonthlyMovement("2024-11-01", 9_00_000)],
              "s1": [la.MonthlyMovement("2025-10-01", 50_000_00)]}
    assert la._months_between("2024-11-01", "2025-10-01") == 11, "premise"
    assert not any(x.kind == la.DORMANT_BALANCE for x in la.scan([dep, sal], eleven))

    twelve = {"d1": [la.MonthlyMovement("2024-10-01", 9_00_000)],
              "s1": [la.MonthlyMovement("2025-10-01", 50_000_00)]}
    assert any(x.kind == la.DORMANT_BALANCE for x in la.scan([dep, sal], twelve))


def test_a_still_account_with_a_nil_balance_is_not_a_finding():
    """An account that was used, netted to nothing and then went quiet needs no
    review — it is closed in all but name."""
    dep = acct(id="d1", name="Old Advance", type="Asset", subtype="Current Asset")
    sal = acct(id="s1", name="Salaries", type="Expense")
    found = la.scan([dep, sal], {
        "d1": [la.MonthlyMovement("2024-04-01", 9_00_000),
               la.MonthlyMovement("2024-05-01", -9_00_000)],
        "s1": [la.MonthlyMovement("2025-10-01", 50_000_00)],
    })
    assert not any(x.kind == la.DORMANT_BALANCE for x in found)


def test_a_dormant_balance_below_the_floor_is_left_alone():
    dep = acct(id="d1", name="Sundry Deposits", type="Asset", subtype="Current Asset")
    sal = acct(id="s1", name="Salaries", type="Expense")
    below = {"d1": [la.MonthlyMovement("2024-04-01", la.DEFAULT_MATERIALITY_PAISE - 1)],
             "s1": [la.MonthlyMovement("2025-10-01", 50_000_00)]}
    assert not any(x.kind == la.DORMANT_BALANCE for x in la.scan([dep, sal], below))


@pytest.mark.parametrize("earlier,later,expected", [
    ("2025-04-01", "2025-04-01", 0),
    ("2025-04-01", "2025-05-01", 1),
    ("2024-04-01", "2025-04-01", 12),
    # Across a leap year. Counted on the CALENDAR rather than in days, so the
    # answer cannot disagree with itself — domain/fixed_assets/cwip's reason.
    ("2024-01-01", "2024-03-01", 2),
    ("2023-12-01", "2025-01-01", 13),
])
def test_the_month_count_is_calendar_arithmetic(earlier, later, expected):
    assert la._months_between(earlier, later) == expected


# ── 3. A month far above the account's own usual month ───────────────────────

def test_a_keyed_extra_zero_is_caught():
    a = acct(id="s1", code="5001", name="Salaries", type="Expense",
             subtype="Employee Benefits")
    rows = months(50_000_00, 50_000_00, 50_000_00, 50_000_00, 50_000_00, 500_000_00)
    found = [x for x in la.scan([a], {"s1": rows}) if x.kind == la.OUTLIER_MONTH]
    assert len(found) == 1
    assert found[0].period_month == "2025-09-01"
    assert found[0].amount_paise == 500_000_00


def test_two_keying_errors_do_not_hide_each_other_behind_a_mean():
    """The median matters for a NARROWER reason than it first looks, and this
    test exists because the first version of it asserted the wrong one and a
    negative control swapping `_median` for a mean passed.

    The candidate month is already out of the comparison set, so on a series
    with ONE odd month a mean and a median agree exactly. They part on a SECOND
    large month — which is what a recurring wrong template produces. Here
    eleven ordinary months and two of ₹5,00,000: the mean of the comparison set
    rises to a point where neither outlier clears the threshold, and both go
    unreported."""
    a = acct(id="s1", name="Salaries", type="Expense")
    rows = months(*([50_000_00] * 11 + [500_000_00, 500_000_00]))

    # The premise, asserted rather than assumed: a mean would report neither.
    values = [abs(m.net_paise) for m in rows]
    for i, candidate in enumerate(values):
        others = values[:i] + values[i + 1:]
        if candidate == 500_000_00:
            assert candidate < (sum(others) // len(others)) * la.OUTLIER_MULTIPLE

    found = [x for x in la.scan([a], {"s1": rows}) if x.kind == la.OUTLIER_MONTH]
    assert len(found) == 2, "the median reports both; a mean reports neither"


def test_a_seasonal_march_is_not_an_outlier():
    """March carries the annual bonus and the last advance-tax instalment.
    Three or four times an ordinary month is trading, not a keying error."""
    a = acct(id="s1", name="Salaries", type="Expense")
    rows = months(50_000_00, 50_000_00, 50_000_00, 50_000_00, 50_000_00, 200_000_00)
    assert not any(x.kind == la.OUTLIER_MONTH for x in la.scan([a], {"s1": rows}))


def test_a_client_with_too_little_history_is_left_alone_and_not_reported():
    """A median needs a history. Below the minimum the check simply does not
    fire — and it emits nothing SAYING so either, because a client three months
    old is not something wrong with the books. The catalogue entry the screen
    renders carries that caveat instead."""
    a = acct(id="s1", name="Salaries", type="Expense")
    for n in range(1, la.MIN_MONTHS_FOR_A_MEDIAN + 1):
        rows = months(*([50_000_00] * (n - 1) + [500_000_00]))
        assert not any(x.kind == la.OUTLIER_MONTH
                       for x in la.scan([a], {"s1": rows})), n
    enough = months(*([50_000_00] * la.MIN_MONTHS_FOR_A_MEDIAN + [500_000_00]))
    assert any(x.kind == la.OUTLIER_MONTH for x in la.scan([a], {"s1": enough}))


def test_a_nil_month_is_not_a_month_for_the_median():
    """`moved` drops nil months before taking the median, because a client who
    bills quarterly would otherwise have a median of zero and every billing
    month would be infinitely above it."""
    a = acct(id="r1", name="Professional Fees", type="Revenue")
    rows = months(-50_000_00, 0, 0, -50_000_00, 0, 0, -50_000_00, 0, 0,
                  -50_000_00, 0, 0)
    assert not any(x.kind == la.OUTLIER_MONTH for x in la.scan([a], {"r1": rows}))


def test_an_outlier_in_either_direction_is_caught():
    """The test is on the ABSOLUTE movement, so a credit-side account's large
    month fires the same way a debit-side one's does."""
    a = acct(id="r1", name="Sales", type="Revenue")
    rows = months(-50_000_00, -50_000_00, -50_000_00, -50_000_00, -50_000_00,
                  -500_000_00)
    found = [x for x in la.scan([a], {"r1": rows}) if x.kind == la.OUTLIER_MONTH]
    assert len(found) == 1
    assert found[0].amount_paise == -500_000_00


def test_an_entry_and_its_reversal_in_one_month_do_not_fire():
    """The movement is the NET, so a posting reversed in the same month nets to
    nothing and is not an outlier. Gross would flag every busy bank month."""
    a = acct(id="s1", name="Salaries", type="Expense")
    rows = months(50_000_00, 50_000_00, 50_000_00, 50_000_00, 50_000_00, 0)
    assert not any(x.kind == la.OUTLIER_MONTH for x in la.scan([a], {"s1": rows}))


# ── Shape ────────────────────────────────────────────────────────────────────

def test_an_account_never_posted_to_is_skipped_entirely():
    """A firm's chart carries every account the seed created and a given client
    uses a fraction of them. Reporting the rest as dormant is the
    forty-findings failure."""
    assert la.scan([acct()], {}) == ()
    assert la.scan([acct()], {"a1": []}) == ()


def test_findings_are_ordered_by_kind_then_by_size():
    small = acct(id="a1", code="1100", name="Trade Receivables")
    big = acct(id="a2", code="1200", name="Other Receivables")
    found = la.scan([small, big],
                    {"a1": months(-1_000_00), "a2": months(-9_000_00)})
    assert [a.account_id for a in found] == ["a2", "a1"]


def test_every_kind_the_module_can_emit_is_in_all_kinds():
    """`ALL_KINDS` is what `reconciliation_service.CHECK_CATALOGUE` and its
    guard read. A kind emitted but not listed renders to a CA as its own
    identifier."""
    import ast
    import pathlib

    src = pathlib.Path(la.__file__).read_text()
    tree = ast.parse(src)
    constants = {
        node.targets[0].id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        and node.value.value.startswith("ledger_")
    }
    assert constants, "the walk found no kind constants — it has gone blind"
    assert set(constants.values()) == set(la.ALL_KINDS)


def test_the_module_says_what_it_cannot_see():
    """A clean result must not be read as a clean set of books."""
    assert len(la.NOT_CHECKED) >= 3
    assert all(s.endswith(".") and len(s) >= 60 for s in la.NOT_CHECKED)
