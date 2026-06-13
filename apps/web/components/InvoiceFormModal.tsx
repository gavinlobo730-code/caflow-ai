"use client";

import { useState, useEffect, FormEvent } from "react";
import { X, Plus, Trash2 } from "lucide-react";
import type { Client } from "@/lib/types";
import { computeInvoiceTotals } from "@/lib/data/transactions";
import type { TransactionLine, CreateInvoiceInput, SupplyType, InvoiceType } from "@/lib/data/transactions";

const GST_RATES = [0, 5, 12, 18, 28];

const SUPPLY_TYPES: { value: SupplyType; label: string }[] = [
  { value: "taxable",    label: "Taxable" },
  { value: "nil_rated",  label: "Nil Rated (0% — statutory)" },
  { value: "exempt",     label: "Exempt (no GST)" },
  { value: "zero_rated", label: "Zero Rated (exports / SEZ)" },
  { value: "non_gst",    label: "Non-GST Supply" },
];

const INVOICE_TYPES: { value: InvoiceType; label: string }[] = [
  { value: "Regular",              label: "Regular" },
  { value: "SEZ_with_payment",     label: "SEZ with Payment of Tax" },
  { value: "SEZ_without_payment",  label: "SEZ without Payment of Tax" },
  { value: "Deemed_export",        label: "Deemed Export" },
];
const TDS_SECTIONS = [
  { section: "194C", label: "194C — Contractor (1%/2%)", rate: 2 },
  { section: "194J", label: "194J — Professional (10%)", rate: 10 },
  { section: "194I", label: "194I — Rent (10%)", rate: 10 },
  { section: "194H", label: "194H — Commission (5%)", rate: 5 },
  { section: "194A", label: "194A — Interest (10%)", rate: 10 },
];

const STATES = [
  { code: "01", name: "J&K" }, { code: "03", name: "Punjab" }, { code: "04", name: "Chandigarh" },
  { code: "06", name: "Haryana" }, { code: "07", name: "Delhi" }, { code: "08", name: "Rajasthan" },
  { code: "09", name: "Uttar Pradesh" }, { code: "10", name: "Bihar" },
  { code: "19", name: "West Bengal" }, { code: "20", name: "Jharkhand" },
  { code: "21", name: "Odisha" }, { code: "22", name: "Chhattisgarh" },
  { code: "23", name: "Madhya Pradesh" }, { code: "24", name: "Gujarat" },
  { code: "27", name: "Maharashtra" }, { code: "29", name: "Karnataka" },
  { code: "30", name: "Goa" }, { code: "32", name: "Kerala" },
  { code: "33", name: "Tamil Nadu" }, { code: "36", name: "Telangana" },
  { code: "37", name: "Andhra Pradesh" },
];

function formatPaise(p: number) {
  return "₹" + (p / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 });
}

const EMPTY_LINE: TransactionLine = {
  description: "", hsn_sac_code: "", quantity: 1, unit: "NOS",
  rate_paise: 0, taxable_paise: 0, gst_rate: 18,
  cgst_paise: 0, sgst_paise: 0, igst_paise: 0, total_paise: 0,
};

interface Props {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  clients: Client[];
  type: "sales_invoice" | "purchase_invoice";
}

export function InvoiceFormModal({ open, onClose, onSaved, clients, type }: Props) {
  const [clientId, setClientId] = useState("");
  const [date, setDate] = useState(new Date().toISOString().split("T")[0]);
  const [refNo, setRefNo] = useState("");
  const [partyName, setPartyName] = useState("");
  const [partyGstin, setPartyGstin] = useState("");
  const [placeOfSupply, setPlaceOfSupply] = useState("27");
  const [isInterstate, setIsInterstate] = useState(false);
  const [supplyType, setSupplyType] = useState<SupplyType>("taxable");
  const [invoiceType, setInvoiceType] = useState<InvoiceType>("Regular");
  const [isReverseCharge, setIsReverseCharge] = useState(false);
  const [lines, setLines] = useState<TransactionLine[]>([{ ...EMPTY_LINE }]);
  const [tdsSection, setTdsSection] = useState("");
  const [tdsRate, setTdsRate] = useState(0);
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setClientId(""); setDate(new Date().toISOString().split("T")[0]);
      setRefNo(""); setPartyName(""); setPartyGstin(""); setPlaceOfSupply("27");
      setIsInterstate(false); setSupplyType("taxable"); setInvoiceType("Regular");
      setIsReverseCharge(false); setLines([{ ...EMPTY_LINE }]);
      setTdsSection(""); setTdsRate(0); setNotes(""); setError(null);
    }
  }, [open]);

  function updateLine(idx: number, field: keyof TransactionLine, value: string | number) {
    setLines(prev => {
      const updated = [...prev];
      updated[idx] = { ...updated[idx], [field]: value };
      return updated;
    });
  }

  function addLine() { setLines(p => [...p, { ...EMPTY_LINE }]); }
  function removeLine(idx: number) { setLines(p => p.filter((_, i) => i !== idx)); }

  // Compute totals live
  const linesForCalc = lines.map(l => ({ ...l, rate_paise: Math.round((l as unknown as { rate_rupees?: number }).rate_rupees ?? l.rate_paise) }));
  const totals = computeInvoiceTotals(linesForCalc.map(l => ({ ...l })), isInterstate);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!clientId) { setError("Select a client"); return; }
    if (!partyName) { setError("Enter party name"); return; }
    if (lines.some(l => !l.description)) { setError("All line items need a description"); return; }

    setSaving(true); setError(null);
    try {
      const processedLines = lines.map(l => {
        const ratePaise = Math.round(parseFloat(String(l.rate_paise)) * 100);
        return { ...l, rate_paise: ratePaise };
      });
      computeInvoiceTotals(processedLines, isInterstate);

      const input: CreateInvoiceInput = {
        client_id: clientId,
        transaction_type: type,
        transaction_date: date,
        reference_no: refNo,
        party_name: partyName,
        party_gstin: partyGstin,
        place_of_supply: placeOfSupply,
        is_interstate: isInterstate,
        supply_type: supplyType,
        invoice_type: invoiceType,
        is_reverse_charge: isReverseCharge,
        lines: processedLines,
        tds_section: tdsSection || undefined,
        tds_rate: tdsRate || undefined,
        notes,
      };
      const { createInvoice } = await import("@/lib/data/transactions");
      await createInvoice(input);
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  if (!open) return null;

  const title = type === "sales_invoice" ? "New Sales Invoice" : "New Purchase / Expense";
  const partyLabel = type === "sales_invoice" ? "Customer Name" : "Vendor / Supplier Name";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-[#0F172A]/60" onClick={onClose} />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-3xl mx-4 max-h-[92vh] overflow-y-auto">
        <div className="flex items-center justify-between px-6 py-4 border-b sticky top-0 bg-white z-10">
          <div>
            <h2 className="text-base font-semibold text-[#0F172A]">{title}</h2>
            <p className="text-xs text-[#64748B] mt-0.5">Auto-creates journal entry + GST feed</p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-[#F1F5F9] text-[#94A3B8]"><X size={16} /></button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-5">
          {/* Header fields */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">Client *</label>
              <select value={clientId} onChange={e => setClientId(e.target.value)} required
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500">
                <option value="">Select client…</option>
                {clients.map(c => <option key={c.id} value={c.id}>{c.client_name}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">Invoice Date *</label>
              <input type="date" value={date} onChange={e => setDate(e.target.value)} required
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">{partyLabel} *</label>
              <input value={partyName} onChange={e => setPartyName(e.target.value)} required
                placeholder={type === "sales_invoice" ? "Customer name" : "Vendor name"}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">Reference / Invoice No</label>
              <input value={refNo} onChange={e => setRefNo(e.target.value)}
                placeholder="INV/2025-26/001"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono outline-none focus:border-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">Party GSTIN</label>
              <input value={partyGstin} onChange={e => setPartyGstin(e.target.value.toUpperCase())}
                placeholder="27ABCDE1234F1ZB" maxLength={15}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono outline-none focus:border-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">Place of Supply</label>
              <select value={placeOfSupply}
                onChange={e => { setPlaceOfSupply(e.target.value); setIsInterstate(e.target.value !== "27"); }}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500">
                {STATES.map(s => <option key={s.code} value={s.code}>{s.code} — {s.name}</option>)}
              </select>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <input type="checkbox" id="interstate" checked={isInterstate} onChange={e => setIsInterstate(e.target.checked)} className="rounded" />
            <label htmlFor="interstate" className="text-sm text-[#334155]">Interstate supply (IGST applies instead of CGST+SGST)</label>
          </div>

          {/* GST Classification — CGST Act Section 37 (GSTR-1 reporting) */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">Supply Type *</label>
              <select value={supplyType} onChange={e => setSupplyType(e.target.value as SupplyType)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500">
                {SUPPLY_TYPES.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">Invoice Type</label>
              <select value={invoiceType} onChange={e => setInvoiceType(e.target.value as InvoiceType)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500">
                {INVOICE_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
              </select>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <input type="checkbox" id="rcm" checked={isReverseCharge} onChange={e => setIsReverseCharge(e.target.checked)} className="rounded" />
            <label htmlFor="rcm" className="text-sm text-[#334155]">Reverse Charge Mechanism (RCM) applies — CGST Act Section 9(3)/9(4)</label>
          </div>

          {/* Line items */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-semibold text-[#334155] uppercase tracking-wide">Line Items</label>
              <button type="button" onClick={addLine} className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700">
                <Plus size={12} /> Add Line
              </button>
            </div>
            <div className="border border-[#E2E8F0] rounded-lg overflow-hidden">
              <table className="w-full text-xs">
                <thead className="bg-[#F8FAFC] border-b border-[#E2E8F0]">
                  <tr>
                    <th className="text-left px-3 py-2 text-[#475569] font-medium">Description</th>
                    <th className="text-left px-3 py-2 text-[#475569] font-medium w-20">HSN/SAC</th>
                    <th className="text-right px-3 py-2 text-[#475569] font-medium w-16">Qty</th>
                    <th className="text-right px-3 py-2 text-[#475569] font-medium w-28">Rate (₹)</th>
                    <th className="text-right px-3 py-2 text-[#475569] font-medium w-16">GST%</th>
                    <th className="text-right px-3 py-2 text-[#475569] font-medium w-24">Total</th>
                    <th className="w-8" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#F1F5F9]">
                  {lines.map((line, idx) => {
                    const taxable = Math.round(line.quantity * line.rate_paise);
                    const gst = Math.round(taxable * line.gst_rate / 100);
                    const total = taxable + gst;
                    return (
                      <tr key={idx} className="bg-white">
                        <td className="px-2 py-1.5">
                          <input value={line.description} onChange={e => updateLine(idx, "description", e.target.value)}
                            placeholder="Service / Item description" required
                            className="w-full border-0 bg-transparent outline-none focus:bg-blue-50 rounded px-1 py-0.5" />
                        </td>
                        <td className="px-2 py-1.5">
                          <input value={line.hsn_sac_code ?? ""} onChange={e => updateLine(idx, "hsn_sac_code", e.target.value)}
                            placeholder="9983" className="w-full border-0 bg-transparent outline-none focus:bg-blue-50 rounded px-1 py-0.5 font-mono" />
                        </td>
                        <td className="px-2 py-1.5">
                          <input type="number" min="0.001" step="0.001" value={line.quantity}
                            onChange={e => updateLine(idx, "quantity", parseFloat(e.target.value) || 1)}
                            className="w-full border-0 bg-transparent outline-none focus:bg-blue-50 rounded px-1 py-0.5 text-right" />
                        </td>
                        <td className="px-2 py-1.5">
                          <input type="number" min="0" step="0.01" value={line.rate_paise}
                            onChange={e => updateLine(idx, "rate_paise", parseFloat(e.target.value) || 0)}
                            placeholder="0.00"
                            className="w-full border-0 bg-transparent outline-none focus:bg-blue-50 rounded px-1 py-0.5 text-right" />
                        </td>
                        <td className="px-2 py-1.5">
                          <select value={line.gst_rate} onChange={e => updateLine(idx, "gst_rate", parseFloat(e.target.value))}
                            className="w-full border-0 bg-transparent outline-none focus:bg-blue-50 rounded text-right">
                            {GST_RATES.map(r => <option key={r} value={r}>{r}%</option>)}
                          </select>
                        </td>
                        <td className="px-2 py-1.5 text-right font-mono text-[#334155]">
                          {formatPaise(total)}
                        </td>
                        <td className="px-2 py-1.5">
                          {lines.length > 1 && (
                            <button type="button" onClick={() => removeLine(idx)} className="text-[#94A3B8] hover:text-red-500">
                              <Trash2 size={12} />
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Totals */}
          <div className="bg-[#F8FAFC] rounded-xl p-4 space-y-1.5 text-sm">
            <div className="flex justify-between text-[#475569]">
              <span>Taxable Amount</span>
              <span className="font-mono">{formatPaise(totals.taxable)}</span>
            </div>
            {!isInterstate ? (
              <>
                <div className="flex justify-between text-[#475569]">
                  <span>CGST</span>
                  <span className="font-mono">{formatPaise(totals.cgst)}</span>
                </div>
                <div className="flex justify-between text-[#475569]">
                  <span>SGST</span>
                  <span className="font-mono">{formatPaise(totals.sgst)}</span>
                </div>
              </>
            ) : (
              <div className="flex justify-between text-[#475569]">
                <span>IGST</span>
                <span className="font-mono">{formatPaise(totals.igst)}</span>
              </div>
            )}
            <div className="flex justify-between font-semibold text-[#0F172A] border-t border-[#E2E8F0] pt-1.5">
              <span>Total</span>
              <span className="font-mono">{formatPaise(totals.total)}</span>
            </div>
          </div>

          {/* TDS (purchase only) */}
          {type === "purchase_invoice" && (
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-[#334155] mb-1">TDS Section (IT Act)</label>
                <select value={tdsSection}
                  onChange={e => {
                    const found = TDS_SECTIONS.find(t => t.section === e.target.value);
                    setTdsSection(e.target.value);
                    setTdsRate(found?.rate ?? 0);
                  }}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500">
                  <option value="">No TDS</option>
                  {TDS_SECTIONS.map(t => <option key={t.section} value={t.section}>{t.label}</option>)}
                </select>
              </div>
              {tdsSection && (
                <div>
                  <label className="block text-xs font-medium text-[#334155] mb-1">TDS Amount</label>
                  <div className="rounded-lg border border-[#E2E8F0] bg-[#F8FAFC] px-3 py-2 text-sm font-mono text-[#334155]">
                    {formatPaise(Math.round(totals.taxable * tdsRate / 100))} ({tdsRate}%)
                  </div>
                </div>
              )}
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">Notes</label>
            <input value={notes} onChange={e => setNotes(e.target.value)} placeholder="Optional notes"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500" />
          </div>

          {error && (
            <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{error}</p>
          )}

          <div className="flex gap-3 pt-1 sticky bottom-0 bg-white pb-2">
            <button type="button" onClick={onClose}
              className="flex-1 rounded-lg border border-gray-300 px-4 py-2.5 text-sm font-medium text-[#334155] hover:bg-[#F8FAFC]">
              Cancel
            </button>
            <button type="submit" disabled={saving}
              className="flex-1 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60">
              {saving ? "Saving…" : `Post ${type === "sales_invoice" ? "Invoice" : "Expense"}`}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
