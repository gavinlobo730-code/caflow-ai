"""
Compliance due date calculation engine.
All rules per CGST Act 2017 and Income Tax Act 1961.
"""
from datetime import date, timedelta
from calendar import monthrange
from typing import Optional
from models.compliance import ComplianceType, ComplianceStatus, CompliancePriority


def last_day_of_month(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def nth_of_month(year: int, month: int, day: int) -> date:
    """Return date for the Nth day of given month, clamped to month end."""
    last = monthrange(year, month)[1]
    return date(year, month, min(day, last))


def next_month(year: int, month: int) -> tuple[int, int]:
    if month == 12:
        return year + 1, 1
    return year, month + 1


# ── QRMP: monthly filing is not the only way, and was the only one modelled ──
#
# Rule 61A with §39(1) and its proviso. From 01-01-2021 (Notifications 82, 84
# and 85/2020-Central Tax, 10-11-2020) a registered person whose aggregate
# turnover in the PRECEDING financial year was up to Rs 5 crore may opt to
# furnish GSTR-1 and GSTR-3B QUARTERLY while paying tax MONTHLY. Above Rs 5
# crore, monthly is compulsory.
#
# QRMP is not simply "the same return, three times less often". For a quarterly
# filer:
#
#   GSTR-1    13th of the month following the quarter
#   GSTR-3B   22nd or 24th of the month following the quarter, BY STATE
#   PMT-06    25th of the following month, for months 1 and 2 of the quarter,
#             because tax is still paid monthly. Month 3 is paid with the return.
#   IFF       optional, months 1 and 2, B2B only, up to Rs 50 lakh a month, by
#             the 13th — so the RECIPIENT's credit does not wait a quarter.
#
# What this module used to do was return the 11th and the 20th for everybody.
# clients.gst_filing_frequency has existed since migration 001 and is settable
# on the client form, but nothing read it, so a quarterly client was quoted
# monthly dates and never told about PMT-06 at all. Late filing is Rs 50 a day
# under §47, so a wrong due date is not cosmetic.
#
# GST quarters follow the financial year: Apr-Jun, Jul-Sep, Oct-Dec, Jan-Mar.

MONTHLY = "monthly"
QUARTERLY = "quarterly"

# The two due-date groups for a quarterly GSTR-3B. The split is the same one
# the staggered monthly due dates used (Notification 29/2020-Central Tax) and
# lands cleanly on the state code: 01-21 and 38 are the northern/eastern group,
# 22-37 the southern/western one.
#
#   22nd  Chhattisgarh(22) MP(23) Gujarat(24) Daman & Diu(25) DNHDD(26)
#         Maharashtra(27) Andhra(28, old) Karnataka(29) Goa(30) Lakshadweep(31)
#         Kerala(32) Tamil Nadu(33) Puducherry(34) Andaman & Nicobar(35)
#         Telangana(36) Andhra Pradesh(37)
#   24th  J&K(01) HP(02) Punjab(03) Chandigarh(04) Uttarakhand(05) Haryana(06)
#         Delhi(07) Rajasthan(08) UP(09) Bihar(10) Sikkim(11) Arunachal(12)
#         Nagaland(13) Manipur(14) Mizoram(15) Tripura(16) Meghalaya(17)
#         Assam(18) West Bengal(19) Jharkhand(20) Odisha(21) Ladakh(38)
GST_STATE_CATEGORY_X = frozenset(f"{n:02d}" for n in range(22, 38))   # 22nd
GST_STATE_CATEGORY_Y = frozenset(f"{n:02d}" for n in range(1, 22)) | {"38"}  # 24th


def gst_state_category(state_code: Optional[str]) -> Optional[str]:
    """'X' (22nd), 'Y' (24th), or None when the state is unknown.

    None is a real answer and callers should surface it: the due date for a
    quarterly GSTR-3B cannot be stated without knowing the state, and a client
    with no state_code is common enough (it is nullable) that guessing quietly
    is the wrong behaviour.
    """
    code = (state_code or "").strip()[:2].zfill(2) if (state_code or "").strip() else ""
    if code in GST_STATE_CATEGORY_X:
        return "X"
    if code in GST_STATE_CATEGORY_Y:
        return "Y"
    return None


def gst_quarter_end_month(period_month: int) -> int:
    """Last month of the GST quarter containing `period_month` (Apr-Jun etc)."""
    # Apr(4)->Jun(6), Jul(7)->Sep(9), Oct(10)->Dec(12), Jan(1)->Mar(3)
    return ((period_month - 4) % 12 // 3) * 3 + 6 if period_month >= 4 else 3


def gst_quarter_bounds(period_year: int, period_month: int) -> tuple[int, int]:
    """(year, month) of the quarter END for the period given.

    Jan-Mar is the fourth quarter of the financial year that STARTED the
    previous April, but it still ends in March of its own calendar year — so
    the year only rolls forward for Oct-Dec, which ends in December.
    """
    end_month = gst_quarter_end_month(period_month)
    return period_year, end_month


def gst_period_month_in_quarter(period_month: int) -> int:
    """1, 2 or 3 — where this month sits in its GST quarter.

    PMT-06 is due for months 1 and 2 only; month 3's tax is paid with the
    quarterly return itself.
    """
    return ((period_month - 4) % 3) + 1


# CGST Act §37 with Rule 59 — GSTR-1.
#   monthly    11th of the following month
#   quarterly  13th of the month following the quarter (QRMP)
def gstr1_due_date(period_year: int, period_month: int,
                   frequency: str = MONTHLY) -> date:
    if frequency == QUARTERLY:
        qy, qm = gst_quarter_bounds(period_year, period_month)
        ny, nm = next_month(qy, qm)
        return nth_of_month(ny, nm, 13)
    ny, nm = next_month(period_year, period_month)
    return nth_of_month(ny, nm, 11)


# CGST Act §39 with Rule 61 — GSTR-3B.
#   monthly    20th of the following month
#   quarterly  22nd (category X) or 24th (category Y) of the month following
#              the quarter, decided by the state of registration
def gstr3b_due_date(period_year: int, period_month: int,
                    frequency: str = MONTHLY,
                    state_code: Optional[str] = None) -> date:
    if frequency != QUARTERLY:
        ny, nm = next_month(period_year, period_month)
        return nth_of_month(ny, nm, 20)

    qy, qm = gst_quarter_bounds(period_year, period_month)
    ny, nm = next_month(qy, qm)
    # An unknown state gets the EARLIER of the two dates. Being early costs
    # nothing; being late is Rs 50 a day under §47, so a guess must never be
    # the generous one. gst_state_category() returns None for the same input,
    # which is how a caller knows to say the date is assumed rather than known.
    return nth_of_month(ny, nm, 24 if gst_state_category(state_code) == "Y" else 22)


def pmt06_due_date(period_year: int, period_month: int) -> Optional[date]:
    """Rule 61A — monthly tax payment for a QRMP filer, 25th of the following
    month. None for the third month of a quarter, whose tax is paid with the
    quarterly GSTR-3B rather than by a separate challan."""
    if gst_period_month_in_quarter(period_month) == 3:
        return None
    ny, nm = next_month(period_year, period_month)
    return nth_of_month(ny, nm, 25)


def iff_due_date(period_year: int, period_month: int) -> Optional[date]:
    """Invoice Furnishing Facility — Rule 59(2), optional, months 1 and 2 of a
    quarter, B2B only, 13th of the following month. None for month 3, which is
    covered by the quarterly GSTR-1 itself.

    Optional in the strict sense: nothing is due if it is not used. It is
    offered because the recipient's ITC otherwise waits for the quarter.
    """
    if gst_period_month_in_quarter(period_month) == 3:
        return None
    ny, nm = next_month(period_year, period_month)
    return nth_of_month(ny, nm, 13)


# CGST Act, Section 44 — GSTR-9 annual return due 31st December
def gstr9_due_date(financial_year_end: int) -> date:
    # financial_year_end is the calendar year in which Mar 31 falls
    return date(financial_year_end, 12, 31)


# CGST Act §37(3) proviso and §39(9) proviso (rectifying GSTR-1 / GSTR-3B), and
# §16(4) (taking input tax credit) — all three windows close on the SAME date,
# amended to 30 November by the Finance Act 2022 (from the old "September
# return" formulation).
#
# The statute reads: 30 November following the end of the financial year, OR
# the furnishing of the relevant annual return, WHICHEVER IS EARLIER. Filing
# GSTR-9 early therefore shuts the window early — see
# correction_window_closes(), which is the function to use. This one is only the
# statutory outer limit.
def november_30_cutoff(financial_year_end: int) -> date:
    """30 November following the FY that ended on 31 March of `financial_year_end`.

    FY 2025-26 ends 31 Mar 2026, so its cutoff is 30 Nov 2026.
    """
    return date(financial_year_end, 11, 30)


def correction_window_closes(
    financial_year_end: int, annual_return_filed_on: Optional[date] = None
) -> date:
    """The date after which a period can no longer be corrected at all.

    THE "WHICHEVER IS EARLIER" IS NOT A DETAIL. §37(3), §39(9) and §16(4) each
    close on 30 November OR on the date the annual return is furnished,
    whichever comes first. A client who files GSTR-9 in August has lost the
    ability to amend that year from August — three months before the date
    everyone quotes. Treating 30 November as the answer would tell a CA a
    correction is still available when it is not.
    """
    statutory = november_30_cutoff(financial_year_end)
    if annual_return_filed_on and annual_return_filed_on < statutory:
        return annual_return_filed_on
    return statutory


# IT Act, Section 139 — ITR due date (non-audit: 31 July; audit: 31 Oct)
def itr_due_date(financial_year_end: int, is_audit: bool = False) -> date:
    if is_audit:
        return date(financial_year_end, 10, 31)
    return date(financial_year_end, 7, 31)


# IT Act, Section 200(3) — TDS return due 31st of month following quarter end
TDS_QUARTER_END_MONTHS = {
    "Q1": (6, 31),   # Apr-Jun → 31 Jul
    "Q2": (9, 31),   # Jul-Sep → 31 Oct
    "Q3": (12, 31),  # Oct-Dec → 31 Jan (next year)
    "Q4": (3, 31),   # Jan-Mar → 31 May
}

def tds_return_due_date(quarter: str, financial_year_end: int) -> date:
    """
    quarter: 'Q1', 'Q2', 'Q3', 'Q4'
    financial_year_end: calendar year when Mar 31 falls (e.g. 2025 for FY 2024-25)
    """
    end_month, due_day = TDS_QUARTER_END_MONTHS[quarter]
    if quarter == "Q3":
        return date(financial_year_end, 1, 31)
    if quarter == "Q4":
        return date(financial_year_end, 5, 31)
    return date(financial_year_end - 1, end_month + 1 if end_month < 12 else 1, due_day)


# IT Act, Section 211 — Advance tax due dates
ADVANCE_TAX_SCHEDULE = [
    (6, 15, 15),   # 15% by 15 Jun
    (9, 15, 45),   # 45% by 15 Sep
    (12, 15, 75),  # 75% by 15 Dec
    (3, 15, 100),  # 100% by 15 Mar
]

# Companies Act 2013 — annual ROC filing offsets from the AGM date. R3.1:
# these three offsets used to be hardcoded independently in both
# services/compliance_obligation_service.py::_roc_obligations (AOC-4/MGT-7
# only) and routers/mca_workspace.py's /calendar endpoint (all three) — now
# a single source both call.
MCA_AGM_OFFSET_DAYS = {
    "ADT-1": 15,   # §139 — Auditor Appointment
    "AOC-4": 30,   # §137 — Financial Statements
    "MGT-7": 60,   # §92  — Annual Return
}


def mca_due_date(agm_date: date, form_type: str) -> date:
    return agm_date + timedelta(days=MCA_AGM_OFFSET_DAYS[form_type])


def advance_tax_due_dates(financial_year_end: int) -> list[dict]:
    fy_start = financial_year_end - 1
    results = []
    for month, day, cumulative_pct in ADVANCE_TAX_SCHEDULE:
        year = fy_start if month >= 4 else financial_year_end
        results.append({
            "due_date": date(year, month, day).isoformat(),
            "cumulative_percentage": cumulative_pct,
            "installment": f"{cumulative_pct}% by {date(year, month, day).strftime('%d %b %Y')}",
        })
    return results


def days_remaining(due_date: date) -> int:
    return (due_date - date.today()).days


def compute_priority(days_left: int) -> CompliancePriority:
    if days_left < 0:
        return CompliancePriority.CRITICAL
    if days_left <= 3:
        return CompliancePriority.CRITICAL
    if days_left <= 7:
        return CompliancePriority.HIGH
    if days_left <= 15:
        return CompliancePriority.MEDIUM
    return CompliancePriority.LOW


def compute_status(days_left: int, current_status: str) -> ComplianceStatus:
    if current_status == "filed":
        return ComplianceStatus.FILED
    if days_left < 0:
        return ComplianceStatus.OVERDUE
    return ComplianceStatus.PENDING


def enrich_compliance_task(task: dict) -> dict:
    """Add computed days_remaining, priority, and derived status to a compliance task dict."""
    due = date.fromisoformat(task["due_date"])
    d = days_remaining(due)
    task["days_remaining"] = d
    task["priority"] = compute_priority(d).value
    task["status"] = compute_status(d, task.get("status", "pending")).value
    return task
