"""
Form 24Q Q4 Annexure II — the annual salary detail behind Form 16.

WHY THIS AND NOT A FORM 16 GENERATOR

Because a self-generated Form 16 cannot lawfully be issued. CBDT Notification
09/2019 of 06-05-2019 requires Part B of the salary TDS certificate to be
DOWNLOADED FROM TRACES for every deduction made on or after 01-04-2018 — Part A
had been TRACES-only for years already. An employer who prints their own Form 16
has issued nothing; the employee's certificate is the one TRACES generated.

And TRACES generates Part B from ONE input: Annexure II of the Q4 24Q return, in
the format Notification 36/2019 substituted. Get that wrong and the portal
refuses with "Data Available in 24Q Annexure II is not as per prescribed format
to generate Form 16 Part B", which is a fault the CA discovers in June with the
issue deadline days away.

So the useful thing to build — the thing that actually produces Form 16 — is a
correct Annexure II. This module builds it from the payslips already finalised
and posted for the year, and it computes no tax.

WHAT PAYROLL KNOWS, AND WHAT IT CANNOT

The salary side is ours: §17(1) salary from the year's payslips, §16(iii)
professional tax actually deducted, §16(ia) standard deduction from the
FY-versioned rates, and the tax actually deducted.

The rest belongs to the employee, not the employer's books:

  * §17(2) perquisites and §17(3) profits in lieu — not modelled anywhere in
    this payroll module.
  * exemptions under §10 — HRA under §10(13A) needs rent actually paid, LTA
    under §10(5) needs journeys actually taken. The payslip carries an HRA
    ALLOWANCE, which is not the same thing as an HRA exemption, and treating
    one as the other is the single most common way a Form 16 overstates relief.
  * Chapter VI-A — 80C, 80D and the rest are the employee's declarations with
    proofs behind them.
  * other income the employee reported to the employer under §192(2B).

None of that is invented here. Each is returned as an explicit gap naming what
is missing and who holds it, so the CA fills it in before filing Q4 rather than
discovering it when TRACES rejects the certificate.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")


@dataclass
class AnnexureIIRow:
    """One employee's annual salary detail.

    Every figure is in paise and every one of them came off a payslip, except
    the standard deduction, which is statutory.
    """
    employee_id: str
    name: str
    pan: str
    months_paid: int

    salary_17_1_paise: int              # §17(1) — salary as defined
    perquisites_17_2_paise: int = 0     # §17(2) — NOT modelled; see gaps
    profits_in_lieu_17_3_paise: int = 0  # §17(3) — NOT modelled; see gaps

    exempt_under_10_paise: int = 0      # §10 — employee's, see gaps
    standard_deduction_16_ia_paise: int = 0
    professional_tax_16_iii_paise: int = 0

    chapter_vi_a_paise: int = 0         # employee's declarations, see gaps
    tds_deducted_paise: int = 0

    @property
    def gross_salary_paise(self) -> int:
        return (self.salary_17_1_paise + self.perquisites_17_2_paise
                + self.profits_in_lieu_17_3_paise)

    @property
    def net_salary_paise(self) -> int:
        return self.gross_salary_paise - self.exempt_under_10_paise

    @property
    def income_under_salaries_paise(self) -> int:
        """§15-17 head total, after the §16 deductions. Floored at zero: the
        salary head cannot produce a loss."""
        return max(0, self.net_salary_paise
                   - self.standard_deduction_16_ia_paise
                   - self.professional_tax_16_iii_paise)


@dataclass
class AnnexureII:
    rows: list[AnnexureIIRow] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    @property
    def is_ready(self) -> bool:
        """Ready to FILE. Gaps do not block — they are things only the CA can
        supply, and an Annexure II with no Chapter VI-A is correct for an
        employee who declared none. Problems do block."""
        return bool(self.rows) and not self.problems

    def totals(self) -> dict:
        return {
            "employees": len(self.rows),
            "gross_salary_paise": sum(r.gross_salary_paise for r in self.rows),
            "income_under_salaries_paise": sum(r.income_under_salaries_paise for r in self.rows),
            "tds_paise": sum(r.tds_deducted_paise for r in self.rows),
        }


_SALARY_COMPONENTS = (
    "basic_paise", "hra_paise", "da_paise", "lta_paise", "medical_paise",
    "special_allowance_paise", "other_allowances_paise",
)


def build_annexure_ii(
    *,
    slips: list[dict],
    employees_by_id: dict[str, dict],
    standard_deduction_paise: int,
    months_expected: int = 12,
) -> AnnexureII:
    """Aggregate a financial year's finalised payslips into Annexure II rows.

    `slips` are every payroll_slips row for the year, across all twelve runs.
    """
    out = AnnexureII()
    by_emp: dict[str, list[dict]] = {}
    for s in slips:
        by_emp.setdefault(s.get("employee_id"), []).append(s)

    perquisites_possible = False

    for emp_id, emp_slips in sorted(by_emp.items(), key=lambda kv: str(kv[0])):
        emp = employees_by_id.get(emp_id) or {}
        name = (emp.get("name") or "").strip()
        label = name or emp_id or "unknown employee"

        pan = str(emp.get("pan") or "").strip().upper()
        if not PAN_RE.match(pan):
            out.problems.append(
                f"{label}: PAN {pan or 'missing'!r} is not valid. TRACES generates "
                f"Form 16 Part B against the PAN, so the certificate cannot be "
                f"issued at all without it."
            )
            continue

        # §17(1). Summed from the components rather than from gross_paise, so a
        # future component that is NOT salary (a reimbursement, say) cannot walk
        # into the salary figure just by being on the payslip.
        salary = sum(int(s.get(c) or 0) for s in emp_slips for c in _SALARY_COMPONENTS)
        pt = sum(int(s.get("pt_paise") or 0) for s in emp_slips)
        tds = sum(int(s.get("tds_paise") or 0) for s in emp_slips)

        if salary > 0:
            perquisites_possible = True

        out.rows.append(AnnexureIIRow(
            employee_id=str(emp_id),
            name=name.upper(),
            pan=pan,
            months_paid=len(emp_slips),
            salary_17_1_paise=salary,
            standard_deduction_16_ia_paise=min(standard_deduction_paise, salary),
            professional_tax_16_iii_paise=pt,
            tds_deducted_paise=tds,
        ))

        if len(emp_slips) < months_expected:
            out.gaps.append(
                f"{label}: {len(emp_slips)} months of payroll, not {months_expected}. "
                f"If they joined mid-year, salary from the PREVIOUS employer reported "
                f"under §192(2) belongs in this annexure and is not in these books."
            )

    if perquisites_possible:
        out.gaps.append(
            "§17(2) perquisites and §17(3) profits in lieu are recorded as nil for "
            "everyone, because this payroll module does not model them. Where a "
            "company car, accommodation, interest-free loan or ESOP applies, the "
            "value has to be added before Q4 is filed."
        )
        out.gaps.append(
            "Exemptions under §10 are nil for everyone. HRA under §10(13A) depends on "
            "rent ACTUALLY PAID and LTA under §10(5) on journeys actually taken — an "
            "HRA allowance on a payslip is not an HRA exemption, and treating one as "
            "the other is the commonest way a Form 16 overstates relief."
        )
        out.gaps.append(
            "Chapter VI-A deductions are nil for everyone. 80C, 80D and the rest are "
            "the employee's declarations with proofs behind them, which this system "
            "does not yet collect."
        )

    return out
