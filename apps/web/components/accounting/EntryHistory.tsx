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
import { describeChanges } from "@/components/accounting/entryHistoryFields";
import { formatIstLabelled } from "@/lib/dates/formatIst";
import { LoadingRegion } from "@/components/ui/skeleton";
import { usePermissions } from "@/lib/auth/AuthContext";
import RequestAccess from "@/components/auth/RequestAccess";

/** A line's audit row is keyed to its parent entry, so one request covers both. */
export const JOURNAL_HISTORY_TYPES = "journal_entry,journal_line";

const PAGE = 25;

function actionLabel(action: string): string {
  return action.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function actionClass(action: string): string {
  if (action === "delete") return "bg-state-problem-surface text-state-problem";
  if (action === "create") return "bg-green-50 text-green-700";
  if (action === "approve") return "bg-blue-50 text-blue-700";
  return "bg-state-attention-surface text-state-attention";
}

export default function EntryHistory({ entryId }: { entryId: string }) {
  const [open, setOpen] = useState(false);
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  // The history of one entry is the audit log asked about one row, and it is read on the audit log's own permission
  // (`audit` `read`, POST-A-550). A person who does not hold it is told so, with a way to ask, and nothing is requested:
  // this panel used to send the request for everybody and print the server's refusal in red on a page the person was
  // otherwise allowed to use. Until the permissions are known nothing is withheld, as every gate here does.
  const { can, resolved } = usePermissions();
  const mayRead = !resolved || can("audit", "read");

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
      // Reached only by a person the screen believes may read the log; a refusal here is the server disagreeing, and is said.
      setError(e instanceof Error ? e.message : "Could not read the history");
    } finally {
      setLoading(false);
    }
  }, [entryId]);

  // Fetched only when opened. A history panel nobody expands should cost
  // nothing — the entry page's own load is what a CA is waiting for.
  useEffect(() => {
    if (open && mayRead && !loaded && !loading) void load();
  }, [open, mayRead, loaded, loading, load]);

  return (
    <div className="bg-white rounded-xl border border-ps-border overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full px-5 py-3 flex items-center gap-2 text-left hover:bg-ps-bg transition-colors"
      >
        {open ? <ChevronDown className="w-4 h-4 text-ps-hint" />
              : <ChevronRight className="w-4 h-4 text-ps-hint" />}
        <History className="w-4 h-4 text-ps-label" />
        <span className="text-sm font-semibold text-ps-ink">History</span>
        <span className="text-xs text-ps-hint">
          every change to this entry and its lines
        </span>
      </button>

      {open && (
        <div className="border-t border-ps-border">
          {!mayRead && (
            <div role="status" data-history-not-in-access className="px-5 py-4">
              <p className="text-xs text-ps-body">
                The history of changes is part of the audit log, which is not part of your access. Your Partner decides who can
                read it; if you need to, ask below.
              </p>
              <RequestAccess resource="audit" action="read" askedFrom="The history of a journal entry" />
            </div>
          )}
          {mayRead && loading && entries.length === 0 && (
            <LoadingRegion label="Reading the edit log" className="px-5 py-6 text-xs text-ps-hint">Reading the log…</LoadingRegion>
          )}
          {mayRead && error && (
            <p role="alert" className="px-5 py-6 text-xs text-state-problem">{error}</p>
          )}
          {mayRead && !loading && !error && loaded && entries.length === 0 && (
            <p className="px-5 py-6 text-xs text-ps-hint">
              Nothing has changed since this entry was posted. A posted entry is
              immutable in this system — a correction is an append-only reversal,
              which appears as its own entry rather than as a change to this one.
            </p>
          )}
          {mayRead && entries.length > 0 && (
            <ul className="divide-y divide-ps-border">
              {entries.map((e) => {
                const changes = describeChanges(e);
                return (
                  <li key={e.id} className="px-5 py-3 text-xs">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={`px-2 py-0.5 rounded-full font-medium ${actionClass(e.action)}`}>
                        {actionLabel(e.action)}
                      </span>
                      <span className="text-ps-label">
                        {e.entity_type === "journal_line" ? "line" : "entry"}
                      </span>
                      <span className="text-ps-hint">·</span>
                      <span className="text-ps-body">{e.actor_email || "System"}</span>
                      <span className="text-ps-hint">·</span>
                      <span className="text-ps-label tabular-nums">
                        {formatIstLabelled(e.created_at, e.created_at)}
                      </span>
                    </div>
                    {changes.length > 0 && (
                      <ul className="mt-1 space-y-0.5">
                        {changes.map((c) => (
                          <li key={c.key} className="text-ps-label">
                            {c.label}: <span className="text-ps-hint">{c.before}</span>
                            {" → "}
                            <span className="text-ps-ink">{c.after}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
          {cursor && (
            <div className="px-5 py-3 border-t border-ps-border">
              <button
                onClick={() => { void load(cursor); }}
                disabled={loading}
                className="text-xs border border-ps-border text-ps-label px-3 py-1.5 rounded-md hover:bg-ps-bg disabled:opacity-40"
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
