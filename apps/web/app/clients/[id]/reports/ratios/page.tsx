"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, RefreshCw, AlertTriangle, Info, Loader2, Check, X } from "lucide-react";
import {
  api, type ScheduleIiiRatioNote, type ScheduleIiiRatio,
} from "@/lib/api";
import { formatPaise } from "@/lib/services/formatting";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

/**
 * The eleven Schedule III ratios — Division I, General Instructions, Additional
 * Regulatory Information clause (Q), inserted by MCA Notification G.S.R. 207(E)
 * of 24 March 2021.
 *
 * ZERO BUSINESS LOGIC. Every figure, every numerator label, the preceding-year
 * comparison and the 25% test all come from /api/accounting/schedule-iii/ratios.
 * This file decides layout and formats basis points; it does not know what any
 * ratio means, and must not learn.
 *
 * WHAT THIS SCREEN IS FOR, WHICH IS NOT "SHOWING RATIOS"
 * Clause (Q) makes two demands beyond the numbers, and both are why the page
 * looks the way it does:
 *
 *   1. "The company shall explain the items included in numerator and
 *      denominator." So the two amounts are ON the row, with the words the
 *      backend supplies — they are part of the filing, not a tooltip.
 *
 *   2. "Further explanation shall be provided for any change in the ratio by
 *      more than 25% as compared to the preceding year." So a flagged row opens
 *      a box the CA types into, and the header counts what is still unanswered.
 *      A ratio table with no way to record the explanation would produce a note
 *      that cannot be filed.
 *
 * Two of the eleven come back unavailable by design rather than computed from a
 * guess. They are rendered as a stated reason, never as a dash — a blank reads
 * as "nothing to report", which is the opposite of what a gap means.
 */

/** bps -> display. 10,000 bps = 1.00. */
function formatBps(bps: number | null, unit: "times" | "percent"): string {
  if (bps === null) return "—";
  const v = bps / 100;                       // bps -> percentage points
  if (unit === "percent") return `${v.toFixed(2)}%`;
  return `${(v / 100).toFixed(2)}×`;
}

function formatVariance(bps: number | null): string {
  if (bps === null) return "—";
  const pct = bps / 100;
  return `${pct > 0 ? "+" : ""}${pct.toFixed(1)}%`;
}

function currentFY(): string {
  const now = new Date();
  const start = now.getMonth() + 1 >= 4 ? now.getFullYear() : now.getFullYear() - 1;
  return `${start}-${String(start + 1).slice(2)}`;
}

function fyOptions(): string[] {
  const start = Number(currentFY().split("-")[0]);
  return Array.from({ length: 6 }, (_, i) => {
    const y = start - i;
    return `${y}-${String(y + 1).slice(2)}`;
  });
}

export default function ClientRatioNotePage() {
  // Not useParams(): apps/web is a static export and Cloudflare's 200-rewrite
  // serves the pre-rendered "_placeholder" HTML for every real client URL.
  const { clientId } = useClientNav();
  const router = useRouter();

  const [fy, setFy] = useState(currentFY());
  const [note, setNote] = useState<ScheduleIiiRatioNote | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [principal, setPrincipal] = useState("");

  const load = useCallback(async () => {
    if (!clientId) return;
    setLoading(true);
    setError(null);
    try {
      const r = await api.accounting.scheduleIiiRatios(clientId, fy);
      if (!r.success) throw new Error(r.error ?? "Could not build the ratio note");
      setNote(r.data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not build the ratio note");
    } finally {
      setLoading(false);
    }
  }, [clientId, fy]);

  useEffect(() => { load(); }, [load]);

  const saveExplanation = useCallback(async (ratioKey: string, text: string | null) => {
    setSaving(ratioKey);
    setError(null);
    try {
      const r = await api.accounting.saveRatioExplanation({
        client_id: clientId, fy, ratio_key: ratioKey, explanation: text,
      });
      if (!r.success) throw new Error(r.error ?? "Could not record the explanation");
      setEditing(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not record the explanation");
    } finally {
      setSaving(null);
    }
  }, [clientId, fy, load]);

  const savePrincipal = useCallback(async (raw: string) => {
    setSaving("dscr");
    setError(null);
    try {
      const trimmed = raw.trim();
      // Rupees in the box, paise on the wire — every amount crosses the API as
      // integer paise (CLAUDE.md). Blank clears it back to the gap.
      const rupees = trimmed === "" ? null : Number(trimmed);
      if (rupees !== null && (!Number.isFinite(rupees) || rupees < 0)) {
        throw new Error("Principal repaid must be a number of rupees, and cannot be negative");
      }
      const r = await api.accounting.saveRatioInputs({
        client_id: clientId, fy,
        principal_repaid_paise: rupees === null ? null : Math.round(rupees * 100),
      });
      if (!r.success) throw new Error(r.error ?? "Could not record the figure");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not record the figure");
    } finally {
      setSaving(null);
    }
  }, [clientId, fy, load]);

  const outstanding = note?.needs_explanation_count ?? 0;

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <button
            onClick={() => router.push(`/clients/${clientId}/reports`)}
            className="flex items-center gap-1 text-[11px] text-[#94A3B8] hover:text-[#64748B] mb-1.5"
          >
            <ArrowLeft size={12} /> Reports
          </button>
          <h2 className="text-sm font-semibold text-[#1E293B]">Ratio analysis</h2>
          <p className="text-[11px] text-[#94A3B8] mt-0.5">
            {note?.statute ??
              "Schedule III to the Companies Act 2013, Division I — Additional Regulatory Information, clause (Q)"}
          </p>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <label className="text-[11px] text-[#64748B]">FY</label>
          <select
            value={fy}
            onChange={(e) => setFy(e.target.value)}
            className="text-[11px] border border-[#E2E8F0] rounded-lg px-2.5 py-1.5 text-[#334155] bg-white"
          >
            {fyOptions().map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
          <button
            onClick={load}
            className="flex items-center gap-1.5 text-[11px] text-[#64748B] hover:text-[#334155] border border-[#E2E8F0] rounded-lg px-2.5 py-1.5"
          >
            <RefreshCw size={12} /> Refresh
          </button>
        </div>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-[11px] text-[#94A3B8] py-8">
          <Loader2 size={14} className="animate-spin" /> Computing both years…
        </div>
      )}

      {error && (
        <div className="flex items-start gap-2.5 bg-red-50 border border-red-100 rounded-xl px-4 py-3">
          <AlertTriangle size={14} className="text-red-500 flex-shrink-0 mt-0.5" />
          <p className="text-[11px] text-red-700">{error}</p>
        </div>
      )}

      {!loading && note && (
        <>
          {outstanding > 0 && (
            <div className="flex items-start gap-2.5 bg-amber-50 border border-amber-100 rounded-xl px-4 py-3">
              <AlertTriangle size={14} className="text-amber-600 flex-shrink-0 mt-0.5" />
              <p className="text-[11px] text-amber-900">
                <span className="font-medium">
                  {outstanding} ratio{outstanding === 1 ? "" : "s"} moved by more than 25%
                </span>{" "}
                against {note.preceding_fy}. Clause (Q) requires an explanation for each
                before this note can be filed.
              </p>
            </div>
          )}

          {note.gaps.length > 0 && (
            <div className="bg-[#F8FAFC] border border-[#E2E8F0] rounded-xl px-4 py-3 space-y-2">
              {note.gaps.map((g) => (
                <div key={g.code} className="flex items-start gap-2.5">
                  <Info size={13} className="text-[#94A3B8] flex-shrink-0 mt-0.5" />
                  <p className="text-[10px] text-[#64748B]">{g.message}</p>
                </div>
              ))}
            </div>
          )}

          <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-50">
              <p className="text-xs font-semibold text-[#334155]">
                Ratios — {note.fy}
                {note.preceding_fy && (
                  <span className="font-normal text-[#94A3B8]"> compared with {note.preceding_fy}</span>
                )}
              </p>
              <p className="text-[10px] text-[#94A3B8] mt-0.5">
                The items in each numerator and denominator are shown because clause (Q)
                requires them to be explained — they are part of the disclosure.
              </p>
            </div>
            <div className="divide-y divide-gray-50">
              {note.ratios.map((r) => (
                <RatioRow
                  key={r.key}
                  ratio={r}
                  precedingFy={note.preceding_fy}
                  busy={saving === r.key}
                  editing={editing === r.key}
                  draft={draft}
                  onDraft={setDraft}
                  onEdit={() => { setEditing(r.key); setDraft(r.explanation ?? ""); }}
                  onCancel={() => setEditing(null)}
                  onSave={() => saveExplanation(r.key, draft.trim() || null)}
                  onClear={() => saveExplanation(r.key, null)}
                  principal={principal}
                  onPrincipal={setPrincipal}
                  onSavePrincipal={() => savePrincipal(principal)}
                />
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function RatioRow({
  ratio: r, precedingFy, busy, editing, draft, onDraft, onEdit, onCancel, onSave, onClear,
  principal, onPrincipal, onSavePrincipal,
}: {
  ratio: ScheduleIiiRatio;
  precedingFy: string | null;
  busy: boolean;
  editing: boolean;
  draft: string;
  onDraft: (v: string) => void;
  onEdit: () => void;
  onCancel: () => void;
  onSave: () => void;
  onClear: () => void;
  principal: string;
  onPrincipal: (v: string) => void;
  onSavePrincipal: () => void;
}) {
  const flagged = r.needs_explanation && !r.explanation;
  return (
    <div className={`px-4 py-3 ${flagged ? "bg-amber-50/40" : ""}`}>
      <div className="flex items-start gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-[#94A3B8] tabular-nums">{r.clause}</span>
            <p className="text-xs font-medium text-[#1E293B]">{r.label}</p>
          </div>
          {r.numerator && (
            <p className="text-[10px] text-[#64748B] mt-1">
              <span className="text-[#94A3B8]">Numerator</span> {r.numerator.label} ·{" "}
              <span className="tabular-nums">{formatPaise(r.numerator.paise)}</span>
            </p>
          )}
          {r.denominator && (
            <p className="text-[10px] text-[#64748B] mt-0.5">
              <span className="text-[#94A3B8]">Denominator</span> {r.denominator.label} ·{" "}
              <span className="tabular-nums">{formatPaise(r.denominator.paise)}</span>
            </p>
          )}
          {r.unavailable_reason && (
            <p className="text-[10px] text-amber-800 mt-1.5 bg-amber-50 border border-amber-100 rounded-lg px-2.5 py-1.5">
              {r.unavailable_reason}
            </p>
          )}
        </div>

        <div className="text-right flex-shrink-0 w-40">
          <p className="text-sm font-semibold tabular-nums text-[#1E293B]">
            {r.unavailable_reason ? "Not computed" : formatBps(r.value_bps, r.unit)}
          </p>
          {precedingFy && (
            <p className="text-[10px] text-[#94A3B8] mt-0.5 tabular-nums">
              {precedingFy}: {formatBps(r.prior_value_bps, r.unit)}
            </p>
          )}
          {r.variance_bps !== null && (
            <p className={`text-[10px] mt-0.5 tabular-nums ${
              r.needs_explanation ? "text-amber-700 font-medium" : "text-[#94A3B8]"
            }`}>
              {formatVariance(r.variance_bps)}
            </p>
          )}
          {r.needs_explanation && r.variance_bps === null && (
            <p className="text-[10px] mt-0.5 text-amber-700 font-medium">
              was nil last year
            </p>
          )}
        </div>
      </div>

      {/* The one figure the books cannot supply, entered where it is missed. */}
      {r.key === "dscr" && r.unavailable_reason && (
        <div className="mt-2 flex items-center gap-2">
          <label className="text-[10px] text-[#64748B]">Principal repaid this year (₹)</label>
          <input
            value={principal}
            onChange={(e) => onPrincipal(e.target.value)}
            placeholder="e.g. 200000"
            inputMode="decimal"
            className="text-[11px] border border-[#E2E8F0] rounded-lg px-2.5 py-1 w-40 text-[#334155]"
          />
          <button
            onClick={onSavePrincipal}
            disabled={busy}
            className="text-[10px] border border-[#E2E8F0] rounded-md px-2.5 py-1 text-[#64748B] hover:bg-[#F1F5F9] disabled:opacity-50"
          >
            {busy ? "…" : "Save"}
          </button>
        </div>
      )}

      {/* Clause (Q)'s second demand. */}
      {(r.needs_explanation || r.explanation) && (
        <div className="mt-2">
          {editing ? (
            <div className="flex items-start gap-2">
              <textarea
                value={draft}
                onChange={(e) => onDraft(e.target.value)}
                rows={2}
                placeholder="Why did this ratio move? This wording goes into the note."
                className="flex-1 text-[11px] border border-[#E2E8F0] rounded-lg px-2.5 py-1.5 text-[#334155]"
              />
              <button
                onClick={onSave}
                disabled={busy || !draft.trim()}
                className="text-[10px] border border-blue-200 bg-blue-50 text-blue-700 rounded-md px-2 py-1 hover:bg-blue-100 disabled:opacity-50"
              >
                {busy ? "…" : <Check size={12} />}
              </button>
              <button
                onClick={onCancel}
                className="text-[10px] border border-[#E2E8F0] rounded-md px-2 py-1 text-[#94A3B8] hover:bg-[#F1F5F9]"
              >
                <X size={12} />
              </button>
            </div>
          ) : r.explanation ? (
            <div className="flex items-start gap-2">
              <p className="text-[10px] text-[#334155] bg-[#F8FAFC] border border-[#E2E8F0] rounded-lg px-2.5 py-1.5 flex-1">
                {r.explanation}
              </p>
              <button onClick={onEdit}
                className="text-[10px] text-[#64748B] hover:underline px-1 py-1">Edit</button>
              <button onClick={onClear} disabled={busy}
                className="text-[10px] text-[#94A3B8] hover:underline px-1 py-1 disabled:opacity-50">Clear</button>
            </div>
          ) : (
            <button
              onClick={onEdit}
              className="text-[10px] border border-amber-200 bg-amber-50 text-amber-800 rounded-md px-2.5 py-1 hover:bg-amber-100"
            >
              Explain this movement
            </button>
          )}
        </div>
      )}
    </div>
  );
}
