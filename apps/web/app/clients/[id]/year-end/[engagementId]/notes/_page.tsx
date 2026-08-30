"use client";

import { useEffect, useState, useCallback } from "react";
import { Sparkles, Lock, Unlock, ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import { yearEndApi, type NoteToAccount } from "@/lib/api/yearEnd";
import { getSupabaseClient } from "@/lib/supabase/client";
import { Skeleton } from "@/components/ui/skeleton";
import { useEngagementId } from "../_engagementId";

const TYPE_BADGE: Record<string, string> = {
  auto: "bg-blue-100 text-blue-700",
  manual: "bg-[#F1F5F9] text-[#475569]",
};

function noteType(note: NoteToAccount): "auto" | "manual" {
  if (note.type) return note.type;
  return note.is_auto_generated ? "auto" : "manual";
}

function noteNumber(note: NoteToAccount): number {
  return note.note_number ?? note.sequence_no ?? 0;
}

export default function NotesPage() {
  // window.location, not useParams(): on the deployed static export every
  // dynamic segment is "_placeholder" (see ../_engagementId.ts).
  const engagementId = useEngagementId();

  const [notes, setNotes] = useState<NoteToAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState<Record<string, string>>({});
  const [savingId, setSavingId] = useState<string | null>(null);
  const [lockingId, setLockingId] = useState<string | null>(null);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Plain filtered select (notes_to_accounts, RLS-scoped to the firm) —
      // no server-side computation for an existing list, so read directly
      // instead of round-tripping through the FastAPI backend. Mirrors
      // routers/year_end_notes.py::list_notes (same table, engagement_id
      // filter, sequence_no ordering). Note *generation* is a separate,
      // button-gated write (generateAll below) and stays backend-routed.
      // `year_end_notes`, NOT `notes_to_accounts`. Migration 067 named the table
      // notes_to_accounts; production was built by a divergent Studio migration
      // that called it year_end_notes, and migration 252's audit resolved the
      // split by repointing the ROUTERS at the real name rather than creating a
      // duplicate table. This query was missed in that pass, so it has been
      // asking PostgREST for a table production does not have — the Notes tab
      // could not load for anyone.
      //
      // The repository's migrations still describe notes_to_accounts, so the
      // schema replay in CI builds it and every static check here passes. That
      // is exactly the blind spot migration 252's header warns about: CI
      // validates the schema the repository DESCRIBES, not the one production
      // HAS.
      const supabase = getSupabaseClient();
      const { data, error: sbError } = await supabase
        .from("year_end_notes")
        .select("*")
        .eq("engagement_id", engagementId)
        .order("sequence_no");
      if (sbError) throw sbError;
      setNotes((data as NoteToAccount[]) ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [engagementId]);

  useEffect(() => { load(); }, [load]);

  function showToast(msg: string, ok: boolean) {
    setToast({ msg, ok });
    setTimeout(() => setToast(null), 4000);
  }

  async function handleGenerateAll() {
    setGenerating(true);
    try {
      const res = await yearEndApi.notes.generateAll(engagementId);
      if (!res.success) throw new Error(res.error ?? "Failed to generate notes");
      setNotes(res.data ?? []);
      showToast("All notes generated successfully", true);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Failed to generate", false);
    } finally {
      setGenerating(false);
    }
  }

  async function handleSave(note: NoteToAccount) {
    const content = editContent[note.id] ?? note.content ?? "";
    setSavingId(note.id);
    try {
      const res = await yearEndApi.notes.update(engagementId, note.id, { content });
      if (!res.success) throw new Error(res.error ?? "Failed to save");
      setNotes((prev) => prev.map((n) => (n.id === note.id ? res.data : n)));
      setEditContent((prev) => { const n = { ...prev }; delete n[note.id]; return n; });
      showToast("Note saved", true);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Save failed", false);
    } finally {
      setSavingId(null);
    }
  }

  async function handleLock(note: NoteToAccount) {
    setLockingId(note.id);
    try {
      const res = await yearEndApi.notes.lock(engagementId, note.id);
      if (!res.success) throw new Error(res.error ?? "Failed to lock");
      setNotes((prev) => prev.map((n) => (n.id === note.id ? res.data : n)));
      showToast("Note locked", true);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Lock failed", false);
    } finally {
      setLockingId(null);
    }
  }

  if (loading) {
    return (
      <div className="p-6 space-y-2 max-w-3xl">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="bg-white rounded-xl border border-[#F1F5F9] px-4 py-3 flex items-center gap-3">
            <Skeleton className="h-3.5 w-3.5 rounded-sm shrink-0" />
            <Skeleton className="h-3 w-16 shrink-0" />
            <Skeleton className="h-4 w-20 rounded-full shrink-0" />
            <Skeleton className="h-3 flex-1" />
          </div>
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
    <div className="p-6 space-y-4 max-w-3xl">
      {toast && (
        <div className={`rounded-lg px-4 py-3 text-xs font-medium border ${toast.ok ? "bg-green-50 border-green-100 text-green-700" : "bg-red-50 border-red-100 text-red-700"}`}>
          {toast.msg}
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-[#334155]">
          {notes.length} note{notes.length !== 1 ? "s" : ""}
        </p>
        <button
          onClick={handleGenerateAll}
          disabled={generating}
          className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700 disabled:opacity-50"
        >
          {generating ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
          {generating ? "Generating…" : "Auto-Generate All Notes"}
        </button>
      </div>

      {notes.length === 0 && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] text-center py-14">
          <Sparkles size={28} className="text-gray-200 mx-auto mb-3" />
          <p className="text-sm text-[#64748B]">No notes yet</p>
          <p className="text-xs text-[#94A3B8] mt-1">Click &quot;Auto-Generate All Notes&quot; to create standard notes.</p>
        </div>
      )}

      {/* Notes list */}
      <div className="space-y-2">
        {notes.map((note) => {
          const isExpanded = expandedId === note.id;
          const isEditing = note.id in editContent;
          const contentValue = isEditing ? editContent[note.id] : (note.content ?? "");

          return (
            <div key={note.id} className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
              {/* Header row */}
              <div
                className="px-4 py-3 flex items-center gap-3 cursor-pointer hover:bg-[#F8FAFC]"
                onClick={() => setExpandedId(isExpanded ? null : note.id)}
              >
                {isExpanded ? (
                  <ChevronDown size={14} className="text-[#94A3B8] flex-shrink-0" />
                ) : (
                  <ChevronRight size={14} className="text-[#94A3B8] flex-shrink-0" />
                )}
                <span className="text-xs font-semibold text-[#334155] min-w-[56px]">
                  Note {noteNumber(note)}
                </span>
                <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full ${TYPE_BADGE[noteType(note)] ?? "bg-[#F1F5F9] text-[#475569]"}`}>
                  {noteType(note) === "auto" ? "Auto-generated" : "Manual"}
                </span>
                <p className="text-xs text-[#475569] flex-1 truncate">{note.title}</p>
                {note.is_locked && (
                  <span title="Locked"><Lock size={12} className="text-[#94A3B8] flex-shrink-0" /></span>
                )}
              </div>

              {/* Expanded content */}
              {isExpanded && (
                <div className="border-t border-[#F8FAFC] px-4 py-3 space-y-3">
                  {noteType(note) === "auto" ? (
                    // Auto-generated notes: display as formatted read-only view
                    <AutoNoteContent content={note.content} locked={note.is_locked} />
                  ) : (
                    // Manual notes: editable textarea
                    <div className="space-y-2">
                      {note.is_locked ? (
                        <p className="text-xs text-[#475569] whitespace-pre-wrap bg-[#F8FAFC] rounded-lg p-3">
                          {note.content || "(empty)"}
                        </p>
                      ) : (
                        <>
                          <textarea
                            value={contentValue}
                            onChange={(e) => setEditContent((prev) => ({ ...prev, [note.id]: e.target.value }))}
                            rows={5}
                            className="w-full text-xs px-3 py-2 border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y font-mono"
                            placeholder="Enter note content…"
                          />
                          {isEditing && (
                            <div className="flex gap-2 justify-end">
                              <button
                                onClick={() => setEditContent((prev) => { const n = { ...prev }; delete n[note.id]; return n; })}
                                className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded hover:bg-[#F8FAFC]"
                              >
                                Discard
                              </button>
                              <button
                                onClick={() => handleSave(note)}
                                disabled={savingId === note.id}
                                className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1"
                              >
                                {savingId === note.id && <Loader2 size={10} className="animate-spin" />}
                                Save
                              </button>
                            </div>
                          )}
                          {!isEditing && (
                            <button
                              onClick={() => setEditContent((prev) => ({ ...prev, [note.id]: note.content ?? "" }))}
                              className="text-xs text-blue-600 hover:underline"
                            >
                              Edit
                            </button>
                          )}
                        </>
                      )}
                    </div>
                  )}

                  {/* Lock button */}
                  {!note.is_locked && (
                    <div className="flex justify-end pt-1">
                      <button
                        onClick={() => handleLock(note)}
                        disabled={lockingId === note.id}
                        className="flex items-center gap-1.5 text-xs text-[#64748B] hover:text-[#334155] border border-[#E2E8F0] px-3 py-1.5 rounded-lg hover:bg-[#F8FAFC]"
                      >
                        {lockingId === note.id ? (
                          <Loader2 size={11} className="animate-spin" />
                        ) : (
                          <Lock size={11} />
                        )}
                        Lock Note
                      </button>
                    </div>
                  )}
                  {note.is_locked && (
                    <div className="flex items-center gap-1.5 text-[10px] text-[#94A3B8]">
                      <Unlock size={10} /> Note is locked — contact an admin to unlock.
                    </div>
                  )}

                  <p className="text-[10px] text-[#CBD5E1]">
                    Updated {new Date(note.updated_at).toLocaleDateString("en-IN")}
                  </p>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Auto-generated note renderer ───────────────────────────────────────────

function AutoNoteContent({ content, locked }: { content: string | null; locked: boolean }) {
  if (!content) {
    return <p className="text-xs text-[#94A3B8]">No content generated yet.</p>;
  }

  // Try to parse as JSON table structure; fall back to raw text
  try {
    const parsed = JSON.parse(content) as {
      headers?: string[];
      rows?: (string | number)[][];
      summary?: string;
    };

    if (parsed.headers && parsed.rows) {
      return (
        <div className="space-y-2">
          {parsed.summary && (
            <p className="text-xs text-[#475569]">{parsed.summary}</p>
          )}
          <div className="overflow-x-auto">
            <table className="w-full text-xs border-collapse">
              <thead>
                <tr className="border-b border-[#E2E8F0] text-[#94A3B8]">
                  {parsed.headers.map((h, i) => (
                    <th key={i} className="py-2 px-3 text-left font-semibold text-[10px]">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {parsed.rows.map((row, ri) => (
                  <tr key={ri} className="hover:bg-[#F8FAFC]">
                    {row.map((cell, ci) => (
                      <td key={ci} className="py-1.5 px-3 text-[#334155]">
                        {typeof cell === "number"
                          ? new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2 }).format(cell / 100)
                          : cell}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {locked && <p className="text-[10px] text-[#94A3B8]">🔒 Locked</p>}
        </div>
      );
    }
  } catch {
    // Not JSON — render as text
  }

  return (
    <p className={`text-xs text-[#475569] whitespace-pre-wrap bg-[#F8FAFC] rounded-lg p-3 ${locked ? "opacity-75" : ""}`}>
      {content}
    </p>
  );
}
