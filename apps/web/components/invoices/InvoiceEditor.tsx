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
import { Plus, Trash2, CheckCircle, Send, Loader2, AlertCircle } from "lucide-react";
import { InvoiceWorkspaceLayout } from "@/components/invoices/InvoiceWorkspaceLayout";
import { HsnLookup } from "@/components/lookups/HsnLookup";
import { ServiceCataloguePicker } from "@/components/lookups/ServiceCataloguePicker";
import { serviceToLine, type ServiceCatalogueItem } from "@/lib/catalogue/service";
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

const EMPTY_LINE: InvoiceLine = { description: "", hsn_sac: "", qty: "1", rate: "", gst_rate: 18 };

export function InvoiceEditor({
  clientId,
  clientName,
  clientStateCode,
  customers,
  existing,
  onDone,
  onCancel,
}: {
  clientId: string;
  clientName?: string;
  clientStateCode: string;
  customers: Customer[];
  existing?: InvoiceDetail | null;
  /** Called after a successful save with a human message (the caller navigates). */
  onDone: (message: string) => void;
  /** Called when the user cancels (the caller navigates; guarded by dirty check). */
  onCancel: () => void;
}) {
  const today = new Date().toISOString().split("T")[0];
  const isEdit = !!existing;

  const initialLines: InvoiceLine[] = existing && existing.lines.length > 0
    ? existing.lines.map((l) => ({
        description: l.description ?? "",
        hsn_sac: l.hsn_sac ?? "",
        qty: String(l.quantity ?? 1),
        rate: String((l.rate_paise ?? 0) / 100),
        gst_rate: Math.round((l.gst_rate_bps ?? 0) / 100),
      }))
    : [{ ...EMPTY_LINE }];

  const [customerId, setCustomerId] = useState(existing?.customer_id ?? "");
  const [invoiceDate, setInvoiceDate] = useState(existing?.invoice_date ?? today);
  const [dueDate, setDueDate] = useState(existing?.due_date ?? "");
  const [creditDays, setCreditDays] = useState<string>(
    existing
      ? (existing.credit_days != null
          ? String(existing.credit_days)
          : (existing.due_date ? String(diffDaysISO(existing.invoice_date, existing.due_date) ?? "") : ""))
      : "",
  );
  const [supplyStateCode, setSupplyStateCode] = useState(existing?.supply_state_code ?? "");
  const [isInterstate, setIsInterstate] = useState(existing?.is_interstate ?? false);
  const [termCustom, setTermCustom] = useState<boolean>(() => {
    if (creditDays === "") return false;
    const n = parseInt(creditDays, 10);
    return termLabelForDays(Number.isNaN(n) ? null : n) === CUSTOM_TERM;
  });
  const [notes, setNotes] = useState(existing?.notes ?? "");
  const [lines, setLines] = useState<InvoiceLine[]>(initialLines);
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
  }, [clientId, isEdit]);

  const isForeign = currency !== "" && currency !== "INR";
  const rateNum = parseFloat(exchangeRate);

  // ── Dirty detection (Batch 2 carry-forward: real "Unsaved changes" indicator) ──
  const initialSnapshot = useRef({
    customerId: existing?.customer_id ?? "",
    invoiceDate: existing?.invoice_date ?? today,
    dueDate: existing?.due_date ?? "",
    creditDays, supplyStateCode: existing?.supply_state_code ?? "",
    isInterstate: existing?.is_interstate ?? false,
    notes: existing?.notes ?? "",
    lines: initialLines, currency, exchangeRate,
  });
  const currentSnapshot = { customerId, invoiceDate, dueDate, creditDays, supplyStateCode, isInterstate, notes, lines, currency, exchangeRate };
  const dirty = hasChanges(initialSnapshot.current, currentSnapshot);
  const { confirmLeave } = useUnsavedChanges(dirty && saving === null);

  // ── Live preview totals + validation ────────────────────────────────────────
  const totals = useMemo(() => previewTotals(lines, isInterstate, !isForeign), [lines, isInterstate, isForeign]);
  const validation = useMemo(
    () => validateInvoiceEditor({ customerId, invoiceDate, lines, isForeign, exchangeRate }),
    [customerId, invoiceDate, lines, isForeign, exchangeRate],
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
  const firstRate = lines[0]?.gst_rate ?? 0;

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

  // ── Line ops + keyboard (Enter adds/advances a row) ───────────────────────────
  const descRefs = useRef<(HTMLInputElement | null)[]>([]);
  const [focusRow, setFocusRow] = useState<number | null>(null);
  useEffect(() => {
    if (focusRow != null) { descRefs.current[focusRow]?.focus(); setFocusRow(null); }
  }, [focusRow]);

  function setLine(idx: number, patch: Partial<InvoiceLine>) {
    setLines((prev) => prev.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
  }
  function addLine() {
    setLines((prev) => [...prev, { ...EMPTY_LINE }]);
    setFocusRow(lines.length);
  }
  function removeLine(idx: number) {
    if (lines.length <= 1) return;
    setLines((prev) => prev.filter((_, i) => i !== idx));
  }
  // Drop a fully pre-priced line from a catalogue preset. Fills the first blank
  // line (so the initial empty row is used before appending), else appends. The
  // values are copied and remain fully editable — journal posting is untouched.
  function addFromService(item: ServiceCatalogueItem) {
    const patch = serviceToLine(item);
    setLines((prev) => {
      const emptyIdx = prev.findIndex(
        (l) => !l.description.trim() && !l.hsn_sac.trim() && !l.rate.trim(),
      );
      if (emptyIdx >= 0) return prev.map((l, i) => (i === emptyIdx ? { ...l, ...patch } : l));
      return [...prev, { ...EMPTY_LINE, ...patch }];
    });
  }
  function onLineKeyDown(e: React.KeyboardEvent, idx: number) {
    if (e.key !== "Enter" || e.shiftKey) return;
    e.preventDefault();
    if (idx === lines.length - 1) addLine();
    else setFocusRow(idx + 1);
  }

  // ── Save flow: create/PATCH → (issue) → (send), reusing existing endpoints ─────
  async function save(action: SaveAction) {
    setAttempted(true);
    if (!validation.ok) {
      setError(validation.errors.customer ?? validation.errors.invoiceDate ?? validation.errors.lines ?? validation.errors.exchangeRate ?? "Fix the highlighted fields.");
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
      let invoiceNo = existing?.invoice_no ?? "";

      if (isEdit && existing) {
        const upd = await apiCall(`/api/sales-invoices/${existing.id}`, "PATCH", {
          customer_id: customerId,
          invoice_date: invoiceDate,
          due_date: dueDate || undefined,
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
          invoice_date: invoiceDate,
          due_date: dueDate || undefined,
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
        invoiceNo = inv?.invoice_no ?? "";
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
          onDone(`${invoiceNo || "Invoice"} issued — email failed to send; use Send from the invoice.`);
          return;
        }
      }

      const label = invoiceNo || "Invoice";
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

  function handleCancel() {
    if (confirmLeave()) onCancel();
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
        <Row label={`IGST @ ${firstRate}%`} value={fmtAmt(totals.igst_paise)} />
      ) : (
        <>
          <Row label={`CGST @ ${firstRate / 2}%`} value={fmtAmt(totals.cgst_paise)} />
          <Row label={`SGST @ ${firstRate / 2}%`} value={fmtAmt(totals.sgst_paise)} />
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
          <span>{validation.errors.customer ?? validation.errors.invoiceDate ?? validation.errors.lines ?? validation.errors.exchangeRate}</span>
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

        {/* Line items */}
        <section className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <div className="flex items-center justify-between gap-3 mb-2">
            <h2 className="text-xs font-semibold text-[#334155] flex-shrink-0">Line items</h2>
            <div className="flex items-center gap-3">
              <span className="text-[10px] text-[#94A3B8] hidden sm:inline">Enter adds a row</span>
              <div className="w-48">
                <ServiceCataloguePicker onPick={addFromService} ariaLabel="Add a line from the service catalogue" />
              </div>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs min-w-[640px]">
              <thead>
                <tr className="border-b border-[#F1F5F9] text-[#94A3B8]">
                  <th className="pb-2 text-left font-semibold">Description</th>
                  <th className="pb-2 text-left font-semibold w-32">HSN/SAC</th>
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
                    <tr key={idx} className={invalid ? "bg-red-50/40" : undefined}>
                      <td className="py-1.5 pr-2">
                        <input ref={(el) => { descRefs.current[idx] = el; }}
                          value={line.description} onChange={(e) => setLine(idx, { description: e.target.value })}
                          onKeyDown={(e) => onLineKeyDown(e, idx)} placeholder="Item / service description"
                          className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-xs" />
                      </td>
                      <td className="py-1.5 pr-2">
                        <HsnLookup clientId={clientId} value={line.hsn_sac} onChange={(v) => setLine(idx, { hsn_sac: v })}
                          onPick={(p) => { if (p.gst_rate_bps != null) setLine(idx, { gst_rate: Math.round(p.gst_rate_bps / 100) }); }}
                          description={line.description} size="sm" ariaLabel="HSN or SAC code" />
                      </td>
                      <td className="py-1.5 pr-2">
                        <input type="number" min="0" step="0.001" value={line.qty} onChange={(e) => setLine(idx, { qty: e.target.value })}
                          onKeyDown={(e) => onLineKeyDown(e, idx)}
                          className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-right text-xs" />
                      </td>
                      <td className="py-1.5 pr-2">
                        <input type="number" min="0" step="0.01" value={line.rate} onChange={(e) => setLine(idx, { rate: e.target.value })}
                          onKeyDown={(e) => onLineKeyDown(e, idx)} placeholder="0.00"
                          className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-right text-xs" />
                      </td>
                      <td className="py-1.5 pr-2">
                        <select value={line.gst_rate} onChange={(e) => setLine(idx, { gst_rate: parseInt(e.target.value) })}
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
          <button onClick={addLine} className="mt-2 text-xs text-blue-600 hover:underline flex items-center gap-1">
            <Plus size={12} /> Add line
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
