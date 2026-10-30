"""Advance tax recorded in the income-tax workspace closes the instalment obligation it paid.

WHAT WAS WRONG
    A client with an Advance Tax engagement carries four obligations on the compliance calendar
    (`compliance_obligation_service._advance_tax_obligations`, obligation type `ADVANCE_TAX`: 15% by 15 June, 45% by 15
    September, 75% by 15 December, 100% by 15 March; the period start and end are the instalment's own due date). The
    advance-tax register (`advance_tax_payments`, `POST /api/income-tax/advance-tax`) is where the payments are recorded,
    and recording one never touched the calendar: a CA who had paid and recorded all four instalments saw them Paid
    beside a Deadlines screen, a Compliance tab and a dashboard that called the same four obligations overdue. It is the
    split the GST and ITR workspaces, the TDS statements and challans and the MCA filings had (POST-A-264, POST-A-267),
    and the register was left over because the instalment needs a rule for what "paid" means that a return does not.

THE RULE (`decide_instalment`, a pure function, holds it)
    An instalment is paid when the CUMULATIVE tax paid on or before its due date reaches the cumulative percentage of the
    estimated tax that the instalment requires. That is §211's requirement and it is the measure the §234C engine already
    uses, so the engine supplies it (`compute_234c_interest`: `required_cumulative_paise`, `actual_cumulative_paid_paise`)
    and this module decides nothing about the arithmetic:

      * a payment counts toward an instalment only if it is dated on or before THAT instalment's due date, so one paid
        after the date meets nothing by itself and is never closed on (a late payment is the case where the CA states the
        date, from Compliance);
      * a payment with no date counts toward nothing, as in the engine;
      * the date the obligation is closed with is the day the cumulative requirement was first reached, and the reference
        is the challan number of the payment made that day (the last, when there are several): a closed obligation cannot be
        corrected afterwards, so the answer says what was recorded and tells the person to check it against the challan;
      * a payment dated in the future is not yet a fact, and `mark_filed` refuses it: the instalment is left open with a
        sentence, and is caught up the next time the register is saved;
      * an instalment short of the requirement is left open, and when its due date has passed and a payment was recorded
        against it the answer says by how much it fell short (or that the total paid would have covered it had it all been
        on time); one nothing was recorded against is not answered, because the screens already call it overdue;
      * an estimate of nothing requires nothing, and nothing is closed on it.

    The estimate is the CA's own figure from the register; the §234C(1) proviso for income that arose later is NOT applied
    here, because the register does not store it. So an instalment that the proviso would excuse stays open with the
    sentence, which is the safe direction: nothing is closed that the full requirement did not meet.

    A presumptive assessee (§44AD or §44ADA) pays the whole amount by 15 March under the proviso to §211(1), and the register
    then holds that one instalment. The calendar still carries all four obligations, and nothing here can mark the other
    three not required (there is no such state), so when the register is presumptive the answer says that the earlier three
    were left as they are and are the CA's to mark from Compliance.

    The obligation is closed THROUGH `mark_filed` (see `services/obligation_closure`). `mark_filed` does not ask that an
    advance-tax instalment wait for a period's end (it is lawfully paid before the due date), writes nothing to `filings`
    and locks no period.

    What it deliberately does not do:
      * the self-assessment challan (§140A, `self_assessment_challans`) closes nothing: that tax is paid with the return and
        no obligation on the calendar stands for it, and a challan under minor head 100 is not read here;
      * a payment edited or removed later does not reopen an obligation it closed (a closed obligation says what was true
        when it was closed);
      * a payment made outside the product and never recorded closes nothing: the CA marks it from Compliance;
      * a client with no advance-tax obligation on the calendar is answered nothing: the register stands on its own and has
        nothing to update;
      * it does not act for a caller without compliance access (closing an obligation is a compliance write, decided per
        person), and it never fails the saving of the register: whatever stops an obligation closing comes back in the
        answer and goes to the error reporter.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT: this records a payment the CA has already made at the bank. It transmits
    nothing.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, NamedTuple, Optional

from core.ist_clock import ist_today
from domain.income_tax.advance_tax_interest_engine import (
    InstallmentPayment, compute_234c_interest, installment_schedule,
)
from domain.money_sentence import rupee_text
from repositories.compliance_records_repository import compliance_records_repo
from services.obligation_closure import FROM_COMPLIANCE, NOT_ALLOWED, NOT_CLOSED, answer, mark_filed_and_answer

#: What the obligations are filed under on the calendar (`compliance_obligation_service._spec("ADVANCE_TAX", "Income Tax", ...)`).
COMPLIANCE_TYPE = "Income Tax"
OBLIGATION_TYPE = "ADVANCE_TAX"

#: The one instalment a §44AD/§44ADA assessee has (`advance_tax_interest_engine.PRESUMPTIVE_INSTALLMENT_RULES`).
_PRESUMPTIVE_INSTALMENT = 4


class Payment(NamedTuple):
    paid_paise: int
    paid_on: Optional[date]
    challan: Optional[str]


@dataclass(frozen=True)
class Decision:
    """`filed_on` set: close the obligation with it (and `reference`). Otherwise `sentence`, when there is something to say."""
    filed_on: Optional[date] = None
    reference: Optional[str] = None
    sentence: Optional[str] = None


def _date_text(d: date) -> str:
    return f"{d.day} {d:%B %Y}"


def decide_instalment(
    *, label: str, due: date, required_paise: int, payments: list[Payment], today: date, touched: bool,
) -> Decision:
    """Whether the instalment due on `due` is paid, and the sentence when it is not and somebody should hear why.

    `required_paise` is the cumulative amount the instalment requires (the engine's), `payments` every payment in the
    register whatever instalment slot it was recorded against, `today` the Indian day. `touched` is whether a payment was
    recorded against THIS instalment's own slot: an instalment that is short and past due is explained only to the person who
    recorded something against it, because the cumulative total is the same on every later date and a sentence about each one
    would say one thing three times."""
    if required_paise <= 0:
        return Decision()
    dated = sorted((p for p in payments if p.paid_on is not None and p.paid_paise > 0),
                   key=lambda p: (p.paid_on, str(p.challan or "")))
    on_time = [p for p in dated if p.paid_on <= due]
    running, met_on = 0, None
    for p in on_time:
        running += p.paid_paise
        if running >= required_paise:
            met_on = p.paid_on
            break
    if met_on is not None:
        if met_on > today:
            return Decision(sentence=(
                f"{label} is covered only by a payment dated {_date_text(met_on)}, which has not come yet, so it was left "
                "open. Save the register again once the payment is made."))
        same_day = [p for p in on_time if p.paid_on == met_on and p.challan]
        last = max(same_day, key=lambda p: str(p.challan), default=None)
        return Decision(filed_on=met_on, reference=str(last.challan) if last else None)
    if due >= today:
        return Decision()                    # still time: a shortfall now is not yet a shortfall
    paid_by_due = sum(p.paid_paise for p in on_time)
    paid_ever = sum(p.paid_paise for p in dated)
    if paid_ever <= 0 or not touched:
        return Decision()                    # nothing recorded against it: the screens already call it overdue
    if paid_ever >= required_paise:
        return Decision(sentence=(
            f"{label} was left open: the payments recorded come to {rupee_text(paid_ever)}, enough for the "
            f"{rupee_text(required_paise)} it needed, but only {rupee_text(paid_by_due)} was paid on or before "
            f"{_date_text(due)}. Mark it filed from Compliance with the date it was met, if that is right."))
    return Decision(sentence=(
        f"{label} was left open: {rupee_text(paid_by_due)} was paid on or before {_date_text(due)} against the "
        f"{rupee_text(required_paise)} it needed ({rupee_text(required_paise - paid_by_due)} short). {FROM_COMPLIANCE}"))


def _parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _what(percent: int, due: date, financial_year: str) -> str:
    return f"Advance tax obligation ({percent}% by {_date_text(due)}) for FY {financial_year}"


def close_for_saved_register(
    *, firm_id: str, client_id: str, financial_year: str, rows: list[dict], actor: Optional[dict],
    may_write_compliance: bool,
) -> list[dict[str, Any]]:
    """Close the instalment obligations the saved register shows paid, and say what became of each one that was not.

    `rows` is the register for the financial year exactly as it was just saved (one row per instalment: its number, due date,
    the estimated tax, the amount, date and challan paid). Returns `{state, closed, obligation_id, message, needs_action,
    instalment, due_date}` per answer; an instalment that is open and has nothing to say, one already filed and one that
    cannot be judged yet are not answered. Ordinary reasons are states, not exceptions; an unexpected failure reading the
    calendar propagates, and the router reports it without failing the saving."""
    if not firm_id or not client_id:
        return [_with_action(answer(NOT_CLOSED, "The advance-tax obligations were not matched: the register names no client."))]
    if not rows:
        return []
    estimate = max(int(r.get("estimated_tax_paise") or 0) for r in rows)
    if estimate <= 0:
        return []
    numbers = {int(r["installment_number"]) for r in rows}
    presumptive = numbers == {_PRESUMPTIVE_INSTALMENT}
    payments = [Payment(int(r.get("paid_amount_paise") or 0), _parse_date(r.get("paid_date")),
                        str(r.get("challan_number") or "").strip() or None) for r in rows]
    result = compute_234c_interest(
        financial_year, estimate,
        [InstallmentPayment(int(r["installment_number"]), int(r.get("paid_amount_paise") or 0),
                            _parse_date(r.get("paid_date"))) for r in rows],
        is_presumptive_44ad_44ada=presumptive)

    obligations = {str(r.get("period_start") or "")[:10]: r
                   for r in compliance_records_repo.find_all(firm_id=firm_id, client_id=client_id,
                                                             compliance_type=COMPLIANCE_TYPE)
                   if r.get("obligation_type") == OBLIGATION_TYPE}
    today = ist_today()
    out: list[dict[str, Any]] = []
    closable: list[tuple[Any, Decision, dict]] = []
    for inst in result.installments:
        record = obligations.get(inst.due_date.isoformat())
        if record is None or record.get("status") in ("Filed", "Completed"):
            continue
        what = _what(inst.cumulative_required_percent, inst.due_date, financial_year)
        decision = decide_instalment(
            label=what, due=inst.due_date, required_paise=inst.required_cumulative_paise, payments=payments, today=today,
            touched=any(int(r["installment_number"]) == inst.installment_number and int(r.get("paid_amount_paise") or 0) > 0
                        for r in rows))
        if decision.filed_on is not None:
            closable.append((inst, decision, record))
        elif decision.sentence:
            out.append(_with_action({**answer(NOT_CLOSED, decision.sentence, record.get("id")),
                                     "instalment": inst.installment_number, "due_date": inst.due_date.isoformat()}))

    if closable and not may_write_compliance:
        return out + [_with_action(answer(NOT_ALLOWED, "Your access does not include Compliance, so the advance-tax "
                                                       "obligations the payments cover were left open. Someone with "
                                                       "Compliance access can mark them filed there."))]
    for inst, decision, record in closable:
        what = _what(inst.cumulative_required_percent, inst.due_date, financial_year)
        closed = mark_filed_and_answer(
            record, what=what, operation="advance_tax_closes_obligation.mark_filed", firm_id=firm_id, client_id=client_id,
            compliance_type=COMPLIANCE_TYPE, filed_date=decision.filed_on.isoformat(), arn=decision.reference, actor=actor)
        if closed.get("closed"):
            # Said, not only done: a closed obligation cannot be corrected afterwards, so the person is told what was
            # recorded and can check it against the challan.
            closed = {**closed, "filed_on": decision.filed_on.isoformat(), "reference": decision.reference,
                      "message": f"{closed['message']} Recorded as paid on {decision.filed_on.isoformat()}"
                                 + (f", challan {decision.reference}" if decision.reference else "")
                                 + ", the day the payments reached the instalment: check it against the challan."}
        out.append(_with_action({**closed, "instalment": inst.installment_number, "due_date": inst.due_date.isoformat()}))

    if presumptive:
        # The three dates a general assessee would have paid on, which this one need not (§211(1) proviso).
        not_required = [obligations[d.isoformat()] for n, d in installment_schedule(financial_year)
                        if n != _PRESUMPTIVE_INSTALMENT and d.isoformat() in obligations
                        and obligations[d.isoformat()].get("status") not in ("Filed", "Completed")]
        if not_required:
            out.append(_with_action(answer(
                NOT_CLOSED,
                f"This client's register holds only the 15 March instalment (a §44AD or §44ADA assessee pays the whole "
                f"amount by then, §211(1) proviso), so the {len(not_required)} earlier advance-tax obligation(s) of "
                f"FY {financial_year} on the compliance calendar are not required of them. They were left as they are. "
                f"{FROM_COMPLIANCE}")))
    return out


def _with_action(a: dict[str, Any]) -> dict[str, Any]:
    """`needs_action`: whether somebody has something to do about it (an obligation left open, or the caller not allowed to close
    it). The screen draws the answer from this and does not read the state words itself."""
    return {**a, "needs_action": a.get("state") in (NOT_CLOSED, NOT_ALLOWED)}
