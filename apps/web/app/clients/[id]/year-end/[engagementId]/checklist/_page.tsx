"use client";

import { useEffect, useState, useCallback } from "react";
import { CheckCircle2, Circle, Clock, Ban, Loader2, ChevronRight } from "lucide-react";
import { yearEndApi, type ChecklistItem, type ChecklistItemStatus } from "@/lib/api/yearEnd";
import { arrayOrEmpty } from "@/lib/api/shape";
import { Skeleton, TimelineSkeleton } from "@/components/ui/skeleton";
import { useEngagementId } from "../_engagementId";
import { useRefreshEngagement } from "../_engagementRefresh";
import { formatDate } from "@/lib/dates/format";
import { Button } from "@/components/ui/button";

// ── Status cycle: pending → in_progress → complete ─────────────────────────
const STATUS_CYCLE: Record<ChecklistItemStatus, ChecklistItemStatus> = {
  pending: "in_progress",
  in_progress: "complete",
  complete: "pending",
  not_applicable: "pending",
};

const STATUS_LABEL: Record<ChecklistItemStatus, string> = {
  pending: "Not Started",
  in_progress: "In Progress",
  complete: "Complete",
  not_applicable: "N/A",
};

const STATUS_BADGE: Record<ChecklistItemStatus, string> = {
  pending: "bg-ps-muted text-ps-hint",
  in_progress: "bg-state-attention-surface text-state-attention",
  complete: "bg-state-ready-surface text-state-ready",
  not_applicable: "bg-ps-muted text-ps-label line-through",
};

function StatusIcon({ status }: { status: ChecklistItemStatus }) {
  if (status === "complete") return <CheckCircle2 size={16} className="text-green-600 flex-shrink-0" />;
  if (status === "in_progress") return <Clock size={16} className="text-amber-500 flex-shrink-0" />;
  if (status === "not_applicable") return <Ban size={16} className="text-ps-hint flex-shrink-0" />;
  return <Circle size={16} className="text-ps-disabled flex-shrink-0" />;
}

export default function ChecklistPage() {
  // window.location, not useParams(): on the deployed static export every
  // dynamic segment is "_placeholder" (see ../_engagementId.ts).
  const engagementId = useEngagementId();
  // Submitting flips the engagement's own status from draft to in_review; the
  // workspace header's status chip only picks that up if it is told to
  // re-fetch (sweep-client-inventory-docs-reports-05).
  const refreshEngagement = useRefreshEngagement();

  const [items, setItems] = useState<ChecklistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [editingNotes, setEditingNotes] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitMsg, setSubmitMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    // Right after router.push the id is still "" for one render; the effect
    // re-runs once it is known. Never ask for the checklist of no engagement.
    if (!engagementId) return;
    setLoading(true);
    setError(null);
    try {
      // Through the backend, not PostgREST. This tab used to select from the
      // older checklist table migrations 067/155 declare, which exists only in
      // a migration-built database — production has `year_end_checklist_items`
      // — so every read came back 404 and the tab errored before its API
      // fallback could run.
      // routers/year_end_checklist.py::list_checklist reads the right table,
      // seeds the 12 standard items on an engagement's first read, and applies
      // _assert_engagement_scope, which the table's firm-only RLS cannot (it
      // has no client_id to scope an assignment on).
      const res = await yearEndApi.checklist.list(engagementId);
      if (!res.success) throw new Error(res.error ?? "Failed to load checklist");
      setItems(arrayOrEmpty<ChecklistItem>(res.data));
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
      setActionError(null);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to update status");
      await load();
    } finally {
      setUpdatingId(null);
    }
  }

  async function markNA(item: ChecklistItem) {
    if (updatingId) return;
    setUpdatingId(item.id);
    try {
      const res = await yearEndApi.checklist.updateItem(engagementId, item.id, { status: "not_applicable" });
      if (!res.success) throw new Error(res.error ?? "Failed to update");
      setItems((prev) => prev.map((i) => (i.id === item.id ? res.data : i)));
      setActionError(null);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to mark not applicable");
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
      setActionError(null);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to save notes");
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
      refreshEngagement();
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

  const complete = items.filter((i) => i.status === "complete" || i.status === "not_applicable").length;
  const total = items.length;
  const allDone = total > 0 && complete === total;
  const pct = total > 0 ? Math.round((complete / total) * 100) : 0;

  if (loading) {
    return (
      <div className="p-6 space-y-4 max-w-3xl mx-auto">
        <div className="bg-white rounded-xl border border-ps-border p-4">
          <div className="flex items-center justify-between mb-2">
            <Skeleton className="h-2.5 w-32" />
            <Skeleton className="h-2.5 w-8" />
          </div>
          <Skeleton className="h-2 w-full rounded-full" />
        </div>
        <div className="bg-white rounded-xl border border-ps-border p-4">
          <TimelineSkeleton rows={4} />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-state-problem-surface border border-state-problem-border rounded-xl px-4 py-4 text-sm text-state-problem">
          {error}
          <button onClick={load} className="ml-3 underline text-xs">Retry</button>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-5 max-w-3xl mx-auto">
      {actionError && (
        <div role="alert" className="bg-state-problem-surface border border-state-problem-border rounded-xl px-4 py-2.5 text-sm text-state-problem flex items-center justify-between gap-3">
          <span>{actionError}</span>
          <button onClick={() => setActionError(null)} className="text-red-400 hover:text-red-600 shrink-0">✕</button>
        </div>
      )}
      {/* Progress bar */}
      <div className="bg-white rounded-xl border border-ps-border p-4">
        <div className="flex items-center justify-between mb-2">
          <p className="text-xs font-semibold text-ps-body">
            {complete} of {total} complete
          </p>
          <p className="text-xs text-ps-hint">{pct}%</p>
        </div>
        <div className="w-full h-2 bg-ps-muted rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${allDone ? "bg-state-ready" : "bg-brand"}`}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {/* Grouped items */}
      {Object.entries(grouped).map(([category, catItems]) => (
        <div key={category} className="bg-white rounded-xl border border-ps-border overflow-hidden">
          <div className="px-4 py-2.5 border-b border-ps-border bg-ps-bg">
            <p className="text-3xs font-semibold uppercase tracking-wide text-ps-label">{category}</p>
          </div>
          <div className="divide-y divide-ps-border">
            {catItems.map((item) => {
              const isEditing = item.id in editingNotes;
              const noteValue = isEditing ? editingNotes[item.id] : (item.notes ?? "");

              return (
                <div key={item.id} className="px-4 py-3 space-y-2">
                  <div className="flex items-start gap-3">
                    {/* Status toggle */}
                    <Button variant="plain" size="none"
                      onClick={() => cycleStatus(item)}
                      disabled={!!updatingId}
                      className="mt-0.5 disabled:opacity-50"
                      title={`Click to advance status (currently: ${STATUS_LABEL[item.status]})`}
                    >
                      {updatingId === item.id ? (
                        <Loader2 size={16} className="animate-spin text-ps-hint" />
                      ) : (
                        <StatusIcon status={item.status} />
                      )}
                    </Button>

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <p className={`text-xs font-medium text-ps-ink ${item.status === "not_applicable" ? "opacity-50" : ""}`}>
                          {item.item_label}
                        </p>
                        <span className={`text-3xs font-medium px-1.5 py-0.5 rounded-full ${STATUS_BADGE[item.status]}`}>
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
                            className="flex-1 text-xs px-2 py-1 border border-ps-border rounded focus:outline-none focus:ring-1 focus:ring-brand"
                            placeholder="Add notes…"
                            autoFocus
                          />
                          <Button variant="plain" size="none" onClick={() => saveNotes(item)} className="text-xs text-blue-600 hover:underline">Save</Button>
                        </div>
                      ) : noteValue ? (
                        <p
                          className="text-3xs text-ps-label mt-1 cursor-pointer hover:text-ps-body"
                          onClick={() => setEditingNotes((prev) => ({ ...prev, [item.id]: noteValue }))}
                        >
                          {noteValue}
                        </p>
                      ) : (
                        <button
                          onClick={() => setEditingNotes((prev) => ({ ...prev, [item.id]: "" }))}
                          className="text-3xs text-ps-hint hover:text-ps-label mt-1"
                        >
                          + Add note
                        </button>
                      )}

                      {/* Completed by/at */}
                      {item.completed_by && (
                        <p className="text-3xs text-ps-hint mt-0.5">
                          Completed by {item.completed_by}
                          {item.completed_at && ` · ${formatDate(item.completed_at)}`}
                        </p>
                      )}
                    </div>

                    {/* Mark N/A */}
                    {item.status !== "not_applicable" && (
                      <Button variant="plain" size="none"
                        onClick={() => markNA(item)}
                        disabled={!!updatingId}
                        className="text-3xs text-ps-hint hover:text-ps-label flex-shrink-0 disabled:opacity-50"
                        title="Mark N/A"
                      >
                        N/A
                      </Button>
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
        <div className={`rounded-lg px-4 py-3 text-xs font-medium ${submitMsg.includes("success") ? "bg-green-50 text-green-700 border border-green-100" : "bg-state-problem-surface text-state-problem border border-state-problem-border"}`}>
          {submitMsg}
        </div>
      )}

      <div className="flex justify-end">
        <Button variant="plain" size="none"
          onClick={handleSubmitForReview}
          disabled={!allDone || submitting}
          className="flex items-center gap-1.5 text-xs px-4 py-2 bg-brand text-white rounded-lg hover:bg-brand-dark disabled:opacity-40"
        >
          {submitting && <Loader2 size={12} className="animate-spin" />}
          Submit for Review <ChevronRight size={12} />
        </Button>
      </div>
      {!allDone && (
        <p className="text-3xs text-ps-hint text-right">
          Complete or mark N/A all {total - complete} remaining items to enable submission.
        </p>
      )}
    </div>
  );
}
