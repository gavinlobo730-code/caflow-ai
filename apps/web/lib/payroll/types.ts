/**
 * The payroll shapes the firm-level report screens read.
 *
 * Declared here rather than inside a page because lib/payroll/useSlips.ts and
 * app/payroll/reports both need them, and a type declared twice is two types
 * that drift — the fetch and the table would then disagree about which fields
 * a payslip has, silently, since TypeScript happily structurally-matches two
 * copies until one of them gains a field.
 */

export type Employee = {
  id: string;
  firm_id: string;
  client_id: string;
  name: string;
  pan: string;
  designation: string;
  basic_paise: number;
  hra_percent: number;
  da_percent: number;
  other_allowances_paise: number;
  pf_applicable: boolean;
  esi_applicable: boolean;
};

export type PayrollRun = {
  id: string;
  firm_id: string;
  client_id: string;
  /** "YYYY-MM" */
  month: string;
  status: string;
  generated_at: string;
  financial_year?: string | null;
};

export type PayrollSlip = {
  id: string;
  run_id: string;
  employee_id: string;
  gross_paise: number;
  pf_employee_paise: number;
  esi_employee_paise: number;
  pt_paise: number;
  tds_paise: number;
  net_paise: number;
  /**
   * THE EMPLOYER'S SIDE, computed and stored by the server (PAY-09).
   *
   * These are the figures the payslip, the ledger and the PF challan carry.
   * They are on the row and were simply not read: the CTC report re-derived
   * employer PF as 12% of BASIC — ignoring DA, ignoring the Code on Social
   * Security s.2(88) wage base (migration 334) and ignoring `eps_eligible` —
   * and ESI from a current-month ceiling test with no contribution period
   * (Rule 50), while omitting EDLI and the admin charge that migration 329
   * established are part of what the employer pays.
   *
   * Optional because `/api/payroll/slips` selects `*` and older fixtures do
   * not carry them; `employerCostOf` is the one place that decides what a
   * missing one means.
   */
  pf_employer_paise?: number;
  esi_employer_paise?: number;
  edli_paise?: number;
  pf_admin_paise?: number;
  employee?: Employee;
  run?: PayrollRun;
};

/**
 * What this slip costs the employer beyond the gross, in integer paise.
 *
 * ONE function, and it does no arithmetic on wages at all — it ADDS figures the
 * server already computed. That is the whole point of PAY-09: every attempt to
 * re-derive employer PF or ESI in the browser has been wrong, because the base
 * is not the basic (s.2(88)), the EPS split is not a percentage of it
 * (GSR 609(E) excludes some employees), and the ESI ceiling test is not about
 * this month (Rule 50 fixes it for the contribution period).
 */
export function employerCostOf(s: PayrollSlip): {
  pf: number; esi: number; edli: number; admin: number; total: number;
} {
  const pf = s.pf_employer_paise ?? 0;
  const esi = s.esi_employer_paise ?? 0;
  const edli = s.edli_paise ?? 0;
  const admin = s.pf_admin_paise ?? 0;
  return { pf, esi, edli, admin, total: pf + esi + edli + admin };
}

/** One employee's whole financial year, aggregated BY THE SERVER.
 *  The year-end tab used to build this in the browser from every payslip the
 *  firm had ever produced — a hundred employees over twelve months is 1,200
 *  rows to render a hundred. */
export type EmployeeYearTotals = {
  employee_id: string;
  employee: Pick<Employee, "name" | "pan" | "designation"> | null;
  months: number;
  gross_paise: number;
  net_paise: number;
  tds_paise: number;
  pt_paise: number;
  pf_employee_paise: number;
  esi_employee_paise: number;
};
