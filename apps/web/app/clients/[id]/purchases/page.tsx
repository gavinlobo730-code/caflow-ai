"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { Plus, Upload, AlertCircle, CheckCircle, Trash2, X } from "lucide-react";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import { formatPaise, formatMoney } from "@/lib/services/formatting";
import { estimateBaseMinor, estimateForeignTds, convertBaseToForeignMinor } from "@/lib/services/currencyPreview";
import { DataTable, exportSelectedAction } from "@/components/ui/data-table";
import type { BulkAction, Column, FilterDef } from "@/lib/table/types";
import { VendorLookup } from "@/components/lookups/VendorLookup";
import { AccountLookup } from "@/components/lookups/AccountLookup";
import { HsnLookup } from "@/components/lookups/HsnLookup";
import { EntityLookup } from "@/components/lookups/EntityLookup";
import { Combobox } from "@/components/ui/combobox";
import CsvImportModal, { type ImportRow } from "@/components/CsvImportModal";
import { buildVendors, VENDOR_IMPORT_COLUMNS, buildPurchaseBills, PURCHASE_BILL_IMPORT_COLUMNS, type NameRef } from "@/lib/imports/mappers";
import { dnLineGst } from "@/lib/purchases/debitNoteGst";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── API helpers ────────────────────────────────────────────────────────────

async function apiCall(
  endpoint: string,
  method: "POST" | "PATCH" | "DELETE",
  body?: unknown,
  token?: string
): Promise<{ success: boolean; data: unknown; error: string | null }> {
  const res = await fetch(`${API}${endpoint}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    // Try to parse a structured error from the response body.
    // FastAPI returns { detail: ... } for 422/4xx; our API returns { error: ... }.
    const text = await res.text().catch(() => "");
    let errorMsg = `Request failed (HTTP ${res.status})`;
    if (text) {
      try {
        const json = JSON.parse(text);
        if (typeof json.error === "string" && json.error) {
          errorMsg = json.error;
        } else if (json.detail) {
          if (typeof json.detail === "string") {
            errorMsg = json.detail;
          } else if (Array.isArray(json.detail)) {
            // FastAPI validation errors: [{ loc, msg, type }, ...]
            errorMsg = json.detail
              .map((e: { loc?: string[]; msg?: string }) =>
                [e.loc?.slice(1).join("."), e.msg].filter(Boolean).join(": ")
              )
              .join("; ");
          }
        }
      } catch {
        // Not JSON — use the raw text if it's short enough to be meaningful
        if (text.length < 300) errorMsg = text;
      }
    }
    return { success: false, data: null, error: errorMsg };
  }
  return res.json();
}

async function apiGet(
  endpoint: string,
  token?: string
): Promise<{ success: boolean; data: unknown; error: string | null }> {
  const res = await fetch(`${API}${endpoint}`, {
    method: "GET",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "Request failed");
    return { success: false, data: null, error: text };
  }
  return res.json();
}

async function getAuthToken(): Promise<string> {
  const supabase = getSupabaseClient();
  const { data: { session } } = await supabase.auth.getSession();
  return session?.access_token ?? "";
}

type PurchaseTab = "bills" | "vendors" | "payments" | "debit-notes";
const TABS: { id: PurchaseTab; label: string }[] = [
  { id: "bills", label: "Purchase Bills" },
  { id: "vendors", label: "Vendors" },
  { id: "payments", label: "Payments" },
  { id: "debit-notes", label: "Debit Notes" },
];

// Shared money formatter (paise → ₹). Preserves the sign so a negative amount
// never renders as positive (audit M15).
function fmt(paise: number): string {
  return paise === 0 ? "—" : formatPaise(paise);
}

function fyRange(fy: string): { start: string; end: string } {
  const [y] = fy.split("-");
  const yr = parseInt(y);
  return { start: `${yr}-04-01`, end: `${yr + 1}-03-31` };
}

function toDate(): string {
  return new Date().toISOString().split("T")[0];
}

// ── Main Page ──────────────────────────────────────────────────────────────

export default function PurchasesPage() {
  const { clientId, financialYear } = useClientNav();
  const [tab, setTab] = useState<PurchaseTab>("bills");

  if (!clientId || clientId === "_placeholder") {
    return (
      <div className="px-6 py-4">
        <div className="space-y-3">
          {[...Array(4)].map((_, i) => <div key={i} className="h-10 rounded-lg bg-[#F8FAFC] animate-pulse" />)}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex-shrink-0 overflow-x-auto px-6 pt-5 pb-0">
        <div className="flex gap-0.5 bg-[#F8FAFC] rounded-lg p-1 w-fit">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors whitespace-nowrap ${
                tab === t.id ? "bg-white text-[#0F172A] shadow-sm" : "text-[#64748B] hover:text-[#334155]"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 pb-6 pt-4 min-h-0">
        {tab === "bills" && <PurchaseBills clientId={clientId} financialYear={financialYear} />}
        {tab === "vendors" && <Vendors clientId={clientId} financialYear={financialYear} />}
        {tab === "payments" && <Payments clientId={clientId} financialYear={financialYear} />}
        {tab === "debit-notes" && <DebitNotes clientId={clientId} financialYear={financialYear} />}
      </div>
    </div>
  );
}

// ── Status badge ───────────────────────────────────────────────────────────

const STATUS_COLORS: Record<string, string> = {
  draft: "bg-[#F1F5F9] text-[#475569]",
  received: "bg-blue-100 text-blue-700",
  partially_paid: "bg-amber-100 text-amber-700",
  paid: "bg-green-100 text-green-700",
  cancelled: "bg-red-100 text-red-700",
  issued: "bg-green-100 text-green-700",
};

// ── TDS section options ────────────────────────────────────────────────────

const TDS_SECTIONS = [
  { value: "192", label: "192 — Salary" },
  { value: "194A", label: "194A — Interest (10%)" },
  { value: "194B", label: "194B — Lottery/Winnings (30%)" },
  { value: "194C", label: "194C — Contractors (1%/2%)" },
  { value: "194D", label: "194D — Insurance Commission (5%)" },
  { value: "194H", label: "194H — Commission/Brokerage (5%)" },
  { value: "194I", label: "194I — Rent (10%)" },
  { value: "194IA", label: "194IA — Purchase of Immovable Property (1%)" },
  { value: "194J", label: "194J — Professional/Technical (10%)" },
  { value: "194Q", label: "194Q — Purchase of Goods (0.1%)" },
];

const TDS_DEFAULT_RATES: Record<string, number> = {
  "192":   0,    // variable
  "194A":  1000, // 10%
  "194B":  3000, // 30%
  "194C":  200,  // 2% in bps
  "194D":  500,  // 5%
  "194H":  500,  // 5%
  "194I":  1000, // 10%
  "194IA": 100,  // 1%
  "194J":  1000, // 10%
  "194Q":  10,   // 0.1%
};

// CGST Act Schedule — all notified rates
const GST_RATES = [
  { label: "0%", bps: 0 },
  { label: "0.1%", bps: 10 },
  { label: "0.25%", bps: 25 },
  { label: "1%", bps: 100 },
  { label: "1.5%", bps: 150 },
  { label: "3%", bps: 300 },
  { label: "5%", bps: 500 },
  { label: "6%", bps: 600 },
  { label: "7.5%", bps: 750 },
  { label: "12%", bps: 1200 },
  { label: "18%", bps: 1800 },
  { label: "28%", bps: 2800 },
];

// ── Purchase Bills ─────────────────────────────────────────────────────────

interface BillLine {
  description: string;
  hsn_sac: string;
  quantity: number;
  rate: number; // rupees, or txn-currency major units when foreign
  gst_rate_bps: number;
  expense_account_id: string;
}

interface CurrencyOption {
  code: string;
  symbol: string | null;
  display_name: string | null;
  minor_unit: number;
}

interface Vendor {
  id: string;
  name: string;
  gstin: string | null;
  tds_applicable: boolean;
  tds_section: string | null;
  tds_rate_bps: number;
}

interface PurchaseBillRow {
  id: string;
  bill_no: string | null;
  our_reference: string | null;
  bill_date: string;
  due_date: string | null;
  vendor_id: string;
  vendors?: { name: string };
  taxable_amount_paise: number;
  total_gst_paise: number;
  tds_paise: number;
  net_payable_paise: number;
  total_paise: number;
  status: string;
  is_ai_extracted: boolean;
}

function PurchaseBills({ clientId, financialYear }: { clientId: string; financialYear: string }) {
  const [bills, setBills] = useState<PurchaseBillRow[]>([]);
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [accounts, setAccounts] = useState<{ id: string; account_code: string; account_name: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [aiExtracted, setAiExtracted] = useState<Record<string, unknown> | null>(null);

  // Form state
  const [vendorId, setVendorId] = useState("");
  const [billNo, setBillNo] = useState("");
  const [billDate, setBillDate] = useState(toDate());
  const [dueDate, setDueDate] = useState("");
  const [lines, setLines] = useState<BillLine[]>([
    { description: "", hsn_sac: "", quantity: 1, rate: 0, gst_rate_bps: 1800, expense_account_id: "" },
  ]);

  // Multi-Currency (Phase 3 backend already ships this; UI wired up here).
  // Purchase bills have no edit/PATCH flow — this form is create-only, so
  // there's no "locked after posting" state to show; currency just resets
  // manually after each save (see handleSave), since this form never unmounts.
  const [currency, setCurrency] = useState("");
  const [exchangeRate, setExchangeRate] = useState("");
  const [mcActive, setMcActive] = useState(false);
  const [currencies, setCurrencies] = useState<CurrencyOption[]>([]);

  useEffect(() => {
    if (!clientId) return;
    let cancelled = false;
    (async () => {
      const token = await getAuthToken();
      const pol = await apiGet(`/api/currencies/policy?client_id=${clientId}`, token);
      if (cancelled) return;
      const active = Boolean(pol.success && (pol.data as { active?: boolean } | null)?.active);
      setMcActive(active);
      if (!active) return;
      const list = await apiGet(`/api/currencies?active_only=true`, token);
      if (!cancelled && list.success) setCurrencies((list.data as CurrencyOption[]) ?? []);
    })();
    return () => { cancelled = true; };
  }, [clientId]);

  const isForeign = currency !== "" && currency !== "INR";
  const rateNum = parseFloat(exchangeRate);

  // Rough client-side preview only — the backend recomputes everything from
  // `lines` + `vendor_id` on save (this form's POST body never sends totals).
  function fmtAmt(paise: number): string {
    return isForeign ? formatMoney(paise, currency) : fmt(paise);
  }

  const selectedVendor = vendors.find((v) => v.id === vendorId);

  const load = useCallback(async () => {
    setLoading(true);
    const supabase = getSupabaseClient();
    const { start, end } = fyRange(financialYear);
    const [billsRes, vendorsRes, accsRes] = await Promise.all([
      selectAll(() => supabase
        .from("purchase_bills")
        .select("*, vendors(name)")
        .eq("client_id", clientId)
        .gte("bill_date", start)
        .lte("bill_date", end)
        .order("bill_date", { ascending: false })
        .order("id")),
      selectAll(() => supabase
        .from("vendors")
        .select("id, name, gstin, tds_applicable, tds_section, tds_rate_bps")
        .eq("client_id", clientId)
        .eq("is_active", true)
        .order("name")
        .order("id")),
      selectAll(() => supabase
        .from("chart_of_accounts")
        .select("id, account_code, account_name")
        .or(`client_id.eq.${clientId},client_id.is.null`)
        .in("account_type", ["Expense", "Asset"])
        .eq("is_active", true)
        .order("account_code")
        .order("id")),
    ]);
    setBills((billsRes.data as PurchaseBillRow[]) ?? []);
    setVendors((vendorsRes.data as Vendor[]) ?? []);
    setAccounts(accsRes.data ?? []);
    setLoading(false);
  }, [clientId, financialYear]);

  useEffect(() => { load(); }, [load]);

  // Compute GST for a line (integer basis points)
  function lineGst(line: BillLine) {
    const taxable = Math.round(line.quantity * line.rate * 100); // paise
    const gst_paise = Math.floor((taxable * line.gst_rate_bps) / 10000);
    return {
      taxable_paise: taxable,
      gst_paise,
      line_total: taxable + gst_paise,
    };
  }

  const totals = lines.reduce(
    (acc, l) => {
      const g = lineGst(l);
      return {
        taxable: acc.taxable + g.taxable_paise,
        gst: acc.gst + g.gst_paise,
        total: acc.total + g.line_total,
      };
    },
    { taxable: 0, gst: 0, total: 0 }
  );

  // TDS is a purely domestic, INR-only concept (IT Act §194) — the backend
  // always computes it off the INR-equivalent taxable value, converting a
  // foreign bill's txn-currency taxable to base BEFORE applying the TDS rate
  // (never off the raw foreign figure). Mirror that same order here so the
  // preview doesn't understate/overstate TDS by the exchange-rate factor.
  // See lib/services/currencyPreview.ts (unit-tested) for the exact math.
  const estBaseTaxable = isForeign && rateNum > 0 ? estimateBaseMinor(totals.taxable, rateNum) : totals.taxable;
  const estBaseTotal = isForeign && rateNum > 0 ? estimateBaseMinor(totals.total, rateNum) : totals.total;

  const tds_paise = // always INR paise — never formatted via fmtAmt()
    selectedVendor?.tds_applicable && selectedVendor.tds_rate_bps > 0
      ? estimateForeignTds(estBaseTaxable, selectedVendor.tds_rate_bps)
      : 0;

  // Net payable to a foreign vendor is actionable in their own currency — the
  // amount actually wired — so convert the INR TDS back at the entered rate.
  const net_payable = isForeign
    ? totals.total - convertBaseToForeignMinor(tds_paise, rateNum)
    : totals.total - tds_paise;

  function setLine(idx: number, patch: Partial<BillLine>) {
    setLines((prev) => prev.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
  }

  // AI document extraction
  async function handleExtract() {
    if (!uploadFile) return;
    setExtracting(true);
    setAiExtracted(null);
    try {
      const formData = new FormData();
      formData.append("file", uploadFile);
      formData.append("client_id", clientId);
      const token = (await getSupabaseClient().auth.getSession()).data.session?.access_token;
      const res = await fetch(`${API}/api/document-intelligence-v1/extract-invoice`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
      });
      const json = await res.json();
      if (json.success && json.data?.extracted) {
        const ex = json.data.extracted;
        setAiExtracted(ex);
        // Pre-fill form
        if (ex.invoice_no) setBillNo(ex.invoice_no);
        if (ex.invoice_date) setBillDate(ex.invoice_date);
        if (ex.line_items?.length) {
          setLines(
            (ex.line_items as Array<Record<string, unknown>>).map((li) => ({
              description: String(li.description ?? ""),
              hsn_sac: String(li.hsn_sac ?? ""),
              quantity: Number(li.quantity ?? 1),
              rate: Math.floor(Number(li.rate_paise ?? 0)) / 100,
              gst_rate_bps: Number(li.gst_rate_bps ?? 1800),
              expense_account_id: "",
            }))
          );
        }
      } else {
        // R2.8/F19: the backend no longer fabricates a plausible-looking
        // invoice when AI extraction is unavailable or fails — surface the
        // honest error instead of silently leaving the form blank.
        setMsg({ type: "err", text: json.error || "AI extraction failed. Please enter the bill details manually." });
      }
    } catch {
      setMsg({ type: "err", text: "AI extraction failed. Please enter the bill details manually." });
    } finally {
      setExtracting(false);
    }
  }

  async function handleSave() {
    if (!vendorId) { setMsg({ type: "err", text: "Select a vendor" }); return; }
    if (lines.some((l) => !l.description)) { setMsg({ type: "err", text: "All lines need a description" }); return; }
    if (isForeign && (!exchangeRate.trim() || !(rateNum > 0))) {
      setMsg({ type: "err", text: `Enter a valid exchange rate for ${currency} → INR` });
      return;
    }
    setSaving(true);
    setMsg(null);
    try {
      const token = await getAuthToken();
      const result = await apiCall(
        "/api/purchase-bills/",
        "POST",
        {
          client_id: clientId,
          vendor_id: vendorId,
          bill_date: billDate,
          due_date: dueDate || undefined,
          bill_no: billNo || undefined,
          lines: lines.map((l) => ({
            description: l.description,
            hsn_sac: l.hsn_sac || undefined,
            quantity: l.quantity,
            rate_paise: Math.round(l.rate * 100),
            // PurchaseBillLineIn (apps/api/models/invoices.py) declares
            // gst_rate_percent, not gst_rate_bps — the latter is silently
            // dropped by Pydantic and every line falls back to the model's
            // 18% default regardless of the rate picked here (Part 4, Beta batch).
            gst_rate_percent: l.gst_rate_bps / 100,
            expense_account_id: l.expense_account_id || undefined,
          })),
          currency: isForeign ? currency : undefined,
          exchange_rate: isForeign ? exchangeRate : undefined,
        },
        token
      );
      if (!result.success) throw new Error(result.error ?? "Failed to create bill");

      setMsg({ type: "ok", text: "Purchase bill saved as draft." });
      setShowForm(false);
      setLines([{ description: "", hsn_sac: "", quantity: 1, rate: 0, gst_rate_bps: 1800, expense_account_id: "" }]);
      setBillNo(""); setVendorId(""); setBillDate(toDate()); setDueDate(""); setAiExtracted(null);
      setCurrency(""); setExchangeRate("");
      load();
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Save failed" });
    } finally {
      setSaving(false);
    }
  }

  async function handleReceive(billId: string) {
    try {
      const token = await getAuthToken();
      // CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
      await apiCall(`/api/purchase-bills/${billId}/receive`, "POST", undefined, token);
      load();
    } catch { /* skip */ }
  }

  // Bulk receive over the DataTable's selected rows. POST
  // /api/purchase-bills/{id}/receive is draft-only on the backend (each row's
  // journal-posting/FY-lock validation runs server-side) — loop per row via
  // Promise.all so a mid-batch failure on one bill (e.g. FY-lock 409) is safe
  // and can't corrupt the rest. Non-draft rows are skipped client-side (mirrors
  // the single-row "Receive" rowAction's status === "draft" gate) rather than
  // sent to the backend to 422. Refresh only if at least one bill was received,
  // and keep the selection (return false) if anything was skipped or failed so
  // the user can see what's left.
  const handleBulkReceive = useCallback(async (rows: PurchaseBillRow[]): Promise<boolean> => {
    const token = await getAuthToken();
    const draftRows = rows.filter((b) => b.status === "draft");
    const skipped = rows.length - draftRows.length;

    type ReceiveResult = { ok: true } | { ok: false; reason: string };
    const results: ReceiveResult[] = await Promise.all(
      draftRows.map(async (b): Promise<ReceiveResult> => {
        try {
          // CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
          const result = await apiCall(`/api/purchase-bills/${b.id}/receive`, "POST", undefined, token);
          if (result.success) return { ok: true };
          return { ok: false, reason: result.error ?? "Failed to receive bill" };
        } catch (e) {
          return { ok: false, reason: e instanceof Error ? e.message : "Failed to receive bill" };
        }
      })
    );

    const received = results.filter((r) => r.ok).length;
    const failures = results.filter((r): r is { ok: false; reason: string } => !r.ok);
    const failed = failures.length;

    if (received > 0) load();

    const parts: string[] = [];
    if (received > 0) parts.push(`${received} received`);
    if (skipped > 0) parts.push(`${skipped} skipped (not draft)`);
    if (failed > 0) {
      const reasons = Array.from(new Set(failures.map((f) => f.reason)));
      parts.push(`${failed} failed (${reasons.join("; ")})`);
    }
    const text = parts.length > 0 ? `${parts.join(", ")}.` : "No draft bills selected.";

    if (skipped > 0 || failed > 0) {
      setMsg({ type: "err", text });
      return false;
    }
    setMsg({ type: "ok", text });
    return true;
  }, [load]);

  /**
   * Bulk-import handler. Maps flat rows → grouped bills via buildPurchaseBills, then
   * creates each through the EXISTING /api/purchase-bills/ endpoint (no parallel logic).
   * Bills land as drafts. Vendors must already exist (referenced by name).
   */
  async function handleImport(rows: ImportRow[]): Promise<{ imported: number; errors: string[] }> {
    const vendorRefs: NameRef[] = vendors.map((v) => ({ id: v.id, name: v.name }));
    const { bills: built, errors } = buildPurchaseBills(rows, clientId, vendorRefs);
    const token = await getAuthToken();
    let imported = 0;
    for (const bill of built) {
      const { ref, ...payload } = bill; // drop the internal grouping key
      void ref;
      const result = await apiCall("/api/purchase-bills/", "POST", payload, token);
      if (result.success) imported += bill.lines.length;
      else errors.push(`Bill "${bill.bill_no ?? bill.ref}": ${result.error ?? "failed to create"}`);
    }
    if (imported > 0) load();
    return { imported, errors };
  }

  const totalPayable = bills.filter((b) => !["paid", "cancelled"].includes(b.status))
    .reduce((s, b) => s + b.net_payable_paise, 0);
  const totalThisFy = bills.reduce((s, b) => s + b.total_paise, 0);

  // ── DataTable columns (money columns return integer paise, right-aligned) ────
  const billColumns: Column<PurchaseBillRow>[] = useMemo(() => [
    { key: "our_reference", header: "Our Ref", accessor: (b) => b.our_reference ?? "", searchable: true,
      render: (b) => <span className="font-mono text-[10px] text-[#475569]">{b.our_reference ?? "—"}</span> },
    { key: "bill_no", header: "Vendor Invoice", accessor: (b) => b.bill_no ?? "", searchable: true,
      render: (b) => (
        <span className="text-[#475569]">
          {b.bill_no ?? "—"}
          {b.is_ai_extracted && <span className="ml-1 text-[9px] bg-amber-100 text-amber-600 px-1 rounded">AI</span>}
        </span>
      ) },
    { key: "vendor", header: "Vendor", accessor: (b) => b.vendors?.name ?? "", searchable: true, sticky: true, hideable: false,
      render: (b) => <span className="font-medium text-[#1E293B]">{b.vendors?.name ?? "—"}</span> },
    { key: "bill_date", header: "Date", accessor: (b) => b.bill_date, sortable: true,
      render: (b) => <span className="text-[#64748B]">{b.bill_date}</span> },
    { key: "taxable", header: "Taxable", accessor: (b) => b.taxable_amount_paise, align: "right",
      render: (b) => <span className="font-mono text-[#334155]">{fmt(b.taxable_amount_paise)}</span> },
    { key: "gst", header: "GST", accessor: (b) => b.total_gst_paise, align: "right",
      render: (b) => <span className="font-mono text-[#64748B]">{fmt(b.total_gst_paise)}</span> },
    { key: "tds", header: "TDS", accessor: (b) => b.tds_paise, align: "right",
      render: (b) => <span className="font-mono text-blue-600">{b.tds_paise > 0 ? fmt(b.tds_paise) : "—"}</span> },
    { key: "net_payable", header: "Net Payable", accessor: (b) => b.net_payable_paise, sortable: true, align: "right",
      render: (b) => <span className="font-mono font-semibold text-[#1E293B]">{fmt(b.net_payable_paise)}</span> },
    { key: "status", header: "Status", accessor: (b) => b.status, sortable: true,
      render: (b) => (
        <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${STATUS_COLORS[b.status] ?? "bg-[#F1F5F9] text-[#475569]"}`}>{b.status}</span>
      ) },
  ], []);

  const billFilters: FilterDef<PurchaseBillRow>[] = useMemo(() => [
    { key: "status", label: "Status", type: "select", accessor: (b) => b.status,
      options: Object.keys(STATUS_COLORS).map((s) => ({ value: s, label: s })) },
    { key: "vendor", label: "Vendor", type: "select", accessor: (b) => b.vendors?.name ?? "",
      options: vendors.map((v) => ({ value: v.name, label: v.name })) },
    { key: "bill_date", label: "Bill date", type: "dateRange", accessor: (b) => b.bill_date },
    { key: "net_payable", label: "Net payable", type: "amountRange", accessor: (b) => b.net_payable_paise },
    { key: "is_ai_extracted", label: "AI-extracted", type: "boolean", accessor: (b) => b.is_ai_extracted },
  ], [vendors]);

  // ── DataTable bulk actions — receive is draft-only (non-draft rows are
  // skipped client-side); export just CSV-dumps the checked rows. ─────────
  const bulkActions: BulkAction<PurchaseBillRow>[] = useMemo(() => [
    {
      id: "receive",
      label: "Receive draft(s)",
      icon: <CheckCircle size={12} />,
      confirm: "Receive the selected draft purchase bills? This posts a journal entry for each and cannot be undone.",
      run: handleBulkReceive,
    },
    exportSelectedAction("purchase-bills-selected.csv", billColumns),
  ], [handleBulkReceive, billColumns]);

  return (
    <div className="space-y-4 max-w-5xl">
      {msg && (
        <div className={`flex items-center gap-2 px-4 py-3 rounded-lg text-sm ${msg.type === "ok" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-600"}`}>
          {msg.type === "ok" ? <CheckCircle size={14} /> : <AlertCircle size={14} />}
          {msg.text}
          <button onClick={() => setMsg(null)} className="ml-auto"><X size={13} /></button>
        </div>
      )}

      {/* Summary strip */}
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <p className="text-[10px] text-[#64748B] mb-1">Outstanding Payable</p>
          <p className="text-lg font-bold text-orange-700 tabular-nums">{fmt(totalPayable)}</p>
        </div>
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <p className="text-[10px] text-[#64748B] mb-1">Total Bills (FY)</p>
          <p className="text-lg font-bold text-[#1E293B] tabular-nums">{fmt(totalThisFy)}</p>
        </div>
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <p className="text-[10px] text-[#64748B] mb-1">Bills This FY</p>
          <p className="text-lg font-bold text-[#1E293B] tabular-nums">{bills.length}</p>
        </div>
      </div>

      <div className="flex justify-between items-center">
        <p className="text-xs font-semibold text-[#334155]">Purchase Bills — FY {financialYear}</p>
      </div>

      {showImport && (
        <CsvImportModal
          title="Import Purchase Bills"
          columns={PURCHASE_BILL_IMPORT_COLUMNS}
          templateFilename="purchase-bills-template.csv"
          onImport={handleImport}
          onClose={() => setShowImport(false)}
        />
      )}

      {/* Create form */}
      {showForm && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-[#0F172A]">New Purchase Bill</h3>
            <button onClick={() => setShowForm(false)} className="text-[#94A3B8] hover:text-[#475569]"><X size={16} /></button>
          </div>

          {/* AI Upload */}
          <div className="bg-amber-50 border border-amber-100 rounded-lg p-3 space-y-2">
            <p className="text-xs font-medium text-amber-800 flex items-center gap-1.5"><Upload size={12} /> Upload Invoice (AI Extract)</p>
            <div className="flex items-center gap-2">
              <input
                type="file"
                accept=".pdf,.png,.jpg,.jpeg"
                onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
                className="text-xs text-[#475569]"
              />
              <button
                onClick={handleExtract}
                disabled={!uploadFile || extracting}
                className="text-xs px-3 py-1.5 bg-amber-600 text-white rounded-lg hover:bg-amber-700 disabled:opacity-40"
              >
                {extracting ? "Extracting…" : "Extract"}
              </button>
            </div>
            {aiExtracted && (
              <div className="mt-1 text-[10px] text-amber-700 bg-amber-100 rounded px-2 py-1.5">
                ✓ AI extracted data pre-filled below. <strong>Review before saving.</strong>
              </div>
            )}
          </div>

          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <div className="col-span-2">
              <label className="block text-xs font-medium text-[#475569] mb-1">Vendor *</label>
              <VendorLookup
                vendors={vendors}
                value={vendorId}
                onChange={setVendorId}
                ariaLabel="Vendor"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Vendor Invoice No.</label>
              <input value={billNo} onChange={(e) => setBillNo(e.target.value)} placeholder="INV-001" className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Bill Date *</label>
              <input type="date" value={billDate} onChange={(e) => setBillDate(e.target.value)} className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Due Date</label>
              <input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
          </div>

          {/* Multi-Currency (Phase 3 backend, UI added here) — mirrors the
              Sales Invoice selector. Purchase bills have no edit flow, so
              there's no locked/read-only variant to show. */}
          {mcActive && (
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <div>
                <label className="block text-xs font-medium text-[#475569] mb-1">Currency</label>
                <select
                  value={currency}
                  onChange={(e) => { setCurrency(e.target.value); setExchangeRate(""); }}
                  className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">INR (default)</option>
                  {currencies.filter((c) => c.code !== "INR").map((c) => (
                    <option key={c.code} value={c.code}>
                      {c.code}{c.display_name ? ` — ${c.display_name}` : ""}
                    </option>
                  ))}
                </select>
              </div>
              {isForeign && (
                <>
                  <div>
                    <label className="block text-xs font-medium text-[#475569] mb-1">Exchange Rate *</label>
                    <input
                      type="number"
                      min="0"
                      step="0.0001"
                      value={exchangeRate}
                      onChange={(e) => setExchangeRate(e.target.value)}
                      placeholder={`1 ${currency} = ? INR`}
                      className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-right font-mono"
                    />
                    <p className="mt-1 text-[10px] text-[#94A3B8]">Today&apos;s rate — recorded as a manual booking rate, frozen on save.</p>
                  </div>
                  <div className="col-span-2 flex flex-col justify-end pb-1.5">
                    <span className="text-xs font-medium text-[#475569] mb-1">Estimated INR total</span>
                    <span className="font-mono text-sm text-[#0F172A]">
                      {rateNum > 0 && totals.total > 0 ? `≈ ${fmt(estBaseTotal)}` : "— enter a rate to preview —"}
                    </span>
                    <p className="mt-1 text-[10px] text-[#94A3B8]">Estimate only — the exact INR total is confirmed on save.</p>
                  </div>
                </>
              )}
            </div>
          )}

          {/* TDS info banner */}
          {selectedVendor?.tds_applicable && (
            <div className="bg-blue-50 border border-blue-100 rounded-lg px-3 py-2 text-xs text-blue-700">
              TDS applicable — §{selectedVendor.tds_section} @ {(selectedVendor.tds_rate_bps / 100).toFixed(1)}%
              {totals.taxable > 0 && ` | TDS: ${fmt(tds_paise)}${isForeign ? " (₹ — always deducted in INR, per IT Act)" : ""} | Net payable: ${fmtAmt(net_payable)}`}
            </div>
          )}

          {/* Lines */}
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[#F1F5F9] text-[#94A3B8]">
                  <th className="pb-2 text-left font-semibold">Description *</th>
                  <th className="pb-2 text-left font-semibold w-24">HSN/SAC</th>
                  <th className="pb-2 text-left font-semibold w-28">Expense Account</th>
                  <th className="pb-2 text-right font-semibold w-16">Qty</th>
                  <th className="pb-2 text-right font-semibold w-28">Rate ({isForeign ? currency : "₹"})</th>
                  <th className="pb-2 text-right font-semibold w-20">GST %</th>
                  <th className="pb-2 text-right font-semibold w-28">Amount{isForeign ? ` (${currency})` : ""}</th>
                  <th className="pb-2 w-6" />
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {lines.map((line, idx) => {
                  const g = lineGst(line);
                  return (
                    <tr key={idx}>
                      <td className="py-1.5 pr-2">
                        <input value={line.description} onChange={(e) => setLine(idx, { description: e.target.value })} placeholder="Item description" className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-xs" />
                      </td>
                      <td className="py-1.5 px-1">
                        <HsnLookup
                          clientId={clientId}
                          value={line.hsn_sac}
                          onChange={(v) => setLine(idx, { hsn_sac: v })}
                          onPick={(p) => { if (p.gst_rate_bps != null) setLine(idx, { gst_rate_bps: p.gst_rate_bps }); }}
                          size="sm"
                          ariaLabel="HSN or SAC code"
                        />
                      </td>
                      <td className="py-1.5 px-1">
                        <AccountLookup
                          accounts={accounts}
                          value={line.expense_account_id}
                          onChange={(id) => setLine(idx, { expense_account_id: id })}
                          size="sm"
                          placeholder="— Account —"
                          ariaLabel="Expense account"
                        />
                      </td>
                      <td className="py-1.5 px-1">
                        <input type="number" min="0.001" step="0.001" value={line.quantity} onChange={(e) => setLine(idx, { quantity: parseFloat(e.target.value) || 1 })} className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none text-xs text-right" />
                      </td>
                      <td className="py-1.5 px-1">
                        <input type="number" min="0" step="0.01" value={line.rate || ""} onChange={(e) => setLine(idx, { rate: parseFloat(e.target.value) || 0 })} placeholder="0.00" className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none text-xs text-right" />
                      </td>
                      <td className="py-1.5 px-1">
                        <select value={line.gst_rate_bps} onChange={(e) => setLine(idx, { gst_rate_bps: parseInt(e.target.value) })} className="w-full px-1 py-1 border border-[#E2E8F0] rounded focus:outline-none text-xs">
                          {GST_RATES.map((r) => <option key={r.bps} value={r.bps}>{r.label}</option>)}
                        </select>
                      </td>
                      <td className="py-1.5 px-1 text-right font-mono text-[#334155]">
                        {g.taxable_paise > 0 ? fmtAmt(g.line_total) : "—"}
                      </td>
                      <td className="py-1.5 pl-1">
                        {lines.length > 1 && <button onClick={() => setLines((prev) => prev.filter((_, i) => i !== idx))} className="text-[#CBD5E1] hover:text-red-600 font-bold">×</button>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot>
                <tr className="border-t border-[#F1F5F9] text-xs font-semibold">
                  <td colSpan={6} className="pt-2 text-right text-[#64748B] pr-2">Taxable{isForeign ? ` (${currency})` : ""}</td>
                  <td className="pt-2 text-right font-mono text-[#334155] px-1">{fmtAmt(totals.taxable)}</td>
                  <td />
                </tr>
                <tr className="text-xs">
                  <td colSpan={6} className="text-right text-[#94A3B8] pr-2">Total GST</td>
                  <td className="text-right font-mono text-[#64748B] px-1">{fmtAmt(totals.gst)}</td>
                  <td />
                </tr>
                {tds_paise > 0 && (
                  <tr className="text-xs">
                    <td colSpan={6} className="text-right text-blue-600 pr-2">Less: TDS{isForeign ? " (₹)" : ""}</td>
                    <td className="text-right font-mono text-blue-600 px-1">({fmt(tds_paise)})</td>
                    <td />
                  </tr>
                )}
                <tr className="text-xs font-bold border-t border-[#E2E8F0]">
                  <td colSpan={6} className="pt-1 text-right text-[#1E293B] pr-2">Net Payable{isForeign ? ` (${currency})` : ""}</td>
                  <td className="pt-1 text-right font-mono text-[#0F172A] px-1">{fmtAmt(net_payable)}</td>
                  <td />
                </tr>
                {isForeign && rateNum > 0 && totals.total > 0 && (
                  <tr className="text-xs">
                    <td colSpan={6} className="text-right text-[#94A3B8] pr-2">≈ Estimated INR total</td>
                    <td className="text-right font-mono text-[#94A3B8] px-1">{fmt(estBaseTotal)}</td>
                    <td />
                  </tr>
                )}
              </tfoot>
            </table>
          </div>
          <button onClick={() => setLines((prev) => [...prev, { description: "", hsn_sac: "", quantity: 1, rate: 0, gst_rate_bps: 1800, expense_account_id: "" }])} className="text-xs text-blue-600 hover:underline flex items-center gap-1"><Plus size={12} /> Add line</button>

          <div className="flex gap-3 justify-end pt-1">
            <button onClick={() => setShowForm(false)} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Cancel</button>
            <button onClick={handleSave} disabled={saving} className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40">
              {saving ? "Saving…" : "Save Draft"}
            </button>
          </div>
        </div>
      )}

      {/* Bills table — shared DataTable (search, sort, filters, pagination, export, prefs) */}
      <DataTable
        data={bills}
        columns={billColumns}
        filters={billFilters}
        getRowId={(b) => b.id}
        loading={loading}
        onRefresh={load}
        searchPlaceholder="Search by our ref, vendor invoice, or vendor…"
        initialSort={{ key: "bill_date", dir: "desc" }}
        exportFilename="purchase-bills"
        persistKey="purchases.bills"
        emptyTitle="No purchase bills"
        emptyDescription={`No purchase bills for FY ${financialYear}.`}
        toolbarExtra={
          <>
            <button
              onClick={() => setShowImport(true)}
              className="flex items-center gap-1.5 text-xs border border-[#E2E8F0] text-[#475569] px-3 py-1.5 rounded-lg hover:bg-[#F8FAFC]"
            >
              <Upload size={12} /> Import
            </button>
            <button
              onClick={() => setShowForm((s) => !s)}
              className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700"
            >
              <Plus size={12} /> New Bill
            </button>
          </>
        }
        bulkActions={bulkActions}
        rowActions={(b) =>
          b.status === "draft" ? (
            <button onClick={() => handleReceive(b.id)} className="text-xs text-blue-600 hover:underline">Receive</button>
          ) : null
        }
      />
    </div>
  );
}

// ── Vendors ────────────────────────────────────────────────────────────────

interface VendorRow {
  id: string;
  name: string;
  gstin: string | null;
  state_code: string | null;
  pan: string | null;
  email: string | null;
  phone: string | null;
  tds_applicable: boolean;
  tds_section: string | null;
  tds_rate_bps: number;
  opening_balance_paise: number;
  is_active: boolean;
}

const GSTIN_RE = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/;

function Vendors({ clientId }: { clientId: string; financialYear: string }) {
  const [vendors, setVendors] = useState<VendorRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  const [name, setName] = useState("");
  const [gstin, setGstin] = useState("");
  const [pan, setPan] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [tdsApplicable, setTdsApplicable] = useState(false);
  const [tdsSection, setTdsSection] = useState("194C");
  const [tdsRate, setTdsRate] = useState("2");
  const [openingBalance, setOpeningBalance] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    const supabase = getSupabaseClient();
    const { data } = await selectAll(() => supabase
      .from("vendors")
      .select("*")
      .eq("client_id", clientId)
      .eq("is_active", true)
      .order("name")
      .order("id"));
    setVendors((data as VendorRow[]) ?? []);
    setLoading(false);
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  /** Bulk-import vendors through the EXISTING /api/vendors/ endpoint. */
  async function handleImport(rows: ImportRow[]): Promise<{ imported: number; errors: string[] }> {
    const { records, errors } = buildVendors(rows, clientId);
    const token = await getAuthToken();
    let imported = 0;
    for (const v of records) {
      const result = await apiCall("/api/vendors/", "POST", v, token);
      if (result.success) imported++;
      else errors.push(`Vendor "${v.name}": ${result.error ?? "failed to create"}`);
    }
    if (imported > 0) load();
    return { imported, errors };
  }

  async function handleSave() {
    if (!name.trim()) { setMsg({ type: "err", text: "Name is required" }); return; }
    if (gstin && !GSTIN_RE.test(gstin.trim().toUpperCase())) { setMsg({ type: "err", text: "Invalid GSTIN format (15 chars: 2-digit state + PAN + entity + Z + check)" }); return; }
    setSaving(true);
    setMsg(null);
    try {
      const token = await getAuthToken();
      const cleanGstin = gstin.trim().toUpperCase() || undefined;
      const stateCode = cleanGstin ? cleanGstin.slice(0, 2) : undefined;
      const rateBps = tdsApplicable ? Math.round(parseFloat(tdsRate) * 100) : 0;

      const result = await apiCall(
        "/api/vendors/",
        "POST",
        {
          client_id: clientId,
          name: name.trim(),
          gstin: cleanGstin,
          state_code: stateCode,
          pan: pan.trim().toUpperCase() || undefined,
          email: email.trim() || undefined,
          phone: phone.trim() || undefined,
          tds_applicable: tdsApplicable,
          tds_section: tdsApplicable ? tdsSection : undefined,
          tds_rate_bps: rateBps,
          opening_balance_paise: Math.round(parseFloat(openingBalance || "0") * 100),
        },
        token
      );
      if (!result.success) throw new Error(result.error ?? "Failed to add vendor");
      setMsg({ type: "ok", text: "Vendor added." });
      setShowForm(false);
      setName(""); setGstin(""); setPan(""); setEmail(""); setPhone("");
      setTdsApplicable(false); setTdsSection("194C"); setTdsRate("2"); setOpeningBalance("");
      load();
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Save failed" });
    } finally {
      setSaving(false);
    }
  }

  // ── DataTable columns (opening balance returns integer paise, right-aligned) ─
  const vendorColumns: Column<VendorRow>[] = useMemo(() => [
    { key: "name", header: "Name", accessor: (v) => v.name, searchable: true, sortable: true, sticky: true, hideable: false,
      render: (v) => <span className="font-medium text-[#1E293B]">{v.name}</span> },
    { key: "gstin", header: "GSTIN", accessor: (v) => v.gstin ?? "", searchable: true,
      render: (v) => <span className="font-mono text-[10px] text-[#64748B]">{v.gstin ?? "—"}</span> },
    { key: "tds_applicable", header: "TDS", accessor: (v) => v.tds_applicable, align: "center",
      render: (v) => v.tds_applicable ? <span className="px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-blue-100 text-blue-700">Yes</span> : <span className="text-[#94A3B8]">—</span> },
    { key: "tds_section", header: "Section", accessor: (v) => v.tds_section ?? "",
      render: (v) => <span className="text-[#64748B]">{v.tds_section ?? "—"}</span> },
    { key: "tds_rate", header: "Rate", accessor: (v) => v.tds_rate_bps, sortable: true, align: "right",
      render: (v) => <span className="text-[#475569]">{v.tds_rate_bps > 0 ? `${(v.tds_rate_bps / 100).toFixed(1)}%` : "—"}</span> },
    { key: "opening_balance", header: "Opening Bal", accessor: (v) => v.opening_balance_paise, sortable: true, align: "right",
      render: (v) => <span className="font-mono text-[#334155]">{v.opening_balance_paise > 0 ? fmt(v.opening_balance_paise) : "—"}</span> },
    { key: "email", header: "Email", accessor: (v) => v.email ?? "", searchable: true, defaultHidden: true,
      render: (v) => <span className="text-[#64748B]">{v.email ?? "—"}</span> },
    { key: "phone", header: "Phone", accessor: (v) => v.phone ?? "", searchable: true, defaultHidden: true,
      render: (v) => <span className="text-[#64748B]">{v.phone ?? "—"}</span> },
  ], []);

  const vendorFilters: FilterDef<VendorRow>[] = useMemo(() => [
    { key: "tds_applicable", label: "TDS", type: "boolean", accessor: (v) => v.tds_applicable, trueLabel: "Applicable", falseLabel: "Not applicable" },
  ], []);

  return (
    <div className="space-y-4 max-w-4xl">
      {msg && (
        <div className={`flex items-center gap-2 px-4 py-3 rounded-lg text-sm ${msg.type === "ok" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-600"}`}>
          {msg.type === "ok" ? <CheckCircle size={14} /> : <AlertCircle size={14} />}
          {msg.text}
          <button onClick={() => setMsg(null)} className="ml-auto"><X size={13} /></button>
        </div>
      )}

      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-[#334155]">{vendors.length} vendor{vendors.length !== 1 ? "s" : ""}</p>
      </div>

      {showImport && (
        <CsvImportModal
          title="Import Vendors"
          columns={VENDOR_IMPORT_COLUMNS}
          templateFilename="vendors-template.csv"
          onImport={handleImport}
          onClose={() => setShowImport(false)}
        />
      )}

      {showForm && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-[#0F172A]">New Vendor</h3>
            <button onClick={() => setShowForm(false)}><X size={16} className="text-[#94A3B8]" /></button>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2">
              <label className="block text-xs font-medium text-[#475569] mb-1">Name *</label>
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Vendor legal name" className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">GSTIN</label>
              <input value={gstin} onChange={(e) => setGstin(e.target.value.toUpperCase())} placeholder="27AABCS1429B1Z5" maxLength={15} className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono" />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">PAN</label>
              <input value={pan} onChange={(e) => setPan(e.target.value.toUpperCase())} placeholder="ABCDE1234F" maxLength={10} className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono" />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Email</label>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Phone</label>
              <input value={phone} onChange={(e) => setPhone(e.target.value)} className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Opening Balance (₹ payable)</label>
              <input type="number" min="0" step="0.01" value={openingBalance} onChange={(e) => setOpeningBalance(e.target.value)} placeholder="0.00" className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
          </div>

          {/* TDS section */}
          <div className="bg-blue-50 border border-blue-100 rounded-lg p-3 space-y-2">
            <div className="flex items-center gap-2">
              <input type="checkbox" id="tds-toggle" checked={tdsApplicable} onChange={(e) => setTdsApplicable(e.target.checked)} className="rounded" />
              <label htmlFor="tds-toggle" className="text-xs font-medium text-blue-800">TDS Applicable (IT Act §194C/I/J)</label>
            </div>
            {tdsApplicable && (
              <div className="grid grid-cols-2 gap-3 pt-1">
                <div>
                  <label className="block text-xs font-medium text-[#475569] mb-1">TDS Section</label>
                  <Combobox
                    options={TDS_SECTIONS}
                    value={TDS_SECTIONS.find((s) => s.value === tdsSection) ?? null}
                    onChange={(v) => { const s = v && !Array.isArray(v) ? v : null; if (s) { setTdsSection(s.value); setTdsRate(String(TDS_DEFAULT_RATES[s.value] / 100)); } }}
                    getOptionId={(s) => s.value}
                    getLabel={(s) => s.label}
                    getSearchFields={(s) => [s.value, s.label]}
                    placeholder="Select section…"
                    searchPlaceholder="Search TDS section…"
                    ariaLabel="TDS section"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-[#475569] mb-1">TDS Rate (%)</label>
                  <input type="number" min="0" max="30" step="0.1" value={tdsRate} onChange={(e) => setTdsRate(e.target.value)} className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
              </div>
            )}
          </div>

          <div className="flex gap-3 justify-end">
            <button onClick={() => setShowForm(false)} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Cancel</button>
            <button onClick={handleSave} disabled={saving} className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40">{saving ? "Saving…" : "Add Vendor"}</button>
          </div>
        </div>
      )}

      {/* Vendors table — shared DataTable (search, sort, filters, pagination, export, prefs) */}
      <DataTable
        data={vendors}
        columns={vendorColumns}
        filters={vendorFilters}
        getRowId={(v) => v.id}
        loading={loading}
        onRefresh={load}
        searchPlaceholder="Search by name, GSTIN, email, or phone…"
        initialSort={{ key: "name", dir: "asc" }}
        exportFilename="vendors"
        persistKey="purchases.vendors"
        emptyTitle="No vendors"
        emptyDescription="No vendors added yet."
        toolbarExtra={
          <>
            <button onClick={() => setShowImport(true)} className="flex items-center gap-1.5 text-xs border border-[#E2E8F0] text-[#475569] px-3 py-1.5 rounded-lg hover:bg-[#F8FAFC]"><Upload size={12} /> Import</button>
            <button onClick={() => setShowForm((s) => !s)} className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700"><Plus size={12} /> Add Vendor</button>
          </>
        }
      />
    </div>
  );
}

// ── Payments ───────────────────────────────────────────────────────────────

interface PaymentRow {
  id: string;
  payment_no: string;
  payment_date: string;
  vendor_id: string;
  vendors?: { name: string };
  purchase_bill_id: string | null;
  amount_paise: number;
  payment_mode: string;
  reference_no: string | null;
}

function Payments({ clientId, financialYear }: { clientId: string; financialYear: string }) {
  const [payments, setPayments] = useState<PaymentRow[]>([]);
  const [vendors, setVendors] = useState<{ id: string; name: string }[]>([]);
  const [openBills, setOpenBills] = useState<{
    id: string; our_reference: string; bill_no: string | null; net_payable_paise: number;
    txn_currency?: string | null; exchange_rate?: string | null; txn_net_payable?: number | null;
  }[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  const [vendorId, setVendorId] = useState("");
  const [billId, setBillId] = useState("");
  const [payDate, setPayDate] = useState(toDate());
  const [amount, setAmount] = useState("");
  const [mode, setMode] = useState("bank");
  const [refNo, setRefNo] = useState("");

  // Multi-Currency (Phase 3 backend, UI added here). Unlike a receipt, a
  // foreign vendor payment MUST be linked to the bill it settles (the
  // backend has no "foreign advance" concept for payments) — so the Against
  // Bill field becomes required, not optional, once a foreign currency is
  // selected.
  const [currency, setCurrency] = useState("");
  const [exchangeRate, setExchangeRate] = useState("");
  const [mcActive, setMcActive] = useState(false);
  const [currencies, setCurrencies] = useState<CurrencyOption[]>([]);

  useEffect(() => {
    if (!clientId) return;
    let cancelled = false;
    (async () => {
      const token = await getAuthToken();
      const pol = await apiGet(`/api/currencies/policy?client_id=${clientId}`, token);
      if (cancelled) return;
      const active = Boolean(pol.success && (pol.data as { active?: boolean } | null)?.active);
      setMcActive(active);
      if (!active) return;
      const list = await apiGet(`/api/currencies?active_only=true`, token);
      if (!cancelled && list.success) setCurrencies((list.data as CurrencyOption[]) ?? []);
    })();
    return () => { cancelled = true; };
  }, [clientId]);

  const isForeign = currency !== "" && currency !== "INR";
  const rateNum = parseFloat(exchangeRate);

  function fmtAmt(paise: number): string {
    return isForeign ? formatMoney(paise, currency) : fmt(paise);
  }

  const visibleBills = openBills.filter(
    (b) => (b.txn_currency || "INR").toUpperCase() === (currency || "INR").toUpperCase()
  );

  function billDisplayAmt(b: { net_payable_paise: number; txn_net_payable?: number | null }): number {
    return isForeign ? (b.txn_net_payable ?? 0) : b.net_payable_paise;
  }

  const load = useCallback(async () => {
    setLoading(true);
    const supabase = getSupabaseClient();
    const { start, end } = fyRange(financialYear);
    const [pmtRes, vendorRes] = await Promise.all([
      selectAll(() => supabase
        .from("purchase_payments")
        .select("*, vendors(name)")
        .eq("client_id", clientId)
        .gte("payment_date", start)
        .lte("payment_date", end)
        .order("payment_date", { ascending: false })
        .order("id")),
      selectAll(() => supabase.from("vendors").select("id, name").eq("client_id", clientId).eq("is_active", true).order("name").order("id")),
    ]);
    setPayments((pmtRes.data as PaymentRow[]) ?? []);
    setVendors(vendorRes.data ?? []);
    setLoading(false);
  }, [clientId, financialYear]);

  useEffect(() => { load(); }, [load]);

  async function loadOpenBills(vId: string) {
    const supabase = getSupabaseClient();
    const { data } = await selectAll(() => supabase
      .from("purchase_bills")
      .select("id, our_reference, bill_no, net_payable_paise, txn_currency, exchange_rate, txn_net_payable")
      .eq("client_id", clientId)
      .eq("vendor_id", vId)
      .in("status", ["received", "partially_paid"])
      .order("bill_date", { ascending: false })
      .order("id"));
    setOpenBills(data ?? []);
    setBillId("");
  }

  async function handleSave() {
    if (!vendorId) { setMsg({ type: "err", text: "Select a vendor" }); return; }
    const amtPaise = Math.round(parseFloat(amount || "0") * 100);
    if (amtPaise <= 0) { setMsg({ type: "err", text: "Amount must be positive" }); return; }
    if (isForeign && !billId) { setMsg({ type: "err", text: "Select the bill this foreign payment settles" }); return; }
    if (isForeign && (!exchangeRate.trim() || !(rateNum > 0))) {
      setMsg({ type: "err", text: `Enter a valid exchange rate for ${currency} → INR` });
      return;
    }
    setSaving(true); setMsg(null);
    try {
      const token = await getAuthToken();
      const result = await apiCall(
        "/api/purchase-payments",
        "POST",
        {
          client_id: clientId,
          vendor_id: vendorId,
          payment_date: payDate,
          amount_paise: amtPaise,
          payment_mode: mode,
          reference_no: refNo || undefined,
          purchase_bill_id: billId || undefined,
          currency: isForeign ? currency : undefined,
          exchange_rate: isForeign ? exchangeRate : undefined,
        },
        token
      );
      if (!result.success) throw new Error(result.error ?? "Failed to record payment");

      setMsg({ type: "ok", text: "Payment recorded." });
      setShowForm(false);
      setVendorId(""); setBillId(""); setAmount(""); setRefNo(""); setMode("bank");
      setCurrency(""); setExchangeRate("");
      load();
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Save failed" });
    } finally {
      setSaving(false);
    }
  }

  const totalPaid = payments.reduce((s, p) => s + p.amount_paise, 0);

  // ── DataTable columns (amount returns integer paise, right-aligned) ──────────
  const paymentColumns: Column<PaymentRow>[] = useMemo(() => [
    { key: "payment_no", header: "Payment No", accessor: (p) => p.payment_no, searchable: true, sticky: true, hideable: false,
      render: (p) => <span className="font-mono text-[10px] text-[#475569]">{p.payment_no}</span> },
    { key: "payment_date", header: "Date", accessor: (p) => p.payment_date, sortable: true,
      render: (p) => <span className="text-[#64748B]">{p.payment_date}</span> },
    { key: "vendor", header: "Vendor", accessor: (p) => p.vendors?.name ?? "", searchable: true,
      render: (p) => <span className="font-medium text-[#1E293B]">{p.vendors?.name ?? "—"}</span> },
    { key: "amount", header: "Amount", accessor: (p) => p.amount_paise, sortable: true, align: "right",
      render: (p) => <span className="font-mono font-semibold text-[#1E293B]">{fmt(p.amount_paise)}</span> },
    { key: "payment_mode", header: "Mode", accessor: (p) => p.payment_mode, searchable: true,
      render: (p) => <span className="text-[#64748B] capitalize">{p.payment_mode}</span> },
    { key: "reference_no", header: "Reference", accessor: (p) => p.reference_no ?? "", searchable: true,
      render: (p) => <span className="text-[10px] text-[#94A3B8]">{p.reference_no ?? "—"}</span> },
  ], []);

  const paymentFilters: FilterDef<PaymentRow>[] = useMemo(() => [
    { key: "vendor", label: "Vendor", type: "select", accessor: (p) => p.vendors?.name ?? "",
      options: vendors.map((v) => ({ value: v.name, label: v.name })) },
    { key: "payment_mode", label: "Mode", type: "select", accessor: (p) => p.payment_mode,
      options: ["bank", "cash", "cheque", "upi", "neft", "rtgs"].map((m) => ({ value: m, label: m })) },
  ], [vendors]);

  return (
    <div className="space-y-4 max-w-4xl">
      {msg && (
        <div className={`flex items-center gap-2 px-4 py-3 rounded-lg text-sm ${msg.type === "ok" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-600"}`}>
          {msg.type === "ok" ? <CheckCircle size={14} /> : <AlertCircle size={14} />}
          {msg.text}
          <button onClick={() => setMsg(null)} className="ml-auto"><X size={13} /></button>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <p className="text-[10px] text-[#64748B] mb-1">Total Paid (FY)</p>
          <p className="text-lg font-bold text-green-700 tabular-nums">{fmt(totalPaid)}</p>
        </div>
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <p className="text-[10px] text-[#64748B] mb-1">Transactions</p>
          <p className="text-lg font-bold text-[#1E293B] tabular-nums">{payments.length}</p>
        </div>
      </div>

      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-[#334155]">Payments — FY {financialYear}</p>
      </div>

      {showForm && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-[#0F172A]">Record Payment</h3>
            <button onClick={() => setShowForm(false)}><X size={16} className="text-[#94A3B8]" /></button>
          </div>
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
            <div className="col-span-2 lg:col-span-1">
              <label className="block text-xs font-medium text-[#475569] mb-1">Vendor *</label>
              <VendorLookup
                vendors={vendors}
                value={vendorId}
                onChange={(id) => { setVendorId(id); if (id) loadOpenBills(id); }}
                ariaLabel="Vendor"
              />
            </div>
            {mcActive && (
              <div>
                <label className="block text-xs font-medium text-[#475569] mb-1">Currency</label>
                <select
                  value={currency}
                  onChange={(e) => { setCurrency(e.target.value); setExchangeRate(""); setBillId(""); }}
                  className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">INR (default)</option>
                  {currencies.filter((c) => c.code !== "INR").map((c) => (
                    <option key={c.code} value={c.code}>
                      {c.code}{c.display_name ? ` — ${c.display_name}` : ""}
                    </option>
                  ))}
                </select>
              </div>
            )}
            {isForeign && (
              <div>
                <label className="block text-xs font-medium text-[#475569] mb-1">Cash Exchange Rate *</label>
                <input
                  type="number"
                  min="0"
                  step="0.0001"
                  value={exchangeRate}
                  onChange={(e) => setExchangeRate(e.target.value)}
                  placeholder={`1 ${currency} = ? INR`}
                  className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-right font-mono"
                />
              </div>
            )}
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">
                Against Bill {isForeign ? "*" : "(optional)"}
              </label>
              <EntityLookup
                items={visibleBills}
                value={billId}
                onChange={setBillId}
                getId={(b) => b.id}
                getLabel={(b) => b.our_reference ?? b.bill_no ?? "—"}
                getSecondary={(b) => fmtAmt(billDisplayAmt(b))}
                getSearchFields={(b) => [b.our_reference ?? "", b.bill_no ?? ""]}
                clearable={!isForeign}
                placeholder={isForeign ? "— Select the bill this settles —" : "— Advance / Select bill —"}
                ariaLabel="Against bill"
              />
              {isForeign && (
                <p className="mt-1 text-[10px] text-[#94A3B8]">A foreign payment must be linked to the bill it settles — no unlinked foreign advance.</p>
              )}
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Date *</label>
              <input type="date" value={payDate} onChange={(e) => setPayDate(e.target.value)} className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Amount ({isForeign ? currency : "₹"}) *</label>
              <input type="number" min="0" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Mode</label>
              <select value={mode} onChange={(e) => setMode(e.target.value)} className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
                {["bank", "cash", "cheque", "upi", "neft", "rtgs"].map((m) => <option key={m}>{m}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Reference No.</label>
              <input value={refNo} onChange={(e) => setRefNo(e.target.value)} placeholder="UTR / cheque no." className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
          </div>
          <div className="flex gap-3 justify-end">
            <button onClick={() => setShowForm(false)} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Cancel</button>
            <button onClick={handleSave} disabled={saving} className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40">{saving ? "Saving…" : "Record Payment"}</button>
          </div>
        </div>
      )}

      {/* Payments table — shared DataTable (search, sort, filters, pagination, export, prefs) */}
      <DataTable
        data={payments}
        columns={paymentColumns}
        filters={paymentFilters}
        getRowId={(p) => p.id}
        loading={loading}
        onRefresh={load}
        searchPlaceholder="Search by payment no, vendor, mode, or reference…"
        initialSort={{ key: "payment_date", dir: "desc" }}
        exportFilename="purchase-payments"
        persistKey="purchases.payments"
        emptyTitle="No payments"
        emptyDescription={`No payments for FY ${financialYear}.`}
        toolbarExtra={
          <button onClick={() => setShowForm((s) => !s)} className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700"><Plus size={12} /> Record Payment</button>
        }
      />
    </div>
  );
}

// ── Debit Notes (C3) ─────────────────────────────────────────────────────────
// AP-side mirror of Credit Notes (sales/page.tsx): a debit note reduces a
// purchase bill's payable and reverses the ITC (CGST Act §34). Backend
// (/api/debit-notes) only supports list/create-draft/issue — no edit or
// delete — so this UI intentionally has no draft-line-editing or detail view,
// mirroring Credit Notes' own restrictions.

interface DebitNoteRow {
  id: string;
  debit_note_no: string | null;
  debit_note_date: string;
  vendor_id: string;
  vendor_name?: string;
  purchase_bill_id: string | null;
  purchase_bills?: { bill_no: string | null; our_reference: string | null } | null;
  reason: string | null;
  taxable_amount_paise: number;
  total_gst_paise: number;
  total_paise: number;
  status: string;
}

function DebitNotes({ clientId, financialYear }: { clientId: string; financialYear: string }) {
  const [debitNotes, setDebitNotes] = useState<DebitNoteRow[]>([]);
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [msg, setMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const supabase = getSupabaseClient();
    const { start, end } = fyRange(financialYear);
    const [dnRes, vendorsRes] = await Promise.all([
      // debit_notes.vendor_id has no FK to vendors — resolve the name via the
      // vendors list below instead of a PostgREST embed.
      selectAll(() => supabase
        .from("debit_notes")
        .select("*, purchase_bills(bill_no, our_reference)")
        .eq("client_id", clientId)
        .gte("debit_note_date", start)
        .lte("debit_note_date", end)
        .order("debit_note_date", { ascending: false })
        .order("id")),
      selectAll(() => supabase
        .from("vendors")
        .select("id, name, gstin, tds_applicable, tds_section, tds_rate_bps")
        .eq("client_id", clientId)
        .eq("is_active", true)
        .order("name")
        .order("id")),
    ]);
    const vendorList = (vendorsRes.data as Vendor[]) ?? [];
    const vendorMap = new Map(vendorList.map((v) => [v.id, v.name]));
    const rows = ((dnRes.data as DebitNoteRow[]) ?? []).map((d) => ({
      ...d,
      vendor_name: vendorMap.get(d.vendor_id) ?? "—",
    }));
    setDebitNotes(rows);
    setVendors(vendorList);
    setLoading(false);
  }, [clientId, financialYear]);

  useEffect(() => { load(); }, [load]);

  async function issueDebitNote(id: string) {
    try {
      const token = await getAuthToken();
      const result = await apiCall(`/api/debit-notes/${id}/issue`, "POST", undefined, token);
      if (!result.success) throw new Error(result.error ?? "Failed to issue debit note");
      setMsg({ type: "ok", text: "Debit note issued." });
      load();
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Error issuing debit note" });
    }
  }

  // Bulk delete over the DataTable's selected rows. DELETE /api/debit-notes/{id}
  // is draft-only on the backend (soft-deletes a draft; 422s "Cannot delete an
  // issued debit note…" for anything already issued, 404 if not found) — loop
  // per row so one rejection doesn't abort the rest, reuse the existing load()
  // to refresh, and report a summary. If anything was skipped, keep the
  // selection (return false) so the user can see what's left.
  const handleBulkDelete = useCallback(async (rows: DebitNoteRow[]): Promise<boolean> => {
    const token = await getAuthToken();
    const results = await Promise.all(
      rows.map(async (d) => {
        try {
          const result = await apiCall(`/api/debit-notes/${d.id}`, "DELETE", undefined, token);
          return result.success;
        } catch {
          return false;
        }
      })
    );
    const deleted = results.filter(Boolean).length;
    const skipped = results.length - deleted;
    load();
    if (skipped > 0) {
      setMsg({ type: "err", text: `${deleted} deleted, ${skipped} skipped (issued)` });
      return false;
    }
    setMsg({ type: "ok", text: `${deleted} debit note${deleted === 1 ? "" : "s"} deleted.` });
    return true;
  }, [load]);

  const columns: Column<DebitNoteRow>[] = useMemo(() => [
    { key: "debit_note_no", header: "DN No", accessor: (d) => d.debit_note_no ?? "", searchable: true, sortable: true, sticky: true, hideable: false,
      render: (d) => <span className="font-mono font-medium text-[#1E293B]">{d.debit_note_no ?? "—"}</span> },
    { key: "debit_note_date", header: "Date", accessor: (d) => d.debit_note_date, sortable: true,
      render: (d) => <span className="text-[#64748B] whitespace-nowrap">{d.debit_note_date}</span> },
    { key: "vendor_name", header: "Vendor", accessor: (d) => d.vendor_name ?? "", searchable: true,
      render: (d) => <span className="font-medium text-[#1E293B]">{d.vendor_name ?? "—"}</span> },
    { key: "linked_bill", header: "Linked Bill", accessor: (d) => d.purchase_bills?.our_reference ?? d.purchase_bills?.bill_no ?? "",
      render: (d) => <span className="font-mono text-[#64748B]">{d.purchase_bills?.our_reference ?? d.purchase_bills?.bill_no ?? "—"}</span> },
    { key: "reason", header: "Reason", accessor: (d) => d.reason ?? "", searchable: true,
      render: (d) => <span className="block max-w-[120px] truncate text-[#475569]">{d.reason ?? "—"}</span> },
    { key: "taxable", header: "Taxable", accessor: (d) => d.taxable_amount_paise, align: "right",
      render: (d) => <span className="font-mono text-[#334155]">{fmt(d.taxable_amount_paise)}</span> },
    { key: "gst", header: "GST", accessor: (d) => d.total_gst_paise, align: "right",
      render: (d) => <span className="font-mono text-[#64748B]">{fmt(d.total_gst_paise)}</span> },
    { key: "total_paise", header: "Total", accessor: (d) => d.total_paise, sortable: true, align: "right",
      render: (d) => <span className="font-mono font-semibold text-[#0F172A]">{fmt(d.total_paise)}</span> },
    { key: "status", header: "Status", accessor: (d) => d.status, sortable: true,
      render: (d) => (
        <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${STATUS_COLORS[d.status] ?? "bg-[#F1F5F9] text-[#475569]"}`}>
          {d.status}
        </span>
      ) },
  ], []);

  const filters: FilterDef<DebitNoteRow>[] = useMemo(() => [
    { key: "status", label: "Status", type: "select", accessor: (d) => d.status, options: [
      { value: "draft", label: "Draft" },
      { value: "issued", label: "Issued" },
    ] },
    { key: "vendor_name", label: "Vendor", type: "select", accessor: (d) => d.vendor_name ?? "",
      options: vendors.map((v) => ({ value: v.name, label: v.name })) },
  ], [vendors]);

  // ── DataTable bulk actions — delete is draft-only (backend rejects issued
  // debit notes with a 422); export just CSV-dumps the checked rows. ─────────
  const bulkActions: BulkAction<DebitNoteRow>[] = useMemo(() => [
    {
      id: "delete",
      label: "Delete draft(s)",
      icon: <Trash2 size={12} />,
      variant: "danger",
      confirm: "Delete the selected draft debit notes? This cannot be undone.",
      run: handleBulkDelete,
    },
    exportSelectedAction("debit-notes-selected.csv", columns),
  ], [handleBulkDelete, columns]);

  return (
    <div className="space-y-4 max-w-screen-2xl">
      {msg && (
        <div className={`flex items-center gap-2 px-4 py-3 rounded-lg text-sm ${msg.type === "ok" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-600"}`}>
          {msg.type === "ok" ? <CheckCircle size={14} /> : <AlertCircle size={14} />}
          {msg.text}
          <button onClick={() => setMsg(null)} className="ml-auto"><X size={13} /></button>
        </div>
      )}

      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-[#334155]">
          {debitNotes.length} debit note{debitNotes.length !== 1 ? "s" : ""} in FY {financialYear}
        </p>
      </div>

      {showForm && (
        <DebitNoteForm
          clientId={clientId}
          vendors={vendors}
          onSaved={() => { setShowForm(false); load(); setMsg({ type: "ok", text: "Debit note created." }); }}
          onCancel={() => setShowForm(false)}
        />
      )}

      {/* Table — shared DataTable (search, sort, filters, pagination, export, prefs) */}
      <DataTable
        data={debitNotes}
        columns={columns}
        filters={filters}
        getRowId={(d) => d.id}
        loading={loading}
        onRefresh={load}
        searchPlaceholder="Search DN no., vendor, or reason…"
        initialSort={{ key: "debit_note_date", dir: "desc" }}
        exportFilename="debit-notes"
        persistKey="purchases.debit-notes"
        emptyTitle={`No debit notes in FY ${financialYear}`}
        toolbarExtra={
          <button onClick={() => setShowForm((s) => !s)} className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700"><Plus size={12} /> Create Debit Note</button>
        }
        bulkActions={bulkActions}
        rowActions={(d) =>
          d.status === "draft" ? (
            <button onClick={() => issueDebitNote(d.id)} className="text-xs text-blue-600 hover:underline flex items-center gap-1">
              <CheckCircle size={11} /> Issue
            </button>
          ) : null
        }
      />
    </div>
  );
}

// ── Debit Note Form ──────────────────────────────────────────────────────────

interface DebitNoteLine {
  description: string;
  hsn_sac: string;
  quantity: number;
  rate: number; // rupees
  gst_rate_bps: number;
}

interface OpenBillOption {
  id: string;
  our_reference: string | null;
  bill_no: string | null;
  net_payable_paise: number;
  paid_paise: number;
  debited_paise: number;
}

function DebitNoteForm({
  clientId,
  vendors,
  onSaved,
  onCancel,
}: {
  clientId: string;
  vendors: Vendor[];
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [vendorId, setVendorId] = useState("");
  const [dnDate, setDnDate] = useState(toDate());
  const [reason, setReason] = useState("");
  const [billId, setBillId] = useState("");
  const [openBills, setOpenBills] = useState<OpenBillOption[]>([]);
  const [isInterstate, setIsInterstate] = useState(false);
  const [lines, setLines] = useState<DebitNoteLine[]>([
    { description: "", hsn_sac: "", quantity: 1, rate: 0, gst_rate_bps: 1800 },
  ]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadOpenBills(vId: string) {
    setBillId("");
    if (!vId) { setOpenBills([]); return; }
    const supabase = getSupabaseClient();
    const { data } = await selectAll(() => supabase
      .from("purchase_bills")
      .select("id, our_reference, bill_no, net_payable_paise, paid_paise, debited_paise")
      .eq("client_id", clientId)
      .eq("vendor_id", vId)
      .in("status", ["received", "partially_paid", "paid"])
      .order("bill_date", { ascending: false })
      .order("id"));
    setOpenBills(data ?? []);
  }

  function outstanding(b: OpenBillOption): number {
    return b.net_payable_paise - b.paid_paise - b.debited_paise;
  }

  function setLine(idx: number, patch: Partial<DebitNoteLine>) {
    setLines((prev) => prev.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
  }
  function addLine() {
    setLines((prev) => [...prev, { description: "", hsn_sac: "", quantity: 1, rate: 0, gst_rate_bps: 1800 }]);
  }
  function removeLine(idx: number) {
    if (lines.length <= 1) return;
    setLines((prev) => prev.filter((_, i) => i !== idx));
  }

  const totals = lines.reduce(
    (acc, l) => {
      const g = dnLineGst(l, isInterstate);
      return {
        taxable: acc.taxable + g.taxable_paise,
        cgst: acc.cgst + g.cgst_paise,
        sgst: acc.sgst + g.sgst_paise,
        igst: acc.igst + g.igst_paise,
        total: acc.total + g.line_total,
      };
    },
    { taxable: 0, cgst: 0, sgst: 0, igst: 0, total: 0 }
  );

  async function handleSave() {
    if (!vendorId) { setError("Select a vendor"); return; }
    const validLines = lines.filter((l) => l.description.trim() && l.rate > 0);
    if (validLines.length === 0) { setError("Add at least one line with description and rate"); return; }

    setSaving(true); setError(null);
    try {
      const token = await getAuthToken();
      const result = await apiCall(
        "/api/debit-notes/",
        "POST",
        {
          client_id: clientId,
          vendor_id: vendorId,
          debit_note_date: dnDate,
          purchase_bill_id: billId || undefined,
          reason: reason.trim() || undefined,
          is_interstate: isInterstate,
          lines: validLines.map((l) => ({
            description: l.description.trim(),
            hsn_sac: l.hsn_sac || undefined,
            quantity: l.quantity,
            rate_paise: Math.round(l.rate * 100),
            // Backend's shared InvoiceLineIn model declares gst_rate_percent
            // (not gst_rate_bps) — send the field it actually reads.
            gst_rate_percent: l.gst_rate_bps / 100,
          })),
        },
        token
      );
      if (!result.success) throw new Error(result.error ?? "Failed to create debit note");

      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save debit note");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="bg-white rounded-xl border border-[#F1F5F9] p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-[#0F172A]">Create Debit Note</h3>
        <button onClick={onCancel} className="text-[#94A3B8] hover:text-[#475569]"><X size={16} /></button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">Vendor *</label>
          <VendorLookup
            vendors={vendors}
            value={vendorId}
            onChange={(id) => { setVendorId(id); loadOpenBills(id); }}
            ariaLabel="Vendor"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">DN Date *</label>
          <input
            type="date"
            value={dnDate}
            onChange={(e) => setDnDate(e.target.value)}
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">Against Bill (optional)</label>
          <EntityLookup
            items={openBills}
            value={billId}
            onChange={setBillId}
            getId={(b) => b.id}
            getLabel={(b) => b.our_reference ?? b.bill_no ?? "—"}
            getSecondary={(b) => `${fmt(outstanding(b))} outstanding`}
            getSearchFields={(b) => [b.our_reference ?? "", b.bill_no ?? ""]}
            clearable
            disabled={!vendorId}
            placeholder="— Standalone / Select bill —"
            ariaLabel="Against bill"
          />
        </div>
        <div className="col-span-2">
          <label className="block text-xs font-medium text-[#475569] mb-1">Reason</label>
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Goods returned / rate correction / excess billed"
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div className="flex items-end pb-1.5">
          <label className="flex items-center gap-2 text-xs text-[#475569] cursor-pointer">
            <input
              type="checkbox"
              checked={isInterstate}
              onChange={(e) => setIsInterstate(e.target.checked)}
              className="rounded"
            />
            Interstate (IGST)
          </label>
        </div>
      </div>

      {/* Lines */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-[#F1F5F9] text-[#94A3B8]">
              <th className="pb-2 text-left font-semibold">Description</th>
              <th className="pb-2 text-left font-semibold w-24">HSN/SAC</th>
              <th className="pb-2 text-right font-semibold w-16">Qty</th>
              <th className="pb-2 text-right font-semibold w-24">Rate (₹)</th>
              <th className="pb-2 text-right font-semibold w-20">GST %</th>
              <th className="pb-2 text-right font-semibold w-24">Amount</th>
              <th className="pb-2 w-6" />
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F8FAFC]">
            {lines.map((line, idx) => {
              const g = dnLineGst(line, isInterstate);
              return (
                <tr key={idx}>
                  <td className="py-1.5 pr-2">
                    <input
                      value={line.description}
                      onChange={(e) => setLine(idx, { description: e.target.value })}
                      placeholder="Item description"
                      className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-xs"
                    />
                  </td>
                  <td className="py-1.5 pr-2">
                    <HsnLookup
                      clientId={clientId}
                      value={line.hsn_sac}
                      onChange={(v) => setLine(idx, { hsn_sac: v })}
                      onPick={(p) => { if (p.gst_rate_bps != null) setLine(idx, { gst_rate_bps: p.gst_rate_bps }); }}
                      description={line.description}
                      size="sm"
                      ariaLabel="HSN or SAC code"
                    />
                  </td>
                  <td className="py-1.5 pr-2">
                    <input
                      type="number" min="0.001" step="0.001" value={line.quantity}
                      onChange={(e) => setLine(idx, { quantity: parseFloat(e.target.value) || 1 })}
                      className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-right text-xs"
                    />
                  </td>
                  <td className="py-1.5 pr-2">
                    <input
                      type="number" min="0" step="0.01" value={line.rate || ""}
                      onChange={(e) => setLine(idx, { rate: parseFloat(e.target.value) || 0 })}
                      placeholder="0.00"
                      className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-right text-xs"
                    />
                  </td>
                  <td className="py-1.5 pr-2">
                    <select
                      value={line.gst_rate_bps}
                      onChange={(e) => setLine(idx, { gst_rate_bps: parseInt(e.target.value) })}
                      className="w-full px-1 py-1 border border-[#E2E8F0] rounded focus:outline-none text-xs"
                    >
                      {GST_RATES.map((r) => <option key={r.bps} value={r.bps}>{r.label}</option>)}
                    </select>
                  </td>
                  <td className="py-1.5 px-2 text-right font-mono text-[#334155]">
                    {g.taxable_paise > 0 ? fmt(g.line_total) : "—"}
                  </td>
                  <td className="py-1.5">
                    {lines.length > 1 && (
                      <button onClick={() => removeLine(idx)} className="text-[#CBD5E1] hover:text-red-600">
                        <X size={13} />
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <button onClick={addLine} className="text-xs text-blue-600 hover:underline flex items-center gap-1">
        <Plus size={12} /> Add line
      </button>

      {/* GST Preview */}
      {totals.taxable > 0 && (
        <div className="bg-[#F8FAFC] rounded-lg p-3 text-xs space-y-1">
          <p className="font-semibold text-[#334155] mb-2">GST Computation (Debit Note)</p>
          <div className="flex justify-between text-[#475569]">
            <span>Taxable Value</span>
            <span className="font-mono">{fmt(totals.taxable)}</span>
          </div>
          {isInterstate ? (
            <div className="flex justify-between text-[#475569]">
              <span>IGST</span>
              <span className="font-mono">{fmt(totals.igst)}</span>
            </div>
          ) : (
            <>
              <div className="flex justify-between text-[#475569]">
                <span>CGST</span>
                <span className="font-mono">{fmt(totals.cgst)}</span>
              </div>
              <div className="flex justify-between text-[#475569]">
                <span>SGST</span>
                <span className="font-mono">{fmt(totals.sgst)}</span>
              </div>
            </>
          )}
          <div className="flex justify-between font-semibold text-[#0F172A] border-t border-[#E2E8F0] pt-1 mt-1">
            <span>Total Debit Note Amount</span>
            <span className="font-mono">{fmt(totals.total)}</span>
          </div>
        </div>
      )}

      {error && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}
      <div className="flex gap-3 justify-end">
        <button onClick={onCancel} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Cancel</button>
        <button
          onClick={handleSave}
          disabled={saving}
          className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save Debit Note"}
        </button>
      </div>
    </div>
  );
}
