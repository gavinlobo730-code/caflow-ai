"""
What period a GST return covers — and it is NOT always a calendar month
(GST-11, remaining half).

WHAT WAS WRONG

    `services/gst_return_service._period_bounds` read a period as 'MMYYYY',
    raised on anything else, and returned the first and last day of ONE
    calendar month. Both from-books builders opened on it, so the return
    engine could not express a QUARTER at all.

    Rule 61A with the proviso to CGST s.39(1) — Notifications 82, 84 and
    85/2020-Central Tax, in force 01-01-2021 — let a registered person whose
    aggregate turnover in the preceding financial year was up to Rs 5 crore OPT
    to furnish GSTR-1 and GSTR-3B QUARTERLY while paying tax monthly (QRMP).
    That is most of a small Indian practice's book. For every one of those
    clients the DUE DATES were already right — `services/compliance_engine`
    has resolved the 13th and the 22nd/24th, PMT-06 and IFF since the QRMP
    half of this finding closed — and the return they were due could not be
    computed: a CA was quoted the quarterly date and then had to add three
    monthly GSTR-3Bs by hand.

WHY THIS IS A MODULE AND NOT A PARAMETER

    A period is now TWO facts — which months, and under which key it is
    stored — and five callers need both. Spreading the derivation would put
    the quarter arithmetic in each of them, and "which months are in this
    quarter" already exists twice in this codebase (`core.ist_clock
    .fy_quarters` and `services.compliance_obligation_service.fy_quarters`).
    A third is what this file exists to prevent: the quarter here is READ OFF
    `core.ist_clock.fy_quarters` and nothing in this module restates April.

    It reads nothing and writes nothing. Which frequency a registration is on
    is `domain/gst/registrations.Registration.filing_frequency`, resolved from
    the database by `services/client_gst_registration_service`; this module is
    told.

THE KEY IS THE QUARTER'S FIRST MONTH, AND THAT WAS ALREADY DECIDED

    `gstr1_returns.period` / `gstr3b_returns.period` are TEXT in MMYYYY and
    migration 390 keys both tables on `(client_id, period, gstin)`, so a
    quarter needs a period STRING and it must not collide with anything
    already stored. It is the quarter's FIRST month — 042025 for Apr-Jun 2025
    — because the half of this finding that already merged chose it:
    `routers/compliance.py::mark_compliance_filed` writes the `filings` row
    for a quarterly obligation with `period = f"{start[5:7]}{start[0:4]}"` off
    the calendar row's own period_start, and `_unsubmitted_workspace_return`
    then looks the prepared return up under that same key. Choosing the
    quarter END here would have left those two reading a key nothing writes.

    Nothing about the spelling changes: it is six digits, an existing reader
    that parses it still gets a real month, and a monthly client's key is
    exactly what it always was. What a quarter's key means is "the return for
    the quarter this month opens", and `resolve()` is the only thing that says
    so.

    ANY month of the quarter RESOLVES to it. A CA who types 052025 for a
    quarterly registration means Q1, unambiguously, and refusing would make
    the CA learn a convention rather than the software apply one. What comes
    back always names the canonical key, so a screen that saves what it
    computed cannot open a second row for one quarter.

WHAT IS REFUSED RATHER THAN GUESSED

    * The FORM's own `fp` / `ret_period` field for a quarterly return. The
      payload carries the canonical key, and whether the GSTN offline utility
      wants the quarter's first or last month there could not be checked —
      every `.gov.in` is refused at this environment's egress proxy. So the
      return NAMES it (`period_window.payload_caveat`) instead of a guess
      being filed. [S]
    * The INVOICE FURNISHING FACILITY (Rule 59(2)) — months 1 and 2 of a
      quarter, B2B only. It is a different return with a different due date
      and no storage of its own, and building it is not making a period mean
      three months. Named on every quarterly GSTR-1 so the next reader does
      not conclude the quarterly return covers it.
    * WHICH FREQUENCY A REGISTRATION WAS ON IN AN EARLIER YEAR. `filing_
      frequency` is the position TODAY, and a client who moved off QRMP in
      April would have last year's quarters recomputed as months. There is no
      history column, so the caller may say, and what was used is always
      reported.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from typing import Optional

from core.ist_clock import fy_quarters, ist_fy_label
from domain.gst.registrations import FILING_FREQUENCIES, MONTHLY, QUARTERLY

#: The windows below are the Act's and are written from the notifications
#: named in the header rather than read off them, because egress is refused
#: here. A test pins every one.
VERIFIED = False


@dataclass(frozen=True)
class ReturnPeriod:
    """One GSTR-1 or GSTR-3B period: what it covers and what it is keyed on."""

    #: The MMYYYY this return is stored under — the month itself, or the
    #: quarter's FIRST month. See the header for why the first.
    key: str
    frequency: str
    #: ISO YYYY-MM-DD, inclusive at both ends. Always month boundaries.
    start: str
    end: str
    #: Every MMYYYY the window contains, in order. One for a month, three for
    #: a quarter. This is what a period-KEYED read has to be asked for — a
    #: GSTR-2B is generated monthly for a quarterly filer too.
    months: tuple[str, ...]
    #: What a CA reads: 'June 2025' or 'Q1 Apr-Jun 2025 (quarter)'.
    label: str
    #: What the caller asked for, which differs from `key` whenever a month
    #: inside a quarter was named.
    requested: str

    @property
    def is_quarter(self) -> bool:
        return self.frequency == QUARTERLY

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "frequency": self.frequency,
            "start": self.start,
            "end": self.end,
            "months": list(self.months),
            "label": self.label,
            "requested": self.requested,
            "months_covered": len(self.months),
        }


def parse_month(period: str) -> tuple[int, int]:
    """'MMYYYY' → (month, year). The refusals the engine has always made."""
    value = str(period or "")
    if len(value) != 6 or not value.isdigit():
        raise ValueError("period must be MMYYYY")
    mm, yyyy = int(value[:2]), int(value[2:])
    if not 1 <= mm <= 12:
        raise ValueError("period month must be 01-12")
    return mm, yyyy


def month_bounds(period: str) -> tuple[str, str]:
    """'MMYYYY' → (first_iso, last_iso) for that calendar month."""
    mm, yyyy = parse_month(period)
    last = calendar.monthrange(yyyy, mm)[1]
    return f"{yyyy:04d}-{mm:02d}-01", f"{yyyy:04d}-{mm:02d}-{last:02d}"


def normalise_frequency(value: Optional[str]) -> str:
    """The filing frequency a period is to be read under.

    ABSENT MEANS MONTHLY, and that is not a guess dressed up as a default:
    `clients.gst_filing_frequency` is nullable (migration 001) and every
    caller predating QRMP awareness meant a month, so an unrecorded client
    keeps exactly the return they have always been given —
    `compliance_obligation_service.gst_profile_for` reads it the same way and
    says why.

    An unrecognised NON-EMPTY value is REFUSED. Both columns CHECK to the two
    values, so a third one means the caller invented it, and coercing it to
    monthly would build a one-month return for somebody who asked for
    something else and say nothing about it.
    """
    text = str(value or "").strip().lower()
    if not text:
        return MONTHLY
    if text not in FILING_FREQUENCIES:
        raise ValueError(
            f"{value!r} is not a GST filing frequency. A registration is on "
            f"{' or '.join(FILING_FREQUENCIES)} (Rule 61A) and nothing else.")
    return text


def _months_in_window(start_iso: str, end_iso: str) -> tuple[str, ...]:
    """Every MMYYYY between two MONTH-BOUNDARY dates, inclusive.

    Derived from the window rather than from the quarter, so a month and a
    quarter are enumerated by the same code and a one-month window comes back
    as one month with no special case.
    """
    y, m = int(start_iso[:4]), int(start_iso[5:7])
    last_y, last_m = int(end_iso[:4]), int(end_iso[5:7])
    out: list[str] = []
    while (y, m) <= (last_y, last_m):
        out.append(f"{m:02d}{y:04d}")
        m += 1
        if m == 13:
            m, y = 1, y + 1
    return tuple(out)


def _quarter_containing(mm: int, yyyy: int) -> tuple[str, str, str]:
    """(label, start_iso, end_iso) of the GST quarter this month falls in.

    READ OFF `core.ist_clock.fy_quarters`, which derives the four windows from
    `fy_bounds` — so a change to what a financial year IS cannot leave GST
    quarters describing the old one, and there is no second statement of
    Apr-Jun anywhere in this module. `ist_fy_label` supplies the year, which
    is the part that is easy to get wrong: January to March belong to the
    financial year that STARTED the previous April, so Q4 of FY 2025-26 is
    Jan-Mar 2026 and its months carry 2026.
    """
    first_of_month = f"{yyyy:04d}-{mm:02d}-01"
    for label, q_start, q_end in fy_quarters(ist_fy_label(first_of_month)):
        if q_start <= first_of_month <= q_end:
            return label, q_start, q_end
    # fy_quarters covers every month of the FY ist_fy_label just named, so
    # this is unreachable; raising beats returning a window nobody chose.
    raise ValueError(                                        # pragma: no cover
        f"{first_of_month} falls in no quarter of its own financial year.")


_QUARTER_MONTHS = {"Q1": "Apr-Jun", "Q2": "Jul-Sep", "Q3": "Oct-Dec", "Q4": "Jan-Mar"}


def resolve(period: str, frequency: Optional[str] = MONTHLY) -> ReturnPeriod:
    """The period a return covers, under one registration's filing frequency.

    `period` is any month of it. A monthly registration gets that month back
    unchanged — the same two dates `_period_bounds` has always returned — and
    a quarterly one gets the whole quarter, keyed on its first month.
    """
    freq = normalise_frequency(frequency)
    mm, yyyy = parse_month(period)
    requested = f"{mm:02d}{yyyy:04d}"

    if freq != QUARTERLY:
        start, end = month_bounds(requested)
        return ReturnPeriod(
            key=requested, frequency=MONTHLY, start=start, end=end,
            months=(requested,),
            label=f"{calendar.month_name[mm]} {yyyy}", requested=requested)

    quarter, start, end = _quarter_containing(mm, yyyy)
    months = _months_in_window(start, end)
    return ReturnPeriod(
        key=months[0], frequency=QUARTERLY, start=start, end=end,
        months=months,
        label=f"{quarter} {_QUARTER_MONTHS[quarter]} {end[:4]} (quarter)",
        requested=requested)


def bounds(period: str, frequency: Optional[str] = MONTHLY) -> tuple[str, str]:
    """(first_iso, last_iso) of the period — a month, or a QRMP quarter."""
    window = resolve(period, frequency)
    return window.start, window.end


#: What a quarterly return cannot say about its own `fp` / `ret_period`. [S] —
#: see the header. Emitted on the return rather than resolved, because filing
#: under a field the portal rejects costs the CA the return and saying so
#: costs them a glance.
PAYLOAD_PERIOD_CAVEAT = (
    "This return covers a QRMP quarter (Rule 61A) and its GSTN payload carries "
    "the quarter's FIRST month, {key}, in `fp` / `ret_period` — the same key it "
    "is stored and locked under. Whether the offline utility expects the "
    "quarter's first or last month there could not be verified from this "
    "environment; check it against the utility before uploading."
)

#: Rule 59(2). Named on every quarterly GSTR-1 rather than silently absent —
#: a CA reading a quarterly return has to know the two interim months are not
#: in it, because their customers' credit is what waits.
IFF_AVAILABLE = (
    "The Invoice Furnishing Facility is available for months 1 and 2 of this "
    "quarter (CGST Rule 59(2) — documents to a registered person only, between "
    "the 1st and the 13th of the following month). Nothing is owed if it is "
    "not used, but without it the recipient's input tax credit waits for this "
    "quarterly return. Prepare it per month from the IFF panel."
)

# `IFF_NOT_BUILT` stood here and said the facility "is not produced by this
# product", which was true from GST-11 until `domain/gst/iff.py` was written.
# RENAMED rather than aliased: a constant called NOT_BUILT holding a sentence
# that says it IS built is the kind of name a later reader trusts and a grep
# finds, and there is no caller outside this repository to keep it for.
