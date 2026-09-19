"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowLeft, RefreshCw, AlertTriangle, Info, Loader2, ChevronDown, Check,
} from "lucide-react";
import {
  api, type ApiResp, type AgeingSchedule, type AgeingTable, type AgeingDocument,
  type AgeingAdvance, type AgeingClassifyBody,
} from "@/lib/api";
import { formatPaise } from "@/lib/services/formatting";
import { getSupabaseClient } from "@/lib/supabase/client";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

import { todayLocalISO } from "@/lib/dateMath";
import { objectOrNull } from "@/lib/api/shape";
import { Callout, GapList } from "@/components/ui/callout";
/**
 * Trade Receivables and Trade Payables ageing schedules — the notes to the
 * balance sheet required by Schedule III to the Companies Act 2013 as amended
 * by MCA Notification G.S.R. 207(E) of 24 March 2021 (Division I).
 *
 * ZERO BUSINESS LOGIC HERE. Every figure comes from
 * /api/accounting/schedule-iii/ageing, which is computed by
 * public.schedule_iii_ageing (migration 303) with domain/reporting/ageing.py as
 * its pinned twin. This file decides layout and nothing else — it does not know
 * what six months means, which enterprises are MSME, or which row a document
 * belongs in, and it must not learn.
 *
 * THREE THINGS ON THIS SCREEN ARE DELIBERATE AND EASY TO "TIDY" WRONG:
 *
 *  1. The two tables have DIFFERENT columns. Receivables age in five prescribed
 *     buckets from six months, payables in four from one year. Columns are read
 *     off each table's own `buckets`, never hardcoded, so neither can acquire
 *     the other's shape.
 *
 *  2. "Not due" is NOT a prescribed column and is marked as such. Every
 *     outstanding amount must appear somewhere for the total to tie to the
 *     balance sheet, and folding not-yet-due balances into "less than 6 months"
 *     overstates the ageing of a current book. Both figures are here so a filer
 *     can present either shape.
 *
 *  3. Unclassified vendors are shown ABOVE the payables table, not inside it.
 *     IT Act s.43B(h) disallows a deduction for sums payable to a micro or
 *     small enterprise beyond the MSMED s.15 limit unless actually paid, so
 *     calling an unclassified vendor "Others" would change the client's taxable
 *     income. The note is not finished until that list is empty.
 *
 *  4. Unbilled dues sit BESIDE each table and are never aged. Both notes end
 *     "Unbilled dues shall be disclosed separately", and the reason is the same
 *     reason they get no bucket: the tables age from the due date, or where
 *     none is specified the transaction date, and an unbilled due has neither.
 *     The figure is absent rather than zero until somebody records that they
 *     have been through the chart of accounts — an unreviewed nil claims the
 *     client has none when the truth is that nobody has looked.
 */

type Tab = "note" | "receivables" | "payables" | "unbilled";

const TABS: { id: Tab; label: string; hint: string }[] = [
  { id: "note", label: "Schedule III note", hint: "The two prescribed tables" },
  { id: "receivables", label: "Receivables detail", hint: "Open invoices, and what to mark" },
  { id: "payables", label: "Payables detail", hint: "Open bills, and what to mark" },
  { id: "unbilled", label: "Unbilled dues", hint: "Which accounts hold them, and the review that lets the figure be printed" },
];

/** An account a CA can mark. Only assets and liabilities are offered: accrued
 *  income is an asset and accrued expenses are a liability, and the database
 *  CHECK refuses anything else — the P&L leg of an accrual is not the due, and
 *  marking it would double the disclosure. */
type MarkableAccount = {
  id: string;
  account_code: string;
  account_name: string;
  account_type: string;
  unbilled_dues_side: "receivable" | "payable" | null;
};

type MsmeStatus = NonNullable<AgeingClassifyBody["msme_status"]>;

/** Four values and an empty one, because "not classified" is a real state the
 *  CA can return a vendor to — not an absence of a choice. Medium is labelled
 *  with where it lands: MSMED s.22 and s.2(n) both stop at small, so a medium
 *  enterprise is registered and still belongs in Others. */
const MSME_OPTIONS: { value: "" | MsmeStatus; label: string }[] = [
  { value: "", label: "Not classified" },
  { value: "micro", label: "Micro" },
  { value: "small", label: "Small" },
  { value: "medium", label: "Medium (→ Others)" },
  { value: "not_registered", label: "Not registered under MSMED" },
];



function Amount({ paise }: { paise: number }) {
  return (
    <span className={paise ? "tabular-nums text-ps-ink" : "tabular-nums text-ps-disabled"}>
      {paise ? formatPaise(paise) : "—"}
    </span>
  );
}

/** One prescribed table. Columns come from the payload, never from this file. */
function ScheduleTable({ table }: { table: AgeingTable }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-2xs border-collapse">
        <thead>
          <tr className="border-b border-ps-border">
            <th className="text-left font-medium text-ps-label px-4 py-2.5 min-w-[280px]">
              Particulars
            </th>
            {table.buckets.map((b) => (
              <th
                key={b.key}
                className={`text-right font-medium px-3 py-2.5 whitespace-nowrap ${
                  b.prescribed ? "text-ps-label" : "text-ps-hint italic border-r border-dashed border-ps-border"
                }`}
              >
                {b.label}
                {!b.prescribed && <sup className="ml-0.5">†</sup>}
              </th>
            ))}
            <th className="text-right font-semibold text-ps-body px-4 py-2.5">Total</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-50">
          {table.rows.map((r) => (
            <tr key={r.key} className="hover:bg-ps-bg">
              <td className="px-4 py-2.5 text-ps-body">{r.label}</td>
              {table.buckets.map((b) => (
                <td
                  key={b.key}
                  className={`text-right px-3 py-2.5 ${
                    b.prescribed ? "" : "border-r border-dashed border-ps-border bg-[#FAFBFC]"
                  }`}
                >
                  <Amount paise={r.amounts[b.key] ?? 0} />
                </td>
              ))}
              <td className="text-right px-4 py-2.5 font-medium">
                <Amount paise={r.total_paise} />
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-ps-border bg-ps-bg">
            <td className="px-4 py-2.5 font-semibold text-ps-ink">Total</td>
            {table.buckets.map((b) => (
              <td key={b.key} className="text-right px-3 py-2.5 font-semibold">
                <Amount paise={table.column_totals[b.key] ?? 0} />
              </td>
            ))}
            <td className="text-right px-4 py-2.5 font-semibold">
              <Amount paise={table.total_paise} />
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

export default function ClientAgeingSchedulePage() {
  // Not useParams(): apps/web is a static export and Cloudflare's 200-rewrite
  // serves the pre-rendered "_placeholder" HTML for every real client URL.
  const { clientId } = useClientNav();
  const router = useRouter();

  const [tab, setTab] = useState<Tab>("note");
  const [asOf, setAsOf] = useState<string>(todayLocalISO());
  const [schedule, setSchedule] = useState<AgeingSchedule | null>(null);
  const [invoices, setInvoices] = useState<AgeingDocument[] | null>(null);
  const [bills, setBills] = useState<AgeingDocument[] | null>(null);
  // The advances section (PUR-24), kept beside the rows rather than folded
  // into them: an advance is not an open document and must never enter the
  // buckets. Held per side because the two reconcile to different accounts.
  const [arAdvances, setArAdvances] = useState<AdvanceSection | null>(null);
  const [apAdvances, setApAdvances] = useState<AdvanceSection | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [accounts, setAccounts] = useState<MarkableAccount[] | null>(null);
  const [reviewNote, setReviewNote] = useState("");

  const load = useCallback(async () => {
    if (!clientId) return;
    setLoading(true);
    setError(null);
    try {
      const r = await api.accounting.scheduleIiiAgeing(clientId, asOf) as ApiResp<AgeingSchedule>;
      if (!r.success) throw new Error(r.error ?? "Could not build the ageing schedule");
      setSchedule(objectOrNull(r.data));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not build the ageing schedule");
    } finally {
      setLoading(false);
    }
  }, [clientId, asOf]);

  const loadDetail = useCallback(async () => {
    if (!clientId) return;
    setDetailError(null);
    try {
      const [ar, ap] = await Promise.all([
        api.ageing.receivables(clientId, asOf),
        api.ageing.payables(clientId, asOf),
      ]);
      setInvoices(ar.success ? ar.data.invoices ?? [] : []);
      setBills(ap.success ? ap.data.bills ?? [] : []);
      setArAdvances(ar.success ? {
        advances: ar.data.advances ?? [],
        total_advances_paise: ar.data.total_advances_paise ?? 0,
        total_outstanding_paise: ar.data.total_outstanding_paise ?? 0,
        net_paise: ar.data.net_receivable_paise ?? ar.data.total_outstanding_paise ?? 0,
        gaps: ar.data.advance_gaps ?? [],
      } : null);
      setApAdvances(ap.success ? {
        advances: ap.data.advances ?? [],
        total_advances_paise: ap.data.total_advances_paise ?? 0,
        total_outstanding_paise: ap.data.total_outstanding_paise ?? 0,
        net_paise: ap.data.net_payable_paise ?? ap.data.total_outstanding_paise ?? 0,
        gaps: ap.data.advance_gaps ?? [],
      } : null);
      if (!ar.success) setDetailError(ar.error ?? "Could not load the open invoices");
      else if (!ap.success) setDetailError(ap.error ?? "Could not load the open bills");
    } catch (e) {
      setDetailError(e instanceof Error ? e.message : "Could not load the open documents");
    }
  }, [clientId, asOf]);

  /** The client's asset and liability accounts, read directly — this is a read,
   *  and RLS governs it (see CLAUDE.md on the frontend's second data path). The
   *  WRITE goes through the guarded classify endpoint, because marking an
   *  account puts its balance into a statutory disclosure. */
  const loadAccounts = useCallback(async () => {
    if (!clientId) return;
    setDetailError(null);
    try {
      const sb = getSupabaseClient();
      const { data, error: err } = await sb
        .from("chart_of_accounts")
        .select("id, account_code, account_name, account_type, unbilled_dues_side")
        .eq("client_id", clientId)
        .in("account_type", ["Asset", "Liability"])
        .eq("is_active", true)
        .order("account_code");
      if (err) throw new Error(err.message);
      setAccounts((data ?? []) as MarkableAccount[]);
    } catch (e) {
      setDetailError(e instanceof Error ? e.message : "Could not load the chart of accounts");
    }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if ((tab === "receivables" || tab === "payables")
        && invoices === null && bills === null) loadDetail();
  }, [tab, invoices, bills, loadDetail]);
  useEffect(() => {
    if (tab === "unbilled" && accounts === null) loadAccounts();
  }, [tab, accounts, loadAccounts]);

  /** Mark or un-mark one account, then rebuild the note so the figure moves. */
  const markAccount = useCallback(async (
    account: MarkableAccount, side: "receivable" | "payable" | null,
  ) => {
    setSaving(account.id);
    setDetailError(null);
    try {
      const r = await api.accounting.classifyForAgeing({
        client_id: clientId, target: "account", target_id: account.id,
        unbilled_dues_side: side,
      });
      if (!r.success) throw new Error(r.error ?? "Could not mark the account");
      await Promise.all([load(), loadAccounts()]);
    } catch (e) {
      setDetailError(e instanceof Error ? e.message : "Could not mark the account");
    } finally {
      setSaving(null);
    }
  }, [clientId, load, loadAccounts]);

  /** Record — or withdraw — the review that lets the figure be printed. */
  const setReviewed = useCallback(async (reviewed: boolean) => {
    setSaving("review");
    setDetailError(null);
    try {
      const r = await api.accounting.reviewUnbilledDues({
        client_id: clientId, reviewed, note: reviewNote.trim() || null,
      });
      if (!r.success) throw new Error(r.error ?? "Could not record the review");
      setReviewNote("");
      await load();
    } catch (e) {
      setDetailError(e instanceof Error ? e.message : "Could not record the review");
    } finally {
      setSaving(null);
    }
  }, [clientId, reviewNote, load]);

  /** Record one classification, then rebuild the note so the figures move. */
  const classify = useCallback(async (
    key: string,
    body: Parameters<typeof api.accounting.classifyForAgeing>[0],
  ) => {
    setSaving(key);
    setDetailError(null);
    try {
      const r = await api.accounting.classifyForAgeing(body);
      if (!r.success) throw new Error(r.error ?? "Could not record the classification");
      // The note always: the mark changes which ROW of the note the amount is
      // in. The detail lists only if they are already open — a classification
      // made from the note tab has no toggle on screen to refresh, and
      // refetching them there would be two requests for nothing.
      await Promise.all(
        (invoices !== null || bills !== null) ? [load(), loadDetail()] : [load()]);
    } catch (e) {
      setDetailError(e instanceof Error ? e.message : "Could not record the classification");
    } finally {
      setSaving(null);
    }
  }, [load, loadDetail, invoices, bills]);

  const unclassified = schedule?.payables.unclassified_vendors ?? [];

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <button
            onClick={() => router.push(`/clients/${clientId}/reports`)}
            className="flex items-center gap-1 text-2xs text-ps-hint hover:text-ps-label mb-1.5"
          >
            <ArrowLeft size={12} /> Reports
          </button>
          <h2 className="text-sm font-semibold text-ps-ink">Ageing schedules</h2>
          <p className="text-2xs text-ps-hint mt-0.5">
            {schedule?.statute ??
              "Schedule III to the Companies Act 2013, as amended by MCA Notification G.S.R. 207(E) dated 24 March 2021"}
          </p>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <label className="text-2xs text-ps-label">As at</label>
          <input
            type="date"
            value={asOf}
            onChange={(e) => { setAsOf(e.target.value); setInvoices(null); setBills(null); setArAdvances(null); setApAdvances(null); }}
            className="text-2xs border border-ps-border rounded-lg px-2.5 py-1.5 text-ps-body"
          />
          <button
            onClick={() => { setInvoices(null); setBills(null); setArAdvances(null); setApAdvances(null); load(); }}
            className="flex items-center gap-1.5 text-2xs text-ps-label hover:text-ps-body border border-ps-border rounded-lg px-2.5 py-1.5"
          >
            <RefreshCw size={12} /> Refresh
          </button>
        </div>
      </div>

      <div className="flex gap-1 border-b border-ps-muted">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            title={t.hint}
            className={`text-2xs px-3 py-2 border-b-2 -mb-px transition-colors ${
              tab === t.id
                ? "border-blue-600 text-blue-700 font-medium"
                : "border-transparent text-ps-hint hover:text-ps-label"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-2xs text-ps-hint py-8">
          <Loader2 size={14} className="animate-spin" /> Building the schedule…
        </div>
      )}

      {error && <Callout tone="problem">{error}</Callout>}

      {detailError && (
        <div className="flex items-start gap-2.5 bg-amber-50 border border-amber-100 rounded-xl px-4 py-3">
          <AlertTriangle size={14} className="text-amber-600 flex-shrink-0 mt-0.5" />
          <p className="text-2xs text-amber-900">{detailError}</p>
        </div>
      )}

      {!loading && !error && schedule && (
        <>
          {/* The gaps, always visible — they are what stops the note being signed. */}
          <GapList gaps={schedule.gaps} tone="attention" />

          {tab === "note" && (
            <div className="space-y-5">
              <section className="bg-white rounded-xl border border-ps-muted overflow-hidden">
                <div className="px-4 py-3 border-b border-gray-50">
                  <p className="text-xs font-semibold text-ps-body">
                    {schedule.receivables.title}
                  </p>
                  <p className="text-3xs text-ps-hint mt-0.5">
                    Outstanding for the following periods from {schedule.ageing_from}.
                  </p>
                </div>
                <ScheduleTable table={schedule.receivables} />
                <UnbilledLine table={schedule.receivables}
                              reviewedOn={schedule.unbilled_reviewed_on}
                              onReview={() => setTab("unbilled")} />
              </section>

              {unclassified.length > 0 && (
                <section className="bg-white rounded-xl border border-amber-200 overflow-hidden">
                  <div className="px-4 py-3 border-b border-amber-100 bg-amber-50/50">
                    <p className="text-xs font-semibold text-ps-body">
                      Classify these vendors before signing the payables note
                    </p>
                    <p className="text-3xs text-ps-hint mt-0.5">
                      {formatPaise(schedule.payables.unclassified_paise)} across{" "}
                      {unclassified.length} vendor{unclassified.length === 1 ? "" : "s"} is in
                      neither row. Micro and small are row (i); medium and unregistered are
                      Others (MSMED s.22, s.2(n)).
                    </p>
                  </div>
                  <div className="divide-y divide-gray-50">
                    {unclassified.map((v) => (
                      <div key={v.vendor_id ?? v.vendor_name}
                           className="px-4 py-2.5 flex items-center gap-4">
                        <p className="text-2xs text-ps-body flex-1 min-w-0 truncate">
                          {v.vendor_name}
                        </p>
                        <p className="text-2xs tabular-nums text-ps-label">
                          {formatPaise(v.outstanding_paise)}
                        </p>
                        <MsmeSelect
                          value=""
                          busy={saving === `vendor:${v.vendor_id}`}
                          onChange={(value) => classify(`vendor:${v.vendor_id}`, {
                            client_id: clientId, target: "vendor",
                            target_id: v.vendor_id ?? "",
                            msme_status: value === "" ? null : value,
                          })}
                        />
                      </div>
                    ))}
                  </div>
                </section>
              )}

              <section className="bg-white rounded-xl border border-ps-muted overflow-hidden">
                <div className="px-4 py-3 border-b border-gray-50">
                  <p className="text-xs font-semibold text-ps-body">
                    {schedule.payables.title}
                  </p>
                  <p className="text-3xs text-ps-hint mt-0.5">
                    Four prescribed columns, from one year — deliberately not the receivables&apos;
                    five. Row (i) is micro and small enterprises only.
                  </p>
                </div>
                <ScheduleTable table={schedule.payables} />
                <UnbilledLine table={schedule.payables}
                              reviewedOn={schedule.unbilled_reviewed_on}
                              onReview={() => setTab("unbilled")} />
              </section>

              <div className="flex items-start gap-2.5 bg-ps-bg border border-ps-border rounded-xl px-4 py-3">
                <Info size={13} className="text-ps-hint flex-shrink-0 mt-0.5" />
                <p className="text-3xs text-ps-label">
                  <span className="font-medium">†</span> &ldquo;Not due&rdquo; is not one of the
                  prescribed columns. It is shown separately because folding not-yet-due balances
                  into the first bucket overstates the ageing of a current book. To present the
                  prescribed table, add it into the first column — the row totals are the same
                  number either way.
                </p>
              </div>
            </div>
          )}

          {(tab === "receivables" || tab === "payables") && (
            <>
              <AdvancesPanel
                kind={tab}
                section={tab === "receivables" ? arAdvances : apAdvances}
              />
              <DocumentList
                kind={tab}
                rows={(tab === "receivables" ? invoices : bills) ?? null}
                saving={saving}
                onClassify={classify}
                clientId={clientId}
              />
            </>
          )}

          {tab === "unbilled" && (
            <UnbilledPanel
              accounts={accounts}
              reviewedOn={schedule.unbilled_reviewed_on}
              note={reviewNote}
              onNote={setReviewNote}
              saving={saving}
              onMark={markAccount}
              onReviewed={setReviewed}
            />
          )}
        </>
      )}
    </div>
  );
}

/** Beside the table, never inside it. Both notes end "Unbilled dues shall be
 *  disclosed separately", and an unbilled due has no due date to age from — a
 *  bucket here would be an invented one. */
function UnbilledLine({ table, reviewedOn, onReview }: {
  table: AgeingTable; reviewedOn: string | null; onReview: () => void;
}) {
  const paise = table.unbilled_dues_paise;
  return (
    <div className="px-4 py-2.5 border-t border-gray-50">
      <div className="flex items-center gap-2">
        <p className="text-3xs text-ps-label flex-1">
          Unbilled dues <span className="text-ps-hint">(disclosed separately)</span>
        </p>
        {paise === null ? (
          <button onClick={onReview}
            className="text-3xs border border-amber-200 bg-amber-50 text-amber-800 rounded-md px-2 py-0.5 hover:bg-amber-100">
            Not reviewed — review the accounts
          </button>
        ) : (
          <p className="text-3xs tabular-nums text-ps-ink font-medium">
            {formatPaise(paise)}
          </p>
        )}
      </div>
      {/* What the figure is made of. A CA signing the note needs to see which
          accounts it came from, and it is a handful of them. */}
      {table.unbilled_accounts.length > 0 && (
        <div className="mt-1.5 space-y-0.5">
          {table.unbilled_accounts.map((a) => (
            <div key={a.account_id} className="flex items-center gap-2 pl-3">
              <span className="text-3xs text-ps-hint tabular-nums">{a.account_code}</span>
              <span className="text-3xs text-ps-hint flex-1 truncate">{a.account_name}</span>
              <span className={`text-3xs tabular-nums ${
                a.balance_paise < 0 ? "text-red-600" : "text-ps-hint"}`}>
                {formatPaise(a.balance_paise)}
              </span>
            </div>
          ))}
        </div>
      )}
      {paise !== null && reviewedOn && (
        <p className="text-[9px] text-ps-disabled mt-1">
          Chart of accounts reviewed {reviewedOn}
          {table.unbilled_accounts.length === 0 && " — no account holds unbilled dues"}
        </p>
      )}
    </div>
  );
}

function MsmeSelect({ value, busy, onChange }: {
  value: "" | MsmeStatus; busy: boolean; onChange: (v: "" | MsmeStatus) => void;
}) {
  return (
    <div className="relative flex items-center">
      <select
        value={value}
        disabled={busy}
        onChange={(e) => onChange(e.target.value as "" | MsmeStatus)}
        className="text-2xs border border-ps-border rounded-lg pl-2.5 pr-7 py-1.5 text-ps-body appearance-none bg-white disabled:opacity-50"
      >
        {MSME_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
      {busy
        ? <Loader2 size={11} className="animate-spin absolute right-2 text-ps-hint" />
        : <ChevronDown size={11} className="absolute right-2 text-ps-hint pointer-events-none" />}
    </div>
  );
}

/** What the ageing report owes its control account. Held per side because the
 *  two reconcile to different accounts and mean opposite things. */
type AdvanceSection = {
  advances: AgeingAdvance[];
  total_advances_paise: number;
  total_outstanding_paise: number;
  /** Documents outstanding less the advances — the tie-up figure, computed
   *  server-side (CLAUDE.md: zero business logic in the frontend). */
  net_paise: number;
  gaps: string[];
};

/**
 * MONEY THAT HAS MOVED WITH NO DOCUMENT TO SIT AGAINST (PUR-24).
 *
 * A payment made to a supplier before the bill arrives, or a receipt taken
 * from a customer before the invoice is raised, is real cash that the journal
 * has already put through Trade Payables or Trade Receivables. The ageing
 * listed open documents only, so it could not be tied to the control account
 * and legitimately disagreed with the party statement — which debits or
 * credits every payment and receipt.
 *
 * Shown ABOVE the documents and never inside them. A supplier advance is an
 * ASSET and a customer advance a LIABILITY, so folding either into the buckets
 * would misstate the very Schedule III note this screen builds; the reconciling
 * line is the whole point of the panel.
 */
function AdvancesPanel({ kind, section }: {
  kind: "receivables" | "payables";
  section: AdvanceSection | null;
}) {
  if (section === null) return null;
  const isAr = kind === "receivables";
  const control = isAr ? "Trade Receivables" : "Trade Payables";
  const noun = isAr ? "customer advance" : "supplier advance";

  return (
    <section className="bg-white rounded-xl border border-ps-muted overflow-hidden mb-5">
      <div className="px-4 py-3 border-b border-gray-50">
        <p className="text-xs font-semibold text-ps-body">
          {isAr ? "Advances received" : "Advances paid"} — on account
        </p>
        <p className="text-3xs text-ps-hint mt-0.5">
          {section.advances.length === 0
            ? `No ${noun} is outstanding, so the documents below are the whole of ${control}.`
            : `A ${noun} has no document to age against. It is listed here, outside the `
              + `buckets — ${isAr ? "an advance received is a liability" : "an advance paid is an asset"}, `
              + `and adding it to the ${isAr ? "receivables" : "payables"} note would misstate it.`}
        </p>
      </div>

      {section.gaps.length > 0 && (
        <div className="px-4 py-3 bg-amber-50/60 border-b border-amber-100 space-y-1.5">
          {section.gaps.map((g, i) => (
            <div key={i} className="flex items-start gap-2">
              <AlertTriangle size={12} className="text-amber-600 flex-shrink-0 mt-0.5" />
              <p className="text-3xs text-amber-900">{g}</p>
            </div>
          ))}
        </div>
      )}

      {section.advances.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-2xs">
            <thead>
              <tr className="border-b border-ps-border text-left text-ps-label">
                <th className="font-medium px-4 py-2">{isAr ? "Receipt" : "Payment"}</th>
                <th className="font-medium px-3 py-2">{isAr ? "Customer" : "Vendor"}</th>
                <th className="font-medium px-3 py-2">Date</th>
                <th className="font-medium px-3 py-2 text-right">Unapplied</th>
                <th className="font-medium px-3 py-2 text-right">Days old</th>
                <th className="font-medium px-4 py-2">Bucket</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {section.advances.map((a) => (
                <tr key={a.document_id} className="hover:bg-ps-bg">
                  <td className="px-4 py-2 text-ps-body">
                    {a.document_no || "—"}
                    {a.txn_currency && (
                      <span className="ml-1.5 text-[9px] text-ps-hint">{a.txn_currency}</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-ps-label truncate max-w-[180px]">
                    {a.party_name || "—"}
                  </td>
                  <td className="px-3 py-2 text-ps-label">{a.document_date || "—"}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-ps-ink">
                    {formatPaise(a.unapplied_paise)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-ps-label">{a.days_old}</td>
                  <td className="px-4 py-2 text-ps-hint">{a.aging_bucket}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* THE TIE-UP. Three lines, in the order a CA checks them. */}
      <div className="px-4 py-3 border-t border-ps-muted bg-ps-bg space-y-1">
        <div className="flex justify-between text-2xs text-ps-label">
          <span>{isAr ? "Open invoices" : "Open bills"}</span>
          <span className="tabular-nums">{formatPaise(section.total_outstanding_paise)}</span>
        </div>
        <div className="flex justify-between text-2xs text-ps-label">
          <span>Less advances on account</span>
          <span className="tabular-nums">({formatPaise(section.total_advances_paise)})</span>
        </div>
        <div className="flex justify-between text-2xs font-semibold text-ps-ink pt-1 border-t border-ps-border">
          <span>{control}</span>
          <span className="tabular-nums">{formatPaise(section.net_paise)}</span>
        </div>
      </div>
    </section>
  );
}

/**
 * The per-document ageing that sits behind the note, with the two marks the
 * note needs. Its buckets are the OPERATIONAL ones the collections view uses
 * (0-30 / 31-60 / 61-90 / 90+ days), not the statutory ones — a different
 * question, deliberately answered differently.
 */
function DocumentList({ kind, rows, saving, onClassify, clientId }: {
  kind: "receivables" | "payables";
  rows: AgeingDocument[] | null;
  saving: string | null;
  onClassify: (key: string, body: Parameters<typeof api.accounting.classifyForAgeing>[0]) => void;
  clientId: string;
}) {
  const isAr = kind === "receivables";
  if (rows === null) {
    return (
      <div className="flex items-center gap-2 text-2xs text-ps-hint py-8">
        <Loader2 size={14} className="animate-spin" /> Loading open documents…
      </div>
    );
  }
  if (rows.length === 0) {
    return (
      <div className="text-2xs text-ps-hint py-8 text-center bg-white rounded-xl border border-ps-muted">
        Nothing outstanding.
      </div>
    );
  }
  return (
    <div className="bg-white rounded-xl border border-ps-muted overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-50">
        <p className="text-xs font-semibold text-ps-body">
          {isAr ? "Open invoices" : "Open bills"}
        </p>
        <p className="text-3xs text-ps-hint mt-0.5">
          Marking a document disputed{isAr ? " or doubtful" : ""} moves it between the rows of
          the Schedule III note. Nothing is marked until somebody marks it.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-2xs">
          <thead>
            <tr className="border-b border-ps-border text-left text-ps-label">
              <th className="font-medium px-4 py-2">{isAr ? "Invoice" : "Bill"}</th>
              <th className="font-medium px-3 py-2">{isAr ? "Customer" : "Vendor"}</th>
              <th className="font-medium px-3 py-2">Date</th>
              <th className="font-medium px-3 py-2 text-right">Outstanding</th>
              <th className="font-medium px-3 py-2 text-right">Days</th>
              <th className="font-medium px-3 py-2">Bucket</th>
              <th className="font-medium px-3 py-2">Disputed</th>
              {isAr && <th className="font-medium px-4 py-2">Doubtful</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {rows.map((d) => {
              const id = (isAr ? d.invoice_id : d.bill_id) ?? "";
              const key = `${isAr ? "invoice" : "bill"}:${id}`;
              return (
                <tr key={id} className="hover:bg-ps-bg">
                  <td className="px-4 py-2 text-ps-body">{(isAr ? d.invoice_no : d.bill_no) || "—"}</td>
                  <td className="px-3 py-2 text-ps-label truncate max-w-[180px]">
                    {(isAr ? d.customer_name : d.vendor_name) || "—"}
                  </td>
                  <td className="px-3 py-2 text-ps-label">{(isAr ? d.invoice_date : d.bill_date) || "—"}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-ps-ink">
                    {formatPaise(d.outstanding_paise)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-ps-label">{d.days_overdue}</td>
                  <td className="px-3 py-2 text-ps-hint">{d.aging_bucket}</td>
                  <td className="px-3 py-2">
                    <MarkToggle
                      on={!!d.is_disputed}
                      busy={saving === key}
                      onClick={() => onClassify(key, {
                        client_id: clientId,
                        target: isAr ? "invoice" : "bill",
                        target_id: id, is_disputed: !d.is_disputed,
                      })}
                    />
                  </td>
                  {isAr && (
                    <td className="px-4 py-2">
                      <MarkToggle
                        on={!!d.considered_doubtful}
                        busy={saving === key}
                        onClick={() => onClassify(key, {
                          client_id: clientId, target: "invoice",
                          target_id: id, considered_doubtful: !d.considered_doubtful,
                        })}
                      />
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** A mark, and a way to take it back. A one-way button would be the wrong
 *  affordance for something that moves an amount between the rows of a signed
 *  note — a CA who marks the wrong invoice needs to be able to unmark it. */
function MarkToggle({ on, busy, onClick }: { on: boolean; busy: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      disabled={busy}
      aria-pressed={on}
      className={`text-3xs border rounded-md px-2 py-0.5 disabled:opacity-50 transition-colors ${
        on
          ? "border-amber-300 bg-amber-50 text-amber-800 hover:bg-amber-100"
          : "border-ps-border text-ps-hint hover:bg-ps-muted hover:text-ps-label"
      }`}
    >
      {busy ? "…" : on ? "Yes" : "No"}
    </button>
  );
}


/**
 * Where the two human steps behind the unbilled disclosure are taken.
 *
 * THEY ARE TWO STEPS, AND THAT IS THE POINT. Marking accounts says "these hold
 * unbilled dues". Only the review says "and there are no others" — which is
 * what the note actually claims, and what makes a nil printable. A client with
 * genuinely none marks nothing and records the review; a client nobody has
 * looked at has no figure at all, which is the truth.
 */
function UnbilledPanel({
  accounts, reviewedOn, note, onNote, saving, onMark, onReviewed,
}: {
  accounts: MarkableAccount[] | null;
  reviewedOn: string | null;
  note: string;
  onNote: (v: string) => void;
  saving: string | null;
  onMark: (a: MarkableAccount, side: "receivable" | "payable" | null) => void;
  onReviewed: (reviewed: boolean) => void;
}) {
  if (accounts === null) {
    return (
      <div className="flex items-center gap-2 text-2xs text-ps-hint py-8">
        <Loader2 size={14} className="animate-spin" /> Loading the chart of accounts…
      </div>
    );
  }
  const marked = accounts.filter((a) => a.unbilled_dues_side);

  return (
    <div className="space-y-5">
      <section className={`rounded-xl border overflow-hidden ${
        reviewedOn ? "bg-white border-ps-muted" : "bg-amber-50/50 border-amber-200"}`}>
        <div className="px-4 py-3">
          <p className="text-xs font-semibold text-ps-body">
            {reviewedOn ? `Reviewed ${reviewedOn}` : "Not yet reviewed"}
          </p>
          <p className="text-3xs text-ps-label mt-1">
            {reviewedOn
              ? `The note discloses ${marked.length === 0
                  ? "nil unbilled dues, affirmed by somebody rather than assumed"
                  : `the balances on ${marked.length} marked account${marked.length === 1 ? "" : "s"}`}.`
              : "Until somebody records that they have been through this client's chart of "
                + "accounts, the note shows no unbilled figure at all. A zero would claim the "
                + "client has none, when the truth is that nobody has looked."}
          </p>
          <div className="mt-2.5 flex items-center gap-2">
            {!reviewedOn && (
              <input
                value={note}
                onChange={(e) => onNote(e.target.value)}
                placeholder="Optional note — what you checked"
                className="flex-1 text-2xs border border-ps-border rounded-lg px-2.5 py-1.5 text-ps-body bg-white"
              />
            )}
            <button
              onClick={() => onReviewed(!reviewedOn)}
              disabled={saving === "review"}
              className={`flex items-center gap-1.5 text-2xs rounded-lg px-3 py-1.5 disabled:opacity-50 ${
                reviewedOn
                  ? "border border-ps-border text-ps-label hover:bg-ps-muted"
                  : "border border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100"}`}
            >
              {saving === "review" ? <Loader2 size={12} className="animate-spin" />
                : reviewedOn ? null : <Check size={12} />}
              {reviewedOn ? "Withdraw the review" : "I have marked every account that holds unbilled dues"}
            </button>
          </div>
          {reviewedOn && (
            <p className="text-3xs text-ps-hint mt-2">
              Withdrawing puts the disclosure back into its gap — for when the chart of
              accounts has moved on and the review no longer stands.
            </p>
          )}
        </div>
      </section>

      <section className="bg-white rounded-xl border border-ps-muted overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-50">
          <p className="text-xs font-semibold text-ps-body">
            Which accounts hold unbilled dues
          </p>
          <p className="text-3xs text-ps-hint mt-0.5">
            Accrued income is an ASSET and goes under receivables; accrued expenses and
            goods received not invoiced are a LIABILITY and go under payables. Only assets
            and liabilities are listed — the P&amp;L leg of an accrual is not the due, and
            marking it would count the same money twice.
          </p>
        </div>
        {accounts.length === 0 ? (
          <p className="px-4 py-6 text-2xs text-ps-hint text-center">
            This client has no active asset or liability accounts.
          </p>
        ) : (
          <div className="divide-y divide-gray-50">
            {accounts.map((a) => (
              <div key={a.id} className="px-4 py-2 flex items-center gap-3">
                <span className="text-3xs text-ps-hint tabular-nums w-14 flex-shrink-0">
                  {a.account_code}
                </span>
                <span className="text-2xs text-ps-body flex-1 truncate">{a.account_name}</span>
                <span className="text-3xs text-ps-disabled w-16 flex-shrink-0">{a.account_type}</span>
                <select
                  value={a.unbilled_dues_side ?? ""}
                  disabled={saving === a.id}
                  onChange={(e) => onMark(
                    a, (e.target.value || null) as "receivable" | "payable" | null)}
                  className="text-3xs border border-ps-border rounded-md px-2 py-1 text-ps-body bg-white disabled:opacity-50"
                >
                  <option value="">Not unbilled dues</option>
                  {/* Offered per type, because the database refuses the other
                      pairing anyway — an asset cannot hold accrued expenses. */}
                  {a.account_type === "Asset"
                    ? <option value="receivable">Unbilled — receivables</option>
                    : <option value="payable">Unbilled — payables</option>}
                </select>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
