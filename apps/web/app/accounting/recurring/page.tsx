"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import Link from "next/link";
import {
  ChevronLeft, Plus, Play, Pause, Trash2, CheckCircle2,
  Download, X, History, ExternalLink,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { downloadCsv } from "@/components/ui/data-table";
import { toCsv } from "@/lib/table/process";
import { formatPaise } from "@/lib/services/formatting";
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import { getFirmId } from "@/lib/data/getFirmId";
import { getClients } from "@/lib/data/clients";
import { arrayOrEmpty } from "@/lib/api/shape";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { api, type RecurringJournalTemplate, type RecurringJournalRun } from "@/lib/api";
import { todayLocalISO } from "@/lib/dateMath";
import type { Account, Client } from "@/lib/types";
import { paiseFromRupeeInput, rupeeInputFromPaise } from "@/lib/money/rupeeInput";
import { Callout } from "@/components/ui/callout";

// ─── What changed here, and why (ACC-06) ────────────────────────────────────
//
// This screen kept every template in
// `localStorage["practicesync_recurring_templates"]`, worked out the next due
// date in the browser, and the hub card promised "Automate monthly, quarterly
// & yearly entries" while nothing anywhere posted a due template. Four things
// were wrong and only the first was in the finding.
//
//   1. The templates reached no database. Another device, another user, or a
//      cleared site-data, and the firm's recurring journals were gone.
//
//   2. NOTHING WAS AUTOMATIC. There was no scheduler, no job, no server-side
//      anything — only a "Post Now" button a CA had to remember to press.
//
//   3. "POST NOW" POSTED STRAIGHT TO THE LEDGER, with `status: "posted"`, and
//      dated the entry TODAY rather than the occurrence. A rent journal due on
//      the 1st and remembered on the 7th landed on the 7th, in whatever period
//      that was.
//
//   4. `nextDueDate()` and `isDueToday()` were business logic in the browser —
//      a second cadence engine beside the one the recurring INVOICES already
//      had, free to disagree with it about which month is due.
//
// All four are the same fix: `recurring_journal_templates` (migration 377),
// `services/recurring_journal_service.py`, the daily sweep, and one cadence
// engine in `domain/recurrence.py` that both features import. Generating
// produces a DRAFT the CA reviews and issues — this product acts unprompted in
// exactly one place, a bank rule a Manager has marked trusted, and that was a
// recorded owner decision rather than a default to copy.

const FREQUENCIES = [
  { value: "monthly", label: "Monthly" },
  { value: "quarterly", label: "Quarterly" },
  { value: "half_yearly", label: "Half-yearly" },
  { value: "yearly", label: "Yearly" },
] as const;

function freqLabel(v: string): string {
  return FREQUENCIES.find(f => f.value === v)?.label ?? v;
}

interface TemplateForm {
  client_id: string;
  name: string;
  frequency: string;
  day_of_month: number;
  debit_account_id: string;
  credit_account_id: string;
  amount_rupees: string;
  narration: string;
  start_date: string;
  end_date: string;
}

const EMPTY_FORM: TemplateForm = {
  client_id: "",
  name: "",
  frequency: "monthly",
  day_of_month: 1,
  debit_account_id: "",
  credit_account_id: "",
  amount_rupees: "",
  narration: "",
  start_date: todayLocalISO(),
  end_date: "",
};


export default function RecurringPage() {
  const [templates, setTemplates] = useState<RecurringJournalTemplate[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<RecurringJournalTemplate | null>(null);
  const [form, setForm] = useState<TemplateForm>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [historyFor, setHistoryFor] = useState<string | null>(null);
  /** The next few dates this template will generate on, from
   *  `GET /{id}/preview`. `domain/recurrence` is the one cadence engine and
   *  its month-end clamp is against the ORIGINAL day, so a 31 January
   *  template runs 31 Jan, 28 Feb, 31 Mar — which is exactly the thing a CA
   *  wants to see before trusting a template, and which nothing in the
   *  product showed: the endpoint had no caller. Never derived here. */
  const [upcoming, setUpcoming] = useState<string[]>([]);
  const [runs, setRuns] = useState<RecurringJournalRun[]>([]);

  const accountName = useCallback(
    (id: string) => accounts.find(a => a.id === id)?.account_name ?? "—",
    [accounts]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.recurringJournals.list();
      if (!res.success) throw new Error(res.error ?? "Failed to load templates");
      setTemplates(res.data ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const fid = await getFirmId();
        const sb = getSupabaseClient();
        // Paged for the same silent-truncation reason as the export screens,
        // though this read is NOT one of them: this screen's Export button
        // builds its CSV from `templates`, which comes from the API. What this
        // read feeds is the account DROPDOWNS — and PostgREST's ~1000-row cap
        // would remove accounts from them with no error and no empty state, so
        // a template simply could not be built against an account past the cap.
        const { data } = await selectAll(() => sb.from("chart_of_accounts").select("*")
          .eq("firm_id", fid).eq("is_active", true)
          .order("account_name").order("id"));
        if (!cancelled) setAccounts((data ?? []) as Account[]);
      } catch { /* the dropdowns degrade; the list above still loads */ }
      try {
        const cs = await getClients();
        if (!cancelled) setClients(cs);
      } catch { /* same */ }
    })();
    load();
    return () => { cancelled = true; };
  }, [load]);

  // ── Modal ──────────────────────────────────────────────────────────────

  function openCreate() {
    setEditing(null);
    setForm({ ...EMPTY_FORM, start_date: todayLocalISO() });
    setFormError(null);
    setModalOpen(true);
  }

  function openEdit(t: RecurringJournalTemplate) {
    const dr = t.lines.find(l => l.debit_paise > 0);
    const cr = t.lines.find(l => l.credit_paise > 0);
    setEditing(t);
    setForm({
      client_id: t.client_id,
      name: t.name,
      frequency: t.frequency,
      day_of_month: t.day_of_month,
      debit_account_id: dr?.account_id ?? "",
      credit_account_id: cr?.account_id ?? "",
      amount_rupees: rupeeInputFromPaise(dr?.debit_paise ?? 0),
      narration: t.narration ?? "",
      start_date: t.start_date,
      end_date: t.end_date ?? "",
    });
    setFormError(null);
    setModalOpen(true);
  }

  async function handleSave() {
    if (!form.client_id) { setFormError("Client is required"); return; }
    if (!form.name.trim()) { setFormError("Name is required"); return; }
    if (!form.debit_account_id) { setFormError("Debit account is required"); return; }
    if (!form.credit_account_id) { setFormError("Credit account is required"); return; }
    if (form.debit_account_id === form.credit_account_id) {
      setFormError("Debit and credit accounts must differ"); return;
    }
    // Integer paise through the one parser. This was
    // `Math.round(parseFloat(form.amount_rupees) * 100)`, and
    // parseFloat("1,25,000") is 1 — a recurring entry a CA set up for
    // ₹1,25,000 a month would have posted ₹1 a month, unattended.
    const amount = paiseFromRupeeInput(form.amount_rupees);
    if (amount === null || amount <= 0) {
      setFormError("Amount isn't a number. Type it in rupees, like 125000 or 125000.50.");
      return;
    }
    if (!form.start_date) { setFormError("Start date is required"); return; }

    // The screen writes two lines; the model holds N (migration 377), so a
    // rent journal with its GST needs no schema change when the form grows.
    const body = {
      client_id: form.client_id,
      name: form.name.trim(),
      frequency: form.frequency,
      day_of_month: form.day_of_month,
      narration: form.narration.trim() || null,
      start_date: form.start_date,
      end_date: form.end_date || null,
      lines: [
        { account_id: form.debit_account_id, debit_paise: amount, credit_paise: 0,
          narration: form.narration.trim() || null },
        { account_id: form.credit_account_id, debit_paise: 0, credit_paise: amount,
          narration: form.narration.trim() || null },
      ],
    };

    setBusyId("save");
    try {
      const res = editing
        ? await api.recurringJournals.update(editing.id, body)
        : await api.recurringJournals.create(body);
      if (!res.success) throw new Error(res.error ?? "Failed to save");
      setModalOpen(false);
      await load();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setBusyId(null);
    }
  }

  async function toggleStatus(t: RecurringJournalTemplate) {
    setBusyId(t.id);
    setError(null);
    try {
      const res = await api.recurringJournals.update(t.id, {
        status: t.status === "active" ? "paused" : "active",
      });
      if (!res.success) throw new Error(res.error ?? "Failed to update");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update");
    } finally {
      setBusyId(null);
    }
  }

  async function remove(t: RecurringJournalTemplate) {
    if (!confirm(`Delete "${t.name}"? The journals it already generated are not affected.`)) return;
    setBusyId(t.id);
    try {
      const res = await api.recurringJournals.remove(t.id);
      if (!res.success) throw new Error(res.error ?? "Failed to delete");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    } finally {
      setBusyId(null);
    }
  }

  async function generate(t: RecurringJournalTemplate) {
    setBusyId(t.id);
    setError(null);
    setNotice(null);
    try {
      const res = await api.recurringJournals.generate(t.id);
      if (!res.success) throw new Error(res.error ?? "Failed to generate");
      const out = res.data;
      setNotice(out.created
        ? `Draft journal created for "${t.name}". Review and post it from Journal Entries — nothing reaches the ledger until you do.`
        : out.reason === "already generated"
          ? `That occurrence already has a draft. Nothing was created.`
          : `Could not generate: ${out.reason}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to generate");
    } finally {
      setBusyId(null);
    }
  }

  async function runAll() {
    setBusyId("run");
    setError(null);
    setNotice(null);
    try {
      const res = await api.recurringJournals.runDue();
      if (!res.success) throw new Error(res.error ?? "Failed to run");
      const d = res.data;
      setNotice(
        `${d.generated_count} draft${d.generated_count === 1 ? "" : "s"} created, ` +
        `${d.skipped_count} already existed` +
        (d.failed_count ? `, ${d.failed_count} failed: ${d.failed.map(f => f.error).join("; ")}` : "") +
        `. Drafts are in Journal Entries — nothing is posted until a CA posts it.`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to run");
    } finally {
      setBusyId(null);
    }
  }

  async function openHistory(t: RecurringJournalTemplate) {
    setHistoryFor(t.id);
    setRuns([]);
    setUpcoming([]);
    // Disabled while in flight like every other server call on this screen.
    // A read, so a second click costs only a wasted round trip — but the rule
    // `scripts/concurrent-actions.test.ts` states is about the BUTTON, not
    // about which verb is behind it, and an exception for "it is only a read"
    // is how the next Delete slips through.
    setBusyId(t.id);
    try {
      const [res, prev] = await Promise.all([
        api.recurringJournals.history(t.id),
        api.recurringJournals.preview(t.id, 6),
      ]);
      if (res.success) setRuns(res.data ?? []);
      // `arrayOrEmpty` rather than a cast: state replaced from a payload, and
      // `useState<string[]>([])` satisfies TypeScript however absent the key
      // is at runtime.
      if (prev.success) setUpcoming(arrayOrEmpty<string>(prev.data?.occurrences));
    } catch {
      /* the panel shows nothing rather than breaking the page */
    } finally {
      setBusyId(null);
    }
  }

  // ── Computed ───────────────────────────────────────────────────────────

  const today = todayLocalISO();
  const active = templates.filter(t => t.status === "active");
  const dueNow = active.filter(t => t.next_run_date && t.next_run_date <= today);
  const monthlyValue = useMemo(
    () => active.reduce((sum, t) => sum + t.lines.reduce((s, l) => s + l.debit_paise, 0), 0),
    [active]);

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <Link href="/accounting" className="text-ps-hint hover:text-ps-label">
          <ChevronLeft size={18} />
        </Link>
        <div className="flex-1 min-w-[220px]">
          <h1 className="text-xl font-semibold text-ps-ink">Recurring Journals</h1>
          <p className="text-sm text-ps-label mt-0.5">
            Templates saved for the firm. Each due occurrence becomes a DRAFT journal —
            nothing reaches the ledger until a CA posts it.
          </p>
        </div>
        <button
          onClick={runAll}
          disabled={busyId !== null || dueNow.length === 0}
          className="flex items-center gap-1 px-3 py-1.5 text-sm border border-ps-border rounded-md hover:bg-ps-bg disabled:opacity-40"
        >
          <Play size={14} /> Generate {dueNow.length} due
        </button>
        <button
          onClick={() => downloadCsv("recurring-journals.csv", toCsv(templates, [
            { key: "client", header: "Client", accessor: (t: RecurringJournalTemplate) =>
                clients.find(c => c.id === t.client_id)?.client_name ?? t.client_id },
            { key: "name", header: "Name", accessor: (t: RecurringJournalTemplate) => t.name },
            { key: "frequency", header: "Frequency", accessor: (t: RecurringJournalTemplate) => freqLabel(t.frequency) },
            { key: "next_due", header: "Next due", accessor: (t: RecurringJournalTemplate) => t.next_run_date },
            { key: "status", header: "Status", accessor: (t: RecurringJournalTemplate) => t.status },
            { key: "amount", header: "Amount (₹)", accessor: (t: RecurringJournalTemplate) =>
                (t.lines.reduce((s, l) => s + l.debit_paise, 0) / 100).toFixed(2) },
          ]))}
          disabled={templates.length === 0}
          className="flex items-center gap-1 px-3 py-1.5 text-sm border border-ps-border rounded-md hover:bg-ps-bg disabled:opacity-40"
        >
          <Download size={14} /> Export
        </button>
        <button
          onClick={openCreate}
          className="flex items-center gap-1 px-3 py-1.5 text-sm bg-blue-600 text-white rounded-md hover:bg-blue-700"
        >
          <Plus size={14} /> New template
        </button>
      </div>

      {error && <Callout tone="problem">{error}</Callout>}
      {notice && (
        <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-3 flex gap-2 text-sm text-blue-800">
          <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{notice}</span>
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
        {[
          { label: "Active templates", value: String(active.length) },
          { label: "Due to generate", value: String(dueNow.length) },
          { label: "Value per cycle", value: formatPaise(monthlyValue) },
        ].map(s => (
          <Card key={s.label}>
            <CardContent className="pt-4 pb-3">
              <p className="text-lg font-bold tabular-nums text-ps-ink">{loading ? "—" : s.value}</p>
              <p className="text-xs text-ps-label mt-0.5">{s.label}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-sm min-w-[860px]">
            <thead>
              <tr className="text-xs text-ps-hint border-b border-ps-muted">
                <th className="px-5 py-2.5 text-left font-medium">Template</th>
                <th className="px-3 py-2.5 text-left font-medium">Client</th>
                <th className="px-3 py-2.5 text-left font-medium">Posting</th>
                <th className="px-3 py-2.5 text-right font-medium">Amount</th>
                <th className="px-3 py-2.5 text-left font-medium">Cycle</th>
                <th className="px-3 py-2.5 text-left font-medium">Next due</th>
                <th className="px-5 py-2.5 text-left font-medium">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ps-bg">
              {loading ? (
                <tr><td colSpan={7} className="px-5 py-8 text-center text-sm text-ps-hint">Loading…</td></tr>
              ) : templates.length === 0 ? (
                <tr><td colSpan={7} className="px-5 py-8 text-center text-sm text-ps-hint">
                  No recurring journals yet.
                </td></tr>
              ) : templates.map(t => {
                const dr = t.lines.find(l => l.debit_paise > 0);
                const cr = t.lines.find(l => l.credit_paise > 0);
                const amount = t.lines.reduce((s, l) => s + l.debit_paise, 0);
                const busy = busyId === t.id;
                const due = t.status === "active" && !!t.next_run_date && t.next_run_date <= today;
                return (
                  <tr key={t.id} className="hover:bg-ps-bg">
                    <td className="px-5 py-2.5">
                      <p className="font-medium text-ps-ink">{t.name}</p>
                      {t.narration && <p className="text-2xs text-ps-hint">{t.narration}</p>}
                    </td>
                    <td className="px-3 py-2.5 text-xs text-ps-label">
                      {clients.find(c => c.id === t.client_id)?.client_name ?? "—"}
                    </td>
                    <td className="px-3 py-2.5 text-xs text-ps-label">
                      {t.lines.length > 2
                        ? `${t.lines.length} lines`
                        : <>Dr {accountName(dr?.account_id ?? "")} / Cr {accountName(cr?.account_id ?? "")}</>}
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums font-medium">{formatPaise(amount)}</td>
                    <td className="px-3 py-2.5 text-xs text-ps-label">{freqLabel(t.frequency)}</td>
                    <td className="px-3 py-2.5 text-xs">
                      <span className={due ? "text-state-attention font-medium" : "text-ps-label"}>
                        {t.next_run_date}
                      </span>
                      {t.status !== "active" && (
                        <Badge className="ml-2 bg-ps-muted text-ps-label">{t.status}</Badge>
                      )}
                    </td>
                    <td className="px-5 py-2.5">
                      <div className="flex items-center gap-3">
                        {t.status === "active" && (
                          <button
                            onClick={() => generate(t)}
                            disabled={busy}
                            className="text-xs text-green-700 hover:text-green-900 font-medium disabled:opacity-40"
                          >
                            {busy ? "Working…" : "Generate draft"}
                          </button>
                        )}
                        <button onClick={() => openEdit(t)} className="text-xs text-blue-600 hover:text-blue-800">
                          Edit
                        </button>
                        <button
                          onClick={() => toggleStatus(t)}
                          disabled={busy}
                          className="text-xs text-ps-hint hover:text-ps-label flex items-center gap-1 disabled:opacity-40"
                        >
                          {t.status === "active" ? <Pause size={12} /> : <Play size={12} />}
                          {t.status === "active" ? "Pause" : "Resume"}
                        </button>
                        <button
                          onClick={() => openHistory(t)}
                          disabled={busy}
                          className="text-xs text-ps-hint hover:text-ps-label flex items-center gap-1 disabled:opacity-40"
                        >
                          <History size={12} /> History
                        </button>
                        <button
                          onClick={() => remove(t)}
                          disabled={busy}
                          className="text-xs text-red-600 hover:text-red-800 disabled:opacity-40"
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {historyFor && (
        <Card>
          <div className="px-5 py-3 border-b border-gray-50 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-ps-ink">
              History — {templates.find(t => t.id === historyFor)?.name}
            </h2>
            <button onClick={() => setHistoryFor(null)} className="text-ps-hint hover:text-ps-label">
              <X size={14} />
            </button>
          </div>
          <CardContent className="p-0">
            {/* WHAT IS COMING, beside what has happened. The dates are the
                server's — one cadence engine, shared with recurring invoices
                and recurring purchase bills — and a template whose next six
                occurrences look wrong is one to fix before it posts, not
                after. An empty list is a real answer for a paused or ended
                template, so it says so rather than rendering nothing. */}
            <div className="px-5 py-3 border-b border-ps-muted">
              <p className="text-xs text-ps-hint mb-1">Next occurrences</p>
              {upcoming.length === 0 ? (
                <p className="text-xs text-ps-disabled">
                  None — the template is paused, ended, or has no further dates.
                </p>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {upcoming.map(d => (
                    <span key={d}
                      className="text-xs px-2 py-0.5 rounded-md bg-ps-bg text-ps-label tabular-nums">
                      {d}
                    </span>
                  ))}
                </div>
              )}
            </div>
            {runs.length === 0 ? (
              <p className="px-5 py-6 text-sm text-ps-hint">Nothing generated yet.</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-ps-hint border-b border-ps-muted">
                    <th className="px-5 py-2 text-left font-medium">Occurrence</th>
                    <th className="px-3 py-2 text-left font-medium">Result</th>
                    <th className="px-5 py-2 text-left font-medium">Journal</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ps-bg">
                  {runs.map(r => (
                    <tr key={r.id}>
                      <td className="px-5 py-2 text-xs text-ps-label">{r.occurrence_date}</td>
                      <td className="px-3 py-2 text-xs">
                        {r.status === "generated"
                          ? <span className="text-green-700">Draft created</span>
                          : <span className="text-red-600">
                              {r.status}
                              {r.detail && typeof r.detail.error === "string" ? ` — ${r.detail.error}` : ""}
                            </span>}
                      </td>
                      <td className="px-5 py-2 text-xs">
                        {r.journal_entry_id
                          ? <Link href="/accounting/journal" className="text-blue-600 hover:underline inline-flex items-center gap-1">
                              Open <ExternalLink size={11} />
                            </Link>
                          : <span className="text-ps-disabled">—</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      )}

      {modalOpen && (
        <div className="fixed inset-0 bg-brand-dark/60 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-lg p-6 space-y-4 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-ps-ink">
                {editing ? "Edit" : "New"} recurring journal
              </h3>
              <button onClick={() => setModalOpen(false)} className="text-ps-hint hover:text-ps-label" aria-label="Close">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div>
              <label className="text-xs font-medium text-ps-body block mb-1">Client</label>
              <ClientLookup
                clients={clients}
                value={form.client_id}
                onChange={id => setForm(f => ({ ...f, client_id: id }))}
                size="sm"
                ariaLabel="Client"
                placeholder="Select a client"
                disabled={!!editing}
              />
              {editing && (
                <p className="text-3xs text-ps-hint mt-1">
                  A template cannot move to another client — its generated journals
                  would still belong to this one.
                </p>
              )}
            </div>

            <div>
              <label htmlFor="rj-name" className="text-xs font-medium text-ps-body block mb-1">Name</label>
              <input
                id="rj-name"
                type="text"
                className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="Monthly office rent"
                value={form.name}
                onChange={e => { setForm(f => ({ ...f, name: e.target.value })); setFormError(null); }}
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label htmlFor="rj-dr" className="text-xs font-medium text-ps-body block mb-1">Debit account</label>
                <select
                  id="rj-dr"
                  className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  value={form.debit_account_id}
                  onChange={e => setForm(f => ({ ...f, debit_account_id: e.target.value }))}
                >
                  <option value="">Select…</option>
                  {accounts.map(a => <option key={a.id} value={a.id}>{a.account_code} — {a.account_name}</option>)}
                </select>
              </div>
              <div>
                <label htmlFor="rj-cr" className="text-xs font-medium text-ps-body block mb-1">Credit account</label>
                <select
                  id="rj-cr"
                  className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  value={form.credit_account_id}
                  onChange={e => setForm(f => ({ ...f, credit_account_id: e.target.value }))}
                >
                  <option value="">Select…</option>
                  {accounts.map(a => <option key={a.id} value={a.id}>{a.account_code} — {a.account_name}</option>)}
                </select>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label htmlFor="rj-amount" className="text-xs font-medium text-ps-body block mb-1">Amount (₹)</label>
                <input
                  id="rj-amount"
                  type="text"
                  inputMode="decimal"
                  className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="125000"
                  value={form.amount_rupees}
                  onChange={e => { setForm(f => ({ ...f, amount_rupees: e.target.value })); setFormError(null); }}
                />
              </div>
              <div>
                <label htmlFor="rj-freq" className="text-xs font-medium text-ps-body block mb-1">Frequency</label>
                <select
                  id="rj-freq"
                  className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  value={form.frequency}
                  onChange={e => setForm(f => ({ ...f, frequency: e.target.value }))}
                >
                  {FREQUENCIES.map(f => <option key={f.value} value={f.value}>{f.label}</option>)}
                </select>
              </div>
            </div>

            <div className="grid grid-cols-3 gap-3">
              <div>
                <label htmlFor="rj-day" className="text-xs font-medium text-ps-body block mb-1">Day of month</label>
                <select
                  id="rj-day"
                  className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  value={form.day_of_month}
                  onChange={e => setForm(f => ({ ...f, day_of_month: parseInt(e.target.value, 10) }))}
                >
                  {/* 1–28 only: 29, 30 and 31 do not exist in every month, and
                      a template that slides to the 28th in February posts on a
                      date nobody chose. The CHECK in migration 377 says the
                      same thing. */}
                  {Array.from({ length: 28 }, (_, i) => i + 1).map(d => (
                    <option key={d} value={d}>{d}</option>
                  ))}
                </select>
              </div>
              <div>
                <label htmlFor="rj-start" className="text-xs font-medium text-ps-body block mb-1">Starts</label>
                <input
                  id="rj-start"
                  type="date"
                  className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  value={form.start_date}
                  onChange={e => setForm(f => ({ ...f, start_date: e.target.value }))}
                />
              </div>
              <div>
                <label htmlFor="rj-end" className="text-xs font-medium text-ps-body block mb-1">Ends (optional)</label>
                <input
                  id="rj-end"
                  type="date"
                  className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  value={form.end_date}
                  onChange={e => setForm(f => ({ ...f, end_date: e.target.value }))}
                />
              </div>
            </div>

            <div>
              <label htmlFor="rj-narr" className="text-xs font-medium text-ps-body block mb-1">Narration</label>
              <input
                id="rj-narr"
                type="text"
                className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="Office rent for the month"
                value={form.narration}
                onChange={e => setForm(f => ({ ...f, narration: e.target.value }))}
              />
            </div>

            {formError && <p className="text-2xs text-red-600">{formError}</p>}

            <div className="flex gap-2 pt-1">
              <button onClick={() => setModalOpen(false)} className="flex-1 border border-ps-border text-ps-label text-sm py-2 rounded-lg hover:bg-ps-bg">
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={busyId === "save"}
                className="flex-1 bg-blue-600 text-white text-sm py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50"
              >
                {busyId === "save" ? "Saving…" : "Save template"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
