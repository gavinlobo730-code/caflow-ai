"""PF ECR filing demo — the monthly EPF return, from a finalized payroll run.

THE REAL CHANNEL THIS MIMICS (POST-A-518)
    unifiedportal-emp.epfindia.gov.in, in the order EPFO's own User Manual for the re-engineered ECR (v3.0, read on 19-11-2026,
    pages 3 to 15, 21 and 22) walks it:

      1. Payments, Return Filing, the wage month, View/Upload.
      2. The upload page: the ECR text file, the return type (Regular, Supplementary or Revised), the contribution rate (12% or
         10%) and a remark.
      3. The portal checks the file and gives either an error file or a RETURN FILE ID (12 digits in the manual's example,
         250100001024) and a return statement.
      4. The employer approves or rejects the return statement. Once approved, "the wages and contribution details cannot be
         modified".
      5. The Due Deposit Balance Summary then offers full payment, part payment by a contribution file, administrative and
         inspection charges, and interest and damages (which the portal computes).
      6. Prepare Challan, Finalize, and ONLY THEN the TRRN (15 digits in the manual's example, 250113000000438).
      7. Pay: choose a bank, make the payment; the receipt comes from View/Pay Challan.

    The return and the payment are two acts, and the Scheme says so: the Employees' Provident Funds Scheme, 2026 (G.S.R. 525(E) of
    29-06-2026, read on 19-11-2026) has the employer upload the return in Form VII within fifteen days of the close of the month
    "and thereafter pay the dues" (para 24(2)(ix)) and remit within fifteen days of the close of every month (para 28(3)); a late
    return carries a fee of Rs 500 a day, capped at the month's administrative charge (para 29(2)). The walk-through used to put
    the TRRN at the upload and generate the challan when the file was verified, which is the order before the revamp and not the
    manual's.

    WHAT THE MANUAL DOES NOT SETTLE, and this walk-through therefore does not state: whether the portal asks for an OTP or a
    digital signature at any step. The manual's home page carries a notice that the OTP-based second step on the employer login
    "has been temporarily relaxed" and another that "the existing digital signature process has been changed", and the manual does
    not say whether either touches the return. This walk-through used to say "no DSC and no OTP in the monthly flow"; it now has no
    declaration, signature or otp STAGE because nothing in the manual's walk of the return or the payment asks for one, and it takes
    no OTP in any case: an OTP is typed on the portal, never here.

    A month with no active members is a different route: the FAQs (question 21) say the administrative and inspection charges for
    such a month are paid through Direct Challan Entry, which the portal enables only when there are no active members. The
    walk-through used to say such a month "needs a NIL return".

    Software may not transmit this today: EPFO exposes no public API for ECR upload — the employer portal is the only door. The
    demo says so in real_channel.

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
from core.db_provider import privileged_for

# Statuses from which the real ECR is prepared. A draft or in-review run's
# figures are still moving; the portal upload happens after payroll is
# settled — payroll_runs_status_check (migrations 093/225) is the full set.
_FILEABLE_STATUSES = ("finalized", "paid")


def _due_date_text(month: str) -> str | None:
    """'YYYY-MM' → '15-MM-YYYY' of the FOLLOWING month, or None when the
    stored month is malformed. Employees' Provident Funds Scheme, 2026, paras
    24(2)(ix) and 28(3): the return is uploaded and the dues remitted within
    fifteen days of the close of the month. Integer arithmetic only."""
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

    rows = (privileged_for(db).table("payroll_runs").select("*")
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
            "deposit. (For a month in which the establishment has no active "
            "members the portal's FAQ, question 21, has the administrative and "
            "inspection charges paid through Direct Challan Entry; this "
            "walk-through covers the contribution upload.)")

    # payroll_slips carries neither firm_id nor client_id — its only scope
    # column is run_id. The run row above was fetched WITH the firm and
    # client filters, so run_id is already proven to belong to this tenant
    # and scoping the slips by it is the firm+client scope, one hop removed.
    # Columns are narrowed to the PF legs: what we need is WHICH members the
    # ECR would list, which is headcount-sized, not ledger-sized.
    slips = (privileged_for(db).table("payroll_slips")
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
        employees = (privileged_for(db).table("payroll_employees").select("id,name,uan")
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
        # Paras 24(2)(ix) and 28(3), Employees' Provident Funds Scheme 2026 —
        # see _due_date_text.
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
        # THE UPLOAD PAGE, as the manual draws it (User Manual v3.0, pages 7 and
        # 8): the form asks for four things beside the file, and the file itself
        # has rules about its name and size that the portal enforces before it
        # ever reads a line. Said in the manual's words, with no claim of what
        # the portal will accept.
        common.table_stage(
            "The upload page",
            "After Payments, Return Filing and the wage month, the portal's "
            "View/Upload page asks for the file and three choices beside it. "
            "This is what it asks, in the order it asks.",
            ["On the upload page", "What it asks for"],
            [
                [{"text": "The ECR file"},
                 {"text": "A text file, or a zip holding one text file, up to "
                          "8 MB (the portal asks for a text file above 2 MB to "
                          "be compressed). Its notice asks for letters and "
                          "digits only in the file name, with the extension in "
                          "small case — this product names the file ECR and the "
                          "wage month, for example ECR202609.txt."}],
                [{"text": "Return type"},
                 {"text": "Regular, Supplementary or Revised. A Regular is every "
                          "active member for the month; a Supplementary is for "
                          "members registered after that month's Regular was "
                          "approved; a Revised corrects figures already "
                          "submitted."}],
                [{"text": "Contribution rate"},
                 {"text": "12% or 10%. The file this product builds is at 12%."}],
                [{"text": "Remark"},
                 {"text": "The form marks the remark as required."}],
            ],
        ),
        # THE FILE ITSELF, AND THE FOUR CHECKS THAT REJECT IT. The ECR is not
        # a form filled on the portal — it is a text file the portal parses,
        # and an upload that fails on line 40 of 200 fails as a whole. A CA
        # who has had one bounce recognises these instantly; one who has not
        # is about to. ECR 2.0 format: plain .txt, #~# delimited, eleven
        # fields per member, keyed by UAN, which the manual (page 8) and the
        # FAQs (questions 2 and 16) say is unchanged by the revamp.
        common.table_stage(
            "The ECR file, and what the portal checks",
            "One line per member, #~# separated, eleven fields, keyed by UAN "
            "— the ECR 2.0 format, unchanged by the 2025 revamp of the "
            "workflow around it. The portal parses the whole file and "
            "rejects it as a whole, so these checks are worth meeting before "
            "the upload rather than at it. If the file fails, the portal "
            "gives an error file and no Return File ID.",
            ["Check the portal applies", "What it means"],
            [
                [{"text": "EPF wages ≤ gross wages"},
                 {"text": "A contribution base above the pay it came out of "
                          "is a data error, not a policy choice."}],
                [{"text": "EPS wages ≤ EPF wages"},
                 {"text": "The pension share is carved OUT of the "
                          "contribution, never added to it."}],
                [{"text": "EDLI wages = EPF wages, capped at the notified wage ceiling"},
                 {"text": "The insurance base follows the PF base up to the "
                          "wage ceiling the Government notifies (₹25,000 from "
                          "17-09-2026, ₹15,000 before) and no further."}],
                [{"text": "Every member line carries a UAN"},
                 {"text": "The UAN is the key. A member without one cannot "
                          "appear in the file at all."}],
            ],
        ),
        # SEQUENCE, WHICH IS THE ONE THAT ACTUALLY STOPS A BUREAU. The
        # re-engineered ECR (from wage month September 2025) enforces the
        # order: a later month cannot be filed while an earlier one is
        # pending, which turns a single skipped month into a blocked queue.
        # A month with no active members is NOT a NIL return: the FAQs
        # (question 21) have its administrative and inspection charges paid
        # through Direct Challan Entry, enabled only when there are no active
        # members (POST-A-518; the walk-through used to say NIL return).
        # Filing and payment are also two acts, which the Scheme itself says
        # (paras 24(2)(ix) and 28(3)), so an approved return with an unpaid
        # challan is a live liability.
        common.warning_stage(
            "The ECR is filed in wage-month ORDER. Since the re-engineered "
            "ECR (from wage month September 2025) a later month cannot be "
            "uploaded while an earlier one is still pending — so one skipped "
            "month blocks every month after it. A month in which the "
            "establishment has no active members is a different route: the "
            "portal's FAQ (question 21) has the administrative and "
            "inspection charges for such a month paid through Direct Challan "
            "Entry, which it enables only when there are no active members. "
            "Filing and paying are also two separate acts: approving the "
            "return does not pay anything, and the TRRN comes only when the "
            "challan is finalised, so an unpaid challan is a live liability "
            "whatever the portal shows about the return.",
        ),
        # THE PORTAL'S OWN IRREVERSIBILITY WARNING (User Manual v3.0): after the
        # file passes, the employer approves or rejects the return statement,
        # and an approval cannot be undone. The lawful correction route is the
        # Revised return, which is what the manual's return types are for.
        common.warning_stage(
            "After the file passes its checks the portal gives a Return File "
            "ID and a return statement, and the employer approves or rejects "
            "the statement. The manual says that once approved, the wages and "
            "contribution details cannot be modified: a correction after that "
            "goes in a Revised return, not by changing the approved one. "
            "Check the statement against the figures here before approving.",
            cta="Proceed",
        ),
        # THE DUE DEPOSIT BALANCE SUMMARY (manual pages 12 and 22): what the
        # portal offers once a return is approved. Interest and damages are the
        # portal's own figures and this product never computes them — a second
        # implementation of a statutory interest calculation drifts, and the CA
        # would have two numbers with no way to tell which the portal accepts
        # (domain/payroll/ecr.py, tests/test_the_ecr_knows_which_months_are_
        # outstanding.py). The manual labels them sections 7Q and 14B of the
        # 1952 Act, repealed from 21-11-2025; the 2026 Scheme names the Code's
        # sections 127 and 128 for interest and damages (para 20(7), for an
        # exempted establishment's late transfer), so no section is cited as
        # the portal's own label on the screen.
        common.table_stage(
            "The Due Deposit Balance Summary",
            "Once the return is approved the portal shows what is payable for "
            "the month and offers the ways to pay it. Nothing in it is a "
            "figure this walk-through can give: the portal computes them.",
            ["The summary offers", "What it is"],
            [
                [{"text": "Contributions"},
                 {"text": "Raised from the approved return, to pay in full or "
                          "in part by uploading a contribution file."}],
                [{"text": "Administrative and inspection charges"},
                 {"text": "Offered as a payment of their own."}],
                [{"text": "Interest and damages"},
                 {"text": "Computed by EPFO and shown in the summary. This "
                          "product never computes them: a second figure for a "
                          "statutory calculation would only drift from the "
                          "portal's."}],
            ],
        ),
        common.table_stage(
            "Challan account heads",
            "Prepare Challan and Finalize then raise one challan split across "
            "the EPFO scheme accounts. This run stores the employee + employer "
            "PF as one combined figure, so the rates below are the statutory "
            "split shown indicatively — the portal computes the exact amounts "
            "from the approved return.",
            ["A/c", "Head", "Rate (indicative)"],
            [
                # Employees' Provident Funds Scheme, 2026 para 18: the employee's
                # contribution is 12% of the wages and the employer matches it,
                # of which EPS takes its share (next row) and the balance 3.67%
                # stays in EPF.
                [{"text": "A/c 1"}, {"text": "EPF contributions"},
                 {"text": "Employee 12% + employer balance 3.67%"}],
                # Administrative charges: EPFO's rates sheet of 2018 gives 0.5%
                # of PF wages (minimum ₹500) from 01-06-2018; the 2026 Scheme
                # leaves the percentage to the Central Government (paras 28(2)
                # and 29(1)).
                [{"text": "A/c 2"}, {"text": "EPF administrative charges"},
                 {"text": "0.5% of PF wages (min ₹500)"}],
                # Employees' Pension Scheme, 2026 para 4(1): 8.33% diverted
                # from the employer's 12%, on wages up to the notified wage
                # ceiling (statutory.PF_WAGE_CEILINGS; Rs 25,000 from
                # 17-09-2026, Rs 15,000 before).
                [{"text": "A/c 10"}, {"text": "EPS (pension)"},
                 {"text": "8.33% of wages up to the notified wage ceiling"}],
                # Employees' Deposit-Linked Insurance Scheme, 2026 para 5(1):
                # the contribution is "as notified"; EPFO's rates sheet of 2018
                # gives 0.5% of PF wages (owner list S49).
                [{"text": "A/c 21"}, {"text": "EDLI"},
                 {"text": "0.5% of PF wages"}],
                # EDLI administrative charges stand waived w.e.f. 01-04-2017
                # (EPFO's rates sheet of 2018).
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
        # The steps are the manual's order, and the reference each one yields:
        # the Return File ID at the checks, the TRRN only at Finalize.
        common.transmit_stage([
            {"key": "prepare", "label": "Preparing ECR text file (#~# separated)"},
            {"key": "upload", "label": "Uploading with the wage month, return type and rate"},
            {"key": "validate", "label": "Portal checking the file — error file, or a Return File ID"},
            {"key": "approve", "label": "Return statement shown; the employer approves it (cannot be undone)"},
            {"key": "summary", "label": "Due Deposit Balance Summary shown"},
            {"key": "challan", "label": "Challan prepared and finalised — TRRN issued"},
            {"key": "payment", "label": "Challan ready to pay through a bank chosen on the portal"},
        ]),
        common.result_stage(
            "EPFO",
            "Challan reference (TRRN)",
            common.specimen_epfo_trrn(run_id),
            f"ECR for {month} — on the real portal the return would have its "
            "own Return File ID when the file passed its checks, and this "
            "TRRN would appear only after the return was approved and the "
            "challan finalised.",
            [
                "Nothing was uploaded and nothing was paid — payment is made "
                "on the portal itself, through the bank you choose there.",
                "To file for real: log in at unifiedportal-emp.epfindia.gov.in, "
                "upload the ECR, approve the return statement, then prepare and "
                "finalise the challan and pay it, by the 15th of the following "
                "month. Keep the Return File ID, the TRRN and the receipt from "
                "View/Pay Challan.",
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
                   "establishment's login — the ECR text file, the portal's "
                   "checks and a Return File ID, the employer's approval of the "
                   "return statement, the Due Deposit Balance Summary, then the "
                   "challan (TRRN) and its payment through a bank. The manual "
                   "does not say whether the portal's OTP-based second step on "
                   "the employer login or its digital signature process touches "
                   "the return, so this walk-through states neither.",
            "software_permitted": False,
            "note": "EPFO exposes no public API for ECR upload; the employer "
                    "portal is the only channel. PracticeSync prepares the "
                    "figures and the employer files on the portal.",
        },
        # What changes when this is real. The gate here is not a registration
        # PracticeSync could obtain — it is the EMPLOYER's establishment
        # login, which belongs to the client and is theirs to use, and no
        # public API exists behind it in any case. So nothing is left to wait
        # for: the file is built today (domain/payroll/ecr.build_ecr, served
        # by GET /api/payroll/runs/{run_id}/ecr) and the transmission is not
        # ours to build. Say the first in the present tense —
        # tests/test_filing_demo_payroll.py holds the premise and the tense.
        "There is no registration to wait for here, and pretending otherwise "
        "would be the easy lie: EPFO publishes no API for ECR upload, and "
        "the only door is the employer's own establishment login on "
        "unifiedportal-emp.epfindia.gov.in — which belongs to the client, "
        "not to the firm, and should stay that way. PracticeSync already "
        "produces the ECR .txt itself from a finalised payroll run, member "
        "by member with each UAN, and names every member the file cannot "
        "carry (no UAN, a ceiling breached) before the upload rather than "
        "after the portal rejects the batch, so the step is an upload of a "
        "file rather than a spreadsheet reconciled by hand. The upload, the "
        "employer's approval of the return, the challan and the payment "
        "stay with whoever holds the establishment login.",
        stages,
    )
