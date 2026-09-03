"use client";

/**
 * Payroll Module — IT Act Section 192 (TDS on Salary), ESI Act, EPF Act
 * All monetary values stored and computed in integer paise.
 */

import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { useState, useEffect, useCallback, useMemo } from "react";
import Link from "next/link";
import {
  Users, Play, FileText, Shield, Plus, X, AlertCircle,
  Download, CheckCircle, Clock, AlertTriangle, BarChart2, Upload,
  Pencil, Ban, Trash2, RotateCcw, Receipt,
} from "lucide-react";
import CsvImportModal, { type ImportRow } from "@/components/CsvImportModal";
import { DataTable, exportSelectedAction } from "@/components/ui/data-table";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import type { Column, FilterDef, BulkAction } from "@/lib/table/types";
import { formatPaise } from "@/lib/services/formatting";
import { toLocalISO } from "@/lib/dateMath";
import { useToast } from "@/components/ui/use-toast";

const EMPLOYEE_IMPORT_COLUMNS = [
  { key: "name",                    label: "Employee Name",       required: true,  hint: "e.g. Ramesh Kumar" },
  { key: "pan",                     label: "PAN",                 required: true,  hint: "e.g. AABCU9603R" },
  { key: "designation",             label: "Designation",         required: false, hint: "e.g. Senior Associate" },
  { key: "gender",                  label: "Gender",              required: false, hint: "Male | Female | Other (for MH PT)" },
  { key: "client_name",             label: "Client Name",         required: true,  hint: "Must match existing client" },
  { key: "basic_rs",                label: "Basic Salary (₹/mo)", required: true,  hint: "e.g. 30000" },
  { key: "hra_percent",             label: "HRA %",               required: false, hint: "e.g. 40" },
  { key: "da_percent",              label: "DA %",                required: false, hint: "e.g. 0" },
  { key: "other_allowances_rs",     label: "Other Allow. (₹/mo)",required: false, hint: "e.g. 5000" },
  { key: "pf_applicable",           label: "PF Applicable",       required: false, hint: "true | false" },
  { key: "esi_applicable",          label: "ESI Applicable",      required: false, hint: "true | false" },
  { key: "pt_state",                label: "PT State",            required: false, hint: "MH | KA | WB | TN | blank" },
];
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { api, type ApiResp } from "@/lib/api";

// ── Types ──────────────────────────────────────────────────────────────────

type Client = { id: string; client_name: string };

type Employee = {
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
};

type PayrollRun = {
  id: string;
  firm_id: string;
  client_id: string;
  month: string;
  status: string;
  generated_at: string;
  total_gross_paise?: number;
  total_net_paise?: number;
  headcount?: number;
  paid_at?: string | null;
  payment_reference?: string | null;
};

type PayrollSlip = {
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

function fmtRs(paise: number): string {
  const rupees = Math.floor(paise / 100);
  const p = paise % 100;
  return `₹${rupees.toLocaleString("en-IN")}.${p.toString().padStart(2, "0")}`;
}

function rsToP(rs: number): number {
  return Math.round(rs * 100);
}

/** Pull a readable message out of a thrown API error. `request()` throws
 *  `API error 409: {"detail":"…"}` on non-2xx; surface the detail, not the noise. */
function apiErr(e: unknown, fallback: string): string {
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
function employeeGrossPaise(emp: Employee): number {
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
const PT_STATES = [
  { code: "NONE", label: "No Professional Tax" },
  { code: "MH", label: "Maharashtra — Rs 175/200/mo (Feb Rs 300); women ≤ Rs 25k exempt" },
  { code: "KA", label: "Karnataka — Rs 200/month if ≥ Rs 25,000" },
  { code: "WB", label: "West Bengal — Rs 110–200/month slab (> Rs 10,000)" },
  { code: "TN", label: "Tamil Nadu — half-yearly (Chennai), deducted Sep & Mar" },
];

// ── Statutory Returns helpers ─────────────────────────────────────────────

/**
 * Given today's date, compute the list of statutory return deadlines
 * relevant for the current month/quarter.
 *
 * PF ECR: monthly, due 15th of following month (EPF Act)
 * ESI Return: half-yearly (Apr-Sep → Nov 11; Oct-Mar → May 11)
 * PT: monthly challan (Maharashtra example)
 * TDS 24Q: quarterly (IT Act Section 192)
 *   Q1 Apr-Jun → 31 Jul | Q2 Jul-Sep → 31 Oct | Q3 Oct-Dec → 31 Jan | Q4 Jan-Mar → 31 May
 */
function getStatutoryDeadlines(today: Date): {
  id: string;
  label: string;
  description: string;
  dueDate: Date;
  status: "overdue" | "due-soon" | "upcoming";
  portal: string;
}[] {
  const y = today.getFullYear();
  const m = today.getMonth(); // 0-indexed

  const deadlines = [];

  // PF ECR — due 15th of current month for prior month
  const pfMonth = m === 0 ? 11 : m - 1;
  const pfYear = m === 0 ? y - 1 : y;
  const pfDue = new Date(y, m, 15);
  const pfMonthName = new Date(pfYear, pfMonth, 1).toLocaleString("en-IN", { month: "long", year: "numeric" });
  deadlines.push({
    id: "pf-ecr",
    label: `PF ECR — ${pfMonthName}`,
    description: "Electronic Challan cum Return — EPFO Unified Portal",
    dueDate: pfDue,
    status: getDueDateStatus(pfDue, today),
    portal: "EPFO Unified Portal",
  });

  // ESI Return — half-yearly
  // Apr-Sep period → due Nov 11; Oct-Mar period → due May 11
  let esiDue: Date;
  let esiPeriod: string;
  if (m >= 3 && m <= 8) {
    // Apr–Sep period, due Nov 11 this year
    esiDue = new Date(y, 10, 11);
    esiPeriod = `Apr–Sep ${y}`;
  } else if (m >= 9) {
    // Oct–Dec, due May 11 next year
    esiDue = new Date(y + 1, 4, 11);
    esiPeriod = `Oct ${y}–Mar ${y + 1}`;
  } else {
    // Jan–Mar, due May 11 this year
    esiDue = new Date(y, 4, 11);
    esiPeriod = `Oct ${y - 1}–Mar ${y}`;
  }
  deadlines.push({
    id: "esi-return",
    label: `ESI Return — ${esiPeriod}`,
    description: "Half-yearly return — ESIC Portal (employees ≤ ₹21,000/month)",
    dueDate: esiDue,
    status: getDueDateStatus(esiDue, today),
    portal: "ESIC Portal",
  });

  // PT Challan — monthly, due by end of current month (state-dependent; showing general)
  const ptDue = new Date(y, m + 1, 0); // last day of current month
  deadlines.push({
    id: "pt-challan",
    label: `Professional Tax — ${today.toLocaleString("en-IN", { month: "long", year: "numeric" })}`,
    description: "Monthly PT challan — State treasury (Maharashtra: ₹200 if salary > ₹10,000)",
    dueDate: ptDue,
    status: getDueDateStatus(ptDue, today),
    portal: "State Treasury Portal",
  });

  // TDS 24Q — quarterly (IT Act Section 192)
  // Q1: Apr-Jun → 31 Jul | Q2: Jul-Sep → 31 Oct | Q3: Oct-Dec → 31 Jan | Q4: Jan-Mar → 31 May
  let tdsQuarter: string;
  let tdsDue: Date;
  if (m >= 3 && m <= 5) {
    tdsQuarter = `Q1 Apr–Jun ${y}`;
    tdsDue = new Date(y, 6, 31);
  } else if (m >= 6 && m <= 8) {
    tdsQuarter = `Q2 Jul–Sep ${y}`;
    tdsDue = new Date(y, 9, 31);
  } else if (m >= 9 && m <= 11) {
    tdsQuarter = `Q3 Oct–Dec ${y}`;
    tdsDue = new Date(y + 1, 0, 31);
  } else {
    tdsQuarter = `Q4 Jan–Mar ${y}`;
    tdsDue = new Date(y, 4, 31);
  }
  deadlines.push({
    id: "tds-24q",
    label: `TDS 24Q — ${tdsQuarter}`,
    description: "Quarterly TDS return on salary — IT Act Section 192 — filed on the e-filing portal (incometax.gov.in)",
    dueDate: tdsDue,
    status: getDueDateStatus(tdsDue, today),
    portal: "e-filing portal (incometax.gov.in)",
  });

  return deadlines;
}

function getDueDateStatus(
  due: Date,
  today: Date,
): "overdue" | "due-soon" | "upcoming" {
  const diffMs = due.getTime() - today.getTime();
  const diffDays = Math.ceil(diffMs / (1000 * 60 * 60 * 24));
  if (diffDays < 0) return "overdue";
  if (diffDays <= 7) return "due-soon";
  return "upcoming";
}

/* The EPFO ECR and the ESIC return were BUILT HERE, in the browser, until
 * 2026-09-04. Both are now server-built — api.payroll.runEcr / runEsic, backed
 * by domain/payroll/{ecr,esic}.py.
 *
 * They are not coming back. The browser versions hardcoded NCP_DAYS to 0, put
 * PAN (or a fabricated "EMP0001") in the MEMBER_ID field that wants a UAN,
 * computed EPF wages on basic alone where EPF Act s.6 says basic + DA, and
 * decided ESI eligibility from the current month's gross instead of the Rule 50
 * contribution period — every one of them a rule the backend had already fixed.
 * CLAUDE.md's "zero business logic in the frontend" exists for exactly this: a
 * statutory remittance file is the last place a second implementation belongs.
 */

/**
 * Generate TDS 24Q summary CSV.
 * IT Act Section 192 — TDS on salary.
 * # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
 */
function generateTds24QData(slips: PayrollSlip[], quarter: string): string {
  // # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
  const header = `# TDS 24Q Summary — ${quarter}\n# IT Act Section 192 — TDS on Salary\n# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT\n# This data must be reviewed and filed on the e-filing portal (incometax.gov.in) by a qualified CA\n`;
  const csvHeader = "Employee Name,PAN,Designation,Gross Salary (Rs),TDS Deducted (Rs),Quarter";
  const rows = slips.map(s => {
    const emp = s.employee!;
    const grossRs = (s.gross_paise / 100).toFixed(2);
    const tdsRs = (s.tds_paise / 100).toFixed(2);
    return `"${emp.name}","${emp.pan || "PAN NOT AVAILABLE"}","${emp.designation || ""}",${grossRs},${tdsRs},"${quarter}"`;
  });
  const totalGross = slips.reduce((sum, s) => sum + s.gross_paise, 0);
  const totalTds = slips.reduce((sum, s) => sum + s.tds_paise, 0);
  const footer = `"TOTAL","","",${(totalGross / 100).toFixed(2)},${(totalTds / 100).toFixed(2)},""`;
  return [header, csvHeader, ...rows, footer].join("\n");
}

function downloadFile(content: string, filename: string, mimeType: string) {
  // BOM only for CSV: PF ECR is a fixed-format government text upload where
  // extra bytes would break parsing, so it must stay BOM-free.
  const body = mimeType.startsWith("text/csv") ? "\uFEFF" + content : content;
  const blob = new Blob([body], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** Determine the TDS 24Q quarter label for a given YYYY-MM month string */
function getTdsQuarterLabel(month: string): string {
  const [y, m] = month.split("-").map(Number);
  if (m >= 4 && m <= 6) return `Q1 Apr–Jun ${y}`;
  if (m >= 7 && m <= 9) return `Q2 Jul–Sep ${y}`;
  if (m >= 10 && m <= 12) return `Q3 Oct–Dec ${y}`;
  return `Q4 Jan–Mar ${y}`;
}

// ── Employee Portal access modal ───────────────────────────────────────────
// The activation link comes back ONCE, from this call. Only its sha256 is
// stored server-side, so it can never be fetched again — which is why the link
// is shown here for copying, not just emailed and forgotten. Re-inviting mints
// a fresh link and invalidates this one.
function PortalAccessModal({ employee, onClose, onChanged }: {
  employee: Employee;
  onClose: () => void;
  onChanged: (msg: string) => void;
}) {
  const [status, setStatus] = useState<{ activated: boolean; invite_pending: boolean;
                                         email: string | null } | null>(null);
  const [email, setEmail] = useState("");
  const [link, setLink] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const res = await api.payroll.portalStatus(employee.id);
        const d = res.data;
        if (d) { setStatus(d); setEmail(d.email ?? ""); }
      } catch (e) {
        setErr(e instanceof Error ? e.message : "Couldn't read portal status.");
      }
    })();
  }, [employee.id]);

  async function invite() {
    setBusy(true); setErr(null);
    try {
      const res = await api.payroll.invitePortal(employee.id, email.trim());
      setLink(res.data?.activation_url ?? null);
      onChanged(`Invitation sent to ${email.trim()}.`);
      setStatus((s) => s ? { ...s, invite_pending: true, email: email.trim() } : s);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Couldn't send the invitation.");
    } finally { setBusy(false); }
  }

  async function revoke() {
    if (!confirm(`Remove portal access for ${employee.name}? They will no longer be able to sign in and view their payslips. You can invite them again later.`)) return;
    setBusy(true); setErr(null);
    try {
      await api.payroll.revokePortal(employee.id);
      onChanged(`Portal access removed for ${employee.name}.`);
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Couldn't remove access.");
    } finally { setBusy(false); }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl w-full max-w-lg p-5">
        <h2 className="font-semibold text-[#0F172A]">Payslip portal — {employee.name}</h2>
        <p className="text-sm text-[#64748B] mt-1 mb-4">
          Lets this employee sign in and see their own payslips and leave
          balance. They see nothing else.
        </p>

        {err && <p className="text-sm text-red-600 mb-3">{err}</p>}

        {status?.activated ? (
          <div>
            <p className="text-sm text-green-700 mb-4">Portal access is active.</p>
            <div className="flex gap-2">
              <Button variant="outline" onClick={onClose}>Close</Button>
              <Button onClick={revoke} disabled={busy}
                      className="bg-red-600 hover:bg-red-700 text-white">
                {busy ? "Removing…" : "Remove access"}
              </Button>
            </div>
          </div>
        ) : link ? (
          <div>
            <p className="text-sm text-[#475569] mb-2">
              Invitation sent. If the email does not arrive, share this link —
              it works once and expires in 14 days.
            </p>
            <div className="flex gap-2 mb-4">
              <input readOnly value={link}
                     className="flex-1 border border-[#E2E8F0] rounded-lg px-3 py-2 text-xs font-mono" />
              <Button variant="outline" onClick={() => {
                navigator.clipboard?.writeText(link);
                setCopied(true);
                setTimeout(() => setCopied(false), 2000);
              }}>{copied ? "Copied" : "Copy"}</Button>
            </div>
            <Button onClick={onClose}>Done</Button>
          </div>
        ) : (
          <div>
            <label className="block text-xs font-medium text-[#475569] mb-1">
              Their email address *
            </label>
            <input value={email} onChange={(e) => setEmail(e.target.value)}
                   placeholder="name@example.com" type="email"
                   className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm mb-1" />
            {status?.invite_pending && (
              <p className="text-xs text-amber-700 mb-2">
                An invitation is already pending. Sending again replaces it —
                the earlier link stops working.
              </p>
            )}
            <div className="flex gap-2 mt-3">
              <Button variant="outline" onClick={onClose}>Cancel</Button>
              <Button onClick={invite} disabled={busy || !email.trim().includes("@")}>
                {busy ? "Sending…" : status?.invite_pending ? "Send a new invitation" : "Send invitation"}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Add Employee Modal ────────────────────────────────────────────────────

function AddEmployeeModal({
  clients,
  employee,
  onClose,
  onSaved,
}: {
  clients: Client[];
  employee?: Employee | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEdit = !!employee;
  const [form, setForm] = useState({
    client_id: employee?.client_id ?? clients[0]?.id ?? "",
    name: employee?.name ?? "",
    pan: employee?.pan ?? "",
    gender: employee?.gender ?? "",
    designation: employee?.designation ?? "",
    basic_rs: employee ? String(employee.basic_paise / 100) : "",
    hra_percent: employee ? String(employee.hra_percent ?? 0) : "40",
    da_percent: employee ? String(employee.da_percent ?? 0) : "10",
    other_rs: employee ? String((employee.other_allowances_paise ?? 0) / 100) : "0",
    pf_applicable: employee?.pf_applicable ?? false,
    esi_applicable: employee?.esi_applicable ?? false,
    pt_state: employee?.pt_applicable ? (employee.pt_state ?? "NONE") : "NONE",
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  async function save() {
    if (!form.name || !form.basic_rs) { setErr("Name and Basic Salary are required."); return; }
    setSaving(true);
    setErr("");
    try {
      const payload = {
        name: form.name,
        pan: form.pan.toUpperCase() || null,
        gender: form.gender || null,
        designation: form.designation || null,
        basic_paise: rsToP(parseFloat(form.basic_rs) || 0),
        hra_percent: parseFloat(form.hra_percent) || 0,
        da_percent: parseFloat(form.da_percent) || 0,
        other_allowances_paise: rsToP(parseFloat(form.other_rs) || 0),
        pf_applicable: form.pf_applicable,
        esi_applicable: form.esi_applicable,
        // Professional Tax — state-specific slab, computed server-side (R2.10).
        pt_applicable: form.pt_state !== "NONE",
        pt_state: form.pt_state === "NONE" ? null : form.pt_state,
      };
      if (isEdit && employee) {
        // client_id can't change on edit (EmployeeUpdateIn has no client_id).
        await api.payroll.updateEmployee(employee.id, payload);
      } else {
        await api.payroll.createEmployee({ client_id: form.client_id, ...payload });
      }
      onSaved();
    } catch (e) {
      setErr(e instanceof Error ? e.message : `Failed to ${isEdit ? "update" : "add"} employee.`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0F172A]/60">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-[#0F172A]">{isEdit ? "Edit Employee" : "Add Employee"}</h2>
          <button onClick={onClose}><X size={16} /></button>
        </div>
        {err && <p className="text-red-600 text-sm mb-3">{err}</p>}
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2">
            <label className="block text-xs font-medium text-[#334155] mb-1">Client</label>
            {isEdit ? (
              <div className="w-full border rounded-lg px-3 py-2 text-sm bg-[#F8FAFC] text-[#64748B]">
                {clients.find(c => c.id === form.client_id)?.client_name ?? "—"}
              </div>
            ) : (
              <div className="w-full">
                <ClientLookup
                  clients={clients}
                  value={form.client_id}
                  onChange={(id) => setForm(f => ({ ...f, client_id: id }))}
                  ariaLabel="Client"
                  placeholder="Select client…"
                />
              </div>
            )}
          </div>
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">Name *</label>
            <input className="w-full border rounded-lg px-3 py-2 text-sm" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
          </div>
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">PAN</label>
            <input className="w-full border rounded-lg px-3 py-2 text-sm uppercase" value={form.pan} onChange={e => setForm(f => ({ ...f, pan: e.target.value }))} maxLength={10} />
          </div>
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">Designation</label>
            <input className="w-full border rounded-lg px-3 py-2 text-sm" value={form.designation} onChange={e => setForm(f => ({ ...f, designation: e.target.value }))} />
          </div>
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">Gender</label>
            <select className="w-full border rounded-lg px-3 py-2 text-sm" value={form.gender} onChange={e => setForm(f => ({ ...f, gender: e.target.value }))}>
              <option value="">Not specified</option>
              <option value="male">Male</option>
              <option value="female">Female</option>
              <option value="other">Other</option>
            </select>
            <p className="text-[10px] text-[#94A3B8] mt-1">Used for Maharashtra PT — women earning ≤ ₹25,000/month are exempt.</p>
          </div>
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">Basic Salary (Rs/month) *</label>
            <input type="number" className="w-full border rounded-lg px-3 py-2 text-sm" value={form.basic_rs} onChange={e => setForm(f => ({ ...f, basic_rs: e.target.value }))} />
          </div>
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">HRA %</label>
            <input type="number" className="w-full border rounded-lg px-3 py-2 text-sm" value={form.hra_percent} onChange={e => setForm(f => ({ ...f, hra_percent: e.target.value }))} />
          </div>
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">DA %</label>
            <input type="number" className="w-full border rounded-lg px-3 py-2 text-sm" value={form.da_percent} onChange={e => setForm(f => ({ ...f, da_percent: e.target.value }))} />
          </div>
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">Other Allowances (Rs)</label>
            <input type="number" className="w-full border rounded-lg px-3 py-2 text-sm" value={form.other_rs} onChange={e => setForm(f => ({ ...f, other_rs: e.target.value }))} />
          </div>
          <div className="flex items-center gap-2">
            <input type="checkbox" id="pf" checked={form.pf_applicable} onChange={e => setForm(f => ({ ...f, pf_applicable: e.target.checked }))} />
            <label htmlFor="pf" className="text-sm text-[#334155]">PF Applicable (12% of basic)</label>
          </div>
          <div className="flex items-center gap-2">
            <input type="checkbox" id="esi" checked={form.esi_applicable} onChange={e => setForm(f => ({ ...f, esi_applicable: e.target.checked }))} />
            <label htmlFor="esi" className="text-sm text-[#334155]">ESI Applicable (if &le; Rs 21,000)</label>
          </div>
          <div className="col-span-2">
            <label className="block text-xs font-medium text-[#334155] mb-1">Professional Tax (state)</label>
            <select className="w-full border rounded-lg px-3 py-2 text-sm" value={form.pt_state} onChange={e => setForm(f => ({ ...f, pt_state: e.target.value }))}>
              {PT_STATES.map(s => <option key={s.code} value={s.code}>{s.label}</option>)}
            </select>
          </div>
        </div>
        <div className="flex gap-2 justify-end mt-5">
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={save} disabled={saving}>{saving ? "Saving..." : isEdit ? "Update Employee" : "Add Employee"}</Button>
        </div>
      </div>
    </div>
  );
}

// ── Payslip Modal ─────────────────────────────────────────────────────────

function PayslipModal({ slip, onClose }: { slip: PayrollSlip; onClose: () => void }) {
  const emp = slip.employee!;
  const run = slip.run!;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0F172A]/60">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6">
        <div className="flex justify-between items-center mb-4">
          <h2 className="font-semibold">Payslip</h2>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={() => window.print()}>Print</Button>
            <button onClick={onClose}><X size={16} /></button>
          </div>
        </div>
        <div className="border-b pb-3 mb-3">
          <h3 className="font-bold text-lg text-[#0F172A]">{emp.name}</h3>
          <p className="text-sm text-[#475569]">{emp.designation} {emp.pan ? `• ${emp.pan}` : ""}</p>
          <p className="text-sm text-[#475569]">Month: {run.month}</p>
        </div>
        <table className="w-full text-sm">
          <tbody>
            <tr className="border-b">
              <td className="py-1 text-[#475569]">Gross Salary</td>
              <td className="py-1 text-right font-medium">{fmtRs(slip.gross_paise)}</td>
            </tr>
            <tr>
              <td className="py-1 text-[#475569]">PF Deduction (12% of Basic)</td>
              <td className="py-1 text-right text-red-600">- {fmtRs(slip.pf_employee_paise)}</td>
            </tr>
            <tr>
              <td className="py-1 text-[#475569]">ESI Deduction (0.75%)</td>
              <td className="py-1 text-right text-red-600">- {fmtRs(slip.esi_employee_paise)}</td>
            </tr>
            <tr>
              <td className="py-1 text-[#475569]">Professional Tax</td>
              <td className="py-1 text-right text-red-600">- {fmtRs(slip.pt_paise)}</td>
            </tr>
            <tr className="border-b">
              <td className="py-1 text-[#475569]">TDS on Salary (IT Act Sec 192)</td>
              <td className="py-1 text-right text-red-600">- {fmtRs(slip.tds_paise)}</td>
            </tr>
            <tr className="font-bold">
              <td className="py-2 text-[#0F172A]">Net Pay</td>
              <td className="py-2 text-right text-green-700">{fmtRs(slip.net_paise)}</td>
            </tr>
          </tbody>
        </table>
        <p className="text-[10px] text-[#94A3B8] mt-4 text-center">Generated by PracticeSync AI</p>
      </div>
    </div>
  );
}

// ── Statutory Returns Tab ─────────────────────────────────────────────────

function StatusBadge({ status }: { status: "overdue" | "due-soon" | "upcoming" | "filed" }) {
  if (status === "overdue") {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700">
        <AlertTriangle size={11} />Overdue
      </span>
    );
  }
  if (status === "due-soon") {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-700">
        <Clock size={11} />Due Soon
      </span>
    );
  }
  if (status === "filed") {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700">
        <CheckCircle size={11} />Filed
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-[#F1F5F9] text-[#475569]">
      <Clock size={11} />Upcoming
    </span>
  );
}

function StatutoryReturnsTab({
  runs,
  slips,
  clients,
}: {
  runs: PayrollRun[];
  slips: PayrollSlip[];
  clients: Client[];
}) {
  const today = new Date();
  const deadlines = getStatutoryDeadlines(today);

  // Group runs by client for the "Generate" section
  const [selectedClientId, setSelectedClientId] = useState(clients[0]?.id ?? "");
  const [statutoryBusy, setStatutoryBusy] = useState<string | null>(null);
  const { toast } = useToast();

  const clientRuns = runs.filter(r => r.client_id === selectedClientId);

  function slipsForRun(runId: string): PayrollSlip[] {
    return slips.filter(s => s.run_id === runId);
  }

  /** Ask the SERVER for the statutory file, and let its refusal reach the CA.
   *
   *  The endpoint returns the text alongside `problems` and `filable` rather
   *  than a download, because a member the file cannot carry — no UAN, a
   *  ceiling breached, a zero-wage ESIC member with no reason code — has to be
   *  fixed before the upload, not after the portal rejects the batch. A run
   *  that is not finalised is refused outright with its own 409: the ECR
   *  reports contributions actually made, and a draft run's figures can still
   *  change. The browser version happily built one from a draft. */
  async function downloadStatutoryFile(
    run: PayrollRun,
    what: "ecr" | "esic",
    fetcher: () => Promise<unknown>,
  ) {
    setStatutoryBusy(`${run.id}:${what}`);
    try {
      const res = (await fetcher()) as {
        data?: { filename?: string; lines?: string; csv?: string;
                 problems?: string[]; filable?: boolean };
      };
      const d = res?.data;
      if (!d) throw new Error("The server returned no file.");
      const content = what === "ecr" ? d.lines : d.csv;
      const problems = d.problems ?? [];

      if (!d.filable) {
        toast({
          title: `${what === "ecr" ? "ECR" : "ESIC return"} not ready to file`,
          description: problems.length
            ? problems.join(" · ")
            : "The server could not build a filable return for this run.",
          variant: "destructive",
        });
        return;
      }
      if (!content) throw new Error("The server returned an empty file.");

      downloadFile(
        content,
        d.filename ?? `${what.toUpperCase()}_${run.month}.${what === "ecr" ? "txt" : "csv"}`,
        what === "ecr" ? "text/plain" : "text/csv",
      );
      // Filable and still worth saying: a problem here is a member LEFT OUT of
      // a file the CA is about to upload, which is not visible in the file.
      if (problems.length) {
        toast({
          title: `Downloaded, with ${problems.length} member${problems.length === 1 ? "" : "s"} to fix`,
          description: problems.join(" · "),
        });
      }
    } catch (e) {
      toast({
        title: `Couldn't build the ${what === "ecr" ? "ECR" : "ESIC return"}`,
        description: e instanceof Error ? e.message : String(e),
        variant: "destructive",
      });
    } finally {
      setStatutoryBusy(null);
    }
  }

  /** The server refuses the ECR and the ESIC return for a run that is not
   *  finalised, because both report contributions actually made. Say that on
   *  the button rather than spending a round trip to be told. */
  const isFiled = (run: PayrollRun) => run.status === "finalized" || run.status === "paid";

  const handleGeneratePfEcr = (run: PayrollRun) =>
    downloadStatutoryFile(run, "ecr", () => api.payroll.runEcr(run.id));

  const handleGenerateEsiStatement = (run: PayrollRun) =>
    downloadStatutoryFile(run, "esic", () => api.payroll.runEsic(run.id));

  function handleGenerate24Q(run: PayrollRun) {
    // # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    const runSlips = slipsForRun(run.id);
    const quarter = getTdsQuarterLabel(run.month);
    const content = generateTds24QData(runSlips, quarter);
    downloadFile(content, `TDS_24Q_${run.month}.csv`, "text/csv");
  }

  return (
    <div className="space-y-6">
      {/* Due Date Checklist */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Statutory Return Deadlines</CardTitle>
          <p className="text-xs text-[#64748B] mt-0.5">
            Based on today&apos;s date. Mark as filed in your records after submission.
          </p>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {deadlines.map(d => (
              <div
                key={d.id}
                className={`flex items-start justify-between p-3 rounded-lg border ${
                  d.status === "overdue"
                    ? "border-red-200 bg-red-50"
                    : d.status === "due-soon"
                    ? "border-amber-200 bg-amber-50"
                    : "border-[#E2E8F0] bg-white"
                }`}
              >
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-[#0F172A]">{d.label}</p>
                  <p className="text-xs text-[#64748B] mt-0.5">{d.description}</p>
                  <p className="text-xs text-[#64748B] mt-0.5">
                    Portal: {d.portal} &middot; Due:{" "}
                    {d.dueDate.toLocaleDateString("en-IN", {
                      day: "numeric",
                      month: "short",
                      year: "numeric",
                    })}
                  </p>
                </div>
                <div className="ml-4 flex-shrink-0">
                  <StatusBadge status={d.status} />
                </div>
              </div>
            ))}
          </div>
          <p className="text-xs text-[#94A3B8] mt-4 border-t pt-3">
            Note: Status is computed from today&apos;s date. This checklist does not auto-track filed
            returns — update your firm records after each submission.
          </p>
        </CardContent>
      </Card>

      {/* Generate Returns for Payroll Runs */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Generate Statutory Return Files</CardTitle>
          <p className="text-xs text-[#64748B] mt-0.5">
            Download files in the correct format for each portal. Review before uploading.
          </p>
        </CardHeader>
        <CardContent>
          {clients.length > 1 && (
            <div className="mb-4">
              <label className="block text-xs font-medium text-[#334155] mb-1">Client</label>
              <ClientLookup
                clients={clients}
                value={selectedClientId}
                onChange={setSelectedClientId}
                ariaLabel="Client"
                placeholder="Select client…"
              />
            </div>
          )}

          {clientRuns.length === 0 ? (
            <p className="text-sm text-[#94A3B8] py-6 text-center">
              No payroll runs for this client. Run a Monthly Payroll first.
            </p>
          ) : (
            <div className="space-y-3">
              {/* CA Review notice */}
              <div className="flex items-start gap-2 p-3 bg-amber-50 border border-amber-200 rounded-lg">
                <AlertCircle size={15} className="text-amber-600 mt-0.5 flex-shrink-0" />
                <p className="text-xs text-amber-800">
                  <strong>CA Review Required.</strong> These files are generated for review only.
                  Do not upload to any government portal without explicit CA verification and approval.
                  All statutory returns must be authorised by a qualified Chartered Accountant.
                </p>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-xs font-medium text-[#64748B] uppercase tracking-wide">
                      <th className="text-left py-3 px-3">Month</th>
                      <th className="text-center py-3 px-3">Employees</th>
                      <th className="text-right py-3 px-3">Total Gross</th>
                      <th className="text-right py-3 px-3">Total TDS</th>
                      <th className="py-3 px-3 text-right">Generate Files</th>
                    </tr>
                  </thead>
                  <tbody>
                    {clientRuns.map(run => {
                      const runSlips = slipsForRun(run.id);
                      const totalGross = runSlips.reduce((sum, s) => sum + s.gross_paise, 0);
                      const totalTds = runSlips.reduce((sum, s) => sum + s.tds_paise, 0);
                      // Whether a slip actually CARRIED the contribution, not
                      // whether a re-derived ceiling test says it should have.
                      // The old ESI test was `gross <= 2100000` for the month,
                      // which drops a member Rule 50 keeps in past the ceiling
                      // until the contribution period ends — so the button read
                      // "no ESI-applicable employees" for people we deducted from.
                      const pfCount = runSlips.filter(s => (s.pf_employee_paise || 0) > 0).length;
                      const esiCount = runSlips.filter(
                        s => (s.esi_employee_paise || 0) > 0 || (s.esi_employer_paise || 0) > 0,
                      ).length;
                      return (
                        <tr key={run.id} className="border-b hover:bg-[#F8FAFC]">
                          <td className="py-3 px-3 font-medium">{run.month}</td>
                          <td className="py-3 px-3 text-center text-[#475569]">{runSlips.length}</td>
                          <td className="py-3 px-3 text-right font-mono">{fmtRs(totalGross)}</td>
                          <td className="py-3 px-3 text-right font-mono text-red-600">{fmtRs(totalTds)}</td>
                          <td className="py-3 px-3">
                            <div className="flex gap-2 justify-end flex-wrap">
                              <Button
                                size="sm"
                                variant="outline"
                                className="flex items-center gap-1 text-xs"
                                onClick={() => handleGeneratePfEcr(run)}
                                disabled={pfCount === 0 || !isFiled(run) || statutoryBusy === `${run.id}:ecr`}
                                title={pfCount === 0 ? "No PF-applicable employees this month"
                                  : !isFiled(run) ? "Finalise the run first — the ECR reports contributions actually made"
                                  : `Generate PF ECR for ${pfCount} employees`}
                              >
                                <Download size={12} />
                                {statutoryBusy === `${run.id}:ecr` ? "…" : "PF ECR"}
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                className="flex items-center gap-1 text-xs"
                                onClick={() => handleGenerateEsiStatement(run)}
                                disabled={esiCount === 0 || !isFiled(run) || statutoryBusy === `${run.id}:esic`}
                                title={esiCount === 0 ? "No ESI-applicable employees this month"
                                  : !isFiled(run) ? "Finalise the run first — the return reports contributions actually made"
                                  : `Generate ESI statement for ${esiCount} employees`}
                              >
                                <Download size={12} />
                                {statutoryBusy === `${run.id}:esic` ? "…" : "ESI"}
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                className="flex items-center gap-1 text-xs"
                                onClick={() => handleGenerate24Q(run)}
                                disabled={runSlips.length === 0}
                                title="Generate TDS 24Q data — CA review required before filing"
                              >
                                <Download size={12} />
                                24Q
                              </Button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {/* Format notes */}
              <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-3 text-xs text-[#64748B]">
                <div className="p-3 bg-[#F8FAFC] rounded-lg border border-[#F1F5F9]">
                  <p className="font-medium text-[#334155] mb-1">PF ECR (.txt)</p>
                  <p>Tilde-separated format for EPFO Unified Portal. Upload via &quot;ECR Upload&quot; on epfindia.gov.in. Due by 15th each month.</p>
                </div>
                <div className="p-3 bg-[#F8FAFC] rounded-lg border border-[#F1F5F9]">
                  <p className="font-medium text-[#334155] mb-1">ESI Statement (.csv)</p>
                  <p>Employee-wise ESI contribution data for ESIC portal. Half-yearly filing — Apr-Sep by Nov 11, Oct-Mar by May 11.</p>
                </div>
                <div className="p-3 bg-[#F8FAFC] rounded-lg border border-[#F1F5F9]">
                  <p className="font-medium text-[#334155] mb-1">TDS 24Q (.csv)</p>
                  <p>Quarterly TDS data per IT Act Section 192. Must be filed on the e-filing portal (incometax.gov.in) under the deductor’s TAN. CA review mandatory before submission.</p>
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────

// ── Salary Disbursement Modal (mark a finalized run paid) ───────────────────
// Records the net-salary payout from a bank account. The chosen bank account
// must be linked to a chart-of-accounts ledger account (bank_accounts.coa_account_id)
// so the disbursement journal (Dr Net Salary Payable / Cr Bank) can post.

interface DisburseBankAccount {
  id: string; bank_name: string; account_no: string;
  coa_account_id: string | null; is_active: boolean;
}

function DisburseModal({ run, onClose, onDone }: {
  run: PayrollRun; onClose: () => void; onDone: (msg: string) => void;
}) {
  const [accounts, setAccounts] = useState<DisburseBankAccount[]>([]);
  const [loadingAccts, setLoadingAccts] = useState(true);
  const [accountId, setAccountId] = useState("");
  const [payDate, setPayDate] = useState(() => toLocalISO(new Date()).slice(0, 10));
  const [reference, setReference] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const res = await api.banking.listBankAccounts({ client_id: run.client_id }) as ApiResp<DisburseBankAccount[]>;
        // Only active accounts with a linked ledger account can post the journal.
        const linked = (res.data ?? []).filter((a) => a.is_active && a.coa_account_id);
        setAccounts(linked);
        setAccountId(linked[0]?.id ?? "");
      } catch { setAccounts([]); }
      setLoadingAccts(false);
    })();
  }, [run.client_id]);

  async function save() {
    if (!accountId) { setError("Select a bank account."); return; }
    setSaving(true); setError(null);
    try {
      const res = await api.payroll.disburseRun(run.id, {
        bank_account_id: accountId,
        payment_date: payDate || undefined,
        payment_reference: reference.trim() || undefined,
      }) as ApiResp<unknown>;
      if (!res.success) { setError(res.error ?? "Could not record the disbursement."); return; }
      onDone(`Payroll for ${run.month} marked paid.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not record the disbursement.");
    } finally {
      setSaving(false);
    }
  }

  const netStr = run.total_net_paise != null ? fmtRs(run.total_net_paise) : "—";
  const inputCls = "w-full border rounded-lg px-3 py-2 text-sm";

  return (
    <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-[#0F172A]">Mark Payroll Paid — {run.month}</h3>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#475569]"><X size={16} /></button>
        </div>
        <div className="bg-[#F8FAFC] rounded-lg px-3 py-2 text-xs text-[#475569]">
          Posts <span className="font-medium">Dr Net Salary Payable / Cr Bank</span> for the net pay
          <span className="font-mono"> {netStr}</span>, clearing the payable raised at finalization.
        </div>
        {loadingAccts ? (
          <p className="text-sm text-[#64748B]">Loading bank accounts…</p>
        ) : accounts.length === 0 ? (
          <div className="text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2">
            No bank account is linked to a ledger account for this client. Add one under
            Accounting → Bank (with a Ledger Account link) before disbursing salaries.
          </div>
        ) : (
          <>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Pay from bank account *</label>
              <select value={accountId} onChange={(e) => setAccountId(e.target.value)} className={inputCls}>
                {accounts.map((a) => <option key={a.id} value={a.id}>{a.bank_name} · ····{a.account_no.slice(-4)}</option>)}
              </select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs font-medium text-[#475569] mb-1">Payment date</label>
                <input type="date" value={payDate} onChange={(e) => setPayDate(e.target.value)} className={inputCls} />
              </div>
              <div>
                <label className="block text-xs font-medium text-[#475569] mb-1">Reference</label>
                <input value={reference} onChange={(e) => setReference(e.target.value)} placeholder="NEFT / UTR no." className={inputCls} />
              </div>
            </div>
          </>
        )}
        {error && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}
        <div className="flex gap-3 justify-end">
          <button onClick={onClose} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Cancel</button>
          <button onClick={save} disabled={saving || loadingAccts || accounts.length === 0} className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40">
            {saving ? "Recording…" : "Confirm Payment"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function PayrollPage() {
  const [loadError, setLoadError] = useState<string | null>(null);
  const [clients, setClients] = useState<Client[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [runs, setRuns] = useState<PayrollRun[]>([]);
  const [slips, setSlips] = useState<PayrollSlip[]>([]);
  const [loading, setLoading] = useState(true);

  const [runClientId, setRunClientId] = useState("");
  const [runMonth, setRunMonth] = useState(() => new Date().toISOString().slice(0, 7));
  const [runEmployees, setRunEmployees] = useState<Employee[]>([]);
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);

  const [statMonth, setStatMonth] = useState(() => toLocalISO(new Date()).slice(0, 7));
  const [statClientId, setStatClientId] = useState("");
  const [statSlips, setStatSlips] = useState<PayrollSlip[]>([]);

  const [showAdd, setShowAdd] = useState(false);
  const [showImportEmp, setShowImportEmp] = useState(false);
  const [viewSlip, setViewSlip] = useState<PayrollSlip | null>(null);

  // Payroll-run lifecycle actions (finalize → mark paid).
  const [disburseTarget, setDisburseTarget] = useState<PayrollRun | null>(null);
  const [runActionBusy, setRunActionBusy] = useState<string | null>(null);
  const [runActionMsg, setRunActionMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  async function finalizeRunAction(run: PayrollRun) {
    if (!confirm(`Finalize payroll for ${run.month}? This posts the salary accrual journal (Dr Salaries Expense / Cr Net Salary Payable + statutory payables) and locks the run.`)) return;
    setRunActionBusy(run.id); setRunActionMsg(null);
    try {
      const res = await api.payroll.finalizeRun(run.id) as ApiResp<unknown>;
      if (!res.success) { setRunActionMsg({ type: "err", text: res.error ?? "Could not finalize the run." }); }
      else { setRunActionMsg({ type: "ok", text: `Payroll for ${run.month} finalized.` }); await load(); }
    } catch (e) { setRunActionMsg({ type: "err", text: e instanceof Error ? e.message : "Could not finalize the run." }); }
    finally { setRunActionBusy(null); }
  }

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [clientsRes, empRes, runsRes] = await Promise.all([
        api.clients.list() as Promise<ApiResp<{ clients: Client[] }>>,
        // include_inactive: the Employees roster shows resigned/terminated staff
        // too (with a status filter). Payroll generation still uses only active
        // employees — see the runEmployees derivation below.
        api.payroll.listEmployees(undefined, true) as Promise<ApiResp<Employee[]>>,
        api.payroll.listRuns() as Promise<ApiResp<PayrollRun[]>>,
      ]);
      const clientList = clientsRes.data?.clients ?? [];
      const empList = empRes.data ?? [];
      const runList = runsRes.data ?? [];
      setClients(clientList);
      setEmployees(empList);
      setRuns(runList);

      if (runList.length > 0) {
        const slipLists = await Promise.all(
          runList.map(r => api.payroll.getRunSlips(r.id) as Promise<ApiResp<PayrollSlip[]>>)
        );
        const rawSlips = slipLists.flatMap(res => res.data ?? []);
        const enriched = rawSlips.map(s => ({
          ...s,
          employee: empList.find(e => e.id === s.employee_id),
          run: runList.find(r => r.id === s.run_id),
        }));
        setSlips(enriched);
      } else {
        setSlips([]);
      }
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Failed to load payroll data.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (runClientId) {
      // Only ACTIVE employees are eligible for a payroll run (mirrors the
      // backend create_run filter); resigned/terminated staff must not appear.
      setRunEmployees(employees.filter(e => e.client_id === runClientId && (e.status ?? "active") === "active"));
    }
  }, [runClientId, employees]);

  // ── Employee roster CRUD (edit / deactivate / delete + bulk) ────────────────
  const [editEmployee, setEditEmployee] = useState<Employee | null>(null);
  // Which employee's portal access is being managed, if any.
  const [portalEmployee, setPortalEmployee] = useState<Employee | null>(null);
  const [empActionMsg, setEmpActionMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  const setEmployeeStatus = useCallback(async (emp: Employee, status: "active" | "resigned") => {
    const deactivating = status !== "active";
    if (!confirm(`${deactivating ? "Deactivate" : "Reactivate"} ${emp.name}? ${deactivating ? "They will be excluded from new payroll runs; existing payslips are unaffected." : "They will be eligible for payroll runs again."}`)) return;
    try {
      const res = await api.payroll.updateEmployee(emp.id, { status }) as ApiResp<unknown>;
      if (!res.success) { setEmpActionMsg({ type: "err", text: res.error ?? "Could not update the employee." }); return; }
      setEmpActionMsg({ type: "ok", text: `${emp.name} ${deactivating ? "deactivated" : "reactivated"}.` });
      load();
    } catch (e) { setEmpActionMsg({ type: "err", text: apiErr(e, "Could not update the employee.") }); }
  }, [load]);

  const deleteEmployeeAction = useCallback(async (emp: Employee) => {
    if (!confirm(`Permanently delete ${emp.name}? Only an employee with no payroll history can be deleted — otherwise deactivate them instead.`)) return;
    try {
      const res = await api.payroll.deleteEmployee(emp.id) as ApiResp<unknown>;
      if (!res.success) { setEmpActionMsg({ type: "err", text: res.error ?? "Could not delete the employee." }); return; }
      setEmpActionMsg({ type: "ok", text: `${emp.name} deleted.` });
      load();
    } catch (e) { setEmpActionMsg({ type: "err", text: apiErr(e, "Could not delete the employee.") }); }
  }, [load]);

  // Bulk: set status for the selected rows (deactivate → resigned, reactivate → active).
  const bulkSetEmployeeStatus = useCallback(async (rows: Employee[], status: "active" | "resigned"): Promise<void> => {
    const targets = rows.filter(e => (e.status ?? "active") !== status);
    if (targets.length === 0) { setEmpActionMsg({ type: "ok", text: "Nothing to change — the selected employees are already in that state." }); return; }
    let ok = 0; const failures: string[] = [];
    await Promise.all(targets.map(async (e) => {
      try {
        const res = await api.payroll.updateEmployee(e.id, { status }) as ApiResp<unknown>;
        if (!res.success) throw new Error(res.error ?? "failed");
        ok++;
      } catch (err) { failures.push(`${e.name}: ${apiErr(err, "failed")}`); }
    }));
    const verb = status === "active" ? "reactivated" : "deactivated";
    setEmpActionMsg(failures.length
      ? { type: "err", text: `${ok} ${verb}, ${failures.length} failed. ${failures.slice(0, 3).join("; ")}${failures.length > 3 ? "…" : ""}` }
      : { type: "ok", text: `${ok} employee${ok === 1 ? "" : "s"} ${verb}.` });
    if (ok) load();
  }, [load]);

  // Bulk delete: employees with payroll history are skipped (backend 409s); report both.
  const bulkDeleteEmployees = useCallback(async (rows: Employee[]): Promise<void> => {
    let deleted = 0, skipped = 0; const failures: string[] = [];
    await Promise.all(rows.map(async (e) => {
      try {
        const res = await api.payroll.deleteEmployee(e.id) as ApiResp<unknown>;
        if (!res.success) throw new Error(res.error ?? "failed");
        deleted++;
      } catch (err) {
        const msg = apiErr(err, "failed");
        if (/payroll history/i.test(msg)) skipped++;
        else failures.push(`${e.name}: ${msg}`);
      }
    }));
    const parts = [`${deleted} deleted`];
    if (skipped) parts.push(`${skipped} skipped (has payroll history — deactivate instead)`);
    if (failures.length) parts.push(`${failures.length} failed`);
    setEmpActionMsg({ type: failures.length ? "err" : "ok", text: parts.join(", ") + "." });
    if (deleted) load();
  }, [load]);

  useEffect(() => {
    if (clients.length > 0 && !runClientId) {
      setRunClientId(clients[0].id);
      setStatClientId(clients[0].id);
    }
  }, [clients, runClientId]);

  useEffect(() => {
    if (statClientId) {
      const monthRuns = runs.filter(r => r.client_id === statClientId && r.month === statMonth);
      const runIds = monthRuns.map(r => r.id);
      setStatSlips(slips.filter(s => runIds.includes(s.run_id)));
    }
  }, [statClientId, statMonth, runs, slips]);

  async function generatePayslips() {
    if (!runClientId || runEmployees.length === 0) return;
    setGenerating(true);
    setGenerateError(null);
    try {
      // Server-side computation (routers/payroll.py::create_run) — the ONLY
      // place gross/PF/ESI/PT/TDS are computed; see R2.10.
      await api.payroll.createRun({ client_id: runClientId, month: runMonth });
      await load();
    } catch (e) {
      setGenerateError(e instanceof Error ? e.message : "Failed to generate payslips.");
    } finally {
      setGenerating(false);
    }
  }

  // ── Employees table (shared DataTable) ─────────────────────────────────────
  const employeeColumns: Column<Employee>[] = useMemo(() => [
    { key: "name", header: "Name", accessor: (e) => e.name, searchable: true, sortable: true, sticky: true, hideable: false,
      render: (e) => <span className="font-medium text-[#0F172A]">{e.name}</span> },
    { key: "pan", header: "PAN", accessor: (e) => e.pan ?? "", searchable: true,
      render: (e) => <span className="font-mono text-xs">{e.pan || "—"}</span> },
    { key: "designation", header: "Designation", accessor: (e) => e.designation ?? "", searchable: true, sortable: true,
      render: (e) => <span className="text-[#475569]">{e.designation || "—"}</span> },
    // Money column — accessor returns integer paise, right-aligned, rendered via formatPaise.
    { key: "gross", header: "Monthly CTC", accessor: (e) => employeeGrossPaise(e), sortable: true, align: "right",
      render: (e) => <span className="font-mono">{formatPaise(employeeGrossPaise(e))}</span> },
    { key: "pf_applicable", header: "PF", accessor: (e) => e.pf_applicable, sortable: true, align: "center",
      render: (e) => (
        <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${e.pf_applicable ? "bg-green-100 text-green-700" : "bg-[#F1F5F9] text-[#64748B]"}`}>
          {e.pf_applicable ? "Yes" : "No"}
        </span>
      ) },
    { key: "esi_applicable", header: "ESI", accessor: (e) => e.esi_applicable, sortable: true, align: "center",
      render: (e) => (
        <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${e.esi_applicable ? "bg-green-100 text-green-700" : "bg-[#F1F5F9] text-[#64748B]"}`}>
          {e.esi_applicable ? "Yes" : "No"}
        </span>
      ) },
    // Reads portal_enabled straight off the employee row rather than calling
    // portal-status per row — one request per employee would be N requests for
    // a column most firms will not use. The modal fetches the detail on open.
    { key: "portal", header: "Payslip portal", accessor: (e) => (e.portal_enabled ? "on" : "off"),
      sortable: true, align: "center",
      render: (e) => (
        <button
          onClick={() => setPortalEmployee(e)}
          className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium hover:ring-1 hover:ring-blue-300 ${
            e.portal_enabled ? "bg-green-100 text-green-700" : "bg-[#F1F5F9] text-[#64748B]"}`}
          title={e.portal_enabled ? "Portal access is on — click to manage" : "Give this employee portal access"}
        >
          {e.portal_enabled ? "Active" : "Give access"}
        </button>
      ) },
    { key: "status", header: "Status", accessor: (e) => e.status ?? "active", sortable: true, align: "center",
      render: (e) => {
        const s = e.status ?? "active";
        const cls = s === "active" ? "bg-green-100 text-green-700" : "bg-[#F1F5F9] text-[#64748B]";
        return <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium capitalize ${cls}`}>{s}</span>;
      } },
  ], []);

  const employeeFilters: FilterDef<Employee>[] = useMemo(() => [
    { key: "status", label: "Status", type: "select", accessor: (e) => e.status ?? "active",
      options: [{ value: "active", label: "Active" }, { value: "resigned", label: "Resigned" }, { value: "terminated", label: "Terminated" }] },
    { key: "pf_applicable", label: "PF", type: "boolean", accessor: (e) => e.pf_applicable, trueLabel: "Applicable", falseLabel: "Not applicable" },
    { key: "esi_applicable", label: "ESI", type: "boolean", accessor: (e) => e.esi_applicable, trueLabel: "Applicable", falseLabel: "Not applicable" },
  ], []);

  const employeeBulkActions: BulkAction<Employee>[] = useMemo(() => [
    { id: "deactivate", label: "Deactivate", icon: <Ban size={13} />,
      confirm: "Deactivate the selected employees? They will be excluded from new payroll runs. Existing payslips are unaffected and this can be undone.",
      run: (rows) => bulkSetEmployeeStatus(rows, "resigned") },
    { id: "reactivate", label: "Reactivate", icon: <RotateCcw size={13} />,
      confirm: "Reactivate the selected employees so they are eligible for payroll runs again?",
      run: (rows) => bulkSetEmployeeStatus(rows, "active") },
    { id: "delete", label: "Delete", icon: <Trash2 size={13} />, variant: "danger",
      confirm: "Permanently delete the selected employees? Anyone with payroll history is skipped (deactivate them instead). This cannot be undone.",
      run: bulkDeleteEmployees },
    exportSelectedAction<Employee>("employees-selected.csv", employeeColumns),
  ], [bulkSetEmployeeStatus, bulkDeleteEmployees, employeeColumns]);

  // ── Payslips table (shared DataTable) ──────────────────────────────────────
  const slipDeductions = (s: PayrollSlip) => s.pf_employee_paise + s.esi_employee_paise + s.pt_paise + s.tds_paise;

  const payslipColumns: Column<PayrollSlip>[] = useMemo(() => [
    { key: "employee", header: "Employee", accessor: (s) => s.employee?.name ?? "", searchable: true, sortable: true, sticky: true, hideable: false,
      render: (s) => <span className="font-medium text-[#0F172A]">{s.employee?.name ?? "—"}</span> },
    { key: "month", header: "Month", accessor: (s) => s.run?.month ?? "", searchable: true, sortable: true,
      render: (s) => <span className="text-[#475569]">{s.run?.month ?? "—"}</span> },
    { key: "gross", header: "Gross", accessor: (s) => s.gross_paise, sortable: true, align: "right",
      render: (s) => <span className="font-mono">{formatPaise(s.gross_paise)}</span> },
    { key: "deductions", header: "Deductions", accessor: (s) => slipDeductions(s), sortable: true, align: "right",
      render: (s) => <span className="font-mono text-red-600">{formatPaise(slipDeductions(s))}</span> },
    { key: "net", header: "Net Pay", accessor: (s) => s.net_paise, sortable: true, align: "right",
      render: (s) => <span className="font-mono font-semibold text-green-700">{formatPaise(s.net_paise)}</span> },
  ], []);

  const payslipMonthOptions = useMemo(() => {
    const months = Array.from(new Set(slips.map((s) => s.run?.month).filter(Boolean) as string[]));
    months.sort((a, b) => b.localeCompare(a));
    return months.map((m) => ({ value: m, label: m }));
  }, [slips]);

  const payslipFilters: FilterDef<PayrollSlip>[] = useMemo(() => [
    { key: "month", label: "Month", type: "select", accessor: (s) => s.run?.month ?? "", options: payslipMonthOptions },
  ], [payslipMonthOptions]);

  if (loading) {
    return <div className="min-h-screen bg-[#F8FAFC] flex items-center justify-center"><p className="text-[#64748B]">Loading payroll...</p></div>;
  }

  if (loadError) {
    return (
      <div className="min-h-screen bg-[#F8FAFC] p-8">
        <Card className="max-w-2xl mx-auto">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <AlertCircle size={18} className="text-red-500" />
              Couldn&apos;t load payroll
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-[#475569] mb-4">{loadError}</p>
            <Button onClick={load}>Retry</Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#F8FAFC] p-8">
      {portalEmployee && (
        <PortalAccessModal
          employee={portalEmployee}
          onClose={() => setPortalEmployee(null)}
          onChanged={(msg) => {
            setEmpActionMsg({ type: "ok", text: msg });
            // portal_enabled changed on the server; refetch so the column and
            // any later modal open reflect it rather than a stale row.
            load();
          }}
        />
      )}
      {showAdd && (
        <AddEmployeeModal
          clients={clients}
          employee={editEmployee}
          onClose={() => { setShowAdd(false); setEditEmployee(null); }}
          onSaved={() => {
            const wasEdit = !!editEmployee;
            setShowAdd(false); setEditEmployee(null);
            setEmpActionMsg({ type: "ok", text: wasEdit ? "Employee updated." : "Employee added." });
            load();
          }}
        />
      )}
      {viewSlip && <PayslipModal slip={viewSlip} onClose={() => setViewSlip(null)} />}
      {disburseTarget && (
        <DisburseModal
          run={disburseTarget}
          onClose={() => setDisburseTarget(null)}
          onDone={(msg) => { setDisburseTarget(null); setRunActionMsg({ type: "ok", text: msg }); load(); }}
        />
      )}

      <div className="max-w-6xl mx-auto">
        <div className="mb-6 flex items-start justify-between flex-wrap gap-4">
          <div>
            <h1 className="text-2xl font-bold text-[#0F172A]">Payroll</h1>
            <p className="text-sm text-[#64748B] mt-0.5">IT Act Section 192 &middot; EPF Act &middot; ESI Act</p>
          </div>
          <div className="flex items-center gap-2">
            {/* IT Act §192 / Rule 26C — what each employee declared, and what
                their proofs support. Its own page rather than a tab: it is a
                per-client, per-financial-year review, not part of a run. */}
            <Link href="/payroll/declarations">
              <Button variant="outline" className="flex items-center gap-1.5">
                <Receipt size={15} />Declarations
              </Button>
            </Link>
            <Link href="/payroll/reports">
              <Button variant="outline" className="flex items-center gap-1.5">
                <BarChart2 size={15} />Reports
              </Button>
            </Link>
          </div>
        </div>

        <Tabs defaultValue="employees">
          <TabsList className="mb-6">
            <TabsTrigger value="employees" className="flex items-center gap-1.5"><Users size={14} />Employees</TabsTrigger>
            <TabsTrigger value="monthly" className="flex items-center gap-1.5"><Play size={14} />Monthly Run</TabsTrigger>
            <TabsTrigger value="payslips" className="flex items-center gap-1.5"><FileText size={14} />Payslips</TabsTrigger>
            <TabsTrigger value="statutory" className="flex items-center gap-1.5"><Shield size={14} />Statutory</TabsTrigger>
            <TabsTrigger value="statutory-returns" className="flex items-center gap-1.5"><Download size={14} />Statutory Returns</TabsTrigger>
          </TabsList>

          {/* EMPLOYEES TAB */}
          <TabsContent value="employees">
            <Card>
              <CardHeader className="flex flex-row items-center justify-between">
                <CardTitle>Employees</CardTitle>
                <div className="flex items-center gap-2">
                  <Button size="sm" variant="outline" onClick={() => setShowImportEmp(true)} className="flex items-center gap-1.5">
                    <Upload size={14} />Import CSV
                  </Button>
                  <Button size="sm" onClick={() => { setEditEmployee(null); setShowAdd(true); }} className="flex items-center gap-1.5">
                    <Plus size={14} />Add Employee
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                {empActionMsg && (
                  <div className={`mb-3 flex items-center gap-2 px-3 py-2 rounded-lg text-xs ${empActionMsg.type === "ok" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-600"}`}>
                    {empActionMsg.text}
                    <button onClick={() => setEmpActionMsg(null)} className="ml-auto"><X size={12} /></button>
                  </div>
                )}
                <DataTable
                  data={employees}
                  columns={employeeColumns}
                  filters={employeeFilters}
                  getRowId={(e) => e.id}
                  loading={loading}
                  onRefresh={load}
                  searchPlaceholder="Search by name, PAN, or designation…"
                  initialSort={{ key: "name", dir: "asc" }}
                  initialFilters={{ status: "active" }}
                  exportFilename="employees"
                  persistKey="payroll.employees"
                  bulkActions={employeeBulkActions}
                  rowActions={(e) => {
                    const active = (e.status ?? "active") === "active";
                    return (
                      <div className="flex items-center justify-end gap-1">
                        <button onClick={() => { setEditEmployee(e); setShowAdd(true); }} title="Edit"
                          className="p-1.5 rounded-lg text-[#64748B] hover:bg-[#F1F5F9] hover:text-[#334155]"><Pencil size={14} /></button>
                        {active ? (
                          <button onClick={() => setEmployeeStatus(e, "resigned")} title="Deactivate"
                            className="p-1.5 rounded-lg text-[#64748B] hover:bg-amber-50 hover:text-amber-700"><Ban size={14} /></button>
                        ) : (
                          <button onClick={() => setEmployeeStatus(e, "active")} title="Reactivate"
                            className="p-1.5 rounded-lg text-[#64748B] hover:bg-green-50 hover:text-green-700"><RotateCcw size={14} /></button>
                        )}
                        <button onClick={() => deleteEmployeeAction(e)} title="Delete (only if no payroll history)"
                          className="p-1.5 rounded-lg text-[#64748B] hover:bg-red-50 hover:text-red-600"><Trash2 size={14} /></button>
                      </div>
                    );
                  }}
                  emptyTitle="No employees yet"
                  emptyDescription={'Click "Add Employee" or import a CSV to get started.'}
                />
              </CardContent>
            </Card>
          </TabsContent>

          {/* MONTHLY RUN TAB */}
          <TabsContent value="monthly">
            <Card className="mb-4">
              <CardContent className="pt-5">
                <div className="flex flex-wrap gap-4 items-end">
                  <div>
                    <label className="block text-xs font-medium text-[#334155] mb-1">Client</label>
                    <ClientLookup
                      clients={clients}
                      value={runClientId}
                      onChange={setRunClientId}
                      ariaLabel="Client"
                      placeholder="Select client…"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-[#334155] mb-1">Month</label>
                    <input type="month" className="border rounded-lg px-3 py-2 text-sm" value={runMonth} onChange={e => setRunMonth(e.target.value)} />
                  </div>
                  <Button
                    onClick={generatePayslips}
                    disabled={generating || runEmployees.length === 0}
                    className="flex items-center gap-1.5"
                  >
                    <Play size={14} />{generating ? "Generating..." : "Generate Payslips"}
                  </Button>
                </div>
                {generateError && <p className="text-sm text-red-600 mt-3">{generateError}</p>}
              </CardContent>
            </Card>

            {/* ── Payroll runs for this client — lifecycle: finalize → mark paid ── */}
            {runClientId && (() => {
              const clientRunList = runs
                .filter((r) => r.client_id === runClientId)
                .sort((a, b) => b.month.localeCompare(a.month));
              if (clientRunList.length === 0) return null;
              const statusBadge = (s: string) => {
                const map: Record<string, string> = {
                  draft: "bg-[#F1F5F9] text-[#64748B]",
                  review: "bg-amber-50 text-amber-700",
                  finalized: "bg-blue-50 text-blue-700",
                  paid: "bg-green-50 text-green-700",
                };
                return <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${map[s] ?? map.draft}`}>{s}</span>;
              };
              return (
                <Card className="mb-4">
                  <CardHeader><CardTitle className="text-base">Payroll Runs</CardTitle></CardHeader>
                  <CardContent>
                    {runActionMsg && (
                      <div className={`mb-3 flex items-center gap-2 px-3 py-2 rounded-lg text-xs ${runActionMsg.type === "ok" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-600"}`}>
                        {runActionMsg.text}
                        <button onClick={() => setRunActionMsg(null)} className="ml-auto"><X size={12} /></button>
                      </div>
                    )}
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead><tr className="border-b border-[#F1F5F9] text-[#94A3B8] text-xs">
                          <th className="py-2 px-3 text-left font-semibold">Month</th>
                          <th className="py-2 px-3 text-center font-semibold">Status</th>
                          <th className="py-2 px-3 text-center font-semibold">Employees</th>
                          <th className="py-2 px-3 text-right font-semibold">Gross</th>
                          <th className="py-2 px-3 text-right font-semibold">Net Pay</th>
                          <th className="py-2 px-3 text-right font-semibold">Action</th>
                        </tr></thead>
                        <tbody className="divide-y divide-[#F1F5F9]">
                          {clientRunList.map((r) => (
                            <tr key={r.id} className="hover:bg-[#F8FAFC]">
                              <td className="py-2.5 px-3 font-medium text-[#1E293B]">{r.month}</td>
                              <td className="py-2.5 px-3 text-center">{statusBadge(r.status)}</td>
                              <td className="py-2.5 px-3 text-center text-[#64748B]">{r.headcount ?? "—"}</td>
                              <td className="py-2.5 px-3 text-right font-mono text-[#334155]">{r.total_gross_paise != null ? fmtRs(r.total_gross_paise) : "—"}</td>
                              <td className="py-2.5 px-3 text-right font-mono text-[#334155]">{r.total_net_paise != null ? fmtRs(r.total_net_paise) : "—"}</td>
                              <td className="py-2.5 px-3 text-right whitespace-nowrap">
                                {(r.status === "draft" || r.status === "review") && (
                                  <Button size="sm" variant="outline" disabled={runActionBusy === r.id} onClick={() => finalizeRunAction(r)}>
                                    {runActionBusy === r.id ? "Finalizing…" : "Finalize"}
                                  </Button>
                                )}
                                {r.status === "finalized" && (
                                  <Button size="sm" disabled={runActionBusy === r.id} onClick={() => setDisburseTarget(r)} className="flex items-center gap-1.5">
                                    <CheckCircle size={13} /> Mark Paid
                                  </Button>
                                )}
                                {r.status === "paid" && (
                                  <span className="text-xs text-green-700 inline-flex items-center gap-1">
                                    <CheckCircle size={13} /> Paid{r.paid_at ? ` · ${r.paid_at.slice(0, 10)}` : ""}
                                  </span>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </CardContent>
                </Card>
              );
            })()}

            {runEmployees.length === 0 ? (
              <Card><CardContent className="py-12 text-center text-[#94A3B8]">No employees for this client.</CardContent></Card>
            ) : (
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Employees in this run ({runEmployees.length})</CardTitle>
                  <p className="text-xs text-[#64748B] mt-0.5">
                    Gross pay, PF, ESI, Professional Tax and TDS are computed by the
                    server when you click &quot;Generate Payslips&quot; — open the
                    Payslips tab afterwards to see the results.
                  </p>
                </CardHeader>
                <CardContent className="p-0">
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b text-xs font-medium text-[#64748B] uppercase tracking-wide">
                          <th className="text-left py-3 px-4">Employee</th>
                          <th className="text-left py-3 px-4">Designation</th>
                          <th className="text-right py-3 px-4">Monthly CTC</th>
                          <th className="text-center py-3 px-4">PF</th>
                          <th className="text-center py-3 px-4">ESI</th>
                          <th className="text-center py-3 px-4">PT</th>
                        </tr>
                      </thead>
                      <tbody>
                        {runEmployees.map(emp => (
                          <tr key={emp.id} className="border-b hover:bg-[#F8FAFC]">
                            <td className="py-3 px-4 font-medium">{emp.name}</td>
                            <td className="py-3 px-4 text-[#475569]">{emp.designation || "—"}</td>
                            <td className="py-3 px-4 text-right font-mono">{fmtRs(employeeGrossPaise(emp))}</td>
                            <td className="py-3 px-4 text-center">{emp.pf_applicable ? "Yes" : "No"}</td>
                            <td className="py-3 px-4 text-center">{emp.esi_applicable ? "Yes" : "No"}</td>
                            <td className="py-3 px-4 text-center">{emp.pt_applicable ? (emp.pt_state ?? "Yes") : "No"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            )}
          </TabsContent>

          {/* PAYSLIPS TAB */}
          <TabsContent value="payslips">
            <Card>
              <CardHeader><CardTitle>Generated Payslips</CardTitle></CardHeader>
              <CardContent>
                <DataTable
                  data={slips}
                  columns={payslipColumns}
                  filters={payslipFilters}
                  getRowId={(s) => s.id}
                  loading={loading}
                  onRefresh={load}
                  searchPlaceholder="Search by employee or month…"
                  initialSort={{ key: "month", dir: "desc" }}
                  exportFilename="payslips"
                  persistKey="payroll.payslips"
                  emptyTitle="No payslips generated yet"
                  emptyDescription="Run a Monthly Run to generate payslips."
                  rowActions={(s) => (
                    <Button size="sm" variant="outline" onClick={() => setViewSlip(s)}>View</Button>
                  )}
                />
              </CardContent>
            </Card>
          </TabsContent>

          {/* STATUTORY TAB */}
          <TabsContent value="statutory">
            <Card className="mb-4">
              <CardContent className="pt-5">
                <div className="flex gap-4 items-end">
                  <div>
                    <label className="block text-xs font-medium text-[#334155] mb-1">Client</label>
                    <ClientLookup
                      clients={clients}
                      value={statClientId}
                      onChange={setStatClientId}
                      ariaLabel="Client"
                      placeholder="Select client…"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-[#334155] mb-1">Month</label>
                    <input type="month" className="border rounded-lg px-3 py-2 text-sm" value={statMonth} onChange={e => setStatMonth(e.target.value)} />
                  </div>
                </div>
              </CardContent>
            </Card>
            {statSlips.length === 0 ? (
              <Card><CardContent className="py-12 text-center text-[#94A3B8]">No payroll runs for selected month/client.</CardContent></Card>
            ) : (() => {
              // SUM what the run stored. Nothing here re-derives a rate, a
              // ceiling or a formula.
              //
              // It used to. The employer PF was Math.min(basic * 12%, 180000) —
              // basic ALONE where EPF Act s.6 says basic + DA, and a hardcoded
              // Rs 1,800 that is only right while the ceiling is Rs 15,000. ESI
              // was gross * 3.25% behind the same monthly-ceiling test Rule 50
              // contradicts. EDLI was 0.5% OF THAT WRONG NUMBER. Every one of
              // those figures is already on the slip, computed once by
              // apps/api and posted to the ledger in the same paise, so a
              // screen that recomputed them could only ever disagree with the
              // books it sits beside.
              const sum = (f: (s: PayrollSlip) => number) => statSlips.reduce((t, s) => t + (f(s) || 0), 0);
              const totalPfEmp      = sum(s => s.pf_employee_paise);
              const totalPfEmployer = sum(s => s.pf_employer_paise ?? 0);
              const totalEsiEmp     = sum(s => s.esi_employee_paise);
              const totalEsiEmployer = sum(s => s.esi_employer_paise ?? 0);
              const totalPt         = sum(s => s.pt_paise);
              const totalTds        = sum(s => s.tds_paise);
              const edli            = sum(s => s.edli_paise ?? 0);
              return (
                <Card>
                  <CardHeader><CardTitle>Statutory Contributions — {statMonth}</CardTitle></CardHeader>
                  <CardContent>
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b text-xs font-medium text-[#64748B] uppercase">
                          <th className="text-left py-2">Component</th>
                          <th className="text-right py-2">Amount</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr className="border-b"><td className="py-2">PF Employee Contribution (12% of Basic)</td><td className="py-2 text-right font-mono">{fmtRs(totalPfEmp)}</td></tr>
                        <tr className="border-b"><td className="py-2">PF Employer Contribution (12% of Basic)</td><td className="py-2 text-right font-mono">{fmtRs(totalPfEmployer)}</td></tr>
                        <tr className="border-b"><td className="py-2">EDLI (0.5% of Basic)</td><td className="py-2 text-right font-mono">{fmtRs(edli)}</td></tr>
                        <tr className="border-b"><td className="py-2">ESI Employee (0.75% of Gross)</td><td className="py-2 text-right font-mono">{fmtRs(totalEsiEmp)}</td></tr>
                        <tr className="border-b"><td className="py-2">ESI Employer (3.25% of Gross)</td><td className="py-2 text-right font-mono">{fmtRs(totalEsiEmployer)}</td></tr>
                        <tr className="border-b"><td className="py-2">Professional Tax</td><td className="py-2 text-right font-mono">{fmtRs(totalPt)}</td></tr>
                        <tr className="font-bold"><td className="py-2">TDS on Salary (IT Act Sec 192)</td><td className="py-2 text-right font-mono">{fmtRs(totalTds)}</td></tr>
                      </tbody>
                    </table>
                  </CardContent>
                </Card>
              );
            })()}
          </TabsContent>

          {/* STATUTORY RETURNS TAB */}
          <TabsContent value="statutory-returns">
            <StatutoryReturnsTab runs={runs} slips={slips} clients={clients} />
          </TabsContent>
        </Tabs>
      </div>

      {showImportEmp && (
        <CsvImportModal
          title="Import Employees from CSV"
          columns={EMPLOYEE_IMPORT_COLUMNS}
          templateFilename="practicesync-employees-template.xlsx"
          onClose={() => setShowImportEmp(false)}
          onImport={async (rows: ImportRow[]) => {
            let imported = 0;
            const errors: string[] = [];
            for (const row of rows) {
              const client = clients.find(c => c.client_name.toLowerCase() === row.client_name?.toLowerCase());
              if (!client) { errors.push(`Employee "${row.name}": client "${row.client_name}" not found`); continue; }
              const ptState = (row.pt_state ?? "").trim().toUpperCase();
              // A CSV row is not a keystroke, so a bad amount SKIPS the row and
              // is reported rather than blocking the whole import — but it is
              // never coerced. "1,25,000" in a spreadsheet column is exactly how
              // an amount gets there, and parseFloat reads it as 1.
              const basic = paiseFromRupeeInput(row.basic_rs ?? "0");
              const allowances = paiseFromRupeeInput(row.other_allowances_rs ?? "0");
              if (basic === null || allowances === null) {
                errors.push(`Employee "${row.name}": basic_rs and other_allowances_rs `
                            + "must be plain amounts in rupees, without commas");
                continue;
              }
              try {
                await api.payroll.createEmployee({
                  client_id: client.id,
                  name: row.name,
                  pan: row.pan?.toUpperCase() || null,
                  gender: row.gender || null,
                  designation: row.designation || "",
                  basic_paise: basic,
                  hra_percent: parseFloat(row.hra_percent ?? "40"),
                  da_percent: parseFloat(row.da_percent ?? "0"),
                  other_allowances_paise: allowances,
                  pf_applicable: row.pf_applicable?.toLowerCase() !== "false",
                  esi_applicable: row.esi_applicable?.toLowerCase() === "true",
                  pt_applicable: ptState !== "",
                  pt_state: ptState || null,
                });
                imported++;
              } catch (e) {
                errors.push(`${row.name}: ${e instanceof Error ? e.message : "failed"}`);
              }
            }
            if (imported > 0) load();
            return { imported, errors };
          }}
          validateRow={(row) => {
            const errs: string[] = [];
            if (!/^[A-Z]{5}[0-9]{4}[A-Z]$/.test(row.pan?.toUpperCase() ?? "")) errs.push("Invalid PAN format");
            // isNaN(parseFloat(x)) was the old test, and it is FALSE for
            // "1,25,000" — parseFloat answers 1, so the row imported silently
            // at one rupee.
            if (row.basic_rs && paiseFromRupeeInput(row.basic_rs) === null) {
              errs.push("basic_rs must be a plain amount in rupees, without commas");
            }
            if (row.other_allowances_rs && paiseFromRupeeInput(row.other_allowances_rs) === null) {
              errs.push("other_allowances_rs must be a plain amount in rupees, without commas");
            }
            return errs;
          }}
        />
      )}
    </div>
  );
}
