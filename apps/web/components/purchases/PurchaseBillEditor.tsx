"use client";

/**
 * PurchaseBillEditor — dedicated create experience for Purchase Bills,
 * mirroring the Sales Invoice editor's architecture (InvoiceWorkspaceLayout,
 * dirty-changes guard, per-field validation, live GST preview) instead of
 * the old inline modal. No business logic is duplicated: totals shown here
 * are a preview (lib/purchases/billEditor.ts, unit-tested, floor-based —
 * matches the backend's own _compute_line_gst exactly); the backend remains
 * authoritative and recomputes everything on save.
 */
import { useState, useRef, useEffect } from "react";
import { Trash2, Plus, Loader2, AlertCircle, AlertTriangle, Upload } from "lucide-react";
import { InvoiceWorkspaceLayout } from "@/components/invoices/InvoiceWorkspaceLayout";
import { VendorLookup, type VendorLike } from "@/components/lookups/VendorLookup";
import { AccountLookup, type AccountLike } from "@/components/lookups/AccountLookup";
import { HsnLookup } from "@/components/lookups/HsnLookup";
import { ServiceCataloguePicker } from "@/components/lookups/ServiceCataloguePicker";
import type { ServiceCatalogueItem } from "@/lib/catalogue/service";
import { UQC_CODES } from "@/lib/constants/uqc";
import { estimateBaseMinor, estimateForeignTds, convertBaseToForeignMinor } from "@/lib/services/currencyPreview";
import { formatMoney } from "@/lib/services/formatting";
import { hasChanges, useUnsavedChanges } from "@/lib/invoices/dirtyState";
import { confirmDialog } from "@/components/ui/confirm-dialog";
import { apiCall, apiGet, getAuthToken, fmt, GST_RATES, type CurrencyOption } from "@/lib/invoices/shared";
import { getSupabaseClient } from "@/lib/supabase/client";
import {
  isValidBillLine, previewBillTotals, validateBillEditor, findBlockedCreditHits,
  type PurchaseBillLine,
} from "@/lib/purchases/billEditor";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface PurchaseVendor extends VendorLike {
  tds_applicable?: boolean;
  tds_section?: string | null;
  tds_rate_bps?: number;
  is_active?: boolean;
}

type EditorLine = PurchaseBillLine & {
  _k: number;
  product?: ServiceCatalogueItem | null;
  /** Catalogue items sharing this line's HSN/SAC, looked up right after AI
   * extraction (see handleExtract) — undefined means "not looked up" (e.g.
   * a manually-added blank line), [] means "looked up, no match". A single
   * match auto-links; multiple render as one-click chips instead of forcing
   * a manual catalogue search the CA has no way to aim (they only know the
   * HSN code shown on the line, not which preset name it maps to). */
  hsnMatches?: ServiceCatalogueItem[];
};
const EMPTY_LINE: PurchaseBillLine = { description: "", hsn_sac: "", qty: "1", rate: "", gst_rate: 18, unit: "NOS", expense_account_id: "", service_catalogue_id: "" };

/** Purchase-side product/service prefill — uses purchase_price_paise, NOT
 * default_rate_paise (the SELL price). The old inline-modal form used
 * lib/catalogue/service.ts's serviceToLine here, which is sales-side and
 * silently pre-filled the SELL price on every purchase bill line picked
 * from the catalogue — fixed here. */
function purchaseServiceToLine(item: ServiceCatalogueItem): Partial<PurchaseBillLine> {
  return {
    description: (item.description ?? "").trim(),
    hsn_sac: item.hsn_sac ?? "",
    rate: item.purchase_price_paise ? String(item.purchase_price_paise / 100) : "",
    gst_rate: item.gst_rate_bps == null ? 0 : item.gst_rate_bps / 100,
    unit: item.unit ?? "NOS",
  };
}

function todayISO(): string {
  return new Date().toISOString().split("T")[0];
}

interface ExtractedInvoice {
  vendor_name?: string;
  vendor_gstin?: string;
  invoice_no?: string;
  invoice_date?: string;
  line_items?: { description?: string; hsn_sac?: string; quantity?: number; rate_paise?: number; gst_rate_bps?: number }[];
}

/** Server line shape (from GET /api/purchase-bills/{id}). */
export interface PurchaseBillLineDetail {
  id?: string;
  description: string;
  hsn_sac: string | null;
  quantity: number;
  unit?: string | null;
  rate_paise: number;
  gst_rate_bps: number;
  taxable_amount_paise?: number;
  cgst_paise?: number;
  sgst_paise?: number;
  igst_paise?: number;
  line_total_paise?: number;
  expense_account_id?: string | null;
  service_catalogue_id?: string | null;
}

/** Full purchase-bill detail (Edit route). vendor_id is NOT editable via
 * PATCH (backend has no vendor_id field on PurchaseBillUpdateIn — changing
 * the vendor would invalidate the frozen TDS section/rate) so the Edit
 * route only ever shows this for context, never mutates it. */
export interface PurchaseBillDetail {
  id: string;
  vendor_id: string;
  bill_no: string;
  our_reference?: string | null;
  bill_date: string;
  due_date: string | null;
  credit_days?: number | null;
  is_reverse_charge?: boolean;
  is_interstate?: boolean;
  status: string;
  notes?: string | null;
  document_url?: string | null;
  txn_currency?: string | null;
  exchange_rate?: string | null;
  taxable_amount_paise?: number;
  cgst_paise?: number;
  sgst_paise?: number;
  igst_paise?: number;
  total_gst_paise?: number;
  total_paise?: number;
  tds_paise?: number;
  tds_rate_bps?: number;
  tds_section?: string | null;
  net_payable_paise?: number;
  paid_paise?: number;
  // Sum of issued debit notes against this bill (routers/debit_notes.py) —
  // reduces the payable alongside paid_paise, so outstanding is
  // net_payable − paid − debited (mirrors purchase_payments._claim_bill_outstanding).
  debited_paise?: number;
  // Sum of issued purchase credit notes against this bill (routers/
  // purchase_credit_notes.py, CGST Act §34(3) — a vendor undercharge) —
  // INCREASES the payable: outstanding = (net_payable + credit_note_paise) − paid − debited.
  credit_note_paise?: number;
  journal_entry_id?: string | null;
  received_at?: string | null;
  created_at?: string | null;
  lines: PurchaseBillLineDetail[];
}

/** existing.lines is the server line shape — shared here so re-editing a
 * draft can't drift from how it was originally saved. */
function detailLinesToEditorLines(lines: PurchaseBillDetail["lines"]): EditorLine[] {
  return lines.map((l, i) => ({
    description: l.description ?? "",
    hsn_sac: l.hsn_sac ?? "",
    qty: String(l.quantity ?? 1),
    rate: String((l.rate_paise ?? 0) / 100),
    gst_rate: Math.round((l.gst_rate_bps ?? 0) / 100),
    unit: l.unit ?? "NOS",
    expense_account_id: l.expense_account_id ?? "",
    service_catalogue_id: l.service_catalogue_id ?? "",
    _k: i,
  }));
}

export function PurchaseBillEditor({
  clientId, clientName, clientStateCode, vendors, accounts, existing, duplicateSeed, onDone, onCancel,
}: {
  clientId: string;
  clientName?: string;
  /** This client's own GST state code — vendor.state_code differing from
   * this drives the CGST+SGST vs IGST preview split (CGST Act §8). The
   * backend independently recomputes is_interstate from the live vendor/
   * client rows on save; this is preview-only. */
  clientStateCode: string;
  vendors: PurchaseVendor[];
  accounts: AccountLike[];
  /** Set → edit an existing draft bill (PATCH). Absent/null → create (POST). */
  existing?: PurchaseBillDetail | null;
  /** "Duplicate bill" prefill (lib/purchases/duplicateSeed) — create mode
   * only. Copies vendor, lines, RCM flag and notes; deliberately NOT the
   * vendor invoice number (each vendor bill has its own), dates, reference,
   * or the attachment (which belongs to the original bill). */
  duplicateSeed?: PurchaseBillDetail | null;
  onDone: (message: string) => void;
  onCancel: () => void;
}) {
  const today = todayISO();
  const isEdit = !!existing;
  const initialLines: EditorLine[] =
    existing && existing.lines.length > 0 ? detailLinesToEditorLines(existing.lines)
    : duplicateSeed && duplicateSeed.lines.length > 0 ? detailLinesToEditorLines(duplicateSeed.lines)
    : [{ ...EMPTY_LINE, _k: 0 }];

  const [vendorId, setVendorId] = useState(existing?.vendor_id ?? duplicateSeed?.vendor_id ?? "");
  const [selectedVendor, setSelectedVendor] = useState<PurchaseVendor | null>(() => {
    const seedVendorId = existing?.vendor_id ?? duplicateSeed?.vendor_id;
    return seedVendorId ? vendors.find((v) => v.id === seedVendorId) ?? null : null;
  });
  const [billNo, setBillNo] = useState(existing?.bill_no ?? "");
  const [ourReference, setOurReference] = useState(existing?.our_reference ?? "");
  const [notes, setNotes] = useState(existing?.notes ?? duplicateSeed?.notes ?? "");
  const [billDate, setBillDate] = useState(existing?.bill_date ?? today);
  const [dueDate, setDueDate] = useState(existing?.due_date ?? "");
  const [isReverseCharge, setIsReverseCharge] = useState(existing?.is_reverse_charge ?? duplicateSeed?.is_reverse_charge ?? false);
  // Once a bill is received/partially-paid/paid, the backend only accepts
  // our_reference/notes/due_date/document_url on PATCH (routers/purchase_bills.py
  // _SOFT_BILL_UPDATE_FIELDS) — bill_no/bill_date/lines are frozen; a correction
  // to those needs a Debit Note instead (CGST Act §34). Locking them here too
  // (not just server-side) means the CA never fills in a full edit only to have
  // it rejected on save.
  const isLocked = isEdit && existing?.status !== "draft";
  const [lines, setLines] = useState<EditorLine[]>(initialLines);
  const keyRef = useRef(initialLines.length);
  const nextKey = () => keyRef.current++;
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempted, setAttempted] = useState(false);

  // AI Upload (Extract) — create-only; re-extracting into an already-saved
  // draft would silently overwrite manually-corrected fields.
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [aiExtracted, setAiExtracted] = useState<Record<string, unknown> | null>(null);
  // Storage PATH of the uploaded invoice (not a browser-openable URL — the
  // "Documents" bucket is private) — set on any upload attempt, whether or
  // not AI extraction itself succeeds, so the original file is retained as
  // ITC/audit evidence (CGST Rule 36(1)) even on a failed extraction.
  const [documentUrl, setDocumentUrl] = useState<string | null>(existing?.document_url ?? null);

  // Multi-currency — frozen at creation; not user-editable in edit mode
  // (PurchaseBillUpdateIn has no currency/exchange_rate field), but still
  // seeded from `existing` so preview totals render in the bill's own
  // currency rather than silently reverting to INR.
  const [currency, setCurrency] = useState(
    isEdit && existing?.txn_currency && existing.txn_currency !== "INR" ? existing.txn_currency : "",
  );
  const [exchangeRate, setExchangeRate] = useState(
    isEdit && existing?.exchange_rate ? String(existing.exchange_rate) : "",
  );
  const [mcActive, setMcActive] = useState(false);
  const [currencies, setCurrencies] = useState<CurrencyOption[]>([]);

  useEffect(() => {
    if (isEdit || !clientId) return;
    let cancelled = false;
    (async () => {
      try {
        const token = await getAuthToken();
        const pol = await apiGet(`/api/currencies/policy?client_id=${clientId}`, token);
        if (cancelled) return;
        const active = Boolean(pol.success && (pol.data as { active?: boolean } | null)?.active);
        setMcActive(active);
        if (!active) return;
        const list = await apiGet(`/api/currencies?active_only=true`, token);
        if (!cancelled && list.success) setCurrencies((list.data as CurrencyOption[]) ?? []);
      } catch { /* best-effort: multi-currency is optional */ }
    })();
    return () => { cancelled = true; };
  }, [clientId, isEdit]);

  // Rehydrate each existing line's Product/Service picker. detailLinesToEditorLines
  // deliberately keeps only service_catalogue_id from the server (not the full
  // catalogue object), so on load every line's picker shows blank
  // ("+ Add Product/Service") even though a product IS linked, right up until
  // the CA re-picks something. One batched by-id lookup fixes that. Not
  // filtered to is_active — a bill can reference a since-archived preset, and
  // its name should still show, especially since the picker is disabled in
  // locked mode. Same fix as InvoiceEditor.tsx (same underlying pattern).
  useEffect(() => {
    if (!isEdit || !existing?.id) return;
    const ids = Array.from(new Set(
      initialLines.map((l) => l.service_catalogue_id).filter((id): id is string => !!id),
    ));
    if (!ids.length) return;
    let cancelled = false;
    (async () => {
      try {
        const supabase = getSupabaseClient();
        const { data } = await supabase
          .from("service_catalogue")
          .select("*")
          .eq("client_id", clientId)
          .in("id", ids);
        if (cancelled || !data?.length) return;
        const byId = new Map((data as ServiceCatalogueItem[]).map((s) => [s.id, s]));
        const withProducts = (prev: EditorLine[]): EditorLine[] =>
          prev.map((l) => (l.service_catalogue_id && byId.has(l.service_catalogue_id) && !l.product
            ? { ...l, product: byId.get(l.service_catalogue_id) }
            : l));
        setLines(withProducts);
        // Keep the dirty-check snapshot in lockstep — otherwise this
        // rehydration itself would flip the editor to "Unsaved changes".
        initialSnapshot.current = { ...initialSnapshot.current, lines: withProducts(initialSnapshot.current.lines) };
      } catch {
        // Best-effort: a failed lookup just leaves those lines' pickers blank,
        // same as before this fix — never blocks editing.
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-once per loaded bill; initialLines is derived from `existing` and stable for its lifetime
  }, [isEdit, existing?.id, clientId]);

  const isForeign = currency !== "" && currency !== "INR";
  const rateNum = parseFloat(exchangeRate);
  function fmtAmt(paise: number): string {
    return isForeign ? formatMoney(paise, currency) : fmt(paise);
  }

  // ── Dirty detection ──────────────────────────────────────────────────────
  const initialSnapshot = useRef({
    vendorId: existing?.vendor_id ?? "",
    billNo: existing?.bill_no ?? "",
    ourReference: existing?.our_reference ?? "",
    notes: existing?.notes ?? "",
    billDate: existing?.bill_date ?? today,
    dueDate: existing?.due_date ?? "",
    isReverseCharge: existing?.is_reverse_charge ?? false,
    lines: initialLines, currency, exchangeRate,
  });
  const currentSnapshot = { vendorId, billNo, ourReference, notes, billDate, dueDate, isReverseCharge, lines, currency, exchangeRate };
  const dirty = hasChanges(initialSnapshot.current, currentSnapshot);
  const { confirmLeave } = useUnsavedChanges(dirty && !saving, undefined, confirmDialog);

  // ── Interstate preview (CGST Act §8) — server recomputes independently ──
  const isInterstate = !!(clientStateCode && selectedVendor?.state_code && clientStateCode !== selectedVendor.state_code);
  const gstAuto = !!(clientStateCode && selectedVendor?.state_code);

  // ── Live preview totals + validation ────────────────────────────────────
  const totals = previewBillTotals(lines, isInterstate);
  // RCM (CGST Act §9(3)/(4)): the vendor invoices WITHOUT tax — the GST shown
  // is self-assessed (paid via GSTR-3B, ITC claimable), so the amount owed to
  // the vendor is the taxable value alone. Mirrors the backend's
  // _compute_bill_lines_and_totals; the server remains authoritative.
  const vendorTotalPaise = isReverseCharge ? totals.taxable_paise : totals.grand_total_paise;
  const validation = validateBillEditor({ vendorId, billDate, lines, isForeign, exchangeRate });
  const estBaseTaxable = isForeign && rateNum > 0 ? estimateBaseMinor(totals.taxable_paise, rateNum) : totals.taxable_paise;
  const estBaseTotal = isForeign && rateNum > 0 ? estimateBaseMinor(vendorTotalPaise, rateNum) : vendorTotalPaise;
  // TDS is a purely domestic, INR-only concept (IT Act §194) computed off the
  // INR-equivalent taxable value — never the raw foreign figure.
  const tdsPaise = selectedVendor?.tds_applicable && (selectedVendor.tds_rate_bps ?? 0) > 0
    ? estimateForeignTds(estBaseTaxable, selectedVendor.tds_rate_bps ?? 0)
    : 0;
  const netPayable = isForeign
    ? vendorTotalPaise - convertBaseToForeignMinor(tdsPaise, rateNum)
    : vendorTotalPaise - tdsPaise;

  const accountNameById = new Map(accounts.map((a) => [a.id ?? "", a.account_name ?? a.name ?? ""]));
  const blockedCreditHits = findBlockedCreditHits(lines, accountNameById);

  function onVendorChange(id: string) {
    // Vendor is locked once a draft exists — PurchaseBillUpdateIn has no
    // vendor_id field (changing it would invalidate the frozen TDS section/
    // rate resolution), so the picker itself is disabled in edit mode too.
    if (isEdit) return;
    setVendorId(id);
    setSelectedVendor(vendors.find((v) => v.id === id) ?? null);
  }

  function setLine(idx: number, patch: Partial<EditorLine>) {
    setLines((prev) => prev.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
  }
  function removeLine(idx: number) {
    if (lines.length <= 1) return;
    setLines((prev) => prev.filter((_, i) => i !== idx));
  }
  function onPickProduct(idx: number, item: ServiceCatalogueItem) {
    setLine(idx, { ...purchaseServiceToLine(item), product: item, service_catalogue_id: item.id });
  }
  function addLine() {
    setLines((prev) => [...prev, { ...EMPTY_LINE, _k: nextKey() }]);
  }

  // Look up catalogue items sharing each extracted line's HSN/SAC (one
  // batched query, not one search per line) and either auto-link a single
  // confident match or attach the candidate list for the chip UI below.
  // Never touches description/rate/gst_rate/unit — those came straight off
  // the actual invoice and are authoritative for this specific bill; the
  // catalogue item is a link for reuse/inventory, not a source of truth.
  async function matchLinesByHsn(rawLines: EditorLine[]): Promise<EditorLine[]> {
    const codes = Array.from(new Set(rawLines.map((l) => l.hsn_sac.trim()).filter(Boolean)));
    if (!codes.length) return rawLines;
    try {
      const supabase = getSupabaseClient();
      const { data } = await supabase
        .from("service_catalogue")
        .select("*")
        .eq("client_id", clientId)
        .eq("is_active", true)
        .in("hsn_sac", codes);
      const byHsn = new Map<string, ServiceCatalogueItem[]>();
      for (const item of (data as ServiceCatalogueItem[]) ?? []) {
        const code = (item.hsn_sac ?? "").trim();
        if (!code) continue;
        byHsn.set(code, [...(byHsn.get(code) ?? []), item]);
      }
      return rawLines.map((l) => {
        const code = l.hsn_sac.trim();
        if (!code) return l;
        const matches = byHsn.get(code) ?? [];
        return matches.length === 1
          ? { ...l, service_catalogue_id: matches[0].id, product: matches[0], hsnMatches: matches }
          : { ...l, hsnMatches: matches };
      });
    } catch {
      // Best-effort: a failed lookup just leaves lines unlinked, same as before.
      return rawLines;
    }
  }

  // ── AI document extraction ───────────────────────────────────────────────
  async function handleExtract() {
    if (!uploadFile) return;
    setExtracting(true);
    setAiExtracted(null);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", uploadFile);
      formData.append("client_id", clientId);
      const token = await getAuthToken();
      const res = await fetch(`${API}/api/document-intelligence-v1/extract-invoice`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
      });
      const json = await res.json();
      // The uploaded file is retained server-side as ITC/audit evidence
      // regardless of whether AI extraction itself succeeded.
      if (json.data?.document_url) setDocumentUrl(json.data.document_url as string);
      if (json.success && json.data?.extracted) {
        const ex = json.data.extracted as ExtractedInvoice;
        setAiExtracted(ex as unknown as Record<string, unknown>);
        if (ex.invoice_no) setBillNo(ex.invoice_no);
        if (ex.invoice_date) setBillDate(ex.invoice_date);
        // Match the extracted vendor — GSTIN first (exact, authoritative),
        // then name (fuzzy) — mirrors bill_from_document's own server-side
        // matching (routers/purchase_bills.py). Previously this extraction
        // path never attempted a vendor match at all, so the Vendor field
        // silently stayed empty even on a successful extraction.
        const gstin = ex.vendor_gstin?.trim().toUpperCase();
        const name = ex.vendor_name?.trim().toLowerCase();
        const matched = (gstin && vendors.find((v) => v.gstin?.toUpperCase() === gstin))
          ?? (name && vendors.find((v) => v.name.trim().toLowerCase() === name))
          ?? null;
        if (matched) onVendorChange(matched.id);
        if (ex.line_items?.length) {
          const rawLines: EditorLine[] = ex.line_items.map((li) => ({
            description: li.description ?? "", hsn_sac: li.hsn_sac ?? "",
            qty: String(li.quantity ?? 1), unit: "NOS",
            rate: String(Math.floor((li.rate_paise ?? 0)) / 100),
            gst_rate: (li.gst_rate_bps ?? 1800) / 100,
            expense_account_id: "", service_catalogue_id: "",
            _k: nextKey(),
          }));
          setLines(await matchLinesByHsn(rawLines));
        }
        if (!matched && (gstin || name)) {
          setError(`AI extracted vendor "${ex.vendor_name ?? gstin}" but no matching vendor was found — select one manually.`);
        }
      } else {
        setError(json.error || "AI extraction failed. Please enter the bill details manually.");
      }
    } catch {
      setError("AI extraction failed. Please enter the bill details manually.");
    } finally {
      setExtracting(false);
    }
  }

  // ── Save ─────────────────────────────────────────────────────────────────
  async function save() {
    setAttempted(true);
    if (!validation.ok) {
      setError(validation.errors.vendor ?? validation.errors.billDate ?? validation.errors.lines ?? validation.errors.exchangeRate ?? "Fix the highlighted fields.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const token = await getAuthToken();
      const linePayload = lines.filter(isValidBillLine).map((l) => ({
        description: l.description,
        hsn_sac: l.hsn_sac || undefined,
        quantity: parseFloat(l.qty) || 0,
        unit: l.unit || undefined,
        rate_paise: Math.round((parseFloat(l.rate) || 0) * 100),
        gst_rate_percent: l.gst_rate,
        expense_account_id: l.expense_account_id || undefined,
        service_catalogue_id: l.service_catalogue_id || undefined,
      }));

      if (isEdit && existing) {
        // Once received, the backend only accepts our_reference/notes/due_date/
        // document_url (routers/purchase_bills.py's _SOFT_BILL_UPDATE_FIELDS) —
        // sending bill_date/bill_no/lines at all (even unchanged) gets the whole
        // PATCH rejected with 422, since the check is "was the key present",
        // not "did the value change". isLocked mirrors that exactly so a
        // received-bill edit never fails on fields the CA never touched.
        const patchPayload = isLocked
          ? {
              due_date: dueDate || undefined,
              our_reference: ourReference.trim() || undefined,
              notes: notes.trim() || undefined,
              document_url: documentUrl || undefined,
            }
          : {
              bill_date: billDate,
              due_date: dueDate || undefined,
              bill_no: billNo.trim() || undefined,
              our_reference: ourReference.trim() || undefined,
              notes: notes.trim() || undefined,
              document_url: documentUrl || undefined,
              lines: linePayload,
            };
        const upd = await apiCall(`/api/purchase-bills/${existing.id}`, "PATCH", patchPayload, token);
        if (!upd.success) throw new Error(upd.error ?? "Failed to update bill");
      } else {
        const result = await apiCall(
          "/api/purchase-bills/",
          "POST",
          {
            client_id: clientId,
            vendor_id: vendorId,
            bill_date: billDate,
            due_date: dueDate || undefined,
            bill_no: billNo.trim() || undefined,
            our_reference: ourReference.trim() || undefined,
            notes: notes.trim() || undefined,
            is_reverse_charge: isReverseCharge,
            document_url: documentUrl || undefined,
            lines: linePayload,
            currency: isForeign ? currency : undefined,
            exchange_rate: isForeign ? exchangeRate : undefined,
          },
          token,
        );
        if (!result.success) throw new Error(result.error ?? "Failed to create bill");
      }
      const label = billNo.trim() || "Purchase bill";
      onDone(isEdit ? `${label} updated` : `${label} saved as draft`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save purchase bill");
    } finally {
      setSaving(false);
    }
  }

  async function handleCancel() {
    if (await confirmLeave()) onCancel();
  }

  const busy = saving;
  const fieldErr = (msg?: string) => (attempted && msg ? <p className="mt-1 text-[10px] text-red-600">{msg}</p> : null);

  const toolbar = (
    <>
      <button onClick={handleCancel} disabled={busy} className="mr-auto text-xs px-3 py-1.5 text-[#64748B] hover:text-[#334155] disabled:opacity-50">
        Cancel
      </button>
      <button onClick={save} disabled={busy} className="text-xs px-3.5 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 inline-flex items-center gap-1.5">
        {saving && <Loader2 size={12} className="animate-spin" />} {isEdit ? "Save Changes" : "Save Draft"}
      </button>
    </>
  );

  const summary = (
    <div className="bg-white rounded-xl border border-[#F1F5F9] p-4 space-y-2 text-xs">
      <p className="font-semibold text-[#334155]">Summary{isForeign ? ` (${currency})` : ""}</p>
      <Row label="Taxable value" value={fmtAmt(totals.taxable_paise)} />
      {isInterstate ? (
        <Row label="IGST" value={fmtAmt(totals.igst_paise)} />
      ) : (
        <>
          <Row label="CGST" value={fmtAmt(totals.cgst_paise)} />
          <Row label="SGST" value={fmtAmt(totals.sgst_paise)} />
        </>
      )}
      <p className="text-[10px] text-[#94A3B8]">
        {gstAuto ? `${isInterstate ? "Interstate" : "Intra-state"} — ${isInterstate ? "IGST" : "CGST + SGST"} (CGST Act §8)` : "Pick a vendor to preview CGST/SGST vs IGST."}
      </p>
      {isReverseCharge && (
        <p className="text-[10px] text-amber-700">
          Reverse charge — the GST above is self-assessed by you (GSTR-3B 3.1(d)), not payable to the vendor.
        </p>
      )}
      <div className="flex justify-between font-semibold text-[#0F172A] border-t border-[#E2E8F0] pt-1.5 mt-1">
        <span>{isReverseCharge ? "Payable to Vendor" : "Grand Total"}{isForeign ? ` (${currency})` : ""}</span>
        <span className="font-mono">{fmtAmt(vendorTotalPaise)}</span>
      </div>
      {isForeign && rateNum > 0 && <Row label="≈ INR total" value={fmt(estBaseTotal)} muted />}
      {selectedVendor?.tds_applicable && (
        <div className="border-t border-[#F1F5F9] pt-2 mt-1 space-y-1.5">
          <Row label={`TDS §${selectedVendor.tds_section} @ ${((selectedVendor.tds_rate_bps ?? 0) / 100).toFixed(1)}%`} value={fmt(tdsPaise)} />
          <Row label="Net payable" value={fmtAmt(netPayable)} />
          {isForeign && <p className="text-[10px] text-[#94A3B8]">TDS is always deducted in ₹ per IT Act §194.</p>}
        </div>
      )}
      <p className="text-[10px] text-[#94A3B8] pt-1">
        Preview — GST and TDS are confirmed by the server on save.
      </p>
      {attempted && !validation.ok && (
        <div className="flex items-start gap-1.5 text-[10px] text-red-600 bg-red-50 rounded px-2 py-1.5">
          <AlertCircle size={12} className="mt-px flex-shrink-0" />
          <span>{validation.errors.vendor ?? validation.errors.billDate ?? validation.errors.lines ?? validation.errors.exchangeRate}</span>
        </div>
      )}
    </div>
  );

  return (
    <InvoiceWorkspaceLayout
      breadcrumbs={[
        { label: clientName || "Client", href: `/clients/${clientId}` },
        { label: "Purchases", href: `/clients/${clientId}/purchases` },
        { label: isEdit ? `Edit ${billNo || "Purchase Bill"}` : "New Purchase Bill" },
      ]}
      title={isEdit ? `Edit ${billNo || "Purchase Bill"}` : "New Purchase Bill"}
      statusPill={<span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-[#F1F5F9] text-[#64748B]">{isEdit ? (existing?.status ?? "draft").replace("_", " ") : "Draft"}</span>}
      dirtyHint={dirty ? <span className="inline-flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-amber-400" /> Unsaved changes</span> : undefined}
      toolbar={toolbar}
      summary={summary}
    >
      <div className="space-y-5">
        {/* AI Upload — create-only; re-extracting into an already-saved draft
            would silently overwrite manually-corrected fields. */}
        {isEdit ? (
          documentUrl && (
            <section className="bg-amber-50 border border-amber-100 rounded-lg p-3">
              <p className="text-[10px] text-amber-700">
                📎 Original invoice attached — retained on this bill as supporting evidence (CGST Rule 36).
              </p>
            </section>
          )
        ) : (
          <section className="bg-amber-50 border border-amber-100 rounded-lg p-3 space-y-2">
            <p className="text-xs font-medium text-amber-800 flex items-center gap-1.5"><Upload size={12} /> Upload Invoice (AI Extract)</p>
            <div className="flex items-center gap-2">
              <input type="file" accept=".pdf,.png,.jpg,.jpeg" onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)} className="text-xs text-[#475569]" />
              <button onClick={handleExtract} disabled={!uploadFile || extracting} className="text-xs px-3 py-1.5 bg-amber-600 text-white rounded-lg hover:bg-amber-700 disabled:opacity-40">
                {extracting ? "Extracting…" : "Extract"}
              </button>
            </div>
            {aiExtracted && (
              <div className="mt-1 text-[10px] text-amber-700 bg-amber-100 rounded px-2 py-1.5">
                ✓ AI extracted data pre-filled below. <strong>Review before saving.</strong>
              </div>
            )}
            {documentUrl && (
              <p className="text-[10px] text-amber-700">
                📎 Original invoice attached — retained on this bill as supporting evidence (CGST Rule 36).
              </p>
            )}
          </section>
        )}

        {/* Party + metadata */}
        <section className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <div className="col-span-2">
              <label className="block text-xs font-medium text-[#475569] mb-1">Vendor *</label>
              <VendorLookup vendors={vendors} value={vendorId} onChange={onVendorChange} ariaLabel="Vendor" disabled={isEdit} />
              {isEdit && <p className="mt-1 text-[10px] text-[#94A3B8]">Vendor can&apos;t be changed once a bill exists — it&apos;s locked to the TDS section resolved at creation.</p>}
              {fieldErr(validation.errors.vendor)}
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Vendor Invoice No.</label>
              <input value={billNo} onChange={(e) => setBillNo(e.target.value)} placeholder="INV-001" disabled={isLocked}
                className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-[#F8FAFC] disabled:text-[#94A3B8]" />
              {isLocked && <p className="mt-1 text-[10px] text-[#94A3B8]">Frozen once received.</p>}
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Our Reference</label>
              <input value={ourReference} onChange={(e) => setOurReference(e.target.value)} placeholder="Internal tracking no."
                className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Bill Date *</label>
              <input type="date" value={billDate} onChange={(e) => setBillDate(e.target.value)} disabled={isLocked}
                className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-[#F8FAFC] disabled:text-[#94A3B8]" />
              {fieldErr(validation.errors.billDate)}
              {isLocked && <p className="mt-1 text-[10px] text-[#94A3B8]">Frozen once received — issue a Debit Note to correct (CGST Act §34).</p>}
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Due Date</label>
              <input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)}
                className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div className="flex flex-col justify-end pb-1.5">
              <label className={`flex items-center gap-2 text-xs text-[#475569] ${isEdit ? "opacity-50" : "cursor-pointer"}`}>
                <input type="checkbox" checked={isReverseCharge} disabled={isEdit} onChange={(e) => setIsReverseCharge(e.target.checked)} className="rounded" />
                Reverse Charge (RCM)
              </label>
              <p className="mt-1 text-[10px] text-[#94A3B8]">
                {isEdit ? "Locked once a bill exists." : "CGST Act §9(3)/(4) — GTA, import of services, notified supplies, or purchases from an unregistered person in a specified category."}
              </p>
            </div>
            <div className="col-span-2 lg:col-span-4">
              <label className="block text-xs font-medium text-[#475569] mb-1">Notes</label>
              <textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Internal notes — not shown to the vendor" rows={2}
                className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
          </div>

          {mcActive && (
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mt-3 pt-3 border-t border-[#F1F5F9]">
              <div>
                <label className="block text-xs font-medium text-[#475569] mb-1">Currency</label>
                <select value={currency} onChange={(e) => { setCurrency(e.target.value); setExchangeRate(""); }}
                  className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
                  <option value="">INR (default)</option>
                  {currencies.filter((c) => c.code !== "INR").map((c) => (
                    <option key={c.code} value={c.code}>{c.code}{c.display_name ? ` — ${c.display_name}` : ""}</option>
                  ))}
                </select>
              </div>
              {isForeign && (
                <div>
                  <label className="block text-xs font-medium text-[#475569] mb-1">Exchange Rate *</label>
                  <input type="number" min="0" step="0.0001" value={exchangeRate} onChange={(e) => setExchangeRate(e.target.value)}
                    placeholder={`1 ${currency} = ? INR`}
                    className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-right font-mono" />
                  {fieldErr(validation.errors.exchangeRate)}
                </div>
              )}
            </div>
          )}
        </section>

        {blockedCreditHits.length > 0 && (
          <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2.5 text-xs text-amber-800">
            <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" />
            <div className="space-y-1">
              <p className="font-medium">Possible blocked ITC — review before saving (CGST Act §17(5))</p>
              {blockedCreditHits.map((h, i) => (
                <p key={i}>Line {h.lineIndex + 1} ({h.label}): {h.note}</p>
              ))}
              <p className="text-[10px] text-amber-700">This is a heuristic prompt, not a legal determination — confirm eligibility before claiming ITC.</p>
            </div>
          </div>
        )}

        {/* Line items */}
        <section className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <h2 className="text-xs font-semibold text-[#334155] mb-2">Line items</h2>
          {isLocked && (
            <p className="mb-2 text-[10px] text-[#94A3B8]">
              Frozen once received — issue a Debit Note to correct a quantity, rate, or item (CGST Act §34).
            </p>
          )}
          {/* fieldset disables every input/select/button in the table below in
              one shot, no need to thread `disabled` through each custom lookup
              component individually — native form-control disable propagates
              through any wrapper markup. */}
          <fieldset disabled={isLocked} className="border-0 p-0 m-0 min-w-0">
          <div className="overflow-x-auto">
            <table className="w-full text-xs min-w-[860px]">
              <thead>
                <tr className="border-b border-[#F1F5F9] text-[#94A3B8]">
                  <th className="pb-2 text-left font-semibold w-36">Product/Service *</th>
                  <th className="pb-2 text-left font-semibold">Description</th>
                  <th className="pb-2 text-left font-semibold w-24">HSN/SAC</th>
                  <th className="pb-2 text-left font-semibold w-28">Expense Account</th>
                  <th className="pb-2 text-right font-semibold w-20">Qty</th>
                  <th className="pb-2 text-left font-semibold w-16">Unit</th>
                  <th className="pb-2 text-right font-semibold w-24">Rate ({isForeign ? currency : "₹"})</th>
                  <th className="pb-2 text-right font-semibold w-20">GST %</th>
                  <th className="pb-2 text-right font-semibold w-24">Amount</th>
                  <th className="pb-2 w-6" />
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {lines.map((line, idx) => {
                  const g = previewBillTotals([line], isInterstate);
                  const invalid = attempted && !isValidBillLine(line) && (line.description.trim() || line.rate || line.hsn_sac);
                  return (
                    <tr key={line._k} className={invalid ? "bg-red-50/40" : undefined}>
                      <td className="py-1.5 pr-2">
                        <ServiceCataloguePicker clientId={clientId} value={line.product} onPick={(item) => onPickProduct(idx, item)} size="sm" ariaLabel={`Line ${idx + 1} product or service`} />
                        {/* HSN-based catalogue hints (see matchLinesByHsn) — only
                            relevant right after AI extraction; a manually-added
                            blank line has hsnMatches === undefined and shows nothing. */}
                        {line.hsnMatches && line.hsnMatches.length > 1 && !line.service_catalogue_id && (
                          <div className="mt-1 flex flex-wrap gap-1 items-center">
                            <span className="text-[9px] text-[#94A3B8]">HSN {line.hsn_sac} matches:</span>
                            {line.hsnMatches.map((m) => (
                              <button key={m.id} type="button" onClick={() => onPickProduct(idx, m)}
                                className="text-[9px] px-1.5 py-0.5 rounded-full bg-blue-50 text-blue-700 hover:bg-blue-100 border border-blue-200">
                                {m.name}
                              </button>
                            ))}
                          </div>
                        )}
                        {line.hsnMatches && line.hsnMatches.length === 0 && line.hsn_sac.trim() && !line.service_catalogue_id && (
                          <p className="mt-1 text-[9px] text-[#CBD5E1]">No catalogue match for HSN {line.hsn_sac}</p>
                        )}
                        {line.hsnMatches?.length === 1 && line.service_catalogue_id === line.hsnMatches[0].id && (
                          <p className="mt-1 text-[9px] text-emerald-600">✓ Auto-linked from catalogue</p>
                        )}
                      </td>
                      <td className="py-1.5 pr-2">
                        <input value={line.description} onChange={(e) => setLine(idx, { description: e.target.value })} placeholder="Item description" aria-label={`Line ${idx + 1} description`}
                          className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-xs" />
                      </td>
                      <td className="py-1.5 px-1">
                        <HsnLookup clientId={clientId} value={line.hsn_sac} onChange={(v) => setLine(idx, { hsn_sac: v })}
                          onPick={(p) => { if (p.gst_rate_bps != null) setLine(idx, { gst_rate: p.gst_rate_bps / 100 }); }}
                          size="sm" chrome="plain" placeholder="Set HSN/SAC" ariaLabel="HSN or SAC code" />
                      </td>
                      <td className="py-1.5 px-1">
                        <AccountLookup accounts={accounts} value={line.expense_account_id} onChange={(id) => setLine(idx, { expense_account_id: id })} size="sm" placeholder="— Account —" ariaLabel="Expense account" />
                      </td>
                      <td className="py-1.5 px-1">
                        <input type="number" min="0" step="0.001" value={line.qty} onChange={(e) => setLine(idx, { qty: e.target.value })} aria-label={`Line ${idx + 1} quantity`}
                          className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-right text-xs" />
                      </td>
                      <td className="py-1.5 px-1">
                        <select value={line.unit || "NOS"} onChange={(e) => setLine(idx, { unit: e.target.value })} aria-label={`Line ${idx + 1} unit`}
                          className="w-full px-1 py-1 border border-[#E2E8F0] rounded focus:outline-none text-xs">
                          {UQC_CODES.map((u) => <option key={u.code} value={u.code}>{u.code}</option>)}
                        </select>
                      </td>
                      <td className="py-1.5 px-1">
                        <input type="number" min="0" step="0.01" value={line.rate} onChange={(e) => setLine(idx, { rate: e.target.value })} placeholder="0.00" aria-label={`Line ${idx + 1} rate`}
                          className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-right text-xs" />
                      </td>
                      <td className="py-1.5 px-1">
                        <select value={line.gst_rate} onChange={(e) => setLine(idx, { gst_rate: parseFloat(e.target.value) })} aria-label={`Line ${idx + 1} GST rate`}
                          className="w-full px-1 py-1 border border-[#E2E8F0] rounded focus:outline-none text-xs">
                          {GST_RATES.map((r) => <option key={r} value={r}>{r}%</option>)}
                        </select>
                      </td>
                      <td className="py-1.5 px-2 text-right font-mono text-[#334155]">{g.grand_total_paise > 0 ? fmtAmt(g.grand_total_paise) : "—"}</td>
                      <td className="py-1.5">
                        {lines.length > 1 && (
                          <button onClick={() => removeLine(idx)} className="text-[#CBD5E1] hover:text-red-600" aria-label="Remove line">
                            <Trash2 size={13} />
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <button type="button" onClick={addLine} className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-blue-600 hover:text-blue-700 disabled:opacity-40 disabled:cursor-not-allowed">
            <Plus size={13} /> Add line
          </button>
          </fieldset>
          {fieldErr(validation.errors.lines)}
        </section>

        {error && <p className="text-xs text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{error}</p>}
      </div>
    </InvoiceWorkspaceLayout>
  );
}

function Row({ label, value, muted }: { label: string; value: string; muted?: boolean }) {
  return (
    <div className={`flex justify-between ${muted ? "text-[#94A3B8]" : "text-[#475569]"}`}>
      <span>{label}</span>
      <span className="font-mono">{value}</span>
    </div>
  );
}
