"use client";

/**
 * Billable time that has not been invoiced (practice_management-11) — what it is
 * worth, and, apart from that, the time that has NO rate.
 *
 * Every figure here is the server's (`GET /api/billing/unbilled-work`, aggregated
 * in SQL where the rows are). The screen adds nothing up and multiplies nothing:
 * `total_value_paise` is minutes x rate / 60 in whole paise summed by the
 * database, and the "no rate" section is time nobody has priced — which is NOT
 * worth ₹0, and is never folded into the total. It is a to-do list: give each
 * hour a rate here, or record the person's or the engagement's rate once under
 * "Billing rates" and every later hour carries it.
 */
import { useCallback, useEffect, useState } from "react";
import { AlertCircle, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatPaise } from "@/lib/money/format";
import { formatDuration, setEntryRate } from "@/lib/data/timeTracking";
import { readRateInput } from "@/lib/time/rateInput";
import { nothingUnbilled, readUnbilledWork, type UnbilledWork } from "@/lib/time/unbilledWork";
import { formatDate } from "@/lib/services/formatting";
import type { Client } from "@/lib/types";

export function UnbilledWorkPanel({ clients, canEdit }: { clients: Client[]; canEdit: boolean }) {
  const [work, setWork] = useState<UnbilledWork | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [savingId, setSavingId] = useState<string | null>(null);

  const clientName = new Map(clients.map((c) => [c.id, c.client_name]));
  const nameOf = (id: string | null | undefined) =>
    id && id !== "unassigned" ? (clientName.get(id) ?? "Unknown client") : "No client";

  const load = useCallback(async () => {
    try {
      const r = await api.billing.unbilledWork();
      if (!r.success) {
        setError(r.error ?? "Unbilled work could not be loaded.");
        setWork(null);
        return;
      }
      setError(null);
      setWork(readUnbilledWork(r.data));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Unbilled work could not be loaded.");
      setWork(null);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const saveRate = async (entryId: string) => {
    const typed = readRateInput(drafts[entryId] ?? "");
    if (typed.kind === "clear") {
      setError("Enter a rate for this hour, or 0 if it is not to be billed.");
      return;
    }
    if (typed.kind === "invalid") { setError(typed.message); return; }
    setSavingId(entryId);
    try {
      await setEntryRate(entryId, typed.paise);
      setDrafts((d) => { const next = { ...d }; delete next[entryId]; return next; });
      setError(null);
      await load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to set the rate.");
    } finally {
      setSavingId(null);
    }
  };

  if (!work && !error) {
    return (
      <div className="flex items-center justify-center py-10 text-ps-hint">
        <Loader2 className="animate-spin mr-2" size={16} /> Loading…
      </div>
    );
  }

  const clientRows = work ? Object.entries(work.by_client) : [];
  const noRate = work?.no_rate;
  const hiddenNoRate = noRate ? Math.max(0, noRate.count - noRate.entries.length) : 0;

  return (
    <div className="space-y-4">
      {error && (
        <div role="alert" className="flex items-center gap-2 text-sm text-state-problem bg-state-problem-surface border border-state-problem-border rounded-lg px-4 py-3">
          <AlertCircle size={14} /> {error}
        </div>
      )}

      {work && (
        <>
          <div className="grid grid-cols-3 gap-4">
            <Card>
              <CardContent className="py-4">
                <p className="text-xs text-ps-label">Unbilled value</p>
                <p className="text-2xl font-bold text-ps-ink mt-1">{formatPaise(work.total_value_paise)}</p>
                <p className="text-xs text-ps-hint">time that has a rate, not yet invoiced</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="py-4">
                <p className="text-xs text-ps-label">Hours with a rate</p>
                <p className="text-2xl font-bold text-blue-600 mt-1">{formatDuration(work.priced_minutes)}</p>
                <p className="text-xs text-ps-hint">{formatDuration(work.total_minutes)} unbilled in all</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="py-4">
                <p className="text-xs text-ps-label">Hours with no rate</p>
                <p className="text-2xl font-bold text-state-problem mt-1">{formatDuration(noRate?.minutes ?? 0)}</p>
                <p className="text-xs text-ps-hint">{noRate?.count ?? 0} entries — not in the value</p>
              </CardContent>
            </Card>
          </div>

          {nothingUnbilled(work) && (
            <p className="text-sm text-ps-hint text-center py-6">No billable time is waiting to be invoiced.</p>
          )}

          {clientRows.length > 0 && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-semibold">By client</CardTitle>
              </CardHeader>
              <CardContent className="p-0 divide-y">
                {clientRows.map(([id, g]) => (
                  <div key={id} className="flex items-center gap-4 px-5 py-3">
                    <span className="flex-1 min-w-0 truncate text-sm text-gray-800">{nameOf(id)}</span>
                    <span className="text-xs text-ps-label">{formatDuration(g.minutes)} · {g.count} entries</span>
                    <span className="text-sm font-semibold text-gray-800 w-28 text-right">{formatPaise(g.value_paise)}</span>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}

          {noRate && noRate.count > 0 && (
            <Card className="border-state-problem-border">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-semibold">Time with no billing rate</CardTitle>
                <p className="text-xs text-ps-label">
                  Nobody had said what an hour of this was worth when it was recorded, so it is left out of the
                  value above rather than counted as nothing. Give each hour a rate here. Recording a person&apos;s
                  or an engagement&apos;s rate under Billing rates prices the hours recorded AFTER it — an hour
                  already logged keeps the rate it was logged with.
                </p>
              </CardHeader>
              <CardContent className="p-0 divide-y">
                {noRate.entries.map((e) => (
                  <div key={e.id} className="flex flex-wrap items-center gap-3 px-5 py-3">
                    <div className="flex-1 min-w-[12rem]">
                      <p className="text-sm text-gray-800 truncate">
                        {nameOf(e.client_id)}{e.user_name ? ` · ${e.user_name}` : ""}
                      </p>
                      <p className="text-2xs text-ps-hint truncate">
                        {e.started_at ? formatDate(e.started_at) : ""}
                        {e.description ? ` — ${e.description}` : ""}
                      </p>
                    </div>
                    <span className="text-sm text-gray-800">{formatDuration(e.duration_minutes ?? 0)}</span>
                    {canEdit && (
                      <div className="flex items-center gap-2">
                        <input
                          aria-label="Rate in rupees per hour"
                          inputMode="decimal"
                          value={drafts[e.id] ?? ""}
                          onChange={(ev) => setDrafts((d) => ({ ...d, [e.id]: ev.target.value }))}
                          placeholder="₹ / hour"
                          className="w-28 border rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
                        />
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={savingId === e.id || !(drafts[e.id] ?? "").trim()}
                          onClick={() => saveRate(e.id)}
                        >
                          {savingId === e.id ? <Loader2 className="animate-spin" size={13} /> : "Set rate"}
                        </Button>
                      </div>
                    )}
                  </div>
                ))}
                {hiddenNoRate > 0 && (
                  <p className="px-5 py-3 text-xs text-ps-label">
                    Showing the {noRate.entries.length} most recent of {noRate.count}; the rest appear here as
                    these are priced.
                  </p>
                )}
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
