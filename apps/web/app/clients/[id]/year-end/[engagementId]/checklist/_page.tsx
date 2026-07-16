"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { CheckCircle2, Circle, Clock, Ban, Loader2, ChevronRight } from "lucide-react";
import { yearEndApi, type ChecklistItem, type ChecklistItemStatus } from "@/lib/api/yearEnd";
import { getSupabaseClient } from "@/lib/supabase/client";

// ── Status cycle: not_started → in_progress → complete ────────────────────
const STATUS_CYCLE: Record<ChecklistItemStatus, ChecklistItemStatus> = {
  not_started: "in_progress",
  in_progress: "complete",
  complete: "not_started",
  na: "not_started",
};

const STATUS_LABEL: Record<ChecklistItemStatus, string> = {
  not_started: "Not Started",
  in_progress: "In Progress",
  complete: "Complete",
  na: "N/A",
};

const STATUS_BADGE: Record<ChecklistItemStatus, string> = {
  not_started: "bg-[#F1F5F9] text-[#94A3B8]",
  in_progress: "bg-amber-100 text-amber-700",
  complete: "bg-green-100 text-green-700",
  na: "bg-[#F1F5F9] text-[#64748B] line-through",
};

function StatusIcon({ status }: { status: ChecklistItemStatus }) {
  if (status === "complete") return <CheckCircle2 size={16} className="text-green-600 flex-shrink-0" />;
  if (status === "in_progress") return <Clock size={16} className="text-amber-500 flex-shrink-0" />;
  if (status === "na") return <Ban size={16} className="text-[#94A3B8] flex-shrink-0" />;
  return <Circle size={16} className="text-[#CBD5E1] flex-shrink-0" />;
}

export default function ChecklistPage() {
  const params = useParams<{ id: string; engagementId: string }>();
  const { engagementId } = params;

  const [items, setItems] = useState<ChecklistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [editingNotes, setEditingNotes] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitMsg, setSubmitMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Plain filtered select (year_end_checklists, RLS-scoped to the firm) —
      // no server-side computation for an existing list, so read directly
      // instead of round-tripping through the FastAPI backend. Mirrors
      // routers/year_end_checklist.py::list_checklist's own query (same
      // table, engagement_id filter, sequence_no ordering).
      const supabase = getSupabaseClient();
      const { data, error: sbError } = await supabase
        .from("year_end_checklists")
        .select("*")
        .eq("engagement_id", engagementId)
        .order("sequence_no");
      if (sbError) throw sbError;
      if (data && data.length > 0) {
        setItems(data as unknown as ChecklistItem[]);
      } else {
        // A brand-new engagement has no checklist rows yet. The backend
        // auto-initializes the 12 standard items on first read (a real
        // write — see list_checklist's "if not existing: insert…" branch),
        // so that seeding stays backend-routed; only fall back to it here.
        const res = await yearEndApi.checklist.list(engagementId);
        if (!res.success) throw new Error(res.error ?? "Failed to load checklist");
        setItems(res.data ?? []);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [engagementId]);

  useEffect(() => { load(); }, [load]);

  async function cycleStatus(item: ChecklistItem) {
    if (updatingId) return;
    const nextStatus = STATUS_CYCLE[item.status];
    setUpdatingId(item.id);
    try {
      const res = await yearEndApi.checklist.updateItem(engagementId, item.id, { status: nextStatus });
      if (!res.success) throw new Error(res.error ?? "Failed to update");
      setItems((prev) => prev.map((i) => (i.id === item.id ? res.data : i)));
    } catch {
      // silent — reload
      await load();
    } finally {
      setUpdatingId(null);
    }
  }

  async function markNA(item: ChecklistItem) {
    if (updatingId) return;
    setUpdatingId(item.id);
    try {
      const res = await yearEndApi.checklist.updateItem(engagementId, item.id, { status: "na" });
      if (!res.success) throw new Error(res.error ?? "Failed to update");
      setItems((prev) => prev.map((i) => (i.id === item.id ? res.data : i)));
    } catch {
      await load();
    } finally {
      setUpdatingId(null);
    }
  }

  async function saveNotes(item: ChecklistItem) {
    const notes = editingNotes[item.id] ?? item.notes ?? "";
    setUpdatingId(item.id);
    try {
      const res = await yearEndApi.checklist.updateItem(engagementId, item.id, { notes });
      if (!res.success) throw new Error(res.error ?? "Failed to save notes");
      setItems((prev) => prev.map((i) => (i.id === item.id ? res.data : i)));
      setEditingNotes((prev) => { const n = { ...prev }; delete n[item.id]; return n; });
    } catch {
      // ignore
    } finally {
      setUpdatingId(null);
    }
  }

  async function handleSubmitForReview() {
    setSubmitting(true);
    setSubmitMsg(null);
    try {
      const res = await yearEndApi.checklist.submitForReview(engagementId);
      if (!res.success) throw new Error(res.error ?? "Failed to submit");
      setSubmitMsg("Submitted for review successfully.");
    } catch (err) {
      setSubmitMsg(err instanceof Error ? err.message : "Failed to submit");
    } finally {
      setSubmitting(false);
    }
  }

  // Group by category
  const grouped: Record<string, ChecklistItem[]> = {};
  for (const item of items) {
    if (!grouped[item.category]) grouped[item.category] = [];
    grouped[item.category].push(item);
  }

  const complete = items.filter((i) => i.status === "complete" || i.status === "na").length;
  const total = items.length;
  const allDone = total > 0 && complete === total;
  const pct = total > 0 ? Math.round((complete / total) * 100) : 0;

  if (loading) {
    return (
      <div className="p-6 space-y-4 max-w-3xl">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-20 rounded-xl bg-[#F8FAFC] animate-pulse" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-red-50 border border-red-100 rounded-xl px-4 py-4 text-sm text-red-700">
          {error}
          <button onClick={load} className="ml-3 underline text-xs">Retry</button>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-5 max-w-3xl">
      {/* Progress bar */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
        <div className="flex items-center justify-between mb-2">
          <p className="text-xs font-semibold text-[#334155]">
            {complete} of {total} complete
          </p>
          <p className="text-xs text-[#94A3B8]">{pct}%</p>
        </div>
        <div className="w-full h-2 bg-[#F1F5F9] rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${allDone ? "bg-green-500" : "bg-blue-500"}`}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {/* Grouped items */}
      {Object.entries(grouped).map(([category, catItems]) => (
        <div key={category} className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <div className="px-4 py-2.5 border-b border-[#F8FAFC] bg-[#F8FAFC]">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-[#64748B]">{category}</p>
          </div>
          <div className="divide-y divide-[#F8FAFC]">
            {catItems.map((item) => {
              const isEditing = item.id in editingNotes;
              const noteValue = isEditing ? editingNotes[item.id] : (item.notes ?? "");

              return (
                <div key={item.id} className="px-4 py-3 space-y-2">
                  <div className="flex items-start gap-3">
                    {/* Status toggle */}
                    <button
                      onClick={() => cycleStatus(item)}
                      disabled={!!updatingId}
                      className="mt-0.5 disabled:opacity-50"
                      title={`Click to advance status (currently: ${STATUS_LABEL[item.status]})`}
                    >
                      {updatingId === item.id ? (
                        <Loader2 size={16} className="animate-spin text-[#94A3B8]" />
                      ) : (
                        <StatusIcon status={item.status} />
                      )}
                    </button>

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <p className={`text-xs font-medium text-[#1E293B] ${item.status === "na" ? "opacity-50" : ""}`}>
                          {item.label}
                        </p>
                        <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full ${STATUS_BADGE[item.status]}`}>
                          {STATUS_LABEL[item.status]}
                        </span>
                      </div>

                      {/* Notes */}
                      {isEditing ? (
                        <div className="mt-1.5 flex gap-2">
                          <input
                            value={editingNotes[item.id]}
                            onChange={(e) => setEditingNotes((prev) => ({ ...prev, [item.id]: e.target.value }))}
                            onKeyDown={(e) => { if (e.key === "Enter") saveNotes(item); if (e.key === "Escape") setEditingNotes((prev) => { const n = { ...prev }; delete n[item.id]; return n; }); }}
                            className="flex-1 text-xs px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
                            placeholder="Add notes…"
                            autoFocus
                          />
                          <button onClick={() => saveNotes(item)} className="text-xs text-blue-600 hover:underline">Save</button>
                        </div>
                      ) : noteValue ? (
                        <p
                          className="text-[10px] text-[#64748B] mt-1 cursor-pointer hover:text-[#334155]"
                          onClick={() => setEditingNotes((prev) => ({ ...prev, [item.id]: noteValue }))}
                        >
                          {noteValue}
                        </p>
                      ) : (
                        <button
                          onClick={() => setEditingNotes((prev) => ({ ...prev, [item.id]: "" }))}
                          className="text-[10px] text-[#CBD5E1] hover:text-[#94A3B8] mt-1"
                        >
                          + Add note
                        </button>
                      )}

                      {/* Completed by/at */}
                      {item.completed_by && (
                        <p className="text-[10px] text-[#94A3B8] mt-0.5">
                          Completed by {item.completed_by}
                          {item.completed_at && ` · ${new Date(item.completed_at).toLocaleDateString("en-IN")}`}
                        </p>
                      )}
                    </div>

                    {/* Mark N/A */}
                    {item.status !== "na" && (
                      <button
                        onClick={() => markNA(item)}
                        disabled={!!updatingId}
                        className="text-[10px] text-[#CBD5E1] hover:text-[#94A3B8] flex-shrink-0 disabled:opacity-50"
                        title="Mark N/A"
                      >
                        N/A
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ))}

      {/* Submit for Review */}
      {submitMsg && (
        <div className={`rounded-lg px-4 py-3 text-xs font-medium ${submitMsg.includes("success") ? "bg-green-50 text-green-700 border border-green-100" : "bg-red-50 text-red-700 border border-red-100"}`}>
          {submitMsg}
        </div>
      )}

      <div className="flex justify-end">
        <button
          onClick={handleSubmitForReview}
          disabled={!allDone || submitting}
          className="flex items-center gap-1.5 text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40"
        >
          {submitting && <Loader2 size={12} className="animate-spin" />}
          Submit for Review <ChevronRight size={12} />
        </button>
      </div>
      {!allDone && (
        <p className="text-[10px] text-[#94A3B8] text-right">
          Complete or mark N/A all {total - complete} remaining items to enable submission.
        </p>
      )}
    </div>
  );
}
