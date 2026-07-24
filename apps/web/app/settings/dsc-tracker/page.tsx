"use client";

/**
 * DSC Tracker — Digital Signature Certificate expiry tracker
 * DSCs are required for GST filing (CGST Act), MCA filings (Companies Act 2013),
 * and Income Tax returns. Expire every 1-2 years.
 */

import { useState, useEffect, useCallback } from "react";
import { Shield, Plus, X, AlertCircle, AlertTriangle, CheckCircle } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { useToast } from "@/components/ui/use-toast";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function apiFetch(path: string, opts?: RequestInit) {
  const { data: { session } } = await getSupabaseClient().auth.getSession();
  const token = session?.access_token ?? "";
  const res = await fetch(`${API}${path}`, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts?.headers ?? {}),
    },
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json() as { error?: string; detail?: string };
      detail = body.error ?? body.detail ?? detail;
    } catch { /* not JSON */ }
    throw new Error(detail);
  }
  return res.json();
}

// ─── Types ───────────────────────────────────────────────────────────────────

interface DSCRecord {
  id: string;
  firm_id: string;
  holder_name: string;
  pan: string;
  dsc_type: "Class 2" | "Class 3";
  purpose: string;
  issued_by: string;
  issued_date: string;
  expiry_date: string;
  notes: string | null;
  created_at: string;
}

const DSC_TYPES = ["Class 2", "Class 3"];
const DSC_PURPOSES = ["GST", "MCA", "Income Tax", "All"];
const ISSUING_CAS = ["eMudhra", "NSDL e-Governance", "Sify Technologies", "CDAC", "MTNL TrustLine"];

const TODAY = new Date();

function getDaysRemaining(expiryDate: string): number {
  return Math.ceil((new Date(expiryDate).getTime() - TODAY.getTime()) / 86400000);
}

interface DSCStatus {
  label: string;
  style: string;
}

function getDSCStatus(expiryDate: string): DSCStatus {
  const days = getDaysRemaining(expiryDate);
  if (days < 0)  return { label: "Expired",      style: "bg-red-100 text-red-700" };
  if (days <= 30) return { label: "Renew Now",    style: "bg-amber-100 text-amber-700" };
  if (days <= 90) return { label: "Renew Soon",   style: "bg-yellow-100 text-yellow-700" };
  return              { label: "Valid",          style: "bg-green-100 text-green-700" };
}

// Seed data
// DSC records are loaded from the firm's real data; empty until added
// (no fictional DSC holders shown to users).

// ─── Add DSC Modal ────────────────────────────────────────────────────────────

function AddDSCModal({ onClose, onAdded }: {
  onClose: () => void;
  onAdded: (d: DSCRecord) => void;
}) {
  const { toast } = useToast();
  const [holderName, setHolderName] = useState("");
  const [pan, setPan] = useState("");
  const [dscType, setDscType] = useState<"Class 2" | "Class 3">("Class 3");
  const [purpose, setPurpose] = useState("All");
  const [issuingCA, setIssuingCA] = useState("eMudhra");
  const [issueDate, setIssueDate] = useState("");
  const [expiryDate, setExpiryDate] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function handleSubmit() {
    if (!holderName.trim() || !issueDate || !expiryDate) {
      setErr("Name, issue date and expiry date are required.");
      return;
    }
    setSaving(true); setErr(null);
    try {
      const res = await apiFetch("/api/dsc", {
        method: "POST",
        body: JSON.stringify({
          holder_name: holderName.trim(),
          pan: pan.trim().toUpperCase() || null,
          dsc_type: dscType,
          purpose,
          issued_by: issuingCA,
          issued_date: issueDate,
          expiry_date: expiryDate,
          notes: notes.trim() || null,
        }),
      });
      onAdded(res.data.dsc_record as DSCRecord);
      toast({ title: "DSC record added" });
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-[#0F172A]">Add DSC Record</h3>
          <button onClick={onClose}><X className="w-4 h-4 text-[#94A3B8]" /></button>
        </div>
        {err && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{err}</p>}
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2">
            <label className="text-xs font-medium text-[#334155] block mb-1">Full Name</label>
            <input className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={holderName} onChange={e => setHolderName(e.target.value)} placeholder="CA / Director name" />
          </div>
          <div>
            <label className="text-xs font-medium text-[#334155] block mb-1">PAN</label>
            <input className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm font-mono uppercase focus:outline-none focus:ring-2 focus:ring-blue-500" value={pan} onChange={e => setPan(e.target.value.toUpperCase())} placeholder="ABCDE1234F" maxLength={10} />
          </div>
          <div>
            <label className="text-xs font-medium text-[#334155] block mb-1">Type</label>
            <select className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={dscType} onChange={e => setDscType(e.target.value as "Class 2" | "Class 3")}>
              {DSC_TYPES.map(t => <option key={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs font-medium text-[#334155] block mb-1">Purpose</label>
            <select className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={purpose} onChange={e => setPurpose(e.target.value)}>
              {DSC_PURPOSES.map(p => <option key={p}>{p}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs font-medium text-[#334155] block mb-1">Issuing CA</label>
            <select className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={issuingCA} onChange={e => setIssuingCA(e.target.value)}>
              {ISSUING_CAS.map(c => <option key={c}>{c}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs font-medium text-[#334155] block mb-1">Issue Date</label>
            <input type="date" className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={issueDate} onChange={e => setIssueDate(e.target.value)} />
          </div>
          <div>
            <label className="text-xs font-medium text-[#334155] block mb-1">Expiry Date</label>
            <input type="date" className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={expiryDate} onChange={e => setExpiryDate(e.target.value)} />
          </div>
          <div className="col-span-2">
            <label className="text-xs font-medium text-[#334155] block mb-1">Notes</label>
            <input className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={notes} onChange={e => setNotes(e.target.value)} placeholder="Optional" />
          </div>
        </div>
        <div className="flex gap-2">
          <button onClick={onClose} className="flex-1 border border-[#E2E8F0] text-[#475569] text-sm py-2 rounded-lg">Cancel</button>
          <button onClick={handleSubmit} disabled={saving} className="flex-1 bg-blue-600 text-white text-sm py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50">
            {saving ? "Saving…" : "Add DSC"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export default function DSCTrackerPage() {
  const [dscs, setDscs] = useState<DSCRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [tableError, setTableError] = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // firm_id is derived server-side from the caller's JWT — no need to resolve it here
      const res = await apiFetch("/api/dsc");
      setDscs((res.data?.dsc_records ?? []) as DSCRecord[]);   // real data only; empty firm → empty state
      setTableError(null);
    } catch (e) {
      setTableError(e instanceof Error ? e.message : "Couldn't load DSC records.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const expiringIn30 = dscs.filter(d => { const days = getDaysRemaining(d.expiry_date); return days >= 0 && days <= 30; }).length;
  const expiringIn90 = dscs.filter(d => { const days = getDaysRemaining(d.expiry_date); return days >= 0 && days <= 90; }).length;
  const expired = dscs.filter(d => getDaysRemaining(d.expiry_date) < 0).length;

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-[#0F172A]">DSC Tracker</h1>
          <p className="text-sm text-[#64748B] mt-0.5">Digital Signature Certificate expiry tracker</p>
        </div>
        <button onClick={() => setShowModal(true)} className="flex items-center gap-1.5 bg-blue-600 text-white text-sm px-3 py-2 rounded-lg hover:bg-blue-700">
          <Plus className="w-4 h-4" /> Add DSC
        </button>
      </div>

      {/* Alert banner */}
      {expiringIn30 > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 flex gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
          <p className="text-sm font-medium text-amber-800">
            {expiringIn30} DSC{expiringIn30 > 1 ? "s" : ""} expiring within 30 days — renew immediately to avoid disruption to GST / MCA filings.
          </p>
        </div>
      )}

      {tableError && (
        <div className="bg-red-50 border border-red-100 rounded-lg px-4 py-3 flex items-start gap-2">
          <AlertCircle className="w-4 h-4 text-red-600 shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="text-sm text-red-700 font-medium">Couldn&apos;t load DSC records.</p>
            <p className="text-xs text-red-600 mt-0.5">{tableError}</p>
          </div>
          <button onClick={load} className="text-xs px-3 py-1.5 border border-red-200 rounded-lg hover:bg-red-100 text-red-700 shrink-0">
            Retry
          </button>
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          { icon: <Shield className="w-4 h-4 text-blue-600" />,    bg: "bg-blue-50",   label: "Total DSCs",         value: String(dscs.length), sub: "Tracked" },
          { icon: <AlertTriangle className="w-4 h-4 text-red-600" />,   bg: "bg-red-50",   label: "Expired",            value: String(expired),       sub: "Immediate action" },
          { icon: <AlertCircle className="w-4 h-4 text-amber-600" />,  bg: "bg-amber-50",  label: "Expiring (30 days)", value: String(expiringIn30), sub: "Renew Now" },
          { icon: <CheckCircle className="w-4 h-4 text-green-600" />,  bg: "bg-green-50",  label: "Expiring (90 days)", value: String(expiringIn90), sub: "Renew Soon" },
        ].map(c => (
          <div key={c.label} className="bg-white rounded-xl border border-[#F1F5F9] p-4">
            <div className="flex items-center gap-2 mb-3">
              <div className={`w-8 h-8 rounded-lg ${c.bg} flex items-center justify-center`}>{c.icon}</div>
              <span className="text-xs text-[#64748B]">{c.label}</span>
            </div>
            <p className="text-lg font-semibold text-[#0F172A]">{c.value}</p>
            <p className="text-xs text-[#94A3B8] mt-0.5">{c.sub}</p>
          </div>
        ))}
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-50">
          <h2 className="text-sm font-semibold text-[#0F172A]">DSC Records</h2>
          <p className="text-xs text-[#94A3B8] mt-0.5">Class 2/3 digital signatures for GST, MCA, Income Tax filings</p>
        </div>
        {loading ? <div className="px-5 py-10 text-center text-sm text-[#94A3B8]">Loading…</div> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-50">
                  {["Name", "PAN", "Type", "Purpose", "Issuing CA", "Issue Date", "Expiry Date", "Days Remaining", "Status"].map(h => (
                    <th key={h} className="text-left text-xs font-medium text-[#94A3B8] px-4 py-3">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {dscs.sort((a, b) => getDaysRemaining(a.expiry_date) - getDaysRemaining(b.expiry_date)).map(d => {
                  const days = getDaysRemaining(d.expiry_date);
                  const status = getDSCStatus(d.expiry_date);
                  return (
                    <tr key={d.id} className="hover:bg-[#F8FAFC]/50">
                      <td className="px-4 py-3">
                        <p className="text-sm font-medium text-[#0F172A]">{d.holder_name}</p>
                      </td>
                      <td className="px-4 py-3 text-xs font-mono text-[#475569]">{d.pan || "—"}</td>
                      <td className="px-4 py-3">
                        <span className="text-xs font-medium text-[#334155] bg-[#F1F5F9] px-1.5 py-0.5 rounded">{d.dsc_type}</span>
                      </td>
                      <td className="px-4 py-3 text-xs text-[#475569]">{d.purpose}</td>
                      <td className="px-4 py-3 text-xs text-[#475569]">{d.issued_by}</td>
                      <td className="px-4 py-3 text-xs text-[#475569]">{new Date(d.issued_date).toLocaleDateString("en-IN")}</td>
                      <td className="px-4 py-3 text-xs text-[#475569] font-medium">{new Date(d.expiry_date).toLocaleDateString("en-IN")}</td>
                      <td className="px-4 py-3 text-xs font-medium">
                        <span className={days < 0 ? "text-red-600" : days <= 30 ? "text-amber-600" : days <= 90 ? "text-yellow-600" : "text-green-600"}>
                          {days < 0 ? `${Math.abs(days)}d overdue` : `${days} days`}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex text-xs font-medium px-2 py-0.5 rounded-full ${status.style}`}>{status.label}</span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {showModal && (
        <AddDSCModal onClose={() => setShowModal(false)} onAdded={d => setDscs(prev => [...prev, d])} />
      )}
    </div>
  );
}
