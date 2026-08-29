"""PF ECR filing demo — the monthly EPF return, from a finalized payroll run.

THE REAL CHANNEL THIS MIMICS
    unifiedportal-emp.epfindia.gov.in → login with the establishment's
    username and password → Payments → ECR upload → the ECR text file
    (#~# separated, one line per member keyed by UAN) → portal validation →
    a 10-digit TRRN (Temporary Return Reference Number) for the upload →
    verify the ECR → challan generated, split across the scheme account
    heads → pay by net banking. Due by the 15th of the following month
    (para 38(1), EPF Scheme 1952 — within fifteen days of the close of the
    month).

    There is NO digital-signature ceremony and NO OTP anywhere in the
    monthly ECR flow — it is a password login and a net-banking payment —
    so this walk-through has no declaration, signature or otp stage. EPFO
    publishes no statutory declaration text for the ECR either, and the
    demo does not invent one.

    Software may not transmit this today: EPFO exposes no public API for
    ECR upload — the employer portal is the only door. The demo says so in
    real_channel.

ref: {"run_id": <payroll_runs.id>} — the finalized (or paid) payroll run
whose stored PF total the walk-through presents. Read-only throughout.

HONESTY ABOUT THE SPLIT
    payroll_runs.total_pf_paise is the employee + employer contribution
    COMBINED, and the challan's account-head split (A/c 1/2/10/21/22)
    cannot be derived from it faithfully — EPS diversion depends on each
    member's capped wages, and the admin/EDLI charges are employer costs on
    top of the contribution. So the table stage shows the statutory rates
    as indicative text and the combined stored figure once, rather than
    fabricating an exact split the data does not contain.
"""
from __future__ import annotations

from services.filing_demo import common

# Statuses from which the real ECR is prepared. A draft or in-review run's
# figures are still moving; the portal upload happens after payroll is
# settled — payroll_runs_status_check (migrations 093/225) is the full set.
_FILEABLE_STATUSES = ("finalized", "paid")


def _due_date_text(month: str) -> str | None:
    """'YYYY-MM' → '15-MM-YYYY' of the FOLLOWING month, or None when the
    stored month is malformed. Para 38(1), EPF Scheme 1952: dues are payable
    within fifteen days of the close of the month. Integer arithmetic only."""
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
    """Compose the PF ECR walk-through. Three selects — run header, the run's
    slip PF columns, the covered members' UANs — no writes of any kind."""
    run_id = str(ref.get("run_id") or "")
    if not run_id:
        raise ValueError("pf demo needs ref.run_id")

    rows = (db.table("payroll_runs").select("*")
            .eq("id", run_id).eq("firm_id", firm_id)
            .eq("client_id", client_id).limit(1).execute().data) or []
    if not rows:
        raise ValueError("Payroll run not found")
    run = rows[0]

    status = run.get("status") or ""
    if status not in _FILEABLE_STATUSES:
        raise ValueError(
            f"The PF ECR is filed from a finalized payroll run. This run is "
            f"still '{status}' — finalize it first.")

    month = run.get("month") or ""
    total_pf = int(run.get("total_pf_paise") or 0)
    headcount = int(run.get("headcount") or 0)
    if total_pf <= 0:
        raise ValueError(
            "This run records no PF contribution, so there is nothing to "
            "deposit. (The real portal offers a nil-ECR declaration for such "
            "months; this walk-through covers the contribution upload.)")

    # payroll_slips carries neither firm_id nor client_id — its only scope
    # column is run_id. The run row above was fetched WITH the firm and
    # client filters, so run_id is already proven to belong to this tenant
    # and scoping the slips by it is the firm+client scope, one hop removed.
    # Columns are narrowed to the PF legs: what we need is WHICH members the
    # ECR would list, which is headcount-sized, not ledger-sized.
    slips = (db.table("payroll_slips")
             .select("employee_id,pf_employee_paise,pf_employer_paise")
             .eq("run_id", run_id).execute().data) or []
    member_ids = sorted({
        s["employee_id"] for s in slips
        if s.get("employee_id") is not None
        and (int(s.get("pf_employee_paise") or 0)
             + int(s.get("pf_employer_paise") or 0)) > 0
    })

    # The ECR file is one line per member, keyed by UAN (Universal Account
    # Number — ECR 2.0 format, mandatory since the 2016 UAN-seeded revision).
    # A member without a UAN cannot appear in the upload at all, so the demo
    # surfaces exactly who would block the real filing.
    missing_uan: list[str] = []
    if member_ids:
        employees = (db.table("payroll_employees").select("id,name,uan")
                     .eq("firm_id", firm_id).eq("client_id", client_id)
                     .in_("id", member_ids).execute().data) or []
        missing_uan = sorted(
            (e.get("name") or "(unnamed employee)")
            for e in employees if not str(e.get("uan") or "").strip())

    due = _due_date_text(month)
    figures = [
        {"label": "Wage month", "text": month},
        {"label": "Employees in this run", "text": str(headcount)},
        {"label": "PF payable (employee + employer)", "paise": total_pf},
    ]
    if due:
        # Para 38(1), EPF Scheme 1952 — see _due_date_text.
        figures.append({"label": "Due date", "text": f"{due} (15th of the following month)"})

    stages = [
        common.summary_stage(
            f"PF ECR · {month}",
            "On the portal this is the ECR ready for upload — a #~# "
            "separated text file, one line per member keyed by UAN, built "
            "from this payroll run.",
            figures,
            cta="Proceed to upload",
        ),
        common.table_stage(
            "Challan account heads",
            "The verified ECR generates one challan split across the EPFO "
            "scheme accounts. This run stores the employee + employer PF as "
            "one combined figure, so the rates below are the statutory split "
            "shown indicatively — the portal computes the exact amounts from "
            "each member's line.",
            ["A/c", "Head", "Rate (indicative)"],
            [
                # EPF Act 1952 §6: employee 12% of (basic + DA); the employer
                # matches 12%, of which EPS takes its share (next row) and
                # the balance 3.67% stays in EPF.
                [{"text": "A/c 1"}, {"text": "EPF contributions"},
                 {"text": "Employee 12% + employer balance 3.67%"}],
                # EPF Scheme 1952 para 30(3): administrative charges, 0.5%
                # of PF wages (minimum ₹500) w.e.f. 01-06-2018.
                [{"text": "A/c 2"}, {"text": "EPF administrative charges"},
                 {"text": "0.5% of PF wages (min ₹500)"}],
                # EPS-95 para 3: 8.33% diverted from the employer's 12%, on
                # EPF wages capped at ₹15,000/month (= 15_000_00 paise).
                [{"text": "A/c 10"}, {"text": "EPS (pension)"},
                 {"text": "8.33% of wages capped at ₹15,000/month"}],
                # EPF Act §6C with the EDLI Scheme 1976: 0.5% of PF wages.
                [{"text": "A/c 21"}, {"text": "EDLI"},
                 {"text": "0.5% of PF wages"}],
                # EDLI administrative charges stand waived w.e.f. 01-04-2017.
                [{"text": "A/c 22"}, {"text": "EDLI administrative charges"},
                 {"text": "Nil at present"}],
            ],
            footer=[{"text": "PF recorded on this run (employee + employer, combined)"},
                    {"text": ""}, {"paise": total_pf}],
        ),
    ]

    if missing_uan:
        stages.append(common.warning_stage(
            "The ECR lists one line per member, keyed by UAN. "
            f"{len(missing_uan)} employee(s) in this run have no UAN on "
            f"record: {', '.join(missing_uan)}. On the real portal their "
            "lines cannot be uploaded — capture the UANs before filing.",
            cta="Proceed anyway (demo)",
        ))

    stages += [
        common.transmit_stage([
            {"key": "prepare", "label": "Preparing ECR text file (#~# separated)"},
            {"key": "upload", "label": "Uploading ECR to the unified portal"},
            {"key": "validate", "label": "Portal validating member lines"},
            {"key": "trrn", "label": "TRRN issued for this upload"},
            {"key": "challan", "label": "ECR verified, challan generated"},
            {"key": "netbanking", "label": "Challan ready for net-banking payment"},
        ]),
        common.result_stage(
            "EPFO",
            "Temporary Return Reference Number (TRRN)",
            common.specimen_epfo_trrn(run_id),
            f"ECR for {month} — on the real portal this TRRN would track the "
            "upload, and the challan would now be paid by net banking.",
            [
                "Nothing was uploaded and nothing was paid — payment happens "
                "by net banking on the portal itself.",
                "To file for real: log in at unifiedportal-emp.epfindia.gov.in, "
                "upload the ECR, verify it, generate the challan and pay by "
                "net banking, by the 15th of the following month.",
            ],
        ),
    ]

    return common.envelope(
        "pf",
        "File PF ECR",
        f"EPF · {month}",
        run_id,
        {
            "how": "Uploaded on unifiedportal-emp.epfindia.gov.in with the "
                   "establishment's login — ECR text file, TRRN, challan, "
                   "net-banking payment. No DSC and no OTP in the monthly flow.",
            "software_permitted": False,
            "note": "EPFO exposes no public API for ECR upload; the employer "
                    "portal is the only channel. PracticeSync prepares the "
                    "figures and the employer files on the portal.",
        },
        stages,
    )
