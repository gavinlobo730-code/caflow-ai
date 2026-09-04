/**
 * Payroll types and helpers shared by the firm rail and the People screen.
 *
 * WHY THIS FILE EXISTS
 *
 * /payroll and /payroll/people are two pages over one roster. Everything below
 * lived in /payroll/page.tsx while there was only one page; copying it into the
 * second one is exactly how the salary register and the ECR each ended up
 * implemented twice, once per surface, with only one of them right.
 *
 * Nothing here computes a statutory figure. `employeeGrossPaise` is the single
 * calculation, it is a DISPLAY preview of the backend's gross, and its own
 * comment says so.
 */

// ── Types ──────────────────────────────────────────────────────────────────

export type Client = { id: string; client_name: string };

export type Employee = {
  // Set by the portal invite flow (migration 264); absent on older rows.
  portal_enabled?: boolean;
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
  // Optional fixed components — this page's Add-Employee form doesn't capture
  // them, but an employee created via the per-client payroll page can carry
  // them, and the backend slip folds all of them into gross. Included here so
  // the on-screen CTC preview matches the computed slip for every employee.
  lta_paise?: number;
  medical_paise?: number;
  special_allowance_paise?: number;
  pf_applicable: boolean;
  esi_applicable: boolean;
  pt_applicable?: boolean;
  pt_state?: string | null;
  gender?: string | null;
  // 'active' | 'resigned' | 'terminated' (payroll_employees.status). Absent on
  // rows created before the roster started returning it — treat as active.
  status?: string;
  // The statutory identifiers. All have existed on payroll_employees and in
  // EmployeeIn for some time; nothing collected them, so three finished
  // statutory builders had no way to be fed.
  uan?: string | null;
  esi_number?: string | null;
  joining_date?: string | null;
  department?: string | null;
  bank_account_no?: string | null;
  bank_ifsc?: string | null;
  bank_name?: string | null;
};

export type PayrollRun = {
  id: string;
  firm_id: string;
  client_id: string;
  month: string;
  status: string;
  generated_at: string;
  total_gross_paise?: number;
  total_net_paise?: number;
  /** Migration 329. EDLI and the EPF administrative charge are employer costs
   *  OUTSIDE the 12%, and the admin charge is floored at ₹500 per
   *  ESTABLISHMENT per month — so the figure owed is a property of the RUN and
   *  cannot be reconstructed by adding up payslips. Three members at ₹60 each
   *  owe ₹500, not ₹180. */
  total_edli_paise?: number;
  total_pf_admin_paise?: number;
  headcount?: number;
  paid_at?: string | null;
  payment_reference?: string | null;
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
  // The EMPLOYER side, stored on the slip by the run (migration 295 and its
  // neighbours) rather than recomputed anywhere. The EPS share is capped on its
  // OWN ceiling and EPF absorbs the rest, EDLI and the admin charge are the
  // employer's other two EPF costs, and all of it is what posted to the ledger.
  // A screen that recalculated any of it would be a second implementation of a
  // statutory split — which is exactly what this page used to be.
  pf_employer_paise?: number;
  pf_employer_eps_paise?: number;
  pf_employer_epf_paise?: number;
  edli_paise?: number;
  pf_admin_paise?: number;
  esi_employer_paise?: number;
  employee?: Employee;
  run?: PayrollRun;
};
// ── Paise helpers ─────────────────────────────────────────────────────────

export function fmtRs(paise: number): string {
  const rupees = Math.floor(paise / 100);
  const p = paise % 100;
  return `₹${rupees.toLocaleString("en-IN")}.${p.toString().padStart(2, "0")}`;
}

/* rsToP — `Math.round(rs * 100)` — was deleted on 2026-09-04 along with its
 * last caller. It is the second half of the forbidden form: parseFloat turns
 * "1,25,000" into 1, and this turned the 1 into 100 paise without complaint.
 * paiseFromRupeeInput builds the paise digit string instead and never
 * multiplies, so there is nothing here to bring back.
 */

/** Pull a readable message out of a thrown API error. `request()` throws
 *  `API error 409: {"detail":"…"}` on non-2xx; surface the detail, not the noise. */
export function apiErr(e: unknown, fallback: string): string {
  if (!(e instanceof Error)) return fallback;
  const m = e.message.match(/API error \d+:\s*([\s\S]*)$/);
  if (m) {
    try {
      const j = JSON.parse(m[1]);
      if (j && typeof j.detail === "string") return j.detail;
    } catch { /* not JSON — fall through to raw text */ }
    return m[1].trim() || fallback;
  }
  return e.message || fallback;
}

/** Monthly gross CTC for an employee, in integer paise. Mirrors the backend
 *  slip's gross = basic + HRA + DA + LTA + medical + special + other (any
 *  component not captured on this page is absent → treated as 0). */
export function employeeGrossPaise(emp: Employee): number {
  return (
    emp.basic_paise +
    Math.round((emp.basic_paise * emp.hra_percent) / 100) +
    Math.round((emp.basic_paise * emp.da_percent) / 100) +
    (emp.lta_paise ?? 0) +
    (emp.medical_paise ?? 0) +
    (emp.special_allowance_paise ?? 0) +
    emp.other_allowances_paise
  );
}

// Professional Tax states this build knows a slab for — must stay in sync
// with routers/payroll.py's _PT_SLABS_BY_STATE (the sole source of truth for
// PT computation; the frontend no longer computes PT itself — see R2.10).
export const PT_STATES = [
  { code: "NONE", label: "No Professional Tax" },
  { code: "MH", label: "Maharashtra — Rs 175/200/mo (Feb Rs 300); women ≤ Rs 25k exempt" },
  { code: "KA", label: "Karnataka — Rs 200/month if ≥ Rs 25,000" },
  { code: "WB", label: "West Bengal — Rs 110–200/month slab (> Rs 10,000)" },
  { code: "TN", label: "Tamil Nadu — half-yearly (Chennai), deducted Sep & Mar" },
];

/* EMPLOYEE_IMPORT_COLUMNS is deliberately NOT here.
 *
 * The rail used to carry its own list — `basic_rs`, no `employee_code`, keys
 * that no longer match anything — beside the one in lib/imports/mappers.ts that
 * MIRRORS domain/payroll/employee_import.COLUMNS and is held to it by a parity
 * test. Two lists for one importer is the fault this whole module has been
 * unpicking; moving the stale one into a shared file would have preserved it.
 *
 * The People screen composes the real list instead: the server-mirrored columns
 * plus `client_name`, which only the firm-wide roster needs because it spans
 * clients (the per-client import takes a client_id parameter and has nothing to
 * resolve). See app/payroll/people/page.tsx.
 */

