"use client";

/**
 * Advance Tax Tracker — IT Act Section 207/208/234B/234C
 * Taxpayers with annual tax liability > ₹10,000 must pay advance tax in 4 instalments.
 * Due dates: 15 Jun (15%), 15 Sep (45%), 15 Dec (75%), 15 Mar (100%)
 * Interest for default: Section 234B (234C for instalments) — 1% per month simple interest.
 *
 * All monetary calculations use integer paise arithmetic (never floating point).
 */

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { ChevronLeft, Save, AlertTriangle, CheckCircle, Clock } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { formatPaise } from "@/lib/services/formatting";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";
import { getClients } from "@/lib/data/clients";
import type { Client } from "@/lib/types";

// ─── Types ────────────────────────────────────────────────────────────────────

interface InstallmentDef {
  number: 1 | 2 | 3 | 4;
  label: string;
  percent: number; // cumulative %
  dueDate: string; // ISO date
}

interface AdvanceTaxRow {
  id: string | null; // null if not yet in DB
  firm_id: string;
  client_id: string;
  financial_year: string;
  installment_number: 1 | 2 | 3 | 4;
  due_date: string;
  required_percent: number;
  estimated_tax_paise: number;
  paid_amount_paise: number;
  paid_date: string | null;
  challan_number: string | null;
}

// ─── Installment schedule — IT Act Section 208 ───────────────────────────────

function installmentSchedule(fy: string): InstallmentDef[] {
  const startYear = parseInt(fy.split("-")[0]);
  return [
    { number: 1, label: "1st Installment (15 Jun)", percent: 15, dueDate: `${startYear}-06-15` },
    { number: 2, label: "2nd Installment (15 Sep)", percent: 45, dueDate: `${startYear}-09-15` },
    { number: 3, label: "3rd Installment (15 Dec)", percent: 75, dueDate: `${startYear}-12-15` },
    { number: 4, label: "4th Installment (15 Mar)", percent: 100, dueDate: `${startYear + 1}-03-15` },
  ];
}

// ─── Interest computation — IT Act Section 234C ──────────────────────────────
/**
 * Compute Section 234C interest for an installment.
 * Simple interest @ 1% per month (or part thereof).
 * Shortfall = required cumulative amount - actual cumulative paid
 */
function compute234CInterest(
  shortfallPaise: number,
  dueDate: string,
  paidDate: string | null
): number {
  if (shortfallPaise <= 0) return 0;
  const due = new Date(dueDate);
  const paid = paidDate ? new Date(paidDate) : new Date();
  const diffDays = Math.ceil((paid.getTime() - due.getTime()) / 86400000);
  if (diffDays <= 0) return 0;
  // Months = ceil(days / 30) — IT Act Section 234C
  const months = Math.ceil(diffDays / 30);
  // Interest = shortfall × 1% × months (integer paise)
  return Math.round((shortfallPaise * months) / 100);
}

const TODAY = new Date().toISOString().slice(0, 10);

function rowStatus(row: AdvanceTaxRow, requiredPaise: number): "paid" | "overdue" | "upcoming" {
  if (row.paid_amount_paise >= requiredPaise) return "paid";
  if (TODAY > row.due_date) return "overdue";
  return "upcoming";
}

const FY_OPTIONS = ["2026-27", "2025-26", "2024-25"];

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function AdvanceTaxPage() {
  const [clients, setClients] = useState<Client[]>([]);
  const [clientId, setClientId] = useState("");
  const [fy, setFy] = useState(FY_OPTIONS[0]);
  const [estimatedTaxRs, setEstimatedTaxRs] = useState("");
  const [rows, setRows] = useState<AdvanceTaxRow[]>([]);
  const [editPaidRs, setEditPaidRs] = useState<Record<number, string>>({});
  const [editPaidDate, setEditPaidDate] = useState<Record<number, string>>({});
  const [editChallan, setEditChallan] = useState<Record<number, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  useEffect(() => {
    getClients()
      .then(c => { setClients(c); if (c.length > 0) setClientId(c[0].id); })
      .catch(() => {});
  }, []);

  const loadData = useCallback(async () => {
    if (!clientId) return;
    setLoading(true);
    setError(null);
    try {
      const firmId = await getFirmId();
      const sb = getSupabaseClient();
      const schedule = installmentSchedule(fy);

      const { data } = await sb
        .from("advance_tax_payments")
        .select("*")
        .eq("client_id", clientId)
        .eq("financial_year", fy);

      const dbMap = new Map((data ?? []).map((r: AdvanceTaxRow) => [r.installment_number, r]));

      const built: AdvanceTaxRow[] = schedule.map(inst => {
        const existing = dbMap.get(inst.number);
        return existing ?? {
          id: null,
          firm_id: firmId,
          client_id: clientId,
          financial_year: fy,
          installment_number: inst.number,
          due_date: inst.dueDate,
          required_percent: inst.percent,
          estimated_tax_paise: 0,
          paid_amount_paise: 0,
          paid_date: null,
          challan_number: null,
        };
      });

      setRows(built);

      // Initialize edit state from DB
      const paidRs: Record<number, string> = {};
      const paidDate: Record<number, string> = {};
      const challan: Record<number, string> = {};
      for (const r of built) {
        paidRs[r.installment_number] = r.paid_amount_paise > 0 ? (r.paid_amount_paise / 100).toFixed(2) : "";
        paidDate[r.installment_number] = r.paid_date ?? "";
        challan[r.installment_number] = r.challan_number ?? "";
      }
      setEditPaidRs(paidRs);
      setEditPaidDate(paidDate);
      setEditChallan(challan);

      if (built.length > 0 && built[0].estimated_tax_paise > 0) {
        setEstimatedTaxRs((built[0].estimated_tax_paise / 100).toFixed(2));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [clientId, fy]);

  useEffect(() => { loadData(); }, [loadData]);

  // All money in integer paise
  const estimatedTaxPaise = Math.round(parseFloat(estimatedTaxRs || "0") * 100);
  const schedule = installmentSchedule(fy);

  async function handleSave() {
    if (!clientId || estimatedTaxPaise <= 0) {
      setError("Enter estimated annual tax first");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const firmId = await getFirmId();
      const sb = getSupabaseClient();
      const upserts = schedule.map(inst => {
        const paidPaise = Math.round(parseFloat(editPaidRs[inst.number] || "0") * 100);
        return {
          firm_id: firmId,
          client_id: clientId,
          financial_year: fy,
          installment_number: inst.number,
          due_date: inst.dueDate,
          required_percent: inst.percent,
          estimated_tax_paise: estimatedTaxPaise,
          paid_amount_paise: paidPaise,
          paid_date: editPaidDate[inst.number] || null,
          challan_number: editChallan[inst.number] || null,
        };
      });
      const { error: err } = await sb
        .from("advance_tax_payments")
        .upsert(upserts, { onConflict: "client_id,financial_year,installment_number" });
      if (err) throw new Error(err.message);
      setSaveMsg("Saved");
      setTimeout(() => setSaveMsg(null), 3000);
      await loadData();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  const totalPaid = Object.values(editPaidRs).reduce((s, v) => s + Math.round(parseFloat(v || "0") * 100), 0);
  const totalInterest = schedule.reduce((sum, inst) => {
    const cumRequired = Math.round((estimatedTaxPaise * inst.percent) / 100);
    // Cumulative paid up to this installment
    const cumPaid = schedule.filter(i => i.number <= inst.number).reduce(
      (s, i) => s + Math.round(parseFloat(editPaidRs[i.number] || "0") * 100), 0
    );
    const shortfall = Math.max(0, cumRequired - cumPaid);
    return sum + compute234CInterest(shortfall, inst.dueDate, editPaidDate[inst.number] || null);
  }, 0);

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/income-tax" className="text-white/30 hover:text-white/55"><ChevronLeft size={18} /></Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-white/85">Advance Tax Tracker</h1>
          <p className="text-sm text-white/40 mt-0.5">IT Act Section 207/208 — 4 installments per FY</p>
        </div>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap gap-3 items-end">
        <div>
          <label className="text-xs text-white/40">Client</label>
          <select value={clientId} onChange={e => setClientId(e.target.value)}
            className="block mt-1 border border-white/[0.07] rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500 min-w-[200px]">
            {clients.map(c => <option key={c.id} value={c.id}>{c.client_name}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs text-white/40">Financial Year</label>
          <select value={fy} onChange={e => setFy(e.target.value)}
            className="block mt-1 border border-white/[0.07] rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500">
            {FY_OPTIONS.map(f => <option key={f} value={f}>FY {f}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs text-white/40">Estimated Annual Tax (₹)</label>
          <input type="number" min="0" step="0.01" value={estimatedTaxRs}
            onChange={e => setEstimatedTaxRs(e.target.value)}
            className="block mt-1 border border-white/[0.07] rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500 w-48"
            placeholder="Enter tax amount" />
        </div>
        <Button onClick={handleSave} disabled={saving || !clientId}>
          <Save size={14} className="mr-1" /> {saving ? "Saving…" : "Save"}
        </Button>
      </div>

      {error && <div className="bg-red-50 text-red-700 rounded-lg px-5 py-4 text-sm">{error}</div>}
      {saveMsg && <div className="bg-green-50 text-green-700 rounded-lg px-5 py-2 text-sm">{saveMsg}</div>}

      {/* Summary */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        {[
          { label: "Estimated Tax", value: formatPaise(estimatedTaxPaise) },
          { label: "Total Paid", value: formatPaise(totalPaid) },
          { label: "Interest u/s 234C", value: formatPaise(totalInterest), red: totalInterest > 0 },
        ].map(s => (
          <Card key={s.label}>
            <CardContent className="pt-4 pb-3">
              <p className={`text-lg font-bold tabular-nums ${s.red ? "text-red-600" : "text-white/85"}`}>{s.value}</p>
              <p className="text-xs text-white/40 mt-0.5">{s.label}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Installment table */}
      <Card>
        {loading ? (
          <div className="p-8 text-center text-white/30 text-sm animate-pulse">Loading…</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/[0.05] text-xs text-white/30">
                  <th className="px-5 py-3 text-left">Installment</th>
                  <th className="px-3 py-3 text-left">Due Date</th>
                  <th className="px-3 py-3 text-right">Required %</th>
                  <th className="px-3 py-3 text-right">Required Amount</th>
                  <th className="px-3 py-3 text-right">Paid Amount (₹)</th>
                  <th className="px-3 py-3 text-left">Paid Date</th>
                  <th className="px-3 py-3 text-left">Challan No.</th>
                  <th className="px-3 py-3 text-right">Interest 234C</th>
                  <th className="px-5 py-3 text-left">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.03]">
                {schedule.map((inst, idx) => {
                  const cumRequired = Math.round((estimatedTaxPaise * inst.percent) / 100);
                  const cumPaid = schedule.filter(i => i.number <= inst.number).reduce(
                    (s, i) => s + Math.round(parseFloat(editPaidRs[i.number] || "0") * 100), 0
                  );
                  const shortfall = Math.max(0, cumRequired - cumPaid);
                  const interest = compute234CInterest(shortfall, inst.dueDate, editPaidDate[inst.number] || null);
                  const row = rows[idx];
                  const status = row ? rowStatus(row, cumRequired) : "upcoming";

                  const statusEl = status === "paid"
                    ? <span className="inline-flex items-center gap-1 text-xs text-green-700 bg-green-50 px-2 py-0.5 rounded-full"><CheckCircle size={11} /> Paid</span>
                    : status === "overdue"
                    ? <span className="inline-flex items-center gap-1 text-xs text-red-700 bg-red-50 px-2 py-0.5 rounded-full"><AlertTriangle size={11} /> Overdue</span>
                    : <span className="inline-flex items-center gap-1 text-xs text-white/55 bg-white/[0.06] px-2 py-0.5 rounded-full"><Clock size={11} /> Upcoming</span>;

                  return (
                    <tr key={inst.number} className="hover:bg-[#0e1017]">
                      <td className="px-5 py-3 text-sm font-medium">{inst.label}</td>
                      <td className="px-3 py-3 text-xs text-white/55">{inst.dueDate}</td>
                      <td className="px-3 py-3 text-sm text-right tabular-nums">{inst.percent}%</td>
                      <td className="px-3 py-3 text-sm text-right tabular-nums font-medium">{formatPaise(cumRequired)}</td>
                      <td className="px-3 py-3">
                        <input type="number" min="0" step="0.01"
                          value={editPaidRs[inst.number] ?? ""}
                          onChange={e => setEditPaidRs(prev => ({ ...prev, [inst.number]: e.target.value }))}
                          className="w-28 border border-white/[0.07] rounded px-2 py-1 text-sm text-right outline-none focus:border-blue-500" />
                      </td>
                      <td className="px-3 py-3">
                        <input type="date"
                          value={editPaidDate[inst.number] ?? ""}
                          onChange={e => setEditPaidDate(prev => ({ ...prev, [inst.number]: e.target.value }))}
                          className="border border-white/[0.07] rounded px-2 py-1 text-xs outline-none focus:border-blue-500" />
                      </td>
                      <td className="px-3 py-3">
                        <input type="text"
                          value={editChallan[inst.number] ?? ""}
                          onChange={e => setEditChallan(prev => ({ ...prev, [inst.number]: e.target.value }))}
                          placeholder="BSR/challan"
                          className="w-32 border border-white/[0.07] rounded px-2 py-1 text-xs outline-none focus:border-blue-500" />
                      </td>
                      <td className={`px-3 py-3 text-sm text-right tabular-nums ${interest > 0 ? "text-red-600 font-semibold" : "text-white/30"}`}>
                        {interest > 0 ? formatPaise(interest) : "—"}
                      </td>
                      <td className="px-5 py-3">{statusEl}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <p className="text-xs text-white/30 text-center">
        Interest computed under IT Act Section 234C @ 1% per month simple interest on shortfall.
        CA Review Required before filing.
      </p>
    </div>
  );
}
