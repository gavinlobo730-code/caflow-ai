"""
The salary register, as a file a CA can open.

WHAT WAS MISSING

GET /api/payroll/reports/salary-register returns JSON and always has. A salary
register is a document — it goes to the client, into the audit file, and beside
the bank advice — and there was no way to get one out of the software except by
reading a screen and retyping it.

WHY THE SHAPE IS FIXED HERE AND NOT IN THE ROUTER

One column order, written down once, so the file a CA gets in August has the
same columns in the same places as the one they got in April. A register whose
columns move between months cannot be diffed, and diffing two months is most of
what a register is for.

# Every amount is integer paise on the wire and rupees in the file. The rupee
# conversion happens HERE, at the file boundary, and nowhere earlier — the same
# rule domain/gst/money.py follows for the statutory payloads.
"""

from __future__ import annotations

import csv
import io

#: (csv header, slip key). Order is the document's order and is deliberate:
#: identity, then attendance, then what was EARNED, then what was DEDUCTED,
#: then what was PAID — the order a payslip reads in, so a register and a
#: payslip can be checked against each other line by line.
COLUMNS: list[tuple[str, str]] = [
    ("Employee",            "employee_name"),
    ("PAN",                 "pan"),
    ("Designation",         "designation"),
    ("Department",          "department"),
    ("Working Days",        "working_days"),
    ("Days Present",        "days_present"),
    ("LOP Days",            "lop_days"),
    ("Basic",               "basic_paise"),
    ("HRA",                 "hra_paise"),
    ("DA",                  "da_paise"),
    ("LTA",                 "lta_paise"),
    ("Medical",             "medical_paise"),
    ("Special Allowance",   "special_allowance_paise"),
    ("Other Allowances",    "other_allowances_paise"),
    ("Bonus / Incentive / Arrears", "one_time_earnings_paise"),
    ("Gross",               "gross_paise"),
    ("PF (employee)",       "pf_employee_paise"),
    ("ESI (employee)",      "esi_employee_paise"),
    ("Professional Tax",    "pt_paise"),
    ("TDS",                 "tds_paise"),
    ("Loan Recovery",       "loan_recovery_paise"),
    ("Net Pay",             "net_paise"),
    ("PF (employer)",       "pf_employer_paise"),
    ("ESI (employer)",      "esi_employer_paise"),
    ("EDLI",                "edli_paise"),
    ("PF Admin",            "pf_admin_paise"),
    ("Bank Account",        "bank_account_no"),
    ("Bank IFSC",           "bank_ifsc"),
]

#: Columns that are money and are therefore written in rupees, not paise.
_MONEY = {key for _h, key in COLUMNS if key.endswith("_paise")}


def _rupees(paise) -> str:
    """Integer paise to a plain two-decimal rupee string.

    No thousands separators and no currency symbol: this is a file another
    program will read as often as a person will. Grouping is what makes
    parseFloat("1,25,000") return 1, and a register is exactly the kind of file
    somebody pastes back into a spreadsheet.
    """
    p = int(paise or 0)
    sign = "-" if p < 0 else ""
    p = abs(p)
    return f"{sign}{p // 100}.{p % 100:02d}"


def flatten(slip: dict) -> dict:
    """One register row from one payroll_slips row with its employee joined.

    The employee comes back nested under `payroll_employees` from PostgREST;
    flattened here so the column list above can be a flat mapping and stay
    readable as the document it describes.
    """
    emp = slip.get("payroll_employees") or {}
    row = dict(slip)
    row["employee_name"] = emp.get("name") or ""
    for f in ("pan", "designation", "department", "bank_account_no", "bank_ifsc"):
        row[f] = emp.get(f) or ""
    return row


def to_csv(slips: list[dict]) -> bytes:
    """The register as CSV, with a TOTALS row.

    The totals row is not decoration. A register is checked by adding it up and
    comparing against the run header and the journal, and a file that makes
    somebody do that in a spreadsheet invites the arithmetic to be skipped.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([h for h, _k in COLUMNS])

    totals: dict[str, int] = {k: 0 for k in _MONEY}
    for slip in slips:
        row = flatten(slip)
        out = []
        for _h, key in COLUMNS:
            value = row.get(key)
            if key in _MONEY:
                totals[key] += int(value or 0)
                out.append(_rupees(value))
            else:
                out.append("" if value is None else str(value))
        writer.writerow(out)

    if slips:
        writer.writerow([
            "TOTAL" if key == "employee_name"
            else (_rupees(totals[key]) if key in _MONEY else "")
            for _h, key in COLUMNS
        ])

    # utf-8-sig: the BOM is what makes Excel open a UTF-8 file as UTF-8 rather
    # than as the local code page, which is where an employee named Prakash
    # Iyengar turns into mojibake. Same choice services/time_export_service.py
    # made for the same reason.
    return buf.getvalue().encode("utf-8-sig")
