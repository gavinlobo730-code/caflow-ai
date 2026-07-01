"use client";

/**
 * Supplier Master with TDS Section Mapping
 * IT Act sections 194C (Contractor), 194I (Rent), 194J (Professional), 194H (Commission),
 * 194A (Interest), 194B (Lottery) — deduct at source before payment to supplier.
 * All monetary amounts stored in paise (integer arithmetic).
 */

import { useState, useEffect } from "react";
import Link from "next/link";
import { ChevronLeft, Plus, X, Users, IndianRupee } from "lucide-react";
import { TableSkeleton } from "@/components/ui/skeleton";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";

// ─── Types ────────────────────────────────────────────────────────────────────

interface Client {
  id: string;
  client_name: string;
}

interface Supplier {
  id: string;
  firm_id: string;
  client_id: string;
  supplier_name: string;
  gstin: string | null;
  pan: string | null;
  tds_section: string | null;
  tds_rate_percent: number | null;
  credit_limit_paise: number;
  payment_terms_days: number;
  is_active: boolean;
  created_at: string;
}

// TDS sections with default rates — IT Act sections
const TDS_SECTIONS = [
  { value: "",     label: "None (No TDS)",           defaultRate: 0 },
  { value: "194C", label: "194C — Contractor (1%/2%)",  defaultRate: 2 },
  { value: "194I", label: "194I — Rent (10%)",           defaultRate: 10 },
  { value: "194J", label: "194J — Professional (10%)",   defaultRate: 10 },
  { value: "194H", label: "194H — Commission (5%)",      defaultRate: 5 },
  { value: "194A", label: "194A — Interest (10%)",       defaultRate: 10 },
  { value: "194B", label: "194B — Lottery (30%)",        defaultRate: 30 },
  { value: "other", label: "Other",                      defaultRate: 0 },
];

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmtRs(paise: number): string {
  return "₹" + (paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 });
}

function rsToP(rs: string): number {
  return Math.round(parseFloat(rs || "0") * 100);
}

const BLANK_FORM = {
  supplier_name: "",
  gstin: "",
  pan: "",
  tds_section: "",
  tds_rate_percent: "",
  credit_limit_rs: "",
  payment_terms_days: "30",
  is_active: true,
};

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function SuppliersPage() {
  const [firmId, setFirmId] = useState<string | null>(null);
  const [clients, setClients] = useState<Client[]>([]);
  const [selectedClientId, setSelectedClientId] = useState<string>("");
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState(BLANK_FORM);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // TDS calculator
  const [billRs, setBillRs] = useState("");
  const billPaise = rsToP(billRs);
  const calcTdsSection = TDS_SECTIONS.find(s => s.value === form.tds_section);
  const calcTdsRate = parseFloat(form.tds_rate_percent || "0");
  // TDS deduction per IT Act sections 194C, 194I, 194J etc.
  // Deduct at source before payment to supplier
  const tdsAmount = Math.round(billPaise * calcTdsRate / 100); // integer paise

  useEffect(() => {
    const sb = getSupabaseClient();
    getFirmId().then(async (fid) => {
      setFirmId(fid);
      const { data } = await sb.from("clients").select("id, client_name").eq("firm_id", fid).eq("is_active", true).order("client_name");
      setClients((data ?? []) as Client[]);
      if (data && data.length > 0) setSelectedClientId((data[0] as Client).id);
    }).catch(() => setError("Failed to load")).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selectedClientId || !firmId) return;
    loadSuppliers();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedClientId, firmId]);

  async function loadSuppliers() {
    if (!selectedClientId || !firmId) return;
    const sb = getSupabaseClient();
    const { data } = await sb.from("suppliers").select("*").eq("firm_id", firmId).eq("client_id", selectedClientId).order("supplier_name");
    setSuppliers((data ?? []) as Supplier[]);
  }

  function openAdd() {
    setEditingId(null);
    setForm(BLANK_FORM);
    setBillRs("");
    setShowModal(true);
  }

  function openEdit(s: Supplier) {
    setEditingId(s.id);
    setForm({
      supplier_name: s.supplier_name,
      gstin: s.gstin ?? "",
      pan: s.pan ?? "",
      tds_section: s.tds_section ?? "",
      tds_rate_percent: s.tds_rate_percent !== null ? String(s.tds_rate_percent) : "",
      credit_limit_rs: s.credit_limit_paise ? String(s.credit_limit_paise / 100) : "",
      payment_terms_days: String(s.payment_terms_days),
      is_active: s.is_active,
    });
    setBillRs("");
    setShowModal(true);
  }

  function onSectionChange(val: string) {
    const sec = TDS_SECTIONS.find(s => s.value === val);
    setForm(f => ({ ...f, tds_section: val, tds_rate_percent: sec && sec.defaultRate > 0 ? String(sec.defaultRate) : "" }));
  }

  async function handleSave() {
    if (!firmId || !selectedClientId) return;
    if (!form.supplier_name.trim()) { setError("Supplier name is required"); return; }
    setSaving(true);
    setError(null);
    const sb = getSupabaseClient();
    const payload = {
      firm_id: firmId,
      client_id: selectedClientId,
      supplier_name: form.supplier_name.trim(),
      gstin: form.gstin.trim() || null,
      pan: form.pan.trim() || null,
      tds_section: form.tds_section || null,
      tds_rate_percent: form.tds_rate_percent ? parseFloat(form.tds_rate_percent) : null,
      credit_limit_paise: rsToP(form.credit_limit_rs),
      payment_terms_days: parseInt(form.payment_terms_days || "30"),
      is_active: form.is_active,
    };
    let err;
    if (editingId) {
      ({ error: err } = await sb.from("suppliers").update(payload).eq("id", editingId));
    } else {
      ({ error: err } = await sb.from("suppliers").insert(payload));
    }
    setSaving(false);
    if (err) { setError(err.message); return; }
    setShowModal(false);
    await loadSuppliers();
  }

  async function toggleActive(id: string, cur: boolean) {
    const sb = getSupabaseClient();
    await sb.from("suppliers").update({ is_active: !cur }).eq("id", id);
    await loadSuppliers();
  }

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link href="/accounting" className="text-[#94A3B8] hover:text-[#475569]">
          <ChevronLeft className="w-4 h-4" />
        </Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-[#0F172A]">Supplier Master</h1>
          <p className="text-sm text-[#64748B] mt-0.5">TDS section mapping &amp; credit terms</p>
        </div>
        <Button onClick={openAdd} size="sm" className="flex items-center gap-1">
          <Plus className="w-4 h-4" /> Add Supplier
        </Button>
      </div>

      {error && <div className="bg-red-50 text-red-700 text-sm px-4 py-3 rounded-lg">{error}</div>}

      {/* Client selector */}
      <Card>
        <CardContent className="pt-4 pb-4">
          <label className="text-xs font-medium text-[#334155] block mb-1">Select Client</label>
          <div className="w-full max-w-xs">
            <ClientLookup
              clients={clients}
              value={selectedClientId}
              onChange={setSelectedClientId}
              ariaLabel="Client"
              placeholder="Select client…"
            />
          </div>
        </CardContent>
      </Card>

      {/* Suppliers table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm flex items-center gap-2">
            <Users className="w-4 h-4 text-blue-600" />
            Suppliers ({suppliers.length})
          </CardTitle>
        </CardHeader>
        {loading ? (
          <TableSkeleton bare rows={5} cols={5} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-[#F8FAFC] text-xs text-[#64748B] uppercase tracking-wide">
                  <th className="px-4 py-3 text-left">Supplier Name</th>
                  <th className="px-4 py-3 text-left">GSTIN</th>
                  <th className="px-4 py-3 text-left">PAN</th>
                  <th className="px-4 py-3 text-left">TDS Section</th>
                  <th className="px-4 py-3 text-right">TDS Rate</th>
                  <th className="px-4 py-3 text-right">Credit Limit</th>
                  <th className="px-4 py-3 text-right">Payment Terms</th>
                  <th className="px-4 py-3 text-center">Status</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {suppliers.map(s => (
                  <tr key={s.id} className="hover:bg-[#F8FAFC]">
                    <td className="px-4 py-3 font-medium text-[#0F172A]">{s.supplier_name}</td>
                    <td className="px-4 py-3 text-[#475569] font-mono text-xs">{s.gstin ?? "—"}</td>
                    <td className="px-4 py-3 text-[#475569] font-mono text-xs">{s.pan ?? "—"}</td>
                    <td className="px-4 py-3">
                      {s.tds_section ? (
                        <span className="bg-amber-100 text-amber-700 text-xs px-2 py-0.5 rounded-full font-medium">{s.tds_section}</span>
                      ) : (
                        <span className="text-[#94A3B8] text-xs">No TDS</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right text-[#334155]">{s.tds_rate_percent != null ? `${s.tds_rate_percent}%` : "—"}</td>
                    <td className="px-4 py-3 text-right text-[#334155]">{s.credit_limit_paise ? fmtRs(s.credit_limit_paise) : "—"}</td>
                    <td className="px-4 py-3 text-right text-[#334155]">{s.payment_terms_days} days</td>
                    <td className="px-4 py-3 text-center">
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${s.is_active ? "bg-green-100 text-green-700" : "bg-[#F1F5F9] text-[#64748B]"}`}>
                        {s.is_active ? "Active" : "Inactive"}
                      </span>
                    </td>
                    <td className="px-4 py-3 flex gap-2 justify-end">
                      <button onClick={() => openEdit(s)} className="text-xs text-blue-600 hover:underline">Edit</button>
                      <button onClick={() => toggleActive(s.id, s.is_active)} className="text-xs text-[#94A3B8] hover:underline">
                        {s.is_active ? "Deactivate" : "Activate"}
                      </button>
                    </td>
                  </tr>
                ))}
                {suppliers.length === 0 && (
                  <tr><td colSpan={9} className="px-4 py-8 text-center text-[#94A3B8] text-sm">No suppliers yet. Add your first supplier.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* TDS Calculator */}
      {form.tds_section && showModal && (
        null // shown in modal below
      )}

      {/* Add/Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between px-5 py-4 border-b">
              <h2 className="text-sm font-semibold text-[#0F172A]">{editingId ? "Edit Supplier" : "Add Supplier"}</h2>
              <button onClick={() => setShowModal(false)}><X className="w-4 h-4 text-[#94A3B8]" /></button>
            </div>
            <div className="px-5 py-4 space-y-4">
              {error && <div className="bg-red-50 text-red-700 text-xs px-3 py-2 rounded-lg">{error}</div>}

              <div>
                <label className="text-xs font-medium text-[#334155] block mb-1">Supplier Name *</label>
                <input className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={form.supplier_name} onChange={e => setForm(f => ({ ...f, supplier_name: e.target.value }))} placeholder="e.g. ABC Contractors Pvt Ltd" />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-medium text-[#334155] block mb-1">GSTIN</label>
                  <input className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono" value={form.gstin} onChange={e => setForm(f => ({ ...f, gstin: e.target.value.toUpperCase() }))} placeholder="27AAAAA0000A1Z5" maxLength={15} />
                </div>
                <div>
                  <label className="text-xs font-medium text-[#334155] block mb-1">PAN</label>
                  <input className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono" value={form.pan} onChange={e => setForm(f => ({ ...f, pan: e.target.value.toUpperCase() }))} placeholder="AAAAA0000A" maxLength={10} />
                </div>
              </div>

              <div>
                <label className="text-xs font-medium text-[#334155] block mb-1">TDS Section</label>
                <select className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={form.tds_section} onChange={e => onSectionChange(e.target.value)}>
                  {TDS_SECTIONS.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
                </select>
              </div>

              {form.tds_section && (
                <div>
                  <label className="text-xs font-medium text-[#334155] block mb-1">TDS Rate %</label>
                  <input type="number" min="0" max="100" step="0.01" className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={form.tds_rate_percent} onChange={e => setForm(f => ({ ...f, tds_rate_percent: e.target.value }))} placeholder="e.g. 10" />
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-medium text-[#334155] block mb-1">Credit Limit (₹)</label>
                  <input type="number" min="0" className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={form.credit_limit_rs} onChange={e => setForm(f => ({ ...f, credit_limit_rs: e.target.value }))} placeholder="0" />
                </div>
                <div>
                  <label className="text-xs font-medium text-[#334155] block mb-1">Payment Terms (days)</label>
                  <input type="number" min="0" className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={form.payment_terms_days} onChange={e => setForm(f => ({ ...f, payment_terms_days: e.target.value }))} placeholder="30" />
                </div>
              </div>

              <div className="flex items-center gap-2">
                <input type="checkbox" id="is_active" checked={form.is_active} onChange={e => setForm(f => ({ ...f, is_active: e.target.checked }))} className="rounded" />
                <label htmlFor="is_active" className="text-xs text-[#334155]">Active supplier</label>
              </div>

              {/* TDS Calculator */}
              {form.tds_section && (
                <div className="bg-amber-50 rounded-lg p-4 space-y-3">
                  <div className="flex items-center gap-2">
                    <IndianRupee className="w-4 h-4 text-amber-600" />
                    <p className="text-xs font-semibold text-amber-800">Calculate TDS on Bill</p>
                  </div>
                  <p className="text-xs text-amber-700">IT Act Section {form.tds_section} — deduct at source before payment to supplier</p>
                  <div>
                    <label className="text-xs font-medium text-[#334155] block mb-1">Bill Amount (₹)</label>
                    <input type="number" min="0" className="w-full border border-amber-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-amber-400 bg-white" value={billRs} onChange={e => setBillRs(e.target.value)} placeholder="0" />
                  </div>
                  {billPaise > 0 && calcTdsRate > 0 && (
                    <div className="space-y-1">
                      <div className="flex justify-between text-xs text-[#475569]">
                        <span>Bill Amount</span>
                        <span className="font-medium">{fmtRs(billPaise)}</span>
                      </div>
                      <div className="flex justify-between text-xs text-[#475569]">
                        <span>TDS @ {calcTdsRate}% ({calcTdsSection?.label ?? form.tds_section})</span>
                        <span className="font-medium text-red-600">- {fmtRs(tdsAmount)}</span>
                      </div>
                      <div className="flex justify-between text-xs font-semibold text-[#0F172A] border-t border-amber-200 pt-1">
                        <span>Net Payment to Supplier</span>
                        <span className="text-green-700">{fmtRs(billPaise - tdsAmount)}</span>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="flex justify-end gap-3 px-5 py-4 border-t">
              <Button variant="outline" size="sm" onClick={() => setShowModal(false)}>Cancel</Button>
              <Button size="sm" onClick={handleSave} disabled={saving}>{saving ? "Saving…" : "Save Supplier"}</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
