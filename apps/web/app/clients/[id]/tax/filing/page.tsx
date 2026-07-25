"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { Plus, Loader2, FileText, ChevronRight, AlertTriangle, CheckCircle } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { TransactionListSkeleton } from "@/components/ui/skeleton";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function apiFetch(path: string, opts?: RequestInit) {
  const { supabase } = await import("@/lib/supabase/client");
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;
  const res = await fetch(`${BASE}${path}`, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts?.headers ?? {}),
    },
  });
  return res.json();
}

const STATUS_ORDER = ["draft", "review", "partner_review", "ready_for_filing", "filed"];
const STATUS_LABEL: Record<string, string> = {
  draft: "Draft",
  review: "Review",
  partner_review: "Partner Review",
  ready_for_filing: "Ready for Filing",
  filed: "Filed",
};
const STATUS_COLOR: Record<string, string> = {
  draft: "bg-[#F1F5F9] text-[#64748B]",
  review: "bg-amber-100 text-amber-700",
  partner_review: "bg-blue-100 text-blue-700",
  ready_for_filing: "bg-purple-100 text-purple-700",
  filed: "bg-green-100 text-green-700",
};

const ITR_FORMS = ["ITR-3", "ITR-5", "ITR-6", "ITR-7"];
const FY_OPTIONS = ["2025-26", "2024-25", "2023-24"];
const AY_OPTIONS = ["2026-27", "2025-26", "2024-25"];

interface Filing {
  id: string;
  itr_form: string;
  financial_year: string;
  assessment_year: string;
  status: string;
  acknowledgement_number: string | null;
  filing_date: string | null;
  created_at: string;
}

export default function ITRFilingPage() {
  const params = useParams<{ id: string }>();
  const clientId = params.id;

  const [filings, setFilings] = useState<Filing[]>([]);
  const [loading, setLoading] = useState(true);
  // Distinguishes "fetch failed" from "no ITR filings yet" — a masked
  // failure previously rendered identically to a genuinely empty list.
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [selectedFiling, setSelectedFiling] = useState<Filing | null>(null);

  // Create form
  const [fy, setFy] = useState(FY_OPTIONS[0]);
  const [ay, setAy] = useState(AY_OPTIONS[0]);
  const [form, setForm] = useState("ITR-6");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Transition
  const [transitioning, setTransitioning] = useState(false);
  const [transitionError, setTransitionError] = useState<string | null>(null);

  // Ack form
  const [showAck, setShowAck] = useState(false);
  const [ackNumber, setAckNumber] = useState("");
  const [ackDate, setAckDate] = useState("");
  const [savingAck, setSavingAck] = useState(false);

  const load = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true);
    // Plain read — routed directly to Supabase (RLS: firm_isolation) instead
    // of through the FastAPI backend, which cold-starts. Mirrors the exact
    // table/columns/filter/ordering of list_itr_filings in
    // apps/api/domain/income_tax/itr_workflow.py. Create/transition/acknowledge
    // remain backend-routed (workflow state-machine logic).
    const supabase = getSupabaseClient();
    const { data, error } = await supabase
      .from("itr_filings")
      .select("id, itr_form, financial_year, assessment_year, status, acknowledgement_number, filing_date, created_at")
      .eq("client_id", clientId)
      .order("created_at", { ascending: false });
    if (error) {
      setFilings([]);
      setLoadError(error.message || "Couldn't load ITR filings.");
    } else {
      setFilings((data as Filing[]) ?? []);
      setLoadError(null);
    }
    setLoading(false);
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  async function handleCreate() {
    setCreating(true);
    setCreateError(null);
    try {
      const res = await apiFetch("/api/itr/filings", {
        method: "POST",
        body: JSON.stringify({
          client_id: clientId,
          financial_year: fy,
          assessment_year: ay,
          itr_form: form,
        }),
      });
      if (!res.success) throw new Error(res.error ?? "Failed");
      setShowCreate(false);
      await load();
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Failed");
    } finally {
      setCreating(false);
    }
  }

  async function handleTransition(filing: Filing, newStatus: string) {
    setTransitioning(true);
    setTransitionError(null);
    try {
      const res = await apiFetch(`/api/itr/filings/${filing.id}/transition`, {
        method: "POST",
        body: JSON.stringify({ new_status: newStatus }),
      });
      if (!res.success) throw new Error(res.error ?? "Failed");
      setSelectedFiling(res.data);
      await load();
    } catch (err) {
      setTransitionError(err instanceof Error ? err.message : "Invalid transition");
    } finally {
      setTransitioning(false);
    }
  }

  async function handleRecordAck(filing: Filing) {
    setSavingAck(true);
    try {
      const res = await apiFetch(`/api/itr/filings/${filing.id}/acknowledge`, {
        method: "POST",
        body: JSON.stringify({ acknowledgement_number: ackNumber, filing_date: ackDate }),
      });
      if (!res.success) throw new Error(res.error ?? "Failed");
      setShowAck(false);
      setSelectedFiling(null);
      await load();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed");
    } finally {
      setSavingAck(false);
    }
  }

  const nextStatus = (current: string) => {
    const idx = STATUS_ORDER.indexOf(current);
    return idx >= 0 && idx < STATUS_ORDER.length - 1 ? STATUS_ORDER[idx + 1] : null;
  };

  return (
    <div className="p-6 max-w-3xl space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-[#1E293B]">ITR Preparation</h2>
          <p className="text-xs text-[#94A3B8] mt-0.5">IT Act §139 — Return of Income</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700"
        >
          <Plus size={12} /> New Filing
        </button>
      </div>

      {/* CA Review Banner */}
      <div className="flex items-center gap-2 bg-red-50 border border-red-200 rounded-xl px-4 py-2.5">
        <AlertTriangle size={13} className="text-red-500 flex-shrink-0" />
        <p className="text-xs font-medium text-red-800">
          CA REVIEW REQUIRED — Partner review mandatory before Ready for Filing. DO NOT AUTO-SUBMIT.
        </p>
      </div>

      {/* Workflow Status Legend */}
      <div className="flex items-center gap-1 overflow-x-auto pb-1">
        {STATUS_ORDER.map((s, i) => (
          <div key={s} className="flex items-center gap-1 flex-shrink-0">
            <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${STATUS_COLOR[s]}`}>
              {STATUS_LABEL[s]}
            </span>
            {i < STATUS_ORDER.length - 1 && <ChevronRight size={10} className="text-[#CBD5E1]" />}
          </div>
        ))}
      </div>

      {/* Create Form */}
      {showCreate && (
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-5 space-y-3">
          <p className="text-xs font-semibold text-[#334155]">New ITR Filing</p>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="text-[10px] text-[#64748B] mb-1 block">Form</label>
              <select value={form} onChange={e => setForm(e.target.value)}
                className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg">
                {ITR_FORMS.map(f => <option key={f}>{f}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[10px] text-[#64748B] mb-1 block">Financial Year</label>
              <select value={fy} onChange={e => setFy(e.target.value)}
                className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg">
                {FY_OPTIONS.map(f => <option key={f}>{f}</option>)}
              </select>
            </div>
            <div>
              <label className="text-[10px] text-[#64748B] mb-1 block">Assessment Year</label>
              <select value={ay} onChange={e => setAy(e.target.value)}
                className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg">
                {AY_OPTIONS.map(a => <option key={a}>{a}</option>)}
              </select>
            </div>
          </div>
          {createError && <p className="text-xs text-red-600">{createError}</p>}
          <div className="flex gap-2 justify-end">
            <button onClick={() => setShowCreate(false)} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded">Cancel</button>
            <button onClick={handleCreate} disabled={creating}
              className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded disabled:opacity-50 flex items-center gap-1">
              {creating && <Loader2 size={10} className="animate-spin" />} Create
            </button>
          </div>
        </div>
      )}

      {/* Filing List */}
      {loading ? (
        <TransactionListSkeleton rows={3} />
      ) : loadError ? (
        <div className="bg-white rounded-xl border border-red-200 text-center py-16 space-y-2">
          <p className="text-sm text-red-600 font-medium">{loadError}</p>
          <button onClick={() => load()} className="text-xs px-3 py-1 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
        </div>
      ) : filings.length === 0 ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] text-center py-16 space-y-2">
          <FileText size={28} className="text-gray-200 mx-auto" />
          <p className="text-sm text-[#64748B]">No ITR filings yet</p>
          <p className="text-xs text-[#94A3B8]">Click &quot;New Filing&quot; to start the ITR preparation workflow.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {filings.map(f => (
            <button
              key={f.id}
              onClick={() => setSelectedFiling(f)}
              className={`w-full bg-white rounded-xl border px-4 py-3 flex items-center gap-3 hover:bg-[#F8FAFC] text-left ${
                selectedFiling?.id === f.id ? "border-blue-200 bg-blue-50/30" : "border-[#F1F5F9]"
              }`}
            >
              <FileText size={16} className="text-blue-500 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-xs font-semibold text-[#1E293B]">
                  {f.itr_form} — FY {f.financial_year}
                </p>
                <p className="text-[10px] text-[#94A3B8]">
                  AY {f.assessment_year} · {new Date(f.created_at).toLocaleDateString("en-IN")}
                  {f.acknowledgement_number && ` · Ack: ${f.acknowledgement_number}`}
                </p>
              </div>
              <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full flex-shrink-0 ${STATUS_COLOR[f.status]}`}>
                {STATUS_LABEL[f.status]}
              </span>
            </button>
          ))}
        </div>
      )}

      {/* Filing Detail Panel */}
      {selectedFiling && (
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-5 space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-[#334155]">
              {selectedFiling.itr_form} — FY {selectedFiling.financial_year}
            </p>
            <button onClick={() => setSelectedFiling(null)} className="text-[10px] text-[#94A3B8] hover:text-[#64748B]">Close</button>
          </div>

          {/* Workflow Progress */}
          <div className="flex items-center gap-1">
            {STATUS_ORDER.map((s, i) => (
              <div key={s} className="flex items-center gap-1 flex-1">
                <div className={`h-1.5 flex-1 rounded-full ${
                  STATUS_ORDER.indexOf(selectedFiling.status) >= i ? "bg-blue-500" : "bg-[#E2E8F0]"
                }`} />
              </div>
            ))}
          </div>
          <div className="flex justify-between">
            {STATUS_ORDER.map(s => (
              <span key={s} className="text-[9px] text-[#94A3B8]">{STATUS_LABEL[s]}</span>
            ))}
          </div>

          {selectedFiling.status === "filed" && selectedFiling.acknowledgement_number && (
            <div className="flex items-center gap-2 bg-green-50 border border-green-100 rounded-lg p-3">
              <CheckCircle size={14} className="text-green-500" />
              <div>
                <p className="text-xs font-medium text-green-800">Filed Successfully</p>
                <p className="text-[10px] text-green-600">Ack: {selectedFiling.acknowledgement_number} · {selectedFiling.filing_date}</p>
              </div>
            </div>
          )}

          {transitionError && <p className="text-xs text-red-600">{transitionError}</p>}

          <div className="flex gap-2 flex-wrap">
            {nextStatus(selectedFiling.status) && selectedFiling.status !== "filed" && (
              <button
                onClick={() => handleTransition(selectedFiling, nextStatus(selectedFiling.status)!)}
                disabled={transitioning}
                className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg disabled:opacity-50 flex items-center gap-1 hover:bg-blue-700"
              >
                {transitioning && <Loader2 size={10} className="animate-spin" />}
                Move to {STATUS_LABEL[nextStatus(selectedFiling.status)!]}
              </button>
            )}
            {selectedFiling.status === "ready_for_filing" && !showAck && (
              <button
                onClick={() => setShowAck(true)}
                className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]"
              >
                Record Acknowledgement
              </button>
            )}
          </div>

          {showAck && (
            <div className="border border-[#E2E8F0] rounded-xl p-4 space-y-3">
              <p className="text-xs font-medium text-[#334155]">Record Filing Acknowledgement</p>
              <p className="text-[10px] text-amber-700 bg-amber-50 p-2 rounded">
                CA REVIEW REQUIRED — Only record after manually filing on Income Tax Portal
              </p>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-[10px] text-[#64748B] mb-1 block">Acknowledgement Number</label>
                  <input value={ackNumber} onChange={e => setAckNumber(e.target.value)}
                    className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg" />
                </div>
                <div>
                  <label className="text-[10px] text-[#64748B] mb-1 block">Filing Date</label>
                  <input type="date" value={ackDate} onChange={e => setAckDate(e.target.value)}
                    className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg" />
                </div>
              </div>
              <div className="flex gap-2">
                <button onClick={() => setShowAck(false)} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded">Cancel</button>
                <button
                  onClick={() => handleRecordAck(selectedFiling)}
                  disabled={savingAck || !ackNumber || !ackDate}
                  className="text-xs px-3 py-1.5 bg-green-600 text-white rounded disabled:opacity-50 flex items-center gap-1"
                >
                  {savingAck && <Loader2 size={10} className="animate-spin" />}
                  Record as Filed
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
