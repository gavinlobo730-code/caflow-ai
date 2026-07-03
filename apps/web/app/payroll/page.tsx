"use client";

/**
 * Payroll Module — IT Act Section 192 (TDS on Salary), ESI Act, EPF Act
 * All monetary values stored and computed in integer paise.
 */

import { useState, useEffect, useCallback, useMemo } from "react";
import Link from "next/link";
import {
  Users, Play, FileText, Shield, Plus, X, AlertCircle,
  Download, CheckCircle, Clock, AlertTriangle, BarChart2, Upload,
} from "lucide-react";
import CsvImportModal, { type ImportRow } from "@/components/CsvImportModal";
import { DataTable } from "@/components/ui/data-table";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import type { Column, FilterDef } from "@/lib/table/types";
import { formatPaise } from "@/lib/services/formatting";

const EMPLOYEE_IMPORT_COLUMNS = [
  { key: "name",                    label: "Employee Name",       required: true,  hint: "e.g. Ramesh Kumar" },
  { key: "pan",                     label: "PAN",                 required: true,  hint: "e.g. AABCU9603R" },
  { key: "designation",             label: "Designation",         required: false, hint: "e.g. Senior Associate" },
  { key: "client_name",             label: "Client Name",         required: true,  hint: "Must match existing client" },
  { key: "basic_rs",                label: "Basic Salary (₹/mo)", required: true,  hint: "e.g. 30000" },
  { key: "hra_percent",             label: "HRA %",               required: false, hint: "e.g. 40" },
  { key: "da_percent",              label: "DA %",                required: false, hint: "e.g. 0" },
  { key: "other_allowances_rs",     label: "Other Allow. (₹/mo)",required: false, hint: "e.g. 5000" },
  { key: "pf_applicable",           label: "PF Applicable",       required: false, hint: "true | false" },
  { key: "esi_applicable",          label: "ESI Applicable",      required: false, hint: "true | false" },
];
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";

// ── Types ──────────────────────────────────────────────────────────────────

type Client = { id: string; client_name: string };

type Employee = {
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

type PayrollRun = {
  id: string;
  firm_id: string;
  client_id: string;
  month: string;
  status: string;
  generated_at: string;
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

/** Monthly gross CTC for an employee, in integer paise (basic + HRA + DA + other allowances). */
function employeeGrossPaise(emp: Employee): number {
  return (
    emp.basic_paise +
    Math.round((emp.basic_paise * emp.hra_percent) / 100) +
    Math.round((emp.basic_paise * emp.da_percent) / 100) +
    emp.other_allowances_paise
  );
}

/**
 * Monthly salary TDS under the new regime (IT Act §192), in integer paise.
 *
 * FY 2024-25 (AY 2025-26): standard deduction ₹75,000; slabs 0–3L nil, 3–7L 5%,
 * 7–10L 10%, 10–12L 15%, 12–15L 20%, >15L 30%; §87A rebate makes tax nil up to
 * ₹7,00,000 taxable (with marginal relief just above the ceiling); 4% cess.
 *
 * Input and output are PAISE. The previous version compared a paise-scale annual
 * gross against rupee-scale thresholds (e.g. `annualGross > 1500000` meaning
 * ₹15,000 instead of ₹15,00,000) while the base amounts were paise, so it
 * massively over-deducted (finding F15). NOTE: this statutory logic belongs
 * server-side — the payroll compute should route through the backend
 * (POST /api/payroll/runs). Kept here, corrected, until that migration lands.
 *
 * PENDING (roadmap R2.3/R3.1 — FY-versioned rules): parameters here are FY
 * 2024-25 and must be updated to the current financial year (Budget 2025 revised
 * the new-regime slabs, standard deduction and §87A ceiling from FY 2025-26) —
 * across the backend engines too, so both stay in step. It also omits surcharge
 * (>₹50L taxable) and §80CCD(2)/§192(2B) declarations; this is a labelled monthly
 * ESTIMATE, trued up in the return.
 */
function monthlyTdsPaiseNewRegime(annualGrossPaise: number): number {
  const STD_DEDUCTION = 7_500_000;   // ₹75,000 in paise (new regime)
  const REBATE_CEIL = 70_000_000;    // ₹7,00,000 taxable in paise (§87A)
  const taxable = Math.max(0, annualGrossPaise - STD_DEDUCTION);
  if (taxable <= REBATE_CEIL) return 0;

  // Cumulative base tax (paise) at each slab floor + marginal rate above it.
  let tax: number;
  if (taxable > 150_000_000)      tax = 14_000_000 + Math.floor((taxable - 150_000_000) * 30 / 100);
  else if (taxable > 120_000_000) tax =  8_000_000 + Math.floor((taxable - 120_000_000) * 20 / 100);
  else if (taxable > 100_000_000) tax =  5_000_000 + Math.floor((taxable - 100_000_000) * 15 / 100);
  else                            tax =  2_000_000 + Math.floor((taxable -  70_000_000) * 10 / 100);

  // §87A marginal relief: tax cannot exceed the income above the ₹7,00,000 ceiling.
  tax = Math.min(tax, taxable - REBATE_CEIL);
  tax = tax + Math.floor(tax * 4 / 100);   // 4% health & education cess
  return Math.floor(tax / 12);
}

/**
 * Compute payroll for one employee — all integer paise arithmetic.
 * IT Act Section 192: TDS on salary via new-regime basic slab rates.
 * ESI Act: employee 0.75%, employer 3.25% of gross (gross <= Rs 21,000/month).
 * EPF Act: PF employee 12% of basic, capped Rs 1,800/month.
 */
function computeSlip(emp: Employee, ptState: string): {
  gross: number; pf: number; esi: number; pt: number; tds: number; net: number;
} {
  const basic = emp.basic_paise;
  const hra = Math.round(basic * emp.hra_percent / 100);
  const da = Math.round(basic * emp.da_percent / 100);
  const gross = basic + hra + da + emp.other_allowances_paise;

  // PF: 12% of basic, max Rs 1,800/month (EPF Act)
  let pf = 0;
  if (emp.pf_applicable) {
    pf = Math.min(Math.round(basic * 12 / 100), 180000);
  }

  // ESI: 0.75% of gross if gross <= Rs 21,000/month (ESI Act)
  let esi = 0;
  if (emp.esi_applicable && gross <= 2100000) {
    esi = Math.round(gross * 75 / 10000); // 0.75%
  }

  // Professional Tax by state
  let pt = 0;
  if (ptState === "MH" && gross > 1000000) {
    pt = 20000; // Rs 200 in paise
  } else if (ptState === "KA" && gross > 1500000) {
    pt = 20000;
  } else if (ptState === "WB" && gross > 1000000) {
    pt = 20000;
  } else if (ptState === "TN" && gross > 2100000) {
    pt = 20800;
  }

  // TDS estimate — IT Act §192, new regime (FY 2024-25). Integer paise; see
  // monthlyTdsPaiseNewRegime for the slab/rebate/cess logic and the F15 fix note.
  const tds = monthlyTdsPaiseNewRegime(gross * 12);

  const net = gross - pf - esi - pt - tds;
  return { gross, pf, esi, pt, tds, net };
}

const PT_STATES = [
  { code: "MH", label: "Maharashtra — Rs 200/month if > Rs 10,000" },
  { code: "KA", label: "Karnataka — Rs 200/month if > Rs 15,000" },
  { code: "WB", label: "West Bengal — Rs 200/month if > Rs 10,000" },
  { code: "TN", label: "Tamil Nadu — Rs 208/month if > Rs 21,000" },
  { code: "NONE", label: "No Professional Tax" },
];

const INSTALL_SQL = `-- Run in Supabase SQL editor:
CREATE TABLE IF NOT EXISTS payroll_employees (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL,
  client_id UUID NOT NULL,
  name TEXT NOT NULL,
  pan TEXT,
  designation TEXT,
  basic_paise BIGINT NOT NULL DEFAULT 0,
  hra_percent NUMERIC(5,2) NOT NULL DEFAULT 0,
  da_percent NUMERIC(5,2) NOT NULL DEFAULT 0,
  other_allowances_paise BIGINT NOT NULL DEFAULT 0,
  pf_applicable BOOLEAN NOT NULL DEFAULT false,
  esi_applicable BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS payroll_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL,
  client_id UUID NOT NULL,
  month TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  generated_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS payroll_slips (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id UUID NOT NULL REFERENCES payroll_runs(id),
  employee_id UUID NOT NULL REFERENCES payroll_employees(id),
  gross_paise BIGINT NOT NULL,
  pf_employee_paise BIGINT NOT NULL DEFAULT 0,
  esi_employee_paise BIGINT NOT NULL DEFAULT 0,
  pt_paise BIGINT NOT NULL DEFAULT 0,
  tds_paise BIGINT NOT NULL DEFAULT 0,
  net_paise BIGINT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);`;

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
    description: "Quarterly TDS return on salary — IT Act Section 192 — filed via TRACES/NSDL",
    dueDate: tdsDue,
    status: getDueDateStatus(tdsDue, today),
    portal: "TRACES / NSDL",
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

/**
 * Generate PF ECR text in EPFO-specified tab/tilde-separated format.
 * Format: MEMBER_ID~MEMBER_NAME~GROSS_WAGES~EPF_WAGES~EPS_WAGES~EDLI_WAGES~
 *         EPF_CONTRI_REMITTED~EPS_CONTRI_REMITTED~EPF_EPS_DIFF_REMITTED~NCP_DAYS~REFUND_OF_ADVANCES
 * EPF Act: employee + employer 12% of basic each; EPS 8.33% of basic (capped Rs 1,250/month)
 */
function generatePfEcr(slips: PayrollSlip[]): string {
  const header = "MEMBER_ID~MEMBER_NAME~GROSS_WAGES~EPF_WAGES~EPS_WAGES~EDLI_WAGES~EPF_CONTRI_REMITTED~EPS_CONTRI_REMITTED~EPF_EPS_DIFF_REMITTED~NCP_DAYS~REFUND_OF_ADVANCES";
  const rows = slips
    .filter(s => s.employee?.pf_applicable)
    .map((s, idx) => {
      const emp = s.employee!;
      // All amounts in whole rupees (EPFO expects rupees, not paise)
      const grossRs = Math.floor(s.gross_paise / 100);
      const basicRs = Math.floor(emp.basic_paise / 100);
      // EPF wages = basic (EPF Act)
      const epfWages = basicRs;
      // EPS wages = basic capped at Rs 15,000 (EPF Act Schedule)
      const epsWages = Math.min(basicRs, 15000);
      // EDLI wages same as EPF wages capped at Rs 15,000
      const edliWages = Math.min(basicRs, 15000);
      // Employee EPF contribution = 12% of basic
      const epfContri = Math.floor(basicRs * 12 / 100);
      // EPS employer contribution = 8.33% of basic capped Rs 1,250
      const epsContri = Math.min(Math.floor(epsWages * 833 / 10000), 1250);
      // EPF-EPS diff = employee epf - eps contri (remaining goes to EPF)
      const epfEpsDiff = epfContri - epsContri;
      // Member ID: use PAN if available, else generate a placeholder
      const memberId = emp.pan || `EMP${String(idx + 1).padStart(4, "0")}`;
      return `${memberId}~${emp.name}~${grossRs}~${epfWages}~${epsWages}~${edliWages}~${epfContri}~${epsContri}~${epfEpsDiff}~0~0`;
    });
  return [header, ...rows].join("\n");
}

/**
 * Generate ESI Statement CSV.
 * ESI Act: employee 0.75%, employer 3.25% of gross for employees earning <= Rs 21,000/month.
 */
function generateEsiStatement(slips: PayrollSlip[], month: string): string {
  const header = "Employee Name,PAN,Gross Wages (Rs),ESI Wages (Rs),Employee Contribution (0.75%),Employer Contribution (3.25%),Total Contribution";
  const rows = slips
    .filter(s => s.employee?.esi_applicable && s.gross_paise <= 2100000)
    .map(s => {
      const emp = s.employee!;
      const grossRs = Math.floor(s.gross_paise / 100);
      const empContri = Math.floor(s.gross_paise * 75 / 10000) / 100; // 0.75% in rupees
      const emplrContri = Math.floor(s.gross_paise * 325 / 10000) / 100; // 3.25% in rupees
      const total = (empContri + emplrContri).toFixed(2);
      return `"${emp.name}","${emp.pan || ""}",${grossRs},${grossRs},${empContri.toFixed(2)},${emplrContri.toFixed(2)},${total}`;
    });
  const footer = `\n"# ESI Return — Period: ${month}"\n"# Filed with ESIC Portal"\n"# ESI Act: Employee 0.75% + Employer 3.25% of gross wages"`;
  return [header, ...rows, footer].join("\n");
}

/**
 * Generate TDS 24Q summary CSV.
 * IT Act Section 192 — TDS on salary.
 * # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
 */
function generateTds24QData(slips: PayrollSlip[], quarter: string): string {
  // # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
  const header = `# TDS 24Q Summary — ${quarter}\n# IT Act Section 192 — TDS on Salary\n# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT\n# This data must be reviewed and filed via TRACES/NSDL by a qualified CA\n`;
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
  const blob = new Blob([content], { type: mimeType });
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

// ── Add Employee Modal ────────────────────────────────────────────────────

function AddEmployeeModal({
  clients,
  firmId,
  onClose,
  onSaved,
}: {
  clients: Client[];
  firmId: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    client_id: clients[0]?.id ?? "",
    name: "",
    pan: "",
    designation: "",
    basic_rs: "",
    hra_percent: "40",
    da_percent: "10",
    other_rs: "0",
    pf_applicable: false,
    esi_applicable: false,
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  async function save() {
    if (!form.name || !form.basic_rs) { setErr("Name and Basic Salary are required."); return; }
    setSaving(true);
    const sb = getSupabaseClient();
    const { error } = await sb.from("payroll_employees").insert({
      firm_id: firmId,
      client_id: form.client_id,
      name: form.name,
      pan: form.pan.toUpperCase(),
      designation: form.designation,
      basic_paise: rsToP(parseFloat(form.basic_rs) || 0),
      hra_percent: parseFloat(form.hra_percent) || 0,
      da_percent: parseFloat(form.da_percent) || 0,
      other_allowances_paise: rsToP(parseFloat(form.other_rs) || 0),
      pf_applicable: form.pf_applicable,
      esi_applicable: form.esi_applicable,
    });
    setSaving(false);
    if (error) { setErr(error.message); return; }
    onSaved();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0F172A]/60">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-[#0F172A]">Add Employee</h2>
          <button onClick={onClose}><X size={16} /></button>
        </div>
        {err && <p className="text-red-600 text-sm mb-3">{err}</p>}
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2">
            <label className="block text-xs font-medium text-[#334155] mb-1">Client</label>
            <div className="w-full">
              <ClientLookup
                clients={clients}
                value={form.client_id}
                onChange={(id) => setForm(f => ({ ...f, client_id: id }))}
                ariaLabel="Client"
                placeholder="Select client…"
              />
            </div>
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
        </div>
        <div className="flex gap-2 justify-end mt-5">
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={save} disabled={saving}>{saving ? "Saving..." : "Add Employee"}</Button>
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

  const clientRuns = runs.filter(r => r.client_id === selectedClientId);

  function slipsForRun(runId: string): PayrollSlip[] {
    return slips.filter(s => s.run_id === runId);
  }

  function handleGeneratePfEcr(run: PayrollRun) {
    const runSlips = slipsForRun(run.id);
    const content = generatePfEcr(runSlips);
    downloadFile(content, `PF_ECR_${run.month}.txt`, "text/plain");
  }

  function handleGenerateEsiStatement(run: PayrollRun) {
    const runSlips = slipsForRun(run.id);
    const content = generateEsiStatement(runSlips, run.month);
    downloadFile(content, `ESI_Statement_${run.month}.csv`, "text/csv");
  }

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
                      const pfCount = runSlips.filter(s => s.employee?.pf_applicable).length;
                      const esiCount = runSlips.filter(
                        s => s.employee?.esi_applicable && s.gross_paise <= 2100000,
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
                                disabled={pfCount === 0}
                                title={pfCount === 0 ? "No PF-applicable employees this month" : `Generate PF ECR for ${pfCount} employees`}
                              >
                                <Download size={12} />
                                PF ECR
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                className="flex items-center gap-1 text-xs"
                                onClick={() => handleGenerateEsiStatement(run)}
                                disabled={esiCount === 0}
                                title={esiCount === 0 ? "No ESI-applicable employees this month" : `Generate ESI statement for ${esiCount} employees`}
                              >
                                <Download size={12} />
                                ESI
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
                  <p>Quarterly TDS data per IT Act Section 192. Must be filed via TRACES/NSDL. CA review mandatory before submission.</p>
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

export default function PayrollPage() {
  const [firmId, setFirmId] = useState<string | null>(null);
  const [tablesError, setTablesError] = useState(false);
  const [clients, setClients] = useState<Client[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [runs, setRuns] = useState<PayrollRun[]>([]);
  const [slips, setSlips] = useState<PayrollSlip[]>([]);
  const [loading, setLoading] = useState(true);

  const [runClientId, setRunClientId] = useState("");
  const [runMonth, setRunMonth] = useState(() => new Date().toISOString().slice(0, 7));
  const [ptState, setPtState] = useState("MH");
  const [runEmployees, setRunEmployees] = useState<Employee[]>([]);
  const [generating, setGenerating] = useState(false);

  const [statMonth, setStatMonth] = useState(() => new Date().toISOString().slice(0, 7));
  const [statClientId, setStatClientId] = useState("");
  const [statSlips, setStatSlips] = useState<PayrollSlip[]>([]);

  const [showAdd, setShowAdd] = useState(false);
  const [showImportEmp, setShowImportEmp] = useState(false);
  const [viewSlip, setViewSlip] = useState<PayrollSlip | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const fid = await getFirmId();
      setFirmId(fid);
      const sb = getSupabaseClient();
      const [clientsRes, empRes, runsRes] = await Promise.all([
        sb.from("clients").select("id, client_name").eq("firm_id", fid),
        sb.from("payroll_employees").select("*").eq("firm_id", fid),
        sb.from("payroll_runs").select("*").eq("firm_id", fid).order("generated_at", { ascending: false }),
      ]);
      if (empRes.error?.message?.includes("does not exist")) {
        setTablesError(true);
        setLoading(false);
        return;
      }
      setClients(clientsRes.data ?? []);
      setEmployees(empRes.data ?? []);
      setRuns(runsRes.data ?? []);

      if (runsRes.data && runsRes.data.length > 0) {
        const runIds = runsRes.data.map(r => r.id);
        const slipsRes = await sb.from("payroll_slips").select("*").in("run_id", runIds);
        const rawSlips: PayrollSlip[] = slipsRes.data ?? [];
        const enriched = rawSlips.map(s => ({
          ...s,
          employee: (empRes.data ?? []).find((e: Employee) => e.id === s.employee_id),
          run: runsRes.data!.find(r => r.id === s.run_id),
        }));
        setSlips(enriched);
      }
    } catch { /* not authenticated */ }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (runClientId) {
      setRunEmployees(employees.filter(e => e.client_id === runClientId));
    }
  }, [runClientId, employees]);

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
    if (!firmId || !runClientId || runEmployees.length === 0) return;
    setGenerating(true);
    const sb = getSupabaseClient();
    const { data: run, error: runErr } = await sb.from("payroll_runs").insert({
      firm_id: firmId,
      client_id: runClientId,
      month: runMonth,
      status: "generated",
    }).select().single();
    if (runErr || !run) { setGenerating(false); return; }

    const slipRows = runEmployees.map(emp => {
      const calc = computeSlip(emp, ptState);
      return {
        run_id: run.id,
        employee_id: emp.id,
        gross_paise: calc.gross,
        pf_employee_paise: calc.pf,
        esi_employee_paise: calc.esi,
        pt_paise: calc.pt,
        tds_paise: calc.tds,
        net_paise: calc.net,
      };
    });
    await sb.from("payroll_slips").insert(slipRows);
    setGenerating(false);
    load();
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
  ], []);

  // The payroll_employees model has no active/inactive status field; PF/ESI
  // applicability are the meaningful boolean facets, so filter on those.
  const employeeFilters: FilterDef<Employee>[] = useMemo(() => [
    { key: "pf_applicable", label: "PF", type: "boolean", accessor: (e) => e.pf_applicable, trueLabel: "Applicable", falseLabel: "Not applicable" },
    { key: "esi_applicable", label: "ESI", type: "boolean", accessor: (e) => e.esi_applicable, trueLabel: "Applicable", falseLabel: "Not applicable" },
  ], []);

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

  if (tablesError) {
    return (
      <div className="min-h-screen bg-[#F8FAFC] p-8">
        <Card className="max-w-2xl mx-auto">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <AlertCircle size={18} className="text-amber-500" />
              Install Payroll Tables
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-[#475569] mb-4">The payroll tables do not exist yet. Run this SQL in your Supabase dashboard:</p>
            <pre className="bg-gray-900 text-green-400 p-4 rounded-lg text-xs overflow-auto whitespace-pre-wrap">{INSTALL_SQL}</pre>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#F8FAFC] p-8">
      {showAdd && firmId && (
        <AddEmployeeModal
          clients={clients}
          firmId={firmId}
          onClose={() => setShowAdd(false)}
          onSaved={() => { setShowAdd(false); load(); }}
        />
      )}
      {viewSlip && <PayslipModal slip={viewSlip} onClose={() => setViewSlip(null)} />}

      <div className="max-w-6xl mx-auto">
        <div className="mb-6 flex items-start justify-between flex-wrap gap-4">
          <div>
            <h1 className="text-2xl font-bold text-[#0F172A]">Payroll</h1>
            <p className="text-sm text-[#64748B] mt-0.5">IT Act Section 192 &middot; EPF Act &middot; ESI Act</p>
          </div>
          <Link href="/payroll/reports">
            <Button variant="outline" className="flex items-center gap-1.5">
              <BarChart2 size={15} />Reports
            </Button>
          </Link>
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
                  <Button size="sm" onClick={() => setShowAdd(true)} className="flex items-center gap-1.5">
                    <Plus size={14} />Add Employee
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                <DataTable
                  data={employees}
                  columns={employeeColumns}
                  filters={employeeFilters}
                  getRowId={(e) => e.id}
                  loading={loading}
                  onRefresh={load}
                  searchPlaceholder="Search by name, PAN, or designation…"
                  initialSort={{ key: "name", dir: "asc" }}
                  exportFilename="employees"
                  persistKey="payroll.employees"
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
                  <div>
                    <label className="block text-xs font-medium text-[#334155] mb-1">PT State</label>
                    <select className="border rounded-lg px-3 py-2 text-sm" value={ptState} onChange={e => setPtState(e.target.value)}>
                      {PT_STATES.map(s => <option key={s.code} value={s.code}>{s.label}</option>)}
                    </select>
                  </div>
                  <Button
                    onClick={generatePayslips}
                    disabled={generating || runEmployees.length === 0}
                    className="flex items-center gap-1.5"
                  >
                    <Play size={14} />{generating ? "Generating..." : "Generate Payslips"}
                  </Button>
                </div>
              </CardContent>
            </Card>
            {runEmployees.length === 0 ? (
              <Card><CardContent className="py-12 text-center text-[#94A3B8]">No employees for this client.</CardContent></Card>
            ) : (
              <Card>
                <CardContent className="p-0">
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b text-xs font-medium text-[#64748B] uppercase tracking-wide">
                          <th className="text-left py-3 px-4">Employee</th>
                          <th className="text-right py-3 px-4">Gross</th>
                          <th className="text-right py-3 px-4">PF Emp</th>
                          <th className="text-right py-3 px-4">ESI Emp</th>
                          <th className="text-right py-3 px-4">PT</th>
                          <th className="text-right py-3 px-4">TDS (Sec 192)</th>
                          <th className="text-right py-3 px-4">Net Pay</th>
                        </tr>
                      </thead>
                      <tbody>
                        {runEmployees.map(emp => {
                          const c = computeSlip(emp, ptState);
                          return (
                            <tr key={emp.id} className="border-b hover:bg-[#F8FAFC]">
                              <td className="py-3 px-4 font-medium">{emp.name}</td>
                              <td className="py-3 px-4 text-right font-mono">{fmtRs(c.gross)}</td>
                              <td className="py-3 px-4 text-right font-mono text-red-600">{fmtRs(c.pf)}</td>
                              <td className="py-3 px-4 text-right font-mono text-red-600">{fmtRs(c.esi)}</td>
                              <td className="py-3 px-4 text-right font-mono text-red-600">{fmtRs(c.pt)}</td>
                              <td className="py-3 px-4 text-right font-mono text-red-600">{fmtRs(c.tds)}</td>
                              <td className="py-3 px-4 text-right font-mono font-semibold text-green-700">{fmtRs(c.net)}</td>
                            </tr>
                          );
                        })}
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
              const emps = statSlips.map(s => s.employee).filter(Boolean) as Employee[];
              let totalPfEmp = 0, totalPfEmployer = 0, totalEsiEmp = 0, totalEsiEmployer = 0, totalPt = 0, totalTds = 0;
              statSlips.forEach((s, i) => {
                const emp = emps[i];
                totalPfEmp += s.pf_employee_paise;
                totalPfEmployer += emp ? Math.min(Math.round(emp.basic_paise * 12 / 100), 180000) : 0;
                totalEsiEmp += s.esi_employee_paise;
                totalEsiEmployer += (emp && emp.esi_applicable && s.gross_paise <= 2100000)
                  ? Math.round(s.gross_paise * 325 / 10000) : 0;
                totalPt += s.pt_paise;
                totalTds += s.tds_paise;
              });
              const edli = Math.round(totalPfEmployer * 5 / 1000);
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

      {showImportEmp && firmId && (
        <CsvImportModal
          title="Import Employees from CSV"
          columns={EMPLOYEE_IMPORT_COLUMNS}
          templateFilename="practicesync-employees-template.xlsx"
          onClose={() => setShowImportEmp(false)}
          onImport={async (rows: ImportRow[]) => {
            const sb = getSupabaseClient();
            let imported = 0;
            const errors: string[] = [];
            for (const row of rows) {
              const client = clients.find(c => c.client_name.toLowerCase() === row.client_name?.toLowerCase());
              if (!client) { errors.push(`Employee "${row.name}": client "${row.client_name}" not found`); continue; }
              const { error } = await sb.from("payroll_employees").insert({
                firm_id: firmId,
                client_id: client.id,
                name: row.name,
                pan: row.pan.toUpperCase(),
                designation: row.designation || "",
                basic_paise: Math.round(parseFloat(row.basic_rs ?? "0") * 100),
                hra_percent: parseFloat(row.hra_percent ?? "40"),
                da_percent: parseFloat(row.da_percent ?? "0"),
                other_allowances_paise: Math.round(parseFloat(row.other_allowances_rs ?? "0") * 100),
                pf_applicable: row.pf_applicable?.toLowerCase() !== "false",
                esi_applicable: row.esi_applicable?.toLowerCase() === "true",
              });
              if (error) errors.push(`${row.name}: ${error.message}`);
              else imported++;
            }
            if (imported > 0) load();
            return { imported, errors };
          }}
          validateRow={(row) => {
            const errs: string[] = [];
            if (!/^[A-Z]{5}[0-9]{4}[A-Z]$/.test(row.pan?.toUpperCase() ?? "")) errs.push("Invalid PAN format");
            if (row.basic_rs && isNaN(parseFloat(row.basic_rs))) errs.push("basic_rs must be a number");
            return errs;
          }}
        />
      )}
    </div>
  );
}
