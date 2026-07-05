"use client";

/**
 * GSTR-2A vs Purchase Register ITC Reconciliation
 *
 * CGST Act Section 16 — ITC eligibility conditions
 * CGST Rule 36(4) — ITC restricted to 105% of eligible ITC appearing in GSTR-2A/2B
 * Reconciliation mandatory for accurate ITC claims
 *
 * All monetary values stored and computed in integer paise (never floating point).
 * CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
 */

import { useState, useEffect, useCallback, useRef } from "react";
import {
  ChevronLeft,
  Upload,
  Download,
  CheckCircle,
  AlertCircle,
  Info,
  FileText,
  Users,
  BookOpen,
} from "lucide-react";
import Link from "next/link";
import * as XLSX from "xlsx";
import { getClients } from "@/lib/data/clients";
import type { Client } from "@/lib/types";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { todayLocalISO } from "@/lib/dateMath";

// ─── Types ────────────────────────────────────────────────────────────────────

/** One invoice row — used for both purchase register and GSTR-2A */
interface InvoiceRow {
  supplier_gstin: string;
  supplier_name: string;
  invoice_number: string;
  invoice_date: string;
  /** Integer paise — CGST Act integer arithmetic requirement */
  taxable_value_paise: number;
  igst_paise: number;
  cgst_paise: number;
  sgst_paise: number;
}

type ReconStatus = "matched" | "mismatch" | "missing_in_2a" | "extra_in_2a";

/** One reconciled line — result of matching Purchase Register vs GSTR-2A */
interface ReconRow {
  key: string; // supplier_gstin + "|" + invoice_number (normalised)
  supplier_gstin: string;
  supplier_name: string;
  invoice_number: string;
  invoice_date: string;
  status: ReconStatus;

  // Books side (purchase register)
  books_taxable: number | null; // paise
  books_igst: number | null;
  books_cgst: number | null;
  books_sgst: number | null;

  // GSTR-2A side
  gstr2a_taxable: number | null; // paise
  gstr2a_igst: number | null;
  gstr2a_cgst: number | null;
  gstr2a_sgst: number | null;

  // Difference (books - 2A), non-zero only for "mismatch"
  diff_igst: number;
  diff_cgst: number;
  diff_sgst: number;
}

// ─── Constants ────────────────────────────────────────────────────────────────

const MONTHS = [
  { value: "01", label: "January" },
  { value: "02", label: "February" },
  { value: "03", label: "March" },
  { value: "04", label: "April" },
  { value: "05", label: "May" },
  { value: "06", label: "June" },
  { value: "07", label: "July" },
  { value: "08", label: "August" },
  { value: "09", label: "September" },
  { value: "10", label: "October" },
  { value: "11", label: "November" },
  { value: "12", label: "December" },
];

const _today = new Date(todayLocalISO() + "T00:00:00");
const CURRENT_YEAR = _today.getFullYear();
const YEAR_OPTIONS: number[] = [];
for (let y = CURRENT_YEAR; y >= CURRENT_YEAR - 4; y--) {
  YEAR_OPTIONS.push(y);
}

// ─── CSV Columns definition ───────────────────────────────────────────────────

const CSV_COLUMNS = [
  "supplier_gstin",
  "supplier_name",
  "invoice_number",
  "invoice_date",
  "taxable_value",
  "igst",
  "cgst",
  "sgst",
] as const;

const CSV_TEMPLATE_HEADER = CSV_COLUMNS.join(",");
const CSV_TEMPLATE_SAMPLE =
  "27AABCU9603R1ZX,Supplier Co Ltd,INV/2025/001,01-04-2025,100000,18000,0,0";

// ─── Paise helpers ────────────────────────────────────────────────────────────

/** Parse a rupee string (may have commas) → integer paise. NEVER float. */
function toPaise(val: string | number | undefined | null): number {
  if (val === null || val === undefined || val === "") return 0;
  const s = String(val).replace(/,/g, "").trim();
  const f = parseFloat(s);
  if (isNaN(f)) return 0;
  // Round to nearest paise — avoids floating point drift
  return Math.round(f * 100);
}

/** Format paise → Indian rupee string (en-IN locale) */
function fmtRupees(paise: number | null): string {
  if (paise === null) return "—";
  const rupees = paise / 100;
  return rupees.toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

// ─── CSV Parser ───────────────────────────────────────────────────────────────

function parseLine(line: string): string[] {
  const result: string[] = [];
  let cur = "";
  let inQ = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (inQ && line[i + 1] === '"') { cur += '"'; i++; }
      else inQ = !inQ;
    } else if (ch === "," && !inQ) {
      result.push(cur.trim());
      cur = "";
    } else {
      cur += ch ?? "";
    }
  }
  result.push(cur.trim());
  return result;
}

function parseCsv(text: string): { rows: InvoiceRow[]; error: string | null } {
  const lines = text.split(/\r?\n/).filter((l) => l.trim() && !l.trim().startsWith("#"));
  if (lines.length < 2) {
    return { rows: [], error: "CSV must have a header row and at least one data row." };
  }

  const headers = parseLine(lines[0]!).map((h) =>
    h.toLowerCase().trim().replace(/\s+/g, "_")
  );

  const required = ["supplier_gstin", "invoice_number", "taxable_value"];
  const missing = required.filter((c) => !headers.includes(c));
  if (missing.length > 0) {
    return {
      rows: [],
      error: `Missing required columns: ${missing.join(", ")}. Expected: ${CSV_TEMPLATE_HEADER}`,
    };
  }

  const idx = (col: string) => headers.indexOf(col);
  const rows: InvoiceRow[] = [];

  for (let i = 1; i < lines.length; i++) {
    const cols = parseLine(lines[i]!);
    const get = (col: string): string => (cols[idx(col)] ?? "").trim();

    const supplier_gstin = get("supplier_gstin").toUpperCase();
    const invoice_number = get("invoice_number");
    if (!supplier_gstin || !invoice_number) continue;

    rows.push({
      supplier_gstin,
      supplier_name: get("supplier_name"),
      invoice_number,
      invoice_date: get("invoice_date"),
      taxable_value_paise: toPaise(get("taxable_value")),
      igst_paise: toPaise(get("igst")),
      cgst_paise: toPaise(get("cgst")),
      sgst_paise: toPaise(get("sgst")),
    });
  }

  return { rows, error: null };
}

// ─── Reconciliation Engine ────────────────────────────────────────────────────

/**
 * Match Purchase Register vs GSTR-2A by supplier_gstin + invoice_number.
 *
 * CGST Act Section 16 — ITC eligibility conditions
 * CGST Rule 36(4) — ITC restricted to 105% of eligible ITC in GSTR-2A/2B
 *
 * Sections:
 *   matched        — invoice in both, amounts match (green)
 *   mismatch       — invoice in both but amounts differ (amber)
 *   missing_in_2a  — in books but supplier hasn't filed in GSTR-2A (red)
 *   extra_in_2a    — in GSTR-2A but not in books (blue)
 */
function reconcile(books: InvoiceRow[], gstr2a: InvoiceRow[]): ReconRow[] {
  const booksMap = new Map<string, InvoiceRow>();
  for (const r of books) {
    const key = `${r.supplier_gstin.toUpperCase()}|${r.invoice_number.toUpperCase().trim()}`;
    booksMap.set(key, r);
  }

  const gstr2aMap = new Map<string, InvoiceRow>();
  for (const r of gstr2a) {
    const key = `${r.supplier_gstin.toUpperCase()}|${r.invoice_number.toUpperCase().trim()}`;
    gstr2aMap.set(key, r);
  }

  const allKeys = Array.from(
    new Set([...Array.from(booksMap.keys()), ...Array.from(gstr2aMap.keys())])
  );

  const result: ReconRow[] = [];

  for (const key of allKeys) {
    const b = booksMap.get(key);
    const g = gstr2aMap.get(key);
    const [gstin, invNo] = key.split("|") as [string, string];

    let status: ReconStatus;
    let diff_igst = 0;
    let diff_cgst = 0;
    let diff_sgst = 0;

    if (b && g) {
      // Both sides — check if tax amounts match (within 1 paise per head tolerance)
      diff_igst = b.igst_paise - g.igst_paise;
      diff_cgst = b.cgst_paise - g.cgst_paise;
      diff_sgst = b.sgst_paise - g.sgst_paise;
      const totalDiff = Math.abs(diff_igst) + Math.abs(diff_cgst) + Math.abs(diff_sgst);
      status = totalDiff <= 3 ? "matched" : "mismatch";
    } else if (b && !g) {
      status = "missing_in_2a";
    } else {
      status = "extra_in_2a";
    }

    result.push({
      key,
      supplier_gstin: gstin,
      supplier_name: b?.supplier_name ?? g?.supplier_name ?? "",
      invoice_number: invNo,
      invoice_date: b?.invoice_date ?? g?.invoice_date ?? "",
      status,
      books_taxable: b?.taxable_value_paise ?? null,
      books_igst: b?.igst_paise ?? null,
      books_cgst: b?.cgst_paise ?? null,
      books_sgst: b?.sgst_paise ?? null,
      gstr2a_taxable: g?.taxable_value_paise ?? null,
      gstr2a_igst: g?.igst_paise ?? null,
      gstr2a_cgst: g?.cgst_paise ?? null,
      gstr2a_sgst: g?.sgst_paise ?? null,
      diff_igst,
      diff_cgst,
      diff_sgst,
    });
  }

  // Sort: matched, mismatch, missing_in_2a, extra_in_2a
  const ORDER: ReconStatus[] = ["matched", "mismatch", "missing_in_2a", "extra_in_2a"];
  result.sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status));
  return result;
}

// ─── Excel Export ─────────────────────────────────────────────────────────────

/**
 * Export reconciliation as Excel with 4 sheets.
 * Uses xlsx library — all amounts in rupees (paise / 100) for readability.
 */
function exportExcel(rows: ReconRow[], period: string, clientName: string) {
  const toRs = (p: number | null): string =>
    p === null ? "" : (p / 100).toFixed(2);

  const headers = [
    "Supplier GSTIN",
    "Supplier Name",
    "Invoice Number",
    "Invoice Date",
    "Books Taxable (₹)",
    "Books IGST (₹)",
    "Books CGST (₹)",
    "Books SGST (₹)",
    "GSTR-2A Taxable (₹)",
    "GSTR-2A IGST (₹)",
    "GSTR-2A CGST (₹)",
    "GSTR-2A SGST (₹)",
    "Diff IGST (₹)",
    "Diff CGST (₹)",
    "Diff SGST (₹)",
  ];

  const toSheetRow = (r: ReconRow): (string | number)[] => [
    r.supplier_gstin,
    r.supplier_name,
    r.invoice_number,
    r.invoice_date,
    toRs(r.books_taxable),
    toRs(r.books_igst),
    toRs(r.books_cgst),
    toRs(r.books_sgst),
    toRs(r.gstr2a_taxable),
    toRs(r.gstr2a_igst),
    toRs(r.gstr2a_cgst),
    toRs(r.gstr2a_sgst),
    toRs(r.diff_igst),
    toRs(r.diff_cgst),
    toRs(r.diff_sgst),
  ];

  const makeSheet = (filtered: ReconRow[]) =>
    XLSX.utils.aoa_to_sheet([headers, ...filtered.map(toSheetRow)]);

  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, makeSheet(rows.filter((r) => r.status === "matched")), "Matched");
  XLSX.utils.book_append_sheet(wb, makeSheet(rows.filter((r) => r.status === "mismatch")), "Mismatch");
  XLSX.utils.book_append_sheet(wb, makeSheet(rows.filter((r) => r.status === "missing_in_2a")), "Missing in 2A");
  XLSX.utils.book_append_sheet(wb, makeSheet(rows.filter((r) => r.status === "extra_in_2a")), "Extra in 2A");

  const filename = `GSTR2A_Recon_${clientName.replace(/\s+/g, "_")}_${period.replace(/\s+/g, "_")}.xlsx`;
  XLSX.writeFile(wb, filename);
}

// ─── Template download ────────────────────────────────────────────────────────

function downloadTemplate(filename: string) {
  const csv = [
    "# PracticeSync GSTR-2A / Purchase Register CSV Template",
    "# Required: supplier_gstin, invoice_number, taxable_value",
    "# All amounts in Indian Rupees (decimal)",
    CSV_TEMPLATE_HEADER,
    CSV_TEMPLATE_SAMPLE,
  ].join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ─── Upload Panel Component ───────────────────────────────────────────────────

interface UploadPanelProps {
  title: string;
  subtitle: string;
  templateFilename: string;
  fileName: string | null;
  rowCount: number;
  error: string | null;
  onFile: (text: string, name: string) => void;
  note?: string;
  accent: "green" | "blue";
}

function UploadPanel({
  title,
  subtitle,
  templateFilename,
  fileName,
  rowCount,
  error,
  onFile,
  note,
  accent,
}: UploadPanelProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    const file = files[0]!;
    const reader = new FileReader();
    reader.onload = (e) => onFile(e.target?.result as string, file.name);
    reader.readAsText(file);
  }

  const borderClass =
    dragging
      ? "border-blue-400 bg-blue-50/40"
      : fileName
      ? accent === "green"
        ? "border-green-400 bg-green-50/20"
        : "border-blue-400 bg-blue-50/20"
      : error
      ? "border-red-300 bg-red-50/10"
      : "border-[#E2E8F0] hover:border-blue-300 hover:bg-blue-50/10";

  return (
    <div className="bg-white rounded-xl border border-[#F1F5F9] p-5 space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-[#0F172A]">{title}</p>
          <p className="text-xs text-[#94A3B8] mt-0.5">{subtitle}</p>
        </div>
        <button
          type="button"
          onClick={() => downloadTemplate(templateFilename)}
          className="flex items-center gap-1 text-[10px] text-blue-600 hover:underline whitespace-nowrap"
        >
          <Download className="w-3 h-3" />
          Template
        </button>
      </div>

      <div
        className={`border-2 border-dashed rounded-xl px-4 py-6 flex flex-col items-center gap-2 cursor-pointer transition-colors ${borderClass}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); handleFiles(e.dataTransfer.files); }}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />
        {fileName ? (
          <>
            <CheckCircle className={`w-6 h-6 ${accent === "green" ? "text-green-500" : "text-blue-500"}`} />
            <p className="text-xs font-medium text-[#334155]">{fileName}</p>
            <p className="text-[10px] text-[#94A3B8]">{rowCount} invoices loaded · click to replace</p>
          </>
        ) : (
          <>
            <Upload className="w-6 h-6 text-[#CBD5E1]" />
            <p className="text-xs text-[#64748B]">Click or drag &amp; drop CSV</p>
          </>
        )}
        {error && (
          <p className="text-xs text-red-600 bg-red-50 rounded px-2 py-1 text-center">{error}</p>
        )}
      </div>

      {note && (
        <p className="text-[10px] text-[#94A3B8] bg-[#F8FAFC] rounded-lg px-3 py-2 leading-relaxed">
          {note}
        </p>
      )}
    </div>
  );
}

// ─── Status UI helpers ────────────────────────────────────────────────────────

const STATUS_LABEL: Record<ReconStatus, string> = {
  matched: "Matched",
  mismatch: "Mismatch",
  missing_in_2a: "Missing in 2A",
  extra_in_2a: "Extra in 2A",
};

const STATUS_BADGE: Record<ReconStatus, string> = {
  matched: "bg-green-100 text-green-700",
  mismatch: "bg-amber-100 text-amber-700",
  missing_in_2a: "bg-red-100 text-red-700",
  extra_in_2a: "bg-blue-100 text-blue-700",
};

const STATUS_ROW: Record<ReconStatus, string> = {
  matched: "hover:bg-green-50/30",
  mismatch: "bg-amber-50/20 hover:bg-amber-50/40",
  missing_in_2a: "bg-red-50/20 hover:bg-red-50/40",
  extra_in_2a: "bg-blue-50/10 hover:bg-blue-50/30",
};

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function GstReconciliationPage() {
  // Step 1: parameters
  const [clients, setClients] = useState<Client[]>([]);
  const [loadingClients, setLoadingClients] = useState(true);
  const [selectedClientId, setSelectedClientId] = useState("");
  const [selectedMonth, setSelectedMonth] = useState(
    String(_today.getMonth() + 1).padStart(2, "0") // current month as MM
  );
  const [selectedYear, setSelectedYear] = useState(String(CURRENT_YEAR));
  const [paramsLoaded, setParamsLoaded] = useState(false);

  // Step 2: file state
  const [booksFile, setBooksFile] = useState<string | null>(null);
  const [booksRows, setBooksRows] = useState<InvoiceRow[]>([]);
  const [booksError, setBooksError] = useState<string | null>(null);

  const [gstr2aFile, setGstr2aFile] = useState<string | null>(null);
  const [gstr2aRows, setGstr2aRows] = useState<InvoiceRow[]>([]);
  const [gstr2aError, setGstr2aError] = useState<string | null>(null);

  // Step 3: reconciliation
  const [reconRows, setReconRows] = useState<ReconRow[]>([]);
  const [filterStatus, setFilterStatus] = useState<ReconStatus | "all">("all");

  // Load clients
  useEffect(() => {
    getClients()
      .then((cls) => {
        setClients(cls);
        if (cls.length > 0 && cls[0]) setSelectedClientId(cls[0].id);
      })
      .catch(() => {})
      .finally(() => setLoadingClients(false));
  }, []);

  // Auto-reconcile whenever files change
  const runRecon = useCallback(() => {
    if (booksRows.length === 0 && gstr2aRows.length === 0) {
      setReconRows([]);
      return;
    }
    setReconRows(reconcile(booksRows, gstr2aRows));
  }, [booksRows, gstr2aRows]);

  useEffect(() => {
    runRecon();
  }, [runRecon]);

  function handleBooksFile(text: string, name: string) {
    setBooksFile(name);
    setBooksError(null);
    const { rows, error } = parseCsv(text);
    if (error) { setBooksError(error); setBooksRows([]); }
    else if (rows.length === 0) { setBooksError("No valid rows found."); setBooksRows([]); }
    else setBooksRows(rows);
  }

  function handleGstr2aFile(text: string, name: string) {
    setGstr2aFile(name);
    setGstr2aError(null);
    const { rows, error } = parseCsv(text);
    if (error) { setGstr2aError(error); setGstr2aRows([]); }
    else if (rows.length === 0) { setGstr2aError("No valid rows found."); setGstr2aRows([]); }
    else setGstr2aRows(rows);
  }

  // ── Summary maths (all in paise — CGST Act integer arithmetic) ──────────────
  const matched       = reconRows.filter((r) => r.status === "matched");
  const mismatches    = reconRows.filter((r) => r.status === "mismatch");
  const missingIn2a   = reconRows.filter((r) => r.status === "missing_in_2a");
  const extraIn2a     = reconRows.filter((r) => r.status === "extra_in_2a");

  const totalBooksITC = booksRows.reduce(
    (s, r) => s + r.igst_paise + r.cgst_paise + r.sgst_paise, 0
  );
  const totalGstr2aITC = gstr2aRows.reduce(
    (s, r) => s + r.igst_paise + r.cgst_paise + r.sgst_paise, 0
  );
  const matchedITC = matched.reduce(
    (s, r) => s + (r.gstr2a_igst ?? 0) + (r.gstr2a_cgst ?? 0) + (r.gstr2a_sgst ?? 0), 0
  );
  const diffITC = totalBooksITC - totalGstr2aITC;

  const displayRows =
    filterStatus === "all" ? reconRows : reconRows.filter((r) => r.status === filterStatus);

  const selectedClient = clients.find((c) => c.id === selectedClientId);
  const periodLabel = `${MONTHS.find((m) => m.value === selectedMonth)?.label ?? selectedMonth} ${selectedYear}`;
  // Return period in MMYYYY format (used for gstr2a_records table)
  const returnPeriod = `${selectedMonth}${selectedYear}`;

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-1.5 mb-1">
            <Link
              href="/gst"
              className="text-[#94A3B8] hover:text-[#475569] flex items-center gap-1 text-xs"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
              GST
            </Link>
          </div>
          <h1 className="text-xl font-semibold text-[#0F172A]">
            GSTR-2A vs Purchase Reconciliation
          </h1>
          <p className="text-sm text-[#64748B] mt-0.5">
            CGST Rule 36(4) · Section 16 — Reconcile purchase register against GSTR-2A to verify ITC claims
          </p>
        </div>
        {reconRows.length > 0 && (
          <button
            onClick={() => exportExcel(reconRows, periodLabel, selectedClient?.client_name ?? "Client")}
            className="flex items-center gap-1.5 text-xs bg-gray-800 text-white px-3 py-2 rounded-lg hover:bg-gray-900"
          >
            <Download className="w-3.5 h-3.5" />
            Export Excel
          </button>
        )}
      </div>

      {/* Info banner */}
      <div className="bg-blue-50 border border-blue-100 rounded-xl px-4 py-3 flex gap-2.5 text-xs text-blue-700">
        <Info className="w-4 h-4 shrink-0 mt-0.5" />
        <span>
          <strong>CGST Rule 36(4):</strong> ITC is restricted to 105% of eligible credit appearing in GSTR-2A/2B.
          Reconcile every period before filing GSTR-3B to avoid ITC reversal notices.{" "}
          {/* CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT */}
        </span>
      </div>

      {/* Step 1 — Select parameters */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] p-5 space-y-4">
        <div>
          <p className="text-sm font-semibold text-[#0F172A]">Step 1 — Select Parameters</p>
          <p className="text-xs text-[#94A3B8] mt-0.5">Choose client and return period, then upload files</p>
        </div>

        <div className="flex flex-wrap gap-4">
          {/* Client */}
          <div className="flex-1 min-w-[200px]">
            <label className="text-xs font-medium text-[#334155] block mb-1">
              <Users className="w-3 h-3 inline mr-1" />
              Client
            </label>
            {loadingClients ? (
              <div className="h-9 rounded-lg bg-[#F8FAFC] animate-pulse" />
            ) : clients.length === 0 ? (
              <p className="text-xs text-[#94A3B8] italic">No clients found</p>
            ) : (
              <div className="w-full">
                <ClientLookup
                  clients={clients}
                  value={selectedClientId}
                  onChange={setSelectedClientId}
                  ariaLabel="Client"
                  placeholder="Select client…"
                />
              </div>
            )}
          </div>

          {/* Month */}
          <div className="min-w-[150px]">
            <label className="text-xs font-medium text-[#334155] block mb-1">Month</label>
            <select
              value={selectedMonth}
              onChange={(e) => setSelectedMonth(e.target.value)}
              className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {MONTHS.map((m) => (
                <option key={m.value} value={m.value}>{m.label}</option>
              ))}
            </select>
          </div>

          {/* Year */}
          <div className="min-w-[110px]">
            <label className="text-xs font-medium text-[#334155] block mb-1">Year</label>
            <select
              value={selectedYear}
              onChange={(e) => setSelectedYear(e.target.value)}
              className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {YEAR_OPTIONS.map((y) => (
                <option key={y} value={String(y)}>{y}</option>
              ))}
            </select>
          </div>

          {/* Load Data button */}
          <div className="flex items-end">
            <button
              onClick={() => setParamsLoaded(true)}
              className="h-9 px-4 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium"
            >
              Load Data
            </button>
          </div>
        </div>

        {paramsLoaded && (
          <div className="flex items-center gap-2 text-xs text-green-600 bg-green-50 rounded-lg px-3 py-2">
            <CheckCircle className="w-3.5 h-3.5" />
            <span>
              Parameters set: <strong>{selectedClient?.client_name ?? "—"}</strong> · Period{" "}
              <strong>{periodLabel}</strong> · Return period code: <strong>{returnPeriod}</strong>
            </span>
          </div>
        )}
      </div>

      {/* Step 2 — Upload files */}
      <div>
        <p className="text-sm font-semibold text-[#0F172A] mb-3">Step 2 — Upload Files</p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <UploadPanel
            title="Purchase Register (Your Books)"
            subtitle="Your recorded purchase invoices for this period"
            templateFilename="purchase_register_template.csv"
            fileName={booksFile}
            rowCount={booksRows.length}
            error={booksError}
            onFile={handleBooksFile}
            accent="green"
          />
          <UploadPanel
            title="GSTR-2A (From GST Portal)"
            subtitle="Supplier-filed invoices reflected in your GSTR-2A"
            templateFilename="gstr2a_template.csv"
            fileName={gstr2aFile}
            rowCount={gstr2aRows.length}
            error={gstr2aError}
            onFile={handleGstr2aFile}
            note="Download GSTR-2A from GST Portal → Returns → View/Download → GSTR-2A → export to CSV"
            accent="blue"
          />
        </div>
      </div>

      {/* Step 3 — Results */}
      {reconRows.length > 0 && (
        <>
          <div>
            <p className="text-sm font-semibold text-[#0F172A] mb-3">Step 3 — Reconciliation Results</p>

            {/* Summary cards */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
              {/* Total ITC in Books */}
              <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
                <div className="flex items-center gap-2 mb-2">
                  <div className="w-8 h-8 rounded-lg bg-[#F8FAFC] flex items-center justify-center">
                    <BookOpen className="w-4 h-4 text-[#475569]" />
                  </div>
                  <span className="text-xs text-[#64748B]">ITC in Books</span>
                </div>
                <p className="text-base font-semibold text-[#0F172A]">₹{fmtRupees(totalBooksITC)}</p>
                <p className="text-[10px] text-[#94A3B8] mt-0.5">{booksRows.length} purchase invoices</p>
              </div>

              {/* Total ITC in GSTR-2A */}
              <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
                <div className="flex items-center gap-2 mb-2">
                  <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center">
                    <FileText className="w-4 h-4 text-blue-600" />
                  </div>
                  <span className="text-xs text-[#64748B]">ITC in GSTR-2A</span>
                </div>
                <p className="text-base font-semibold text-[#0F172A]">₹{fmtRupees(totalGstr2aITC)}</p>
                <p className="text-[10px] text-[#94A3B8] mt-0.5">{gstr2aRows.length} supplier-filed invoices</p>
              </div>

              {/* Matched ITC */}
              <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
                <div className="flex items-center gap-2 mb-2">
                  <div className="w-8 h-8 rounded-lg bg-green-50 flex items-center justify-center">
                    <CheckCircle className="w-4 h-4 text-green-600" />
                  </div>
                  <span className="text-xs text-[#64748B]">Matched ITC</span>
                </div>
                <p className="text-base font-semibold text-[#0F172A]">₹{fmtRupees(matchedITC)}</p>
                <p className="text-[10px] text-[#94A3B8] mt-0.5">{matched.length} invoices matched</p>
              </div>

              {/* Difference */}
              <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
                <div className="flex items-center gap-2 mb-2">
                  <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${diffITC === 0 ? "bg-[#F8FAFC]" : diffITC > 0 ? "bg-red-50" : "bg-amber-50"}`}>
                    <AlertCircle className={`w-4 h-4 ${diffITC === 0 ? "text-[#94A3B8]" : diffITC > 0 ? "text-red-600" : "text-amber-600"}`} />
                  </div>
                  <span className="text-xs text-[#64748B]">Difference (Books − 2A)</span>
                </div>
                <p className={`text-base font-semibold ${diffITC === 0 ? "text-[#0F172A]" : diffITC > 0 ? "text-red-600" : "text-amber-600"}`}>
                  {diffITC >= 0 ? "" : "−"}₹{fmtRupees(Math.abs(diffITC))}
                </p>
                <p className="text-[10px] text-[#94A3B8] mt-0.5">
                  {diffITC > 0 ? "Books > 2A — ITC at risk" : diffITC < 0 ? "2A > Books — unclaimed ITC" : "Fully reconciled"}
                </p>
              </div>
            </div>

            {/* Section pills */}
            <div className="flex flex-wrap gap-2 mb-3">
              {(
                [
                  { status: "all" as const,           label: `All (${reconRows.length})`,          cls: "bg-[#F1F5F9] text-[#334155]" },
                  { status: "matched" as ReconStatus,       label: `Matched ✓ (${matched.length})`,      cls: "bg-green-100 text-green-700" },
                  { status: "mismatch" as ReconStatus,      label: `Mismatch ⚠ (${mismatches.length})`, cls: "bg-amber-100 text-amber-700" },
                  { status: "missing_in_2a" as ReconStatus, label: `Missing in 2A (${missingIn2a.length})`, cls: "bg-red-100 text-red-700" },
                  { status: "extra_in_2a" as ReconStatus,   label: `Extra in 2A (${extraIn2a.length})`,  cls: "bg-blue-100 text-blue-700" },
                ] as { status: ReconStatus | "all"; label: string; cls: string }[]
              ).map(({ status, label, cls }) => (
                <button
                  key={status}
                  onClick={() => setFilterStatus(status)}
                  className={`px-3 py-1 rounded-full text-xs font-medium transition-opacity ${cls} ${filterStatus === status ? "opacity-100 ring-2 ring-offset-1 ring-current" : "opacity-70 hover:opacity-100"}`}
                >
                  {label}
                </button>
              ))}
            </div>

            {/* Results table */}
            <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-gray-50 bg-[#F8FAFC]/50">
                      <th className="text-left font-medium text-[#94A3B8] px-4 py-3">Status</th>
                      <th className="text-left font-medium text-[#94A3B8] px-3 py-3">Supplier GSTIN</th>
                      <th className="text-left font-medium text-[#94A3B8] px-3 py-3">Supplier Name</th>
                      <th className="text-left font-medium text-[#94A3B8] px-3 py-3">Invoice No.</th>
                      <th className="text-left font-medium text-[#94A3B8] px-3 py-3">Date</th>
                      <th className="text-right font-medium text-[#94A3B8] px-3 py-3">Books Tax (₹)</th>
                      <th className="text-right font-medium text-[#94A3B8] px-3 py-3">2A Tax (₹)</th>
                      <th className="text-right font-medium text-[#94A3B8] px-4 py-3">Diff (₹)</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#F8FAFC]">
                    {displayRows.map((r) => {
                      const booksTax =
                        r.books_igst !== null || r.books_cgst !== null || r.books_sgst !== null
                          ? (r.books_igst ?? 0) + (r.books_cgst ?? 0) + (r.books_sgst ?? 0)
                          : null;
                      const gstr2aTax =
                        r.gstr2a_igst !== null || r.gstr2a_cgst !== null || r.gstr2a_sgst !== null
                          ? (r.gstr2a_igst ?? 0) + (r.gstr2a_cgst ?? 0) + (r.gstr2a_sgst ?? 0)
                          : null;
                      const diffTax =
                        r.status === "mismatch"
                          ? r.diff_igst + r.diff_cgst + r.diff_sgst
                          : null;
                      return (
                        <tr key={r.key} className={STATUS_ROW[r.status]}>
                          <td className="px-4 py-2.5">
                            <span className={`inline-flex px-2 py-0.5 rounded-full text-[10px] font-medium ${STATUS_BADGE[r.status]}`}>
                              {STATUS_LABEL[r.status]}
                            </span>
                          </td>
                          <td className="px-3 py-2.5 font-mono text-[#475569]">{r.supplier_gstin}</td>
                          <td className="px-3 py-2.5 text-[#334155] max-w-[160px] truncate" title={r.supplier_name}>
                            {r.supplier_name || "—"}
                          </td>
                          <td className="px-3 py-2.5 text-[#334155] font-medium">{r.invoice_number}</td>
                          <td className="px-3 py-2.5 text-[#64748B]">{r.invoice_date || "—"}</td>
                          <td className="px-3 py-2.5 text-right text-[#334155]">
                            {booksTax !== null ? fmtRupees(booksTax) : "—"}
                          </td>
                          <td className="px-3 py-2.5 text-right text-[#334155]">
                            {gstr2aTax !== null ? fmtRupees(gstr2aTax) : "—"}
                          </td>
                          <td className="px-4 py-2.5 text-right font-medium">
                            {diffTax !== null ? (
                              <span className={diffTax !== 0 ? "text-amber-600" : "text-[#94A3B8]"}>
                                {diffTax >= 0 ? "" : "−"}
                                {fmtRupees(Math.abs(diffTax))}
                              </span>
                            ) : (
                              <span className="text-[#CBD5E1]">—</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div className="px-5 py-3 border-t border-gray-50 bg-[#F8FAFC]/30">
                <p className="text-[10px] text-[#94A3B8]">
                  {/* CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT */}
                  CGST Act Section 16 · Rule 36(4) — ITC subject to 105% cap of GSTR-2A eligible credit ·
                  PracticeSync does not auto-submit anything to the GST portal — CA must review and file manually.
                </p>
              </div>
            </div>
          </div>
        </>
      )}

      {/* Empty state */}
      {reconRows.length === 0 && !booksError && !gstr2aError && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] px-6 py-16 text-center space-y-2">
          <div className="w-12 h-12 rounded-xl bg-[#F8FAFC] flex items-center justify-center mx-auto">
            <FileText className="w-6 h-6 text-gray-200" />
          </div>
          <p className="text-sm font-medium text-[#64748B]">
            Upload both files to start reconciliation
          </p>
          <p className="text-xs text-[#94A3B8]">
            Upload your purchase register CSV and GSTR-2A CSV above — results appear automatically.
          </p>
        </div>
      )}
    </div>
  );
}
