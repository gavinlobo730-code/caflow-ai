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

from domain.reporting.amount_words import amount_in_words

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
    """([["Deductions", "Amount (Rs.)"], [label, amount], ...], total_paise)."""
    rows = [["Deductions", "Amount (Rs.)"]]
    total = 0
    for label, key in DEDUCTION_DEFS:
        value = int(slip.get(key) or 0)
        if value == 0 and key in _HIDE_WHEN_ZERO:
            continue
        total += value
        rows.append([label, _paise_to_rupee_str(value)])
    return rows, total


# ── The employer's own contributions ──────────────────────────────────────────
#
# These are NOT deducted from the employee and must never appear in the
# deductions table: putting them there would make gross minus deductions stop
# equalling net, which is the one arithmetic an employee actually checks. They
# appear as their own block because the employer's contribution is what makes
# the CTC conversation possible — an employee told their cost to company is
# ₹6,00,000 and shown a payslip that accounts for ₹5,40,000 has no way to find
# the rest.
#
# pf_employer_paise is the WHOLE 12% and the EPS diversion is INSIDE it
# (migration 295's own COMMENT ON COLUMN says so). Listing the 12% and the
# EPS line side by side would state the employer paid 20.33%. So the split is
# shown as two sub-lines that sum to the 12%, and the total below adds
# pf_employer_paise once.
_EMPLOYER_SPLIT: tuple[tuple[str, str], ...] = (
    # EPF Act s.6 / Code on Social Security 2020 s.16 — employer's 12%, less
    # the pension diversion.
    ("Provident Fund — EPF (Employer)", "pf_employer_epf_paise"),
    # EPS 1995 para 3 — 8.33% of the wage, capped at ₹1,250, diverted OUT of
    # the 12% above and not additional to it.
    ("Pension Fund — EPS (Employer)", "pf_employer_eps_paise"),
)
_EMPLOYER_OTHER: tuple[tuple[str, str], ...] = (
    ("ESI (Employer)", "esi_employer_paise"),          # ESI Act §39, 3.25%
    ("EDLI", "edli_paise"),                            # EDLI 1976, 0.5%
    ("PF Administrative Charges", "pf_admin_paise"),   # 0.5%
)


def employer_contribution_lines(slip: dict) -> tuple[list[list[str]], int]:
    """([["Employer Contributions", "Amount (Rs.)"], [label, amount], ...], total).

    Pure, and separate from the PDF so the no-double-count invariant can be
    tested as arithmetic rather than by reading a rendered document.

    Returns ([], 0) when the employer contributed nothing — a block of five
    zeroes on a contractor's payslip is noise, and unlike the statutory
    deductions there is no "it was considered and came to nothing" to show.
    """
    pf_total = int(slip.get("pf_employer_paise") or 0)
    epf = int(slip.get("pf_employer_epf_paise") or 0)
    eps = int(slip.get("pf_employer_eps_paise") or 0)

    rows: list[list[str]] = []
    if pf_total:
        # The split is only shown when it actually reconciles to the 12%.
        # Migration 295 backfilled these two columns to zero for every slip
        # written before it, and 295's own note says splitting them
        # retrospectively would be inventing a figure — so an old slip shows
        # the total it really holds instead of a split that does not add up.
        if epf + eps == pf_total:
            for label, key in _EMPLOYER_SPLIT:
                rows.append([label, _paise_to_rupee_str(int(slip.get(key) or 0))])
        else:
            rows.append(["Provident Fund (Employer)", _paise_to_rupee_str(pf_total)])

    total = pf_total
    for label, key in _EMPLOYER_OTHER:
        value = int(slip.get(key) or 0)
        if value:
            rows.append([label, _paise_to_rupee_str(value)])
        total += value

    if not rows:
        return [], 0
    return [["Employer Contributions", "Amount (Rs.)"]] + rows, total


# ── Year to date ──────────────────────────────────────────────────────────────

def fy_months_upto(month: str) -> list[str]:
    """The 'YYYY-MM' labels from April of that financial year up to `month`.

    A payslip's year-to-date is the FINANCIAL year to date, not the calendar
    year: it is the figure that reconciles to Form 16 and to the §192
    withholding, both of which run April to March. A January slip's YTD
    therefore starts the previous April, and an April slip's YTD is itself.

    Returns [] for a label this cannot parse, which makes the YTD block absent
    rather than wrong.
    """
    text = str(month or "").strip()
    if len(text) < 7 or text[4] != "-":
        return []
    try:
        year, mon = int(text[:4]), int(text[5:7])
    except ValueError:
        return []
    if not 1 <= mon <= 12:
        return []
    fy_start_year = year if mon >= 4 else year - 1
    out, y, m = [], fy_start_year, 4
    while True:
        out.append(f"{y}-{m:02d}")
        if y == year and m == mon:
            return out
        m += 1
        if m == 13:
            m, y = 1, y + 1
        if len(out) > 12:                       # a month outside its own FY
            return []


def ytd_totals(slips) -> dict:
    """Year-to-date gross, deductions and net over the slips handed in.

    The caller decides WHICH slips (see fy_months_upto); this only adds up.
    Deductions are summed from DEDUCTION_DEFS rather than from a stored total,
    so a deduction added to the payslip is in the YTD the same day it is on
    the slip.
    """
    gross = net = deductions = 0
    tds = 0
    months = 0
    for slip in slips or []:
        months += 1
        gross += int(slip.get("gross_paise") or 0)
        net += int(slip.get("net_paise") or 0)
        tds += int(slip.get("tds_paise") or 0)
        for _label, key in DEDUCTION_DEFS:
            deductions += int(slip.get(key) or 0)
    return {"months": months, "gross_paise": gross,
            "deductions_paise": deductions, "tds_paise": tds, "net_paise": net}


def mask_account(number) -> str:
    """A bank account with only its last four digits shown.

    The payslip is emailed, printed and handed to landlords. The account number
    is on it so the employee can confirm WHICH account was credited, which the
    last four digits answer; the whole number answers a different question
    nobody asked. A number of four digits or fewer is shown whole — masking it
    to nothing would defeat the only purpose it has.
    """
    digits = "".join(ch for ch in str(number or "") if ch.isalnum())
    if not digits:
        return ""
    if len(digits) <= 4:
        return digits
    return "X" * (len(digits) - 4) + digits[-4:]


def _paise_to_rupee_str(paise: int) -> str:
    """Format integer paise as a rupee string, e.g. 123456 -> 'Rs.1,234.56'.

    Integer paise arithmetic only — never float (project rupee rule)."""
    paise = int(paise or 0)
    rupees = paise // 100
    fraction = paise % 100
    return f"Rs.{rupees:,}.{fraction:02d}"


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


def build_payslip_pdf(slip: dict, employee: dict, run: dict, employer: dict,
                      ytd: Optional[dict] = None) -> bytes:
    """Render a salary slip PDF and return raw bytes.

    `slip` is a payroll_slips row; component paise columns are optional and only
    rendered when present (the base schema stores gross/PF/ESI/PT/TDS/net, while
    later migrations add basic/HRA/etc.).

    `employer` IS THE CLIENT, NOT THE FIRM. The fourth argument used to be the
    CA practice's `firms` row and the payslip was headed with the practice's
    name — so an employee of Acme Manufacturing received a payslip that said
    their employer was the accountancy firm keeping Acme's books. It is the
    same defect the customer statement had (see
    statement_pdf_service.load_account_holder), in the document with the widest
    readership in the product: every employee of every client sees one every
    month, and the person named on it is who they would write to about their
    pay, name to their bank, and produce as proof of employment.

    §192 makes the person "responsible for paying" salary the deductor, and
    that is the client. The firm's name belongs nowhere on this page.
    """
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

    # The employer's own registered name, in the order the ledger prefers it —
    # the same order the customer statement uses, so one client is named the
    # same way on every document that leaves the platform.
    employer_name = (employer.get("legal_name")
                     or employer.get("trade_name")
                     or employer.get("client_name")
                     # `name` is the shape a firms row uses. Kept only so a
                     # caller that still passes one renders something rather
                     # than a blank letterhead; load_employer refuses first.
                     or employer.get("name")
                     or "Employer")
    story.append(Paragraph(employer_name, ParagraphStyle(
        "title", parent=styles["Title"], fontSize=16, spaceAfter=2)))
    # The employer's own registrations. An employee querying their PF with the
    # EPFO, or an ESIC claim, is asked for the ESTABLISHMENT the contribution
    # was remitted under — a number they have no other way to learn, and one
    # this platform already holds in client_statutory_identity (migration 325).
    # A registration that is not on file is simply absent; a blank label would
    # read as "your employer is not registered".
    reg_bits = []
    if employer.get("epf_establishment_code"):
        reg_bits.append(f"EPF Estt.: {employer['epf_establishment_code']}")
    if employer.get("esic_employer_code"):
        reg_bits.append(f"ESIC Code: {employer['esic_employer_code']}")
    if employer.get("tan"):
        # IT Act §203A — quoted on the TDS certificate this slip's §192
        # withholding ends up on, so it is the number that ties them together.
        reg_bits.append(f"TAN: {employer['tan']}")
    if employer.get("pan"):
        reg_bits.append(f"PAN: {employer['pan']}")
    if reg_bits:
        story.append(Paragraph(" &nbsp;|&nbsp; ".join(reg_bits), small))
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
    # The employee's own statutory identifiers. The UAN is what the employee
    # signs in to the EPFO member portal with; without it on the slip they have
    # to ask their employer for it, which is the query this document exists to
    # prevent.
    if employee.get("uan"):
        emp_lines.append(f"UAN: {employee['uan']}")
    if employee.get("esi_number"):
        emp_lines.append(f"ESIC No.: {employee['esi_number']}")
    if employee.get("bank_account_no"):
        # Masked — see mask_account. Enough to confirm which account was
        # credited, not enough to be a payment instruction if the slip is
        # forwarded.
        acct = f"Bank A/c: {mask_account(employee['bank_account_no'])}"
        if employee.get("bank_ifsc"):
            acct += f" ({employee['bank_ifsc']})"
        emp_lines.append(acct)

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
        # One-time and variable earnings (migration 331). LAST, because it is
        # the line that is not a monthly rate — every row above it repeats next
        # month and this one does not. Without it the earnings block sums to
        # LESS than the gross printed directly under it, with no line to point
        # at, which is exactly the reconciliation migration 222 existed to fix.
        ("Bonus / Incentive / Arrears", "one_time_earnings_paise"),
    ]
    gross_paise = int(slip.get("gross_paise") or 0)
    earning_rows = [["Earnings", "Amount (Rs.)"]]
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
    story.append(Spacer(1, 4 * mm))

    # ─── Employer contributions ─────────────────────────────────────────────
    # Deliberately AFTER the deductions table and outside it: none of this was
    # taken from the employee, and the net below is gross minus the deductions
    # above and nothing else.
    employer_rows, employer_total = employer_contribution_lines(slip)
    if employer_rows:
        employer_rows.append(["Total Employer Contribution",
                              _paise_to_rupee_str(employer_total)])
        contributions = Table(employer_rows, colWidths=[120 * mm, 60 * mm])
        contributions.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(contributions)
        story.append(Paragraph(
            "Employer contributions are paid by the employer in addition to "
            "the gross salary above. They are not deducted from your pay.",
            small))
        story.append(Spacer(1, 4 * mm))
    story.append(Spacer(1, 2 * mm))

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
    # In words, under the figure. This is the line a lender reads and the line
    # an employee disputes; a figure alone can be misread by a decimal place
    # and a photocopy can lose a comma.
    story.append(Paragraph(f"<b>In words:</b> {amount_in_words(net_paise)}",
                           styles["Normal"]))
    story.append(Spacer(1, 6 * mm))

    # ─── Year to date ───────────────────────────────────────────────────────
    # The FINANCIAL year to date — April to this month — because that is the
    # period Form 16 and the §192 withholding are computed over, so these are
    # the figures that must agree with the certificate at the end of the year.
    # Absent rather than zero when the caller did not supply it: a YTD of zero
    # in month nine is a statement, and a wrong one.
    if ytd and int(ytd.get("months") or 0):
        ytd_rows = [
            [f"Year to Date (April - {period_label}, {ytd['months']} month(s))",
             "Amount (Rs.)"],
            ["Gross Earnings", _paise_to_rupee_str(ytd.get("gross_paise") or 0)],
            ["Total Deductions", _paise_to_rupee_str(ytd.get("deductions_paise") or 0)],
            ["of which TDS (§192)", _paise_to_rupee_str(ytd.get("tds_paise") or 0)],
            ["Net Paid", _paise_to_rupee_str(ytd.get("net_paise") or 0)],
        ]
        ytd_table = Table(ytd_rows, colWidths=[120 * mm, 60 * mm])
        ytd_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(ytd_table)
        story.append(Spacer(1, 6 * mm))

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        "This is a computer-generated payslip and does not require a signature. "
        "Amounts are stated in Indian Rupees. For queries, contact your employer.",
        small,
    ))

    doc.build(story)
    return buf.getvalue()


def get_payslip_pdf(slip_id: str, firm_id: Optional[str]) -> tuple[bytes, str]:
    """
    Load a payroll slip with its employee, run and EMPLOYER records and render
    the PDF. The employer is the client the run belongs to, not the CA firm.

    Enforces firm-scoping: the slip's run must belong to `firm_id`.

    Returns:
        (pdf_bytes, suggested_filename)
    """
    from core.supabase_client import get_supabase
    db = get_supabase()

    slip_res = (
        db.table("payroll_slips")
        .select("*, payroll_employees(name, pan, designation, department, "
                "uan, esi_number, bank_account_no, bank_ifsc), "
                "payroll_runs(month, firm_id, client_id)")
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

    employer = load_employer(run.get("firm_id") or firm_id, run.get("client_id"))
    ytd = load_ytd(run.get("firm_id") or firm_id, run.get("client_id"),
                   run.get("month"), [slip.get("employee_id")]).get(
                       slip.get("employee_id"))

    pdf = build_payslip_pdf(slip, employee, run, employer, ytd=ytd)
    _label, m, y = _pay_period(slip, run)
    period = f"{y}-{m:02d}" if m and y else "payslip"
    filename = f"payslip-{period}.pdf"
    return pdf, filename


def build_run_payslip_zip(run_id: str, firm_id: Optional[str]) -> tuple[bytes, str, list[str]]:
    """Every payslip in one run, as a zip. Returns (zip_bytes, filename, problems).

    WHY A ZIP AND NOT THIRTY REQUESTS. get_payslip_pdf renders ONE slip and
    re-reads the employer for each — so a CA with thirty employees clicked thirty
    times, waited for thirty round trips to Mumbai, and got thirty files named
    the same thing, because the single-slip filename is `payslip-YYYY-MM.pdf`
    with no employee in it. The month-end pack is one action.

    ONE QUERY FOR THE SLIPS AND ONE FOR THE EMPLOYER. The per-slip path reads
    the employer every time; here it is read once and passed to every render,
    which is the difference between one round trip and thirty.

    A SLIP THAT WILL NOT RENDER IS REPORTED, NOT SKIPPED SILENTLY. If one
    employee's slip fails, the other twenty-nine are still worth having — but a
    zip that quietly contains twenty-nine files when the run has thirty is a
    trap, because nobody counts. The names come back in `problems` and the
    caller puts them on the response.

    Firm-scoped on the RUN, once, rather than per slip: the slips are selected
    by run_id, so proving the run belongs to the firm proves it for all of them.
    """
    import io
    import zipfile

    from core.supabase_client import get_supabase
    db = get_supabase()

    run = (db.table("payroll_runs")
           .select("id, firm_id, client_id, month, status")
           .eq("id", run_id).maybe_single().execute().data)
    if not run:
        raise ValueError("Payroll run not found")
    # Fail CLOSED, like get_payslip_pdf: deny unless ownership is proven.
    if not firm_id or run.get("firm_id") != firm_id:
        raise PermissionError("Access denied")

    slips = (db.table("payroll_slips")
             .select("*, payroll_employees(name, pan, designation, department, "
                     "uan, esi_number, bank_account_no, bank_ifsc)")
             .eq("run_id", run_id).execute().data) or []
    if not slips:
        raise ValueError("This run has no payslips")

    employer = load_employer(run.get("firm_id"), run.get("client_id"))
    # ONE year-to-date query for the whole run, not one per employee. Thirty
    # employees would otherwise be thirty more round trips to Mumbai on top of
    # the thirty this function exists to collapse into one.
    ytd_by_employee = load_ytd(run.get("firm_id"), run.get("client_id"),
                               run.get("month"),
                               [s.get("employee_id") for s in slips])
    month = run.get("month") or "payslips"

    problems: list[str] = []
    used: set[str] = set()
    buf = io.BytesIO()
    # ZIP_DEFLATED: a payslip PDF is mostly text and compresses well, and a
    # thirty-employee pack is emailed rather than streamed.
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for slip in slips:
            employee = slip.pop("payroll_employees", None) or {}
            name = (employee.get("name") or "employee").strip()
            try:
                pdf = build_payslip_pdf(slip, employee, run, employer,
                                        ytd=ytd_by_employee.get(slip.get("employee_id")))
            except Exception as e:  # noqa: BLE001 — one bad slip must not lose the rest
                logger.exception("payslip render failed for slip %s", slip.get("id"))
                problems.append(f"{name}: could not be rendered ({e.__class__.__name__}).")
                continue
            zf.writestr(_payslip_filename(name, month, used), pdf)

    return buf.getvalue(), f"payslips-{month}.zip", problems


def _payslip_filename(name: str, month: str, used: set) -> str:
    """A file name per employee, unique within the zip.

    The single-slip endpoint names every file `payslip-YYYY-MM.pdf`, which is
    fine for one download and useless for thirty — they collide, and a zip
    entry written twice under one name is not an error, it is a file the reader
    silently keeps only one of. Two employees genuinely can share a name, so
    the collision is resolved with a counter rather than assumed away.
    """
    safe = "".join(ch if (ch.isalnum() or ch in " -_") else "" for ch in name).strip()
    safe = "-".join(safe.split()) or "employee"
    stem = f"payslip-{month}-{safe}"
    candidate, n = f"{stem}.pdf", 2
    while candidate in used:
        candidate = f"{stem}-{n}.pdf"
        n += 1
    used.add(candidate)
    return candidate


def load_ytd(firm_id: Optional[str], client_id: Optional[str],
             month: Optional[str], employee_ids) -> dict:
    """{employee_id: ytd_totals(...)} for the financial year up to `month`.

    TWO QUERIES, BOUNDED BY THE SIZE OF THE ANSWER, not by transaction volume:
    at most twelve payroll runs in a financial year, and at most one slip per
    employee per run. That is the reporting rule — a year-to-date that read the
    slip table unfiltered would grow with the client's whole payroll history to
    print one column.

    Returns {} rather than raising when the period cannot be resolved or the
    query fails: the YTD block is then absent from the payslip, and an absent
    block is honest where a zero would be a false statement. The pay itself is
    on the document either way, and a month-end pack must not fail to render
    over a supplementary figure.
    """
    ids = [e for e in (employee_ids or []) if e]
    months = fy_months_upto(month or "")
    if not ids or not months or not firm_id or not client_id:
        return {}
    from core.supabase_client import get_supabase
    db = get_supabase()
    try:
        runs = (db.table("payroll_runs")
                .select("id")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .in_("month", months).execute().data) or []
        run_ids = [r.get("id") for r in runs if r.get("id")]
        if not run_ids:
            return {}
        rows = (db.table("payroll_slips")
                .select("employee_id, gross_paise, net_paise, "
                        + ", ".join(key for _label, key in DEDUCTION_DEFS))
                .in_("run_id", run_ids).in_("employee_id", ids)
                .execute().data) or []
    except Exception:  # noqa: BLE001 — see the docstring: the pay is not at stake
        logger.exception("year-to-date lookup failed for client %s %s", client_id, month)
        return {}

    by_employee: dict = {}
    for row in rows:
        by_employee.setdefault(row.get("employee_id"), []).append(row)
    return {eid: ytd_totals(slips) for eid, slips in by_employee.items()}


def load_employer(firm_id: Optional[str], client_id: Optional[str]) -> dict:
    """The `clients` row the payslip is issued BY — firm-scoped, and refused
    rather than defaulted.

    Falling back to the firm is what produced the defect: every payslip in the
    product headed with the CA practice's name instead of the employer's. A
    missing client row is a question, not a letterhead — the same rule
    statement_pdf_service.load_account_holder already applies to the document
    a client's customer receives.
    """
    if not client_id or not firm_id:
        raise ValueError(
            "A payslip cannot be issued without knowing which employer issued "
            "it — the payroll run carries no client."
        )
    from core.supabase_client import get_supabase
    db = get_supabase()
    row = (db.table("clients")
           .select("id,client_name,legal_name,trade_name,gstin,pan")
           .eq("id", client_id).eq("firm_id", firm_id)
           .maybe_single().execute())
    employer = dict(getattr(row, "data", None) or {})
    if not employer:
        raise ValueError(
            f"Client {client_id} not found for firm {firm_id} — a payslip "
            "cannot be issued without knowing who the employer is."
        )

    # The employer's OWN registrations (migration 325). A separate table and a
    # separate read, because a client that has not recorded them is normal —
    # not every client runs payroll — and the payslip simply omits the line.
    # Failure here must not take the payslip down with it: the pay is the
    # document, the establishment code is a convenience on it.
    try:
        ident = (db.table("client_statutory_identity")
                 .select("tan,epf_establishment_code,esic_employer_code,lin")
                 .eq("firm_id", firm_id).eq("client_id", client_id)
                 .maybe_single().execute())
        for key, value in (getattr(ident, "data", None) or {}).items():
            if value:
                employer[key] = value
    except Exception:  # noqa: BLE001 — see above
        logger.exception("statutory identity lookup failed for client %s", client_id)
    return employer
