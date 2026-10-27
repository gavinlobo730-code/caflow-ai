"""What became of each tax deduction, from the challan register: the TDS screen's "Deposit" column.

The deductions table printed a "Challan No" column from `tds_deductions.challan_no`, a field nothing writes for a deduction a purchase
bill creates (`POST /challans` records the challan and never touches the deductions it paid), so it was a dash for nearly every row,
and the manual form could type a number there that nothing else reads. The register is the one record of a deposit, so the column
asks it: a challan pays the deductions of its own financial year and quarter under its own section, first in first out
(`domain/tds/challan_mapping`), and the shortfall of a short quarter lands on the LAST deductions of it.

SEVEN STATES, and none stands in for another:

  DEPOSITED      the register covers the deduction's tax; `challans` names the serials that paid it
  PART           it covers some of it
  NOT_DEPOSITED  the quarter has a challan recorded and none of it reaches this deduction (the later deductions of a short quarter,
                 or a section no challan of the quarter is recorded under)
  NOT_RECORDED   the quarter has NO challan recorded: this product cannot say whether the tax was deposited (a firm that keeps its
                 deposits in another system records none here), which is not the same sentence as "not deposited"
  NIL            the row owes no tax (a nil row, or a negative one, which the register counts as nil), so there is nothing to deposit
  SALARY         a section 192 row: payroll deposits salary tax, and neither side of this register carries it
  UNDATED        a row with no usable date has no quarter to be judged in (the database holds a date on every row, so this is reached
                 only by hand-built rows and the in-memory register)

NOT YET DUE IS NOT OVERDUE, AND A LATE DEPOSIT IS NOT ON TIME. A PART or NOT_DEPOSITED row carries the date Rule 30(2) puts its deposit
on (`due_on`) and whether that date has passed (`overdue`): tax deducted on the 20th and looked at on the 25th is not yet deposited
and is not late, and the screen must not draw it as a failure. A row COVERED by a challan paid after that date (`late_on`, the latest
such payment, by the register's first-in-first-out order) is deposited and is not on time, which is what the deposit worksheet charges
interest on. Both dates come from a clock and a due-date rule handed in by the caller (`due_date_of`, `today`), so this module stays
free of the compliance engine; without both, no row says whether it is late.

The rule that decides whether a quarter is recorded is migration 523's (any non-salary challan row for the client, financial year and
quarter), and the tile, Form 3CD clause 34 and this column are held to one fixture over the registry's sections (a section the registry
does not hold, with a bracketed limb, is grouped differently by the SQL and by the match: `undeposited.py` says how). A deposited row
whose covering challan is dated BEFORE the deduction says so (`dated_before`): the register matches by order and not by date, and the
deposit worksheet, which judges each challan by its date, refuses such a part, so the two screens must not disagree in silence.

WARNINGS are what the register itself shows that a reader of its figures should know. A challan recorded twice (the definition Form
3CD clause 34 shares) and a challan against a demand (minor head 400, which every reader counts as a deposit: POST-C-210) are
`register_warnings`, and neither is said of a salary challan, which the register ignores. A challan larger than the deductions of its
quarter and section (`surplus`) is the one sign of a challan recorded for the wrong quarter, which this register cannot otherwise
tell from a deposit made early, and it is worded as a question to check. Integer paise throughout.

WORDS. The labels and generic sentences (`legend`, sent once per answer and not once per row: a client's year can be thousands of
rows) and the sentences that are about one row (a part's rupees, a challan dated before the tax) are the server's, so the browser
words nothing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Iterable, Optional

from domain.tds import challan_mapping, deposit_due
from domain.tds.undeposited import fy_label_of, is_salary, quarter_of, section_group
from domain.money_sentence import rupee_text

DEPOSITED = "deposited"
PART = "part"
NOT_DEPOSITED = "not_deposited"
NOT_RECORDED = "not_recorded"
NIL = "nil"
SALARY = "salary"
UNDATED = "undated"
STATES = (DEPOSITED, PART, NOT_DEPOSITED, NOT_RECORDED, NIL, SALARY, UNDATED)
#: The states a row can only be in when its quarter has a challan recorded: it was judged against the register.
JUDGED = (DEPOSITED, PART, NOT_DEPOSITED)

GAP_CHALLAN_RECORDED_MORE_THAN_ONCE = "challan_recorded_more_than_once"
GAP_CHALLAN_AGAINST_A_DEMAND = "challan_against_a_demand"
GAP_CHALLAN_EXCEEDS_DEDUCTIONS = challan_mapping.GAP_CHALLAN_EXCEEDS_DEDUCTIONS

LABELS = {
    DEPOSITED: "Deposited",
    PART: "Part deposited",
    NOT_DEPOSITED: "Not deposited",
    # Not "No challan recorded" alone, which reads as "not deposited": the point is that this product cannot say.
    NOT_RECORDED: "Unknown: no challan recorded",
    # Not "Nil", which beside a column headed Deposit reads as "nothing was deposited".
    NIL: "Nothing to deposit",
    SALARY: "Through payroll",
    UNDATED: "No date",
}

_LEGEND = {
    DEPOSITED: "Covered by the challans named, first in first out within the deduction's quarter.",
    PART: "Some of it is covered by the challans named; the rest is not covered by any challan recorded for the quarter.",
    NOT_DEPOSITED: ("The challans recorded for this deduction's quarter do not reach it: none is recorded under its section, or the "
                    "earlier deductions under it use them up (first in first out). Record the challan that paid it, or it is still "
                    "to be paid."),
    NOT_RECORDED: ("No challan is recorded for this deduction's quarter, so whether this tax was deposited is not known here. "
                   "Record the challan to have it counted."),
    NIL: "This deduction counts as nil, so there is nothing to deposit.",
    SALARY: "Salary tax is deposited from payroll, so this register does not judge it.",
    UNDATED: "This deduction has no date, so no quarter can be judged.",
}


@dataclass(frozen=True)
class RowState:
    state: str
    tax_paise: int = 0
    deposited_paise: int = 0
    #: The serials of the challans that paid it, in the order it drew on them; empty unless some of it is covered.
    challans: tuple = ()
    #: The financial year and quarter the row was judged in; empty for a salary row or one with no date.
    financial_year: str = ""
    quarter: str = ""
    #: A challan that covers some of it is dated before the tax was deducted.
    dated_before: bool = False
    #: For a PART or NOT_DEPOSITED row: the date its deposit fell due (Rule 30(2)) and whether that date has passed.
    due_on: Optional[date] = None
    overdue: bool = False
    #: For a row some of whose tax a challan covers: the latest payment dated after the date the deposit fell due.
    late_on: Optional[date] = None


@dataclass(frozen=True)
class Judgement:
    states: dict
    #: One warning per (quarter, section) whose challans are more than its deductions.
    surplus: list = field(default_factory=list)


def judge(deductions: Iterable[dict], challans: Iterable[dict], *,
          due_date_of: Optional[Callable[[date], date]] = None, today: Optional[date] = None) -> Judgement:
    """Each deduction's state, by deduction id, for ONE client's deductions and challans (any number of years and quarters), and the
    surplus warnings of the quarters that have a challan recorded. `due_date_of` maps a deduction's date to the date its deposit falls
    due and `today` is the CA's day (IST); without both, no row says whether it is late."""
    # A section is grouped as the card groups it (trimmed, upper-cased, a trailing bracketed limb dropped), so a deduction typed
    # "194Z(A)" and a challan typed "194Z" are one group here as they are in the SQL behind the card.
    challans = [{**c, "section": section_group(c.get("section"))} for c in challans if not is_salary(c.get("section"))]
    recorded = {(str(c.get("financial_year") or ""), str(c.get("quarter") or "")) for c in challans}
    states: dict[str, RowState] = {}
    groups: dict[tuple, list] = {}
    for row in deductions:
        key = str(row.get("id"))
        if is_salary(row.get("section")):
            states[key] = RowState(SALARY)
            continue
        on = challan_mapping.as_date(row.get("transaction_date"))
        if on is None:
            states[key] = RowState(UNDATED, tax_paise=_nil_floor(row))
            continue
        fy, quarter = fy_label_of(on), quarter_of(on)
        if _nil_floor(row) <= 0:
            states[key] = RowState(NIL, financial_year=fy, quarter=quarter)
            continue
        groups.setdefault((fy, quarter), []).append({**row, "section": section_group(row.get("section"), blank="(NO SECTION)")})
    surplus: list[dict] = []
    for (fy, quarter) in sorted(recorded | set(groups)):
        rows = groups.get((fy, quarter), [])
        if (fy, quarter) not in recorded:
            for row in rows:
                states[str(row.get("id"))] = RowState(NOT_RECORDED, tax_paise=_nil_floor(row), financial_year=fy, quarter=quarter)
            continue
        theirs = [c for c in challans if str(c.get("financial_year") or "") == fy and str(c.get("quarter") or "") == quarter]
        mapping = deposit_due.mapping_from_register(rows, theirs, fy=fy)
        surplus.extend(_surplus_warning(g, fy, quarter) for g in mapping.gaps if g.get("code") == GAP_CHALLAN_EXCEEDS_DEDUCTIONS)
        for row in rows:
            tax = _nil_floor(row)
            got = mapping.for_deduction(row.get("id"))
            # Never more than the row owes and never negative: `assign` draws at most each deduction's need (its `tax_of`) from
            # challans of non-negative capacity, so a surplus stays on the challan and is not a deposit of this row.
            covered = got.deposited_paise
            serials = tuple(s for s in (str((c or {}).get("challan_no") or "").strip() for c, _paise in got.parts) if s and covered > 0)
            counted, refused = challan_mapping.dated_parts(got, challan_mapping.as_date(row.get("transaction_date")))
            state = DEPOSITED if covered >= tax else PART if covered > 0 else NOT_DEPOSITED
            due_on = overdue = late_on = None
            if due_date_of is not None and today is not None:
                row_due = due_date_of(challan_mapping.as_date(row.get("transaction_date")))
                if state != DEPOSITED:
                    due_on, overdue = row_due, today > row_due
                late_on = max((paid_on for _paise, paid_on in counted if paid_on > row_due), default=None)
            states[str(row.get("id"))] = RowState(state, tax_paise=tax, deposited_paise=covered, challans=serials,
                                                  financial_year=fy, quarter=quarter, dated_before=refused, due_on=due_on,
                                                  overdue=bool(overdue), late_on=late_on)
    return Judgement(states=states, surplus=surplus)


def deduction_states(deductions: Iterable[dict], challans: Iterable[dict], **kwargs) -> dict[str, RowState]:
    """`judge`'s states alone."""
    return judge(deductions, challans, **kwargs).states


def _nil_floor(row: dict) -> int:
    return max(0, deposit_due.tax_of(row))


def _surplus_warning(gap: dict, fy: str, quarter: str) -> dict:
    serials = sorted({str(n).strip() for n in (gap.get("challan_nos") or []) if n and str(n).strip()})
    section = str(gap.get("section") or "").strip()
    under = f" under {section}" if section else " with no section"
    named = f" ({', '.join(serials)})" if serials else ""
    return {"code": GAP_CHALLAN_EXCEEDS_DEDUCTIONS, "financial_year": fy, "quarter": quarter, "section": section,
            "surplus_paise": int(gap.get("surplus_paise") or 0), "challan_nos": serials,
            "message": (f"The challans recorded for {quarter} of {fy}{under}{named} are {rupee_text(int(gap.get('surplus_paise') or 0))} "
                        "more than the tax deducted in that quarter under that section. A challan is matched to the quarter, year "
                        "and section it is recorded for, and the quarter is the one the tax was deducted in, not always the one it "
                        "was paid in: check the quarter, financial year and section it was recorded for.")}


def duplicate_challan_warnings(challans: Iterable[dict]) -> list[dict]:
    """A challan recorded more than once under the same branch code, serial and date: it would count as two deposits (there is no
    unique key on `tds_challans`). The one definition, read by Form 3CD clause 34 and by this screen. A salary challan is not one of
    them: the register ignores it, so it counts as no deposit at all."""
    seen: dict[tuple, int] = {}
    for c in challans:
        if is_salary(c.get("section")):
            continue
        key = (str(c.get("bsr_code") or ""), str(c.get("challan_no") or ""), str(c.get("payment_date") or "")[:10])
        seen[key] = seen.get(key, 0) + 1
    return [{"code": GAP_CHALLAN_RECORDED_MORE_THAN_ONCE, "bsr_code": k[0], "challan_no": k[1], "payment_date": k[2], "times": n,
             "message": f"Challan {k[1]} of {k[2]} is recorded {n} times, and each is counted as a deposit."}
            for k, n in sorted(seen.items()) if n > 1]


def demand_challan_warnings(challans: Iterable[dict]) -> list[dict]:
    """A challan against a demand (minor head 400) is counted as a deposit of the quarter's deductions like any other, which
    understates a default (POST-C-210): the screen says so beside the figures instead of leaving it to be found. Not said of a salary
    challan, which the register ignores."""
    return [{"code": GAP_CHALLAN_AGAINST_A_DEMAND, "challan_no": str(c.get("challan_no") or ""),
             "message": f"Challan {c.get('challan_no') or '(no serial)'} is a payment against a demand (minor head 400) and is counted as "
                        "a deposit of the quarter's deductions; whether any part of it settles a deduction has not been confirmed."}
            for c in challans if not is_salary(c.get("section")) and str(c.get("minor_head") or "").strip() == "400"]


def register_warnings(challans: Iterable[dict]) -> list[dict]:
    challans = list(challans)
    return duplicate_challan_warnings(challans) + demand_challan_warnings(challans)


def legend() -> dict[str, dict]:
    """The label and the generic sentence of each state, sent once per answer: a row carries its state and the screen reads the words
    from here (a row's own sentence, where it has one, replaces the generic one)."""
    return {s: {"label": LABELS[s], "sentence": _LEGEND[s]} for s in STATES}


def _date_text(d: date) -> str:
    return f"{d.day} {d:%b %Y}"


def due_note(row: RowState) -> Optional[str]:
    """Whether the deposit is late: for a NOT_DEPOSITED row, whether its date has passed, and for a row a challan covers (all or part),
    whether the covering payment was made after the date it fell due. Short, because it is per row."""
    if row.state == NOT_DEPOSITED and row.due_on is not None:
        return (f"Was due on {_date_text(row.due_on)}." if row.overdue else f"Not due yet: due by {_date_text(row.due_on)}.")
    if row.state in (DEPOSITED, PART) and row.late_on is not None:
        return f"Paid late: the latest payment was on {_date_text(row.late_on)}, after the date it fell due."
    return None


def words(row: RowState) -> tuple[str, Optional[str]]:
    """(the short label, the sentence that is about THIS row or None). A row with no sentence of its own is read from `legend()`,
    which the answer carries once. A part's rupees, and a challan dated before the tax, are about one row."""
    where = f"{row.quarter} of {row.financial_year}" if row.quarter else "its quarter"
    covered_by = (f"challan {', '.join(row.challans)}" if row.challans else "a recorded challan")
    earlier = (" One of the challans that covers it is dated before the tax was deducted: check its date (the Due for deposit panel "
               "on the Challans tab does not count such a challan).") if row.dated_before else ""
    label = LABELS[row.state]
    if row.state == PART:
        late = ("" if row.due_on is None else
                f" The deposit was due on {_date_text(row.due_on)}." if row.overdue else f" It is not due yet: due by {_date_text(row.due_on)}.")
        return label, (f"{rupee_text(row.deposited_paise)} of {rupee_text(row.tax_paise)} (tax with surcharge and cess) is covered, "
                       f"by {covered_by}; the rest is not covered by any challan recorded for the quarter.{earlier}{late}")
    if row.state == DEPOSITED and row.dated_before:
        return label, f"Covered by {covered_by}, first in first out within {where}.{earlier}"
    return label, None
