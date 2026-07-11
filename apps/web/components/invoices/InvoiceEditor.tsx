"use client";

/**
 * InvoiceEditor — the Batch 3 create/edit experience, replacing the legacy embedded
 * InvoiceForm. It composes the Batch 2 workspace shell (breadcrumbs, header, sticky
 * toolbar, two-column body + sticky summary) and reuses ALL existing infrastructure:
 * the sales-invoice create/PATCH/issue/send endpoints, the HSN/Customer/State lookups,
 * payment-term math, and the pure preview + validation domain (lib/invoices/gst).
 *
 * No business logic is duplicated: totals shown here are a preview (the backend is
 * authoritative), and Save & Issue / Save & Send chain the existing endpoints.
 */
import { useState, useEffect, useRef, useMemo } from "react";
import { Trash2, CheckCircle, Send, Loader2, AlertCircle, Plus } from "lucide-react";
import { InvoiceWorkspaceLayout } from "@/components/invoices/InvoiceWorkspaceLayout";
import { HsnLookup } from "@/components/lookups/HsnLookup";
import { ServiceCataloguePicker } from "@/components/lookups/ServiceCataloguePicker";
import type { ComboboxHandle } from "@/components/ui/combobox";
import { serviceToLine, type ServiceCatalogueItem } from "@/lib/catalogue/service";
import { UQC_CODES } from "@/lib/constants/uqc";
import { CustomerLookup } from "@/components/lookups/CustomerLookup";
import { StateLookup } from "@/components/lookups/StateLookup";
import { formatMoney } from "@/lib/services/formatting";
import { estimateBaseMinor } from "@/lib/services/currencyPreview";
import { toInvoiceLinePayload } from "@/lib/invoices/lineItemPayload";
import {
  PAYMENT_TERM_PRESETS, CUSTOM_TERM, termLabelForDays, daysForTermLabel,
} from "@/lib/sales/paymentTerms";
import { addDaysISO, diffDaysISO } from "@/lib/sales/dateMath";
import { hasChanges, useUnsavedChanges } from "@/lib/invoices/dirtyState";
import { confirmDialog } from "@/components/ui/confirm-dialog";
import { invoiceBreadcrumbs } from "@/lib/invoices/workspaceNav";
import {
  apiCall, apiGet, getAuthToken, fmt,
  GST_RATES, INDIAN_STATES, STATUS_BADGE,
  previewTotals, validateInvoiceEditor, isValidLine,
  type Customer, type InvoiceDetail, type InvoiceLine, type CurrencyOption,
} from "@/lib/invoices/shared";

type SaveAction = "draft" | "issue" | "send";

function customerStateCode(c: Customer | undefined): string {
  if (!c) return "";
  return (c.state_code || (c.gstin ? c.gstin.slice(0, 2) : "")) ?? "";
}
function stateNameForCode(code: string): string {
  if (!code) return "";
  return INDIAN_STATES.find((s) => s.code === code)?.name ?? code;
}

const EMPTY_LINE: InvoiceLine = { description: "", hsn_sac: "", qty: "1", rate: "", gst_rate: 18, unit: "" };

// A stable per-row key so React reconciles line rows by identity, not array
// index — otherwise a mid-list delete would reuse a row's DOM/caret/ref for a
// different logical line. `_k` is presentational only (ignored by the payload
// mapper and all totals/validation, which read the InvoiceLine fields).
// `product` is likewise presentational only — it just lets the row's
// Product/Service cell display the current pick; toInvoiceLinePayload
// explicitly picks fields rather than spreading, so it never reaches the API.
// `serviceCatalogueId` DOES reach the API (as service_catalogue_id) — kept
// separate from `product` so the link survives a re-edit even when `product`
// isn't rehydrated as a full object on load (see initialLines below).
type EditorLine = InvoiceLine & { _k: number; product?: ServiceCatalogueItem | null; serviceCatalogueId?: string | null };

/** existing.lines / duplicateSeed.lines are the same InvoiceDetail shape —
 * shared so the two seeding paths below can't drift apart. */
function detailLinesToEditorLines(lines: InvoiceDetail["lines"]): EditorLine[] {
  return lines.map((l, i) => ({
    description: l.description ?? "",
    hsn_sac: l.hsn_sac ?? "",
    qty: String(l.quantity ?? 1),
    rate: String((l.rate_paise ?? 0) / 100),
    gst_rate: Math.round((l.gst_rate_bps ?? 0) / 100),
    unit: l.unit ?? "",
    // Round-tripped (not just presentational `product`, which isn't
    // rehydrated here) so re-editing and resaving an invoice doesn't
    // silently drop the delete-guard link — update_invoice deletes and
    // reinserts every line from whatever gets sent back.
    serviceCatalogueId: l.service_catalogue_id ?? null,
    _k: i,
  }));
}

export function InvoiceEditor({
  clientId,
  clientName,
  clientStateCode,
  customers,
  existing,
  duplicateSeed,
  onDone,
  onCancel,
}: {
  clientId: string;
  clientName?: string;
  clientStateCode: string;
  customers: Customer[];
  existing?: InvoiceDetail | null;
  /** "Duplicate invoice" pre-fill (customer + lines + supply context only —
   * never the number, dates or payment state) for an otherwise-blank new
   * invoice. Ignored once `existing` is set (edit mode). */
  duplicateSeed?: InvoiceDetail | null;
  /** Called after a successful save with a human message (the caller navigates). */
  onDone: (message: string) => void;
  /** Called when the user cancels (the caller navigates; guarded by dirty check). */
  onCancel: () => void;
}) {
  const today = new Date().toISOString().split("T")[0];
  const isEdit = !!existing;

  const initialLines: EditorLine[] =
    existing && existing.lines.length > 0 ? detailLinesToEditorLines(existing.lines)
    : duplicateSeed && duplicateSeed.lines.length > 0 ? detailLinesToEditorLines(duplicateSeed.lines)
    : [{ ...EMPTY_LINE, _k: 0 }];

  const [customerId, setCustomerId] = useState(existing?.customer_id ?? duplicateSeed?.customer_id ?? "");
  // Fully manual (Decision: no Caflow-generated numbering scheme) — the CA
  // types it; validateInvoiceEditor checks the CGST Rule 46(b) shape and the
  // server checks per-client uniqueness (the client can't see every other
  // draft/issued number to check itself).
  const [invoiceNo, setInvoiceNo] = useState(existing?.invoice_no ?? "");
  const [invoiceDate, setInvoiceDate] = useState(existing?.invoice_date ?? today);
  const [dueDate, setDueDate] = useState(existing?.due_date ?? "");
  const [referenceNo, setReferenceNo] = useState(existing?.reference_no ?? "");
  const [creditDays, setCreditDays] = useState<string>(
    existing
      ? (existing.credit_days != null
          ? String(existing.credit_days)
          : (existing.due_date ? String(diffDaysISO(existing.invoice_date, existing.due_date) ?? "") : ""))
      : "",
  );
  const [supplyStateCode, setSupplyStateCode] = useState(existing?.supply_state_code ?? duplicateSeed?.supply_state_code ?? "");
  const [isInterstate, setIsInterstate] = useState(existing?.is_interstate ?? duplicateSeed?.is_interstate ?? false);
  const [termCustom, setTermCustom] = useState<boolean>(() => {
    if (creditDays === "") return false;
    const n = parseInt(creditDays, 10);
    return termLabelForDays(Number.isNaN(n) ? null : n) === CUSTOM_TERM;
  });
  const [notes, setNotes] = useState(existing?.notes ?? duplicateSeed?.notes ?? "");
  const [lines, setLines] = useState<EditorLine[]>(initialLines);
  const keyRef = useRef(initialLines.length); // next stable row key
  const nextKey = () => keyRef.current++;
  const [saving, setSaving] = useState<SaveAction | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempted, setAttempted] = useState(false);

  // Multi-Currency (create-only) — mirrors the legacy form.
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
      } catch {
        // Best-effort: multi-currency is optional; on failure the editor stays INR-only.
      }
    })();
    return () => { cancelled = true; };
  }, [clientId, isEdit]);

  const isForeign = currency !== "" && currency !== "INR";
  const rateNum = parseFloat(exchangeRate);

  // ── Dirty detection (Batch 2 carry-forward: real "Unsaved changes" indicator) ──
  const initialSnapshot = useRef({
    customerId: existing?.customer_id ?? duplicateSeed?.customer_id ?? "",
    invoiceNo: existing?.invoice_no ?? "",
    invoiceDate: existing?.invoice_date ?? today,
    dueDate: existing?.due_date ?? "",
    referenceNo: existing?.reference_no ?? "",
    creditDays, supplyStateCode: existing?.supply_state_code ?? duplicateSeed?.supply_state_code ?? "",
    isInterstate: existing?.is_interstate ?? duplicateSeed?.is_interstate ?? false,
    notes: existing?.notes ?? duplicateSeed?.notes ?? "",
    lines: initialLines, currency, exchangeRate,
  });
  const currentSnapshot = { customerId, invoiceNo, invoiceDate, dueDate, referenceNo, creditDays, supplyStateCode, isInterstate, notes, lines, currency, exchangeRate };
  const dirty = hasChanges(initialSnapshot.current, currentSnapshot);
  const { confirmLeave } = useUnsavedChanges(dirty && saving === null, undefined, confirmDialog);

  // ── Live preview totals + validation ────────────────────────────────────────
  const totals = useMemo(() => previewTotals(lines, isInterstate, !isForeign), [lines, isInterstate, isForeign]);
  const validation = useMemo(
    () => validateInvoiceEditor({ customerId, invoiceNo, invoiceDate, lines, isForeign, exchangeRate }),
    [customerId, invoiceNo, invoiceDate, lines, isForeign, exchangeRate],
  );
  const estimatedBasePaise = isForeign && !Number.isNaN(rateNum) && rateNum > 0 && totals.grand_total_paise > 0
    ? estimateBaseMinor(totals.grand_total_paise, rateNum)
    : null;

  function fmtAmt(minor: number): string {
    return isForeign ? formatMoney(minor, currency) : fmt(minor);
  }

  const termValue = termCustom
    ? CUSTOM_TERM
    : (creditDays === "" ? "" : termLabelForDays(Number.isNaN(parseInt(creditDays, 10)) ? null : parseInt(creditDays, 10)));
  const gstAuto = !!(clientStateCode && supplyStateCode);
  // Only show a "@ x%" on the GST head rows when every posted line shares one
  // rate — otherwise the summed amount is a blend and a single % would mislead.
  const rateSet = Array.from(new Set(lines.filter(isValidLine).map((l) => l.gst_rate)));
  const uniformRate: number | null = rateSet.length === 1 ? rateSet[0] : null;

  function deriveInterstate(supplyState: string, fallback: boolean): boolean {
    if (clientStateCode && supplyState) return clientStateCode !== supplyState;
    return fallback;
  }

  // ── Field handlers (identical semantics to the legacy form) ───────────────────
  function onCustomerChange(id: string) {
    setCustomerId(id);
    if (isEdit) return;
    const cust = customers.find((c) => c.id === id);
    if (!cust) return;
    if (cust.credit_days != null) {
      setCreditDays(String(cust.credit_days));
      setTermCustom(termLabelForDays(cust.credit_days) === CUSTOM_TERM);
      setDueDate(addDaysISO(invoiceDate, cust.credit_days));
    }
    const custState = customerStateCode(cust);
    if (custState) {
      setSupplyStateCode(custState);
      setIsInterstate((prev) => deriveInterstate(custState, prev));
    }
  }
  function onTermChange(label: string) {
    if (label === CUSTOM_TERM) { setTermCustom(true); return; }
    const d = daysForTermLabel(label);
    if (d == null) return;
    setTermCustom(false);
    setCreditDays(String(d));
    if (invoiceDate) setDueDate(addDaysISO(invoiceDate, d));
  }
  function onInvoiceDateChange(v: string) {
    setInvoiceDate(v);
    const n = parseInt(creditDays, 10);
    if (!Number.isNaN(n) && v) setDueDate(addDaysISO(v, n));
  }
  function onCreditDaysChange(v: string) {
    setCreditDays(v);
    const n = parseInt(v, 10);
    if (!Number.isNaN(n) && invoiceDate) setDueDate(addDaysISO(invoiceDate, n));
  }
  function onDueDateChange(v: string) {
    setDueDate(v);
    const n = diffDaysISO(invoiceDate, v);
    if (n != null && n >= 0) setCreditDays(String(n));
    setTermCustom(true);
  }
  function onSupplyStateChange(code: string) {
    setSupplyStateCode(code);
    setIsInterstate((prev) => deriveInterstate(code, prev));
  }

  // ── Line ops + keyboard (spreadsheet-style navigation) ────────────────────────
  const descRefs = useRef<(HTMLInputElement | null)[]>([]);
  const [focusRow, setFocusRow] = useState<number | null>(null);
  useEffect(() => {
    if (focusRow != null) { descRefs.current[focusRow]?.focus(); setFocusRow(null); }
  }, [focusRow]);

  // Product/Service is the first cell of every line (UX refinement to the
  // Final Invoice Workflow Alignment): "Add line" and Tab-off-the-last-column
  // both land here, mirroring descRefs/focusRow above.
  const productRefs = useRef<(ComboboxHandle | null)[]>([]);
  const [focusProductRow, setFocusProductRow] = useState<number | null>(null);
  useEffect(() => {
    if (focusProductRow != null) { productRefs.current[focusProductRow]?.focus(); setFocusProductRow(null); }
  }, [focusProductRow]);

  function setLine(idx: number, patch: Partial<EditorLine>) {
    setLines((prev) => prev.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
  }
  function removeLine(idx: number) {
    if (lines.length <= 1) return;
    setLines((prev) => prev.filter((_, i) => i !== idx));
  }
  // A Product/Service picked on THIS row fully pre-prices it (description,
  // HSN/SAC, GST, unit, rate — description stays editable afterwards). The
  // values are copied, not linked, so a later edit/archive of the preset
  // can't change a past invoice.
  function onPickProduct(idx: number, item: ServiceCatalogueItem) {
    setLine(idx, { ...serviceToLine(item), product: item, serviceCatalogueId: item.id });
  }
  // QuickBooks-style "Add line": appends a blank row whose FIRST field is the
  // Product/Service selector (not a free-text description) — the previous
  // "blank line" workflow (Description as the entry point) does not return.
  function addLine() {
    const newIdx = lines.length;
    setLines((prev) => [...prev, { ...EMPTY_LINE, _k: nextKey() }]);
    setFocusProductRow(newIdx);
  }
  function onLineKeyDown(e: React.KeyboardEvent, idx: number) {
    if (e.key !== "Enter" || e.shiftKey) return;
    e.preventDefault();
    // Enter moves to the next row's description if one exists. It never
    // creates a row — only "Add line" and end-of-row Tab do (see onGstKeyDown).
    if (idx < lines.length - 1) setFocusRow(idx + 1);
  }
  // Spreadsheet-style Tab: GST% is the last editable column. Tabbing off it
  // always lands on the NEXT row's Product/Service cell — creating that row
  // first if this is the last one — instead of the browser's native tab
  // order, which would otherwise hit the delete button first.
  function onGstKeyDown(e: React.KeyboardEvent, idx: number) {
    if (e.key !== "Tab" || e.shiftKey) return;
    e.preventDefault();
    const nextIdx = idx + 1;
    if (idx === lines.length - 1) {
      setLines((prev) => [...prev, { ...EMPTY_LINE, _k: nextKey() }]);
    }
    setFocusProductRow(nextIdx);
  }

  // ── Save flow: create/PATCH → (issue) → (send), reusing existing endpoints ─────
  async function save(action: SaveAction) {
    setAttempted(true);
    if (!validation.ok) {
      setError(validation.errors.customer ?? validation.errors.invoiceNo ?? validation.errors.invoiceDate ?? validation.errors.lines ?? validation.errors.exchangeRate ?? "Fix the highlighted fields.");
      return;
    }
    // Pre-check email for Save & Send so we never issue and then fail to deliver.
    const custEmail = customers.find((c) => c.id === customerId)?.email ?? null;
    if (action === "send" && !custEmail) {
      setError("This customer has no email on file. Add one, or use Save & Issue.");
      return;
    }
    const linePayload = lines.filter(isValidLine).map(toInvoiceLinePayload);
    setSaving(action);
    setError(null);
    try {
      const token = await getAuthToken();
      let invoiceId = existing?.id ?? "";
      const trimmedInvoiceNo = invoiceNo.trim();

      if (isEdit && existing) {
        const upd = await apiCall(`/api/sales-invoices/${existing.id}`, "PATCH", {
          customer_id: customerId,
          invoice_no: trimmedInvoiceNo,
          invoice_date: invoiceDate,
          due_date: dueDate || undefined,
          reference_no: referenceNo.trim() || undefined,
          credit_days: creditDays !== "" ? parseInt(creditDays, 10) : undefined,
          supply_state_code: supplyStateCode || undefined,
          notes: notes.trim() || undefined,
          is_inter_state: isInterstate,
          lines: linePayload,
        }, token);
        if (!upd.success) throw new Error(upd.error ?? "Failed to update invoice");
      } else {
        const created = await apiCall("/api/sales-invoices/", "POST", {
          client_id: clientId,
          customer_id: customerId,
          invoice_no: trimmedInvoiceNo,
          invoice_date: invoiceDate,
          due_date: dueDate || undefined,
          reference_no: referenceNo.trim() || undefined,
          credit_days: creditDays !== "" ? parseInt(creditDays, 10) : undefined,
          supply_state_code: supplyStateCode || undefined,
          is_inter_state: isInterstate,
          notes: notes.trim() || undefined,
          lines: linePayload,
          currency: isForeign ? currency : undefined,
          exchange_rate: isForeign ? exchangeRate : undefined,
        }, token);
        if (!created.success) throw new Error(created.error ?? "Failed to create invoice");
        const inv = created.data as { id: string; invoice_no: string };
        invoiceId = inv?.id ?? "";
      }

      if (action === "issue" || action === "send") {
        // CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. Posts the journal atomically; a
        // failure leaves the invoice a re-tryable draft (server guarantee).
        const iss = await apiCall(`/api/sales-invoices/${invoiceId}/issue`, "POST", undefined, token);
        if (!iss.success) throw new Error(iss.error ?? "Saved as draft, but posting failed. It remains a draft — retry.");
      }
      if (action === "send") {
        const snd = await apiCall(`/api/sales-invoices/${invoiceId}/send`, "POST", { to_email: custEmail }, token);
        if (!snd.success) {
          // The invoice IS issued — only delivery failed. Return to the list with a
          // warning rather than stranding the user on an already-issued invoice.
          onDone(`${trimmedInvoiceNo || "Invoice"} issued — email failed to send; use Send from the invoice.`);
          return;
        }
      }

      const label = trimmedInvoiceNo || "Invoice";
      onDone(
        action === "draft" ? `${label} saved as draft`
        : action === "send" ? `${label} issued and emailed`
        : `${label} issued`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save invoice");
    } finally {
      setSaving(null);
    }
  }

  async function handleCancel() {
    if (await confirmLeave()) onCancel();
  }

  const busy = saving !== null;
  const fieldErr = (msg?: string) => (attempted && msg ? <p className="mt-1 text-[10px] text-red-600">{msg}</p> : null);

  // ── Toolbar (workspace shell slot) ────────────────────────────────────────────
  const toolbar = (
    <>
      <button
        onClick={handleCancel}
        disabled={busy}
        className="mr-auto text-xs px-3 py-1.5 text-[#64748B] hover:text-[#334155] disabled:opacity-50"
      >
        Cancel
      </button>
      <button
        onClick={() => save("draft")}
        disabled={busy}
        className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#475569] disabled:opacity-50 inline-flex items-center gap-1.5"
      >
        {saving === "draft" && <Loader2 size={12} className="animate-spin" />} Save Draft
      </button>
      <button
        onClick={() => save("send")}
        disabled={busy}
        className="text-xs px-3 py-1.5 border border-emerald-200 text-emerald-700 rounded-lg hover:bg-emerald-50 disabled:opacity-50 inline-flex items-center gap-1.5"
      >
        {saving === "send" ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />} Save &amp; Send
      </button>
      <button
        onClick={() => save("issue")}
        disabled={busy}
        className="text-xs px-3.5 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 inline-flex items-center gap-1.5"
      >
        {saving === "issue" ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle size={12} />} Save &amp; Issue
      </button>
    </>
  );

  // ── Sticky summary panel ──────────────────────────────────────────────────────
  const outstanding = isEdit && existing ? totals.grand_total_paise - (existing.paid_paise ?? 0) : null;
  const summary = (
    <div className="bg-white rounded-xl border border-[#F1F5F9] p-4 space-y-2 text-xs">
      <p className="font-semibold text-[#334155]">Summary{isForeign ? ` (${currency})` : ""}</p>
      <Row label="Taxable value" value={fmtAmt(totals.taxable_paise)} />
      {isInterstate ? (
        <Row label={uniformRate != null ? `IGST @ ${uniformRate}%` : "IGST"} value={fmtAmt(totals.igst_paise)} />
      ) : (
        <>
          <Row label={uniformRate != null ? `CGST @ ${uniformRate / 2}%` : "CGST"} value={fmtAmt(totals.cgst_paise)} />
          <Row label={uniformRate != null ? `SGST @ ${uniformRate / 2}%` : "SGST"} value={fmtAmt(totals.sgst_paise)} />
        </>
      )}
      {!isForeign && totals.round_off_paise !== 0 && (
        <Row label="Round-off" value={`${totals.round_off_paise < 0 ? "-" : ""}${fmt(Math.abs(totals.round_off_paise))}`} />
      )}
      <div className="flex justify-between font-semibold text-[#0F172A] border-t border-[#E2E8F0] pt-1.5 mt-1">
        <span>Grand Total{isForeign ? ` (${currency})` : ""}</span>
        <span className="font-mono">{fmtAmt(totals.grand_total_paise)}</span>
      </div>
      {isForeign && estimatedBasePaise != null && (
        <Row label="≈ INR total" value={fmt(estimatedBasePaise)} muted />
      )}
      <div className="border-t border-[#F1F5F9] pt-2 mt-1 space-y-1.5">
        <Row label="Due date" value={dueDate || "—"} />
        {outstanding != null && <Row label="Outstanding" value={fmtAmt(outstanding)} />}
      </div>
      <p className="text-[10px] text-[#94A3B8] pt-1">
        Preview — GST, round-off and the exact total are confirmed by the server on save.
      </p>
      {attempted && !validation.ok && (
        <div className="flex items-start gap-1.5 text-[10px] text-red-600 bg-red-50 rounded px-2 py-1.5">
          <AlertCircle size={12} className="mt-px flex-shrink-0" />
          <span>{validation.errors.customer ?? validation.errors.invoiceNo ?? validation.errors.invoiceDate ?? validation.errors.lines ?? validation.errors.exchangeRate}</span>
        </div>
      )}
    </div>
  );

  return (
    <InvoiceWorkspaceLayout
      breadcrumbs={invoiceBreadcrumbs(clientId, clientName, isEdit ? `Edit ${existing?.invoice_no ?? ""}` : "New Invoice")}
      title={isEdit ? `Edit ${existing?.invoice_no ?? "Invoice"}` : "New Sales Invoice"}
      statusPill={<span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${STATUS_BADGE.draft}`}>Draft</span>}
      dirtyHint={dirty ? <span className="inline-flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-amber-400" /> Unsaved changes</span> : undefined}
      toolbar={toolbar}
      summary={summary}
    >
      <div className="space-y-5">
        {/* Party + metadata */}
        <section className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <div className="col-span-2">
              <label className="block text-xs font-medium text-[#475569] mb-1">Customer *</label>
              <CustomerLookup customers={customers} value={customerId} onChange={onCustomerChange} ariaLabel="Customer" />
              {fieldErr(validation.errors.customer)}
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Invoice Number *</label>
              <input value={invoiceNo} onChange={(e) => setInvoiceNo(e.target.value)}
                disabled={isEdit && existing?.status !== "draft"}
                placeholder="e.g. INV-0001" aria-label="Invoice number" maxLength={16}
                className="w-full px-3 py-1.5 text-xs font-mono border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-[#F8FAFC] disabled:text-[#94A3B8]" />
              {fieldErr(validation.errors.invoiceNo)}
              {isEdit && existing?.status !== "draft" && (
                <p className="mt-1 text-[10px] text-[#94A3B8]">Frozen once issued.</p>
              )}
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Invoice Date *</label>
              <input type="date" value={invoiceDate} onChange={(e) => onInvoiceDateChange(e.target.value)}
                className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
              {fieldErr(validation.errors.invoiceDate)}
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Payment Terms</label>
              <select value={termValue} onChange={(e) => onTermChange(e.target.value)}
                className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
                {termValue === "" && <option value="">— Select —</option>}
                {PAYMENT_TERM_PRESETS.map((t) => <option key={t.label} value={t.label}>{t.label}</option>)}
                <option value={CUSTOM_TERM}>Custom</option>
              </select>
              {termCustom && (
                <input type="number" min={0} value={creditDays} onChange={(e) => onCreditDaysChange(e.target.value)}
                  placeholder="Credit days" aria-label="Custom credit days"
                  className="mt-1 w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
              )}
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Due Date</label>
              <input type="date" value={dueDate ?? ""} onChange={(e) => onDueDateChange(e.target.value)}
                className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
              <p className="mt-1 text-[10px] text-[#94A3B8]">Auto-set from terms; edit for a custom date.</p>
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Supply State</label>
              <StateLookup states={INDIAN_STATES} value={supplyStateCode ?? ""} onChange={onSupplyStateChange}
                placeholder="— Select —" ariaLabel="Supply state" />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Reference</label>
              <input value={referenceNo} onChange={(e) => setReferenceNo(e.target.value)} placeholder="PO number, ref…"
                className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div className="flex flex-col justify-end pb-1.5">
              <label className="flex items-center gap-2 text-xs text-[#475569] cursor-pointer">
                <input type="checkbox" checked={isInterstate} onChange={(e) => setIsInterstate(e.target.checked)} className="rounded" />
                Interstate (IGST)
              </label>
              <p className="mt-1 text-[10px] text-[#94A3B8]">
                {gstAuto
                  ? `Auto: ${stateNameForCode(clientStateCode)} → ${stateNameForCode(supplyStateCode)} = ${isInterstate ? "IGST" : "CGST + SGST"}`
                  : "Set automatically from the supply state."}
              </p>
            </div>
          </div>

          {/* Multi-currency (create-only) */}
          {!isEdit && mcActive && (
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
          {isEdit && isForeign && (
            <div className="mt-3 bg-[#EEF2FF] border border-[#C7D2FE] rounded-lg px-3 py-2 text-[11px] text-[#4338CA]">
              Foreign-currency invoice ({currency}, rate {exchangeRate || "—"}) — currency and rate are frozen after creation.
            </div>
          )}
        </section>

        {/* Line items — Product/Service-driven (Final Invoice Workflow
            Alignment, refined). Product/Service is the FIRST cell of every
            line — there is no separate header-level "+ Add Product/Service"
            control and no separate "custom line" path: every line traces
            back to a Product/Service, existing or newly created inline, or
            is left to plain manual entry via the still-editable Description
            cell. "Add line" and end-of-row Tab both create a new row whose
            first field is the Product/Service selector, never a blank
            Description box. */}
        <section className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <h2 className="text-xs font-semibold text-[#334155] mb-2">Line items</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-xs min-w-[760px]">
              <thead>
                <tr className="border-b border-[#F1F5F9] text-[#94A3B8]">
                  <th className="pb-2 text-left font-semibold w-40">Product/Service</th>
                  <th className="pb-2 text-left font-semibold">Description</th>
                  <th className="pb-2 text-left font-semibold w-28">HSN/SAC</th>
                  <th className="pb-2 text-right font-semibold w-16">Qty</th>
                  <th className="pb-2 text-right font-semibold w-24">Rate ({isForeign ? currency : "₹"})</th>
                  <th className="pb-2 text-right font-semibold w-20">GST %</th>
                  <th className="pb-2 text-right font-semibold w-24">Amount</th>
                  <th className="pb-2 w-6" />
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {lines.map((line, idx) => {
                  const lineTaxable = Math.round((parseFloat(line.qty) || 0) * (parseFloat(line.rate) || 0) * 100);
                  const lineTotal = lineTaxable + Math.round((lineTaxable * line.gst_rate) / 100);
                  const invalid = attempted && !isValidLine(line) && (line.description.trim() || line.rate || line.hsn_sac);
                  return (
                    <tr key={line._k} className={invalid ? "bg-red-50/40" : undefined}>
                      <td className="py-1.5 pr-2">
                        <ServiceCataloguePicker
                          ref={(el) => { productRefs.current[idx] = el; }}
                          clientId={clientId}
                          value={line.product}
                          onPick={(item) => onPickProduct(idx, item)}
                          size="sm"
                          ariaLabel={`Line ${idx + 1} product or service`}
                        />
                      </td>
                      <td className="py-1.5 pr-2">
                        {/* Plain, editable — NOT a search box (Final Invoice
                            Workflow Alignment). Description is filled by
                            picking a Product/Service on this row and stays
                            freely editable afterwards; it never searches
                            history. */}
                        <input ref={(el) => { descRefs.current[idx] = el; }}
                          value={line.description} onChange={(e) => setLine(idx, { description: e.target.value })}
                          onKeyDown={(e) => onLineKeyDown(e, idx)}
                          placeholder="Description" aria-label={`Line ${idx + 1} description`}
                          className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-xs" />
                      </td>
                      <td className="py-1.5 pr-2">
                        {/* Auto-filled from the Product/Service pick; renders
                            as static text + "Change" (chrome="plain"), not
                            an always-visible dropdown — the invoice-level
                            override for this line, searching the firm's own
                            HSN/SAC Library (never writes back to the
                            Product/Service master). */}
                        <HsnLookup clientId={clientId} value={line.hsn_sac} onChange={(v) => setLine(idx, { hsn_sac: v })}
                          onPick={(p) => {
                            const patch: Partial<InvoiceLine> = {};
                            if (p.gst_rate_bps != null) patch.gst_rate = Math.round(p.gst_rate_bps / 100);
                            if (p.uqc) patch.unit = p.uqc;
                            setLine(idx, patch);
                          }}
                          size="sm" chrome="plain" placeholder="Set HSN/SAC" ariaLabel="HSN or SAC code" />
                      </td>
                      <td className="py-1.5 pr-2">
                        {/* Unit (UQC) only for goods — CGST Rule 46(h) requires
                            it for goods lines, not services. `line.product`
                            is only populated by a pick THIS session (existing
                            lines aren't rehydrated with the full product), so
                            a saved good line is recognised by already having
                            a unit value once one has been set. */}
                        <div className="flex items-center gap-1">
                          <input type="number" min="0" step="0.001" value={line.qty} onChange={(e) => setLine(idx, { qty: e.target.value })}
                            onKeyDown={(e) => onLineKeyDown(e, idx)} aria-label={`Line ${idx + 1} quantity`}
                            className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-right text-xs" />
                          {(line.product?.kind === "good" || !!line.unit) && (
                            <select value={line.unit} onChange={(e) => setLine(idx, { unit: e.target.value })}
                              aria-label={`Line ${idx + 1} unit`}
                              className="shrink-0 w-16 px-1 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-[10px] text-[#64748B]">
                              <option value="">Unit</option>
                              {UQC_CODES.map((u) => <option key={u.code} value={u.code}>{u.code}</option>)}
                            </select>
                          )}
                        </div>
                      </td>
                      <td className="py-1.5 pr-2">
                        <input type="number" min="0" step="0.01" value={line.rate} onChange={(e) => setLine(idx, { rate: e.target.value })}
                          onKeyDown={(e) => onLineKeyDown(e, idx)} placeholder="0.00" aria-label={`Line ${idx + 1} rate`}
                          className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-right text-xs" />
                      </td>
                      <td className="py-1.5 pr-2">
                        {/* Last editable column: spreadsheet-style Tab here
                            always lands on the NEXT row's Product/Service
                            cell, creating that row first if this is the last
                            one (see onGstKeyDown). */}
                        <select value={line.gst_rate} onChange={(e) => setLine(idx, { gst_rate: parseInt(e.target.value) })}
                          onKeyDown={(e) => onGstKeyDown(e, idx)}
                          aria-label={`Line ${idx + 1} GST rate`}
                          className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-xs">
                          {GST_RATES.map((r) => <option key={r} value={r}>{r}%</option>)}
                        </select>
                      </td>
                      <td className="py-1.5 px-2 text-right font-mono text-[#334155]">{lineTotal > 0 ? fmtAmt(lineTotal) : "—"}</td>
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
          <button
            type="button"
            onClick={addLine}
            className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-blue-600 hover:text-blue-700"
          >
            <Plus size={13} /> Add line
          </button>
          {fieldErr(validation.errors.lines)}
        </section>

        {/* Notes */}
        <section className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <label className="block text-xs font-medium text-[#475569] mb-1">Notes</label>
          <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2}
            placeholder="Optional notes shown on the invoice (terms, PO reference…)"
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
          {isEdit && (
            <p className="mt-2 text-[10px] text-[#94A3B8]">
              Editing a draft. GST is recomputed by the backend on save; only drafts are editable.
            </p>
          )}
        </section>

        {error && (
          <p className="text-xs text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{error}</p>
        )}
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
