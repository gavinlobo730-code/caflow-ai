"""
Which employees will make a statutory output fail, before it is built.

WHY THIS EXISTS

Every statutory file payroll produces already refuses the rows it cannot
honestly carry, and each refusal is correct:

    the ECR      refuses a member with no UAN, or a UAN that is not 12 digits
    the ESIC     return refuses an employee with no IP number
    Form 24Q     refuses a deductee with no valid PAN — §206AA, because a row
                 declaring tax at slab rates against no PAN declares a SHORT
                 deduction and §201(1) puts that on the deductor
    §192         withholds on the general slab ladder where no date of birth is
                 on file, which is wrong for anyone sixty or over on the old
                 regime (Part III of the First Schedule)
    PT           reports a state it does not model rather than deducting zero

But every one of them refuses AT FILE-BUILD TIME — on the 7th, when the CA is
trying to file, having already finalised the run and posted the journal. The
information was on the employee master all along.

So this asks the same questions of the roster, at any time, for the whole firm.
It computes nothing and stores nothing: it re-states what the file builders will
say, early enough to do something about.

WHAT IT IS NOT

Not a validity check on the values. A UAN of twelve digits may still belong to
somebody else; a PAN of the right shape may not exist. Those are facts about the
world that no ledger holds — the same reason the bulk import checks the SHAPE of
these fields and nothing more.

And not a gate. Nothing here blocks a run. An employee missing a UAN is still
paid, still on the payslip, still in the ledger; what they are missing is the
means to be REPORTED, which is a different problem with a different deadline.
"""
from __future__ import annotations

import re

from domain.payroll import age as age_domain
from domain.payroll.professional_tax import classify_state as classify_pt_state

PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
UAN_RE = re.compile(r"^\d{12}$")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")

#: Every kind of gap this reports, and what each one BLOCKS. The blocked-thing
#: is the point: "missing UAN" is a shrug, "this employee cannot be on the ECR"
#: is a deadline.
KINDS = ("uan", "esic_ip", "pan", "date_of_birth", "bank", "pt_state")


def _s(row: dict, key: str) -> str:
    return str(row.get(key) or "").strip()


def for_employee(emp: dict, *, fy: str | None = None,
                 old_regime: bool = False) -> list[dict]:
    """Every statutory gap on one employee, each naming what it blocks.

    `old_regime` comes from the employee's §192 intimation, not from this
    module: under §115BAC(1A) there is ONE slab ladder for every individual
    regardless of age, so a missing date of birth blocks nothing at all for the
    employees payroll withholds on by default. Reporting it for everyone would
    put a line against most of the roster that changes nothing, and a list
    nobody can act on is a list nobody reads.
    """
    out: list[dict] = []
    who = _s(emp, "name") or str(emp.get("id") or "employee")

    if emp.get("pf_applicable"):
        uan = _s(emp, "uan")
        if not uan or not UAN_RE.match(uan):
            out.append({
                "kind": "uan", "employee_id": emp.get("id"), "employee": who,
                "blocks": "EPFO ECR",
                "note": "No UAN, or one that is not 12 digits. The ECR is a "
                        "UAN-based format and refuses the member outright, so "
                        "this employee's PF cannot be remitted with the rest.",
            })

    if emp.get("esi_applicable"):
        if not _s(emp, "esi_number"):
            out.append({
                "kind": "esic_ip", "employee_id": emp.get("id"), "employee": who,
                "blocks": "ESIC contribution return",
                "note": "No ESIC insurance number. The return identifies every "
                        "employee by IP number and cannot carry this one.",
            })

    pan = _s(emp, "pan").upper()
    if not pan or not PAN_RE.match(pan):
        out.append({
            "kind": "pan", "employee_id": emp.get("id"), "employee": who,
            "blocks": "Form 24Q",
            "note": "No valid PAN. §206AA requires tax at the HIGHER of the "
                    "specified rate or 20% where PAN is not furnished, so a "
                    "deductee row at slab rates against no PAN declares a short "
                    "deduction — which §201(1) puts on the employer. The return "
                    "leaves the row out instead.",
        })

    if old_regime and age_domain.senior_status_unknown(emp.get("date_of_birth"), fy):
        out.append({
            "kind": "date_of_birth", "employee_id": emp.get("id"), "employee": who,
            "blocks": "§192 withholding (old regime)",
            "note": "On the old regime with no date of birth on file, so the "
                    "general slab ladder is used. Part III of the First Schedule "
                    "widens the nil band at 60 and again at 80; if this employee "
                    "is 60 or over they are being over-deducted every month.",
        })

    if not _s(emp, "bank_account_no") or not IFSC_RE.match(_s(emp, "bank_ifsc").upper()):
        out.append({
            "kind": "bank", "employee_id": emp.get("id"), "employee": who,
            "blocks": "Salary payment",
            "note": "No account number, or an IFSC that is not in the RBI "
                    "format. The salary cannot be paid by transfer.",
        })

    if emp.get("pt_applicable"):
        pt = classify_pt_state(emp.get("pt_state"))
        if pt.is_gap:
            out.append({
                "kind": "pt_state", "employee_id": emp.get("id"), "employee": who,
                "blocks": "Professional tax",
                "note": pt.note,
            })

    return out


def summarise(exceptions: list[dict]) -> dict:
    """How many employees each kind of gap affects.

    By EMPLOYEE, not by row: one person missing a PAN and a UAN is one person to
    chase, and counting them twice makes the roster look worse than it is.
    """
    by_kind: dict[str, set] = {}
    for e in exceptions:
        by_kind.setdefault(e["kind"], set()).add(e.get("employee_id") or e["employee"])
    return {kind: len(ids) for kind, ids in sorted(by_kind.items())}
