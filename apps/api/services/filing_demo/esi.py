"""ESI filing demo — the monthly contribution, from a finalized payroll run.

THE REAL CHANNEL THIS MIMICS
    esic.gov.in employer portal → login with the 17-digit employer code →
    Monthly Contribution → enter or upload the contribution details, one
    line per Insured Person (IP) number → portal validation → a 19-digit
    challan generated → pay online. Due by the 15th of the following month
    (Regulation 31, ESI (General) Regulations 1950 — within fifteen days of
    the last day of the calendar month, as amended w.e.f. June 2017).

    There is NO digital-signature ceremony and NO OTP anywhere in the
    monthly contribution flow — it is a password login and an online
    payment — so this walk-through has no declaration, signature or otp
    stage. ESIC publishes no statutory declaration text for the monthly
    contribution either, and the demo does not invent one.

    Software may not transmit this today: ESIC exposes no public API for
    contribution filing — the employer portal is the only door. The demo
    says so in real_channel.

ref: {"run_id": <payroll_runs.id>} — the finalized (or paid) payroll run
whose stored ESI total the walk-through presents. Read-only throughout.

HONESTY ABOUT THE SPLIT
    payroll_runs.total_esi_paise is the employee + employer contribution
    COMBINED, so the table stage shows the two statutory rates as
    indicative text and the combined stored figure once, rather than
    fabricating an exact split the data does not contain — the portal
    computes the exact shares from each IP's wages.
"""
from __future__ import annotations

from services.filing_demo import common

# Statuses from which the real contribution is filed. A draft or in-review
# run's figures are still moving; the portal filing happens after payroll is
# settled — payroll_runs_status_check (migrations 093/225) is the full set.
_FILEABLE_STATUSES = ("finalized", "paid")


def _due_date_text(month: str) -> str | None:
    """'YYYY-MM' → '15-MM-YYYY' of the FOLLOWING month, or None when the
    stored month is malformed. Regulation 31, ESI (General) Regulations
    1950: contributions are payable within fifteen days of the last day of
    the calendar month. Integer arithmetic only."""
    parts = str(month).split("-")
    if len(parts) != 2 or not (parts[0].isdigit() and parts[1].isdigit()):
        return None
    year, m = int(parts[0]), int(parts[1])
    if not 1 <= m <= 12:
        return None
    m += 1
    if m == 13:
        m, year = 1, year + 1
    return f"15-{m:02d}-{year}"


def build(db, firm_id: str, client_id: str, ref: dict) -> dict:
    """Compose the ESI walk-through. Three selects — run header, the run's
    ESI slip columns, the covered IPs' ESI numbers — no writes of any kind."""
    run_id = str(ref.get("run_id") or "")
    if not run_id:
        raise ValueError("esi demo needs ref.run_id")

    rows = (db.table("payroll_runs").select("*")
            .eq("id", run_id).eq("firm_id", firm_id)
            .eq("client_id", client_id).limit(1).execute().data) or []
    if not rows:
        raise ValueError("Payroll run not found")
    run = rows[0]

    status = run.get("status") or ""
    if status not in _FILEABLE_STATUSES:
        raise ValueError(
            f"The ESI contribution is filed from a finalized payroll run. "
            f"This run is still '{status}' — finalize it first.")

    month = run.get("month") or ""
    total_esi = int(run.get("total_esi_paise") or 0)
    headcount = int(run.get("headcount") or 0)
    if total_esi <= 0:
        raise ValueError(
            "This run records no ESI contribution, so there is nothing to "
            "deposit. (The real portal takes a zero-contribution declaration "
            "with a reason for such months; this walk-through covers the "
            "contribution filing.)")

    # payroll_slips carries neither firm_id nor client_id — its only scope
    # column is run_id. The run row above was fetched WITH the firm and
    # client filters, so run_id is already proven to belong to this tenant
    # and scoping the slips by it is the firm+client scope, one hop removed.
    # Columns are narrowed to the ESI legs: what we need is WHICH employees
    # the filing would cover, which is headcount-sized, not ledger-sized.
    slips = (db.table("payroll_slips")
             .select("employee_id,esi_employee_paise,esi_employer_paise")
             .eq("run_id", run_id).execute().data) or []
    covered_ids = sorted({
        s["employee_id"] for s in slips
        if s.get("employee_id") is not None
        and (int(s.get("esi_employee_paise") or 0)
             + int(s.get("esi_employer_paise") or 0)) > 0
    })

    # The monthly contribution is filed per Insured Person (IP) number — an
    # employee without one cannot appear in the filing at all (employee
    # declaration and allotment of the insurance number under Regulations
    # 11–12, ESI (General) Regulations 1950, precede contribution), so the
    # demo surfaces exactly who would block the real filing.
    missing_ip: list[str] = []
    if covered_ids:
        employees = (db.table("payroll_employees").select("id,name,esi_number")
                     .eq("firm_id", firm_id).eq("client_id", client_id)
                     .in_("id", covered_ids).execute().data) or []
        missing_ip = sorted(
            (e.get("name") or "(unnamed employee)")
            for e in employees if not str(e.get("esi_number") or "").strip())

    due = _due_date_text(month)
    figures = [
        {"label": "Wage month", "text": month},
        {"label": "Employees in this run", "text": str(headcount)},
        {"label": "ESI payable (employee + employer)", "paise": total_esi},
    ]
    if due:
        # Regulation 31, ESI (General) Regulations 1950 — see _due_date_text.
        figures.append({"label": "Due date", "text": f"{due} (15th of the following month)"})

    stages = [
        common.summary_stage(
            f"ESI contribution · {month}",
            "On the portal this is the monthly contribution ready to file — "
            "one line per Insured Person (IP) number, built from this "
            "payroll run.",
            figures,
            cta="Proceed to file",
        ),
        common.table_stage(
            "Contribution split",
            "This run stores the employee + employer ESI as one combined "
            "figure, so the rates below are the statutory split shown "
            "indicatively — the portal computes the exact shares from each "
            "IP's wages. Coverage applies up to a wage ceiling of "
            "₹21,000/month (₹25,000 for employees with disability) — "
            "Rule 50, ESI (Central) Rules 1950.",
            ["Contribution", "Rate (indicative)"],
            [
                # Rule 51, ESI (Central) Rules 1950, w.e.f. 01-07-2019:
                # employee's contribution 0.75% of wages.
                [{"text": "Employee's contribution"}, {"text": "0.75% of wages"}],
                # Rule 51, same notification: employer's contribution 3.25%.
                [{"text": "Employer's contribution"}, {"text": "3.25% of wages"}],
            ],
            footer=[{"text": "ESI recorded on this run (employee + employer, combined)"},
                    {"paise": total_esi}],
        ),
    ]

    if missing_ip:
        stages.append(common.warning_stage(
            "The monthly contribution is filed per Insured Person (IP) "
            f"number. {len(missing_ip)} employee(s) in this run have no ESI "
            f"number on record: {', '.join(missing_ip)}. On the real portal "
            "their lines cannot be filed — register them and capture the IP "
            "numbers before filing.",
            cta="Proceed anyway (demo)",
        ))

    stages += [
        common.transmit_stage([
            {"key": "login", "label": "Signing in with the 17-digit employer code"},
            {"key": "upload", "label": "Submitting monthly contribution details"},
            {"key": "validate", "label": "Portal validating IP lines"},
            {"key": "challan", "label": "Challan generated (19 digits)"},
            {"key": "payment", "label": "Challan ready for online payment"},
        ]),
        common.result_stage(
            "ESIC",
            "Challan number",
            common.specimen_esic_challan(run_id),
            f"ESI contribution for {month} — on the real portal this challan "
            "would now be paid online, completing the monthly filing.",
            [
                "Nothing was submitted and nothing was paid — payment happens "
                "online on the portal itself.",
                "To file for real: log in at esic.gov.in with the 17-digit "
                "employer code, file the monthly contribution, generate the "
                "challan and pay online, by the 15th of the following month.",
            ],
        ),
    ]

    return common.envelope(
        "esi",
        "File ESI contribution",
        f"ESIC · {month}",
        run_id,
        {
            "how": "Filed on esic.gov.in with the establishment's 17-digit "
                   "employer code — monthly contribution per IP, 19-digit "
                   "challan, online payment. No DSC and no OTP in the "
                   "monthly flow.",
            "software_permitted": False,
            "note": "ESIC exposes no public API for contribution filing; the "
                    "employer portal is the only channel. PracticeSync "
                    "prepares the figures and the employer files on the "
                    "portal.",
        },
        stages,
    )
