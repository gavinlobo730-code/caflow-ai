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
  employee?: Employee;
  run?: PayrollRun;
};

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
