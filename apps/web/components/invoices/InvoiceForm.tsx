"use client";

/**
 * InvoiceForm — create/edit a draft sales invoice. Extracted verbatim from the
 * Sales page (Batch 2) so the new /invoices/new and /invoices/[id]/edit routes and
 * the Sales list reuse ONE component. Behaviour is unchanged; the line-item grid,
 * autofill and Save & Issue redesign are deferred to later batches.
 */
import { useState, useEffect } from "react";
import { Plus, X } from "lucide-react";
import { HsnLookup } from "@/components/lookups/HsnLookup";
import { CustomerLookup } from "@/components/lookups/CustomerLookup";
import { StateLookup } from "@/components/lookups/StateLookup";
import { formatMoney } from "@/lib/services/formatting";
import { estimateBaseMinor } from "@/lib/services/currencyPreview";
import { toInvoiceLinePayload } from "@/lib/invoices/lineItemPayload";
import {
  PAYMENT_TERM_PRESETS, CUSTOM_TERM, termLabelForDays, daysForTermLabel,
} from "@/lib/sales/paymentTerms";
import { addDaysISO, diffDaysISO } from "@/lib/sales/dateMath";
import {
  apiCall, apiGet, getAuthToken, fmt, computeGst, INDIAN_STATES, GST_RATES,
  type Customer, type InvoiceDetail, type InvoiceLine, type CurrencyOption,
} from "@/lib/invoices/shared";

function customerStateCode(c: Customer | undefined): string {
  if (!c) return "";
  return (c.state_code || (c.gstin ? c.gstin.slice(0, 2) : "")) ?? "";
}
/** Human-readable state name for a 2-digit GST state code (falls back to the code). */
function stateNameForCode(code: string): string {
  if (!code) return "";
  return INDIAN_STATES.find((s) => s.code === code)?.name ?? code;
}

export function InvoiceForm({
  clientId,
  clientStateCode,
  customers,
  existing,
  onSaved,
  onCancel,
}: {
  clientId: string;
  /** The selling client's own GST state code — used to auto-determine interstate. */
  clientStateCode: string;
  customers: Customer[];
  existing?: InvoiceDetail | null;
  onSaved: () => void;
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
    : [{ description: "", hsn_sac: "", qty: "1", rate: "", gst_rate: 18 }];

  const [customerId, setCustomerId] = useState(existing?.customer_id ?? "");
  const [invoiceDate, setInvoiceDate] = useState(existing?.invoice_date ?? today);
  const [dueDate, setDueDate] = useState(existing?.due_date ?? "");
  // Credit Days drives the default Due Date. For a NEW invoice it is seeded from
  // the selected customer's credit_days; on EDIT we keep the invoice's own stored
  // terms (snapshot) so existing invoices never shift.
  const [creditDays, setCreditDays] = useState<string>(
    existing
      ? (existing.credit_days != null
          ? String(existing.credit_days)
          : (existing.due_date ? String(diffDaysISO(existing.invoice_date, existing.due_date) ?? "") : ""))
      : "",
  );
  const [supplyStateCode, setSupplyStateCode] = useState(existing?.supply_state_code ?? "");
  const [isInterstate, setIsInterstate] = useState(existing?.is_interstate ?? false);
  // Payment Terms is a label over creditDays. "Custom" is sticky: it stays Custom
  // even if the day count happens to equal a preset (e.g. a hand-picked due date).
  const [termCustom, setTermCustom] = useState<boolean>(() => {
    if (creditDays === "") return false;
    const n = parseInt(creditDays, 10);
    return termLabelForDays(Number.isNaN(n) ? null : n) === CUSTOM_TERM;
  });
  const [notes, setNotes] = useState(existing?.notes ?? "");
  const [lines, setLines] = useState<InvoiceLine[]>(initialLines);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Multi-Currency (Phase 3 backend already ships this; UI wired up here).
  // Currency is create-only — SalesInvoiceUpdateIn has no currency/exchange_rate
  // field, so an existing invoice's currency can never change; on edit we just
  // display it (from `existing`) instead of re-fetching the policy/master.
  const [currency, setCurrency] = useState(
    isEdit && existing?.txn_currency && existing.txn_currency !== "INR" ? existing.txn_currency : ""
  );
  const [exchangeRate, setExchangeRate] = useState(
    isEdit && existing?.exchange_rate ? String(existing.exchange_rate) : ""
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

  const gst = computeGst(lines, isInterstate);

  // Rough client-side preview only — deliberately not the authoritative figure.
  // The backend converts + rounds each GST component independently (Decimal
  // HALF_UP) and sums those, so it will not always equal this single
  // multiply-the-total shortcut to the last paisa; the real total comes back
  // in the save response.
  const estimatedBasePaise = isForeign && !Number.isNaN(rateNum) && rateNum > 0 && gst.total_paise > 0
    ? estimateBaseMinor(gst.total_paise, rateNum)
    : null;

  // Line/GST-preview amounts are in the invoice's own currency's minor units
  // once foreign — fmt() always renders via formatPaise (₹), so route foreign
  // amounts through formatMoney(minor, currency) instead.
  function fmtAmt(minor: number): string {
    return isForeign ? formatMoney(minor, currency) : fmt(minor);
  }

  const termValue = (() => {
    if (termCustom) return CUSTOM_TERM;
    if (creditDays === "") return "";
    const n = parseInt(creditDays, 10);
    return termLabelForDays(Number.isNaN(n) ? null : n);
  })();
  // Did we auto-derive interstate from known states (vs. leaving it manual)?
  const gstAuto = !!(clientStateCode && supplyStateCode);

  // Auto-determine interstate from the seller's state vs the place of supply
  // (CGST Act §8 / IGST Act §7). Returns the prior value when either side is
  // unknown so we never override a deliberate choice with a guess.
  function deriveInterstate(supplyState: string, fallback: boolean): boolean {
    if (clientStateCode && supplyState) return clientStateCode !== supplyState;
    return fallback;
  }

  // Selecting a customer pulls in everything already known: payment terms + due
  // date (default), supply state, and GST treatment. New invoices only — editing
  // a draft must keep its own snapshot so historical invoices never shift.
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
    setDueDate(v); // manual override → a custom due date
    const n = diffDaysISO(invoiceDate, v);
    if (n != null && n >= 0) setCreditDays(String(n));
    setTermCustom(true);
  }
  function onSupplyStateChange(code: string) {
    setSupplyStateCode(code);
    setIsInterstate((prev) => deriveInterstate(code, prev));
  }

  function setLine(idx: number, patch: Partial<InvoiceLine>) {
    setLines((prev) => prev.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
  }
  function addLine() {
    setLines((prev) => [...prev, { description: "", hsn_sac: "", qty: "1", rate: "", gst_rate: 18 }]);
  }
  function removeLine(idx: number) {
    if (lines.length <= 1) return;
    setLines((prev) => prev.filter((_, i) => i !== idx));
  }

  async function handleSave() {
    if (!customerId) { setError("Select a customer"); return; }
    if (!invoiceDate) { setError("Invoice date required"); return; }
    const validLines = lines.filter((l) => l.description.trim() && parseFloat(l.rate) > 0);
    if (validLines.length === 0) { setError("Add at least one line with description and rate"); return; }
    if (!isEdit && isForeign && (!exchangeRate.trim() || !(rateNum > 0))) {
      setError(`Enter a valid exchange rate for ${currency} → INR`);
      return;
    }

    const linePayload = validLines.map(toInvoiceLinePayload);

    setSaving(true); setError(null);
    try {
      const token = await getAuthToken();
      let result;
      if (isEdit && existing) {
        // Update the existing draft in place (PATCH) — never creates a new invoice.
        result = await apiCall(
          `/api/sales-invoices/${existing.id}`,
          "PATCH",
          {
            customer_id: customerId,
            invoice_date: invoiceDate,
            due_date: dueDate || undefined,
            credit_days: creditDays !== "" ? parseInt(creditDays, 10) : undefined,
            supply_state_code: supplyStateCode || undefined,
            notes: notes.trim() || undefined,
            is_inter_state: isInterstate,
            lines: linePayload,
          },
          token
        );
        if (!result.success) throw new Error(result.error ?? "Failed to update invoice");
      } else {
        result = await apiCall(
          "/api/sales-invoices/",
          "POST",
          {
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
          },
          token
        );
        if (!result.success) throw new Error(result.error ?? "Failed to create invoice");
      }
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save invoice");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="bg-white rounded-xl border border-[#F1F5F9] p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-[#0F172A]">
          {isEdit ? `Edit Draft Invoice ${existing?.invoice_no ?? ""}` : "New Sales Invoice"}
        </h3>
        <button onClick={onCancel} className="text-[#94A3B8] hover:text-[#475569]"><X size={16} /></button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="col-span-2">
          <label className="block text-xs font-medium text-[#475569] mb-1">Customer *</label>
          <CustomerLookup
            customers={customers}
            value={customerId}
            onChange={onCustomerChange}
            ariaLabel="Customer"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">Invoice Date *</label>
          <input
            type="date"
            value={invoiceDate}
            onChange={(e) => onInvoiceDateChange(e.target.value)}
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">Payment Terms</label>
          <select
            value={termValue}
            onChange={(e) => onTermChange(e.target.value)}
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {termValue === "" && <option value="">— Select —</option>}
            {PAYMENT_TERM_PRESETS.map((t) => (
              <option key={t.label} value={t.label}>{t.label}</option>
            ))}
            <option value={CUSTOM_TERM}>Custom</option>
          </select>
          {termCustom && (
            <input
              type="number"
              min={0}
              value={creditDays}
              onChange={(e) => onCreditDaysChange(e.target.value)}
              placeholder="Credit days"
              aria-label="Custom credit days"
              className="mt-1 w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          )}
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">Due Date</label>
          <input
            type="date"
            value={dueDate ?? ""}
            onChange={(e) => onDueDateChange(e.target.value)}
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <p className="mt-1 text-[10px] text-[#94A3B8]">Auto-set from payment terms; edit for a custom due date.</p>
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">Supply State</label>
          <StateLookup
            states={INDIAN_STATES}
            value={supplyStateCode ?? ""}
            onChange={onSupplyStateChange}
            placeholder="— Select —"
            ariaLabel="Supply state"
          />
        </div>
        <div className="flex flex-col justify-end pb-1.5">
          <label className="flex items-center gap-2 text-xs text-[#475569] cursor-pointer">
            <input
              type="checkbox"
              checked={isInterstate}
              onChange={(e) => setIsInterstate(e.target.checked)}
              className="rounded"
            />
            Interstate supply (IGST)
          </label>
          {gstAuto ? (
            <p className="mt-1 text-[10px] text-[#94A3B8]">
              Auto: {stateNameForCode(clientStateCode)} → {stateNameForCode(supplyStateCode)} ={" "}
              {isInterstate ? "IGST" : "CGST + SGST"}
            </p>
          ) : (
            <p className="mt-1 text-[10px] text-[#94A3B8]">Set automatically from the supply state.</p>
          )}
        </div>
      </div>

      {/* Multi-Currency (Phase 3 backend, UI added here) — create-only: the
          selector only ever appears while creating a new invoice. An existing
          invoice's currency is fixed (SalesInvoiceUpdateIn has no currency
          field) and shown as a read-only strip below instead. */}
      {!isEdit && mcActive && (
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
                  {estimatedBasePaise != null ? `≈ ${fmt(estimatedBasePaise)}` : "— enter a rate to preview —"}
                </span>
                <p className="mt-1 text-[10px] text-[#94A3B8]">Estimate only — the exact INR total is confirmed on save.</p>
              </div>
            </>
          )}
        </div>
      )}
      {isEdit && isForeign && (
        <div className="bg-[#EEF2FF] border border-[#C7D2FE] rounded-lg px-3 py-2 text-xs text-[#4338CA] flex items-center gap-2">
          <span className="inline-flex items-center rounded-full bg-white px-2 py-0.5 text-[10px] font-semibold text-[#4338CA] border border-[#C7D2FE]">
            {currency}
          </span>
          Foreign-currency invoice — rate {exchangeRate || "—"}{existing?.rate_overridden ? " (manual)" : ""}.
          Currency and rate are frozen and can&apos;t be changed after creation.
        </div>
      )}

      {/* Lines */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-[#F1F5F9] text-[#94A3B8]">
              <th className="pb-2 text-left font-semibold">Description</th>
              <th className="pb-2 text-left font-semibold w-32">HSN/SAC</th>
              <th className="pb-2 text-right font-semibold w-16">Qty</th>
              <th className="pb-2 text-right font-semibold w-24">Rate ({isForeign ? currency : "₹"})</th>
              <th className="pb-2 text-right font-semibold w-20">GST %</th>
              <th className="pb-2 text-right font-semibold w-24">Amount{isForeign ? ` (${currency})` : ""}</th>
              <th className="pb-2 w-6" />
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F8FAFC]">
            {lines.map((line, idx) => {
              const lineTaxable = Math.round((parseFloat(line.qty) || 0) * (parseFloat(line.rate) || 0) * 100);
              const lineTotal = lineTaxable + Math.round((lineTaxable * line.gst_rate) / 100);
              return (
                <tr key={idx}>
                  <td className="py-1.5 pr-2">
                    <input
                      value={line.description}
                      onChange={(e) => setLine(idx, { description: e.target.value })}
                      placeholder="Item / service description"
                      className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-xs"
                    />
                  </td>
                  <td className="py-1.5 pr-2">
                    <HsnLookup
                      clientId={clientId}
                      value={line.hsn_sac}
                      onChange={(v) => setLine(idx, { hsn_sac: v })}
                      onPick={(p) => { if (p.gst_rate_bps != null) setLine(idx, { gst_rate: Math.round(p.gst_rate_bps / 100) }); }}
                      description={line.description}
                      size="sm"
                      ariaLabel="HSN or SAC code"
                    />
                  </td>
                  <td className="py-1.5 pr-2">
                    <input
                      type="number"
                      min="0"
                      step="0.001"
                      value={line.qty}
                      onChange={(e) => setLine(idx, { qty: e.target.value })}
                      className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-right text-xs"
                    />
                  </td>
                  <td className="py-1.5 pr-2">
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={line.rate}
                      onChange={(e) => setLine(idx, { rate: e.target.value })}
                      placeholder="0.00"
                      className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-right text-xs"
                    />
                  </td>
                  <td className="py-1.5 pr-2">
                    <select
                      value={line.gst_rate}
                      onChange={(e) => setLine(idx, { gst_rate: parseInt(e.target.value) })}
                      className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-xs"
                    >
                      {GST_RATES.map((r) => <option key={r} value={r}>{r}%</option>)}
                    </select>
                  </td>
                  <td className="py-1.5 px-2 text-right font-mono text-[#334155]">
                    {lineTotal > 0 ? fmtAmt(lineTotal) : "—"}
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
      <button
        onClick={addLine}
        className="text-xs text-blue-600 hover:underline flex items-center gap-1"
      >
        <Plus size={12} /> Add line
      </button>

      {/* Notes */}
      <div>
        <label className="block text-xs font-medium text-[#475569] mb-1">Notes</label>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={2}
          placeholder="Optional notes shown on the invoice (terms, PO reference…)"
          className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      {/* GST Preview */}
      {gst.taxable_paise > 0 && (
        <div className="bg-[#F8FAFC] rounded-lg p-3 text-xs space-y-1">
          <p className="font-semibold text-[#334155] mb-2">GST Computation{isForeign ? ` (${currency})` : ""}</p>
          <div className="flex justify-between text-[#475569]">
            <span>Taxable Value</span>
            <span className="font-mono">{fmtAmt(gst.taxable_paise)}</span>
          </div>
          {isInterstate ? (
            <div className="flex justify-between text-[#475569]">
              <span>IGST @ {lines[0]?.gst_rate ?? 0}%</span>
              <span className="font-mono">{fmtAmt(gst.igst_paise)}</span>
            </div>
          ) : (
            <>
              <div className="flex justify-between text-[#475569]">
                <span>CGST @ {(lines[0]?.gst_rate ?? 0) / 2}%</span>
                <span className="font-mono">{fmtAmt(gst.cgst_paise)}</span>
              </div>
              <div className="flex justify-between text-[#475569]">
                <span>SGST @ {(lines[0]?.gst_rate ?? 0) / 2}%</span>
                <span className="font-mono">{fmtAmt(gst.sgst_paise)}</span>
              </div>
            </>
          )}
          <div className="flex justify-between font-semibold text-[#0F172A] border-t border-[#E2E8F0] pt-1 mt-1">
            <span>Total Invoice Amount{isForeign ? ` (${currency})` : ""}</span>
            <span className="font-mono">{fmtAmt(gst.total_paise)}</span>
          </div>
          {isForeign && estimatedBasePaise != null && (
            <div className="flex justify-between text-[#94A3B8] pt-1">
              <span>≈ Estimated INR total</span>
              <span className="font-mono">{fmt(estimatedBasePaise)}</span>
            </div>
          )}
        </div>
      )}

      {isEdit && (
        <p className="text-[10px] text-[#94A3B8]">
          Editing a draft. GST is recomputed by the backend on save. Only drafts are editable —
          issued, paid and cancelled invoices are locked.
        </p>
      )}

      {error && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}
      <div className="flex gap-3 justify-end pt-1">
        <button onClick={onCancel} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">
          Cancel
        </button>
        <button
          onClick={handleSave}
          disabled={saving}
          className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? "Saving…" : isEdit ? "Update Invoice" : "Save Invoice"}
        </button>
      </div>
    </div>
  );
}
