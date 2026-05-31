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


# CGST Act, Section 37 — GSTR-1 due on 11th of following month
def gstr1_due_date(period_year: int, period_month: int) -> date:
    ny, nm = next_month(period_year, period_month)
    return nth_of_month(ny, nm, 11)


# CGST Act, Section 39 — GSTR-3B due on 20th of following month
def gstr3b_due_date(period_year: int, period_month: int) -> date:
    ny, nm = next_month(period_year, period_month)
    return nth_of_month(ny, nm, 20)


# CGST Act, Section 44 — GSTR-9 annual return due 31st December
def gstr9_due_date(financial_year_end: int) -> date:
    # financial_year_end is the calendar year in which Mar 31 falls
    return date(financial_year_end, 12, 31)


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
