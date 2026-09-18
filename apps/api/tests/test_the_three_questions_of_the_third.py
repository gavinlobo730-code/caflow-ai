"""What a CA does on the 3rd of the month (PAY-27).

Three things the product computed nothing for while holding every input:

  * WHY IS THIS MONTH BIGGER THAN LAST MONTH, AND BY WHOM. `payroll_runs`
    stores the totals and no screen compared two months.
  * WHAT DOES EACH DEPARTMENT COST. `department` is on the employee master and
    in the salary register, and nothing grouped by it.
  * WHO GETS PAID. `bank_account_no` and `bank_ifsc` have been collected since
    the module was built and NOTHING read them — the finding says so in as
    many words — so the bank file was built by hand, every month, for every
    client.

The sharp edges are in the third: a payment file is uploaded without being
re-read line by line, so a draft run, a blank IFSC and a nil net pay each have
to be refused rather than emitted.
"""
from __future__ import annotations

import ast
import inspect

import pytest

from domain.payroll import bank_advice as ba
from domain.payroll import department_cost as dc
from domain.payroll import month_on_month as mom


def _slip(employee_id, gross=0, net=0, dept=None, account="50100123456789",
          ifsc="HDFC0001234", name="Asha", **components):
    row = {"employee_id": employee_id, "gross_paise": gross, "net_paise": net,
           "payroll_employees": {"name": name, "department": dept,
                                 "bank_account_no": account, "bank_ifsc": ifsc}}
    row.update(components)
    return row


# ═════════════════════════════════════════════════════════════════════════════
# THE BANK ADVICE — the one that moves money if it is wrong
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("status", ["draft", "review", "reversed", "", None,
                                    "FINALISED", "Draft"])
def test_an_unreleased_run_produces_no_payment_file(status):
    """PAY-04: a draft has paid nobody. A bank advice built from one is an
    instruction to pay figures nobody approved, in a file whose whole purpose
    is that somebody uploads it without re-reading every line."""
    slips = [_slip("e1", gross=5_000_000, net=4_500_000)]
    out = ba.build(slips, "2026-09", run_status=status).to_dict()
    assert out["payable_count"] == 0
    assert out["total_paise"] == 0
    assert ba.DRAFT_HAS_PAID_NOBODY in out["notes"]


@pytest.mark.parametrize("status", ["finalized", "paid", "Finalized", " PAID "])
def test_a_released_run_does_produce_one(status):
    out = ba.build([_slip("e1", net=4_500_000)], "2026-09",
                   run_status=status).to_dict()
    assert out["payable_count"] == 1
    assert out["total_paise"] == 4_500_000


@pytest.mark.parametrize("field,value,reason", [
    ("account", "", ba.NO_ACCOUNT),
    ("account", "   ", ba.NO_ACCOUNT),
    ("ifsc", "", ba.NO_IFSC),
    ("ifsc", "NOTANIFSC", ba.BAD_IFSC),
    ("ifsc", "HDFC1001234", ba.BAD_IFSC),      # fifth character must be 0
    ("ifsc", "HDFC000123", ba.BAD_IFSC),       # ten characters, not eleven
])
def test_an_employee_who_cannot_be_paid_is_named_and_held_out(field, value, reason):
    """A row with blanks in a bank file is the dangerous shape: some banks
    reject the whole upload and some process the rest and drop it SILENTLY,
    which leaves the CA believing everybody was paid."""
    out = ba.build([_slip("e1", net=4_500_000, **{field: value})], "2026-09",
                   run_status="finalized").to_dict()
    assert out["payable_count"] == 0
    excluded, = out["excluded"]
    assert excluded["reason"] == reason
    assert excluded["why"]


def test_nil_and_negative_net_pay_are_different_answers():
    """A nil is a full month of loss of pay or recoveries equal to the salary —
    real, and not a payment instruction. A NEGATIVE is recoveries EXCEEDING the
    salary, which is a payroll to look at rather than a transfer to make."""
    out = ba.build([_slip("e1", net=0, name="Nil"),
                    _slip("e2", net=-500, name="Negative")],
                   "2026-09", run_status="paid").to_dict()
    reasons = {e["name"]: e["reason"] for e in out["excluded"]}
    assert reasons == {"Nil": ba.NIL_NET, "Negative": ba.NEGATIVE_NET}
    assert ba.WHY[ba.NIL_NET] != ba.WHY[ba.NEGATIVE_NET]


def test_missing_bank_details_outrank_a_nil_this_month():
    """An employee with no account AND nil net has two problems and one the CA
    can act on durably. Reporting the nil would have them come back to it next
    month and find the same row."""
    out = ba.build([_slip("e1", net=0, account="")], "2026-09",
                   run_status="paid").to_dict()
    assert out["excluded"][0]["reason"] == ba.NO_ACCOUNT


def test_the_file_carries_only_the_payable_rows():
    csv = ba.to_csv(ba.build(
        [_slip("e1", net=4_500_000, name="Payable"),
         _slip("e2", net=3_000_000, name="NoAccount", account="")],
        "2026-09", run_status="paid")).decode()
    assert "Payable" in csv
    assert "NoAccount" not in csv
    assert csv.count("\r\n") == 2, "one header and one row"


def test_the_amount_is_net_pay_in_rupees_with_no_grouping():
    """`domain/payroll/register._rupees`'s rule: no separators and no symbol,
    because a bank upload is parsed by a program and `1,25,000` is what makes a
    parser read one rupee."""
    csv = ba.to_csv(ba.build([_slip("e1", net=12_500_000)], "2026-09",
                             run_status="paid")).decode()
    assert "125000.00" in csv
    assert "1,25,000" not in csv
    assert "₹" not in csv


def test_the_account_number_is_masked_on_the_screen_and_whole_in_the_file():
    built = ba.build([_slip("e1", net=1_000, account="50100123456789")],
                     "2026-09", run_status="paid")
    assert built.to_dict()["rows"][0]["account_no_masked"] == "xxxxxxxxxx6789"
    assert "50100123456789" in ba.to_csv(built).decode()


def test_it_says_it_moves_no_money_and_that_the_layout_is_generic():
    notes = ba.build([_slip("e1", net=1)], "2026-09", run_status="paid").notes
    assert ba.MOVES_NO_MONEY in notes
    assert ba.LAYOUTS_NOT_HELD in notes


def test_no_bank_specific_layout_is_invented():
    """Every bank's bulk upload has its own column order and transaction-type
    code, and those move. A layout written from memory is a file that looks
    right and is rejected at upload — worse than a generic one the CA maps
    once."""
    code = _code_only(ba)
    for bank in ("hdfc", "icici", "axis", "kotak", "sbi", "yes bank"):
        assert bank not in code.lower()


# ═════════════════════════════════════════════════════════════════════════════
# THE VARIANCE
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("month,prior", [
    ("2026-09", "2026-08"), ("2026-01", "2025-12"),
    ("2026-12", "2026-11"), ("2027-01", "2026-12"),
])
def test_the_baseline_is_the_calendar_predecessor(month, prior):
    assert mom.preceding_month(month) == prior


def test_a_draft_baseline_is_no_baseline():
    """PAY-04 again. A draft has paid nobody, so comparing against one compares
    this month with something that never happened."""
    now = [_slip("e1", gross=5_000_000, net=4_500_000)]
    out = mom.compare("2026-09", now, "2026-08", now, prior_released=False).to_dict()
    assert out["comparable"] is False
    assert out["prior_gross_paise"] == 0
    assert mom.NO_BASELINE in out["notes"]
    # ...and this month's own figures are still reported.
    assert out["gross_paise"] == 5_000_000


def test_the_month_being_looked_at_may_be_a_draft():
    """The variance is most useful BEFORE release: catching a jump on the 2nd
    is the point, and refusing until the run is finalised puts the check after
    the moment it could prevent anything."""
    out = mom.compare("2026-09", [_slip("e1", gross=9_000_000)],
                      "2026-08", [_slip("e1", gross=5_000_000)],
                      prior_released=True).to_dict()
    assert out["comparable"] is True
    assert out["gross_delta_paise"] == 4_000_000


def test_a_joiner_a_leaver_and_a_revision_are_told_apart():
    now = [_slip("e1", gross=5_000_000, basic_paise=2_500_000, name="Stays"),
           _slip("e2", gross=2_000_000, basic_paise=1_000_000, name="Joins")]
    before = [_slip("e1", gross=4_000_000, basic_paise=2_000_000, name="Stays"),
              _slip("e9", gross=1_800_000, basic_paise=900_000, name="Leaves")]
    out = mom.compare("2026-09", now, "2026-08", before, True).to_dict()
    by_name = {e["name"]: e for e in out["employees"]}
    assert by_name["Joins"]["status"] == mom.JOINED
    assert by_name["Leaves"]["status"] == mom.LEFT
    assert by_name["Stays"]["status"] == mom.CHANGED
    # A LEAVER IS NAMED. They are not in this month's slips at all, so the name
    # has to come off the month that HAS them — the one report that exists to
    # name them must not show an unnamed row.
    assert by_name["Leaves"]["gross_delta_paise"] == -1_800_000


def test_every_component_that_moved_is_listed_and_none_is_called_the_reason():
    """A payroll total moves for several reasons at once, and naming the
    biggest is how a CA stops reading the rest."""
    now = [_slip("e1", gross=6_000_000, basic_paise=3_000_000,
                 one_time_earnings_paise=500_000, pf_employee_paise=180_000)]
    before = [_slip("e1", gross=5_000_000, basic_paise=2_500_000,
                    one_time_earnings_paise=0, pf_employee_paise=150_000)]
    row, = mom.compare("2026-09", now, "2026-08", before, True).to_dict()["employees"]
    labels = [m["label"] for m in row["moved"]]
    assert set(labels) == {"Basic", "Bonus / Incentive / Arrears", "PF (employee)"}
    # Largest absolute movement first.
    assert labels[0] == "Basic"
    assert mom.NO_SINGLE_CAUSE in mom.compare(
        "2026-09", now, "2026-08", before, True).notes


def test_days_are_reported_apart_from_money():
    now = [_slip("e1", gross=4_000_000, lop_days=3, days_present=24)]
    before = [_slip("e1", gross=5_000_000, lop_days=0, days_present=27)]
    row, = mom.compare("2026-09", now, "2026-08", before, True).to_dict()["employees"]
    assert {d["label"]: d["delta"] for d in row["days_moved"]} == {
        "LOP days": 3.0, "Days present": -3.0}


def test_a_gross_that_moved_with_no_component_behind_it_is_named():
    """The figure is real and what explains it is not in the slip's own
    columns. Inventing a label for it would be worse than the gap."""
    now = [_slip("e1", gross=6_000_000)]
    before = [_slip("e1", gross=5_000_000)]
    row, = mom.compare("2026-09", now, "2026-08", before, True).to_dict()["employees"]
    assert row["unexplained"] is True
    assert row["moved"] == []


def test_a_total_is_never_listed_among_its_own_causes():
    """`gross_paise` and `net_paise` are what is being explained; listing
    either among the components double-counts every movement."""
    keys = {k for k, _label in mom.COMPONENTS}
    assert "gross_paise" not in keys
    assert "net_paise" not in keys


def test_no_percentage_is_computed_against_a_nil_baseline():
    """A joiner went from nothing to something and '∞%' is not a figure."""
    code = _code_only(mom)
    assert "percent" not in code.lower()
    assert "/ prior" not in code


# ═════════════════════════════════════════════════════════════════════════════
# THE DEPARTMENT SPLIT
# ═════════════════════════════════════════════════════════════════════════════

def test_cost_is_gross_plus_the_employers_own_contributions():
    """PAY-25's two debits — Schedule III Division I Part II (a) salaries and
    (b) contribution to provident and other funds. Reported apart, because they
    are two accounts and a blended figure lets a reader take it for either."""
    out = dc.split([_slip("e1", gross=5_000_000, dept="Factory",
                          pf_employer_paise=180_000, esi_employer_paise=39_000,
                          edli_paise=7_500, pf_admin_paise=7_500)],
                   "2026-09").to_dict()
    row, = out["rows"]
    assert row["gross_paise"] == 5_000_000
    assert row["employer_contribution_paise"] == 234_000
    assert row["cost_paise"] == 5_234_000


def test_net_pay_is_not_cost():
    """Net is what leaves the bank; the employee's own PF, ESI, professional
    tax and TDS are the employer's cost too, paid to somebody else. A table
    built on net understates the cost by exactly those deductions."""
    code = _code_only(dc)
    assert "net_paise" not in code
    assert "net" in dc.NET_IS_NOT_COST.lower()


def test_an_employee_with_no_department_is_its_own_row():
    """Never folded into another and never dropped: `department` is nullable
    with no default, so a client who has never used it has every employee
    here — and a table that omitted them would not sum to the run."""
    out = dc.split([_slip("e1", gross=1_000_000, dept="Office"),
                    _slip("e2", gross=2_000_000, dept=None),
                    _slip("e3", gross=3_000_000, dept="   ")], "2026-09").to_dict()
    by_dept = {r["department"]: r for r in out["rows"]}
    assert by_dept[dc.NOT_RECORDED]["headcount"] == 2
    assert by_dept[dc.NOT_RECORDED]["gross_paise"] == 5_000_000


def test_the_table_sums_to_the_run():
    """The one property that makes it checkable."""
    slips = [_slip(f"e{i}", gross=1_000_000 * i, dept=f"D{i % 3}",
                   pf_employer_paise=120_000) for i in range(1, 8)]
    out = dc.split(slips, "2026-09").to_dict()
    assert out["total_gross_paise"] == sum(s["gross_paise"] for s in slips)
    assert out["total_headcount"] == len(slips)
    assert out["total_cost_paise"] == (out["total_gross_paise"]
                                       + out["total_employer_contribution_paise"])
    assert sum(r["cost_paise"] for r in out["rows"]) == out["total_cost_paise"]


def test_the_order_is_total_so_two_reads_agree():
    """Largest cost first, ties on the name — otherwise the table reshuffles
    between two reads of the same month."""
    slips = [_slip("a", gross=1_000_000, dept="Zebra"),
             _slip("b", gross=1_000_000, dept="Alpha"),
             _slip("c", gross=9_000_000, dept="Middle")]
    names = [r["department"] for r in dc.split(slips, "2026-09").to_dict()["rows"]]
    assert names == ["Middle", "Alpha", "Zebra"]


# ═════════════════════════════════════════════════════════════════════════════
# WHAT NONE OF THE THREE DOES
# ═════════════════════════════════════════════════════════════════════════════

def _code_only(mod) -> str:
    """The code, not the prose. Each module EXPLAINS its refusals at length, so
    a substring scan fails on the sentence stating the very rule it checks —
    and a module-level name bound to a string is a caveat wearing an
    identifier, which is the same trap one level up."""
    tree = ast.parse(inspect.getsource(mod))
    prose = {
        t.id
        for node in tree.body if isinstance(node, ast.Assign)
        for t in node.targets
        if isinstance(t, ast.Name)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }
    # The caveat ASSIGNMENTS go entirely, values and all. Renaming the name
    # and leaving the string is the same mistake with an extra step — the
    # sentence explaining "Schedule III Division I Part II" is still in the
    # text a scan for "schedule" reads.
    tree.body = [
        n for n in tree.body
        if not (isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id in prose
                        for t in n.targets))
    ]
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


@pytest.mark.parametrize("mod", [ba, mom, dc])
def test_none_of_them_reaches_a_bank_or_schedules_anything(mod):
    """Prepare-only, the posture this product takes to a government portal and
    for the same reason: the file is uploaded by a person who approves it."""
    code = _code_only(mod)
    for forbidden in ("requests", "httpx", "urlopen", "post(", "schedule",
                      "cron", "neft_api", "imps"):
        assert forbidden not in code.lower(), f"{mod.__name__} mentions {forbidden}"
    assert len(code) > 1500


def test_the_released_test_is_made_in_one_place():
    """Two spellings of "released" is how a fifth status silently joins one of
    them. `refusal_for_status` takes the STATUS rather than the run, so nothing
    can reach into a row for a second reason."""
    sig = inspect.signature(ba.refusal_for_status)
    assert list(sig.parameters) == ["status"]
    assert ba._RELEASED == mom._RELEASED == ("finalized", "paid")
