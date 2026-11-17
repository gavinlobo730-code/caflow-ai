"""A section 192 challan that names its wage month closes that month's salary TDS deposit obligation, when the month's recorded salary
challans paid on time what payroll deducted (POST-A-267, the salary half).

WHAT WAS WRONG
    A client with a payroll engagement carries a `TDS_SALARY_DEPOSIT` obligation for every month on the compliance calendar
    (`compliance_obligation_service._payroll_obligations`, due by Rule 30(2)'s date through `compliance_engine.tds_deposit_due_date`:
    the seventh of the next month, 30 April for March). The salary tax is deposited on a challan 281 recorded in the TDS register
    (`tds_challans`, section 192), and a challan carries a quarter and no month, so recording one never touched the calendar and a
    month whose tax was paid on time read Overdue on Deadlines, the Compliance tab and the dashboard. The non-salary closer matches
    challans to months by the register's order of dated deductions; payroll's tax sits on a run's slips and has no such order.

THE RULE (`decide`, a pure function, holds it)
    A salary challan may name the wage month whose tax it deposits (`tds_challans.deduction_month`, migration 695), typed by the person
    recording it, so the month is stated and not guessed (the ESI remittance register's shape). The month's obligation is closed when
    ALL of these hold, and the first that fails decides the sentence:

      1. payroll has a FINALISED run for the month (a draft's figures can still change) and the section 192 tax on its slips is above
         nil (a month that deducted none has nothing to deposit and is not closed here: nothing says it was not simply unrun);
      2. no challan naming the month is against a demand (minor head 400 is not a deposit of the tax deducted);
      3. every challan naming the month is dated, none in the future (`mark_filed` refuses a day that has not happened) and none
         before the month began;
      4. the tax on the challans naming the month that were paid ON OR BEFORE the due date is at least what payroll deducted. At
         least, not exactly: a challan's tax is the remainder after the surcharge, interest and penalty it records, and a person may
         round. A challan paid after the due date counts for nothing here, so A LATE DEPOSIT CLOSES NOTHING BY ITSELF and the
         sentence says by how much the punctual ones fall short: whether a late deposit is to be recorded as filed late and on what
         date is the CA's to say from Compliance (the rule the TDS deposit, ESI and advance-tax closers keep);
      5. it is not a month a PERSON REOPENED whose covering challans are all among those it was closed on: closing it again on them
         would undo the correction (the non-salary closer's rule, with the same record, `closing_tds_challan_ids`).

    The obligation is closed THROUGH `mark_filed` (`services/obligation_closure`) with the last punctual payment's date as the date
    the deposit was made and that day's challan serial as its reference, and the ids of the challans that covered it are kept on the
    obligation so a retraction of one of them reopens exactly this month (`tds_challan_retraction_service`). Nothing is written to
    `filings` and no period is locked.

WHICH MONTH THE TAX WAS DEDUCTED IN
    The calendar's obligation is generated per WAGE month with Rule 30(2)'s date from that month, and the 24Q built from payroll dates
    the month's salary on its last day (`domain/payroll/form24q`); this closer follows the calendar it closes and compares a month's
    challans with the run OF THAT WAGE MONTH. Where a month's salary is paid after the month ends, the date the tax is due from may be
    later than the calendar's; a challan the calendar's date calls punctual is then punctual on either reading, so closing only on
    such challans is never a false "on time". Which month the tax counts as deducted in is not decided here.

What it deliberately does not do:
      * a salary challan with no month stated closes nothing and is answered with a sentence saying how to state one;
      * the EPF deposit is not closed here or anywhere (its record is the ECR return, which holds no payment), and Form 27EQ has no
        obligation: both wait on statutory readings on the owner's list (S23, S24);
      * a challan edited later does not reopen an obligation it closed; a retraction does (see above);
      * it does not act for a caller without compliance write access, and it reads payroll's figures with the privileged client, so it
        names no payroll figure to a caller the Team screen has blocked from reading payroll (`may_read_payroll`);
      * it never fails the recording of the challan: whatever stops an obligation closing comes back in the answer.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT: this records a deposit the CA has already made at the bank. It transmits nothing.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from core.db_paging import fetch_all
from core.db_provider import privileged_for
from core.ist_clock import ist_today
from domain.money_sentence import rupee_text
from domain.practice.compliance_overdue import is_settled
from domain.tds import deposit_due
from domain.tds.section_rates import quarter_dates
from repositories.compliance_records_repository import compliance_records_repo
from services import compliance_engine as ce
from services.obligation_closure import (
    FROM_COMPLIANCE, NOT_ALLOWED, NOT_CLOSED, NOT_ON_THE_CALENDAR, answer, mark_filed_and_answer,
)
from services.tds_deposit_closes_obligation import closed_on

#: What the obligation is filed under on the calendar (`compliance_obligation_service._payroll_obligations`).
COMPLIANCE_TYPE = "Payroll"
OBLIGATION_TYPE = "TDS_SALARY_DEPOSIT"

#: The run statuses whose slips are final (`routers/payroll._finalised_run_inputs`; the ESI closer reads the same).
FINAL_RUN_STATUSES = ("finalized", "paid")

_MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                "November", "December")

#: How a person states the month on a challan already recorded: the register keeps no edit, so it is retracted and recorded again.
STATE_THE_MONTH = ("Record the challan with the wage month it pays (retract this one on the Challans tab and record it again with "
                   "the month), or mark the obligation filed from Compliance.")


def month_problem(*, deduction_month: Optional[str], section: str, financial_year: str, quarter: str) -> Optional[str]:
    """Why a stated wage month cannot go on this challan, in words, or None when it can (or none was stated). The door's rule:
    a month only on a salary challan, and only one of the challan's own quarter of its own financial year."""
    if deduction_month is None or not str(deduction_month).strip():
        return None
    text = str(deduction_month).strip()
    try:
        year, mon = int(text[:4]), int(text[5:7])
        if len(text) != 7 or text[4] != "-" or not 1 <= mon <= 12:
            raise ValueError
        first = date(year, mon, 1)
    except (ValueError, IndexError):
        return "The wage month is not a month: give it as YYYY-MM, such as 2026-04."
    if not deposit_due.is_salary(section or ""):
        return ("A wage month is stated only on a salary challan (section 192): a challan under any other section is matched to "
                "its deductions by the register's order. Leave the month blank.")
    try:
        start, end, _due = quarter_dates(str(financial_year), str(quarter))
    except (ValueError, TypeError):
        return None                                     # the quarter itself is refused by its own check
    if not (date.fromisoformat(start) <= first <= date.fromisoformat(end)):
        # The rule is the WAGE month's quarter (the challan deposits that month's tax), so the sentence names that quarter and its year
        # rather than the quarter the salary happened to be paid in, which for March wages paid in April is another year.
        from core.ist_clock import ist_fy_label
        from services.compliance_engine import tds_quarter_of_month
        return (f"{_MONTH_NAMES[mon - 1]} {year} is not in {quarter} of FY {financial_year}, the quarter this challan is recorded "
                f"for. A salary challan is recorded for the quarter of the wage month whose tax it deposits: record it for "
                f"{tds_quarter_of_month(mon)} of FY {ist_fy_label(first)}, or check the month.")
    return None


def _what(year: int, mon: int) -> str:
    return f"TDS deposit (salary) {_MONTH_NAMES[mon - 1]} {year} obligation"


def _as_date(value: Any) -> Optional[date]:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def challan_tax_paise(challan: dict) -> int:
    """The tax a challan paid: its `tds_paise` plus its `surcharge_paise`, the amount that left the bank less the interest and the
    penalty (the non-salary register's reading, `deposit_due.mapping_from_register`)."""
    return int(challan.get("tds_paise") or 0) + int(challan.get("surcharge_paise") or 0)


@dataclass(frozen=True)
class Decision:
    """Close the month (`filed_on` set, `reference` the serial of the last challan paid that day) or leave it with a `sentence`."""
    filed_on: Optional[date] = None
    reference: Optional[str] = None
    sentence: Optional[str] = None
    covering_ids: frozenset = frozenset()


def decide(*, today: date, due: date, month_start: date, what: str, deducted_paise: Optional[int], challans: list[dict],
           closed_on_before: Optional[frozenset] = None) -> Decision:
    """The rule, as a pure function. `deducted_paise` is None when payroll has no finalised run for the month; `challans` are every
    challan of the client naming the month. Checked in the order of the module docstring."""
    def leave(reason: str, remedy: str) -> Decision:
        return Decision(sentence=f"The {what} was left open: {reason} {remedy}")

    if deducted_paise is None:
        return leave("payroll has no finalised run for that wage month, so there is nothing to compare the challans with.",
                     "Once the month's run is finalised it is looked at again when a salary challan for the month is recorded, or "
                     "it can be marked filed from Compliance.")
    if deducted_paise <= 0:
        return leave("payroll deducted no tax on salary for that month.", FROM_COMPLIANCE)
    if any(str(c.get("minor_head") or "").strip() == "400" for c in challans):
        return leave("a challan naming the month is against a demand (minor head 400), and a payment against a demand is not a "
                     "deposit of the tax deducted.", FROM_COMPLIANCE)
    dated = [(c, _as_date(c.get("payment_date"))) for c in challans]
    if any(d is None for _, d in dated):
        return leave("a challan naming the month has no payment date.", "Check the challan on the Challans tab.")
    future = [d for _, d in dated if d > today]
    if future:
        return leave(f"a challan naming the month is dated {max(future).isoformat()}, which has not happened yet.",
                     "Check the date on the challan.")
    early = [d for _, d in dated if d < month_start]
    if early:
        return leave(f"a challan naming the month is dated {min(early).isoformat()}, before the wage month began, so it cannot be "
                     "that month's deposit.", "Check the date and the month on the challan.")
    punctual = [(c, d) for c, d in dated if d <= due]
    paid = sum(challan_tax_paise(c) for c, _ in punctual)
    late = [d for _, d in dated if d > due]
    if paid < deducted_paise:
        short = deducted_paise - paid
        tail = (f" A challan dated after the due date {due.isoformat()} is not counted here." if late else "")
        return leave(f"the salary challans naming the month paid on or before the due date {due.isoformat()} come to "
                     f"{rupee_text(paid)}, {rupee_text(short)} less than the {rupee_text(deducted_paise)} payroll deducted for the "
                     f"month.{tail}",
                     ("Mark it filed from Compliance with the date it really went." if late
                      else "Record the challan that paid the rest; it is looked at again when one is recorded."))
    covering = frozenset(str(c["id"]) for c, _ in punctual if c.get("id"))
    if closed_on_before and covering and covering <= closed_on_before:
        return leave("it was closed on these same challans and a person reopened it, and they still cover it.",
                     "It is looked at again when a different challan covers it, or it can be marked filed from Compliance.")
    last = max(d for _, d in punctual)
    same_day = [c for c, d in punctual if d == last]
    last_challan = max(same_day, key=lambda c: str(c.get("challan_no") or ""))
    return Decision(filed_on=last, reference=str(last_challan.get("challan_no") or "").strip() or None, covering_ids=covering)


def tax_deducted(db, firm_id: str, client_id: str, wage_month: str) -> Optional[int]:
    """The section 192 tax on the slips of the client's FINALISED run for the wage month, or None when there is no finalised run. A
    run is unique to (firm, client, month) (migration 237). Paged, so a large run is not summed short."""
    reader = privileged_for(db)
    runs = (reader.table("payroll_runs").select("id, status").eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("month", wage_month).execute().data) or []
    run = next((r for r in runs if r.get("status") in FINAL_RUN_STATUSES), None)
    if run is None:
        return None
    slips = fetch_all(lambda: reader.table("payroll_slips").select("id, tds_paise").eq("run_id", run["id"]),
                      label="salary_tds_deducted.slips")
    return sum(int(s.get("tds_paise") or 0) for s in slips)


def challans_naming(db, firm_id: str, client_id: str, wage_month: str) -> list[dict]:
    """Every salary challan of the client that names the wage month (a retracted challan is gone from the register)."""
    rows = fetch_all(lambda: (privileged_for(db).table("tds_challans")
                              .select("id, section, payment_date, challan_no, tds_paise, surcharge_paise, minor_head, deduction_month")
                              .eq("firm_id", firm_id).eq("client_id", client_id).eq("deduction_month", wage_month)),
                     label="salary_tds_challans_naming")
    return [r for r in rows if deposit_due.is_salary(str(r.get("section") or ""))]


def _record_what_closed_it(record: dict, *, firm_id: str, client_id: str, covering: frozenset) -> None:
    """Keep the ids of the challans that covered the month on the obligation just closed. NEVER FAILS THE CLOSE (the non-salary
    closer's shape): without the record a retraction names the month and leaves it to a person."""
    if not covering:
        return
    try:
        compliance_records_repo.stamp_closing_tds_challans(record["id"], firm_id, sorted(covering), client_id=client_id)
    except Exception as exc:                                    # noqa: BLE001
        from core.observability import capture_soft_failure
        capture_soft_failure(exc, operation="tds_salary_deposit_closes_obligation.record_challans", firm_id=firm_id,
                             client_id=client_id)


def close_for_recorded_challan(*, db, firm_id: str, client_id: str, challan: dict, actor: Optional[dict],
                               may_write_compliance: bool, may_read_payroll: bool) -> list[dict[str, Any]]:
    """What became of the salary deposit obligation of the month this salary challan names: `[]` for a challan that is not a salary
    one, otherwise one `{state, closed, obligation_id, message, month, needs_action}` (a closed one also carries `filed_on` and
    `reference`). Ordinary reasons are states; an unexpected failure propagates and the router reports it without failing the
    recording."""
    if not deposit_due.is_salary(str(challan.get("section") or "")):
        return []
    wage_month = str(challan.get("deduction_month") or "").strip()
    if not wage_month:
        return [{**answer(NOT_CLOSED, "This salary challan names no wage month, so no monthly salary TDS deposit obligation was "
                                      "closed. " + STATE_THE_MONTH),
                 "month": None, "needs_action": True}]
    year, mon = int(wage_month[:4]), int(wage_month[5:7])
    month_start = date(year, mon, 1)
    what = _what(year, mon)
    if not firm_id or not client_id:
        return [{**answer(NOT_CLOSED, f"The {what} was not matched: the challan names no client."), "month": wage_month,
                 "needs_action": True}]
    record = next((r for r in compliance_records_repo.find_all(firm_id=firm_id, client_id=client_id, compliance_type=COMPLIANCE_TYPE)
                   if r.get("obligation_type") == OBLIGATION_TYPE and str(r.get("period_start") or "")[:10] == month_start.isoformat()),
                  None)
    if record is None:
        return [{**answer(NOT_ON_THE_CALENDAR, f"The client has no {what} on the compliance calendar, so none was closed."),
                 "month": wage_month, "needs_action": False}]
    if is_settled(record.get("status")):
        return []
    if not may_write_compliance:
        return [{**answer(NOT_ALLOWED, f"Your access does not include Compliance, so the {what} was left open. Someone with "
                                       "Compliance access can mark it filed there.", record.get("id")),
                 "month": wage_month, "needs_action": True}]
    if not may_read_payroll:
        return [{**answer(NOT_ALLOWED, f"Your access does not include payroll, so the {what} was not checked against the tax payroll "
                                       "deducted and was left open. Someone with payroll access can record a challan for the month, "
                                       "or it can be marked filed from Compliance.", record.get("id")),
                 "month": wage_month, "needs_action": True}]
    decision = decide(today=ist_today(), due=ce.tds_deposit_due_date(year, mon), month_start=month_start, what=what,
                      deducted_paise=tax_deducted(db, firm_id, client_id, wage_month),
                      challans=challans_naming(db, firm_id, client_id, wage_month), closed_on_before=closed_on(record))
    if decision.filed_on is None:
        return [{**answer(NOT_CLOSED, decision.sentence or f"The {what} was left open. {FROM_COMPLIANCE}", record.get("id")),
                 "month": wage_month, "needs_action": True}]
    result = mark_filed_and_answer(
        record, what=what, operation="tds_salary_deposit_closes_obligation.mark_filed", firm_id=firm_id, client_id=client_id,
        compliance_type=COMPLIANCE_TYPE, filed_date=decision.filed_on.isoformat(), arn=decision.reference, actor=actor)
    if result.get("closed"):
        _record_what_closed_it(record, firm_id=firm_id, client_id=client_id, covering=decision.covering_ids)
        result = {**result, "filed_on": decision.filed_on.isoformat(), "reference": decision.reference,
                  "message": f"{result['message']} Recorded as deposited on {decision.filed_on.isoformat()}"
                             + (f", challan {decision.reference}" if decision.reference else "") + "."}
    return [{**result, "month": wage_month, "needs_action": result.get("state") in (NOT_CLOSED, NOT_ALLOWED)}]
