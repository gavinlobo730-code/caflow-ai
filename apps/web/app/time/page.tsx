"use client";

import { readRateInput } from "@/lib/time/rateInput";
import { useState, useEffect, useCallback, useRef } from "react";
import {
  Play, Square, Plus, Trash2, Clock, AlertCircle,
  Loader2, X, IndianRupee, Download,
} from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  listTimeEntries,
  getRunningTimer,
  startTimer,
  stopTimer,
  createManualEntry,
  deleteTimeEntry,
  formatDuration,
  formatElapsed,
} from "@/lib/data/timeTracking";
import { getClients } from "@/lib/data/clients";
import type { TimeEntry, Client } from "@/lib/types";
import { formatDate, formatTime } from "@/lib/dates/format";
import { arrayOrEmpty } from "@/lib/api/shape";
import { formatPaise } from "@/lib/money/format";
import { usePermissions } from "@/lib/auth/AuthContext";
import { EngagementPicker } from "@/components/time/EngagementPicker";
import { UnbilledWorkPanel } from "@/components/time/UnbilledWorkPanel";
import { BillingRatesPanel } from "@/components/time/BillingRatesPanel";
import { confirmDialog } from "@/components/ui/confirm-dialog";
import { PageHeader } from "@/components/ui/page-header";
import { DateInput } from "@/components/ui/date-input";

type Tab = "mine" | "unbilled" | "rates";

export default function TimeTrackingPage() {
  const { can } = usePermissions();
  // The unbilled-work total and the billing rates are fee economics: Partner-only
  // on the server (`billing:read` / `billing:write`), and the tabs are offered only
  // to somebody the server will answer. The server is what refuses; this is courtesy.
  const canSeeBilling = can("billing", "read");
  const canEditRates = can("billing", "write");
  const [tab, setTab] = useState<Tab>("mine");
  const [rateNotice, setRateNotice] = useState<string | null>(null);
  const [entries, setEntries] = useState<TimeEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [clients, setClients] = useState<Client[]>([]);

  // Timer state
  const [isRunning, setIsRunning] = useState(false);
  const [runningEntry, setRunningEntry] = useState<TimeEntry | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Start timer form
  const [showStart, setShowStart] = useState(false);
  const [startClientId, setStartClientId] = useState("");
  const [startEngagementId, setStartEngagementId] = useState("");
  const [startDescription, setStartDescription] = useState("");
  const [startBillable, setStartBillable] = useState(true);
  const [starting, setStarting] = useState(false);

  // Manual entry form
  const [showManual, setShowManual] = useState(false);
  const [manualClientId, setManualClientId] = useState("");
  const [manualEngagementId, setManualEngagementId] = useState("");
  const [manualDescription, setManualDescription] = useState("");
  const [manualStarted, setManualStarted] = useState("");
  const [manualEnded, setManualEnded] = useState("");
  const [manualBillable, setManualBillable] = useState(true);
  const [manualHourlyRate, setManualHourlyRate] = useState("");
  const [manualSaving, setManualSaving] = useState(false);

  // Export
  const [exportClientId, setExportClientId] = useState("");
  const [exportDateFrom, setExportDateFrom] = useState("");
  const [exportDateTo, setExportDateTo] = useState("");
  const [exporting, setExporting] = useState<"csv" | "xlsx" | null>(null);

  const clientMap = new Map(clients.map(c => [c.id, c.client_name]));

  const loadTimer = useCallback(async () => {
    try {
      const state = await getRunningTimer();
      setIsRunning(state.is_running);
      setRunningEntry(state.entry ?? null);
      setElapsed(state.elapsed_seconds);
    } catch {
      /* timer check failure is non-fatal */
    }
  }, []);

  const loadEntries = useCallback(async () => {
    try {
      const { entries: e } = await listTimeEntries({ limit: 100 });
      setEntries(arrayOrEmpty(e));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load entries");
    }
  }, []);

  const loadClients = useCallback(async () => {
    try {
      const list = await getClients();
      setClients(list);
    } catch (e) {
      setClients([]);
      setError(e instanceof Error ? e.message : "Failed to load clients");
    }
  }, []);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        await Promise.all([loadTimer(), loadEntries(), loadClients()]);
      } finally {
        // Each loader already catches its own failure, so this is a backstop —
        // but it is the only thing standing between an unexpected rejection and
        // a page that never leaves its skeleton.
        setLoading(false);
      }
    })();
  }, [loadTimer, loadEntries, loadClients]);

  // Tick interval when timer running
  useEffect(() => {
    if (isRunning) {
      timerRef.current = setInterval(() => {
        setElapsed(s => s + 1);
      }, 1000);
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [isRunning]);

  const handleStartTimer = async () => {
    setStarting(true);
    try {
      const { entry, rate } = await startTimer({
        client_id: startClientId || undefined,
        engagement_id: startEngagementId || undefined,
        description: startDescription || undefined,
        is_billable: startBillable,
      });
      setRunningEntry(entry);
      setIsRunning(true);
      setElapsed(0);
      setShowStart(false);
      setStartDescription("");
      setStartClientId("");
      setStartEngagementId("");
      // The server's own sentence about the rate (why no engagement was chosen,
      // that the time will be listed as "no rate") — shown, never reworded.
      setRateNotice(rate && rate.notes.length ? rate.notes.join(" ") : null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to start timer");
    } finally {
      setStarting(false);
    }
  };

  const handleStopTimer = async () => {
    if (!runningEntry) return;
    try {
      const { rate } = await stopTimer(runningEntry.id);
      if (rate && rate.source === null && rate.notes.length) setRateNotice(rate.notes.join(" "));
      setIsRunning(false);
      setRunningEntry(null);
      setElapsed(0);
      await loadEntries();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to stop timer");
    }
  };

  const handleManualEntry = async () => {
    if (!manualStarted || !manualEnded) return;
    // An hourly rate is billed against every hour on the entry, so reading it
    // as ₹1 instead of ₹2,500 under-bills the client by the whole engagement.
    // A BLANK box is "no rate typed" — the server then uses the engagement's, or
    // the person's — and is not ₹0, which `readRateInput` keeps apart.
    const typedRate = readRateInput(manualHourlyRate);
    if (typedRate.kind === "invalid") {
      setError(typedRate.message);
      return;
    }
    const hourlyRate = typedRate.kind === "rate" ? typedRate.paise : undefined;
    setManualSaving(true);
    try {
      const { rate } = await createManualEntry({
        client_id: manualClientId || undefined,
        engagement_id: manualEngagementId || undefined,
        description: manualDescription || undefined,
        started_at: manualStarted,
        ended_at: manualEnded,
        is_billable: manualBillable,
        hourly_rate_paise: hourlyRate,
      });
      setRateNotice(rate && rate.notes.length ? rate.notes.join(" ") : null);
      setShowManual(false);
      setManualClientId("");
      setManualEngagementId("");
      setManualDescription("");
      setManualStarted("");
      setManualEnded("");
      setManualHourlyRate("");
      await loadEntries();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to save entry");
    } finally {
      setManualSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!(await confirmDialog({ message: "Delete this time entry?", danger: true, confirmLabel: "Delete" }))) return;
    try {
      await deleteTimeEntry(id);
      await loadEntries();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  };

  const handleExport = async (fmt: "csv" | "xlsx") => {
    setExporting(fmt);
    try {
      await api.timeEntries.exportEntries({
        fmt,
        client_id: exportClientId || undefined,
        date_from: exportDateFrom || undefined,
        date_to: exportDateTo || undefined,
      });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to export");
    } finally {
      setExporting(null);
    }
  };

  const totalMinutes = entries.reduce((s, e) => s + (e.duration_minutes ?? 0), 0);
  const billableMinutes = entries.filter(e => e.is_billable).reduce((s, e) => s + (e.duration_minutes ?? 0), 0);

  return (
    <div className="p-6 space-y-6 max-w-5xl mx-auto">
      <PageHeader
        title="Time Tracking"
        subtitle="Track billable and non-billable hours"
        actions={
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => setShowManual(true)} className="gap-1.5">
              <Plus size={14} /> Manual Entry
            </Button>
            {!isRunning && (
              <Button size="sm" onClick={() => setShowStart(true)} className="gap-1.5 bg-green-600 hover:bg-green-700">
                <Play size={14} /> Start Timer
              </Button>
            )}
          </div>
        }
      />

      {error && (
        <div role="alert" className="flex items-center gap-2 text-sm text-state-problem bg-state-problem-surface border border-state-problem-border rounded-lg px-4 py-3">
          <AlertCircle size={14} /> {error}
          <button onClick={() => setError(null)} className="ml-auto"><X size={14} /></button>
        </div>
      )}

      {rateNotice && (
        <div role="status" className="flex items-center gap-2 text-sm text-ps-body bg-ps-bg border rounded-lg px-4 py-3">
          <IndianRupee size={14} /> {rateNotice}
          <button onClick={() => setRateNotice(null)} className="ml-auto" aria-label="Dismiss"><X size={14} /></button>
        </div>
      )}

      {canSeeBilling && (
        <div role="tablist" className="flex gap-1 border-b">
          {([["mine", "Time"], ["unbilled", "Unbilled work"], ["rates", "Billing rates"]] as [Tab, string][]).map(([id, label]) => (
            <button
              key={id}
              role="tab"
              aria-selected={tab === id}
              onClick={() => setTab(id)}
              className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${
                tab === id ? "border-brand text-blue-600" : "border-transparent text-ps-label hover:text-ps-body"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      )}

      {canSeeBilling && tab === "unbilled" && <UnbilledWorkPanel clients={clients} canEdit={canEditRates} />}
      {canSeeBilling && tab === "rates" && <BillingRatesPanel clients={clients} canEdit={canEditRates} />}

      {(tab === "mine" || !canSeeBilling) && (<>
      {/* Live Timer */}
      {isRunning && runningEntry && (
        <Card className="border-green-200 bg-green-50">
          <CardContent className="py-4 flex items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="w-3 h-3 rounded-full bg-green-500 animate-pulse" />
              <div>
                <p className="text-sm font-semibold text-green-800">Timer Running</p>
                <p className="text-xs text-green-600">
                  {runningEntry.client_id ? (clientMap.get(runningEntry.client_id) ?? "Unknown client") : "No client"}
                  {runningEntry.description ? ` — ${runningEntry.description}` : ""}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-4">
              <span className="font-mono text-2xl font-bold text-green-800">{formatElapsed(elapsed)}</span>
              <Button
                size="sm"
                variant="outline"
                onClick={handleStopTimer}
                className="gap-1.5 border-green-400 text-green-700 hover:bg-green-100"
              >
                <Square size={13} /> Stop
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4">
        <Card>
          <CardContent className="py-4">
            <p className="text-xs text-ps-label">Total Hours</p>
            <p className="text-2xl font-bold text-ps-ink mt-1">{formatDuration(totalMinutes)}</p>
            <p className="text-xs text-ps-hint">{entries.length} entries</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4">
            <p className="text-xs text-ps-label">Billable Hours</p>
            <p className="text-2xl font-bold text-blue-600 mt-1">{formatDuration(billableMinutes)}</p>
            <p className="text-xs text-ps-hint">
              {totalMinutes > 0 ? Math.round((billableMinutes / totalMinutes) * 100) : 0}% of total
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4">
            <p className="text-xs text-ps-label">Non-Billable</p>
            <p className="text-2xl font-bold text-ps-label mt-1">{formatDuration(totalMinutes - billableMinutes)}</p>
            <p className="text-xs text-ps-hint">
              {totalMinutes > 0 ? Math.round(((totalMinutes - billableMinutes) / totalMinutes) * 100) : 0}% of total
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Export */}
      <Card>
        <CardContent className="py-3 flex flex-wrap items-end gap-3">
          <div>
            <label className="block text-xs font-medium text-ps-body mb-1">Client</label>
            <select
              value={exportClientId}
              onChange={e => setExportClientId(e.target.value)}
              className="border rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
            >
              <option value="">All clients</option>
              {clients.map(c => <option key={c.id} value={c.id}>{c.client_name}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-ps-body mb-1">From</label>
            <DateInput aria-label="Export from"
              value={exportDateFrom}
              onChange={v => setExportDateFrom(v)}
              className="border rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-ps-body mb-1">To</label>
            <DateInput aria-label="Export to"
              value={exportDateTo}
              onChange={v => setExportDateTo(v)}
              className="border rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
            />
          </div>
          <div className="flex gap-2 ml-auto">
            <Button variant="outline" size="sm" onClick={() => handleExport("csv")} disabled={exporting !== null} className="gap-1.5">
              {exporting === "csv" ? <Loader2 className="animate-spin" size={13} /> : <Download size={13} />} Export CSV
            </Button>
            <Button variant="outline" size="sm" onClick={() => handleExport("xlsx")} disabled={exporting !== null} className="gap-1.5">
              {exporting === "xlsx" ? <Loader2 className="animate-spin" size={13} /> : <Download size={13} />} Export XLSX
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Entries List */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-semibold">Recent Entries</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center py-10 text-ps-hint">
              <Loader2 className="animate-spin mr-2" size={16} /> Loading…
            </div>
          ) : entries.length === 0 ? (
            <div className="py-12 text-center text-ps-hint">
              <Clock size={28} className="mx-auto mb-2 opacity-30" />
              <p className="text-sm">No time entries yet</p>
            </div>
          ) : (
            <div className="divide-y">
              {entries.map((e) => (
                <div key={e.id} className="flex items-center gap-4 px-5 py-3 hover:bg-ps-bg">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-gray-800 truncate">
                        {e.client_id ? (clientMap.get(e.client_id) ?? "Unknown") : "No client"}
                      </span>
                      {e.is_billable ? (
                        <Badge className="text-3xs px-1.5 py-0 bg-green-100 text-green-700">Billable</Badge>
                      ) : (
                        <Badge className="text-3xs px-1.5 py-0 bg-ps-muted text-ps-label">Non-billable</Badge>
                      )}
                    </div>
                    {e.description && (
                      <p className="text-xs text-ps-label truncate mt-0.5">{e.description}</p>
                    )}
                    <p className="text-2xs text-ps-hint mt-0.5">
                      {formatDate(e.started_at)} {formatTime(e.started_at)}
                      {e.ended_at ? ` → ${formatTime(e.ended_at)}` : ""}
                    </p>
                  </div>
                  <div className="text-right shrink-0 flex items-center gap-3">
                    <div>
                      <p className="text-sm font-semibold text-gray-800">
                        {e.duration_minutes ? formatDuration(e.duration_minutes) : "—"}
                      </p>
                      {/* What the SERVER says this time is worth. It used to be multiplied
                          here from `hourly_rate_paise`, which no timer-started entry
                          carried, so the figure was simply absent — and an entry with no
                          rate looked the same as one worth nothing. */}
                      {e.is_billable && e.ended_at && (
                        e.value_paise === null || e.value_paise === undefined ? (
                          <p className="text-2xs text-state-problem">No rate</p>
                        ) : (
                          <p className="text-2xs text-ps-label flex items-center justify-end gap-0.5">
                            {formatPaise(e.value_paise)}
                          </p>
                        )
                      )}
                    </div>
                    <button
                      onClick={() => handleDelete(e.id)}
                      className="p-1.5 rounded text-ps-disabled hover:text-state-problem hover:bg-state-problem-hover transition-colors"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      </>)}

      {/* Start Timer Dialog */}
      {showStart && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-brand-dark/60 p-4">
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-sm p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold text-ps-ink">Start Timer</h2>
              <button onClick={() => setShowStart(false)} className="text-ps-hint hover:text-ps-label">
                <X size={18} />
              </button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-ps-body mb-1">Client</label>
                <select
                  value={startClientId}
                  onChange={e => setStartClientId(e.target.value)}
                  className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
                >
                  <option value="">No client</option>
                  {clients.map(c => <option key={c.id} value={c.id}>{c.client_name}</option>)}
                </select>
              </div>
              <EngagementPicker
                id="start-engagement"
                clientId={startClientId}
                value={startEngagementId}
                onChange={setStartEngagementId}
              />
              <div>
                <label className="block text-xs font-medium text-ps-body mb-1">Description</label>
                <input
                  value={startDescription}
                  onChange={e => setStartDescription(e.target.value)}
                  className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
                  placeholder="What are you working on?"
                />
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="billable-start"
                  checked={startBillable}
                  onChange={e => setStartBillable(e.target.checked)}
                  className="rounded"
                />
                <label htmlFor="billable-start" className="text-sm text-ps-body">Billable</label>
              </div>
            </div>
            <div className="flex gap-2 justify-end pt-1">
              <Button variant="outline" size="sm" onClick={() => setShowStart(false)}>Cancel</Button>
              <Button
                size="sm"
                onClick={handleStartTimer}
                disabled={starting}
                className="bg-green-600 hover:bg-green-700 gap-1.5"
              >
                {starting ? <Loader2 className="animate-spin" size={13} /> : <Play size={13} />}
                Start
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Manual Entry Dialog */}
      {showManual && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-brand-dark/60 p-4">
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-sm p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold text-ps-ink">Manual Time Entry</h2>
              <button onClick={() => setShowManual(false)} className="text-ps-hint hover:text-ps-label">
                <X size={18} />
              </button>
            </div>
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-ps-body mb-1">Client</label>
                <select
                  value={manualClientId}
                  onChange={e => setManualClientId(e.target.value)}
                  className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
                >
                  <option value="">No client</option>
                  {clients.map(c => <option key={c.id} value={c.id}>{c.client_name}</option>)}
                </select>
              </div>
              <EngagementPicker
                id="manual-engagement"
                clientId={manualClientId}
                value={manualEngagementId}
                onChange={setManualEngagementId}
              />
              <div>
                <label className="block text-xs font-medium text-ps-body mb-1">Description</label>
                <input
                  value={manualDescription}
                  onChange={e => setManualDescription(e.target.value)}
                  className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
                  placeholder="What did you work on?"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-ps-body mb-1">Start *</label>
                  <input
                    type="datetime-local"
                    value={manualStarted}
                    onChange={e => setManualStarted(e.target.value)}
                    className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-ps-body mb-1">End *</label>
                  <input
                    type="datetime-local"
                    value={manualEnded}
                    onChange={e => setManualEnded(e.target.value)}
                    className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
                  />
                </div>
              </div>
              <div className="flex items-center gap-4">
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="billable-manual"
                    checked={manualBillable}
                    onChange={e => setManualBillable(e.target.checked)}
                    className="rounded"
                  />
                  <label htmlFor="billable-manual" className="text-sm text-ps-body">Billable</label>
                </div>
                {manualBillable && (
                  <div className="flex-1">
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={manualHourlyRate}
                      onChange={e => setManualHourlyRate(e.target.value)}
                      className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30"
                      placeholder="Rate ₹/hr"
                      title="Leave empty to use the engagement's rate, or your own"
                    />
                  </div>
                )}
              </div>
            </div>
            <div className="flex gap-2 justify-end pt-1">
              <Button variant="outline" size="sm" onClick={() => setShowManual(false)}>Cancel</Button>
              <Button
                size="sm"
                onClick={handleManualEntry}
                disabled={manualSaving || !manualStarted || !manualEnded}
              >
                {manualSaving ? <Loader2 className="animate-spin mr-1" size={13} /> : null}
                Save Entry
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
