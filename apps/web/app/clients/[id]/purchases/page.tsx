"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import { Plus, Upload, AlertCircle, AlertTriangle, CheckCircle, Trash2, X, Loader2, Paperclip, MoreHorizontal, Ban, RotateCcw } from "lucide-react";
import { PurchaseBillViewDrawer } from "@/components/purchases/PurchaseBillViewDrawer";
import type { PurchaseBillDetail } from "@/components/purchases/PurchaseBillEditor";
import { writePurchaseBillDuplicateSeed } from "@/lib/purchases/duplicateSeed";
import { DebitNoteViewDrawer } from "@/components/purchases/DebitNoteViewDrawer";
import type { DebitNoteDetail } from "@/components/purchases/DebitNoteEditor";
import { writeDebitNoteDuplicateSeed } from "@/lib/purchases/debitNoteDuplicateSeed";
import { PurchaseCreditNoteViewDrawer } from "@/components/purchases/PurchaseCreditNoteViewDrawer";
import type { PurchaseCreditNoteDetail } from "@/components/purchases/PurchaseCreditNoteEditor";
import { writePurchaseCreditNoteDuplicateSeed } from "@/lib/purchases/purchaseCreditNoteDuplicateSeed";
import { confirmDialog } from "@/components/ui/confirm-dialog";
import { useClientNav, getCurrentFinancialYear } from "@/lib/workspace/ClientNavContext";
import FinancialYearPicker from "@/components/FinancialYearPicker";
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import { paiseFromRupeeInput, bpsFromPercentInput } from "@/lib/money/rupeeInput";
import { formatPaise, formatMoney } from "@/lib/services/formatting";
import { DataTable, exportSelectedAction } from "@/components/ui/data-table";
import type { BulkAction, Column, FilterDef } from "@/lib/table/types";
import { VendorLookup } from "@/components/lookups/VendorLookup";
import type { ServiceCatalogueItem } from "@/lib/catalogue/service";
import { ProductServiceFormModal } from "@/components/catalogue/ProductServiceFormModal";
import { EntityLookup } from "@/components/lookups/EntityLookup";
import { Combobox } from "@/components/ui/combobox";
import CsvImportModal, { type ImportRow, type ReferenceResolver } from "@/components/CsvImportModal";
import {
  buildVendors, VENDOR_IMPORT_COLUMNS, buildPurchaseBills, PURCHASE_BILL_IMPORT_COLUMNS,
  buildPurchaseDebitNotes, PURCHASE_DEBIT_NOTE_IMPORT_COLUMNS,
  buildPurchaseCreditNotes, PURCHASE_CREDIT_NOTE_IMPORT_COLUMNS,
  type NameRef, type PurchaseServiceRef, type OriginalDocRef,
} from "@/lib/imports/mappers";
import PeriodPicker from "@/components/PeriodPicker";
import { resolvePeriodRange, periodOptionLabel, type PeriodMode } from "@/lib/dates/periods";
import { mapWithConcurrency } from "@/lib/table/concurrency";
import { TableSkeleton } from "@/components/ui/skeleton";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── API helpers ────────────────────────────────────────────────────────────

// A bulk action (handleBulkReceive etc.) fetches ONE token before looping
// over hundreds of rows via mapWithConcurrency — a batch large enough to
// outlive that token surfaces as "Token expired" on every call past the
// expiry boundary (the actual incident this guards against: 754 selected
// bills, 440 received then 314 failed once the token crossed expiry mid-
// batch). Refresh once and retry on 401 instead of failing the rest of the
// batch — safe because a 401 means auth rejected the request before any
// handler ran, so nothing was processed server-side.
async function refreshedAuthToken(): Promise<string | null> {
  const supabase = getSupabaseClient();
  const { data } = await supabase.auth.refreshSession();
  return data.session?.access_token ?? null;
}

async function apiCall(
  endpoint: string,
  method: "POST" | "PATCH" | "DELETE",
  body?: unknown,
  token?: string
): Promise<{ success: boolean; data: unknown; error: string | null }> {
  const doFetch = (t?: string) => fetch(`${API}${endpoint}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(t ? { Authorization: `Bearer ${t}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  let res = await doFetch(token);
  if (res.status === 401) {
    const newToken = await refreshedAuthToken();
    if (newToken && newToken !== token) res = await doFetch(newToken);
  }
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
  const doFetch = (t?: string) => fetch(`${API}${endpoint}`, {
    method: "GET",
    headers: {
      "Content-Type": "application/json",
      ...(t ? { Authorization: `Bearer ${t}` } : {}),
    },
  });
  let res = await doFetch(token);
  if (res.status === 401) {
    const newToken = await refreshedAuthToken();
    if (newToken && newToken !== token) res = await doFetch(newToken);
  }
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

type PurchaseTab = "bills" | "vendors" | "payments" | "debit-notes" | "credit-notes";
const TABS: { id: PurchaseTab; label: string }[] = [
  { id: "bills", label: "Purchase Bills" },
  { id: "vendors", label: "Vendors" },
  { id: "payments", label: "Payments" },
  { id: "debit-notes", label: "Debit Notes" },
  { id: "credit-notes", label: "Credit Notes" },
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
  const { clientId } = useClientNav();
  // ONE financial year for this page, owned by this page — see the Sales page
  // for the two-controls-disagreeing failure this replaces. The Bills tab's
  // period filter and the plain year pickers on the other tabs all write here,
  // so switching year on one tab carries to the next instead of resetting.
  const [financialYear, setFinancialYear] = useState(getCurrentFinancialYear());
  const [tab, setTab] = useState<PurchaseTab>("bills");

  if (!clientId || clientId === "_placeholder") {
    return (
      <div className="px-6 py-4">
        <TableSkeleton cols={9} rows={4} />
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
        {tab === "bills" && <PurchaseBills clientId={clientId} financialYear={financialYear} onFinancialYearChange={setFinancialYear} />}
        {tab === "vendors" && <Vendors clientId={clientId} />}
        {tab === "payments" && <Payments clientId={clientId} financialYear={financialYear} onFinancialYearChange={setFinancialYear} />}
        {tab === "debit-notes" && <DebitNotes clientId={clientId} financialYear={financialYear} onFinancialYearChange={setFinancialYear} />}
        {tab === "credit-notes" && <PurchaseCreditNotes clientId={clientId} financialYear={financialYear} onFinancialYearChange={setFinancialYear} />}
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

// ── Purchase Bills ─────────────────────────────────────────────────────────

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
  document_url: string | null;
}

function PurchaseBills({ clientId, financialYear, onFinancialYearChange }: { clientId: string; financialYear: string; onFinancialYearChange: (fy: string) => void }) {
  const [bills, setBills] = useState<PurchaseBillRow[]>([]);
  const [vendors, setVendors] = useState<Vendor[]>([]);
  // Client's own Product/Service catalogue — only needed for the CSV import's
  // "resolve missing references" step (product_service column), same role
  // this plays on the Sales Invoices tab.
  const [services, setServices] = useState<ServiceCatalogueItem[]>([]);
  const [loading, setLoading] = useState(true);
  // Distinguishes "the bills fetch failed" from "this period genuinely has no
  // bills" (audit M17) — a failed load must show a retryable error, not the same
  // ₹0 summary + "No purchase bills" empty state as an actually-empty period.
  const [loadFailed, setLoadFailed] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [msg, setMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);
  const [receivingId, setReceivingId] = useState<string | null>(null);
  const router = useRouter();

  // One-shot success feedback after creating a bill on the dedicated create
  // page (mirrors the Sales Invoices tab's own ?flash= pattern) — read once
  // on mount, then strip the param so a refresh doesn't repeat the toast.
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    const flash = p.get("flash");
    if (flash) {
      setMsg({ type: "ok", text: flash });
      p.delete("flash");
      const qs = p.toString();
      window.history.replaceState(null, "", qs ? `${window.location.pathname}?${qs}` : window.location.pathname);
    }
  }, []);

  // Date-window selector that SCOPES THE SERVER QUERY (which rows load) —
  // mirrors the Sales Invoices tab's own PeriodPicker.
  const [periodMode, setPeriodMode] = useState<PeriodMode>("this_fy");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const range = useMemo(
    () => resolvePeriodRange(periodMode, financialYear, { from: customFrom, to: customTo }),
    [periodMode, customFrom, customTo, financialYear],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setLoadFailed(false);
    const supabase = getSupabaseClient();
    const { start, end } = range;
    try {
      const [billsRes, vendorsRes, servicesRes] = await Promise.all([
        selectAll(() => supabase
          .from("purchase_bills")
          .select("*, vendors(name)")
          .eq("client_id", clientId)
          .is("deleted_at", null)
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
          .from("service_catalogue")
          .select("id, name, description, hsn_sac, gst_rate_bps, purchase_price_paise, unit, kind, is_active")
          .eq("client_id", clientId)
          .eq("is_active", true)
          .order("name")
          .order("id")),
      ]);
      setVendors((vendorsRes.data as Vendor[]) ?? []);
      setServices((servicesRes.data as ServiceCatalogueItem[]) ?? []);
      // M17: a failed bills fetch — a thrown network error OR a non-null
      // PostgREST error — must surface as retryable, not read as an empty
      // period; otherwise a real book renders as ₹0 payable + "No purchase bills".
      if (billsRes.error) throw billsRes.error;
      setBills((billsRes.data as PurchaseBillRow[]) ?? []);
    } catch {
      setBills([]);
      setLoadFailed(true);
    } finally {
      setLoading(false);
    }
  }, [clientId, range]);

  useEffect(() => { load(); }, [load]);

  async function handleReceive(billId: string) {
    if (receivingId) return; // already receiving one — avoid a double-submit race
    setReceivingId(billId);
    try {
      const token = await getAuthToken();
      // CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
      const result = await apiCall(`/api/purchase-bills/${billId}/receive`, "POST", undefined, token);
      if (!result.success) throw new Error(result.error ?? "Failed to receive purchase bill");
      setMsg({ type: "ok", text: "Purchase bill received" });
      load();
    } catch (err) {
      setMsg({ type: "err", text: err instanceof Error ? err.message : "Failed to receive purchase bill" });
    } finally {
      setReceivingId(null);
    }
  }

  // View drawer + row overflow menu (View details / Edit / Delete) — mirrors
  // the Sales Invoices tab's own menu pattern. Anchored to the viewport since
  // the table scrolls/clips an in-flow dropdown.
  const [detailId, setDetailId] = useState<string | null>(null);
  const [menu, setMenu] = useState<{ id: string; top: number; left: number } | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<PurchaseBillRow | PurchaseBillDetail | null>(null);
  function openMenuFor(e: React.MouseEvent, bill: PurchaseBillRow) {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setMenu({ id: bill.id, top: r.bottom + 4, left: Math.max(8, r.right - 176) });
  }

  async function deleteBill(bill: PurchaseBillRow | PurchaseBillDetail) {
    const token = await getAuthToken();
    const result = await apiCall(`/api/purchase-bills/${bill.id}`, "DELETE", undefined, token);
    if (!result.success) throw new Error(result.error ?? "Failed to delete purchase bill");
    setMsg({ type: "ok", text: `${bill.bill_no || "Purchase bill"} deleted` });
    setDeleteTarget(null);
    load();
  }

  // "Duplicate bill" — stash the full loaded detail and open New Bill, which
  // prefills from it (vendor, lines, RCM, notes; NOT the vendor invoice no.).
  // Same sessionStorage hand-off as Sales (lib/purchases/duplicateSeed).
  function duplicateBill(bill: PurchaseBillDetail) {
    writePurchaseBillDuplicateSeed(bill);
    setDetailId(null);
    router.push(`/clients/${clientId}/purchases/bills/new/edit`);
  }

  // Cancel a RECEIVED bill: reverses its posted journal and inventory stock-in
  // server-side (POST /cancel refuses drafts — those are deleted — and bills
  // with payments). Partner-only on the backend (accounting.approve).
  async function cancelBill(bill: PurchaseBillRow | PurchaseBillDetail) {
    const ok = await confirmDialog({
      title: `Cancel ${bill.bill_no || "this bill"}?`,
      message:
        "This reverses the bill's posted journal entry and returns its stock movements. " +
        "The bill stays on record as cancelled. This cannot be undone.",
      confirmLabel: "Cancel Bill",
      danger: true,
    });
    if (!ok) return;
    setDetailId(null);
    try {
      const token = await getAuthToken();
      const result = await apiCall(`/api/purchase-bills/${bill.id}/cancel`, "POST", undefined, token);
      if (!result.success) throw new Error(result.error ?? "Failed to cancel purchase bill");
      setMsg({ type: "ok", text: `${bill.bill_no || "Purchase bill"} cancelled — journal and stock reversed` });
      load();
    } catch (err) {
      setMsg({ type: "err", text: err instanceof Error ? err.message : "Failed to cancel purchase bill" });
    }
  }

  // The "Documents" bucket is private — document_url on the bill is a
  // storage path, not a browser-openable URL — so mint a fresh signed URL
  // on demand rather than trying to open it directly.
  async function viewAttachment(billId: string) {
    try {
      const token = await getAuthToken();
      const result = await apiGet(`/api/purchase-bills/${billId}/document-url`, token);
      const url = (result.data as { url?: string } | null)?.url;
      if (result.success && url) {
        window.open(url, "_blank", "noopener,noreferrer");
      } else {
        setMsg({ type: "err", text: result.error || "Unable to open the attached invoice." });
      }
    } catch {
      setMsg({ type: "err", text: "Unable to open the attached invoice." });
    }
  }

  // Bulk receive over the DataTable's selected rows. POST
  // /api/purchase-bills/{id}/receive is draft-only on the backend (each row's
  // journal-posting/FY-lock validation runs server-side) — loop per row, at
  // most 8 in flight at once (mapWithConcurrency) so a mid-batch failure on
  // one bill (e.g. FY-lock 409) is safe and can't corrupt the rest. Firing
  // ALL rows at once via Promise.all used to be the plumbing here — fine for
  // a handful of rows, but a few hundred simultaneous POSTs (each doing a
  // journal + inventory write server-side) reliably exhausts the browser's
  // connection pool and a chunk of them come back "Failed to fetch" that
  // never even reached the backend. Non-draft rows are skipped client-side
  // (mirrors the single-row "Receive" rowAction's status === "draft" gate)
  // rather than sent to the backend to 422. Refresh only if at least one bill
  // was received, and keep the selection (return false) if anything was
  // skipped or failed so the user can see what's left.
  const handleBulkReceive = useCallback(async (rows: PurchaseBillRow[]): Promise<boolean> => {
    const token = await getAuthToken();
    const draftRows = rows.filter((b) => b.status === "draft");
    const skipped = rows.length - draftRows.length;

    type ReceiveResult = { ok: true } | { ok: false; reason: string };
    const results: ReceiveResult[] = await mapWithConcurrency(draftRows, 8, async (b): Promise<ReceiveResult> => {
      try {
        // CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
        const result = await apiCall(`/api/purchase-bills/${b.id}/receive`, "POST", undefined, token);
        if (result.success) return { ok: true };
        return { ok: false, reason: result.error ?? "Failed to receive bill" };
      } catch (e) {
        return { ok: false, reason: e instanceof Error ? e.message : "Failed to receive bill" };
      }
    });

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

  // Bulk-delete over the DataTable's selected rows. DELETE /api/purchase-bills/{id}
  // is draft-only on the backend (received/partially-paid/paid/cancelled bills
  // are permanent records — soft-deleting one would strip its posted journal
  // from the books), so non-draft rows are skipped client-side (mirrors the
  // single-row "Delete draft" menu gate) rather than sent to 409. Loop per row,
  // at most 8 in flight at once (see handleBulkReceive above for why unbounded
  // Promise.all breaks down at large selection sizes); keep the selection
  // (return false) if anything was skipped or failed so the user can see
  // what's left. Parity with the Sales tab's bulk Delete/Void.
  const handleBulkDelete = useCallback(async (rows: PurchaseBillRow[]): Promise<boolean> => {
    const token = await getAuthToken();
    const draftRows = rows.filter((b) => b.status === "draft");
    const skipped = rows.length - draftRows.length;

    type DeleteResult = { ok: true } | { ok: false; reason: string };
    const results: DeleteResult[] = await mapWithConcurrency(draftRows, 8, async (b): Promise<DeleteResult> => {
      try {
        const result = await apiCall(`/api/purchase-bills/${b.id}`, "DELETE", undefined, token);
        if (result.success) return { ok: true };
        return { ok: false, reason: result.error ?? "Failed to delete bill" };
      } catch (e) {
        return { ok: false, reason: e instanceof Error ? e.message : "Failed to delete bill" };
      }
    });

    const deleted = results.filter((r) => r.ok).length;
    const failures = results.filter((r): r is { ok: false; reason: string } => !r.ok);
    const failed = failures.length;

    if (deleted > 0) load();

    const parts: string[] = [];
    if (deleted > 0) parts.push(`${deleted} deleted`);
    if (skipped > 0) parts.push(`${skipped} skipped (only drafts can be deleted)`);
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

  // Bulk-cancel over the DataTable's selected rows. POST /api/purchase-bills/
  // {id}/cancel is received-only on the backend (drafts are deleted, not
  // cancelled; bills with payments/debit/credit notes refuse) and reverses
  // the bill's posted journal + inventory stock-in — the only correct way to
  // undo a received bill, so this deliberately calls the SAME real endpoint
  // the single-row "Cancel" action uses rather than any local shortcut. Loop
  // per row, at most 8 in flight at once (see handleBulkReceive above for
  // why unbounded Promise.all breaks down at large selection sizes);
  // non-received rows are skipped client-side rather than sent to 422; keep
  // the selection (return false) if anything was skipped or failed.
  const handleBulkCancel = useCallback(async (rows: PurchaseBillRow[]): Promise<boolean> => {
    const token = await getAuthToken();
    const receivedRows = rows.filter((b) => b.status === "received");
    const skipped = rows.length - receivedRows.length;

    type CancelResult = { ok: true } | { ok: false; reason: string };
    const results: CancelResult[] = await mapWithConcurrency(receivedRows, 8, async (b): Promise<CancelResult> => {
      try {
        const result = await apiCall(`/api/purchase-bills/${b.id}/cancel`, "POST", undefined, token);
        if (result.success) return { ok: true };
        return { ok: false, reason: result.error ?? "Failed to cancel bill" };
      } catch (e) {
        return { ok: false, reason: e instanceof Error ? e.message : "Failed to cancel bill" };
      }
    });

    const cancelled = results.filter((r) => r.ok).length;
    const failures = results.filter((r): r is { ok: false; reason: string } => !r.ok);
    const failed = failures.length;

    if (cancelled > 0) load();

    const parts: string[] = [];
    if (cancelled > 0) parts.push(`${cancelled} cancelled`);
    if (skipped > 0) parts.push(`${skipped} skipped (not received)`);
    if (failed > 0) {
      const reasons = Array.from(new Set(failures.map((f) => f.reason)));
      parts.push(`${failed} failed (${reasons.join("; ")})`);
    }
    const text = parts.length > 0 ? `${parts.join(", ")}.` : "No received bills selected.";

    if (skipped > 0 || failed > 0) {
      setMsg({ type: "err", text });
      return false;
    }
    setMsg({ type: "ok", text });
    return true;
  }, [load]);

  /**
   * Bulk-import handler. Maps flat rows → grouped bills via buildPurchaseBills, then
   * creates them all in ONE request via /api/purchase-bills/bulk (same
   * _create_purchase_bill_core logic the manual form's single-create endpoint uses —
   * no parallel logic, just no per-row network round-trip). Bills land as drafts.
   * Vendors must already exist (referenced by name).
   */
  async function handleImport(rows: ImportRow[]): Promise<{ imported: number; errors: string[]; skipped?: number; skippedDetail?: string[] }> {
    const vendorRefs: NameRef[] = vendors.map((v) => ({ id: v.id, name: v.name }));
    const serviceRefs: PurchaseServiceRef[] = services.map((s) => ({
      id: s.id, name: s.name, description: s.description, hsn_sac: s.hsn_sac,
      gst_rate_bps: s.gst_rate_bps, purchase_price_paise: s.purchase_price_paise, unit: s.unit,
    }));
    const { bills: built, errors } = buildPurchaseBills(rows, clientId, vendorRefs, serviceRefs);
    if (built.length === 0) return { imported: 0, errors };
    const token = await getAuthToken();

    const payloads = built.map(({ ref, ...payload }) => { void ref; return payload; }); // drop the internal grouping key
    let imported = 0;
    const skippedDetail: string[] = [];
    const result = await apiCall("/api/purchase-bills/bulk", "POST", { bills: payloads }, token);
    if (result.success) {
      const data = result.data as {
        created: { lines?: unknown[] }[];
        errors: { index: number; bill_no?: string; error: string }[];
        skipped?: { index: number; bill_no?: string; reason: string }[];
      };
      for (const bill of data.created) {
        imported += Array.isArray(bill.lines) ? bill.lines.length : 0;
      }
      for (const e of data.errors) {
        const label = e.bill_no || built[e.index]?.ref || "?";
        errors.push(`Bill "${label}": ${e.error}`);
      }
      // Bills already present (same vendor + bill number) — the backend's
      // duplicate guard, not a failure: re-uploading the same file (or a
      // retry after a dropped connection) must not double every bill.
      for (const s of data.skipped ?? []) {
        const label = s.bill_no || built[s.index]?.ref || "?";
        skippedDetail.push(`Bill "${label}": ${s.reason}`);
      }
    } else {
      errors.push(result.error ?? "Bulk import failed");
    }
    if (imported > 0) load();
    return { imported, errors, skipped: skippedDetail.length, skippedDetail };
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
        <span className="text-[#475569] inline-flex items-center gap-1">
          {b.bill_no ?? "—"}
          {b.is_ai_extracted && <span className="text-[9px] bg-amber-100 text-amber-600 px-1 rounded">AI</span>}
          {b.document_url && (
            <button
              onClick={(e) => { e.stopPropagation(); viewAttachment(b.id); }}
              title="View attached invoice"
              aria-label="View attached invoice"
              className="text-[#94A3B8] hover:text-blue-600"
            >
              <Paperclip size={11} />
            </button>
          )}
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
    {
      id: "delete",
      label: "Delete draft(s)",
      icon: <Trash2 size={12} />,
      variant: "danger",
      confirm: "Delete the selected draft purchase bills? Only drafts are removed — received and later bills are protected.",
      run: handleBulkDelete,
    },
    {
      id: "cancel",
      label: "Cancel received",
      icon: <AlertTriangle size={12} />,
      variant: "danger",
      confirm: "Cancel the selected received purchase bills? This reverses each bill's posted journal entry and inventory stock-in. The bills stay on record as cancelled. This cannot be undone.",
      run: handleBulkCancel,
    },
    exportSelectedAction("purchase-bills-selected.csv", billColumns),
  ], [handleBulkReceive, handleBulkDelete, handleBulkCancel, billColumns]);

  // "Resolve missing references" step for the product_service import column —
  // mirrors the Sales Invoices tab's own importResolvers exactly. Reads
  // `services` fresh (not captured once), so a product created inline here
  // immediately drops out of the "missing" list — see ReferenceResolver's contract.
  const importResolvers: ReferenceResolver[] = [
    {
      column: "product_service",
      label: "Products & Services",
      isKnown: (name) => services.some((s) => s.name.trim().toLowerCase() === name.trim().toLowerCase()),
      renderCreate: (name, onDone) => (
        <ProductServiceFormModal
          clientId={clientId}
          existing={null}
          seedName={name}
          onClose={onDone}
          onSaved={(item) => { setServices((prev) => [...prev, item]); onDone(); }}
          onError={(text) => setMsg({ type: "err", text })}
        />
      ),
    },
  ];

  return (
    <div className="space-y-4 max-w-screen-2xl mx-auto">
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
          <p className="text-lg font-bold text-orange-700 tabular-nums">{loadFailed ? "—" : fmt(totalPayable)}</p>
        </div>
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <p className="text-[10px] text-[#64748B] mb-1">Total Bills (Selected Period)</p>
          <p className="text-lg font-bold text-[#1E293B] tabular-nums">{loadFailed ? "—" : fmt(totalThisFy)}</p>
        </div>
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <p className="text-[10px] text-[#64748B] mb-1">Bills in Selected Period</p>
          <p className="text-lg font-bold text-[#1E293B] tabular-nums">{loadFailed ? "—" : bills.length}</p>
        </div>
      </div>

      <div className="flex justify-between items-center">
        <p className="text-xs font-semibold text-[#334155]">Purchase Bills — {periodOptionLabel(periodMode, financialYear)}</p>
      </div>

      {showImport && (
        <CsvImportModal
          title="Import Purchase Bills"
          columns={PURCHASE_BILL_IMPORT_COLUMNS}
          templateFilename="purchase-bills-template.csv"
          onImport={handleImport}
          onClose={() => setShowImport(false)}
          resolvers={importResolvers}
        />
      )}

      {/* Bills table — shared DataTable (search, sort, filters, pagination, export, prefs) */}
      <DataTable
        data={bills}
        columns={billColumns}
        filters={billFilters}
        getRowId={(b) => b.id}
        loading={loading}
        error={loadFailed ? "Couldn't load purchase bills — the request failed or timed out." : null}
        onRetry={load}
        onRefresh={load}
        searchPlaceholder="Search by our ref, vendor invoice, or vendor…"
        initialSort={{ key: "bill_date", dir: "desc" }}
        exportFilename="purchase-bills"
        persistKey="purchases.bills"
        emptyTitle="No purchase bills"
        emptyDescription={`No purchase bills for ${periodOptionLabel(periodMode, financialYear)}.`}
        toolbarExtra={
          <>
            <PeriodPicker
              mode={periodMode}
              onModeChange={setPeriodMode}
              financialYear={financialYear}
              onFinancialYearChange={onFinancialYearChange}
              customFrom={customFrom}
              customTo={customTo}
              onCustomFromChange={setCustomFrom}
              onCustomToChange={setCustomTo}
              ariaLabel="Date range"
            />
            <button
              onClick={() => setShowImport(true)}
              className="flex items-center gap-1.5 text-xs border border-[#E2E8F0] text-[#475569] px-3 py-1.5 rounded-lg hover:bg-[#F8FAFC]"
            >
              <Upload size={12} /> Import
            </button>
            <button
              onClick={() => router.push(`/clients/${clientId}/purchases/bills/new/edit`)}
              className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700"
            >
              <Plus size={12} /> New Bill
            </button>
          </>
        }
        bulkActions={bulkActions}
        rowActions={(b) => (
          <div className="flex items-center justify-end gap-2">
            {b.status === "draft" && (
              <button onClick={() => handleReceive(b.id)} disabled={receivingId === b.id}
                className="text-xs text-blue-600 hover:underline flex items-center gap-1 disabled:opacity-50 disabled:no-underline">
                <CheckCircle size={11} /> {receivingId === b.id ? "Receiving…" : "Receive"}
              </button>
            )}
            <button
              onClick={(e) => openMenuFor(e, b)}
              aria-label={`Actions for bill ${b.bill_no || b.id}`}
              className="p-1 rounded hover:bg-[#F1F5F9] text-[#64748B]"
            >
              <MoreHorizontal size={16} />
            </button>
          </div>
        )}
      />

      {/* Row overflow menu — View details always; Edit for any non-cancelled
          bill (draft gets the full editor, received/partially-paid/paid
          gets the same editor scoped to its soft fields — see
          PurchaseBillEditor's isLocked handling); Delete for drafts only. */}
      {menu && (() => {
        const b = bills.find((x) => x.id === menu.id);
        if (!b) return null;
        return (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setMenu(null)} />
            <div
              className="fixed z-50 w-44 bg-white rounded-lg border border-[#E2E8F0] shadow-lg py-1 text-xs"
              style={{ top: menu.top, left: menu.left }}
            >
              <button onClick={() => { setMenu(null); setDetailId(b.id); }}
                className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F8FAFC] text-[#334155]">
                View details
              </button>
              {b.status !== "cancelled" && (
                <button onClick={() => { setMenu(null); router.push(`/clients/${clientId}/purchases/bills/${b.id}/edit`); }}
                  className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F8FAFC] text-[#334155]">
                  {b.status === "draft" ? "Edit draft" : "Edit"}
                </button>
              )}
              {b.status === "draft" && (
                <>
                  <div className="my-1 border-t border-[#F1F5F9]" />
                  <button onClick={() => { setMenu(null); setDeleteTarget(b); }}
                    className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-red-50 text-red-600">
                    Delete draft
                  </button>
                </>
              )}
              {b.status === "received" && (
                <>
                  <div className="my-1 border-t border-[#F1F5F9]" />
                  <button onClick={() => { setMenu(null); cancelBill(b); }}
                    className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-red-50 text-red-600">
                    Cancel bill
                  </button>
                </>
              )}
            </div>
          </>
        );
      })()}

      {detailId && (
        <PurchaseBillViewDrawer
          billId={detailId}
          clientId={clientId}
          vendorName={
            bills.find((b) => b.id === detailId)?.vendors?.name
            ?? vendors.find((v) => v.id === bills.find((b) => b.id === detailId)?.vendor_id)?.name
            ?? ""
          }
          onClose={() => setDetailId(null)}
          onEdit={(id) => router.push(`/clients/${clientId}/purchases/bills/${id}/edit`)}
          onReceive={(id) => { setDetailId(null); handleReceive(id); }}
          onDelete={(bill) => { setDetailId(null); setDeleteTarget(bill); }}
          onDuplicate={duplicateBill}
          onCancelBill={cancelBill}
          onChanged={load}
          onToast={(text, type) => setMsg({ type: type === "success" ? "ok" : "err", text })}
        />
      )}

      {deleteTarget && (
        <DeleteBillModal
          bill={deleteTarget}
          onConfirm={() => deleteBill(deleteTarget)}
          onClose={() => setDeleteTarget(null)}
        />
      )}
    </div>
  );
}

function DeleteBillModal({
  bill,
  onConfirm,
  onClose,
}: {
  bill: PurchaseBillRow | PurchaseBillDetail;
  onConfirm: () => Promise<void>;
  onClose: () => void;
}) {
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handle() {
    setDeleting(true); setError(null);
    try {
      await onConfirm();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete purchase bill");
    } finally {
      // The success path never lowered it, which only worked because
      // onConfirm() closes this dialog. If it ever stops doing that, Delete
      // stays disabled with no way to tell why.
      setDeleting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/30 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl border border-[#E2E8F0] p-6 w-full max-w-md shadow-xl">
        <div className="flex items-start gap-3 mb-4">
          <div className="p-2 rounded-full bg-red-50 text-red-600 flex-shrink-0"><AlertTriangle size={16} /></div>
          <div>
            <h3 className="text-sm font-semibold text-[#0F172A]">Delete draft purchase bill?</h3>
            <p className="text-xs text-[#64748B] mt-1">
              <span className="font-mono">{bill.bill_no || "This bill"}</span> will be removed from your purchase
              bill list. Only drafts can be deleted — received, partially-paid, paid and cancelled bills are
              permanent records and are protected.
            </p>
          </div>
        </div>
        {error && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2 mb-3">{error}</p>}
        <div className="flex gap-3 justify-end">
          <button onClick={onClose} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Cancel</button>
          <button
            onClick={handle}
            disabled={deleting}
            className="text-xs px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 flex items-center gap-1.5"
          >
            {deleting ? "Deleting…" : <><Trash2 size={12} /> Delete Draft</>}
          </button>
        </div>
      </div>
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
  // null is "nobody has established it" — see the form's own note. It is not
  // a synonym for resident, even though deductions default to 26Q.
  residential_status: "resident" | "non_resident" | null;
  country_of_residence: string | null;
  opening_balance_paise: number;
  is_active: boolean;
}

const GSTIN_RE = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/;

interface VendorDependencies {
  can_delete: boolean;
  dependencies: Record<string, number>;
  total: number;
}

function Vendors({ clientId }: { clientId: string }) {
  const [vendors, setVendors] = useState<VendorRow[]>([]);
  const [loading, setLoading] = useState(true);
  // See PurchaseBills.loadFailed (audit M17): a failed fetch must not render as
  // "no vendors yet", which on this tab reads as an invitation to re-create
  // vendors that already exist.
  const [loadFailed, setLoadFailed] = useState(false);
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
  // "" is a real third value — nobody has established this vendor's residence.
  // It is not the same as "resident", and the backend reports it as a gap
  // rather than pretending the question was answered.
  const [residentialStatus, setResidentialStatus] = useState<"" | "resident" | "non_resident">("");
  const [countryOfResidence, setCountryOfResidence] = useState("");
  const [taxIdentificationNumber, setTaxIdentificationNumber] = useState("");

  // Deactivate/Delete parity with the Customers tab (sales/page.tsx) — see
  // its own comments for the full rationale (deactivate is unconditionally
  // safe and reversible; permanent delete is backend-gated on zero linked
  // accounting records).
  const [deactivateTarget, setDeactivateTarget] = useState<VendorRow | null>(null);
  const [deactivating, setDeactivating] = useState(false);
  const [menu, setMenu] = useState<{ id: string; top: number; left: number } | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<VendorRow | null>(null);
  const [deleteDeps, setDeleteDeps] = useState<VendorDependencies | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const supabase = getSupabaseClient();
    try {
      // Fetch active AND inactive vendors — active/inactive scoping is a
      // client-side DataTable filter (mirrors Customers) so a deactivated
      // vendor stays visible (and reactivatable) instead of vanishing.
      const { data, error } = await selectAll(() => supabase
        .from("vendors")
        .select("*")
        .eq("client_id", clientId)
        .order("name")
        .order("id"));
      if (error) throw error;
      setVendors((data as VendorRow[]) ?? []);
      setLoadFailed(false);
    } catch {
      // Was swallowed entirely: a failed fetch rendered as "no vendors yet",
      // which on this tab is an invitation to re-create vendors that exist.
      setVendors([]);
      setLoadFailed(true);
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  /** Bulk-import vendors through /api/vendors/bulk — one request for the whole
   *  file instead of one POST per row. Duplicates (GSTIN/PAN already on file
   *  for this client) are the backend's own guard doing its job, not a
   *  failure — reported as skipped, mirroring how the Customers importer
   *  (sales/page.tsx) surfaces its identical duplicate shape. */
  async function handleImport(rows: ImportRow[]): Promise<{ imported: number; errors: string[]; skipped?: number; skippedDetail?: string[] }> {
    const { records, errors } = buildVendors(rows, clientId);
    if (records.length === 0) return { imported: 0, errors };
    const token = await getAuthToken();

    let imported = 0;
    const skippedDetail: string[] = [];
    const result = await apiCall("/api/vendors/bulk", "POST", { vendors: records }, token);
    if (result.success) {
      const data = result.data as {
        created: unknown[];
        duplicates: { name?: string; existing_id?: string }[];
        errors: { name?: string; error: string }[];
      };
      imported = data.created.length;
      for (const d of data.duplicates) skippedDetail.push(`"${d.name ?? "?"}" already exists — skipped`);
      for (const e of data.errors) errors.push(`Vendor "${e.name ?? "?"}": ${e.error}`);
    } else {
      errors.push(result.error ?? "Bulk import failed");
    }
    if (imported > 0) load();
    return { imported, errors, skipped: skippedDetail.length, skippedDetail };
  }

  async function handleSave() {
    if (!name.trim()) { setMsg({ type: "err", text: "Name is required" }); return; }
    if (gstin && !GSTIN_RE.test(gstin.trim().toUpperCase())) { setMsg({ type: "err", text: "Invalid GSTIN format (15 chars: 2-digit state + PAN + entity + Z + check)" }); return; }
    // Read exactly before anything is saved. The old form was
    // Math.round(parseFloat(x) * 100), which reads "1,25,000" as 1 and a blank
    // field as NaN — JSON.stringify sends that as null, so an opening balance
    // could reach the API as no value at all.
    const opening = paiseFromRupeeInput(openingBalance || "0");
    if (opening === null) {
      setMsg({ type: "err", text: "Opening balance must be an amount in rupees, "
                                  + "e.g. 125000 or 125000.50 — without commas." });
      return;
    }
    if (tdsApplicable && bpsFromPercentInput(tdsRate) === null) {
      setMsg({ type: "err", text: "TDS rate must be a percentage, e.g. 10 or 7.5." });
      return;
    }
    setSaving(true);
    setMsg(null);
    try {
      const token = await getAuthToken();
      const cleanGstin = gstin.trim().toUpperCase() || undefined;
      const stateCode = cleanGstin ? cleanGstin.slice(0, 2) : undefined;
      const rateBps = tdsApplicable ? bpsFromPercentInput(tdsRate) : 0;

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
          residential_status: residentialStatus || undefined,
          // Only meaningful for a non-resident; 26Q has no field for either.
          country_of_residence:
            residentialStatus === "non_resident" ? countryOfResidence.trim().toUpperCase() || undefined : undefined,
          tax_identification_number:
            residentialStatus === "non_resident" ? taxIdentificationNumber.trim() || undefined : undefined,
          tds_rate_bps: rateBps,
          opening_balance_paise: opening,
        },
        token
      );
      if (!result.success) throw new Error(result.error ?? "Failed to add vendor");
      setMsg({ type: "ok", text: "Vendor added." });
      setShowForm(false);
      setName(""); setGstin(""); setPan(""); setEmail(""); setPhone("");
      setTdsApplicable(false); setTdsSection("194C"); setTdsRate("2"); setOpeningBalance("");
      setResidentialStatus(""); setCountryOfResidence(""); setTaxIdentificationNumber("");
      load();
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Save failed" });
    } finally {
      setSaving(false);
    }
  }

  // Deactivation is unconditionally safe (existing bills/payments/journal
  // entries are never touched) so it only needs a confirmation modal, not a
  // dependency check — mirrors Customers' confirmDeactivate exactly, but
  // routed through the real API (not a direct Supabase write) so it leaves
  // an audit trail.
  async function confirmDeactivate() {
    if (!deactivateTarget) return;
    setDeactivating(true);
    const token = await getAuthToken();
    const result = await apiCall(`/api/vendors/${deactivateTarget.id}`, "DELETE", undefined, token);
    setDeactivating(false);
    if (!result.success) {
      setMsg({ type: "err", text: result.error ?? "Failed to deactivate vendor" });
      setDeactivateTarget(null);
      return;
    }
    setMsg({ type: "ok", text: "Vendor deactivated." });
    setDeactivateTarget(null);
    load();
  }

  async function reactivateVendor(v: VendorRow) {
    const token = await getAuthToken();
    const result = await apiCall(`/api/vendors/${v.id}`, "PATCH", { is_active: true }, token);
    if (!result.success) { setMsg({ type: "err", text: result.error ?? "Failed to reactivate vendor" }); return; }
    setMsg({ type: "ok", text: "Vendor reactivated." });
    load();
  }

  // Open the permanent-delete flow: ask the backend which accounting records (if
  // any) reference this vendor, then show either the blocked or confirm dialog.
  async function startDelete(v: VendorRow) {
    setDeleteTarget(v);
    setDeleteDeps(null);
    const token = await getAuthToken();
    const res = await apiGet(`/api/vendors/${v.id}/dependencies`, token);
    if (res.success) setDeleteDeps(res.data as VendorDependencies);
    else { setMsg({ type: "err", text: "Could not check vendor dependencies" }); setDeleteTarget(null); }
  }

  // Permanent delete — only reachable when the dependency check returned clean.
  // The backend re-checks and refuses (409) if anything was created meanwhile.
  async function confirmDelete() {
    if (!deleteTarget) return;
    setDeleteBusy(true);
    try {
      const token = await getAuthToken();
      const res = await apiCall(`/api/vendors/${deleteTarget.id}?permanent=true`, "DELETE", undefined, token);
      if (!res.success) {
        setMsg({ type: "err", text: res.error ?? "Failed to delete vendor" });
        return;
      }
      setMsg({ type: "ok", text: "Vendor deleted." });
      setDeleteTarget(null);
      setDeleteDeps(null);
      load();
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Failed to delete vendor" });
    } finally {
      setDeleteBusy(false);
    }
  }

  // Anchor the overflow menu to the viewport (the table scrolls/clips, so an
  // in-flow dropdown would be cut off). Right-align a 176px menu under the button.
  function openMenuFor(e: React.MouseEvent, v: VendorRow) {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setMenu({ id: v.id, top: r.bottom + 4, left: Math.max(8, r.right - 176) });
  }

  const bulkDeactivateVendors = useCallback(async (rows: VendorRow[]): Promise<boolean> => {
    const token = await getAuthToken();
    const targets = rows.filter((v) => v.is_active);
    let deactivated = 0;
    const failures: string[] = [];
    await Promise.all(targets.map(async (v) => {
      try {
        const result = await apiCall(`/api/vendors/${v.id}`, "DELETE", undefined, token);
        if (!result.success) throw new Error(result.error ?? "failed");
        deactivated++;
      } catch (e) {
        failures.push(`${v.name}: ${e instanceof Error ? e.message : "failed"}`);
      }
    }));
    const skipped = rows.length - targets.length;
    const parts: string[] = [];
    if (deactivated) parts.push(`${deactivated} deactivated`);
    if (skipped) parts.push(`${skipped} already inactive`);
    if (failures.length) parts.push(`${failures.length} failed (${failures.slice(0, 3).join("; ")}${failures.length > 3 ? "…" : ""})`);
    setMsg({ type: failures.length ? "err" : "ok", text: parts.join(", ") || "Nothing to do" });
    if (deactivated) load();
    return failures.length === 0;
  }, [load]);

  // No pre-check GET here — the backend re-validates dependencies on every
  // call and returns 409 for any vendor with linked accounting records, so a
  // blocked row is just reported as a failure rather than fetched twice.
  const bulkDeletePermanentVendors = useCallback(async (rows: VendorRow[]): Promise<boolean> => {
    const token = await getAuthToken();
    let deleted = 0;
    const failures: string[] = [];
    await Promise.all(rows.map(async (v) => {
      try {
        const result = await apiCall(`/api/vendors/${v.id}?permanent=true`, "DELETE", undefined, token);
        if (!result.success) throw new Error(result.error ?? "failed");
        deleted++;
      } catch (e) {
        failures.push(`${v.name}: ${e instanceof Error ? e.message : "failed"}`);
      }
    }));
    const text = failures.length
      ? `${deleted} deleted, ${failures.length} failed (${failures.slice(0, 3).join("; ")}${failures.length > 3 ? "…" : ""})`
      : `${deleted} vendor${deleted !== 1 ? "s" : ""} deleted`;
    setMsg({ type: failures.length ? "err" : "ok", text });
    if (deleted) load();
    return failures.length === 0;
  }, [load]);

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
    // Shown because an unclassified vendor is filed on an ASSUMPTION — 26Q,
    // because that is right for a domestic vendor — and a CA should be able to
    // see which ones those are without opening each record.
    { key: "residential_status", header: "Residence", accessor: (v) => v.residential_status ?? "",
      render: (v) =>
        v.residential_status === "non_resident"
          ? <span className="px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-amber-100 text-amber-700">
              Non-resident{v.country_of_residence ? ` · ${v.country_of_residence}` : ""}
            </span>
          : v.residential_status === "resident"
            ? <span className="text-[#64748B]">Resident</span>
            : <span className="text-[#94A3B8]" title="Not established — deductions are reported on 26Q as assumed resident">Not set</span> },
    { key: "tds_rate", header: "Rate", accessor: (v) => v.tds_rate_bps, sortable: true, align: "right",
      render: (v) => <span className="text-[#475569]">{v.tds_rate_bps > 0 ? `${(v.tds_rate_bps / 100).toFixed(1)}%` : "—"}</span> },
    { key: "opening_balance", header: "Opening Bal", accessor: (v) => v.opening_balance_paise, sortable: true, align: "right",
      render: (v) => <span className="font-mono text-[#334155]">{v.opening_balance_paise > 0 ? fmt(v.opening_balance_paise) : "—"}</span> },
    { key: "email", header: "Email", accessor: (v) => v.email ?? "", searchable: true, defaultHidden: true,
      render: (v) => <span className="text-[#64748B]">{v.email ?? "—"}</span> },
    { key: "phone", header: "Phone", accessor: (v) => v.phone ?? "", searchable: true, defaultHidden: true,
      render: (v) => <span className="text-[#64748B]">{v.phone ?? "—"}</span> },
    { key: "is_active", header: "Status", accessor: (v) => (v.is_active ? "active" : "inactive"),
      render: (v) => v.is_active ? (
        <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-green-100 text-green-700">Active</span>
      ) : (
        <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-[#F1F5F9] text-[#64748B]">Inactive</span>
      ) },
  ], []);

  const vendorFilters: FilterDef<VendorRow>[] = useMemo(() => [
    { key: "tds_applicable", label: "TDS", type: "boolean", accessor: (v) => v.tds_applicable, trueLabel: "Applicable", falseLabel: "Not applicable" },
    { key: "residential_status", label: "Residence", type: "select",
      accessor: (v) => v.residential_status ?? "unset", options: [
        { value: "resident", label: "Resident" },
        { value: "non_resident", label: "Non-resident" },
        { value: "unset", label: "Not established" },
      ] },
    { key: "is_active", label: "Status", type: "select", accessor: (v) => (v.is_active ? "active" : "inactive"), options: [
      { value: "active", label: "Active" },
      { value: "inactive", label: "Inactive" },
    ] },
  ], []);

  const vendorBulkActions: BulkAction<VendorRow>[] = useMemo(() => [
    {
      id: "deactivate",
      label: "Deactivate",
      icon: <Ban size={12} />,
      confirm: "Deactivate the selected vendors? They will no longer be available for new bills. Existing records are unaffected and this can be undone.",
      run: bulkDeactivateVendors,
    },
    {
      id: "delete-permanent",
      label: "Delete permanently",
      icon: <Trash2 size={12} />,
      variant: "danger",
      confirm: "Permanently delete the selected vendors? Any vendor with linked bills, payments, debit notes, credit notes or an opening balance will be skipped. This cannot be undone.",
      run: bulkDeletePermanentVendors,
    },
    exportSelectedAction("vendors-selected.csv", vendorColumns),
  ], [bulkDeactivateVendors, bulkDeletePermanentVendors, vendorColumns]);

  return (
    <div className="space-y-4 max-w-screen-2xl mx-auto">
      {msg && (
        <div className={`flex items-center gap-2 px-4 py-3 rounded-lg text-sm ${msg.type === "ok" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-600"}`}>
          {msg.type === "ok" ? <CheckCircle size={14} /> : <AlertCircle size={14} />}
          {msg.text}
          <button onClick={() => setMsg(null)} className="ml-auto"><X size={13} /></button>
        </div>
      )}

      {deactivateTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0F172A]/60 p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md">
            <div className="px-6 py-5 border-b border-[#F1F5F9]">
              <h2 className="text-base font-semibold text-[#0F172A]">Deactivate Vendor?</h2>
            </div>
            <div className="px-6 py-5 space-y-2">
              <p className="text-sm text-[#475569]">
                <span className="font-medium text-[#1E293B]">{deactivateTarget.name}</span> will no
                longer be available for new bills.
              </p>
              <p className="text-sm text-[#475569]">
                Existing bills and accounting records will remain unchanged. You can reactivate
                this vendor later.
              </p>
            </div>
            <div className="px-6 py-4 border-t border-[#F1F5F9] flex justify-end gap-2">
              <button
                onClick={() => setDeactivateTarget(null)}
                disabled={deactivating}
                className="px-4 py-2 text-sm text-[#475569] rounded-lg border border-[#E2E8F0] hover:bg-[#F8FAFC] disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={confirmDeactivate}
                disabled={deactivating}
                className="px-4 py-2 text-sm font-medium text-white rounded-lg bg-red-600 hover:bg-red-700 disabled:opacity-50"
              >
                {deactivating ? "Deactivating…" : "Deactivate"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Permanent-delete flow: checking → blocked (has records) → confirm (clean) */}
      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0F172A]/60 p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md">
            {deleteDeps === null ? (
              <div className="px-6 py-10 flex items-center justify-center gap-2 text-sm text-[#475569]">
                <Loader2 size={16} className="animate-spin" /> Checking for linked records…
              </div>
            ) : deleteDeps.can_delete ? (
              <>
                <div className="px-6 py-5 border-b border-[#F1F5F9]">
                  <h2 className="text-base font-semibold text-[#0F172A]">Delete Vendor?</h2>
                </div>
                <div className="px-6 py-5 space-y-2">
                  <p className="text-sm text-[#475569]">
                    <span className="font-medium text-[#1E293B]">{deleteTarget.name}</span> has no
                    linked bills, payments, debit notes, credit notes or opening balance.
                  </p>
                  <p className="text-sm text-[#475569]">
                    This permanently removes the vendor and cannot be undone.
                  </p>
                </div>
                <div className="px-6 py-4 border-t border-[#F1F5F9] flex justify-end gap-2">
                  <button
                    onClick={() => { setDeleteTarget(null); setDeleteDeps(null); }}
                    disabled={deleteBusy}
                    className="px-4 py-2 text-sm text-[#475569] rounded-lg border border-[#E2E8F0] hover:bg-[#F8FAFC] disabled:opacity-50"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={confirmDelete}
                    disabled={deleteBusy}
                    className="px-4 py-2 text-sm font-medium text-white rounded-lg bg-red-600 hover:bg-red-700 disabled:opacity-50"
                  >
                    {deleteBusy ? "Deleting…" : "Delete permanently"}
                  </button>
                </div>
              </>
            ) : (
              <>
                <div className="px-6 py-5 border-b border-[#F1F5F9] flex items-center gap-2">
                  <AlertTriangle size={18} className="text-amber-500" />
                  <h2 className="text-base font-semibold text-[#0F172A]">Can&apos;t delete this vendor</h2>
                </div>
                <div className="px-6 py-5 space-y-3">
                  <p className="text-sm text-[#475569]">
                    <span className="font-medium text-[#1E293B]">{deleteTarget.name}</span> has linked
                    accounting records, so it can&apos;t be permanently deleted:
                  </p>
                  <ul className="text-sm text-[#475569] space-y-1">
                    {([
                      ["bills", "Bills"],
                      ["payments", "Payments"],
                      ["debit_notes", "Debit notes"],
                      ["credit_notes", "Credit notes"],
                      ["opening_balance", "Opening balance"],
                    ] as const)
                      .filter(([k]) => (deleteDeps.dependencies?.[k] ?? 0) > 0)
                      .map(([k, label]) => (
                        <li key={k} className="flex items-center gap-2">
                          <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
                          {k === "opening_balance"
                            ? "Has an opening balance"
                            : `${label}: ${deleteDeps.dependencies[k]}`}
                        </li>
                      ))}
                  </ul>
                  <p className="text-sm text-[#475569]">
                    Deactivate the vendor instead — this keeps all history and removes it from new
                    bills.
                  </p>
                </div>
                <div className="px-6 py-4 border-t border-[#F1F5F9] flex justify-end gap-2">
                  <button
                    onClick={() => { setDeleteTarget(null); setDeleteDeps(null); }}
                    className="px-4 py-2 text-sm text-[#475569] rounded-lg border border-[#E2E8F0] hover:bg-[#F8FAFC]"
                  >
                    Close
                  </button>
                  {deleteTarget.is_active && (
                    <button
                      onClick={() => { const t = deleteTarget; setDeleteTarget(null); setDeleteDeps(null); setDeactivateTarget(t); }}
                      className="px-4 py-2 text-sm font-medium text-white rounded-lg bg-blue-600 hover:bg-blue-700"
                    >
                      Deactivate instead
                    </button>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* Row actions overflow menu (viewport-anchored to dodge table clipping) */}
      {menu && (() => {
        const v = vendors.find((x) => x.id === menu.id);
        if (!v) return null;
        return (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setMenu(null)} />
            <div
              className="fixed z-50 w-44 bg-white rounded-lg border border-[#E2E8F0] shadow-lg py-1 text-xs"
              style={{ top: menu.top, left: menu.left }}
            >
              {v.is_active ? (
                <button onClick={() => { setMenu(null); setDeactivateTarget(v); }}
                  className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F8FAFC] text-[#334155]">
                  <Ban size={13} /> Deactivate
                </button>
              ) : (
                <button onClick={() => { setMenu(null); reactivateVendor(v); }}
                  className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F8FAFC] text-green-700">
                  <RotateCcw size={13} /> Reactivate
                </button>
              )}
              <button onClick={() => { setMenu(null); startDelete(v); }}
                className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-red-50 text-red-600">
                <Trash2 size={13} /> Delete
              </button>
            </div>
          </>
        );
      })()}

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

          {/* Residential status — IT Act. Decides the charging section as well
              as the quarterly statement: s.194C and its neighbours charge only
              payments "to a resident", so a non-resident payee falls under
              s.195 and is reported on Form 27Q (Rule 31A(4)(b)) rather than
              26Q. The backend refuses to compute s.195, so setting this to
              non-resident with TDS on will be rejected with an explanation —
              that refusal is the point, not a gap in this form. */}
          <div className="bg-[#F8FAFC] border border-[#E2E8F0] rounded-lg p-3 space-y-2">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label htmlFor="residential-status" className="block text-xs font-medium text-[#475569] mb-1">Residential status (IT Act)</label>
                <select
                  id="residential-status"
                  value={residentialStatus}
                  onChange={(e) => setResidentialStatus(e.target.value as "" | "resident" | "non_resident")}
                  className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">Not established</option>
                  <option value="resident">Resident</option>
                  <option value="non_resident">Non-resident</option>
                </select>
              </div>
              {residentialStatus === "non_resident" && (
                <div>
                  <label htmlFor="country-of-residence" className="block text-xs font-medium text-[#475569] mb-1">Country (ISO code)</label>
                  <input
                    id="country-of-residence"
                    value={countryOfResidence}
                    onChange={(e) => setCountryOfResidence(e.target.value.toUpperCase())}
                    maxLength={2}
                    placeholder="AE"
                    className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              )}
            </div>
            {residentialStatus === "non_resident" && (
              <div>
                <label htmlFor="foreign-tin" className="block text-xs font-medium text-[#475569] mb-1">
                  Tax identification number {pan.trim() ? "(optional — PAN is on file)" : "(required on 27Q without a PAN)"}
                </label>
                <input
                  id="foreign-tin"
                  value={taxIdentificationNumber}
                  onChange={(e) => setTaxIdentificationNumber(e.target.value)}
                  placeholder="TIN in the country of residence"
                  className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            )}
            {residentialStatus === "" && (
              <p className="text-xs text-[#64748B]">
                Leave this unset if nobody has established it. Deductions are then reported on
                26Q and flagged as assumed resident, rather than silently filed as certain.
              </p>
            )}
            {residentialStatus === "non_resident" && (
              <p className="text-xs text-amber-700">
                Payments to a non-resident are deducted under IT Act §195 at the rates in force,
                which this software does not compute — determine the rate and complete
                Form 15CA/15CB under Rule 37BB before remitting.
              </p>
            )}
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
        error={loadFailed ? "Couldn't load vendors — the request failed or timed out." : null}
        onRefresh={load}
        searchPlaceholder="Search by name, GSTIN, email, or phone…"
        initialSort={{ key: "name", dir: "asc" }}
        initialFilters={{ is_active: "active" }}
        exportFilename="vendors"
        persistKey="purchases.vendors"
        emptyTitle="No vendors"
        emptyDescription="No vendors added yet."
        bulkActions={vendorBulkActions}
        rowActions={(v) => (
          <button
            onClick={(e) => openMenuFor(e, v)}
            aria-label={`Actions for ${v.name}`}
            className="p-1 rounded hover:bg-[#F1F5F9] text-[#64748B]"
          >
            <MoreHorizontal size={14} />
          </button>
        )}
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
  is_reversed?: boolean;
}

function Payments({ clientId, financialYear, onFinancialYearChange }: { clientId: string; financialYear: string; onFinancialYearChange: (fy: string) => void }) {
  const [payments, setPayments] = useState<PaymentRow[]>([]);
  const [vendors, setVendors] = useState<{ id: string; name: string }[]>([]);
  const [openBills, setOpenBills] = useState<{
    id: string; our_reference: string; bill_no: string | null; net_payable_paise: number;
    txn_currency?: string | null; exchange_rate?: string | null; txn_net_payable?: number | null;
  }[]>([]);
  const [loading, setLoading] = useState(true);
  // See PurchaseBills.loadFailed (audit M17): a failed payments fetch must show a
  // retryable error, not the same ₹0 "Total Paid (FY)" + "No payments" empty state.
  const [loadFailed, setLoadFailed] = useState(false);
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
      try {
        const token = await getAuthToken();
        const pol = await apiGet(`/api/currencies/policy?client_id=${clientId}`, token);
        if (cancelled) return;
        const active = Boolean(pol.success && (pol.data as { active?: boolean } | null)?.active);
        setMcActive(active);
        if (!active) return;
        // Direct Supabase, not /api/currencies — that endpoint is a plain
        // currencies-table select (domain/currency/currency_service.py:
        // list_currencies, no business logic); the policy check above is the
        // real server-side gate and stays backend-routed.
        const supabase = getSupabaseClient();
        const { data } = await supabase
          .from("currencies")
          .select("code, symbol, display_name, minor_unit, is_active")
          .eq("is_active", true)
          .order("code");
        if (!cancelled) setCurrencies((data as CurrencyOption[]) ?? []);
      } catch {
        // Best-effort: multi-currency is optional; on failure the form stays INR-only.
      }
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
    setLoadFailed(false);
    const supabase = getSupabaseClient();
    const { start, end } = fyRange(financialYear);
    try {
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
      setVendors(vendorRes.data ?? []);
      // M17: a failed payments fetch (thrown or non-null PostgREST error) must
      // surface as retryable, not read as an empty FY — otherwise real payments
      // render as ₹0 "Total Paid (FY)".
      if (pmtRes.error) throw pmtRes.error;
      setPayments((pmtRes.data as PaymentRow[]) ?? []);
    } catch {
      setPayments([]);
      setLoadFailed(true);
    } finally {
      setLoading(false);
    }
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
    const amtPaise = paiseFromRupeeInput(amount || "0");
    if (amtPaise === null) {
      setMsg({ type: "err", text: "Amount must be a number of rupees, e.g. 125000 or "
                                  + "125000.50 — without commas." });
      return;
    }
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

  /** Reverse a payment (task #102): rolls back its bill's outstanding and
   * reverses its posted journal server-side. Partner-only on the backend
   * (accounting.approve) — mirrors cancelBill's confirm/apiCall pattern. */
  async function reversePayment(p: PaymentRow) {
    const ok = await confirmDialog({
      title: `Reverse ${p.payment_no}?`,
      message:
        "This reverses the payment's posted journal entry and rolls back the linked bill's outstanding — " +
        "the bill becomes payable again. The payment stays on record as reversed. This cannot be undone.",
      confirmLabel: "Reverse Payment",
      danger: true,
    });
    if (!ok) return;
    try {
      const token = await getAuthToken();
      const result = await apiCall(`/api/purchase-payments/${p.id}/reverse`, "POST",
        { reversal_date: toDate() }, token);
      if (!result.success) throw new Error(result.error ?? "Failed to reverse payment");
      setMsg({ type: "ok", text: `${p.payment_no} reversed — journal and bill outstanding rolled back` });
      load();
    } catch (err) {
      setMsg({ type: "err", text: err instanceof Error ? err.message : "Failed to reverse payment" });
    }
  }

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
    { key: "is_reversed", header: "Status", accessor: (p) => (p.is_reversed ? "Reversed" : "Active"),
      render: (p) => p.is_reversed ? (
        <span className="px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-red-100 text-red-700">Reversed</span>
      ) : null },
  ], []);

  const paymentFilters: FilterDef<PaymentRow>[] = useMemo(() => [
    { key: "vendor", label: "Vendor", type: "select", accessor: (p) => p.vendors?.name ?? "",
      options: vendors.map((v) => ({ value: v.name, label: v.name })) },
    { key: "payment_mode", label: "Mode", type: "select", accessor: (p) => p.payment_mode,
      options: ["bank", "cash", "cheque", "upi", "neft", "rtgs"].map((m) => ({ value: m, label: m })) },
  ], [vendors]);

  return (
    <div className="space-y-4 max-w-screen-2xl mx-auto">
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
          <p className="text-lg font-bold text-green-700 tabular-nums">{loadFailed ? "—" : fmt(totalPaid)}</p>
        </div>
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <p className="text-[10px] text-[#64748B] mb-1">Transactions</p>
          <p className="text-lg font-bold text-[#1E293B] tabular-nums">{loadFailed ? "—" : payments.length}</p>
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
        error={loadFailed ? "Couldn't load payments — the request failed or timed out." : null}
        onRetry={load}
        onRefresh={load}
        searchPlaceholder="Search by payment no, vendor, mode, or reference…"
        initialSort={{ key: "payment_date", dir: "desc" }}
        exportFilename="purchase-payments"
        persistKey="purchases.payments"
        emptyTitle="No payments"
        emptyDescription={`No payments for FY ${financialYear}.`}
        toolbarExtra={
          <>
            <FinancialYearPicker value={financialYear} onChange={onFinancialYearChange} />
            <button onClick={() => setShowForm((s) => !s)} className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700"><Plus size={12} /> Record Payment</button>
          </>
        }
        rowActions={(p) => !p.is_reversed && (
          <button onClick={() => reversePayment(p)}
            className="text-[11px] text-red-600 hover:text-red-800 hover:underline">
            Reverse
          </button>
        )}
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

function DebitNotes({ clientId, financialYear, onFinancialYearChange }: { clientId: string; financialYear: string; onFinancialYearChange: (fy: string) => void }) {
  const router = useRouter();
  const [debitNotes, setDebitNotes] = useState<DebitNoteRow[]>([]);
  const [vendors, setVendors] = useState<Vendor[]>([]);
  // Client's own Product/Service catalogue + full (not FY-scoped) bill list,
  // needed only for the CSV import's product_service resolver and bill_no
  // linking/is_interstate derivation — same role as PurchaseBills' own fetch.
  const [services, setServices] = useState<ServiceCatalogueItem[]>([]);
  const [originalBills, setOriginalBills] = useState<OriginalDocRef[]>([]);
  const [showImport, setShowImport] = useState(false);
  const [loading, setLoading] = useState(true);
  // See PurchaseBills.loadFailed (audit M17): a failed fetch must show a retryable
  // error, not the "No debit notes" empty state that a genuinely empty FY shows.
  const [loadFailed, setLoadFailed] = useState(false);
  const [msg, setMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);
  const [issuingId, setIssuingId] = useState<string | null>(null);
  const [menu, setMenu] = useState<{ id: string; top: number; left: number } | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadFailed(false);
    const supabase = getSupabaseClient();
    const { start, end } = fyRange(financialYear);
    try {
      const [dnRes, vendorsRes, servicesRes, billsRes] = await Promise.all([
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
        selectAll(() => supabase
          .from("service_catalogue")
          .select("id, name, description, hsn_sac, gst_rate_bps, purchase_price_paise, unit, kind, is_active")
          .eq("client_id", clientId)
          .eq("is_active", true)
          .order("name")
          .order("id")),
        selectAll(() => supabase
          .from("purchase_bills")
          .select("id, bill_no, vendor_id, is_interstate")
          .eq("client_id", clientId)
          .order("bill_date", { ascending: false })
          .order("id")),
      ]);
      // M17: a failed debit-notes fetch (thrown or non-null PostgREST error) must
      // surface as retryable, not read as an empty FY (identical to having none).
      if (dnRes.error) throw dnRes.error;
      const vendorList = (vendorsRes.data as Vendor[]) ?? [];
      const vendorMap = new Map(vendorList.map((v) => [v.id, v.name]));
      const rows = ((dnRes.data as DebitNoteRow[]) ?? []).map((d) => ({
        ...d,
        vendor_name: vendorMap.get(d.vendor_id) ?? "—",
      }));
      setDebitNotes(rows);
      setVendors(vendorList);
      setServices((servicesRes.data as ServiceCatalogueItem[]) ?? []);
      setOriginalBills(
        ((billsRes.data ?? []) as Array<{ id: string; bill_no: string | null; vendor_id: string; is_interstate: boolean }>)
          .filter((r) => !!r.bill_no)
          .map((r) => ({ id: r.id, no: r.bill_no as string, partyId: r.vendor_id, isInterstate: r.is_interstate }))
      );
    } catch {
      setDebitNotes([]);
      setLoadFailed(true);
    } finally {
      setLoading(false);
    }
  }, [clientId, financialYear]);

  useEffect(() => { load(); }, [load]);

  /** Bulk-import handler for the CSV/XLSX modal. Maps flat rows → grouped
   * Purchase Debit Notes via buildPurchaseDebitNotes, then POSTs each note
   * once through the existing create endpoint (draft-only, same as a manually
   * created note). */
  async function handleImport(rows: ImportRow[]): Promise<{ imported: number; errors: string[] }> {
    const vendorRefs: NameRef[] = vendors.map((v) => ({ id: v.id, name: v.name }));
    const serviceRefs: PurchaseServiceRef[] = services.map((s) => ({
      id: s.id, name: s.name, description: s.description, hsn_sac: s.hsn_sac,
      gst_rate_bps: s.gst_rate_bps, purchase_price_paise: s.purchase_price_paise, unit: s.unit,
    }));
    const { notes, errors } = buildPurchaseDebitNotes(rows, clientId, vendorRefs, originalBills, serviceRefs);
    if (notes.length === 0) return { imported: 0, errors };
    const token = await getAuthToken();
    let imported = 0;
    for (const note of notes) {
      const result = await apiCall("/api/debit-notes/", "POST", note, token);
      if (result.success) imported += 1;
      else errors.push(result.error ?? "Bulk import failed");
    }
    if (imported > 0) load();
    return { imported, errors };
  }

  function openMenuFor(e: React.MouseEvent, dn: DebitNoteRow) {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setMenu({ id: dn.id, top: r.bottom + 4, left: Math.max(8, r.right - 176) });
  }

  async function issueDebitNote(id: string) {
    if (issuingId) return;
    setIssuingId(id);
    try {
      const token = await getAuthToken();
      const result = await apiCall(`/api/debit-notes/${id}/issue`, "POST", undefined, token);
      if (!result.success) throw new Error(result.error ?? "Failed to issue debit note");
      setMsg({ type: "ok", text: "Debit note issued." });
      load();
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Error issuing debit note" });
    } finally {
      setIssuingId(null);
    }
  }

  async function deleteDebitNote(dn: DebitNoteRow | DebitNoteDetail) {
    const ok = await confirmDialog({
      title: `Delete ${dn.debit_note_no || "this debit note"}?`,
      message: "This cannot be undone.",
      confirmLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    setDetailId(null);
    try {
      const token = await getAuthToken();
      const result = await apiCall(`/api/debit-notes/${dn.id}`, "DELETE", undefined, token);
      if (!result.success) throw new Error(result.error ?? "Failed to delete debit note");
      setMsg({ type: "ok", text: `${dn.debit_note_no || "Debit note"} deleted` });
      load();
    } catch (err) {
      setMsg({ type: "err", text: err instanceof Error ? err.message : "Failed to delete debit note" });
    }
  }

  // "Duplicate debit note" — stash the full loaded detail and open New Debit
  // Note, which prefills from it. Same sessionStorage hand-off as Purchase
  // Bills (lib/purchases/debitNoteDuplicateSeed).
  function duplicateDebitNote(dn: DebitNoteDetail) {
    writeDebitNoteDuplicateSeed(dn);
    setDetailId(null);
    router.push(`/clients/${clientId}/purchases/debit-notes/new/edit`);
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

  // Bulk issue over the DataTable's selected rows. POST /api/debit-notes/{id}/issue
  // is draft-only on the backend — loop per row, at most 8 in flight at once
  // (see handleBulkReceive on the Bills tab for why unbounded Promise.all
  // breaks down at large selection sizes); non-draft rows are skipped
  // client-side rather than sent to 422.
  const handleBulkIssue = useCallback(async (rows: DebitNoteRow[]): Promise<boolean> => {
    const token = await getAuthToken();
    const draftRows = rows.filter((d) => d.status === "draft");
    const skipped = rows.length - draftRows.length;

    type IssueResult = { ok: true } | { ok: false; reason: string };
    const results: IssueResult[] = await mapWithConcurrency(draftRows, 8, async (d): Promise<IssueResult> => {
      try {
        const result = await apiCall(`/api/debit-notes/${d.id}/issue`, "POST", undefined, token);
        if (result.success) return { ok: true };
        return { ok: false, reason: result.error ?? "Failed to issue debit note" };
      } catch (e) {
        return { ok: false, reason: e instanceof Error ? e.message : "Failed to issue debit note" };
      }
    });

    const issued = results.filter((r) => r.ok).length;
    const failures = results.filter((r): r is { ok: false; reason: string } => !r.ok);
    const failed = failures.length;

    if (issued > 0) load();

    const parts: string[] = [];
    if (issued > 0) parts.push(`${issued} issued`);
    if (skipped > 0) parts.push(`${skipped} skipped (not draft)`);
    if (failed > 0) {
      const reasons = Array.from(new Set(failures.map((f) => f.reason)));
      parts.push(`${failed} failed (${reasons.join("; ")})`);
    }
    const text = parts.length > 0 ? `${parts.join(", ")}.` : "No draft debit notes selected.";

    if (skipped > 0 || failed > 0) {
      setMsg({ type: "err", text });
      return false;
    }
    setMsg({ type: "ok", text });
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
      id: "issue",
      label: "Issue draft(s)",
      icon: <CheckCircle size={12} />,
      confirm: "Issue the selected draft debit notes? This posts a journal entry for each and cannot be undone.",
      run: handleBulkIssue,
    },
    {
      id: "delete",
      label: "Delete draft(s)",
      icon: <Trash2 size={12} />,
      variant: "danger",
      confirm: "Delete the selected draft debit notes? This cannot be undone.",
      run: handleBulkDelete,
    },
    exportSelectedAction("debit-notes-selected.csv", columns),
  ], [handleBulkIssue, handleBulkDelete, columns]);

  return (
    <div className="space-y-4 max-w-screen-2xl mx-auto">
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

      {/* Row overflow menu — View details always; Edit for any note (draft gets
          the full editor, issued gets the same editor scoped to notes/
          attachment only — see DebitNoteEditor's isLocked handling); Delete
          for drafts only. No Cancel — a debit note has no reversal path,
          deliberately (CGST Act §34: correct with a fresh note). */}
      {menu && (() => {
        const d = debitNotes.find((x) => x.id === menu.id);
        if (!d) return null;
        return (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setMenu(null)} />
            <div
              className="fixed z-50 w-44 bg-white rounded-lg border border-[#E2E8F0] shadow-lg py-1 text-xs"
              style={{ top: menu.top, left: menu.left }}
            >
              <button onClick={() => { setMenu(null); setDetailId(d.id); }}
                className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F8FAFC] text-[#334155]">
                View details
              </button>
              <button onClick={() => { setMenu(null); router.push(`/clients/${clientId}/purchases/debit-notes/${d.id}/edit`); }}
                className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F8FAFC] text-[#334155]">
                {d.status === "draft" ? "Edit draft" : "Edit"}
              </button>
              {d.status === "draft" && (
                <>
                  <div className="my-1 border-t border-[#F1F5F9]" />
                  <button onClick={() => { setMenu(null); deleteDebitNote(d); }}
                    className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-red-50 text-red-600">
                    Delete draft
                  </button>
                </>
              )}
            </div>
          </>
        );
      })()}

      {detailId && (
        <DebitNoteViewDrawer
          dnId={detailId}
          clientId={clientId}
          vendorName={
            debitNotes.find((d) => d.id === detailId)?.vendor_name
            ?? vendors.find((v) => v.id === debitNotes.find((d) => d.id === detailId)?.vendor_id)?.name
            ?? ""
          }
          onClose={() => setDetailId(null)}
          onEdit={(id) => router.push(`/clients/${clientId}/purchases/debit-notes/${id}/edit`)}
          onIssue={(dn) => { setDetailId(null); issueDebitNote(dn.id); }}
          onDelete={deleteDebitNote}
          onDuplicate={duplicateDebitNote}
        />
      )}

      {/* Bulk import (CSV / XLSX) — reuses the existing create endpoint */}
      {showImport && (
        <CsvImportModal
          title="Import Debit Notes"
          columns={PURCHASE_DEBIT_NOTE_IMPORT_COLUMNS}
          templateFilename="purchase_debit_notes_template"
          onImport={handleImport}
          onClose={() => setShowImport(false)}
        />
      )}

      {/* Table — shared DataTable (search, sort, filters, pagination, export, prefs) */}
      <DataTable
        data={debitNotes}
        columns={columns}
        filters={filters}
        getRowId={(d) => d.id}
        loading={loading}
        error={loadFailed ? "Couldn't load debit notes — the request failed or timed out." : null}
        onRetry={load}
        onRefresh={load}
        searchPlaceholder="Search DN no., vendor, or reason…"
        initialSort={{ key: "debit_note_date", dir: "desc" }}
        exportFilename="debit-notes"
        persistKey="purchases.debit-notes"
        emptyTitle={`No debit notes in FY ${financialYear}`}
        toolbarExtra={
          <>
            <FinancialYearPicker value={financialYear} onChange={onFinancialYearChange} />
            <button
              onClick={() => setShowImport(true)}
              className="flex items-center gap-1.5 text-xs border border-[#E2E8F0] text-[#475569] px-3 py-1.5 rounded-lg hover:bg-[#F8FAFC]"
            >
              <Upload size={12} /> Import
            </button>
            <button
              onClick={() => router.push(`/clients/${clientId}/purchases/debit-notes/new/edit`)}
              className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700"
            >
              <Plus size={12} /> Create Debit Note
            </button>
          </>
        }
        bulkActions={bulkActions}
        rowActions={(d) => (
          <div className="flex items-center justify-end gap-2">
            {d.status === "draft" && (
              <button
                onClick={() => issueDebitNote(d.id)}
                disabled={issuingId === d.id}
                className="text-xs text-blue-600 hover:underline flex items-center gap-1 disabled:opacity-50 disabled:no-underline"
              >
                {issuingId === d.id ? <Loader2 size={11} className="animate-spin" /> : <CheckCircle size={11} />} Issue
              </button>
            )}
            <button
              onClick={(e) => openMenuFor(e, d)}
              aria-label={`Actions for debit note ${d.debit_note_no || d.id}`}
              className="p-1 rounded hover:bg-[#F1F5F9] text-[#64748B]"
            >
              <MoreHorizontal size={16} />
            </button>
          </div>
        )}
      />
    </div>
  );
}

// ── Purchase Credit Notes (CGST Act §34(3) — vendor undercharge correction) ──
// The increase-side mirror of Debit Notes above: a vendor undercharged us on
// the original bill and we now owe more. Same shape, same flow, just pointed
// at /api/purchase-credit-notes and the opposite ledger direction (a credit
// note CREDITS — increases — our trade payable).

interface PurchaseCreditNoteRow {
  id: string;
  credit_note_no: string | null;
  credit_note_date: string;
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

function PurchaseCreditNotes({ clientId, financialYear, onFinancialYearChange }: { clientId: string; financialYear: string; onFinancialYearChange: (fy: string) => void }) {
  const router = useRouter();
  const [creditNotes, setCreditNotes] = useState<PurchaseCreditNoteRow[]>([]);
  const [vendors, setVendors] = useState<Vendor[]>([]);
  // See DebitNotes' identical fetch above — same import-only purpose.
  const [services, setServices] = useState<ServiceCatalogueItem[]>([]);
  const [originalBills, setOriginalBills] = useState<OriginalDocRef[]>([]);
  const [showImport, setShowImport] = useState(false);
  const [loading, setLoading] = useState(true);
  // See PurchaseBills.loadFailed (audit M17): a failed fetch must show a retryable
  // error, not the "No credit notes" empty state that a genuinely empty FY shows.
  const [loadFailed, setLoadFailed] = useState(false);
  const [msg, setMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);
  const [issuingId, setIssuingId] = useState<string | null>(null);
  const [menu, setMenu] = useState<{ id: string; top: number; left: number } | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadFailed(false);
    const supabase = getSupabaseClient();
    const { start, end } = fyRange(financialYear);
    try {
      const [pcnRes, vendorsRes, servicesRes, billsRes] = await Promise.all([
        selectAll(() => supabase
          .from("purchase_credit_notes")
          .select("*, purchase_bills(bill_no, our_reference)")
          .eq("client_id", clientId)
          .gte("credit_note_date", start)
          .lte("credit_note_date", end)
          .order("credit_note_date", { ascending: false })
          .order("id")),
        selectAll(() => supabase
          .from("vendors")
          .select("id, name, gstin, tds_applicable, tds_section, tds_rate_bps")
          .eq("client_id", clientId)
          .eq("is_active", true)
          .order("name")
          .order("id")),
        selectAll(() => supabase
          .from("service_catalogue")
          .select("id, name, description, hsn_sac, gst_rate_bps, purchase_price_paise, unit, kind, is_active")
          .eq("client_id", clientId)
          .eq("is_active", true)
          .order("name")
          .order("id")),
        selectAll(() => supabase
          .from("purchase_bills")
          .select("id, bill_no, vendor_id, is_interstate")
          .eq("client_id", clientId)
          .order("bill_date", { ascending: false })
          .order("id")),
      ]);
      // M17: a failed credit-notes fetch (thrown or non-null PostgREST error) must
      // surface as retryable, not read as an empty FY (identical to having none).
      if (pcnRes.error) throw pcnRes.error;
      const vendorList = (vendorsRes.data as Vendor[]) ?? [];
      const vendorMap = new Map(vendorList.map((v) => [v.id, v.name]));
      const rows = ((pcnRes.data as PurchaseCreditNoteRow[]) ?? []).map((d) => ({
        ...d,
        vendor_name: vendorMap.get(d.vendor_id) ?? "—",
      }));
      setCreditNotes(rows);
      setVendors(vendorList);
      setServices((servicesRes.data as ServiceCatalogueItem[]) ?? []);
      setOriginalBills(
        ((billsRes.data ?? []) as Array<{ id: string; bill_no: string | null; vendor_id: string; is_interstate: boolean }>)
          .filter((r) => !!r.bill_no)
          .map((r) => ({ id: r.id, no: r.bill_no as string, partyId: r.vendor_id, isInterstate: r.is_interstate }))
      );
    } catch {
      setCreditNotes([]);
      setLoadFailed(true);
    } finally {
      setLoading(false);
    }
  }, [clientId, financialYear]);

  useEffect(() => { load(); }, [load]);

  /** Bulk-import handler for the CSV/XLSX modal. Maps flat rows → grouped
   * Purchase Credit Notes via buildPurchaseCreditNotes, then POSTs each note
   * once through the existing create endpoint (draft-only). */
  async function handleImport(rows: ImportRow[]): Promise<{ imported: number; errors: string[] }> {
    const vendorRefs: NameRef[] = vendors.map((v) => ({ id: v.id, name: v.name }));
    const serviceRefs: PurchaseServiceRef[] = services.map((s) => ({
      id: s.id, name: s.name, description: s.description, hsn_sac: s.hsn_sac,
      gst_rate_bps: s.gst_rate_bps, purchase_price_paise: s.purchase_price_paise, unit: s.unit,
    }));
    const { notes, errors } = buildPurchaseCreditNotes(rows, clientId, vendorRefs, originalBills, serviceRefs);
    if (notes.length === 0) return { imported: 0, errors };
    const token = await getAuthToken();
    let imported = 0;
    for (const note of notes) {
      const result = await apiCall("/api/purchase-credit-notes/", "POST", note, token);
      if (result.success) imported += 1;
      else errors.push(result.error ?? "Bulk import failed");
    }
    if (imported > 0) load();
    return { imported, errors };
  }

  function openMenuFor(e: React.MouseEvent, pcn: PurchaseCreditNoteRow) {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setMenu({ id: pcn.id, top: r.bottom + 4, left: Math.max(8, r.right - 176) });
  }

  async function issueCreditNote(id: string) {
    if (issuingId) return;
    setIssuingId(id);
    try {
      const token = await getAuthToken();
      const result = await apiCall(`/api/purchase-credit-notes/${id}/issue`, "POST", undefined, token);
      if (!result.success) throw new Error(result.error ?? "Failed to issue credit note");
      setMsg({ type: "ok", text: "Credit note issued." });
      load();
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Error issuing credit note" });
    } finally {
      setIssuingId(null);
    }
  }

  async function deletePcn(pcn: PurchaseCreditNoteRow | PurchaseCreditNoteDetail) {
    const ok = await confirmDialog({
      title: `Delete ${pcn.credit_note_no || "this credit note"}?`,
      message: "This cannot be undone.",
      confirmLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    setDetailId(null);
    try {
      const token = await getAuthToken();
      const result = await apiCall(`/api/purchase-credit-notes/${pcn.id}`, "DELETE", undefined, token);
      if (!result.success) throw new Error(result.error ?? "Failed to delete credit note");
      setMsg({ type: "ok", text: `${pcn.credit_note_no || "Credit note"} deleted` });
      load();
    } catch (err) {
      setMsg({ type: "err", text: err instanceof Error ? err.message : "Failed to delete credit note" });
    }
  }

  function duplicatePcn(pcn: PurchaseCreditNoteDetail) {
    writePurchaseCreditNoteDuplicateSeed(pcn);
    setDetailId(null);
    router.push(`/clients/${clientId}/purchases/credit-notes/new/edit`);
  }

  // Bulk delete over the DataTable's selected rows — draft-only on the
  // backend (422s "Cannot delete an issued credit note…" for anything
  // already issued); loop per row so one rejection doesn't abort the rest.
  const handleBulkDelete = useCallback(async (rows: PurchaseCreditNoteRow[]): Promise<boolean> => {
    const token = await getAuthToken();
    const results = await Promise.all(
      rows.map(async (d) => {
        try {
          const result = await apiCall(`/api/purchase-credit-notes/${d.id}`, "DELETE", undefined, token);
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
    setMsg({ type: "ok", text: `${deleted} credit note${deleted === 1 ? "" : "s"} deleted.` });
    return true;
  }, [load]);

  // Bulk issue over the DataTable's selected rows. POST
  // /api/purchase-credit-notes/{id}/issue is draft-only on the backend — loop
  // per row, at most 8 in flight at once (see handleBulkReceive on the Bills
  // tab for why unbounded Promise.all breaks down at large selection sizes);
  // non-draft rows are skipped client-side rather than sent to 422.
  const handleBulkIssue = useCallback(async (rows: PurchaseCreditNoteRow[]): Promise<boolean> => {
    const token = await getAuthToken();
    const draftRows = rows.filter((d) => d.status === "draft");
    const skipped = rows.length - draftRows.length;

    type IssueResult = { ok: true } | { ok: false; reason: string };
    const results: IssueResult[] = await mapWithConcurrency(draftRows, 8, async (d): Promise<IssueResult> => {
      try {
        const result = await apiCall(`/api/purchase-credit-notes/${d.id}/issue`, "POST", undefined, token);
        if (result.success) return { ok: true };
        return { ok: false, reason: result.error ?? "Failed to issue credit note" };
      } catch (e) {
        return { ok: false, reason: e instanceof Error ? e.message : "Failed to issue credit note" };
      }
    });

    const issued = results.filter((r) => r.ok).length;
    const failures = results.filter((r): r is { ok: false; reason: string } => !r.ok);
    const failed = failures.length;

    if (issued > 0) load();

    const parts: string[] = [];
    if (issued > 0) parts.push(`${issued} issued`);
    if (skipped > 0) parts.push(`${skipped} skipped (not draft)`);
    if (failed > 0) {
      const reasons = Array.from(new Set(failures.map((f) => f.reason)));
      parts.push(`${failed} failed (${reasons.join("; ")})`);
    }
    const text = parts.length > 0 ? `${parts.join(", ")}.` : "No draft credit notes selected.";

    if (skipped > 0 || failed > 0) {
      setMsg({ type: "err", text });
      return false;
    }
    setMsg({ type: "ok", text });
    return true;
  }, [load]);

  const columns: Column<PurchaseCreditNoteRow>[] = useMemo(() => [
    { key: "credit_note_no", header: "CN No", accessor: (d) => d.credit_note_no ?? "", searchable: true, sortable: true, sticky: true, hideable: false,
      render: (d) => <span className="font-mono font-medium text-[#1E293B]">{d.credit_note_no ?? "—"}</span> },
    { key: "credit_note_date", header: "Date", accessor: (d) => d.credit_note_date, sortable: true,
      render: (d) => <span className="text-[#64748B] whitespace-nowrap">{d.credit_note_date}</span> },
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

  const filters: FilterDef<PurchaseCreditNoteRow>[] = useMemo(() => [
    { key: "status", label: "Status", type: "select", accessor: (d) => d.status, options: [
      { value: "draft", label: "Draft" },
      { value: "issued", label: "Issued" },
    ] },
    { key: "vendor_name", label: "Vendor", type: "select", accessor: (d) => d.vendor_name ?? "",
      options: vendors.map((v) => ({ value: v.name, label: v.name })) },
  ], [vendors]);

  const bulkActions: BulkAction<PurchaseCreditNoteRow>[] = useMemo(() => [
    {
      id: "issue",
      label: "Issue draft(s)",
      icon: <CheckCircle size={12} />,
      confirm: "Issue the selected draft credit notes? This posts a journal entry for each and cannot be undone.",
      run: handleBulkIssue,
    },
    {
      id: "delete",
      label: "Delete draft(s)",
      icon: <Trash2 size={12} />,
      variant: "danger",
      confirm: "Delete the selected draft credit notes? This cannot be undone.",
      run: handleBulkDelete,
    },
    exportSelectedAction("purchase-credit-notes-selected.csv", columns),
  ], [handleBulkIssue, handleBulkDelete, columns]);

  return (
    <div className="space-y-4 max-w-screen-2xl mx-auto">
      {msg && (
        <div className={`flex items-center gap-2 px-4 py-3 rounded-lg text-sm ${msg.type === "ok" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-600"}`}>
          {msg.type === "ok" ? <CheckCircle size={14} /> : <AlertCircle size={14} />}
          {msg.text}
          <button onClick={() => setMsg(null)} className="ml-auto"><X size={13} /></button>
        </div>
      )}

      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-[#334155]">
          {creditNotes.length} credit note{creditNotes.length !== 1 ? "s" : ""} in FY {financialYear}
        </p>
      </div>

      {/* Row overflow menu — View details always; Edit for any note (draft
          gets the full editor, issued gets the same editor scoped to notes/
          attachment only); Delete for drafts only. No Cancel — a credit note
          has no reversal path, deliberately (CGST Act §34: correct with a
          fresh note). */}
      {menu && (() => {
        const d = creditNotes.find((x) => x.id === menu.id);
        if (!d) return null;
        return (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setMenu(null)} />
            <div
              className="fixed z-50 w-44 bg-white rounded-lg border border-[#E2E8F0] shadow-lg py-1 text-xs"
              style={{ top: menu.top, left: menu.left }}
            >
              <button onClick={() => { setMenu(null); setDetailId(d.id); }}
                className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F8FAFC] text-[#334155]">
                View details
              </button>
              <button onClick={() => { setMenu(null); router.push(`/clients/${clientId}/purchases/credit-notes/${d.id}/edit`); }}
                className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F8FAFC] text-[#334155]">
                {d.status === "draft" ? "Edit draft" : "Edit"}
              </button>
              {d.status === "draft" && (
                <>
                  <div className="my-1 border-t border-[#F1F5F9]" />
                  <button onClick={() => { setMenu(null); deletePcn(d); }}
                    className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-red-50 text-red-600">
                    Delete draft
                  </button>
                </>
              )}
            </div>
          </>
        );
      })()}

      {detailId && (
        <PurchaseCreditNoteViewDrawer
          pcnId={detailId}
          clientId={clientId}
          vendorName={
            creditNotes.find((d) => d.id === detailId)?.vendor_name
            ?? vendors.find((v) => v.id === creditNotes.find((d) => d.id === detailId)?.vendor_id)?.name
            ?? ""
          }
          onClose={() => setDetailId(null)}
          onEdit={(id) => router.push(`/clients/${clientId}/purchases/credit-notes/${id}/edit`)}
          onIssue={(pcn) => { setDetailId(null); issueCreditNote(pcn.id); }}
          onDelete={deletePcn}
          onDuplicate={duplicatePcn}
        />
      )}

      {/* Bulk import (CSV / XLSX) — reuses the existing create endpoint */}
      {showImport && (
        <CsvImportModal
          title="Import Credit Notes"
          columns={PURCHASE_CREDIT_NOTE_IMPORT_COLUMNS}
          templateFilename="purchase_credit_notes_template"
          onImport={handleImport}
          onClose={() => setShowImport(false)}
        />
      )}

      {/* Table — shared DataTable (search, sort, filters, pagination, export, prefs) */}
      <DataTable
        data={creditNotes}
        columns={columns}
        filters={filters}
        getRowId={(d) => d.id}
        loading={loading}
        error={loadFailed ? "Couldn't load credit notes — the request failed or timed out." : null}
        onRetry={load}
        onRefresh={load}
        searchPlaceholder="Search CN no., vendor, or reason…"
        initialSort={{ key: "credit_note_date", dir: "desc" }}
        exportFilename="purchase-credit-notes"
        persistKey="purchases.credit-notes"
        emptyTitle={`No credit notes in FY ${financialYear}`}
        toolbarExtra={
          <>
            <FinancialYearPicker value={financialYear} onChange={onFinancialYearChange} />
            <button
              onClick={() => setShowImport(true)}
              className="flex items-center gap-1.5 text-xs border border-[#E2E8F0] text-[#475569] px-3 py-1.5 rounded-lg hover:bg-[#F8FAFC]"
            >
              <Upload size={12} /> Import
            </button>
            <button
              onClick={() => router.push(`/clients/${clientId}/purchases/credit-notes/new/edit`)}
              className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700"
            >
              <Plus size={12} /> Create Credit Note
            </button>
          </>
        }
        bulkActions={bulkActions}
        rowActions={(d) => (
          <div className="flex items-center justify-end gap-2">
            {d.status === "draft" && (
              <button
                onClick={() => issueCreditNote(d.id)}
                disabled={issuingId === d.id}
                className="text-xs text-blue-600 hover:underline flex items-center gap-1 disabled:opacity-50 disabled:no-underline"
              >
                {issuingId === d.id ? <Loader2 size={11} className="animate-spin" /> : <CheckCircle size={11} />} Issue
              </button>
            )}
            <button
              onClick={(e) => openMenuFor(e, d)}
              aria-label={`Actions for credit note ${d.credit_note_no || d.id}`}
              className="p-1 rounded hover:bg-[#F1F5F9] text-[#64748B]"
            >
              <MoreHorizontal size={16} />
            </button>
          </div>
        )}
      />
    </div>
  );
}
