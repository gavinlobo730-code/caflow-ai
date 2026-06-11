"use client";

/**
 * Sales Invoice — CGST Act Section 31 (Tax Invoice)
 * All amounts stored in integer paise. Display in Rs with 2 decimal places.
 */

import { useState, useEffect, useCallback } from "react";
import { Plus, X, Printer, AlertCircle, FileText, Upload } from "lucide-react";
import CsvImportModal, { type ImportRow } from "@/components/CsvImportModal";

const INVOICE_IMPORT_COLUMNS = [
  { key: "invoice_no",      label: "Invoice No",      required: true,  hint: "e.g. INV-2025-001" },
  { key: "invoice_date",    label: "Invoice Date",    required: true,  hint: "YYYY-MM-DD e.g. 2025-04-01" },
  { key: "client_name",     label: "Client Name",     required: true,  hint: "Must match existing client name exactly" },
  { key: "description",     label: "Description",     required: true,  hint: "Service/item description" },
  { key: "sac_code",        label: "SAC/HSN Code",    required: false, hint: "e.g. 998211" },
  { key: "quantity",        label: "Quantity",         required: false, hint: "e.g. 1" },
  { key: "rate_rs",         label: "Rate (₹)",         required: true,  hint: "e.g. 10000 (in rupees, not paise)" },
  { key: "gst_rate_pct",    label: "GST Rate %",      required: true,  hint: "e.g. 18" },
  { key: "place_of_supply", label: "Place of Supply", required: false, hint: "e.g. Maharashtra" },
  { key: "is_igst",         label: "IGST?",           required: false, hint: "true | false (interstate supply)" },
  { key: "notes",           label: "Notes",           required: false, hint: "Optional" },
];
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";

// ── Types ──────────────────────────────────────────────────────────────────

type Client = {
  id: string;
  client_name: string;
  gstin?: string;
  pan?: string;
};

type InvoiceLine = {
  description: string;
  hsn_sac: string;
  quantity: string;
  unit: string;
  rate_paise: number;
  gst_rate: number;
};

type Invoice = {
  id: string;
  invoice_no: string;
  invoice_date: string;
  client_id: string;
  party_name: string;
  party_gstin: string;
  place_of_supply: string;
  is_interstate: boolean;
  taxable_amount_paise: number;
  cgst_paise: number;
  sgst_paise: number;
  igst_paise: number;
  total_paise: number;
  status: string;
  notes?: string;
};

// ── Helpers ────────────────────────────────────────────────────────────────

function fmtRs(paise: number): string {
  return (paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 });
}

function rsToP(rs: number | string): number {
  return Math.round(parseFloat(String(rs) || "0") * 100);
}

const ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
  "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
  "Seventeen", "Eighteen", "Nineteen"];
const TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"];

function numToWords(n: number): string {
  if (n === 0) return "Zero";
  if (n < 20) return ONES[n];
  if (n < 100) return TENS[Math.floor(n / 10)] + (n % 10 ? " " + ONES[n % 10] : "");
  if (n < 1000) return ONES[Math.floor(n / 100)] + " Hundred" + (n % 100 ? " " + numToWords(n % 100) : "");
  if (n < 100000) return numToWords(Math.floor(n / 1000)) + " Thousand" + (n % 1000 ? " " + numToWords(n % 1000) : "");
  if (n < 10000000) return numToWords(Math.floor(n / 100000)) + " Lakh" + (n % 100000 ? " " + numToWords(n % 100000) : "");
  return numToWords(Math.floor(n / 10000000)) + " Crore" + (n % 10000000 ? " " + numToWords(n % 10000000) : "");
}

function amountInWords(paise: number): string {
  const rupees = Math.floor(paise / 100);
  const p = paise % 100;
  let words = "Rupees " + numToWords(rupees);
  if (p > 0) words += " and " + numToWords(p) + " Paise";
  return words + " Only";
}

const INDIAN_STATES = [
  "Andhra Pradesh","Arunachal Pradesh","Assam","Bihar","Chhattisgarh","Goa","Gujarat",
  "Haryana","Himachal Pradesh","Jharkhand","Karnataka","Kerala","Madhya Pradesh",
  "Maharashtra","Manipur","Meghalaya","Mizoram","Nagaland","Odisha","Punjab","Rajasthan",
  "Sikkim","Tamil Nadu","Telangana","Tripura","Uttar Pradesh","Uttarakhand","West Bengal",
  "Andaman & Nicobar Islands","Chandigarh","Dadra & Nagar Haveli","Daman & Diu","Delhi",
  "Jammu & Kashmir","Ladakh","Lakshadweep","Puducherry",
];

const UNITS = ["Nos","Kg","Mtrs","Hours","Litres","Box","Pcs","Set","Sqft","Days"];
const GST_RATES = [0, 5, 12, 18, 28];
const STATUS_BADGE: Record<string, string> = {
  draft: "bg-amber-100 text-amber-700",
  sent: "bg-blue-100 text-blue-700",
  paid: "bg-green-100 text-green-700",
};

const INSTALL_SQL = `-- Run in Supabase SQL editor:
CREATE TABLE IF NOT EXISTS sales_invoices (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL,
  client_id UUID,
  invoice_no TEXT NOT NULL,
  invoice_date DATE NOT NULL,
  party_name TEXT,
  party_gstin TEXT,
  place_of_supply TEXT,
  is_interstate BOOLEAN DEFAULT false,
  taxable_amount_paise BIGINT DEFAULT 0,
  cgst_paise BIGINT DEFAULT 0,
  sgst_paise BIGINT DEFAULT 0,
  igst_paise BIGINT DEFAULT 0,
  total_paise BIGINT DEFAULT 0,
  status TEXT DEFAULT 'draft',
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS invoice_lines (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  invoice_id UUID NOT NULL REFERENCES sales_invoices(id),
  description TEXT,
  hsn_sac TEXT,
  quantity NUMERIC,
  unit TEXT,
  rate_paise BIGINT DEFAULT 0,
  taxable_paise BIGINT DEFAULT 0,
  gst_rate NUMERIC DEFAULT 0,
  cgst_paise BIGINT DEFAULT 0,
  sgst_paise BIGINT DEFAULT 0,
  igst_paise BIGINT DEFAULT 0,
  line_total_paise BIGINT DEFAULT 0
);`;

// ── Print Invoice view (hidden except on print) ───────────────────────────

function PrintInvoice({
  invoice,
  lines,
  firmName,
}: {
  invoice: Partial<Invoice>;
  lines: InvoiceLine[];
  firmName: string;
}) {
  const taxable = lines.reduce((s, l) => {
    const qty = parseFloat(l.quantity || "1") || 1;
    return s + Math.round(l.rate_paise * qty);
  }, 0);
  const cgstTotal = invoice.is_interstate ? 0 : lines.reduce((s, l) => {
    const qty = parseFloat(l.quantity || "1") || 1;
    return s + Math.round(Math.round(l.rate_paise * qty) * l.gst_rate / 200);
  }, 0);
  const igstTotal = !invoice.is_interstate ? 0 : lines.reduce((s, l) => {
    const qty = parseFloat(l.quantity || "1") || 1;
    return s + Math.round(Math.round(l.rate_paise * qty) * l.gst_rate / 100);
  }, 0);
  const grandTotal = taxable + cgstTotal * 2 + igstTotal;

  return (
    <div className="hidden print:block p-8 text-sm font-sans text-[#0F172A]">
      <div className="text-center mb-4 border-b pb-4">
        <h1 className="text-2xl font-bold">{firmName}</h1>
        <h2 className="text-lg font-semibold mt-1 uppercase tracking-widest">TAX INVOICE</h2>
        <p className="text-xs text-[#64748B] mt-1">CGST Act Section 31</p>
      </div>
      <div className="grid grid-cols-2 gap-4 mb-4 text-xs">
        <div>
          <p className="font-semibold mb-1">Bill To:</p>
          <p>{invoice.party_name}</p>
          <p>GSTIN: {invoice.party_gstin}</p>
          <p>Place of Supply: {invoice.place_of_supply}</p>
        </div>
        <div className="text-right">
          <p><b>Invoice No:</b> {invoice.invoice_no}</p>
          <p><b>Date:</b> {invoice.invoice_date}</p>
          <p><b>Supply:</b> {invoice.is_interstate ? "Inter-State (IGST)" : "Intra-State (CGST+SGST)"}</p>
        </div>
      </div>
      <table className="w-full border-collapse text-xs mb-4">
        <thead>
          <tr className="bg-[#F1F5F9]">
            <th className="border px-2 py-1 text-left">Description</th>
            <th className="border px-2 py-1">HSN/SAC</th>
            <th className="border px-2 py-1">Qty</th>
            <th className="border px-2 py-1">Unit</th>
            <th className="border px-2 py-1 text-right">Rate</th>
            <th className="border px-2 py-1 text-right">Taxable</th>
            <th className="border px-2 py-1">GST%</th>
            <th className="border px-2 py-1 text-right">GST Amt</th>
            <th className="border px-2 py-1 text-right">Total</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((l, i) => {
            const qty = parseFloat(l.quantity || "1") || 1;
            const lineT = Math.round(l.rate_paise * qty);
            const gstAmt = invoice.is_interstate
              ? Math.round(lineT * l.gst_rate / 100)
              : Math.round(lineT * l.gst_rate / 100);
            return (
              <tr key={i}>
                <td className="border px-2 py-1">{l.description}</td>
                <td className="border px-2 py-1 text-center">{l.hsn_sac}</td>
                <td className="border px-2 py-1 text-center">{qty}</td>
                <td className="border px-2 py-1 text-center">{l.unit}</td>
                <td className="border px-2 py-1 text-right">{fmtRs(l.rate_paise)}</td>
                <td className="border px-2 py-1 text-right">{fmtRs(lineT)}</td>
                <td className="border px-2 py-1 text-center">{l.gst_rate}%</td>
                <td className="border px-2 py-1 text-right">{fmtRs(gstAmt)}</td>
                <td className="border px-2 py-1 text-right">{fmtRs(lineT + gstAmt)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="flex justify-end text-xs">
        <table>
          <tbody>
            <tr><td className="pr-8 py-0.5">Taxable Amount</td><td className="text-right font-mono">Rs {fmtRs(taxable)}</td></tr>
            {!invoice.is_interstate && (
              <>
                <tr><td className="pr-8">CGST</td><td className="text-right font-mono">Rs {fmtRs(cgstTotal)}</td></tr>
                <tr><td className="pr-8">SGST</td><td className="text-right font-mono">Rs {fmtRs(cgstTotal)}</td></tr>
              </>
            )}
            {invoice.is_interstate && <tr><td className="pr-8">IGST</td><td className="text-right font-mono">Rs {fmtRs(igstTotal)}</td></tr>}
            <tr className="font-bold border-t"><td className="pr-8 pt-1">Grand Total</td><td className="text-right font-mono pt-1">Rs {fmtRs(grandTotal)}</td></tr>
          </tbody>
        </table>
      </div>
      <div className="mt-3 p-2 bg-[#F8FAFC] rounded text-xs">
        <b>Amount in Words:</b> {amountInWords(grandTotal)}
      </div>
      <div className="mt-3 text-xs text-[#64748B]">Bank Details: [Your bank details here]</div>
      <div className="mt-3 text-xs text-[#94A3B8] italic">
        We declare that this invoice shows the actual price of the goods described and that all particulars are true and correct.
      </div>
    </div>
  );
}

// ── New Invoice Form ──────────────────────────────────────────────────────

function NewInvoiceForm({
  clients,
  firmId,
  firmName,
  nextNo,
  onClose,
  onSaved,
}: {
  clients: Client[];
  firmId: string;
  firmName: string;
  nextNo: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    invoice_no: nextNo,
    invoice_date: new Date().toISOString().split("T")[0],
    client_id: clients[0]?.id ?? "",
    party_name: clients[0]?.client_name ?? "",
    party_gstin: clients[0]?.gstin ?? "",
    place_of_supply: "Maharashtra",
    is_interstate: false,
    notes: "",
  });
  const [lines, setLines] = useState<InvoiceLine[]>([{
    description: "", hsn_sac: "", quantity: "1", unit: "Nos", rate_paise: 0, gst_rate: 18,
  }]);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  function selectClient(cid: string) {
    const c = clients.find(x => x.id === cid);
    setForm(f => ({ ...f, client_id: cid, party_name: c?.client_name ?? "", party_gstin: c?.gstin ?? "" }));
  }

  function addLine() {
    setLines(l => [...l, { description: "", hsn_sac: "", quantity: "1", unit: "Nos", rate_paise: 0, gst_rate: 18 }]);
  }

  function removeLine(i: number) { setLines(l => l.filter((_, idx) => idx !== i)); }

  function updateLine(i: number, key: keyof InvoiceLine, value: string | number) {
    setLines(l => l.map((line, idx) => idx === i ? { ...line, [key]: value } : line));
  }

  // All integer paise — no float arithmetic on money
  const taxable = lines.reduce((s, l) => {
    const qty = parseFloat(l.quantity || "1") || 1;
    return s + Math.round(l.rate_paise * qty);
  }, 0);

  const cgstTotal = form.is_interstate ? 0 : lines.reduce((s, l) => {
    const qty = parseFloat(l.quantity || "1") || 1;
    const lineT = Math.round(l.rate_paise * qty);
    return s + Math.round(lineT * l.gst_rate / 200);
  }, 0);

  const igstTotal = !form.is_interstate ? 0 : lines.reduce((s, l) => {
    const qty = parseFloat(l.quantity || "1") || 1;
    const lineT = Math.round(l.rate_paise * qty);
    return s + Math.round(lineT * l.gst_rate / 100);
  }, 0);

  const grandTotal = taxable + cgstTotal * 2 + igstTotal;
  const roundOff = Math.round(grandTotal / 100) * 100 - grandTotal;
  const finalTotal = grandTotal + roundOff;

  async function save() {
    if (!form.invoice_no || !form.invoice_date) { setErr("Invoice number and date required."); return; }
    setSaving(true);
    const sb = getSupabaseClient();
    const { data: inv, error } = await sb.from("sales_invoices").insert({
      firm_id: firmId,
      client_id: form.client_id || null,
      invoice_no: form.invoice_no,
      invoice_date: form.invoice_date,
      party_name: form.party_name,
      party_gstin: form.party_gstin,
      place_of_supply: form.place_of_supply,
      is_interstate: form.is_interstate,
      taxable_amount_paise: taxable,
      cgst_paise: cgstTotal,
      sgst_paise: cgstTotal,
      igst_paise: igstTotal,
      total_paise: finalTotal,
      status: "draft",
      notes: form.notes,
    }).select().single();
    if (error || !inv) { setSaving(false); setErr(error?.message ?? "Error saving"); return; }

    const lineRows = lines.map(l => {
      const qty = parseFloat(l.quantity || "1") || 1;
      const lineT = Math.round(l.rate_paise * qty);
      const lineCgst = form.is_interstate ? 0 : Math.round(lineT * l.gst_rate / 200);
      const lineIgst = form.is_interstate ? Math.round(lineT * l.gst_rate / 100) : 0;
      return {
        invoice_id: inv.id,
        description: l.description,
        hsn_sac: l.hsn_sac,
        quantity: qty,
        unit: l.unit,
        rate_paise: l.rate_paise,
        taxable_paise: lineT,
        gst_rate: l.gst_rate,
        cgst_paise: lineCgst,
        sgst_paise: lineCgst,
        igst_paise: lineIgst,
        line_total_paise: lineT + lineCgst * 2 + lineIgst,
      };
    });
    await sb.from("invoice_lines").insert(lineRows);
    setSaving(false);
    onSaved();
  }

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-[#F8FAFC]">
      <PrintInvoice
        invoice={{ ...form, taxable_amount_paise: taxable, cgst_paise: cgstTotal, sgst_paise: cgstTotal, igst_paise: igstTotal, total_paise: finalTotal }}
        lines={lines}
        firmName={firmName}
      />
      <div className="max-w-5xl mx-auto p-6 print:hidden">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold text-[#0F172A]">New Tax Invoice — CGST Act Sec 31</h2>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => window.print()} className="flex items-center gap-1.5">
              <Printer size={14} />Print
            </Button>
            <button onClick={onClose}><X size={18} /></button>
          </div>
        </div>
        {err && <p className="text-red-600 text-sm mb-3">{err}</p>}

        <Card className="mb-4">
          <CardContent className="pt-5">
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              <div>
                <label className="block text-xs font-medium text-[#334155] mb-1">Invoice No</label>
                <input className="w-full border rounded-lg px-3 py-2 text-sm" value={form.invoice_no} onChange={e => setForm(f => ({ ...f, invoice_no: e.target.value }))} />
              </div>
              <div>
                <label className="block text-xs font-medium text-[#334155] mb-1">Invoice Date</label>
                <input type="date" className="w-full border rounded-lg px-3 py-2 text-sm" value={form.invoice_date} onChange={e => setForm(f => ({ ...f, invoice_date: e.target.value }))} />
              </div>
              <div>
                <label className="block text-xs font-medium text-[#334155] mb-1">Client</label>
                <select className="w-full border rounded-lg px-3 py-2 text-sm" value={form.client_id} onChange={e => selectClient(e.target.value)}>
                  <option value="">- Select Client -</option>
                  {clients.map(c => <option key={c.id} value={c.id}>{c.client_name}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-[#334155] mb-1">Party Name</label>
                <input className="w-full border rounded-lg px-3 py-2 text-sm" value={form.party_name} onChange={e => setForm(f => ({ ...f, party_name: e.target.value }))} />
              </div>
              <div>
                <label className="block text-xs font-medium text-[#334155] mb-1">Party GSTIN</label>
                <input className="w-full border rounded-lg px-3 py-2 text-sm uppercase font-mono" value={form.party_gstin} onChange={e => setForm(f => ({ ...f, party_gstin: e.target.value.toUpperCase() }))} maxLength={15} />
              </div>
              <div>
                <label className="block text-xs font-medium text-[#334155] mb-1">Place of Supply</label>
                <select className="w-full border rounded-lg px-3 py-2 text-sm" value={form.place_of_supply} onChange={e => setForm(f => ({ ...f, place_of_supply: e.target.value }))}>
                  {INDIAN_STATES.map(s => <option key={s}>{s}</option>)}
                </select>
              </div>
              <div className="flex items-center gap-2">
                <input type="checkbox" id="interstate" checked={form.is_interstate} onChange={e => setForm(f => ({ ...f, is_interstate: e.target.checked }))} />
                <label htmlFor="interstate" className="text-sm text-[#334155]">Inter-State Supply (IGST)</label>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="mb-4">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-base">Line Items</CardTitle>
            <Button size="sm" variant="outline" onClick={addLine}><Plus size={14} className="mr-1" />Add Row</Button>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-[#F8FAFC] text-xs font-medium text-[#64748B] uppercase">
                    <th className="text-left px-3 py-2">Description</th>
                    <th className="px-3 py-2">HSN/SAC</th>
                    <th className="px-3 py-2 w-16">Qty</th>
                    <th className="px-3 py-2 w-20">Unit</th>
                    <th className="px-3 py-2 text-right w-28">Rate (Rs)</th>
                    <th className="px-3 py-2 text-right w-28">Taxable</th>
                    <th className="px-3 py-2 w-20">GST%</th>
                    <th className="px-3 py-2 text-right w-28">{form.is_interstate ? "IGST" : "CGST+SGST"}</th>
                    <th className="px-3 py-2 text-right w-28">Total</th>
                    <th className="w-8"></th>
                  </tr>
                </thead>
                <tbody>
                  {lines.map((l, i) => {
                    const qty = parseFloat(l.quantity || "1") || 1;
                    const lineT = Math.round(l.rate_paise * qty);
                    const gstAmt = Math.round(lineT * l.gst_rate / 100);
                    return (
                      <tr key={i} className="border-b">
                        <td className="px-3 py-1.5">
                          <input className="w-full border rounded px-2 py-1 text-xs" value={l.description} onChange={e => updateLine(i, "description", e.target.value)} />
                        </td>
                        <td className="px-3 py-1.5">
                          <input className="w-full border rounded px-2 py-1 text-xs" value={l.hsn_sac} onChange={e => updateLine(i, "hsn_sac", e.target.value)} />
                        </td>
                        <td className="px-3 py-1.5">
                          <input type="number" className="w-full border rounded px-2 py-1 text-xs" value={l.quantity} onChange={e => updateLine(i, "quantity", e.target.value)} />
                        </td>
                        <td className="px-3 py-1.5">
                          <select className="w-full border rounded px-1 py-1 text-xs" value={l.unit} onChange={e => updateLine(i, "unit", e.target.value)}>
                            {UNITS.map(u => <option key={u}>{u}</option>)}
                          </select>
                        </td>
                        <td className="px-3 py-1.5">
                          <input type="number" className="w-full border rounded px-2 py-1 text-xs text-right" value={l.rate_paise / 100} onChange={e => updateLine(i, "rate_paise", rsToP(e.target.value))} />
                        </td>
                        <td className="px-3 py-1.5 text-right font-mono text-xs">{fmtRs(lineT)}</td>
                        <td className="px-3 py-1.5">
                          <select className="w-full border rounded px-1 py-1 text-xs" value={l.gst_rate} onChange={e => updateLine(i, "gst_rate", parseInt(e.target.value))}>
                            {GST_RATES.map(r => <option key={r} value={r}>{r}%</option>)}
                          </select>
                        </td>
                        <td className="px-3 py-1.5 text-right font-mono text-xs">{fmtRs(gstAmt)}</td>
                        <td className="px-3 py-1.5 text-right font-mono text-xs font-semibold">{fmtRs(lineT + gstAmt)}</td>
                        <td className="px-3 py-1.5">
                          <button onClick={() => removeLine(i)} className="text-[#CBD5E1] hover:text-red-500"><X size={12} /></button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>

        <div className="flex justify-end mb-6">
          <div className="w-72 space-y-1 text-sm">
            <div className="flex justify-between"><span className="text-[#475569]">Subtotal (Taxable)</span><span className="font-mono">Rs {fmtRs(taxable)}</span></div>
            {!form.is_interstate && (
              <>
                <div className="flex justify-between"><span className="text-[#475569]">CGST</span><span className="font-mono">Rs {fmtRs(cgstTotal)}</span></div>
                <div className="flex justify-between"><span className="text-[#475569]">SGST</span><span className="font-mono">Rs {fmtRs(cgstTotal)}</span></div>
              </>
            )}
            {form.is_interstate && (
              <div className="flex justify-between"><span className="text-[#475569]">IGST</span><span className="font-mono">Rs {fmtRs(igstTotal)}</span></div>
            )}
            {roundOff !== 0 && (
              <div className="flex justify-between"><span className="text-[#475569]">Round Off</span><span className="font-mono">Rs {fmtRs(roundOff)}</span></div>
            )}
            <div className="flex justify-between border-t pt-1 font-bold text-base">
              <span>Grand Total</span>
              <span className="font-mono">Rs {fmtRs(finalTotal)}</span>
            </div>
            <div className="text-xs text-[#64748B] italic">{amountInWords(finalTotal)}</div>
          </div>
        </div>

        <div className="mb-4">
          <label className="block text-xs font-medium text-[#334155] mb-1">Notes</label>
          <textarea className="w-full border rounded-lg px-3 py-2 text-sm" rows={2} value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} />
        </div>

        <div className="flex gap-2 justify-end">
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={save} disabled={saving}>{saving ? "Saving..." : "Save Invoice"}</Button>
        </div>
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────

export default function InvoicesPage() {
  const [firmId, setFirmId] = useState<string | null>(null);
  const [firmName, setFirmName] = useState("Your Firm");
  const [tablesError, setTablesError] = useState(false);
  const [clients, setClients] = useState<Client[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);
  const [showImport, setShowImport] = useState(false);

  const [filterClient, setFilterClient] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [filterFrom, setFilterFrom] = useState("");
  const [filterTo, setFilterTo] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const fid = await getFirmId();
      setFirmId(fid);
      const sb = getSupabaseClient();
      const [clientsRes, invoicesRes, firmRes] = await Promise.all([
        sb.from("clients").select("id, client_name, gstin, pan").eq("firm_id", fid),
        sb.from("sales_invoices").select("*").eq("firm_id", fid).order("created_at", { ascending: false }),
        sb.from("firms").select("name").eq("id", fid).maybeSingle(),
      ]);
      if (invoicesRes.error?.message?.includes("does not exist")) {
        setTablesError(true);
        setLoading(false);
        return;
      }
      setClients(clientsRes.data ?? []);
      setInvoices(invoicesRes.data ?? []);
      if (firmRes.data?.name) setFirmName(firmRes.data.name);
    } catch { /* not authenticated */ }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleInvoiceImport(rows: ImportRow[]) {
    if (!firmId) return { imported: 0, errors: ["Not authenticated"] };
    const sb = getSupabaseClient();
    let imported = 0;
    const errors: string[] = [];
    for (const row of rows) {
      const client = clients.find(c => c.client_name.toLowerCase() === row.client_name?.toLowerCase());
      if (!client) { errors.push(`Row: client "${row.client_name}" not found`); continue; }
      const rateRs = parseFloat(row.rate_rs ?? "0");
      const qty = parseFloat(row.quantity ?? "1") || 1;
      const gstPct = parseFloat(row.gst_rate_pct ?? "18");
      const isIgst = row.is_igst?.toLowerCase() === "true";
      const subtotalPaise = Math.round(rateRs * qty * 100);
      const gstPaise = Math.round(subtotalPaise * gstPct / 100);
      const cgstPaise = isIgst ? 0 : Math.round(gstPaise / 2);
      const sgstPaise = isIgst ? 0 : Math.round(gstPaise / 2);
      const igstPaise = isIgst ? gstPaise : 0;
      const totalPaise = subtotalPaise + gstPaise;
      const { data: inv, error: invErr } = await sb.from("sales_invoices").insert({
        firm_id: firmId,
        client_id: client.id,
        invoice_no: row.invoice_no,
        invoice_date: row.invoice_date,
        place_of_supply: row.place_of_supply || null,
        is_igst: isIgst,
        subtotal_paise: subtotalPaise,
        cgst_paise: cgstPaise,
        sgst_paise: sgstPaise,
        igst_paise: igstPaise,
        total_paise: totalPaise,
        status: "draft",
        notes: row.notes || null,
      }).select().single();
      if (invErr) { errors.push(`${row.invoice_no}: ${invErr.message}`); continue; }
      if (inv) {
        await sb.from("invoice_lines").insert({
          invoice_id: (inv as { id: string }).id,
          description: row.description,
          sac_code: row.sac_code || "998211",
          quantity: qty,
          rate_paise: Math.round(rateRs * 100),
          amount_paise: subtotalPaise,
          gst_rate_pct: gstPct,
        });
      }
      imported++;
    }
    if (imported > 0) load();
    return { imported, errors };
  }

  const nextInvoiceNo = `INV-${new Date().getFullYear()}-${String(invoices.length + 1).padStart(3, "0")}`;

  const filtered = invoices.filter(inv => {
    if (filterClient && inv.client_id !== filterClient) return false;
    if (filterStatus && inv.status !== filterStatus) return false;
    if (filterFrom && inv.invoice_date < filterFrom) return false;
    if (filterTo && inv.invoice_date > filterTo) return false;
    return true;
  });

  if (loading) return <div className="min-h-screen bg-[#F8FAFC] flex items-center justify-center"><p className="text-[#64748B]">Loading invoices...</p></div>;

  if (tablesError) {
    return (
      <div className="min-h-screen bg-[#F8FAFC] p-8">
        <Card className="max-w-2xl mx-auto">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <AlertCircle size={18} className="text-amber-500" />Install Invoice Tables
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-[#475569] mb-4">The sales invoice tables do not exist yet. Run this SQL:</p>
            <pre className="bg-gray-900 text-green-400 p-4 rounded-lg text-xs overflow-auto whitespace-pre-wrap">{INSTALL_SQL}</pre>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#F8FAFC] p-8">
      {showNew && firmId && (
        <NewInvoiceForm
          clients={clients}
          firmId={firmId}
          firmName={firmName}
          nextNo={nextInvoiceNo}
          onClose={() => setShowNew(false)}
          onSaved={() => { setShowNew(false); load(); }}
        />
      )}
      <div className="max-w-6xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-[#0F172A]">Sales Invoices</h1>
            <p className="text-sm text-[#64748B] mt-0.5">CGST Act Section 31 - Tax Invoice</p>
          </div>
          <Button variant="outline" onClick={() => setShowImport(true)} className="flex items-center gap-1.5">
            <Upload size={14} />Import CSV
          </Button>
          <Button onClick={() => setShowNew(true)} className="flex items-center gap-1.5">
            <Plus size={14} />New Invoice
          </Button>
        </div>

        <Card className="mb-4">
          <CardContent className="pt-4">
            <div className="flex flex-wrap gap-3">
              <div>
                <label className="block text-xs font-medium text-[#334155] mb-1">Client</label>
                <select className="border rounded-lg px-3 py-2 text-sm" value={filterClient} onChange={e => setFilterClient(e.target.value)}>
                  <option value="">All Clients</option>
                  {clients.map(c => <option key={c.id} value={c.id}>{c.client_name}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-[#334155] mb-1">Status</label>
                <select className="border rounded-lg px-3 py-2 text-sm" value={filterStatus} onChange={e => setFilterStatus(e.target.value)}>
                  <option value="">All Status</option>
                  <option value="draft">Draft</option>
                  <option value="sent">Sent</option>
                  <option value="paid">Paid</option>
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-[#334155] mb-1">From</label>
                <input type="date" className="border rounded-lg px-3 py-2 text-sm" value={filterFrom} onChange={e => setFilterFrom(e.target.value)} />
              </div>
              <div>
                <label className="block text-xs font-medium text-[#334155] mb-1">To</label>
                <input type="date" className="border rounded-lg px-3 py-2 text-sm" value={filterTo} onChange={e => setFilterTo(e.target.value)} />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-0">
            {filtered.length === 0 ? (
              <div className="text-center py-12 text-[#94A3B8]">
                <FileText size={32} className="mx-auto mb-3 opacity-30" />
                <p>No invoices yet. Click &quot;New Invoice&quot; to create one.</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-xs font-medium text-[#64748B] uppercase tracking-wide">
                      <th className="text-left py-3 px-4">Invoice No</th>
                      <th className="text-left py-3 px-4">Date</th>
                      <th className="text-left py-3 px-4">Party</th>
                      <th className="text-left py-3 px-4">GSTIN</th>
                      <th className="text-right py-3 px-4">Taxable</th>
                      <th className="text-right py-3 px-4">GST</th>
                      <th className="text-right py-3 px-4">Total</th>
                      <th className="text-center py-3 px-4">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map(inv => {
                      const gst = inv.cgst_paise + inv.sgst_paise + inv.igst_paise;
                      const client = clients.find(c => c.id === inv.client_id);
                      return (
                        <tr key={inv.id} className="border-b hover:bg-[#F8FAFC]">
                          <td className="py-3 px-4 font-mono text-xs font-medium">{inv.invoice_no}</td>
                          <td className="py-3 px-4 text-[#475569]">{inv.invoice_date}</td>
                          <td className="py-3 px-4 font-medium">{inv.party_name || client?.client_name || "—"}</td>
                          <td className="py-3 px-4 font-mono text-xs">{inv.party_gstin || "—"}</td>
                          <td className="py-3 px-4 text-right font-mono">Rs {fmtRs(inv.taxable_amount_paise)}</td>
                          <td className="py-3 px-4 text-right font-mono">Rs {fmtRs(gst)}</td>
                          <td className="py-3 px-4 text-right font-mono font-semibold">Rs {fmtRs(inv.total_paise)}</td>
                          <td className="py-3 px-4 text-center">
                            <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_BADGE[inv.status] ?? "bg-[#F1F5F9] text-[#475569]"}`}>
                              {inv.status.charAt(0).toUpperCase() + inv.status.slice(1)}
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {showImport && (
        <CsvImportModal
          title="Import Sales Invoices from CSV"
          columns={INVOICE_IMPORT_COLUMNS}
          templateFilename="practicesync-invoices-template.xlsx"
          onClose={() => setShowImport(false)}
          onImport={handleInvoiceImport}
          validateRow={(row) => {
            const errs: string[] = [];
            if (row.invoice_date && !/^\d{4}-\d{2}-\d{2}$/.test(row.invoice_date)) errs.push("invoice_date must be YYYY-MM-DD");
            if (row.rate_rs && isNaN(parseFloat(row.rate_rs))) errs.push("rate_rs must be a number");
            if (row.gst_rate_pct && isNaN(parseFloat(row.gst_rate_pct))) errs.push("gst_rate_pct must be a number");
            return errs;
          }}
        />
      )}
    </div>
  );
}
