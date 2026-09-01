"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowLeft, RefreshCw, AlertTriangle, Info, Loader2, ChevronDown,
} from "lucide-react";
import {
  api, type ApiResp, type AgeingSchedule, type AgeingTable, type AgeingDocument,
  type AgeingClassifyBody,
} from "@/lib/api";
import { formatPaise } from "@/lib/services/formatting";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

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
 */

type Tab = "note" | "receivables" | "payables";

const TABS: { id: Tab; label: string; hint: string }[] = [
  { id: "note", label: "Schedule III note", hint: "The two prescribed tables" },
  { id: "receivables", label: "Receivables detail", hint: "Open invoices, and what to mark" },
  { id: "payables", label: "Payables detail", hint: "Open bills, and what to mark" },
];

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

function todayISO(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function Amount({ paise }: { paise: number }) {
  return (
    <span className={paise ? "tabular-nums text-[#1E293B]" : "tabular-nums text-[#CBD5E1]"}>
      {paise ? formatPaise(paise) : "—"}
    </span>
  );
}

/** One prescribed table. Columns come from the payload, never from this file. */
function ScheduleTable({ table }: { table: AgeingTable }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px] border-collapse">
        <thead>
          <tr className="border-b border-[#E2E8F0]">
            <th className="text-left font-medium text-[#64748B] px-4 py-2.5 min-w-[280px]">
              Particulars
            </th>
            {table.buckets.map((b) => (
              <th
                key={b.key}
                className={`text-right font-medium px-3 py-2.5 whitespace-nowrap ${
                  b.prescribed ? "text-[#64748B]" : "text-[#94A3B8] italic border-r border-dashed border-[#E2E8F0]"
                }`}
              >
                {b.label}
                {!b.prescribed && <sup className="ml-0.5">†</sup>}
              </th>
            ))}
            <th className="text-right font-semibold text-[#334155] px-4 py-2.5">Total</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-50">
          {table.rows.map((r) => (
            <tr key={r.key} className="hover:bg-[#F8FAFC]">
              <td className="px-4 py-2.5 text-[#334155]">{r.label}</td>
              {table.buckets.map((b) => (
                <td
                  key={b.key}
                  className={`text-right px-3 py-2.5 ${
                    b.prescribed ? "" : "border-r border-dashed border-[#E2E8F0] bg-[#FAFBFC]"
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
          <tr className="border-t-2 border-[#E2E8F0] bg-[#F8FAFC]">
            <td className="px-4 py-2.5 font-semibold text-[#1E293B]">Total</td>
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
  const [asOf, setAsOf] = useState<string>(todayISO());
  const [schedule, setSchedule] = useState<AgeingSchedule | null>(null);
  const [invoices, setInvoices] = useState<AgeingDocument[] | null>(null);
  const [bills, setBills] = useState<AgeingDocument[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!clientId) return;
    setLoading(true);
    setError(null);
    try {
      const r = await api.accounting.scheduleIiiAgeing(clientId, asOf) as ApiResp<AgeingSchedule>;
      if (!r.success) throw new Error(r.error ?? "Could not build the ageing schedule");
      setSchedule(r.data);
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
      if (!ar.success) setDetailError(ar.error ?? "Could not load the open invoices");
      else if (!ap.success) setDetailError(ap.error ?? "Could not load the open bills");
    } catch (e) {
      setDetailError(e instanceof Error ? e.message : "Could not load the open documents");
    }
  }, [clientId, asOf]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (tab !== "note" && invoices === null && bills === null) loadDetail();
  }, [tab, invoices, bills, loadDetail]);

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
  const gapsByCode = useMemo(
    () => Object.fromEntries((schedule?.gaps ?? []).map((g) => [g.code, g.message])),
    [schedule],
  );

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <button
            onClick={() => router.push(`/clients/${clientId}/reports`)}
            className="flex items-center gap-1 text-[11px] text-[#94A3B8] hover:text-[#64748B] mb-1.5"
          >
            <ArrowLeft size={12} /> Reports
          </button>
          <h2 className="text-sm font-semibold text-[#1E293B]">Ageing schedules</h2>
          <p className="text-[11px] text-[#94A3B8] mt-0.5">
            {schedule?.statute ??
              "Schedule III to the Companies Act 2013, as amended by MCA Notification G.S.R. 207(E) dated 24 March 2021"}
          </p>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <label className="text-[11px] text-[#64748B]">As at</label>
          <input
            type="date"
            value={asOf}
            onChange={(e) => { setAsOf(e.target.value); setInvoices(null); setBills(null); }}
            className="text-[11px] border border-[#E2E8F0] rounded-lg px-2.5 py-1.5 text-[#334155]"
          />
          <button
            onClick={() => { setInvoices(null); setBills(null); load(); }}
            className="flex items-center gap-1.5 text-[11px] text-[#64748B] hover:text-[#334155] border border-[#E2E8F0] rounded-lg px-2.5 py-1.5"
          >
            <RefreshCw size={12} /> Refresh
          </button>
        </div>
      </div>

      <div className="flex gap-1 border-b border-[#F1F5F9]">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            title={t.hint}
            className={`text-[11px] px-3 py-2 border-b-2 -mb-px transition-colors ${
              tab === t.id
                ? "border-blue-600 text-blue-700 font-medium"
                : "border-transparent text-[#94A3B8] hover:text-[#64748B]"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-[11px] text-[#94A3B8] py-8">
          <Loader2 size={14} className="animate-spin" /> Building the schedule…
        </div>
      )}

      {error && (
        <div className="flex items-start gap-2.5 bg-red-50 border border-red-100 rounded-xl px-4 py-3">
          <AlertTriangle size={14} className="text-red-500 flex-shrink-0 mt-0.5" />
          <p className="text-[11px] text-red-700">{error}</p>
        </div>
      )}

      {detailError && (
        <div className="flex items-start gap-2.5 bg-amber-50 border border-amber-100 rounded-xl px-4 py-3">
          <AlertTriangle size={14} className="text-amber-600 flex-shrink-0 mt-0.5" />
          <p className="text-[11px] text-amber-900">{detailError}</p>
        </div>
      )}

      {!loading && !error && schedule && (
        <>
          {/* The gaps, always visible — they are what stops the note being signed. */}
          {schedule.gaps.length > 0 && (
            <div className="bg-amber-50 border border-amber-100 rounded-xl px-4 py-3 space-y-2">
              {schedule.gaps.map((g) => (
                <div key={g.code} className="flex items-start gap-2.5">
                  <AlertTriangle size={13} className="text-amber-600 flex-shrink-0 mt-0.5" />
                  <p className="text-[11px] text-amber-900">{g.message}</p>
                </div>
              ))}
            </div>
          )}

          {tab === "note" && (
            <div className="space-y-5">
              <section className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
                <div className="px-4 py-3 border-b border-gray-50">
                  <p className="text-xs font-semibold text-[#334155]">
                    {schedule.receivables.title}
                  </p>
                  <p className="text-[10px] text-[#94A3B8] mt-0.5">
                    Outstanding for the following periods from {schedule.ageing_from}.
                  </p>
                </div>
                <ScheduleTable table={schedule.receivables} />
                <UnbilledLine paise={schedule.receivables.unbilled_dues_paise}
                              why={gapsByCode["unbilled_dues_not_modelled"]} />
              </section>

              {unclassified.length > 0 && (
                <section className="bg-white rounded-xl border border-amber-200 overflow-hidden">
                  <div className="px-4 py-3 border-b border-amber-100 bg-amber-50/50">
                    <p className="text-xs font-semibold text-[#334155]">
                      Classify these vendors before signing the payables note
                    </p>
                    <p className="text-[10px] text-[#94A3B8] mt-0.5">
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
                        <p className="text-[11px] text-[#334155] flex-1 min-w-0 truncate">
                          {v.vendor_name}
                        </p>
                        <p className="text-[11px] tabular-nums text-[#64748B]">
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

              <section className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
                <div className="px-4 py-3 border-b border-gray-50">
                  <p className="text-xs font-semibold text-[#334155]">
                    {schedule.payables.title}
                  </p>
                  <p className="text-[10px] text-[#94A3B8] mt-0.5">
                    Four prescribed columns, from one year — deliberately not the receivables&apos;
                    five. Row (i) is micro and small enterprises only.
                  </p>
                </div>
                <ScheduleTable table={schedule.payables} />
                <UnbilledLine paise={schedule.payables.unbilled_dues_paise}
                              why={gapsByCode["unbilled_dues_not_modelled"]} />
              </section>

              <div className="flex items-start gap-2.5 bg-[#F8FAFC] border border-[#E2E8F0] rounded-xl px-4 py-3">
                <Info size={13} className="text-[#94A3B8] flex-shrink-0 mt-0.5" />
                <p className="text-[10px] text-[#64748B]">
                  <span className="font-medium">†</span> &ldquo;Not due&rdquo; is not one of the
                  prescribed columns. It is shown separately because folding not-yet-due balances
                  into the first bucket overstates the ageing of a current book. To present the
                  prescribed table, add it into the first column — the row totals are the same
                  number either way.
                </p>
              </div>
            </div>
          )}

          {tab !== "note" && (
            <DocumentList
              kind={tab}
              rows={(tab === "receivables" ? invoices : bills) ?? null}
              saving={saving}
              onClassify={classify}
              clientId={clientId}
            />
          )}
        </>
      )}
    </div>
  );
}

function UnbilledLine({ paise, why }: { paise: number | null; why?: string }) {
  return (
    <div className="px-4 py-2.5 border-t border-gray-50 flex items-center gap-2">
      <p className="text-[10px] text-[#94A3B8] flex-1">
        Unbilled dues (disclosed separately under Schedule III)
      </p>
      <p className="text-[10px] text-[#94A3B8]" title={why}>
        {paise === null ? "Not modelled — see the note above" : formatPaise(paise)}
      </p>
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
        className="text-[11px] border border-[#E2E8F0] rounded-lg pl-2.5 pr-7 py-1.5 text-[#334155] appearance-none bg-white disabled:opacity-50"
      >
        {MSME_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
      {busy
        ? <Loader2 size={11} className="animate-spin absolute right-2 text-[#94A3B8]" />
        : <ChevronDown size={11} className="absolute right-2 text-[#94A3B8] pointer-events-none" />}
    </div>
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
      <div className="flex items-center gap-2 text-[11px] text-[#94A3B8] py-8">
        <Loader2 size={14} className="animate-spin" /> Loading open documents…
      </div>
    );
  }
  if (rows.length === 0) {
    return (
      <div className="text-[11px] text-[#94A3B8] py-8 text-center bg-white rounded-xl border border-[#F1F5F9]">
        Nothing outstanding.
      </div>
    );
  }
  return (
    <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-50">
        <p className="text-xs font-semibold text-[#334155]">
          {isAr ? "Open invoices" : "Open bills"}
        </p>
        <p className="text-[10px] text-[#94A3B8] mt-0.5">
          Marking a document disputed{isAr ? " or doubtful" : ""} moves it between the rows of
          the Schedule III note. Nothing is marked until somebody marks it.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="border-b border-[#E2E8F0] text-left text-[#64748B]">
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
                <tr key={id} className="hover:bg-[#F8FAFC]">
                  <td className="px-4 py-2 text-[#334155]">{(isAr ? d.invoice_no : d.bill_no) || "—"}</td>
                  <td className="px-3 py-2 text-[#64748B] truncate max-w-[180px]">
                    {(isAr ? d.customer_name : d.vendor_name) || "—"}
                  </td>
                  <td className="px-3 py-2 text-[#64748B]">{(isAr ? d.invoice_date : d.bill_date) || "—"}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-[#1E293B]">
                    {formatPaise(d.outstanding_paise)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-[#64748B]">{d.days_overdue}</td>
                  <td className="px-3 py-2 text-[#94A3B8]">{d.aging_bucket}</td>
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
      className={`text-[10px] border rounded-md px-2 py-0.5 disabled:opacity-50 transition-colors ${
        on
          ? "border-amber-300 bg-amber-50 text-amber-800 hover:bg-amber-100"
          : "border-[#E2E8F0] text-[#94A3B8] hover:bg-[#F1F5F9] hover:text-[#64748B]"
      }`}
    >
      {busy ? "…" : on ? "Yes" : "No"}
    </button>
  );
}
