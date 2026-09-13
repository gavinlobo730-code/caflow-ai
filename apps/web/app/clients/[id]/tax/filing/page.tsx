"use client";

import { useEffect, useState, useCallback } from "react";
import { Plus, Loader2, FileText, ChevronRight, AlertTriangle, CheckCircle } from "lucide-react";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { getSupabaseClient } from "@/lib/supabase/client";
import { TransactionListSkeleton } from "@/components/ui/skeleton";
import FilingDemoWizard, { fetchFilingDemoCapabilities } from "@/components/FilingDemoWizard";
import { assessmentYearChoicesAround, financialYearChoicesAround } from "@/lib/dates/periods";

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

// The forms are SERVED, not listed here (IT-23). This array said
// ["ITR-3","ITR-5","ITR-6","ITR-7"] while apps/api held verified field mappings
// and a committed Department JSON schema for all seven — so a salaried client
// (ITR-1/2) or a presumptive one (ITR-4) could not have a filing record created
// at all. `GET /api/itr/forms` answers off domain/income_tax/itr_json.ITR_FORMS;
// this is the fallback for the window where the frontend has redeployed ahead
// of the backend, in the same shape as the Schedule III caption fallback.
const ITR_FORMS_FALLBACK = ["ITR-1", "ITR-2", "ITR-3", "ITR-4", "ITR-5", "ITR-6", "ITR-7"];
// FROM THE CLOCK, NOT A LITERAL. This list ended at a year that is now in the
// past, so the current financial year could not be selected at all — broken on
// 1 April with nothing saying so. `financialYearChoicesAround` is the one
// helper (lib/dates/periods.ts); see
// scripts/a-financial-year-choice-comes-from-the-clock.test.ts.
const FY_OPTIONS = financialYearChoicesAround(null);
// FROM THE CLOCK, NOT A LITERAL — the same rule as the financial-year list,
// derived from it so the two cannot disagree about which year is current
// (IT Act §2(9): the AY is the FY plus one).
const AY_OPTIONS = assessmentYearChoicesAround(null);

// The three kinds a return can be, and their sections. SERVED by
// GET /api/itr/return-kinds — this is the fallback for the window where the
// frontend has redeployed ahead of the backend, the same shape as the form
// list above. It is a LABEL table only: every window and every s. 140B figure
// comes from the server, because those are statute (IT-23, migration 381).
const RETURN_KIND_FALLBACK: { return_type: string; section: string; needs_the_earlier_receipt: boolean }[] = [
  { return_type: "original", section: "s. 139(1)", needs_the_earlier_receipt: false },
  { return_type: "revised", section: "s. 139(5)", needs_the_earlier_receipt: true },
  { return_type: "updated", section: "s. 139(8A)", needs_the_earlier_receipt: true },
];
const KIND_LABEL: Record<string, string> = {
  original: "Original", revised: "Revised", updated: "Updated (ITR-U)",
};

interface ReturnWindow {
  is_open: boolean | null;
  closes_on: string | null;
  alternative_closes_on: string | null;
  caveats: string[];
  gaps: string[];
}
interface ReturnKind {
  return_type: string;
  section: string;
  needs_the_earlier_receipt: boolean;
  window?: ReturnWindow | null;
}

interface Filing {
  id: string;
  itr_form: string;
  financial_year: string;
  assessment_year: string;
  status: string;
  acknowledgement_number: string | null;
  filing_date: string | null;
  created_at: string;
  // Migration 381. Nullable in the type as well as the column: a row written
  // before the migration has no value, and `?? "original"` is what it means.
  return_type: string | null;
  original_acknowledgement_number: string | null;
  original_filing_date: string | null;
}

export default function ITRFilingPage() {
  // Not useParams(): apps/web is a static export and Cloudflare's 200-rewrite
  // serves the pre-rendered "_placeholder" HTML for every real client URL, so
  // useParams().id was the literal string "_placeholder" — the load below bailed
  // on its own guard and the page sat on its skeleton forever. useClientNav reads
  // the real UUID out of window.location; it is also the client_id the filing
  // demo posts, so a placeholder made every preview refuse.
  const { clientId } = useClientNav();

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
  const [forms, setForms] = useState<string[]>(ITR_FORMS_FALLBACK);
  const [kind, setKind] = useState("original");
  const [kinds, setKinds] = useState<ReturnKind[]>(RETURN_KIND_FALLBACK);
  const [originalAck, setOriginalAck] = useState("");
  const [originalAckDate, setOriginalAckDate] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Transition
  const [transitioning, setTransitioning] = useState(false);
  const [transitionError, setTransitionError] = useState<string | null>(null);

  // The generic filing walk-through (services/filing_demo/itr). Offered
  // only where the server says the demo exists — the dead-control rule.
  const [demoFlows, setDemoFlows] = useState<string[]>([]);
  const [demo, setDemo] = useState<{ id: string } | null>(null);

  // Ack form
  const [showAck, setShowAck] = useState(false);
  const [ackNumber, setAckNumber] = useState("");
  const [ackDate, setAckDate] = useState("");
  const [savingAck, setSavingAck] = useState(false);
  // One action at a time: every button that starts work waits for whichever
  // is already running. Guarding each on its own flag alone let two fire at
  // once, and the second could act on what the first was still changing.
  const actionInFlight = creating || savingAck || transitioning;

  const load = useCallback(async () => {
    // Clearing loading matters: this returns while the id is still unresolved,
    // and leaving loading true stranded the skeleton with nothing to resolve it.
    if (!clientId || clientId === "_placeholder") { setLoading(false); return; }
    setLoading(true);
    // Plain read — routed directly to Supabase (RLS: firm_isolation) instead
    // of through the FastAPI backend, which cold-starts. Mirrors the exact
    // table/columns/filter/ordering of list_itr_filings in
    // apps/api/domain/income_tax/itr_workflow.py. Create/transition/acknowledge
    // remain backend-routed (workflow state-machine logic).
    const supabase = getSupabaseClient();
    try {
      const { data, error } = await supabase
        .from("itr_filings")
        .select("id, itr_form, financial_year, assessment_year, status, acknowledgement_number, filing_date, created_at, return_type, original_acknowledgement_number, original_filing_date")
        .eq("client_id", clientId)
        .order("created_at", { ascending: false });
      if (error) throw new Error(error.message || "Couldn't load ITR filings.");
      setFilings((data as Filing[]) ?? []);
      setLoadError(null);
    } catch (e) {
      setFilings([]);
      setLoadError(e instanceof Error ? e.message : "Couldn't load ITR filings.");
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    let cancelled = false;
    fetchFilingDemoCapabilities().then((c) => {
      if (!cancelled) setDemoFlows(c.enabled ? c.flows : []);
    });
    return () => { cancelled = true; };
  }, []);
  useEffect(() => {
    let cancelled = false;
    apiFetch("/api/itr/forms").then((r) => {
      const served = (r?.data?.forms ?? []) as { form?: string }[];
      const names = served.map((f) => f.form).filter(Boolean) as string[];
      if (!cancelled && names.length) setForms(names);
    }).catch(() => {
      // The fallback above stands. A picker that empties itself because one
      // request failed is worse than one showing the seven it already knows.
    });
    return () => { cancelled = true; };
  }, []);

  // The windows are STATUTE and are served, never derived here — the same rule
  // the form list follows. Re-fetched when the assessment year changes,
  // because s. 139(5)'s date and s. 139(8A)'s two dates are both functions
  // of it.
  useEffect(() => {
    let cancelled = false;
    apiFetch(`/api/itr/return-kinds?assessment_year=${encodeURIComponent(ay)}`)
      .then((r) => {
        const served = (r?.data?.kinds ?? []) as ReturnKind[];
        if (!cancelled && served.length) setKinds(served);
      })
      .catch(() => {
        // The label fallback above stands, WITHOUT any window: a picker that
        // empties itself because one request failed is worse than one showing
        // the three kinds it already knows, and showing a date we could not
        // fetch would be worse than showing none.
      });
    return () => { cancelled = true; };
  }, [ay]);

  const selectedKind = kinds.find((k) => k.return_type === kind);

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
          return_type: kind,
          // Sent only where the kind needs them. The server refuses a revised
          // or updated return without the earlier receipt — the form carries
          // it — so an empty string here would produce a refusal that reads
          // like a bug rather than a missing field.
          original_acknowledgement_number: originalAck.trim() || null,
          original_filing_date: originalAckDate || null,
        }),
      });
      if (!res.success) throw new Error(res.error ?? "Failed");
      setShowCreate(false);
      setOriginalAck("");
      setOriginalAckDate("");
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
    <div className="p-6 max-w-3xl mx-auto space-y-4">
      {demo && (
        <FilingDemoWizard
          flow="itr"
          clientId={clientId}
          refData={{ filing_id: demo.id }}
          onClose={() => setDemo(null)}
        />
      )}
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
                {forms.map(f => <option key={f}>{f}</option>)}
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
          <div>
            <label className="text-[10px] text-[#64748B] mb-1 block">Kind of return</label>
            <select value={kind} onChange={e => setKind(e.target.value)}
              className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg">
              {kinds.map(k => (
                <option key={k.return_type} value={k.return_type}>
                  {KIND_LABEL[k.return_type] ?? k.return_type} — {k.section}
                </option>
              ))}
            </select>
          </div>

          {/* The window, exactly as the server states it — both dates where the
              two readings of s. 139(8A) disagree, and every caveat. Rendering
              one date and dropping the caveat is how a CA comes to rely on a
              figure nobody verified. */}
          {selectedKind?.window && (
            <div className={`rounded-lg border px-3 py-2 space-y-1 ${
              selectedKind.window.is_open === false
                ? "bg-red-50 border-red-200"
                : selectedKind.window.is_open === null
                  ? "bg-amber-50 border-amber-200"
                  : "bg-[#F8FAFC] border-[#E2E8F0]"
            }`}>
              <p className="text-[11px] font-medium text-[#334155]">
                {selectedKind.window.is_open === false
                  ? "This window has closed"
                  : selectedKind.window.is_open === null
                    ? "Whether this window is open is not settled"
                    : "Window open"}
                {selectedKind.window.closes_on && ` · closes ${selectedKind.window.closes_on}`}
                {selectedKind.window.alternative_closes_on
                  && ` (the other reading: ${selectedKind.window.alternative_closes_on})`}
              </p>
              {[...selectedKind.window.caveats, ...selectedKind.window.gaps].map((c, i) => (
                <p key={i} className="text-[10px] text-[#64748B]">{c}</p>
              ))}
            </div>
          )}

          {selectedKind?.needs_the_earlier_receipt && (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-[10px] text-[#64748B] mb-1 block">
                  Earlier return&apos;s acknowledgement number
                </label>
                <input value={originalAck} onChange={e => setOriginalAck(e.target.value)}
                  className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg font-mono"
                  placeholder="e.g. 123456789012345" />
              </div>
              <div>
                <label className="text-[10px] text-[#64748B] mb-1 block">
                  Earlier return&apos;s filing date
                </label>
                <input type="date" value={originalAckDate}
                  onChange={e => setOriginalAckDate(e.target.value)}
                  className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg" />
              </div>
              <p className="col-span-2 text-[10px] text-[#94A3B8]">
                Both are fields on the form itself, not bookkeeping: a revised
                or updated return re-declares a year already declared and quotes
                the earlier return&apos;s receipt.
              </p>
            </div>
          )}
          {createError && <p className="text-xs text-red-600">{createError}</p>}
          <div className="flex gap-2 justify-end">
            <button onClick={() => setShowCreate(false)} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded">Cancel</button>
            <button onClick={handleCreate} disabled={actionInFlight}
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
                <p className="text-xs font-semibold text-[#1E293B] flex items-center gap-1.5">
                  {f.itr_form} — FY {f.financial_year}
                  {/* Only where it is NOT the original: a badge on every row
                      says nothing, and the original is what a row without one
                      has always been. */}
                  {(f.return_type ?? "original") !== "original" && (
                    <span className="text-[9px] font-medium px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-800">
                      {KIND_LABEL[f.return_type as string] ?? f.return_type}
                    </span>
                  )}
                </p>
                <p className="text-[10px] text-[#94A3B8]">
                  AY {f.assessment_year} · {new Date(f.created_at).toLocaleDateString("en-IN")}
                  {f.acknowledgement_number && ` · Ack: ${f.acknowledgement_number}`}
                  {f.original_acknowledgement_number
                    && ` · supersedes ${f.original_acknowledgement_number}`}
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
                disabled={actionInFlight}
                className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg disabled:opacity-50 flex items-center gap-1 hover:bg-blue-700"
              >
                {transitioning && <Loader2 size={10} className="animate-spin" />}
                Move to {STATUS_LABEL[nextStatus(selectedFiling.status)!]}
              </button>
            )}
            {/* Only on a return that is ready to file, and only where the
                server says the walk-through exists — the dead-control rule. */}
            {selectedFiling.status === "ready_for_filing" && demoFlows.includes("itr") && (
              <button
                onClick={() => setDemo({ id: selectedFiling.id })}
                className="text-xs px-4 py-2 border border-amber-300 rounded-lg hover:bg-amber-50 text-amber-800"
              >
                File (demo)
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
                  disabled={actionInFlight || !ackNumber || !ackDate}
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
