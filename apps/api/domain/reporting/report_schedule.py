"""What a scheduled report is: which report, which period, which due date, and who may be mailed it (PRE-B-002 part 1).

THE SCREEN PROMISED A MAIL THAT NOTHING SENT, AND THE ROW COULD NOT HAVE SAID WHAT IT MEANT. `scheduled_reports`
(migration 031) holds a report type, a frequency, a day of the month and a list of addresses, and nothing in
`apps/api` has ever read it. Before anything can read it, four questions have to have ONE answer that the
service, the router and the screen all ask rather than each working out for itself. This module is those answers.
It reads no table, calls no clock, sends nothing and writes nothing.

THE OWNER'S DECISIONS OF 9 OCTOBER 2026 THIS MODULE HOLDS
    1. A SCHEDULE PREPARES AND A PERSON SENDS. D27 (docs/plan/THE-PLAN.md) is literally about a client's CUSTOMERS;
       the owner applied its reasoning to this mail too, because a figure the sweep produced and nobody read is not
       one to mail outward. `HOW_IT_WORKS` is the sentence the screen shows in place of "emailed automatically".
       Nothing here mails; the due date is the day a report is PREPARED.
    2. THERE IS NO "ALL CLIENTS". A report is one client's books, the row holds one list of addresses, and an
       ageing report names that client's customers or suppliers: applied across clients it would send one client's
       books to addresses chosen for another. A row with no client is refused with its reason (`no_client`).
    3. RECIPIENTS ARE THE FIRM'S ACTIVE STAFF, THE CLIENT'S ACTIVE PORTAL CONTACTS AND THE CLIENT'S OWN EMAIL, and
       nothing else. A free-text address would let a typo, or a customer's address, receive a client's ledger.

THE CONTRACT THE NEXT CHUNKS (the table, the service, the router, the send door, the screen) IMPORT
    kinds        `REPORT_KINDS`, `kind_of`, `kind_problem`, `export_params`: the stored `report_type` vocabulary, which
                 of those the server can make a document of, and the query parameters `report_export_service`
                 takes for a period.
    periods      `plan_for(row, today=, recorded=)` is the ONE question the sweep and the list screen both ask of a
                 stored row: is it blocked (and why), which slot is to be prepared now, which older slots are to be
                 written down as missed, and what is next. `slots_owed`, `next_slot` and `plan` are the pure parts
                 under it, taking `since` (the IST day the schedule began to count): a caller whose row has a later
                 activation stamp than its creation passes that one, and so does the one that adopts rows older
                 than the run table, whose earlier slots were never tracked and must not be written down as missed.
    recipients   `resolve_recipients(requested, staff=, contacts=, client_email=)` at create AND again at send; it
                 SEPARATES the people who may be mailed from the problems and leaves it to the door whether one problem
                 refuses the whole send. `allowed_recipients(...)` is the picker's list.
    the client   `client_problem(client)`: the practice's own record, a deleted or an archived client is never run.
    the file     `size_problem(n_bytes)`.
    sentences    every `Problem.sentence` and the `*_sentence` functions are the words the screen renders. The screen
                 holds no vocabulary of its own.

A DUE DATE IS COMPUTED FROM AN INJECTED IST DATE. Every function takes `today` (and `since`) as a `date`; none reads
the clock, which `tests/test_a_schedule_says_which_period_it_covers_and_when_it_is_due.py` asserts from the source.
Between 00:00 and 05:30 IST the UTC date is yesterday (CLAUDE.md, "A stored instant and ist_today() are not
comparable"), so the one instant this module is handed, a row's `created_at`, is converted to its IST DATE by
`created_on` and never compared as a UTC date.

THE FOUR RULES OF A PERIOD
    * DAY 1 TO 28 ONLY. 29, 30 and 31 do not occur in every month, so a report due "on the 31st" would be due on a
      different day each month or not at all in some. NULL, 0 or 31 is "not schedulable" and is never defaulted to
      the 5th that the column's default would suggest: the column has no CHECK, so a direct insert can hold any of
      them, and the safe reading of a day nobody can interpret is "nothing is due".
    * A RUN IS FOR THE PERIOD THAT HAS ENDED (what the document then shows of that period is the next paragraph's
      question, and differs by report). Monthly: the previous calendar month, due on that day each month.
      Quarterly: the financial-year quarter that ended in the previous month, so due in July, October, January and
      April; yearly: the financial year that ended on 31 March, due in April. The quarters and the year are READ OFF
      `core.ist_clock` (`fy_quarters`, `fy_bounds`), as are the months they are due in, so a change to what a
      financial year is cannot leave this module describing the old one. A report whose period had not ended would
      be a draft of a figure that was still moving.
    * THE FIRST SLOT IS THE FIRST DUE DATE STRICTLY AFTER THE DAY THE SCHEDULE WAS CREATED. A monthly day-5 schedule
      made on the 20th does not owe the 5th that had already passed; one made on the 5th itself does not owe that
      day's either (the first sweep after creation would otherwise prepare a report nobody asked for).
    * ONLY THE LATEST OWED SLOT IS PREPARED. After downtime (the free-tier instance sleeps) a month of slots can be
      owed at once; preparing every one would put seven reports in front of a CA, six of them stale. The newest is
      prepared and the older unrecorded ones are returned as `missed`, so the service writes them down and the gap
      SHOWS on the screen instead of being silence.

WHAT EACH REPORT CAN HONESTLY SAY ABOUT ITS PERIOD (`ReportKind.shape`). The schedule's period is a fact about WHEN a
report falls due; whether the document is that period's is a fact about the report, and the three are not alike.
    * PERIOD  the cash flow statement. It reads the ledger between two dates, so it covers the stretch.
    * AS_AT   the trial balance. It reads `account_period_balances` up to a date, so the document is the position at
              that date: an entry dated after it is not in it. (An entry posted LATER with an earlier date is in it,
              which is what a position is.)
    * LIVE    the two ageing reports (`customer_statement_service.ar_aging`, `vendor_statement_service.ap_aging`).
              They read each document's CURRENT `outstanding_paise` (the generated column of migration 278, filtered
              `> 0` in the query) and use the date they are handed ONLY to age those documents. Nothing in
              `client_sales_invoices` or `purchase_bills` records what a document owed on an earlier day (a
              settlement overwrites `paid_paise`), so the set open on a past date cannot be rebuilt from them: an
              invoice raised on 20 September and paid on 2 October is missing from a September ageing prepared on the
              5th, and one raised on 3 October is in it. A schedule therefore hands them NO date. They run as of the
              IST day they are prepared, the document's own header reads 'As at <that day>', and the period names the
              run (the run table is unique on it) without being what the report shows. Describing them as the
              position at the period's end, as the first draft of this module did, was a claim the report cannot back,
              and in one batch it would have sat beside a trial balance that DOES reconstruct the position and so
              would not tie to it. The `as_of` box on the ageing screens and the export route has the same property
              (a past date re-ages today's open documents, it does not look back); that is existing behaviour, left
              alone here and not claimed otherwise. A report becomes AS_AT only by reconstructing the position:
              `tests/test_a_scheduled_report_is_one_the_server_can_make_and_goes_only_to_people_it_may.py` drives each
              real report over a book where something happened after the period end and fails a kind that claims more
              than its report does.

A STORED ROW IS READ IN THE SAFE DIRECTION. `scheduled_reports.is_active` is nullable (migration 031), and NULL reads
as OFF here, the opposite of how `users.is_active` is read for access: the cost of mail not sent is a click, the cost
of mail sent from a row nobody can interpret is a report in the wrong inbox.

NOT HERE, AND WHY. No row is written and no status vocabulary is defined (the run table's statuses are the
service's); the rule says WHICH slot, not what to record about it. Nothing here decides who may press Send or whether
a firm's mail is switched on (`practice_mail_service.mail_enabled` is the one switch and the send door asks it).
`NOT_SCHEDULABLE_EXPORTS` names the one export a schedule cannot hold (the ledger: it needs an account).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Iterator, Mapping, Optional, Sequence

from core.ist_clock import IST, fy_bounds, fy_quarters, ist_fy_label
from core.validators import validate_email

#: The sentence the screen shows where it used to say reports are "emailed automatically". Nothing is mailed by
#: itself (the owner's decision of 9 October 2026, on D27's reasoning).
HOW_IT_WORKS = (
    "A schedule prepares its report on the due date. Nothing is mailed by itself: a person looks at the prepared "
    "report and presses Send."
)

# ── which report ─────────────────────────────────────────────────────────────────────────────────────────────────

#: The report covers a stretch of time (start to end): the cash flow statement.
PERIOD = "period"
#: The report is a position AS AT the end of the period, rebuilt from what was recorded up to that date: the trial
#: balance. Only a report that reconstructs the position may claim this.
AS_AT = "as_at"
#: The report is what is open on the day it is PREPARED, and the period does not change what it shows: the two ageing
#: reports (see "what each report can honestly say about its period" above). A schedule hands them no date.
LIVE = "live"

#: What a scheduled report is attached as. Every report the server can make is offered as a PDF
#: (`report_export_service.REPORTS`), which a test holds; a spreadsheet is a second file to keep in step.
ATTACHMENT_FORMAT = "pdf"


@dataclass(frozen=True)
class ReportKind:
    """One value `scheduled_reports.report_type` may hold.

    `export_id` is the report's name in `report_export_service.REPORTS`, or None where the server makes no
    document of it. `available` is whether a schedule may be CREATED for it; `reason` says why not, in the words the
    screen shows, and is None exactly when it is available.
    """

    id: str
    label: str
    export_id: Optional[str]
    shape: str
    available: bool
    reason: Optional[str] = None

    def as_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "shape": self.shape, "available": self.available,
                "reason": self.reason}


def _no_document(what: str) -> str:
    return f"The server makes no {what} document, so there is nothing to prepare or mail."


#: The stored vocabulary, in the order a picker shows it. The LAST five ids are the ones the table's CHECK allows
#: today (a row written by the old screen can hold any of them); the four available kinds in front are new values,
#: which the run-table migration adds to that CHECK. A report becomes schedulable by giving it an `export_id` and
#: flipping `available`; nothing else here changes.
REPORT_KINDS: tuple[ReportKind, ...] = (
    ReportKind("trial_balance", "Trial Balance", "trial-balance", AS_AT, True),
    ReportKind("cash_flow", "Cash Flow Statement", "cash-flow", PERIOD, True),
    ReportKind("ar_ageing", "Receivables Ageing", "ar-ageing", LIVE, True),
    ReportKind("ap_ageing", "Payables Ageing", "ap-ageing", LIVE, True),
    ReportKind("pl", "Profit and Loss Statement", None, PERIOD, False,
               _no_document("Profit and Loss")),
    ReportKind("balance_sheet", "Balance Sheet", None, AS_AT, False,
               _no_document("Balance Sheet")),
    ReportKind("gst_summary", "GST Summary", None, PERIOD, False,
               _no_document("GST summary")),
    ReportKind("tds_summary", "TDS Summary", None, PERIOD, False,
               _no_document("TDS summary")),
    ReportKind("payroll_summary", "Payroll Summary", None, PERIOD, False,
               _no_document("payroll summary")),
)

#: Exports the server makes that a schedule cannot hold, with the reason. Together with the `export_id` of each kind
#: this is every name in `report_export_service.REPORTS`, in both directions, which a test holds.
NOT_SCHEDULABLE_EXPORTS: dict[str, str] = {
    "ledger": "A ledger is one account's book and a schedule names no account, so a ledger cannot be scheduled.",
}

#: For each export, the query parameter `report_export_service` reads the period's dates from. Keyed by the export's
#: own name because the parameter names are that service's vocabulary; `tests/` runs every entry through the
#: service's own `_document` and checks the dates arrive where the report reads them. The two ageing reports take NO
#: date: the service reads its own IST day, which is the day the report is prepared and the day its open set is read
#: (see LIVE). An entry here is a claim that the report looks back to that date, and they do not.
_EXPORT_DATE_PARAMS: dict[str, dict[str, str]] = {
    "trial-balance": {"as_of_date": "end"},
    "cash-flow": {"start_date": "start", "end_date": "end"},
    "ar-ageing": {},
    "ap-ageing": {},
}


@dataclass(frozen=True)
class Problem:
    """Why a thing cannot be done, with a stable `code` for a program and a `sentence` for a person. `subject` is
    the address a recipient problem is about."""

    code: str
    sentence: str
    subject: Optional[str] = None

    def as_dict(self) -> dict:
        return {"code": self.code, "sentence": self.sentence, "subject": self.subject}


def kind_of(report_type: object) -> Optional[ReportKind]:
    if not isinstance(report_type, str):
        return None
    return next((k for k in REPORT_KINDS if k.id == report_type), None)


def kind_problem(report_type: object) -> Optional[Problem]:
    """Why a schedule cannot be run for this report type, or None. An unknown id is its own answer: a value written
    around the API is not a report the server was ever asked to make."""
    kind = kind_of(report_type)
    if kind is None:
        if isinstance(report_type, str) and report_type in NOT_SCHEDULABLE_EXPORTS:
            return Problem("report_not_schedulable", NOT_SCHEDULABLE_EXPORTS[report_type])
        return Problem("unknown_report", f"{_shown(report_type)} is not a report a schedule can run.")
    if not kind.available:
        return Problem("report_unavailable", f"{kind.label} cannot be scheduled. {kind.reason}")
    return None


def export_params(report_type: str, period: "Period") -> dict[str, str]:
    """The parameters `report_export_service.export_report` takes for this report over this period, as ISO dates.

    The trial balance is a position and takes the period's END; the cash flow takes both ends; the two ageing
    reports take NO date and so come back as `{}` (they are what is open on the day they are prepared, and a date would
    only re-age today's documents as if they had been read on another day). A kind the server cannot make is refused
    (ValueError with its reason), never given a guessed parameter.
    """
    problem = kind_problem(report_type)
    if problem is not None:
        raise ValueError(problem.sentence)
    kind = kind_of(report_type)
    ends = {"start": period.start, "end": period.end}
    return {name: ends[which].isoformat() for name, which in _EXPORT_DATE_PARAMS[kind.export_id].items()}


# ── how often, and on which day ──────────────────────────────────────────────────────────────────────────────────

MONTHLY, QUARTERLY, YEARLY = "monthly", "quarterly", "yearly"
FREQUENCIES: tuple[str, ...] = (MONTHLY, QUARTERLY, YEARLY)

MIN_DAY, MAX_DAY = 1, 28


def frequency_problem(frequency: object) -> Optional[Problem]:
    if frequency in FREQUENCIES:
        return None
    return Problem("unknown_frequency",
                   f"{_shown(frequency)} is not a frequency a schedule can have: monthly, quarterly or yearly.")


def day_problem(day: object) -> Optional[Problem]:
    """A day of the month a schedule may use, or why not. Never defaulted: a missing day is a missing day."""
    if isinstance(day, bool) or not isinstance(day, int):
        return Problem("day_not_schedulable",
                       "No day of the month is recorded for this schedule, and none is assumed, so nothing is due.")
    if not MIN_DAY <= day <= MAX_DAY:
        return Problem(
            "day_not_schedulable",
            f"Day {day} cannot be used. A schedule takes a day from {MIN_DAY} to {MAX_DAY}, because the 29th, 30th "
            "and 31st do not occur in every month and a report has to fall due in all of them.")
    return None


# ── the periods and the slots ────────────────────────────────────────────────────────────────────────────────────

_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December")


@dataclass(frozen=True)
class Period:
    """The stretch of books a report covers. `key` identifies it for ever ('2026-09', '2026-27-Q2', '2026-27'):
    it is what the run table is made unique on, and it names the PERIOD, not the day a report was prepared. The
    run table is unique per schedule and key, and a schedule has one frequency; the monthly and yearly shapes could
    be confused only for a financial year starting 2000 to 2011 or 2100 to 2111 (FY 2000-01 is also 'January
    2000'), which no run here can have."""

    key: str
    label: str
    start: date
    end: date

    def as_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "start": self.start.isoformat(), "end": self.end.isoformat()}


@dataclass(frozen=True)
class Slot:
    """One occasion a report falls due: the day, and the period it covers."""

    due_on: date
    period: Period

    def as_dict(self) -> dict:
        return {"due_on": self.due_on.isoformat(), "period": self.period.as_dict()}


@dataclass(frozen=True)
class Plan:
    """What to do about one schedule today.

    `prepare` is the slot to prepare now (the latest owed slot, if it has no run recorded); `missed` the older owed
    slots with no run recorded, oldest first, to be written down as missed; `upcoming` the next slot to fall due;
    `problem` why the schedule is blocked, in which case the other three are empty.
    """

    prepare: Optional[Slot] = None
    missed: tuple[Slot, ...] = ()
    upcoming: Optional[Slot] = None
    problem: Optional[Problem] = None


def _fy_label(start_year: int) -> str:
    return f"{start_year}-{str(start_year + 1)[2:]}"


def _month_period(year: int, month: int) -> Period:
    last = (date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)) - timedelta(days=1)
    return Period(f"{year:04d}-{month:02d}", f"{_MONTHS[month - 1]} {year}", date(year, month, 1), last)


def _year_period(label: str) -> Period:
    start, end = fy_bounds(label)
    return Period(label, f"FY {label}", date.fromisoformat(start), date.fromisoformat(end))


def _quarter_periods(label: str) -> list[Period]:
    return [Period(f"{label}-{q}", f"{q} of FY {label}", date.fromisoformat(s), date.fromisoformat(e))
            for q, s, e in fy_quarters(label)]


def _stream(frequency: str, anchor: date) -> Iterator[Period]:
    """Periods of this frequency in order, beginning with the one that contains `anchor`. Endless: the caller
    stops, and `fy_bounds` refuses a year outside 1900 to 2999."""
    if frequency == MONTHLY:
        year, month = anchor.year, anchor.month
        while True:
            yield _month_period(year, month)
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    fy_start = int(ist_fy_label(anchor)[:4])
    while True:
        label = _fy_label(fy_start)
        if frequency == YEARLY:
            yield _year_period(label)
        else:
            yield from _quarter_periods(label)
        fy_start += 1


def _due_on(period: Period, day: int) -> date:
    """The day of the month AFTER the period ends. A day of 1 to 28 exists in every month."""
    end = period.end
    year, month = (end.year + 1, 1) if end.month == 12 else (end.year, end.month + 1)
    return date(year, month, day)


def _checked(frequency: object, day: object) -> None:
    for problem in (frequency_problem(frequency), day_problem(day)):
        if problem is not None:
            raise ValueError(problem.sentence)


def _slots_after(frequency: str, day: int, floor: date) -> Iterator[Slot]:
    """Every slot due strictly after `floor`, soonest first.

    The stream begins with the period holding the last day of the month before `floor`'s: a period that ended in an
    earlier month fell due before `floor` whatever the day is, and one ending in that month falls due in `floor`'s
    own month, on the day, which may still be ahead of `floor`.
    """
    anchor = floor.replace(day=1) - timedelta(days=1)
    for period in _stream(frequency, anchor):
        due = _due_on(period, day)
        if due > floor:
            yield Slot(due, period)


def slots_owed(frequency: str, day: int, *, since: date, today: date) -> list[Slot]:
    """The slots due after `since` and on or before `today`, oldest first. A slot due today is owed today."""
    _checked(frequency, day)
    out: list[Slot] = []
    for slot in _slots_after(frequency, day, since):
        if slot.due_on > today:
            break
        out.append(slot)
    return out


def next_slot(frequency: str, day: int, *, since: date, today: date) -> Slot:
    """The next slot to fall due: the first after both `since` and `today`."""
    _checked(frequency, day)
    return next(_slots_after(frequency, day, max(since, today)))


def plan(frequency: str, day: int, *, since: date, today: date, recorded: Iterable[str] = ()) -> Plan:
    """What the sweep does with a schedule that is not blocked.

    `since` is the IST day the schedule began to count (its creation, or a later activation); `recorded` is the set
    of period keys that already have a run of ANY kind the caller does not want prepared again. Only the LATEST
    owed slot is prepared, and only if it has no run: if it has, the older unrecorded ones are missed all the same,
    because preparing a stale slot after a newer one was handled would mail a CA last quarter's figures as if they
    were new.
    """
    seen = frozenset(recorded)
    owed = slots_owed(frequency, day, since=since, today=today)
    latest = owed[-1] if owed else None
    return Plan(
        prepare=latest if latest is not None and latest.period.key not in seen else None,
        missed=tuple(s for s in owed[:-1] if s.period.key not in seen),
        upcoming=next_slot(frequency, day, since=since, today=today),
    )


def created_on(stamp: object) -> Optional[date]:
    """The IST calendar day of a stored timestamp, or None where it cannot be read.

    A `timestamptz` comes back from PostgREST in UTC, and from 18:30 to 24:00 UTC the UTC date is the day BEFORE the
    Indian one, so the stamp is converted and the date taken after. A naive value is read as UTC (the server's own
    convention); a bare date is that day. `core.ist_clock._as_ist_date` takes `d[:10]` of a string and would give the
    UTC date of a timestamp.
    """
    if isinstance(stamp, datetime):
        moment = stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
        return moment.astimezone(IST).date()
    if isinstance(stamp, date):
        return stamp
    if not isinstance(stamp, str) or not stamp.strip():
        return None
    text = stamp.strip()
    try:
        if len(text) == 10:
            return date.fromisoformat(text)
        return created_on(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        return None


# ── a stored row ─────────────────────────────────────────────────────────────────────────────────────────────────

def schedule_problems(row: Mapping, *, check_active: bool = True) -> list[Problem]:
    """Everything that stops this row being run, soonest to fix first. `check_active=False` is the CREATE door's
    question (a new row is active, and the switch is not a field the CA is filling in)."""
    out: list[Problem] = []
    if check_active and row.get("is_active") is not True:
        out.append(Problem(
            "inactive",
            "This schedule is turned off." if row.get("is_active") is False
            else "This schedule has no on or off state recorded, so it is treated as off."))
    if not row.get("client_id"):
        out.append(Problem(
            "no_client",
            "This schedule names no client. A report is one client's books, and a schedule for all clients cannot be "
            "prepared or mailed: it would send one client's figures to addresses chosen for another. Choose a "
            "client."))
    for problem in (kind_problem(row.get("report_type")), frequency_problem(row.get("frequency")),
                    day_problem(row.get("day_of_month"))):
        if problem is not None:
            out.append(problem)
    return out


def schedule_problem(row: Mapping, *, check_active: bool = True) -> Optional[Problem]:
    problems = schedule_problems(row, check_active=check_active)
    return problems[0] if problems else None


def plan_for(row: Mapping, *, today: date, recorded: Iterable[str] = ()) -> Plan:
    """The ONE question the sweep and the list screen ask of a stored `scheduled_reports` row.

    Reads `report_type`, `frequency`, `day_of_month`, `client_id`, `is_active` and `created_at`. A blocked row gets a
    Plan with a `problem` and nothing to prepare, so a caller cannot prepare a row it forgot to check.
    """
    problem = schedule_problem(row)
    if problem is not None:
        return Plan(problem=problem)
    since = created_on(row.get("created_at"))
    if since is None:
        return Plan(problem=Problem(
            "created_unknown",
            "This schedule has no creation date recorded, so what has fallen due since cannot be told and "
            "nothing is prepared."))
    return plan(row["frequency"], row["day_of_month"], since=since, today=today, recorded=recorded)


# ── the words ────────────────────────────────────────────────────────────────────────────────────────────────────

def _shown(value: object) -> str:
    """A value quoted back to a person: short, on one line, never an unbounded echo."""
    text = " ".join(str(value).split()) if value is not None else ""
    return repr(text[:57] + "..." if len(text) > 60 else text) if text else "(blank)"


def _dmy(d: date) -> str:
    return f"{d.day} {_MONTHS[d.month - 1][:3]} {d.year}"


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _due_months(frequency: str) -> list[str]:
    """The months a frequency falls due in, read off one financial year's own periods."""
    ends = ([date.fromisoformat(fy_bounds("2026-27")[1])] if frequency == YEARLY
            else [date.fromisoformat(e) for _, _, e in fy_quarters("2026-27")])
    return [_MONTHS[e.month % 12] for e in ends]


def _join(names: Sequence[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def schedule_sentence(frequency: str, day: int) -> str:
    """'Every month on the 5th. Covers the previous calendar month.' The screen shows this beside the form."""
    _checked(frequency, day)
    on = f"on the {_ordinal(day)}"
    if frequency == MONTHLY:
        return f"Every month {on}. Covers the previous calendar month."
    months = _join(_due_months(frequency))
    if frequency == QUARTERLY:
        return (f"Every quarter {on} of {months}. Covers the financial-year quarter that has just ended.")
    end = date.fromisoformat(fy_bounds("2026-27")[1])
    return (f"Every year {on} of {months}. Covers the financial year that ended on {end.day} "
            f"{_MONTHS[end.month - 1]}.")


def slot_sentence(report_type: str, slot: Slot, *, prepared_on: Optional[date] = None) -> str:
    """'Due 5 Oct 2026. Covers 1 Sep 2026 to 30 Sep 2026 (September 2026).' The period in a report's own terms: a
    cash flow covers a stretch, a trial balance shows the position at the period's end, and an ageing lists what is
    open on the day it is prepared and does not look back to the period at all.

    `prepared_on` is the IST day a prepared run was made, where the caller has one; the sentence for an ageing then
    names it. Without it the sentence says 'the day it is prepared', which is true of a run not yet made.
    """
    kind = kind_of(report_type)
    due = f"Due {_dmy(slot.due_on)}."
    p = slot.period
    if kind is not None and kind.shape == AS_AT:
        return f"{due} Shows the position as at {_dmy(p.end)}, the end of {p.label}."
    if kind is not None and kind.shape == LIVE:
        # A bare IST date only: a datetime is an instant, and its calendar day depends on the zone it is read in.
        named = isinstance(prepared_on, date) and not isinstance(prepared_on, datetime)
        day = f"on {_dmy(prepared_on)}, the day it was prepared," if named else "on the day it is prepared,"
        return (f"{due} Lists the documents open {day} aged from that day. It does not look back to "
                f"{_dmy(p.end)}, the end of {p.label}; that only says which due date this report is for.")
    return f"{due} Covers {_dmy(p.start)} to {_dmy(p.end)} ({p.label})."


def missed_sentence(slot: Slot) -> str:
    """The note written on a slot nobody prepared, so the gap shows instead of being silence."""
    return (f"Not prepared: the report due on {_dmy(slot.due_on)} for {slot.period.label} passed before this "
            "schedule was looked at (the server was asleep, or the schedule was turned off), and a later report was "
            "already due.")


# ── the client ───────────────────────────────────────────────────────────────────────────────────────────────────

#: The client columns `client_problem` reads. A read that names fewer makes the check a silent no-op, so the service
#: writes all of them in its own `select`.
CLIENT_FIELDS: tuple[str, ...] = ("is_internal", "is_deleted", "is_archived", "deleted_at", "archived_at")


def client_problem(client: Optional[Mapping]) -> Optional[Problem]:
    """Why a client's books are not run on a schedule, or None.

    The three flags are NOT NULL in the schema, so a value that is not exactly False means the row was read without
    them, and "not established" is refused rather than read as "ordinary": the cost of a report not prepared is a
    click, and the practice's own record is Partner-only (guardrail G1).
    """
    if not client:
        return Problem("client_missing", "The client is not in this firm's records.")
    if client.get("is_internal") is True:
        return Problem("client_internal", "That is the practice's own record, not a client's, and its books are not "
                                          "run on a schedule.")
    if client.get("is_deleted") is True or client.get("deleted_at"):
        return Problem("client_deleted", "The client has been deleted.")
    if client.get("is_archived") is True or client.get("archived_at"):
        return Problem("client_archived", "The client is archived, so its reports are not prepared.")
    if any(client.get(f) is not False for f in ("is_internal", "is_deleted", "is_archived")):
        return Problem("client_unread", "The client's record was read without its status, so the schedule is not "
                                        "run. Nothing is assumed.")
    return None


# ── the file ─────────────────────────────────────────────────────────────────────────────────────────────────────

#: 10 MB of file. The portal's own cap for a shared report is the same figure (`shared_report.MAX_BYTES`), and a mail
#: carries the file as base64, a third larger. The provider's own limit was recalled and not verified here.
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024


def size_problem(n_bytes: int) -> Optional[Problem]:
    if int(n_bytes) <= MAX_ATTACHMENT_BYTES:
        return None
    return Problem(
        "too_large",
        f"The report is {int(n_bytes) / (1024 * 1024):.1f} MB and a mailed report is limited to "
        f"{MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB. Nothing was sent.")


# ── who may receive it ───────────────────────────────────────────────────────────────────────────────────────────

#: A schedule takes at most this many recipients. The report is mailed to each in turn while the person who pressed
#: Send waits, and the browser gives up on a request at 45 seconds.
MAX_RECIPIENTS = 5

#: The columns the rule reads, for the service to write out in its own selects.
STAFF_FIELDS: tuple[str, ...] = ("id", "full_name", "email", "is_active", "status", "deleted_at")
CONTACT_FIELDS: tuple[str, ...] = ("name", "email", "status")

STAFF, PORTAL_CONTACT, CLIENT_EMAIL = "staff", "portal_contact", "client_email"

#: Where an address came from, in the order that decides which source speaks for an address held by more than one.
#: Staff first: a staff member's own mail preferences are asked of a mail to them, and a person who is both staff
#: and the client's contact keeps their opt-out.
_SOURCES = (STAFF, PORTAL_CONTACT, CLIENT_EMAIL)

#: The outbox's and the log's own vocabulary for the kind of recipient (`email_outbox_service.RECIPIENT_KINDS`).
_KIND_OF_SOURCE = {STAFF: "staff", PORTAL_CONTACT: "client_contact", CLIENT_EMAIL: "client_contact"}

_SEPARATORS = re.compile(r"""[,;<>"'()\[\]\\]""")
_MAX_ADDRESS = 254


@dataclass(frozen=True)
class Recipient:
    address: str
    source: str
    user_id: Optional[str] = None
    name: Optional[str] = None

    @property
    def kind(self) -> str:
        return _KIND_OF_SOURCE[self.source]

    def as_dict(self) -> dict:
        return {"address": self.address, "source": self.source, "kind": self.kind, "name": self.name}


@dataclass(frozen=True)
class Resolution:
    """The requested addresses, separated into the people who may be mailed and the reasons the others may not."""

    accepted: tuple[Recipient, ...]
    problems: tuple[Problem, ...]

    @property
    def ok(self) -> bool:
        return bool(self.accepted) and not self.problems


def normalise_address(value: object) -> Optional[str]:
    """Trimmed and lower-cased, or None for something that is not text. `Ca@Firm.in` and `ca@firm.in` are one inbox
    (`practice_notices.dedupe_key` folds them the same way)."""
    return value.strip().lower() if isinstance(value, str) else None


def address_problem(address: Optional[str]) -> Optional[str]:
    """What is wrong with the shape of an address. `core.validators.validate_email` is the one pattern; the
    separators it lets through (a comma or a semicolon makes one string several addresses, angle brackets a display
    name) are refused here, because a recipient is an address and never a header."""
    if not address or len(address) > _MAX_ADDRESS or validate_email(address) or _SEPARATORS.search(address):
        return "is not an email address"
    return None


def _flag_active(row: Mapping, source: str) -> bool:
    if source == STAFF:
        # A pending invitee (status 'invited') is not active staff; a suspended member has is_active False (the
        # suspend route writes only that). All three keys must be PRESENT: a narrow select would otherwise read
        # as "nobody is deleted".
        return (row.get("is_active") is True and row.get("status") == "active"
                and "deleted_at" in row and not row["deleted_at"])
    return row.get("status") == "active"


def _people(staff: Iterable[Mapping], contacts: Iterable[Mapping], client_email: object):
    """(active, inactive): address -> Recipient for who may be mailed, address -> source for who exists but may
    not. Precedence follows `_SOURCES`."""
    active: dict[str, Recipient] = {}
    inactive: dict[str, str] = {}

    def add(row: Mapping, source: str, name_key: str) -> None:
        address = normalise_address(row.get("email"))
        if address is None or address_problem(address):
            return
        if _flag_active(row, source):
            active.setdefault(address, Recipient(
                address, source, str(row["id"]) if source == STAFF and row.get("id") else None,
                row.get(name_key) or None))
        else:
            inactive.setdefault(address, source)

    for row in staff:
        add(row, STAFF, "full_name")
    for row in contacts:
        add(row, PORTAL_CONTACT, "name")
    own = normalise_address(client_email)
    if own and not address_problem(own):
        active.setdefault(own, Recipient(own, CLIENT_EMAIL))
    return active, inactive


def allowed_recipients(*, staff: Iterable[Mapping], contacts: Iterable[Mapping],
                       client_email: object = None) -> tuple[Recipient, ...]:
    """Everyone a report for this client MAY be mailed to, for the form's picker: the firm's active staff, the
    client's active portal contacts and the client's own email, one entry per address."""
    active, _ = _people(staff, contacts, client_email)
    return tuple(active[a] for a in sorted(active))


def _judge(address: str, active: Mapping[str, Recipient], inactive: Mapping[str, str]):
    """(Recipient, None) or (None, Problem) for one normalised address."""
    bad = address_problem(address)
    if bad:
        return None, Problem("bad_address", f"{_shown(address)} {bad}.", address)
    if address in active:
        return active[address], None
    if inactive.get(address) == STAFF:
        return None, Problem("staff_inactive", f"{address} belongs to a member of this firm who is not active, so "
                                              "the report is not sent there.", address)
    if inactive.get(address) == PORTAL_CONTACT:
        return None, Problem("contact_inactive", f"{address} is a portal contact of this client whose access is not "
                                                "active, so the report is not sent there.", address)
    return None, Problem(
        "not_allowed",
        f"{address} is not someone this report may go to. A scheduled report goes only to the firm's active staff, "
        "this client's active portal contacts and the client's own email address.", address)


def resolve_recipients(requested: Optional[Iterable[object]], *, staff: Iterable[Mapping],
                       contacts: Iterable[Mapping], client_email: object = None) -> Resolution:
    """Judge a schedule's recipient list against who may receive it.

    Asked at create AND again at send, because the list is a stored array nothing validates (RLS cannot read inside
    it, and the browser wrote it straight into the table) and the people behind it change: a contact leaves, a member
    is suspended. Blank entries are ignored and duplicates fold; a requested address that is not allowed, is not an
    address, or belongs to someone who is no longer active is a problem naming that address. Whether one problem
    refuses the whole send is the door's choice; this separates the two lists and says why.
    """
    active, inactive = _people(staff, contacts, client_email)
    accepted: list[Recipient] = []
    problems: list[Problem] = []
    seen: set[str] = set()
    for raw in (requested or ()):
        address = normalise_address(raw)
        if address is None:
            problems.append(Problem("bad_address", f"{_shown(raw)} is not an email address."))
            continue
        if not address or address in seen:
            continue
        seen.add(address)
        who, problem = _judge(address, active, inactive)
        if who is not None:
            accepted.append(who)
        else:
            problems.append(problem)
    if not seen and not problems:
        problems.append(Problem(
            "no_recipient",
            "No recipient is chosen. A schedule needs at least one person from the firm's active staff, the "
            "client's active portal contacts or the client's own email."))
    if len(accepted) > MAX_RECIPIENTS:
        problems.append(Problem(
            "too_many_recipients",
            f"{len(accepted)} recipients are chosen and a schedule takes at most {MAX_RECIPIENTS}: the report is "
            "mailed to each in turn while the person who pressed Send waits."))
    return Resolution(tuple(accepted), tuple(problems))
