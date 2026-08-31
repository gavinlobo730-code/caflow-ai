"""
Payslip PDF generation.

A salary slip / payslip is the statutory wage statement issued to an employee.
Components shown follow the payroll computation in routers/payroll.py:
  - Earnings: Basic, HRA, DA, LTA, Medical, Special Allowance (IT Act §17 'salary')
  - Deductions: Provident Fund (EPF Act), ESI (ESI Act §2(9)),
    Professional Tax (IT Act §16(iii)), TDS on salary (IT Act §192)

All monetary values arrive as integer paise and are formatted for display only.
No floating point arithmetic is performed on amounts — rupees are derived as
paise // 100 and the fractional paise as paise % 100, per project paise rules.
"""
import io
import logging
from typing import Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

logger = logging.getLogger("caflow.services")

_MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


# Every deduction that reduced net pay has to appear on the payslip, or its own
# arithmetic does not add up for the person reading it: gross minus the
# deductions SHOWN would not equal the net shown, and an employee querying the
# difference is the last person who should have to work it out.
#
# Pure and separate from the PDF so it can be tested as arithmetic rather than
# by reading a rendered document.
DEDUCTION_DEFS: tuple[tuple[str, str], ...] = (
    ("Provident Fund (Employee)", "pf_employee_paise"),  # EPF Act
    ("ESI (Employee)", "esi_employee_paise"),            # ESI Act §2(9)
    ("Professional Tax", "pt_paise"),                    # IT Act §16(iii)
    ("TDS on Salary", "tds_paise"),                      # IT Act §192
    # Migration 300/301.
    ("Loan / Advance Recovery", "loan_recovery_paise"),
)

# Rows suppressed when nil, because a zero line on every payslip for everyone
# who has no advance is noise. The statutory four always show, so an employee
# can see that PF or TDS was considered and came to nothing.
_HIDE_WHEN_ZERO = {"loan_recovery_paise"}


def deduction_lines(slip: dict) -> tuple[list[list[str]], int]:
    """([["Deductions", "Amount (₹)"], [label, amount], ...], total_paise)."""
    rows = [["Deductions", "Amount (₹)"]]
    total = 0
    for label, key in DEDUCTION_DEFS:
        value = int(slip.get(key) or 0)
        if value == 0 and key in _HIDE_WHEN_ZERO:
            continue
        total += value
        rows.append([label, _paise_to_rupee_str(value)])
    return rows, total


def _paise_to_rupee_str(paise: int) -> str:
    """Format integer paise as a rupee string, e.g. 123456 -> '₹1,234.56'.

    Integer paise arithmetic only — never float (project rupee rule)."""
    paise = int(paise or 0)
    rupees = paise // 100
    fraction = paise % 100
    return f"₹{rupees:,}.{fraction:02d}"


def _pay_period(slip: dict, run: dict) -> tuple[str, int, int]:
    """Resolve the pay period as (label, month, year).

    payroll_runs.month is stored as 'YYYY-MM'. Falls back to slip fields
    (month/year) if a run record is unavailable."""
    month_str = (run or {}).get("month")
    if month_str and "-" in str(month_str):
        y, m = str(month_str).split("-")[:2]
        try:
            mi, yi = int(m), int(y)
            return f"{_MONTH_NAMES[mi]} {yi}", mi, yi
        except (ValueError, IndexError):
            pass
    mi = int(slip.get("month") or 0)
    yi = int(slip.get("year") or 0)
    label = f"{_MONTH_NAMES[mi]} {yi}" if 1 <= mi <= 12 and yi else (month_str or "")
    return label, mi, yi


def build_payslip_pdf(slip: dict, employee: dict, run: dict, firm: dict) -> bytes:
    """Render a salary slip PDF and return raw bytes.

    `slip` is a payroll_slips row; component paise columns are optional and only
    rendered when present (the base schema stores gross/PF/ESI/PT/TDS/net, while
    later migrations add basic/HRA/etc.)."""
    period_label, _m, _y = _pay_period(slip, run)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm,
        title=f"Payslip {period_label}",
    )
    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, textColor=colors.grey)
    bold = ParagraphStyle("bold", parent=styles["Normal"], fontName="Helvetica-Bold")

    story = []

    firm_name = firm.get("name") or firm.get("firm_name") or "Employer"
    story.append(Paragraph(firm_name, ParagraphStyle(
        "title", parent=styles["Title"], fontSize=16, spaceAfter=2)))
    story.append(Paragraph(f"Payslip for {period_label}", small))
    story.append(Spacer(1, 6 * mm))

    # ─── Employee details ───────────────────────────────────────────────────
    emp_lines = [f"<b>{employee.get('name', 'Employee')}</b>"]
    if employee.get("designation"):
        emp_lines.append(str(employee["designation"]))
    if employee.get("department"):
        emp_lines.append(f"Dept: {employee['department']}")
    if employee.get("pan"):
        emp_lines.append(f"PAN: {employee['pan']}")

    meta_lines = [f"<b>Pay Period:</b> {period_label}"]
    if slip.get("working_days") is not None:
        meta_lines.append(f"<b>Working Days:</b> {slip['working_days']}")
    if slip.get("days_present") is not None:
        meta_lines.append(f"<b>Days Present:</b> {slip['days_present']}")
    if slip.get("lop_days"):
        meta_lines.append(f"<b>LOP Days:</b> {slip['lop_days']}")

    header = Table(
        [[Paragraph("<br/>".join(emp_lines), styles["Normal"]),
          Paragraph("<br/>".join(meta_lines), styles["Normal"])]],
        colWidths=[100 * mm, 80 * mm],
    )
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
    ]))
    story.append(header)
    story.append(Spacer(1, 6 * mm))

    # ─── Earnings ───────────────────────────────────────────────────────────
    # IT Act §17: components constituting 'salary'. Only render lines present
    # on the slip; sum the gross from the stored gross_paise (authoritative).
    earning_defs = [
        ("Basic", "basic_paise"),
        ("HRA", "hra_paise"),
        ("Dearness Allowance", "da_paise"),
        ("LTA", "lta_paise"),
        ("Medical Allowance", "medical_paise"),
        ("Special Allowance", "special_allowance_paise"),
        ("Other Allowances", "other_allowances_paise"),
    ]
    gross_paise = int(slip.get("gross_paise") or 0)
    earning_rows = [["Earnings", "Amount (₹)"]]
    has_breakdown = any(slip.get(k) for _, k in earning_defs)
    if has_breakdown:
        for label, key in earning_defs:
            if slip.get(key):
                earning_rows.append([label, _paise_to_rupee_str(slip[key])])
    else:
        # No component breakdown stored — show consolidated gross earnings.
        earning_rows.append(["Gross Earnings", _paise_to_rupee_str(gross_paise)])
    earning_rows.append(["Gross Salary", _paise_to_rupee_str(gross_paise)])

    earnings = Table(earning_rows, colWidths=[120 * mm, 60 * mm])
    earnings.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(earnings)
    story.append(Spacer(1, 4 * mm))

    # ─── Deductions ─────────────────────────────────────────────────────────
    deduction_rows, total_deductions = deduction_lines(slip)
    deduction_rows.append(["Total Deductions", _paise_to_rupee_str(total_deductions)])

    deductions = Table(deduction_rows, colWidths=[120 * mm, 60 * mm])
    deductions.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(deductions)
    story.append(Spacer(1, 6 * mm))

    # ─── Net Pay ────────────────────────────────────────────────────────────
    # Net is the authoritative stored value (gross - deductions), integer paise.
    net_paise = int(slip.get("net_paise") or (gross_paise - total_deductions))
    net = Table(
        [["Net Pay", _paise_to_rupee_str(net_paise)]],
        colWidths=[120 * mm, 60 * mm],
    )
    net.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#065f46")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(net)
    story.append(Spacer(1, 12 * mm))

    story.append(Paragraph(
        "This is a computer-generated payslip and does not require a signature. "
        "Amounts are stated in Indian Rupees. For queries, contact your employer.",
        small,
    ))

    doc.build(story)
    return buf.getvalue()


def get_payslip_pdf(slip_id: str, firm_id: Optional[str]) -> tuple[bytes, str]:
    """
    Load a payroll slip with its employee, run and firm records and render the PDF.

    Enforces firm-scoping: the slip's run must belong to `firm_id`.

    Returns:
        (pdf_bytes, suggested_filename)
    """
    from core.supabase_client import get_supabase
    db = get_supabase()

    slip_res = (
        db.table("payroll_slips")
        .select("*, payroll_employees(name, pan, designation, department), payroll_runs(month, firm_id, client_id)")
        .eq("id", slip_id)
        .maybe_single()
        .execute()
    )
    slip = slip_res.data
    if not slip:
        raise ValueError("Salary slip not found")

    employee = slip.pop("payroll_employees", None) or {}
    run = slip.pop("payroll_runs", None) or {}

    # Firm-scope enforcement — slip belongs to a run owned by the caller's firm.
    # Fail CLOSED (deny unless ownership is explicitly proven), matching the
    # rest of this codebase's tenant-check convention (e.g. finalize_run's
    # "F1/F4 fix" comment) -- the previous `firm_id and run.get("firm_id") and
    # ...` short-circuited to "allow" if either side was ever falsy, instead
    # of denying.
    if not firm_id or run.get("firm_id") != firm_id:
        raise PermissionError("Access denied")

    firm = _load_firm(run.get("firm_id") or firm_id)

    pdf = build_payslip_pdf(slip, employee, run, firm)
    _label, m, y = _pay_period(slip, run)
    period = f"{y}-{m:02d}" if m and y else "payslip"
    filename = f"payslip-{period}.pdf"
    return pdf, filename


def _load_firm(firm_id: Optional[str]) -> dict:
    if not firm_id:
        return {}
    try:
        from core.supabase_client import get_supabase
        result = get_supabase().table("firms").select("*").eq("id", firm_id).maybe_single().execute()
        return result.data or {}
    except Exception as e:
        logger.warning(f"Could not load firm {firm_id}: {e}")
        return {}
