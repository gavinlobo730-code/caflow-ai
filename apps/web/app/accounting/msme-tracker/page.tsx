"use client";

/**
 * MSME 43B(h) Tracker
 * IT Act Section 43B(h) — effective FY 2024-25
 * Payments to MSME vendors must be made within 45 days (written agreement)
 * or 15 days (oral/no agreement). Non-payment by due date disallows the expense.
 *
 * Reference: Finance Act 2023 — insertion of clause (h) in Section 43B of IT Act.
 * All monetary amounts in paise (integer arithmetic — no floating point).
 */

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { ChevronLeft, Plus, X, AlertTriangle, CheckCircle, Clock, Download } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { TableSkeleton } from "@/components/ui/skeleton";
import { formatPaise } from "@/lib/services/formatting";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";
import { getClients } from "@/lib/data/clients";
import * as XLSX from "xlsx";
import type { Client } from "@/lib/types";

// ─── Types ────────────────────────────────────────────────────────────────────

interface MSMEPayment {
  id: string;
  firm_id: string;
  client_id: string;
  supplier_name: string;
  invoice_number: string | null;
  invoice_date: string;
  amount_paise: number;
  agreement_type: "written" | "oral";
  payment_date: string | null;
  created_at: string;
}

type PaymentStatus = "paid_on_time" | "overdue" | "disallowed";

interface PaymentRow extends MSMEPayment {
  due_date: string;
  due_days: number; // 45 or 15
  status: PaymentStatus;
  disallowed_paise: number;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function addDays(dateStr: string, days: number): string {
  const d = new Date(dateStr);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

const TODAY = new Date().toISOString().slice(0, 10);

function computeStatus(row: MSMEPayment): Pick<PaymentRow, "due_date" | "due_days" | "status" | "disallowed_paise"> {
  // IT Act Section 43B(h): 45 days if written agreement, 15 days if oral/no agreement
  const due_days = row.agreement_type === "written" ? 45 : 15;
  const due_date = addDays(row.invoice_date, due_days);

  let status: PaymentStatus;
  let disallowed_paise = 0;

  if (row.payment_date) {
    if (row.payment_date <= due_date) {
      status = "paid_on_time";
    } else {
      // Payment made after due date — amount disallowed in year of accrual
      status = "disallowed";
      disallowed_paise = row.amount_paise;
    }
  } else {
    // Not yet paid
    if (TODAY > due_date) {
      status = "disallowed";
      disallowed_paise = row.amount_paise;
    } else {
      status = "overdue";
    }
  }

  return { due_date, due_days, status, disallowed_paise };
}

function statusBadge(status: PaymentStatus) {
  switch (status) {
    case "paid_on_time":
      return { icon: CheckCircle, cls: "text-green-700 bg-green-50", label: "Paid on Time" };
    case "overdue":
      return { icon: Clock, cls: "text-amber-700 bg-amber-50", label: "Overdue" };
    case "disallowed":
      return { icon: AlertTriangle, cls: "text-red-700 bg-red-50", label: "Disallowed" };
  }
}

// ─── Add Payment Modal ────────────────────────────────────────────────────────

interface AddFormState {
  clientId: string;
  supplierName: string;
  invoiceNumber: string;
  invoiceDate: string;
  amountRs: string;
  agreementType: "written" | "oral";
  paymentDate: string;
}

const BLANK: AddFormState = {
  clientId: "",
  supplierName: "",
  invoiceNumber: "",
  invoiceDate: "",
  amountRs: "",
  agreementType: "oral",
  paymentDate: "",
};

function AddModal({ clients, onClose, onAdded }: {
  clients: Client[];
  onClose: () => void;
  onAdded: () => void;
}) {
  const [form, setForm] = useState<AddFormState>({ ...BLANK, clientId: clients[0]?.id ?? "" });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function upd(patch: Partial<AddFormState>) { setForm(f => ({ ...f, ...patch })); }

  const inputCls = "w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500";
  const lbl = "text-xs font-medium text-[#334155] block mb-1";

  async function handleSave() {
    if (!form.clientId || !form.supplierName || !form.invoiceDate || !form.amountRs) {
      setError("Supplier name, invoice date and amount are required");
      return;
    }
    // All money in integer paise — no floating point
    const amountPaise = Math.round(parseFloat(form.amountRs) * 100);
    if (isNaN(amountPaise) || amountPaise <= 0) { setError("Invalid amount"); return; }

    setSaving(true);
    setError(null);
    try {
      const firmId = await getFirmId();
      const sb = getSupabaseClient();
      const { error: err } = await sb.from("msme_payments").insert({
        firm_id: firmId,
        client_id: form.clientId,
        supplier_name: form.supplierName,
        invoice_number: form.invoiceNumber || null,
        invoice_date: form.invoiceDate,
        amount_paise: amountPaise,
        agreement_type: form.agreementType,
        payment_date: form.paymentDate || null,
      });
      if (err) throw new Error(err.message);
      onAdded();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 bg-white flex items-center justify-between px-6 py-4 border-b border-[#F1F5F9]">
          <h3 className="text-sm font-semibold text-[#0F172A]">Add MSME Payment</h3>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#475569]"><X size={16} /></button>
        </div>
        <div className="px-6 py-4 space-y-4">
          {error && <div className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</div>}

          <div>
            <label className={lbl}>Client *</label>
            <div className="w-full">
              <ClientLookup
                clients={clients}
                value={form.clientId}
                onChange={(id) => upd({ clientId: id })}
                ariaLabel="Client"
                placeholder="Select client…"
              />
            </div>
          </div>
          <div>
            <label className={lbl}>Supplier Name *</label>
            <input type="text" value={form.supplierName} onChange={e => upd({ supplierName: e.target.value })} className={inputCls} placeholder="MSME supplier name" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={lbl}>Invoice Number</label>
              <input type="text" value={form.invoiceNumber} onChange={e => upd({ invoiceNumber: e.target.value })} className={inputCls} placeholder="INV-001" />
            </div>
            <div>
              <label className={lbl}>Invoice Date *</label>
              <input type="date" value={form.invoiceDate} onChange={e => upd({ invoiceDate: e.target.value })} className={inputCls} />
            </div>
          </div>
          <div>
            <label className={lbl}>Invoice Amount (₹) *</label>
            <input type="number" min="0" step="0.01" value={form.amountRs} onChange={e => upd({ amountRs: e.target.value })} className={inputCls} placeholder="0.00" />
          </div>
          <div>
            <label className={lbl}>Agreement Type</label>
            <div className="flex gap-3">
              {(["written", "oral"] as const).map(t => (
                <label key={t} className="flex items-center gap-1.5 text-sm text-[#334155] cursor-pointer">
                  <input type="radio" name="agreement" value={t} checked={form.agreementType === t} onChange={() => upd({ agreementType: t })} />
                  {t === "written" ? "Written (45 days)" : "Oral/None (15 days)"}
                </label>
              ))}
            </div>
          </div>
          <div>
            <label className={lbl}>Payment Date (if paid)</label>
            <input type="date" value={form.paymentDate} onChange={e => upd({ paymentDate: e.target.value })} className={inputCls} />
          </div>
        </div>
        <div className="sticky bottom-0 bg-white px-6 py-4 border-t border-[#F1F5F9] flex gap-2 justify-end">
          <button onClick={onClose} className="px-4 py-2 text-sm text-[#334155] bg-[#F1F5F9] rounded-lg hover:bg-white/[0.08]">Cancel</button>
          <button onClick={handleSave} disabled={saving} className="px-4 py-2 text-sm text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-60">
            {saving ? "Saving…" : "Add Payment"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function MSMETrackerPage() {
  const [payments, setPayments] = useState<PaymentRow[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [clientFilter, setClientFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cls, firmId] = await Promise.all([getClients(), getFirmId()]);
      setClients(cls);
      const sb = getSupabaseClient();
      const { data, error: err } = await sb
        .from("msme_payments")
        .select("*")
        .eq("firm_id", firmId)
        .order("invoice_date", { ascending: false });
      if (err) throw new Error(err.message);
      const rows: PaymentRow[] = ((data ?? []) as MSMEPayment[]).map(p => ({
        ...p,
        ...computeStatus(p),
      }));
      setPayments(rows);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const filtered = clientFilter === "all" ? payments : payments.filter(p => p.client_id === clientFilter);

  // Total disallowed amount (affects tax computation — IT Act Section 43B(h))
  const totalDisallowed = filtered.reduce((s, p) => s + p.disallowed_paise, 0);
  const disallowedCount = filtered.filter(p => p.status === "disallowed").length;

  function clientName(id: string) {
    return clients.find(c => c.id === id)?.client_name ?? id;
  }

  function exportExcel() {
    const rows = filtered.map(p => ({
      Client: clientName(p.client_id),
      Supplier: p.supplier_name,
      "Invoice No": p.invoice_number ?? "",
      "Invoice Date": p.invoice_date,
      "Amount (₹)": (p.amount_paise / 100).toFixed(2),
      "Agreement Type": p.agreement_type,
      "Due Days": p.due_days,
      "Due Date": p.due_date,
      "Payment Date": p.payment_date ?? "",
      Status: p.status,
      "Disallowed (₹)": (p.disallowed_paise / 100).toFixed(2),
    }));
    const ws = XLSX.utils.json_to_sheet(rows);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "MSME 43B(h)");
    XLSX.writeFile(wb, "msme_43bh_tracker.xlsx");
  }

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/accounting" className="text-[#94A3B8] hover:text-[#475569]"><ChevronLeft size={18} /></Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-[#0F172A]">MSME 43B(h) Tracker</h1>
          <p className="text-sm text-[#64748B] mt-0.5">IT Act Section 43B(h) — MSME payment compliance (FY 2024-25 onwards)</p>
        </div>
        <Button variant="outline" size="sm" onClick={exportExcel} disabled={filtered.length === 0}>
          <Download size={14} className="mr-1" /> Export
        </Button>
        <Button size="sm" onClick={() => setShowAdd(true)}>
          <Plus size={14} className="mr-1" /> Add Payment
        </Button>
      </div>

      {/* Disallowance summary — prominently shown (affects tax computation) */}
      {totalDisallowed > 0 && (
        <div className="bg-red-50 border border-red-200 rounded-xl px-5 py-4 flex items-start gap-3">
          <AlertTriangle size={18} className="text-red-600 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-semibold text-red-800">
              Total Disallowed under Section 43B(h): {formatPaise(totalDisallowed)}
            </p>
            <p className="text-xs text-red-600 mt-1">
              {disallowedCount} payment{disallowedCount !== 1 ? "s" : ""} not made within the statutory period.
              These amounts are disallowed as expenses and must be added back to taxable income.
              CA Review Required before filing.
            </p>
          </div>
        </div>
      )}

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: "Total", value: filtered.length, color: "text-[#0F172A]" },
          { label: "Paid on Time", value: filtered.filter(p => p.status === "paid_on_time").length, color: "text-green-700" },
          { label: "Overdue (not yet disallowed)", value: filtered.filter(p => p.status === "overdue").length, color: "text-amber-700" },
          { label: "Disallowed", value: disallowedCount, color: "text-red-700" },
        ].map(s => (
          <Card key={s.label}>
            <CardContent className="pt-4 pb-3">
              <p className={`text-2xl font-bold ${s.color}`}>{s.value}</p>
              <p className="text-xs text-[#64748B] mt-0.5">{s.label}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Filters */}
      <div className="flex gap-3">
        <ClientLookup
          clients={clients}
          value={clientFilter === "all" ? "" : clientFilter}
          onChange={(id) => setClientFilter(id || "all")}
          ariaLabel="Client"
          placeholder="All Clients"
          clearable
        />
      </div>

      {error && <div className="bg-red-50 text-red-700 rounded-lg px-5 py-4 text-sm">{error}</div>}

      {/* Table */}
      <Card>
        {loading ? (
          <TableSkeleton cols={9} bare />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[900px]">
              <thead>
                <tr className="border-b border-[#F1F5F9] text-xs text-[#94A3B8]">
                  <th className="px-5 py-3 text-left">Client</th>
                  <th className="px-3 py-3 text-left">Supplier</th>
                  <th className="px-3 py-3 text-left">Invoice</th>
                  <th className="px-3 py-3 text-left">Invoice Date</th>
                  <th className="px-3 py-3 text-right">Amount</th>
                  <th className="px-3 py-3 text-left">Agreement</th>
                  <th className="px-3 py-3 text-left">Due Date</th>
                  <th className="px-3 py-3 text-left">Payment Date</th>
                  <th className="px-5 py-3 text-left">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {filtered.length === 0 && (
                  <tr><td colSpan={9} className="text-center text-[#94A3B8] py-8 text-sm">No MSME payments found. Add one above.</td></tr>
                )}
                {filtered.map(p => {
                  const badge = statusBadge(p.status);
                  const Icon = badge.icon;
                  return (
                    <tr key={p.id} className="hover:bg-[#F8FAFC]">
                      <td className="px-5 py-3 text-sm font-medium text-[#0F172A]">{clientName(p.client_id)}</td>
                      <td className="px-3 py-3 text-sm text-[#334155]">{p.supplier_name}</td>
                      <td className="px-3 py-3 text-xs font-mono text-[#64748B]">{p.invoice_number ?? "—"}</td>
                      <td className="px-3 py-3 text-xs text-[#475569]">{p.invoice_date}</td>
                      <td className="px-3 py-3 text-sm tabular-nums text-right font-medium">{formatPaise(p.amount_paise)}</td>
                      <td className="px-3 py-3 text-xs text-[#475569]">
                        {p.agreement_type === "written" ? "Written (45d)" : "Oral (15d)"}
                      </td>
                      <td className="px-3 py-3 text-xs text-[#475569]">{p.due_date}</td>
                      <td className="px-3 py-3 text-xs text-[#475569]">{p.payment_date ?? "—"}</td>
                      <td className="px-5 py-3">
                        <span className={`inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full font-medium ${badge.cls}`}>
                          <Icon size={12} /> {badge.label}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {showAdd && clients.length > 0 && (
        <AddModal clients={clients} onClose={() => setShowAdd(false)} onAdded={loadData} />
      )}
    </div>
  );
}
