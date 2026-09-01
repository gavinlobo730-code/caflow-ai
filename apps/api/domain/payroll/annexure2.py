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
from typing import Optional

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

    # 24Q Annexure II carries "Whether opting for taxation u/s 115BAC" as a
    # field of its own, and every deduction above has to be consistent with it.
    # Defaults to the new regime because §115BAC(1A) is the default and an
    # employee who intimated nothing is withheld on that basis.
    uses_new_regime: bool = True

    @property
    def gross_salary_paise(self) -> int:
        return (self.salary_17_1_paise + self.perquisites_17_2_paise
                + self.profits_in_lieu_17_3_paise)

    @property
    def net_salary_paise(self) -> int:
        return self.gross_salary_paise - self.exempt_under_10_paise

    @property
    def allowable_professional_tax_paise(self) -> int:
        """§16(iii) professional tax, but only where the regime allows it.

        §115BAC(2)(i) computes total income without any deduction under section
        16 SAVE clause (ia) — the standard deduction, which Finance Act 2023 put
        back for the new regime. Clause (ii) entertainment allowance and clause
        (iii) professional tax stay excluded.

        This was claimed for everyone until now, and since payroll withholds on
        the new regime by default that meant it was claimed for everyone it was
        NOT available to. It understates income under the salary head, so the
        annexure disagrees with TRACES' own computation of Part B — a Form 16
        that is wrong in the employee's favour and traceable to the employer.
        """
        return 0 if self.uses_new_regime else self.professional_tax_16_iii_paise

    @property
    def income_under_salaries_paise(self) -> int:
        """§15-17 head total, after the §16 deductions. Floored at zero: the
        salary head cannot produce a loss."""
        return max(0, self.net_salary_paise
                   - self.standard_deduction_16_ia_paise
                   - self.allowable_professional_tax_paise)


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



def _verified_reliefs(decl, salary_17_1_paise: int) -> tuple:
    """(§10 exemptions, Chapter VI-A) a verified declaration supports.

    Reads only what the CA actually verified. An unverified declaration
    contributes nothing here even though it may have reduced withholding for the
    first three quarters — the two are different questions. Withholding is an
    estimate the year can still correct under §192(3); the annexure is the input
    to a certificate, and there is no correcting that after TRACES issues it.

    The regime gate is the same one the tax engine applies, restated in terms of
    the annexure's own columns rather than recomputed: under §115BAC(2) the new
    regime allows no §10(13A), no §10(5), and of Chapter VI-A only §80CCD(2).
    """
    from domain.payroll import declarations as _d

    if not getattr(decl, "proofs_verified", False):
        return 0, 0

    if decl.uses_new_regime:
        # §80CCD(2) is the one Chapter VI-A head that survives §115BAC(2) for a
        # salaried employee.
        return 0, decl.total_for(_d.SECTION_80CCD2, verified_only=True)

    hra_exempt = 0
    rent = decl.rent_paid(verified_only=True)
    if rent > 0:
        from domain.income_tax.itr_engine import HRADetails
        hra_exempt = HRADetails(
            basic_salary_paise=decl.hra_basic_plus_da_paise,
            hra_received_paise=decl.hra_received_paise,
            rent_paid_paise=rent,
            is_metro=decl.rent_is_metro,
        ).exemption_paise()
    lta_exempt = decl.lta_verified_paise if decl.proofs_verified else 0
    exempt_10 = min(hra_exempt + max(0, lta_exempt), salary_17_1_paise)

    chapter_vi_a = sum(
        decl.total_for(sec, verified_only=True) for sec in _d.VALID_SECTIONS)
    return exempt_10, chapter_vi_a


def build_annexure_ii(
    *,
    slips: list[dict],
    employees_by_id: dict[str, dict],
    standard_deduction_paise: int,
    months_expected: int = 12,
    declarations_by_employee: Optional[dict] = None,
    perquisites_by_employee: Optional[dict] = None,
    settlements_by_employee: Optional[dict] = None,
) -> AnnexureII:
    """Aggregate a financial year's finalised payslips into Annexure II rows.

    `slips` are every payroll_slips row for the year, across all twelve runs.

    `declarations_by_employee` maps employee id to a
    domain.payroll.declarations.Declaration. Where one exists it supplies the
    regime and the reliefs the employee claimed — which is how three of the four
    gaps below stop being gaps. Only VERIFIED figures are carried: an annexure
    is the input TRACES generates a certificate from, and a certificate resting
    on an unproved claim is the employer's exposure, not the employee's.
    """
    out = AnnexureII()
    by_emp: dict[str, list[dict]] = {}
    for s in slips:
        by_emp.setdefault(s.get("employee_id"), []).append(s)

    declarations_by_employee = declarations_by_employee or {}
    perquisites_by_employee = perquisites_by_employee or {}
    settlements_by_employee = settlements_by_employee or {}
    perquisites_possible = False
    any_undeclared = False
    any_unvalued_perquisites = False

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

        # A leaver's settlement is salary of the year of RECEIPT (§15) and
        # belongs in this annexure like any other month's pay — which, until it
        # was wired in, it did not: the settlement was computed, shown, and
        # never reached anyone's Form 16.
        #
        # Its components land on the line the statute puts them on rather than
        # all being lumped into §17(1): §17(1)(va) expressly makes a payment for
        # leave not availed SALARY, while gratuity is a termination payment and
        # sits under §17(3). The §10 exemptions come off separately, which is
        # what the annexure's own format asks for.
        settled = settlements_by_employee.get(emp_id) or {}
        salary += int(settled.get("gross_17_1_paise") or 0)
        profits_in_lieu = int(settled.get("gross_17_3_paise") or 0)
        exempt_10 = int(settled.get("exempt_paise") or 0)
        tds += int(settled.get("tds_paise") or 0)

        perquisite_value = sum(int(p.get("value_paise") or 0)
                               for p in perquisites_by_employee.get(emp_id, []))
        if salary > 0 and not perquisites_by_employee.get(emp_id):
            perquisites_possible = True
            any_unvalued_perquisites = True

        decl = declarations_by_employee.get(emp_id)
        if decl is None:
            any_undeclared = True
            uses_new_regime, chapter_vi_a = True, 0
        else:
            uses_new_regime = decl.uses_new_regime
            declared_exempt, chapter_vi_a = _verified_reliefs(decl, salary)
            exempt_10 += declared_exempt
            if not decl.proofs_verified:
                out.gaps.append(
                    f"{label}: a declaration exists but its proofs were never "
                    f"verified, so nothing from it is carried here. Verify it or "
                    f"file the annexure without it — a certificate resting on an "
                    f"unproved claim is the employer's exposure under §192(1)."
                )

        out.rows.append(AnnexureIIRow(
            employee_id=str(emp_id),
            name=name.upper(),
            pan=pan,
            months_paid=len(emp_slips),
            salary_17_1_paise=salary,
            profits_in_lieu_17_3_paise=profits_in_lieu,
            uses_new_regime=uses_new_regime,
            perquisites_17_2_paise=perquisite_value,
            exempt_under_10_paise=exempt_10,
            chapter_vi_a_paise=chapter_vi_a,
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

    if any_unvalued_perquisites:
        # Narrowed from "nil for everyone" to "nil for those with nothing
        # valued": perquisites are now computed under Rule 3 and stored
        # (migration 299), so an employee WITH a valuation is no longer a gap.
        out.gaps.append(
            "Some employees have no §17(2) perquisite valued for the year, so "
            "nil is reported for them. That is correct for anyone with no "
            "company car, accommodation, concessional loan or other benefit — "
            "and wrong for anyone who has one and was never valued. §17(3) "
            "profits in lieu are not modelled at all."
        )
    if any_undeclared:
        out.gaps.append(
            "Some employees filed no §192 declaration, so their §10 exemptions and "
            "Chapter VI-A deductions are nil here. That is the correct figure for "
            "someone who claimed nothing — and the wrong one for someone who simply "
            "was never asked. HRA under §10(13A) needs rent ACTUALLY PAID and LTA "
            "under §10(5) journeys actually taken; an HRA allowance on a payslip is "
            "not an HRA exemption, and treating one as the other is the commonest "
            "way a Form 16 overstates relief."
        )

    return out
