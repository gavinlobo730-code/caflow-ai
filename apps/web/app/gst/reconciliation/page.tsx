"use client";

/**
 * GSTR-2B Reconciliation Tool
 * Section 16(2)(aa) of CGST Act — Input Tax Credit (ITC) can only be claimed
 * if the inward supply is reflected in GSTR-2B of the recipient.
 *
 * CAs must reconcile GSTR-2B (as filed by vendors on GSTN portal) against the
 * client's own purchase register to identify ITC discrepancies before filing GSTR-3B.
 */

import { useState, useRef, useEffect, useCallback } from "react";
import {
  Upload,
  Download,
  CheckCircle,
  AlertCircle,
  AlertTriangle,
  Info,
  ChevronLeft,
  FileText,
  Users,
} from "lucide-react";
import Link from "next/link";
import { getClients } from "@/lib/data/clients";
import type { Client } from "@/lib/types";

// ─── Types ────────────────────────────────────────────────────────────────────

/** One invoice line from GSTR-2B JSON (GSTN standard format) */
interface Gstr2bInvoice {
  supplierGstin: string;
  invoiceNo: string;
  invoiceDate: string;
  taxableAmount: number; // in paise (integer arithmetic — CGST Act requirement)
  igst: number;
  cgst: number;
  sgst: number;
  total: number;
}

/** One row from the client's purchase register CSV */
interface PurchaseRegisterRow {
  supplierGstin: string;
  invoiceNo: string;
  invoiceDate: string;
  taxableAmount: number; // in paise
  igst: number;
  cgst: number;
  sgst: number;
  total: number;
}

type ReconciliationStatus =
  | "matched"
  | "gstr2b_only"
  | "purchase_only"
  | "amount_mismatch";

/** One reconciled line — result of matching GSTR-2B vs purchase register */
interface ReconRow {
  key: string; // supplierGstin + "|" + invoiceNo (normalised)
  supplierGstin: string;
  invoiceNo: string;
  invoiceDate: string;
  status: ReconciliationStatus;
  gstr2bTaxable: number | null; // paise
  gstr2bIgst: number | null;
  gstr2bCgst: number | null;
  gstr2bSgst: number | null;
  prTaxable: number | null; // paise
  prIgst: number | null;
  prCgst: number | null;
  prSgst: number | null;
  itcAmount: number; // paise — igst+cgst+sgst from whichever side is authoritative
}

// ─── Constants ────────────────────────────────────────────────────────────────

const MONTH_NAMES = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

const TODAY = new Date("2026-06-02");

function buildMonthOptions(): { value: string; label: string }[] {
  const options: { value: string; label: string }[] = [];
  for (let i = 11; i >= 0; i--) {
    const d = new Date(TODAY.getFullYear(), TODAY.getMonth() - i, 1);
    const label = `${MONTH_NAMES[d.getMonth()]} ${d.getFullYear()}`;
    options.push({ value: label, label });
  }
  return options;
}

const MONTH_OPTIONS = buildMonthOptions();

// ─── Paise helpers ────────────────────────────────────────────────────────────

/** Convert rupee float string → integer paise. Never use floating point for money. */
function toPaise(val: string | number): number {
  if (typeof val === "number") return Math.round(val * 100);
  const cleaned = String(val).replace(/,/g, "").trim();
  const f = parseFloat(cleaned);
  if (isNaN(f)) return 0;
  return Math.round(f * 100);
}

/** Format paise → ₹ string with Indian number formatting */
function fmtRupees(paise: number | null): string {
  if (paise === null) return "—";
  const rupees = paise / 100;
  return rupees.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// ─── GSTR-2B JSON Parser ──────────────────────────────────────────────────────

/**
 * Parse GSTN's standard GSTR-2B JSON format.
 * Structure: { data: { docdata: { b2b: [{ ctin, inv: [{ inum, dt, val, itms: [{ rt, txval, igst, cgst, sgst }] }] }] } } }
 * Section 16(2)(aa) CGST Act — ITC eligible only if reflected in GSTR-2B.
 */
function parseGstr2bJson(text: string): { rows: Gstr2bInvoice[]; error: string | null } {
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const parsed: any = JSON.parse(text);
    const b2b =
      parsed?.data?.docdata?.b2b ??
      parsed?.docdata?.b2b ??
      parsed?.b2b ??
      [];

    if (!Array.isArray(b2b)) {
      return { rows: [], error: "Invalid GSTR-2B format: missing b2b array." };
    }

    const rows: Gstr2bInvoice[] = [];

    for (const supplier of b2b) {
      const ctin: string = String(supplier?.ctin ?? "").trim().toUpperCase();
      const invList = supplier?.inv ?? [];
      if (!Array.isArray(invList)) continue;

      for (const inv of invList) {
        const invoiceNo: string = String(inv?.inum ?? "").trim();
        const invoiceDate: string = String(inv?.dt ?? "").trim();
        // Aggregate tax across all line items (itms)
        const itms = Array.isArray(inv?.itms) ? inv.itms : [];
        let txvalPaise = 0;
        let igstPaise = 0;
        let cgstPaise = 0;
        let sgstPaise = 0;

        if (itms.length > 0) {
          for (const itm of itms) {
            const item = itm?.itm_det ?? itm;
            txvalPaise += toPaise(item?.txval ?? 0);
            igstPaise += toPaise(item?.igst ?? 0);
            cgstPaise += toPaise(item?.cgst ?? 0);
            sgstPaise += toPaise(item?.sgst ?? 0);
          }
        } else {
          // Fallback: val at invoice level, no breakdown
          txvalPaise = toPaise(inv?.val ?? 0);
        }

        const totalPaise = txvalPaise + igstPaise + cgstPaise + sgstPaise;

        rows.push({
          supplierGstin: ctin,
          invoiceNo,
          invoiceDate,
          taxableAmount: txvalPaise,
          igst: igstPaise,
          cgst: cgstPaise,
          sgst: sgstPaise,
          total: totalPaise,
        });
      }
    }

    return { rows, error: null };
  } catch {
    return { rows: [], error: "Failed to parse JSON. Please upload a valid GSTR-2B JSON file." };
  }
}

// ─── Purchase Register CSV Parser ─────────────────────────────────────────────

/**
 * Parse purchase register CSV.
 * Expected columns: supplier_gstin, invoice_no, invoice_date, taxable_amount, igst, cgst, sgst, total
 * Manual CSV parsing (no papaparse dependency).
 */
function parsePurchaseCsv(text: string): { rows: PurchaseRegisterRow[]; error: string | null } {
  const lines = text.split(/\r?\n/).filter((l) => l.trim().length > 0);
  if (lines.length < 2) {
    return { rows: [], error: "CSV must have a header row and at least one data row." };
  }

  const headers = lines[0]!.split(",").map((h) => h.trim().toLowerCase().replace(/\s+/g, "_"));

  const idx = (col: string): number => headers.indexOf(col);
  const required = ["supplier_gstin", "invoice_no", "invoice_date", "taxable_amount"];
  const missing = required.filter((c) => idx(c) === -1);
  if (missing.length > 0) {
    return {
      rows: [],
      error: `CSV is missing required columns: ${missing.join(", ")}. Expected: supplier_gstin, invoice_no, invoice_date, taxable_amount, igst, cgst, sgst, total`,
    };
  }

  const rows: PurchaseRegisterRow[] = [];
  for (let i = 1; i < lines.length; i++) {
    const cols = lines[i]!.split(",");
    const get = (col: string): string => (cols[idx(col)] ?? "").trim();

    const supplierGstin = get("supplier_gstin").toUpperCase();
    const invoiceNo = get("invoice_no");
    if (!supplierGstin || !invoiceNo) continue;

    const taxableAmount = toPaise(get("taxable_amount"));
    const igst = toPaise(get("igst"));
    const cgst = toPaise(get("cgst"));
    const sgst = toPaise(get("sgst"));
    const totalRaw = get("total");
    const total = totalRaw ? toPaise(totalRaw) : taxableAmount + igst + cgst + sgst;

    rows.push({
      supplierGstin,
      invoiceNo,
      invoiceDate: get("invoice_date"),
      taxableAmount,
      igst,
      cgst,
      sgst,
      total,
    });
  }

  return { rows, error: null };
}

// ─── Reconciliation Engine ────────────────────────────────────────────────────

/**
 * Match GSTR-2B vs Purchase Register by supplier_gstin + invoice_no.
 * Section 16(2)(aa) CGST Act — ITC can only be claimed on matched invoices.
 *
 * Result categories:
 *   matched         — same invoice on both sides, amounts agree (green)
 *   gstr2b_only     — vendor filed but not in purchase register (orange — missing from books)
 *   purchase_only   — in books but vendor hasn't filed (red — ITC at risk)
 *   amount_mismatch — invoice on both sides but amounts differ (yellow)
 */
function reconcile(
  gstr2bRows: Gstr2bInvoice[],
  prRows: PurchaseRegisterRow[]
): ReconRow[] {
  // Build lookup maps: key = GSTIN|invoice_no (normalised upper-case)
  const gstr2bMap = new Map<string, Gstr2bInvoice>();
  for (const r of gstr2bRows) {
    const key = `${r.supplierGstin.toUpperCase()}|${r.invoiceNo.toUpperCase()}`;
    gstr2bMap.set(key, r);
  }

  const prMap = new Map<string, PurchaseRegisterRow>();
  for (const r of prRows) {
    const key = `${r.supplierGstin.toUpperCase()}|${r.invoiceNo.toUpperCase()}`;
    prMap.set(key, r);
  }

  const allKeys = Array.from(new Set([...Array.from(gstr2bMap.keys()), ...Array.from(prMap.keys())]));
  const result: ReconRow[] = [];

  for (let i = 0; i < allKeys.length; i++) {
    const key = allKeys[i];
    const g = gstr2bMap.get(key);
    const p = prMap.get(key);
    const [gstin, invoiceNo] = key.split("|") as [string, string];

    let status: ReconciliationStatus;
    let itcAmount: number;

    if (g && p) {
      // Both sides — check if amounts match (within 1 paise rounding tolerance)
      const taxDiff = Math.abs(g.taxableAmount - p.taxableAmount);
      const igstDiff = Math.abs(g.igst - p.igst);
      const cgstDiff = Math.abs(g.cgst - p.cgst);
      const sgstDiff = Math.abs(g.sgst - p.sgst);
      const totalDiff = taxDiff + igstDiff + cgstDiff + sgstDiff;

      status = totalDiff <= 4 ? "matched" : "amount_mismatch"; // 4 paise = 1 paise per tax head
      // ITC = tax from GSTR-2B (authoritative per Section 16(2)(aa))
      itcAmount = g.igst + g.cgst + g.sgst;
    } else if (g && !p) {
      status = "gstr2b_only";
      itcAmount = g.igst + g.cgst + g.sgst;
    } else {
      // p && !g
      status = "purchase_only";
      itcAmount = 0; // ITC at risk — not in GSTR-2B, Section 16(2)(aa)
    }

    result.push({
      key,
      supplierGstin: gstin,
      invoiceNo,
      invoiceDate: g?.invoiceDate ?? p?.invoiceDate ?? "",
      status,
      gstr2bTaxable: g?.taxableAmount ?? null,
      gstr2bIgst: g?.igst ?? null,
      gstr2bCgst: g?.cgst ?? null,
      gstr2bSgst: g?.sgst ?? null,
      prTaxable: p?.taxableAmount ?? null,
      prIgst: p?.igst ?? null,
      prCgst: p?.cgst ?? null,
      prSgst: p?.sgst ?? null,
      itcAmount,
    });
  }

  // Sort: matched first, then mismatch, then gstr2b_only, then purchase_only
  const ORDER: ReconciliationStatus[] = ["matched", "amount_mismatch", "gstr2b_only", "purchase_only"];
  result.sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status));

  return result;
}

// ─── Export CSV ───────────────────────────────────────────────────────────────

function exportCsv(rows: ReconRow[], period: string, clientName: string) {
  const header = [
    "status",
    "supplier_gstin",
    "invoice_no",
    "invoice_date",
    "gstr2b_taxable",
    "gstr2b_igst",
    "gstr2b_cgst",
    "gstr2b_sgst",
    "pr_taxable",
    "pr_igst",
    "pr_cgst",
    "pr_sgst",
    "itc_amount",
  ].join(",");

  const lines = rows.map((r) =>
    [
      r.status,
      r.supplierGstin,
      r.invoiceNo,
      r.invoiceDate,
      r.gstr2bTaxable !== null ? (r.gstr2bTaxable / 100).toFixed(2) : "",
      r.gstr2bIgst !== null ? (r.gstr2bIgst / 100).toFixed(2) : "",
      r.gstr2bCgst !== null ? (r.gstr2bCgst / 100).toFixed(2) : "",
      r.gstr2bSgst !== null ? (r.gstr2bSgst / 100).toFixed(2) : "",
      r.prTaxable !== null ? (r.prTaxable / 100).toFixed(2) : "",
      r.prIgst !== null ? (r.prIgst / 100).toFixed(2) : "",
      r.prCgst !== null ? (r.prCgst / 100).toFixed(2) : "",
      r.prSgst !== null ? (r.prSgst / 100).toFixed(2) : "",
      (r.itcAmount / 100).toFixed(2),
    ].join(",")
  );

  const csv = [header, ...lines].join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `GSTR2B_Recon_${clientName.replace(/\s+/g, "_")}_${period.replace(/\s+/g, "_")}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ─── Status UI helpers ────────────────────────────────────────────────────────

const STATUS_LABEL: Record<ReconciliationStatus, string> = {
  matched: "Matched",
  gstr2b_only: "Missing from Books",
  purchase_only: "ITC at Risk",
  amount_mismatch: "Amount Mismatch",
};

const STATUS_BADGE: Record<ReconciliationStatus, string> = {
  matched: "bg-green-100 text-green-700",
  gstr2b_only: "bg-orange-100 text-orange-700",
  purchase_only: "bg-red-100 text-red-700",
  amount_mismatch: "bg-yellow-100 text-yellow-700",
};

const STATUS_ROW: Record<ReconciliationStatus, string> = {
  matched: "hover:bg-green-50/30",
  gstr2b_only: "bg-orange-50/20 hover:bg-orange-50/40",
  purchase_only: "bg-red-50/20 hover:bg-red-50/40",
  amount_mismatch: "bg-yellow-50/20 hover:bg-yellow-50/40",
};

// ─── Upload Zone Component ────────────────────────────────────────────────────

interface UploadZoneProps {
  label: string;
  subLabel: string;
  accept: string;
  fileName: string | null;
  onFile: (text: string, name: string) => void;
  error: string | null;
  icon: React.ReactNode;
}

function UploadZone({ label, subLabel, accept, fileName, onFile, error, icon }: UploadZoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    const file = files[0]!;
    const reader = new FileReader();
    reader.onload = (e) => {
      onFile(e.target?.result as string, file.name);
    };
    reader.readAsText(file);
  }

  return (
    <div
      className={`relative border-2 border-dashed rounded-xl p-6 flex flex-col items-center justify-center gap-3 cursor-pointer transition-colors
        ${dragging ? "border-blue-400 bg-blue-50" : fileName ? "border-green-400 bg-green-50/30" : "border-gray-200 hover:border-blue-300 hover:bg-blue-50/20"}
        ${error ? "border-red-300 bg-red-50/20" : ""}
      `}
      onClick={() => inputRef.current?.click()}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => { e.preventDefault(); setDragging(false); handleFiles(e.dataTransfer.files); }}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="hidden"
        onChange={(e) => handleFiles(e.target.files)}
      />
      <div className="w-10 h-10 rounded-xl bg-gray-100 flex items-center justify-center">
        {icon}
      </div>
      <div className="text-center">
        <p className="text-sm font-semibold text-gray-800">{label}</p>
        <p className="text-xs text-gray-400 mt-0.5">{subLabel}</p>
      </div>
      {fileName ? (
        <div className="flex items-center gap-1.5 text-green-600 text-xs font-medium">
          <CheckCircle className="w-3.5 h-3.5" />
          <span>{fileName}</span>
        </div>
      ) : (
        <p className="text-xs text-blue-600 font-medium">Click or drag to upload</p>
      )}
      {error && (
        <p className="text-xs text-red-600 bg-red-50 rounded px-2 py-1">{error}</p>
      )}
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function Gstr2bReconciliationPage() {
  // Client & period selection
  const [clients, setClients] = useState<Client[]>([]);
  const [selectedClientId, setSelectedClientId] = useState("");
  const [period, setPeriod] = useState(MONTH_OPTIONS[MONTH_OPTIONS.length - 2]?.value ?? "");
  const [loadingClients, setLoadingClients] = useState(true);

  // File state
  const [gstr2bFileName, setGstr2bFileName] = useState<string | null>(null);
  const [prFileName, setPrFileName] = useState<string | null>(null);
  const [gstr2bRows, setGstr2bRows] = useState<Gstr2bInvoice[]>([]);
  const [prRows, setPrRows] = useState<PurchaseRegisterRow[]>([]);
  const [gstr2bError, setGstr2bError] = useState<string | null>(null);
  const [prError, setPrError] = useState<string | null>(null);

  // Reconciliation results
  const [reconRows, setReconRows] = useState<ReconRow[]>([]);
  const [filterStatus, setFilterStatus] = useState<ReconciliationStatus | "all">("all");

  // Load clients from Supabase
  useEffect(() => {
    async function load() {
      setLoadingClients(true);
      try {
        const cls = await getClients().catch(() => [] as Client[]);
        setClients(cls);
        if (cls.length > 0 && cls[0]) {
          setSelectedClientId(cls[0].id);
        }
      } finally {
        setLoadingClients(false);
      }
    }
    load();
  }, []);

  // Re-run reconciliation whenever inputs change
  const runRecon = useCallback(() => {
    if (gstr2bRows.length === 0 && prRows.length === 0) {
      setReconRows([]);
      return;
    }
    setReconRows(reconcile(gstr2bRows, prRows));
  }, [gstr2bRows, prRows]);

  useEffect(() => {
    runRecon();
  }, [runRecon]);

  // ── File handlers ────────────────────────────────────────────────────────
  function handleGstr2bFile(text: string, name: string) {
    setGstr2bFileName(name);
    setGstr2bError(null);
    const { rows, error } = parseGstr2bJson(text);
    if (error) {
      setGstr2bError(error);
      setGstr2bRows([]);
    } else if (rows.length === 0) {
      setGstr2bError("No B2B invoices found in the GSTR-2B file.");
      setGstr2bRows([]);
    } else {
      setGstr2bRows(rows);
    }
  }

  function handlePrFile(text: string, name: string) {
    setPrFileName(name);
    setPrError(null);
    const { rows, error } = parsePurchaseCsv(text);
    if (error) {
      setPrError(error);
      setPrRows([]);
    } else if (rows.length === 0) {
      setPrError("No valid rows found in the Purchase Register CSV.");
      setPrRows([]);
    } else {
      setPrRows(rows);
    }
  }

  // ── Summary ──────────────────────────────────────────────────────────────
  const matched = reconRows.filter((r) => r.status === "matched");
  const gstr2bOnly = reconRows.filter((r) => r.status === "gstr2b_only");
  const purchaseOnly = reconRows.filter((r) => r.status === "purchase_only");
  const amountMismatch = reconRows.filter((r) => r.status === "amount_mismatch");

  // Total ITC Available = sum of GSTR-2B tax (matched + gstr2b_only + mismatch)
  // Section 16(2)(aa) CGST Act — ITC eligible only if in GSTR-2B
  const totalItcAvailable = reconRows
    .filter((r) => r.status !== "purchase_only")
    .reduce((sum, r) => sum + r.itcAmount, 0);

  const matchedItc = matched.reduce((sum, r) => sum + r.itcAmount, 0);

  // ITC at Risk = purchase_only (vendor hasn't filed)
  const itcAtRisk = purchaseOnly.reduce(
    (sum, r) => sum + (r.prIgst ?? 0) + (r.prCgst ?? 0) + (r.prSgst ?? 0),
    0
  );

  // Missing from Books = gstr2b_only ITC (vendor filed, CA hasn't booked)
  const missingFromBooks = gstr2bOnly.reduce((sum, r) => sum + r.itcAmount, 0);

  // ── Filtered rows ────────────────────────────────────────────────────────
  const displayRows =
    filterStatus === "all" ? reconRows : reconRows.filter((r) => r.status === filterStatus);

  const selectedClient = clients.find((c) => c.id === selectedClientId);

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Link
              href="/gst"
              className="text-gray-400 hover:text-gray-600 flex items-center gap-1 text-xs"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
              GST
            </Link>
          </div>
          <h1 className="text-xl font-semibold text-gray-900">GSTR-2B Reconciliation</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Section 16(2)(aa) CGST Act — Match vendor-filed GSTR-2B against purchase register to claim ITC
          </p>
        </div>
        {reconRows.length > 0 && (
          <button
            onClick={() =>
              exportCsv(reconRows, period, selectedClient?.client_name ?? "Client")
            }
            className="flex items-center gap-1.5 text-xs bg-gray-800 text-white px-3 py-2 rounded-lg hover:bg-gray-900"
          >
            <Download className="w-3.5 h-3.5" />
            Export CSV
          </button>
        )}
      </div>

      {/* ITC notice banner */}
      <div className="bg-blue-50 border border-blue-100 rounded-xl px-4 py-3 flex gap-2.5 text-xs text-blue-700">
        <Info className="w-4 h-4 shrink-0 mt-0.5" />
        <span>
          <strong>Section 16(2)(aa) CGST Act:</strong> ITC is available only if the inward supply is reflected in
          the recipient&apos;s GSTR-2B. Mismatches must be resolved with vendors before filing GSTR-3B.
          {/* CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT */}
        </span>
      </div>

      {/* Client + Period selectors */}
      <div className="bg-white rounded-xl border border-gray-100 p-4">
        <div className="flex flex-wrap gap-4">
          <div className="flex-1 min-w-[200px]">
            <label className="text-xs font-medium text-gray-700 block mb-1">
              <Users className="w-3.5 h-3.5 inline mr-1" />
              Client
            </label>
            {loadingClients ? (
              <div className="h-9 bg-gray-50 rounded-lg animate-pulse" />
            ) : clients.length === 0 ? (
              <p className="text-xs text-gray-400 italic">No clients found — add clients first</p>
            ) : (
              <select
                value={selectedClientId}
                onChange={(e) => setSelectedClientId(e.target.value)}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {clients.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.client_name}
                    {c.gstin ? ` · ${c.gstin}` : ""}
                  </option>
                ))}
              </select>
            )}
          </div>
          <div className="min-w-[180px]">
            <label className="text-xs font-medium text-gray-700 block mb-1">
              GSTR-2B Period
            </label>
            <select
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {MONTH_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Upload Section */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <UploadZone
          label="Upload GSTR-2B JSON"
          subLabel="Downloaded from GSTN portal (JSON format)"
          accept=".json,application/json"
          fileName={gstr2bFileName}
          onFile={handleGstr2bFile}
          error={gstr2bError}
          icon={<FileText className="w-5 h-5 text-blue-600" />}
        />
        <UploadZone
          label="Upload Purchase Register CSV"
          subLabel="Columns: supplier_gstin, invoice_no, invoice_date, taxable_amount, igst, cgst, sgst, total"
          accept=".csv,text/csv"
          fileName={prFileName}
          onFile={handlePrFile}
          error={prError}
          icon={<Upload className="w-5 h-5 text-green-600" />}
        />
      </div>

      {/* File parse summary */}
      {(gstr2bRows.length > 0 || prRows.length > 0) && (
        <div className="flex flex-wrap gap-3 text-xs text-gray-500">
          {gstr2bRows.length > 0 && (
            <span className="bg-blue-50 text-blue-700 px-2.5 py-1 rounded-full">
              GSTR-2B: {gstr2bRows.length} invoices loaded
            </span>
          )}
          {prRows.length > 0 && (
            <span className="bg-green-50 text-green-700 px-2.5 py-1 rounded-full">
              Purchase Register: {prRows.length} rows loaded
            </span>
          )}
        </div>
      )}

      {/* Summary Cards — shown only after reconciliation */}
      {reconRows.length > 0 && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            {/* Total ITC Available */}
            <div className="bg-white rounded-xl border border-gray-100 p-4">
              <div className="flex items-center gap-2 mb-2">
                <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center">
                  <Info className="w-4 h-4 text-blue-600" />
                </div>
                <span className="text-xs text-gray-500">Total ITC Available</span>
              </div>
              <p className="text-base font-semibold text-gray-900">₹{fmtRupees(totalItcAvailable)}</p>
              <p className="text-[10px] text-gray-400 mt-0.5">From GSTR-2B (Sec 16(2)(aa))</p>
            </div>

            {/* Matched ITC */}
            <div className="bg-white rounded-xl border border-gray-100 p-4">
              <div className="flex items-center gap-2 mb-2">
                <div className="w-8 h-8 rounded-lg bg-green-50 flex items-center justify-center">
                  <CheckCircle className="w-4 h-4 text-green-600" />
                </div>
                <span className="text-xs text-gray-500">Matched ITC</span>
              </div>
              <p className="text-base font-semibold text-gray-900">₹{fmtRupees(matchedItc)}</p>
              <p className="text-[10px] text-gray-400 mt-0.5">{matched.length} invoices matched</p>
            </div>

            {/* ITC at Risk */}
            <div className="bg-white rounded-xl border border-gray-100 p-4">
              <div className="flex items-center gap-2 mb-2">
                <div className="w-8 h-8 rounded-lg bg-red-50 flex items-center justify-center">
                  <AlertCircle className="w-4 h-4 text-red-600" />
                </div>
                <span className="text-xs text-gray-500">ITC at Risk</span>
              </div>
              <p className="text-base font-semibold text-gray-900">₹{fmtRupees(itcAtRisk)}</p>
              <p className="text-[10px] text-gray-400 mt-0.5">{purchaseOnly.length} invoices — vendor not filed</p>
            </div>

            {/* Missing from Books */}
            <div className="bg-white rounded-xl border border-gray-100 p-4">
              <div className="flex items-center gap-2 mb-2">
                <div className="w-8 h-8 rounded-lg bg-orange-50 flex items-center justify-center">
                  <AlertTriangle className="w-4 h-4 text-orange-600" />
                </div>
                <span className="text-xs text-gray-500">Missing from Books</span>
              </div>
              <p className="text-base font-semibold text-gray-900">₹{fmtRupees(missingFromBooks)}</p>
              <p className="text-[10px] text-gray-400 mt-0.5">{gstr2bOnly.length} invoices — not in purchase register</p>
            </div>
          </div>

          {/* Mismatch summary pill */}
          {amountMismatch.length > 0 && (
            <div className="bg-yellow-50 border border-yellow-100 rounded-xl px-4 py-2.5 flex items-center gap-2 text-xs text-yellow-700">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
              <span>
                <strong>{amountMismatch.length} invoices</strong> have amount mismatches between GSTR-2B and purchase register — verify with vendors.
              </span>
            </div>
          )}
        </>
      )}

      {/* Reconciliation Table */}
      {reconRows.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-50 flex items-center justify-between gap-3 flex-wrap">
            <div>
              <h2 className="text-sm font-semibold text-gray-900">Reconciliation Results</h2>
              <p className="text-xs text-gray-400 mt-0.5">
                {reconRows.length} invoices · {period}{selectedClient ? ` · ${selectedClient.client_name}` : ""}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <label className="text-xs text-gray-500">Filter:</label>
              <select
                value={filterStatus}
                onChange={(e) => setFilterStatus(e.target.value as ReconciliationStatus | "all")}
                className="border border-gray-200 rounded-lg px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="all">All ({reconRows.length})</option>
                <option value="matched">Matched ({matched.length})</option>
                <option value="amount_mismatch">Amount Mismatch ({amountMismatch.length})</option>
                <option value="gstr2b_only">Missing from Books ({gstr2bOnly.length})</option>
                <option value="purchase_only">ITC at Risk ({purchaseOnly.length})</option>
              </select>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-50">
                  <th className="text-left font-medium text-gray-400 px-4 py-3">Status</th>
                  <th className="text-left font-medium text-gray-400 px-3 py-3">Supplier GSTIN</th>
                  <th className="text-left font-medium text-gray-400 px-3 py-3">Invoice No.</th>
                  <th className="text-left font-medium text-gray-400 px-3 py-3">Date</th>
                  <th className="text-right font-medium text-gray-400 px-3 py-3">GSTR-2B Taxable</th>
                  <th className="text-right font-medium text-gray-400 px-3 py-3">GSTR-2B Tax</th>
                  <th className="text-right font-medium text-gray-400 px-3 py-3">PR Taxable</th>
                  <th className="text-right font-medium text-gray-400 px-3 py-3">PR Tax</th>
                  <th className="text-right font-medium text-gray-400 px-4 py-3">ITC (₹)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {displayRows.map((r) => {
                  const gstr2bTax =
                    r.gstr2bIgst !== null || r.gstr2bCgst !== null || r.gstr2bSgst !== null
                      ? (r.gstr2bIgst ?? 0) + (r.gstr2bCgst ?? 0) + (r.gstr2bSgst ?? 0)
                      : null;
                  const prTax =
                    r.prIgst !== null || r.prCgst !== null || r.prSgst !== null
                      ? (r.prIgst ?? 0) + (r.prCgst ?? 0) + (r.prSgst ?? 0)
                      : null;
                  return (
                    <tr key={r.key} className={`${STATUS_ROW[r.status]}`}>
                      <td className="px-4 py-2.5">
                        <span className={`inline-flex px-2 py-0.5 rounded-full text-[10px] font-medium ${STATUS_BADGE[r.status]}`}>
                          {STATUS_LABEL[r.status]}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 font-mono text-gray-600">{r.supplierGstin}</td>
                      <td className="px-3 py-2.5 text-gray-700 font-medium">{r.invoiceNo}</td>
                      <td className="px-3 py-2.5 text-gray-500">{r.invoiceDate}</td>
                      <td className="px-3 py-2.5 text-right text-gray-700">
                        {r.gstr2bTaxable !== null ? fmtRupees(r.gstr2bTaxable) : "—"}
                      </td>
                      <td className="px-3 py-2.5 text-right text-gray-700">
                        {gstr2bTax !== null ? fmtRupees(gstr2bTax) : "—"}
                      </td>
                      <td className="px-3 py-2.5 text-right text-gray-700">
                        {r.prTaxable !== null ? fmtRupees(r.prTaxable) : "—"}
                      </td>
                      <td className="px-3 py-2.5 text-right text-gray-700">
                        {prTax !== null ? fmtRupees(prTax) : "—"}
                      </td>
                      <td className="px-4 py-2.5 text-right font-medium text-gray-900">
                        {r.status === "purchase_only" ? (
                          <span className="text-red-500">—</span>
                        ) : (
                          fmtRupees(r.itcAmount)
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="px-5 py-3 border-t border-gray-50 bg-gray-50/30">
            <p className="text-[10px] text-gray-400">
              {/* CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT */}
              Section 16(2)(aa) CGST Act — ITC claimable only for invoices reflected in GSTR-2B ·
              CAflow does not auto-submit anything to the GST portal — CA must review and file manually.
            </p>
          </div>
        </div>
      )}

      {/* Empty state — no reconciliation yet */}
      {reconRows.length === 0 && !gstr2bError && !prError && (
        <div className="bg-white rounded-xl border border-gray-100 px-6 py-16 text-center space-y-2">
          <div className="w-12 h-12 rounded-xl bg-gray-50 flex items-center justify-center mx-auto">
            <FileText className="w-6 h-6 text-gray-300" />
          </div>
          <p className="text-sm font-medium text-gray-600">Upload both files to start reconciliation</p>
          <p className="text-xs text-gray-400">
            Upload GSTR-2B JSON and Purchase Register CSV above — results appear automatically.
          </p>
        </div>
      )}
    </div>
  );
}
