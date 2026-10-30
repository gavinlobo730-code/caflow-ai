"""A TDS challan recorded in the TDS workspace closes the monthly deposit obligation of every month it paid in full.

WHAT WAS WRONG
    A TDS engagement owes twelve monthly deposits (`TDS_NON_SALARY_DEPOSIT`, Rule 30(2): the seventh of the following month,
    30 April for March), generated on the compliance calendar by `compliance_obligation_service._tds_obligations`. The
    challan register (`tds_challans`) is where a deposit is recorded, and recording one never touched the calendar: on the
    seeded demo firm, with every deduction of the year deposited by a recorded challan, the Deadlines screen, the Compliance
    tab and the dashboard still called the deposits overdue. It is the split the GST and ITR workspaces and the quarterly TDS
    statements had (POST-A-264, POST-A-267), and the monthly deposit was left over because the statement closer's own note
    said a month can carry several challans under several sections, so what closes the month needed a rule nobody had written.

THE RULE (`decide_month`, a pure function, holds it)
    A month's deposit obligation is closed when the month's deposit worksheet (`services/tds_deposit_worksheet_service`, the
    one `GET /deposit-due` shows) has tax in it and NOTHING OUTSTANDING (every section of that month's deductions is covered
    by a recorded challan, first in first out, as the statement and the worksheet match them) AND every payment that covered
    it was made on or before the month's due date. Not before:

      * the month must be over, because tax deducted later in the same month would be uncovered and the obligation, once
        Filed, does not reopen;
      * a month in which no tax was deducted has no deposit to make and is not closed here (nothing in the books says it was
        a nil month and not a month nobody has keyed; the CA marks it from Compliance);
      * a challan against a demand (minor head 400) is not a deposit of the tax deducted, and a month it paid part of is left
        open (POST-C-210 is the question behind the rule for every reader of the register);
      * a payment dated in the future is refused by `mark_filed`, and the month is left open with a sentence;
      * A LATE CHALLAN CLOSES NOTHING BY ITSELF. The register matches a challan to a deduction by order within the quarter,
        and a challan carries a quarter and no month, so one paid after a month's due date may be the deposit for a later
        month and not for this one: with July's tax paid outside the product and August's challan recorded on 5 September,
        the match gives that challan to July, and closing July on it would date July late and leave August open, on a fact
        that cannot be undone. A month covered only by a late challan is left open with a sentence, and the person marks it
        with the date it really went.
      * a month with tax and nothing deposited, or only part of it, is left open; the answer names it only when the recorded
        challan paid some of it (a month the challan did not touch is not reported, and an obligation already filed is left
        as it is). A month fully and punctually deposited is closed WHICHEVER challan made it so: the rule is a fact about the
        register, and it is how challans recorded before the calendar was asked are caught up the next time one is recorded.

    The obligation is closed THROUGH `mark_filed` (see `services/obligation_closure`), with the date of the last payment as
    the date the deposit was made and the serial of the last challan paid that day as its reference. `mark_filed` does not ask
    that a monthly deposit wait for the period's end (a deposit is lawfully made in the month itself). Nothing is written to
    `filings` and no period is locked: only GSTR-1 and GSTR-3B do that.

    What it deliberately does not do:
      * the salary deposit (`TDS_SALARY_DEPOSIT`) and the EPF and ESI deposits are payroll's: a section 192 challan closes
        nothing here;
      * a challan edited or removed later does not reopen an obligation it closed, and a deduction recorded later in a month
        already closed does not either (a closed obligation says what was true when it was closed);
      * a deposit made outside the product and never recorded closes nothing: the CA marks it from Compliance;
      * it does not act for a caller without compliance access (closing an obligation is a compliance write, decided per
        person), and it never fails the recording of the challan: whatever stops an obligation closing comes back in the
        answer and goes to the error reporter.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT: this records a deposit the CA has already made at the bank. It transmits
    nothing.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from core.ist_clock import ist_today
from domain.money_sentence import rupee_text
from domain.tds import challan_mapping, deposit_due
from domain.tds.section_rates import quarter_dates
from repositories.compliance_records_repository import compliance_records_repo
from services import tds_deposit_worksheet_service as worksheet
from services.obligation_closure import (
    FROM_COMPLIANCE, NOT_ALLOWED, NOT_CLOSED, NOT_ON_THE_CALENDAR, answer, mark_filed_and_answer,
)

#: What the obligations are filed under on the calendar (`compliance_obligation_service._spec("TDS_NON_SALARY_DEPOSIT", "TDS", ...)`).
COMPLIANCE_TYPE = "TDS"
OBLIGATION_TYPE = "TDS_NON_SALARY_DEPOSIT"

_MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                "November", "December")


def months_of(financial_year: str, quarter: str) -> list[tuple[int, int]]:
    """The (year, month) of each deduction month in a financial-year quarter."""
    start, end, _due = quarter_dates(financial_year, quarter)
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    return [(y, m) for y, m in ((first.year + (first.month - 1 + i) // 12, (first.month - 1 + i) % 12 + 1)
                                for i in range(3)) if date(y, m, 1) <= last]


def _what(year: int, mon: int) -> str:
    return f"TDS deposit (non-salary) {_MONTH_NAMES[mon - 1]} {year} obligation"


@dataclass(frozen=True)
class Decision:
    """What to do with one month's open obligation: close it (`filed_on` set, with the serial of the last challan paid that
    day when there was one) or leave it, with a `sentence` for the CA or None when there is nothing worth saying."""
    filed_on: Optional[date] = None
    reference: Optional[str] = None
    sentence: Optional[str] = None


def decide_month(*, today: date, due: date, month_end: date, what: str, month_name: str, tax_paise: int,
                 outstanding_paise: int, salary_rows: bool, before_deduction: bool = False, paid_dates: list[date],
                 challans: list[dict], touched: bool) -> Decision:
    """The rule, as a pure function of what the worksheet says about one month. Checked in this order, and a month is closed
    only if it passes every one:

      1. it has tax in it (a month of nil-tax rows has no deposit to date);
      2. it is over (tax deducted later in the month would be uncovered, and a Filed obligation does not reopen);
      3. nothing is outstanding on the worksheet;
      4. no challan that paid it is against a demand (minor head 400 is not a deposit of the tax deducted);
      5. the latest payment is not in the future (`mark_filed` refuses a filing date that has not happened);
      6. EVERY payment was made on or before the month's due date (Rule 30(2)). The register matches a challan to a deduction
         by order within the quarter and not by month (a challan carries a quarter and no month), so a challan paid after the
         due date may be the deposit for a later month and not for this one; closing on it would date the month late, or
         close the wrong month, and a wrong closure is a wrong statement on the calendar until somebody notices and reopens it. A month covered only by a late challan is
         left for a person to mark, with the date it really went.
    A sentence is returned only when the recorded challan paid some of the month (`touched`): a month it did not touch that
    stays open is not its business. What the rule CANNOT settle, and says so in the design record: two challans that are both
    on time can be swapped between two months (July's paid late on 20 August and August's paid on 5 August are matched the
    other way round, both by order and both before September's due date), so a closed month's date and serial are the
    register's order's and the answer says them for the person to check."""
    def leave(reason: str, remedy: str) -> Decision:
        return Decision(sentence=f"The {what} was left open: {reason} {remedy}" if touched else None)

    if tax_paise <= 0:
        return Decision()
    if today <= month_end:
        return leave("the month is not over, so more tax may still be deducted in it.",
                     "It is looked at again when the next challan for the quarter is recorded.")
    if outstanding_paise > 0:
        return leave(f"{rupee_text(outstanding_paise)} of the tax deducted in {month_name} is not yet covered by a "
                     "recorded non-salary challan"
                     + (" (a section 192 row in this register is never covered here: payroll deposits salary tax)"
                        if salary_rows else "")
                     + (" (a challan dated before the tax was deducted does not count as paying it: check its date)"
                        if before_deduction else "") + ".",
                     "Record the challan that paid it; it is looked at again when one is recorded.")
    if any(str((c or {}).get("minor_head") or "").strip() == "400" for c in challans):
        return leave("a challan against a demand (minor head 400) paid part of it, and a payment against a demand is not a "
                     "deposit of the tax deducted.", FROM_COMPLIANCE)
    if not paid_dates:
        return Decision()
    last = max(paid_dates)
    if last > today:
        return leave(f"its latest payment is dated {last.isoformat()}, which has not happened yet.",
                     "Check the date on the challan.")
    if last > due:
        return leave(f"it is covered, but the latest payment is dated {last.isoformat()}, after the due date "
                     f"{due.isoformat()}, and a late challan may be the deposit for a later month: the register matches "
                     "challans to deductions by order within the quarter and not by month.",
                     "Mark it filed from Compliance with the date it really went.")
    same_day = [c for c in challans if challan_mapping.as_date((c or {}).get("payment_date")) == last]
    last_challan = max(same_day, key=lambda c: str(c.get("challan_no") or ""), default=None)
    return Decision(filed_on=last, reference=str((last_challan or {}).get("challan_no") or "") or None)


def close_for_recorded_challan(
    *, db, firm_id: str, client_id: str, financial_year: Optional[str], quarter: Optional[str], challan_id: str,
    section: Optional[str], actor: Optional[dict], may_write_compliance: bool,
) -> list[dict[str, Any]]:
    """`_close`'s answers, each with `needs_action`: whether somebody has something to do about it. A month left open (not closed,
    not allowed to, or one that could not be found to update) needs a person; a month closed, one already filed and the plain
    "nothing on the calendar" do not. The screen draws the answer from this and does not read the state words itself."""
    out = _close(db=db, firm_id=firm_id, client_id=client_id, financial_year=financial_year, quarter=quarter,
                 challan_id=challan_id, section=section, actor=actor, may_write_compliance=may_write_compliance)
    return [{**a, "needs_action": (a.get("state") in (NOT_CLOSED, NOT_ALLOWED)
                                   or (a.get("state") == NOT_ON_THE_CALENDAR and "month" in a))} for a in out]


def _close(
    *, db, firm_id: str, client_id: str, financial_year: Optional[str], quarter: Optional[str], challan_id: str,
    section: Optional[str], actor: Optional[dict], may_write_compliance: bool,
) -> list[dict[str, Any]]:
    """Close the monthly deposit obligations this challan paid in full, and say what became of each month it paid in.

    Returns a list of `{state, closed, obligation_id, message, month}` (a closed month also carries `filed_on` and `reference`; the answers about the
    whole call, below, carry no month): one answer for each month closed, and for each month
    this challan paid some of that was left open (and why), or a single answer when the whole thing could not be looked at (no
    obligations on the calendar, no compliance access, a period that cannot be placed). A month the challan did not touch and
    that stays open, a month with no tax, and an obligation already filed are not answered. Ordinary reasons are states, not exceptions; an unexpected
    failure reading the books or the calendar propagates, and the router reports it without failing the recording."""
    if not firm_id or not client_id:
        return [answer(NOT_CLOSED, "The deposit obligation was not matched: the challan names no client.")]
    if deposit_due.is_salary(str(section or "")):
        return []
    try:
        months = months_of(str(financial_year or ""), str(quarter or ""))
    except (ValueError, TypeError):
        return [answer(NOT_CLOSED, f"The challan's period ({quarter!r}, FY {financial_year!r}) is not one this can match to "
                                   f"the calendar, so the monthly deposit obligations were left open. {FROM_COMPLIANCE}")]

    obligations = {str(r.get("period_start") or "")[:10]: r
                   for r in compliance_records_repo.find_all(firm_id=firm_id, client_id=client_id,
                                                             compliance_type=COMPLIANCE_TYPE)
                   if r.get("obligation_type") == OBLIGATION_TYPE}
    if not obligations:
        return [answer(NOT_ON_THE_CALENDAR, "The client has no monthly TDS deposit obligations on the compliance calendar, "
                                            "so none was closed.")]
    if not may_write_compliance:
        return [answer(NOT_ALLOWED, "Your access does not include Compliance, so the monthly TDS deposit obligations were "
                                    "left open. Someone with Compliance access can mark them filed there.")]

    last_year, last_mon = months[-1]
    window_of_quarter = worksheet.month_window(last_year, last_mon)
    quarter_rows, challans = worksheet.read_register(db, firm_id, client_id, window_of_quarter)
    today = ist_today()
    out: list[dict[str, Any]] = []
    for year, mon in months:
        record = obligations.get(date(year, mon, 1).isoformat())
        if record is None or record.get("status") in ("Filed", "Completed"):
            continue
        window = worksheet.month_window(year, mon)
        sheet, mapping, rows = worksheet.build_sheet(year, mon, window, quarter_rows, challans)
        if not rows:
            continue
        parts = [(challan, paise) for r in rows for challan, paise in mapping.for_deduction(r.get("id")).parts]
        decision = decide_month(
            today=today, due=window["due"], month_end=window["month_end"], what=_what(year, mon),
            month_name=_MONTH_NAMES[mon - 1], tax_paise=int(sheet.totals["tax_paise"]),
            outstanding_paise=int(sheet.totals["outstanding_paise"]),
            salary_rows=any(g.get("kind") == deposit_due.GAP_SALARY_ROW_IN_THIS_REGISTER for g in sheet.statutory_gaps),
            before_deduction=any(g.get("kind") == deposit_due.GAP_CHALLAN_BEFORE_DEDUCTION for g in sheet.statutory_gaps),
            paid_dates=[d for r in rows for d in deposit_due.paid_on_dates(r, mapping)],
            challans=[c for c, _ in parts],
            # Whether THIS challan paid some of the month decides whether a month left open is worth a sentence; a month
            # fully and punctually deposited is closed whichever challan made it so, which is also how a quarter's earlier
            # challans, recorded before the calendar was asked, are caught up the next time one is recorded.
            touched=any(str((c or {}).get("id")) == str(challan_id) for c, _ in parts))
        month = f"{year:04d}-{mon:02d}"
        if decision.filed_on is None:
            if decision.sentence:
                out.append({**answer(NOT_CLOSED, decision.sentence, record.get("id")), "month": month})
            continue
        result = mark_filed_and_answer(
            record, what=_what(year, mon), operation="tds_deposit_closes_obligation.mark_filed", firm_id=firm_id,
            client_id=client_id, compliance_type=COMPLIANCE_TYPE, filed_date=decision.filed_on.isoformat(),
            arn=decision.reference, actor=actor)
        if result.get("closed"):
            # Said, not only done: the date and serial are the register's order's (see `decide_month`), and a closed
            # obligation cannot be corrected afterwards, so the person is told what was recorded and can check it.
            result = {**result, "filed_on": decision.filed_on.isoformat(), "reference": decision.reference,
                      "message": f"{result['message']} Recorded as deposited on {decision.filed_on.isoformat()}"
                                 + (f", challan {decision.reference}" if decision.reference else "")
                                 + ", the date and serial the register's order gives it: check them against the challan."}
        out.append({**result, "month": month})
    return out
