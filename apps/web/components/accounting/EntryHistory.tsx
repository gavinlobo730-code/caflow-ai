"use client";

/**
 * What ever happened to one journal entry — the Rule 3(1) edit log, asked
 * about a single row.
 *
 * WHY THIS EXISTS
 *   The proviso to Rule 3(1) of the Companies (Accounts) Rules 2014 requires
 *   an EDIT LOG, and this product writes a thorough one: migration 266 puts
 *   triggers on journal_entries AND journal_lines, and the line trigger keys
 *   its audit row to the PARENT ENTRY id precisely so this question can be
 *   asked. Nothing asked it. `GET /api/audit` already accepted entity_id and
 *   no screen passed one, so the answer existed and was unreachable — which
 *   is the whole of finding ACC-07.
 *
 * WHY BOTH TYPES
 *   `journal_entry` alone is the header: the date, the narration, the status.
 *   The AMOUNTS are on the lines, so an entry's history that omits
 *   `journal_line` omits what an auditor came to see. The two are asked for
 *   together, in one request.
 *
 * WHAT IT DOES NOT DO
 *   It does not reconstruct the entry as at a date. Every row carries the full
 *   before-and-after snapshot, so a reader can see what changed; assembling a
 *   point-in-time version from them is a different feature and would be a
 *   second opinion about the ledger, which this product deliberately does not
 *   offer — the ledger is journal_entries + journal_lines and nothing else.
 */

import { useCallback, useEffect, useState } from "react";
import { ChevronDown, ChevronRight, History } from "lucide-react";
import { api, type AuditEntry } from "@/lib/api";

/** A line's audit row is keyed to its parent entry, so one request covers both. */
export const JOURNAL_HISTORY_TYPES = "journal_entry,journal_line";

const PAGE = 25;

function istStamp(iso: string): string {
  // Stored UTC, shown IST — the rule for every time this product displays.
  try {
    return new Date(iso).toLocaleString("en-IN", {
      timeZone: "Asia/Kolkata", dateStyle: "medium", timeStyle: "short",
    });
  } catch {
    return iso;
  }
}

function actionLabel(action: string): string {
  return action.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function actionClass(action: string): string {
  if (action === "delete") return "bg-red-50 text-red-700";
  if (action === "create") return "bg-green-50 text-green-700";
  if (action === "approve") return "bg-blue-50 text-blue-700";
  return "bg-amber-50 text-amber-700";
}

/** The fields that actually moved, so a reader is not handed two whole rows. */
export function changedFields(entry: AuditEntry): string[] {
  const before = (entry.old_data ?? {}) as Record<string, unknown>;
  const after = (entry.new_data ?? {}) as Record<string, unknown>;
  const keys = Array.from(new Set([...Object.keys(before), ...Object.keys(after)]));
  const moved: string[] = [];
  for (const k of keys) {
    if (k === "updated_at") continue;   // every update moves it; it says nothing
    if (JSON.stringify(before[k]) !== JSON.stringify(after[k])) moved.push(k);
  }
  return moved.sort();
}

export default function EntryHistory({ entryId }: { entryId: string }) {
  const [open, setOpen] = useState(false);
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async (next?: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.audit.entityHistory(
        JOURNAL_HISTORY_TYPES, entryId, { limit: PAGE, cursor: next });
      if (!res.success) throw new Error(res.error || "Could not read the history");
      setEntries((prev) => next ? [...prev, ...(res.data?.entries ?? [])]
                                : (res.data?.entries ?? []));
      setCursor(res.data?.next_cursor ?? null);
      setLoaded(true);
    } catch (e) {
      // Partner-only: anyone else gets a 403, and that is not an error to
      // shout about on a page they are otherwise allowed to use.
      setError(e instanceof Error ? e.message : "Could not read the history");
    } finally {
      setLoading(false);
    }
  }, [entryId]);

  // Fetched only when opened. A history panel nobody expands should cost
  // nothing — the entry page's own load is what a CA is waiting for.
  useEffect(() => {
    if (open && !loaded && !loading) void load();
  }, [open, loaded, loading, load]);

  return (
    <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full px-5 py-3 flex items-center gap-2 text-left hover:bg-[#F8FAFC] transition-colors"
      >
        {open ? <ChevronDown className="w-4 h-4 text-[#94A3B8]" />
              : <ChevronRight className="w-4 h-4 text-[#94A3B8]" />}
        <History className="w-4 h-4 text-[#64748B]" />
        <span className="text-sm font-semibold text-[#0F172A]">History</span>
        <span className="text-xs text-[#94A3B8]">
          every change to this entry and its lines — Partner only
        </span>
      </button>

      {open && (
        <div className="border-t border-gray-50">
          {loading && entries.length === 0 && (
            <p className="px-5 py-6 text-xs text-[#94A3B8]">Reading the log…</p>
          )}
          {error && (
            <p className="px-5 py-6 text-xs text-red-600">{error}</p>
          )}
          {!loading && !error && loaded && entries.length === 0 && (
            <p className="px-5 py-6 text-xs text-[#94A3B8]">
              Nothing has changed since this entry was posted. A posted entry is
              immutable in this system — a correction is an append-only reversal,
              which appears as its own entry rather than as a change to this one.
            </p>
          )}
          {entries.length > 0 && (
            <ul className="divide-y divide-[#F8FAFC]">
              {entries.map((e) => {
                const moved = changedFields(e);
                return (
                  <li key={e.id} className="px-5 py-3 text-xs">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={`px-2 py-0.5 rounded-full font-medium ${actionClass(e.action)}`}>
                        {actionLabel(e.action)}
                      </span>
                      <span className="text-[#475569]">
                        {e.entity_type === "journal_line" ? "line" : "entry"}
                      </span>
                      <span className="text-[#94A3B8]">·</span>
                      <span className="text-[#334155]">{e.actor_email || "System"}</span>
                      <span className="text-[#94A3B8]">·</span>
                      <span className="text-[#64748B] tabular-nums">
                        {istStamp(e.created_at)} IST
                      </span>
                    </div>
                    {moved.length > 0 && (
                      <p className="mt-1 text-[#64748B]">
                        Changed: <span className="font-mono text-[11px]">{moved.join(", ")}</span>
                      </p>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
          {cursor && (
            <div className="px-5 py-3 border-t border-gray-50">
              <button
                onClick={() => { void load(cursor); }}
                disabled={loading}
                className="text-xs border border-[#E2E8F0] text-[#475569] px-3 py-1.5 rounded-md hover:bg-[#F8FAFC] disabled:opacity-40"
              >
                {loading ? "Loading…" : "Load more"}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
