"""An ESI remittance recorded as paid closes the ESI deposit obligation of the wage month it paid, when it was on time and covered what payroll computed (POST-A-267, the ESI half).

WHAT WAS WRONG
    A client with a payroll engagement carries an `ESI_DEPOSIT` obligation for every wage month on the compliance calendar
    (`compliance_obligation_service._payroll_obligations`, due the 15th of the following month, ESI (General) Regulations 1950
    reg. 31 through `compliance_engine.esi_deposit_due_date`). The remittance register (`statutory_remittances`,
    `POST /api/payroll/clients/{id}/remittances`) is where a deposit is recorded, and recording one never touched the calendar:
    a month's ESI paid and recorded read Overdue on Deadlines, the Compliance tab and the dashboard. It is the split the GST and
    ITR workspaces, the TDS statements and challans, the MCA filings and the advance-tax register had.

THE RULE (`decide`, a pure function, holds it)
    A remittance row names its WAGE MONTH and its scheme (typed or picked by the person recording it, so a wrong month is a
    person's slip and not an inference), so unlike a TDS challan (which carries a quarter and is matched to a month by order)
    the month is stated and not guessed. The obligation for that month is closed when ALL of these hold, and
    the first that fails decides the sentence:

      1. the remittance is recorded as PAID (a contribution only "submitted" is a return filed and money not yet gone: ESIC
         separates the two and the deposit is the second);
      2. payroll has a FINALISED run for the wage month (a draft's figures can still change), and the ESI it computed, the
         employee's share plus the employer's, summed from the run's slips, is above nil (a month that computed none has nothing
         to deposit and is not closed here: nothing says it was not simply unrun);
      3. the amount recorded is at least that sum. At least, not exactly: the challan's figure is what left the bank, and
         interest or damages can be added at the portal (migration 365's comment on the column says so; no section is cited
         here because none was confirmed from a primary text). An amount left at nil is "not recorded" and is said so: the
         default of the field must not read as having paid nothing;
      4. the payment is dated, is not in the future (`mark_filed` refuses a filing date that has not happened), is not before the
         wage month began, and is ON OR BEFORE the due date. A LATE PAYMENT CLOSES NOTHING BY ITSELF: the obligation, once Filed,
         does not reopen, and whether a deposit made after the 15th is to be recorded as filed late and on what date is the CA's
         to say from Compliance (the same rule the TDS deposit and advance-tax closers keep).

    The obligation is closed THROUGH `mark_filed` (`services/obligation_closure`), with the payment date as the date the deposit
    was made and the challan number, when there is one, as its reference. Nothing is written to `filings` and no period is
    locked: only GSTR-1 and GSTR-3B do that.

What it deliberately does not do:
      * EPF and salary TDS are not closed here, and the reason is each one's own. The EPF record (`epfo_ecr_filings`) is the
        RETURN uploaded to EPFO (a Regular, Supplementary or Revised ECR with the TRRN the portal gave back) and holds no payment
        date and no amount, so a filed ECR is not evidence that the contribution was deposited. Salary TDS is paid on a challan
        that carries a quarter and no month, which is the ambiguity `tds_deposit_closes_obligation` already has to live with;
      * professional tax has no obligation on the calendar (its due date is each state's own) so a PT remittance answers
        nothing;
      * a remittance edited or retracted later does not reopen an obligation it closed (a closed obligation says what was true
        when it was closed), and a deposit made outside the product and never recorded closes nothing;
      * it does not act for a caller without compliance access (closing an obligation is a compliance write, decided per person)
        and it never fails the recording of the remittance: whatever stops an obligation closing comes back in the answer;
      * it does not read payroll on behalf of a caller the Team screen has blocked from READING payroll: the route asks only
        payroll:write, the closer reads the run and its slips with the privileged client, and the sentence names the computed
        figures, so without payroll:read the answer says it was not checked and names no figure (`may_read_payroll`);
      * a retracted remittance does not reopen an obligation it closed (a Filed obligation can only go to Completed), so the
        retraction answers a sentence saying the calendar still reads filed (`note_after_retraction`).
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT: this records a deposit the CA has already made at the portal. It transmits
    nothing.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from core.db_provider import privileged_for
from core.db_paging import fetch_all
from core.ist_clock import ist_today
from domain.money_sentence import rupee_text
from repositories.compliance_records_repository import compliance_records_repo
from services import compliance_engine as ce
from services.obligation_closure import (
    FROM_COMPLIANCE, NOT_ALLOWED, NOT_CLOSED, NOT_ON_THE_CALENDAR, answer, mark_filed_and_answer,
)

#: What the obligation is filed under on the calendar (`compliance_obligation_service._payroll_obligations`).
COMPLIANCE_TYPE = "Payroll"
OBLIGATION_TYPE = "ESI_DEPOSIT"

#: What the CA can actually do when the figures on a recorded entry are wrong. The register keeps ONE row per client, scheme and
#: month and a second recording REPLACES it, so "record the remainder" would erase the first amount; and the payroll screen offers
#: the record form only while nothing is recorded, so the way to a corrected entry is to retract and record again.
RETRACT_AND_RECORD = ("Retract this entry and record it again with the total that left the bank (a second entry for the same "
                      "month replaces the first and does not add to it), or mark the obligation filed from Compliance.")

#: The run statuses whose slips are final (`routers/payroll._finalised_run_inputs`).
FINAL_RUN_STATUSES = ("finalized", "paid")

_MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                "November", "December")


@dataclass(frozen=True)
class Decision:
    """What to do with one month's open obligation: close it (`filed_on` set, with the challan number as `reference` when there
    is one) or leave it, with a `sentence` for the CA."""
    filed_on: Optional[date] = None
    reference: Optional[str] = None
    sentence: Optional[str] = None


def _what(wage_month: str) -> str:
    year, mon = int(wage_month[:4]), int(wage_month[5:7])
    return f"ESI deposit obligation for {_MONTH_NAMES[mon - 1]} {year}"


def decide(*, today: date, due: date, month_start: date, what: str, owed_paise: Optional[int], employee_paise: int = 0,
           employer_paise: int = 0, paid_paise: int, paid_on: Optional[date],
           challan_number: Optional[str]) -> Decision:
    """The rule, as a pure function. `owed_paise` is None when payroll has no finalised run for the month. Checked in the order
    of the module docstring; a month is closed only if it passes every one."""
    def leave(reason: str, remedy: str) -> Decision:
        return Decision(sentence=f"The {what} was left open: {reason} {remedy}")

    if owed_paise is None:
        return leave("payroll has no finalised run for that wage month, so there is nothing to compare the amount paid with.",
                     "Once the month's payroll run is finalised, retract this entry and record it again, or mark the obligation "
                     "filed from Compliance.")
    if owed_paise <= 0:
        return leave("payroll computed no ESI for that month.", FROM_COMPLIANCE)
    if paid_paise <= 0:
        return leave("the amount paid was not recorded (it was left at nil).", RETRACT_AND_RECORD)
    if paid_paise < owed_paise:
        return leave(f"the amount recorded, {rupee_text(paid_paise)}, is less than the {rupee_text(owed_paise)} payroll computed "
                     f"for the month (the employees' {rupee_text(employee_paise)} and the employer's {rupee_text(employer_paise)}).",
                     "Check the amount. " + RETRACT_AND_RECORD)
    if paid_on is None:
        return leave("the remittance has no payment date.", "Retract this entry and record it again with the date it was paid.")
    if paid_on > today:
        return leave(f"its payment is dated {paid_on.isoformat()}, which has not happened yet.",
                     "Check the date: retract this entry and record it again with the right one.")
    if paid_on < month_start:
        return leave(f"its payment is dated {paid_on.isoformat()}, before the wage month began, so it cannot be this month's "
                     "contribution.", "Check the date and the wage month: retract this entry and record it again with the right ones.")
    if paid_on > due:
        return leave(f"the payment is dated {paid_on.isoformat()}, after the due date {due.isoformat()}.",
                     "Mark it filed from Compliance with the date it really went.")
    return Decision(filed_on=paid_on, reference=(challan_number or "").strip() or None)


def _as_date(value: Any) -> Optional[date]:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def esi_owed(db, firm_id: str, client_id: str, wage_month: str) -> Optional[tuple[int, int]]:
    """(the employees' ESI, the employer's ESI) for the wage month, summed from the slips of the client's FINALISED run for it, or
    None when there is no finalised run. A run is unique to (firm, client, month) (migration 237)."""
    reader = privileged_for(db)
    runs = (reader.table("payroll_runs").select("id, status").eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("month", wage_month).execute().data) or []
    run = next((r for r in runs if r.get("status") in FINAL_RUN_STATUSES), None)
    if run is None:
        return None
    # PAGED: a run of more than the gateway's row cap would otherwise be summed short, the "owed" figure would be understated and a
    # payment below the true ESI would close the obligation. `id` is in the projection because the pager's cursor reads it.
    slips = fetch_all(lambda: reader.table("payroll_slips").select("id, esi_employee_paise, esi_employer_paise").eq("run_id", run["id"]),
                      label="esi_owed.slips")
    return (sum(int(s.get("esi_employee_paise") or 0) for s in slips), sum(int(s.get("esi_employer_paise") or 0) for s in slips))


def close_for_recorded_remittance(
    *, db, firm_id: str, client_id: str, remittance: dict, actor: Optional[dict], may_write_compliance: bool,
    may_read_payroll: bool = True,
) -> list[dict[str, Any]]:
    """Answer what became of the wage month's ESI deposit obligation when this remittance was recorded: `[]` when there is
    nothing to say, otherwise one `{state, closed, obligation_id, message, month, needs_action}` (a closed one also carries
    `filed_on` and `reference`). `needs_action` is whether somebody has something to do about it: the screen draws its tone from
    it and does not read the state words. Ordinary reasons are states, not exceptions; an unexpected failure reading the books
    or the calendar propagates and the router reports it without failing the recording."""
    if remittance.get("scheme") != "esic" or remittance.get("status") != "paid":
        return []
    wage_month = str(remittance.get("wage_month") or "")
    try:
        year, mon = int(wage_month[:4]), int(wage_month[5:7])
        month_start = date(year, mon, 1)
    except (ValueError, IndexError):
        return []
    what = _what(wage_month)
    if not firm_id or not client_id:
        return [{**answer(NOT_CLOSED, f"The {what} was not matched: the remittance names no client."), "month": wage_month,
                 "needs_action": True}]

    record = next((r for r in compliance_records_repo.find_all(firm_id=firm_id, client_id=client_id, compliance_type=COMPLIANCE_TYPE)
                   if r.get("obligation_type") == OBLIGATION_TYPE and str(r.get("period_start") or "")[:10] == month_start.isoformat()),
                  None)
    if record is None:
        return [{**answer(NOT_ON_THE_CALENDAR, f"The client has no {what} on the compliance calendar, so none was closed."),
                 "month": wage_month, "needs_action": False}]
    if record.get("status") in ("Filed", "Completed"):
        return []
    if not may_write_compliance:
        return [{**answer(NOT_ALLOWED, f"Your access does not include Compliance, so the {what} was left open. Someone with "
                                       "Compliance access can mark it filed there.", record.get("id")),
                 "month": wage_month, "needs_action": True}]

    if not may_read_payroll:
        return [{**answer(NOT_ALLOWED, f"Your access does not include payroll, so the {what} was not checked against what payroll "
                                       "computed and was left open. Someone with payroll access can retract this entry and record "
                                       "it again, or mark the obligation filed from Compliance.", record.get("id")),
                 "month": wage_month, "needs_action": True}]
    owed = esi_owed(db, firm_id, client_id, wage_month)
    employee, employer = owed if owed is not None else (0, 0)
    decision = decide(
        today=ist_today(), due=ce.esi_deposit_due_date(year, mon), month_start=month_start, what=what,
        owed_paise=None if owed is None else employee + employer, employee_paise=employee, employer_paise=employer,
        paid_paise=int(remittance.get("amount_paise") or 0), paid_on=_as_date(remittance.get("paid_on")),
        challan_number=remittance.get("challan_number"))
    if decision.filed_on is None:
        return [{**answer(NOT_CLOSED, decision.sentence or f"The {what} was left open. {FROM_COMPLIANCE}", record.get("id")),
                 "month": wage_month, "needs_action": True}]
    result = mark_filed_and_answer(
        record, what=what, operation="esi_deposit_closes_obligation.mark_filed", firm_id=firm_id, client_id=client_id,
        compliance_type=COMPLIANCE_TYPE, filed_date=decision.filed_on.isoformat(), arn=decision.reference, actor=actor)
    if result.get("closed"):
        result = {**result, "filed_on": decision.filed_on.isoformat(), "reference": decision.reference,
                  "message": f"{result['message']} Recorded as deposited on {decision.filed_on.isoformat()}"
                             + (f", challan {decision.reference}" if decision.reference else "") + "."}
    return [{**result, "month": wage_month, "needs_action": result.get("state") in (NOT_CLOSED, NOT_ALLOWED)}]


def note_after_retraction(*, db, firm_id: str, client_id: str, remittance: dict) -> Optional[str]:
    """The sentence to answer a retraction with when the remittance retracted was an ESI one whose wage month's obligation reads
    Filed on the calendar, or None. A Filed obligation can only go to Completed, so the retraction cannot reopen it, and a person
    who retracts a wrong entry must not be left believing the calendar was corrected too. It says what the calendar holds and
    where to correct it, and does not guess whether this remittance is what closed it."""
    if remittance.get("scheme") != "esic" or not firm_id or not client_id:
        return None
    wage_month = str(remittance.get("wage_month") or "")
    try:
        month_start = date(int(wage_month[:4]), int(wage_month[5:7]), 1)
    except (ValueError, IndexError):
        return None
    record = next((r for r in compliance_records_repo.find_all(firm_id=firm_id, client_id=client_id, compliance_type=COMPLIANCE_TYPE)
                   if r.get("obligation_type") == OBLIGATION_TYPE and str(r.get("period_start") or "")[:10] == month_start.isoformat()),
                  None)
    if record is None or record.get("status") not in ("Filed", "Completed"):
        return None
    filed_on = str(record.get("filed_date") or "")[:10]
    return (f"The compliance calendar still shows the {_what(wage_month)} as filed"
            + (f" on {filed_on}" if filed_on else "")
            + ". A filed obligation cannot be reopened from here, so if the entry just retracted was wrong, correct that obligation "
              "from Compliance.")
