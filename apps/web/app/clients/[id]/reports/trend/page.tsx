"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import * as XLSX from "xlsx";
import {
  ArrowLeft, RefreshCw, AlertTriangle, Info, Loader2, Download,
  TrendingUp, TrendingDown, Minus,
} from "lucide-react";
import { api, type MultiYearTrend, type TrendSeries, type TrendRatioSeries } from "@/lib/api";
import { formatPaise } from "@/lib/services/formatting";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

/**
 * The multi-year trend — Schedule III captions and the clause (Q) ratios across
 * several financial years, with the movement between them.
 *
 * THE FIRST THING THIS PAGE SAYS IS THAT IT IS NOT THE STATEMENTS. Schedule III
 * General Instructions para 5 requires the corresponding amounts for the
 * IMMEDIATELY PRECEDING period — one comparative, which the balance sheet and
 * the statement of profit and loss carry. Nothing prescribes a five-year trend
 * and this one is unaudited. It is what a CA puts in front of a client at the
 * annual meeting and what a bank asks for with a loan application, and a reader
 * who mistook it for the filed statements would be reading an unaudited
 * document as an audited one. The banner is not decoration.
 *
 * ZERO BUSINESS LOGIC. Every amount, every ratio and every movement comes from
 * /api/accounting/schedule-iii/trend, which computes them with the same
 * functions the statements and the ratio note use. This file lays out and
 * formats; it does not know what any caption means, and must not learn.
 *
 * ONE REQUEST FOR THE WHOLE WINDOW. The service reads the client's buckets once
 * and projects each year from them in memory, so ten years costs what one
 * costs. Fetching a year at a time from here would put that cost straight back.
 *
 * WHY A YEAR CAN BE MISSING. A client onboarded two years ago has no 2022-23,
 * and a column of zeros would assert the business had nil revenue and nil
 * assets that year — a claim about the business rather than about the records.
 * The backend drops those years and names them; this page repeats the naming
 * rather than quietly showing a shorter table.
 */

const YEAR_CHOICES = [3, 5, 7, 10];

function currentFY(): string {
  const now = new Date();
  const start = now.getMonth() + 1 >= 4 ? now.getFullYear() : now.getFullYear() - 1;
  return `${start}-${String(start + 1).slice(2)}`;
}

/** bps -> display. 10,000 bps = 1.00. */
function formatBps(bps: number | null, unit: "times" | "percent"): string {
  if (bps === null) return "—";
  const v = bps / 100;                       // bps -> percentage points
  return unit === "percent" ? `${v.toFixed(2)}%` : `${(v / 100).toFixed(2)}×`;
}

/** A movement, in percent, from a bps figure. null means "off a zero base" —
 *  undefined, not infinite, and never rendered as 0%. */
function formatMovement(bps: number | null): string {
  if (bps === null) return "—";
  const pct = bps / 100;
  return `${pct > 0 ? "+" : ""}${pct.toFixed(1)}%`;
}

/** Green / red only where the direction has a meaning. `higher_is_better` is
 *  null for lines where it depends on the business — borrowings are not bad and
 *  inventory is not good — and those stay neutral rather than being coloured on
 *  a guess. */
function movementTone(bps: number | null, higherIsBetter: boolean | null): string {
  if (bps === null || bps === 0 || higherIsBetter === null) return "text-[#94A3B8]";
  const good = bps > 0 ? higherIsBetter : !higherIsBetter;
  return good ? "text-emerald-600" : "text-red-600";
}

function MovementIcon({ bps }: { bps: number | null }) {
  if (bps === null || bps === 0) return <Minus size={10} className="inline" />;
  return bps > 0
    ? <TrendingUp size={10} className="inline" />
    : <TrendingDown size={10} className="inline" />;
}

export default function ClientTrendPage() {
  // Not useParams(): apps/web is a static export and Cloudflare's 200-rewrite
  // serves the pre-rendered "_placeholder" HTML for every real client URL, so
  // useParams().id is the literal "_placeholder". useClientNav reads the real
  // UUID out of window.location.
  const { clientId } = useClientNav();
  const router = useRouter();

  const [years, setYears] = useState(5);
  const [toFy, setToFy] = useState(currentFY());
  const [trend, setTrend] = useState<MultiYearTrend | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!clientId) return;
    setLoading(true);
    setError(null);
    try {
      const r = await api.accounting.scheduleIiiTrend(clientId, years, toFy);
      if (!r.success) throw new Error(r.error ?? "Could not build the trend");
      setTrend(r.data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not build the trend");
    } finally {
      setLoading(false);
    }
  }, [clientId, years, toFy]);

  useEffect(() => { load(); }, [load]);

  const fyChoices = Array.from({ length: 6 }, (_, i) => {
    const y = Number(currentFY().split("-")[0]) - i;
    return `${y}-${String(y + 1).slice(2)}`;
  });

  const exportExcel = useCallback(() => {
    if (!trend) return;
    // Rupees at the spreadsheet boundary only — the wire and every computation
    // above are integer paise.
    const rupees = (p: number) => (p / 100).toFixed(2);
    const rows: Record<string, string>[] = [];
    const push = (section: string, item: string, values: string[]) => {
      const r: Record<string, string> = { Section: section, Item: item };
      trend.fys.forEach((fy, i) => { r[fy] = values[i] ?? ""; });
      rows.push(r);
    };
    push("", trend.basis, []);
    push("PROFIT & LOSS", "", []);
    for (const s of trend.profit_and_loss) push("", s.label, s.values_paise.map(rupees));
    push("BALANCE SHEET", "", []);
    for (const s of trend.balance_sheet) push("", s.label, s.values_paise.map(rupees));
    push("RATIOS", "", []);
    for (const s of trend.ratios) {
      push("", `${s.clause} ${s.label}`,
           s.values_bps.map((b) => (b === null ? "" : formatBps(b, s.unit))));
    }
    const ws = XLSX.utils.json_to_sheet(rows);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Trend");
    XLSX.writeFile(wb, `trend_${trend.fys[0] ?? ""}_to_${trend.fys[trend.fys.length - 1] ?? ""}.xlsx`);
  }, [trend]);

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
          <h2 className="text-sm font-semibold text-[#1E293B]">Multi-year trend</h2>
          <p className="text-[11px] text-[#94A3B8] mt-0.5">
            Schedule III captions and the clause (Q) ratios, year on year, with the
            movement between them
          </p>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <label className="text-[11px] text-[#64748B]">Years</label>
          <select
            value={years}
            onChange={(e) => setYears(Number(e.target.value))}
            className="text-[11px] border border-[#E2E8F0] rounded-lg px-2.5 py-1.5 text-[#334155] bg-white"
          >
            {YEAR_CHOICES.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
          <label className="text-[11px] text-[#64748B]">to</label>
          <select
            value={toFy}
            onChange={(e) => setToFy(e.target.value)}
            className="text-[11px] border border-[#E2E8F0] rounded-lg px-2.5 py-1.5 text-[#334155] bg-white"
          >
            {fyChoices.map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
          <button
            onClick={load}
            className="flex items-center gap-1.5 text-[11px] text-[#64748B] hover:text-[#334155] border border-[#E2E8F0] rounded-lg px-2.5 py-1.5"
          >
            <RefreshCw size={12} /> Refresh
          </button>
          <button
            onClick={exportExcel}
            disabled={!trend || trend.fys.length === 0}
            className="flex items-center gap-1.5 text-[11px] text-[#64748B] hover:text-[#334155] border border-[#E2E8F0] rounded-lg px-2.5 py-1.5 disabled:opacity-40"
          >
            <Download size={12} /> Excel
          </button>
        </div>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-[11px] text-[#94A3B8] py-8">
          <Loader2 size={14} className="animate-spin" /> Building the window…
        </div>
      )}

      {error && (
        <div className="flex items-start gap-2.5 bg-red-50 border border-red-100 rounded-xl px-4 py-3">
          <AlertTriangle size={14} className="text-red-500 flex-shrink-0 mt-0.5" />
          <p className="text-[11px] text-red-700">{error}</p>
        </div>
      )}

      {!loading && trend && (
        <>
          {/* The banner is the point, not the chrome. */}
          <div className="flex items-start gap-2.5 bg-blue-50/60 border border-blue-100 rounded-xl px-4 py-3">
            <Info size={14} className="text-blue-500 flex-shrink-0 mt-0.5" />
            <p className="text-[11px] text-blue-900">{trend.basis}</p>
          </div>

          {trend.dropped_fys.length > 0 && (
            <div className="flex items-start gap-2.5 bg-amber-50 border border-amber-100 rounded-xl px-4 py-3">
              <AlertTriangle size={14} className="text-amber-600 flex-shrink-0 mt-0.5" />
              <p className="text-[11px] text-amber-900">
                <span className="font-medium">
                  {trend.dropped_fys.join(", ")} left out
                </span>{" "}
                — nothing is recorded against{" "}
                {trend.dropped_fys.length === 1 ? "that year" : "those years"}. Shown as
                zeros they would assert the business had nil revenue and nil assets,
                which is a claim about the business rather than about the records.
              </p>
            </div>
          )}

          {/* A failed read is NOT a year with nothing in it, and the two must
              not share a banner. The amber one above says the business has no
              records for those years; this one says the request failed and the
              books may be complete. */}
          {trend.unreadable_fys.length > 0 && (
            <div className="flex items-start gap-2.5 bg-red-50 border border-red-100 rounded-xl px-4 py-3">
              <AlertTriangle size={14} className="text-red-500 flex-shrink-0 mt-0.5" />
              <p className="text-[11px] text-red-800">
                <span className="font-medium">
                  {trend.unreadable_fys.join(", ")} could not be read
                </span>{" "}
                and {trend.unreadable_fys.length === 1 ? "is" : "are"} missing from this
                trend. That is a failure of this request, not a finding about the books —
                those years may be complete. Reload before drawing any conclusion from the
                window shown.
              </p>
            </div>
          )}

          {trend.gaps.filter(
            (g) => g.code !== "years_without_records_dropped" && g.code !== "years_unreadable",
          ).length > 0 && (
            <div className="bg-[#F8FAFC] border border-[#E2E8F0] rounded-xl px-4 py-3 space-y-2">
              {trend.gaps
                .filter((g) => g.code !== "years_without_records_dropped"
                            && g.code !== "years_unreadable")
                .map((g) => (
                  <div key={g.code} className="flex items-start gap-2.5">
                    <Info size={13} className="text-[#94A3B8] flex-shrink-0 mt-0.5" />
                    <p className="text-[10px] text-[#64748B]">{g.message}</p>
                  </div>
                ))}
            </div>
          )}

          {trend.fys.length === 0 ? (
            <div className="bg-white rounded-xl border border-[#F1F5F9] px-4 py-10 text-center">
              <p className="text-xs text-[#64748B]">
                Nothing is recorded against any of the years asked for.
              </p>
            </div>
          ) : (
            <>
              <AmountTable title="Statement of Profit & Loss"
                           note="Each year at its own figures, from the same bucketing the statements use."
                           fys={trend.fys} series={trend.profit_and_loss} />
              <AmountTable title="Balance Sheet"
                           note="As at 31 March of each year."
                           fys={trend.fys} series={trend.balance_sheet} />
              <RatioTable fys={trend.fys} series={trend.ratios} />
            </>
          )}
        </>
      )}
    </div>
  );
}

function ColumnHeads({ fys }: { fys: string[] }) {
  return (
    <tr className="text-[10px] text-[#94A3B8]">
      <th className="text-left font-medium px-4 py-2">Particulars</th>
      {fys.map((fy) => (
        <th key={fy} className="text-right font-medium px-3 py-2 tabular-nums">{fy}</th>
      ))}
    </tr>
  );
}

function AmountTable({ title, note, fys, series }: {
  title: string; note: string; fys: string[]; series: TrendSeries[];
}) {
  return (
    <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-50">
        <p className="text-xs font-semibold text-[#334155]">{title}</p>
        <p className="text-[10px] text-[#94A3B8] mt-0.5">{note}</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px]">
          <thead className="bg-[#FAFBFC] border-b border-gray-50"><ColumnHeads fys={fys} /></thead>
          <tbody className="divide-y divide-gray-50">
            {series.map((s) => (
              <tr key={s.key}>
                <td className="px-4 py-2 text-[11px] text-[#334155]">{s.label}</td>
                {s.values_paise.map((v, i) => (
                  <td key={fys[i]} className="px-3 py-2 text-right">
                    <div className="text-[11px] tabular-nums text-[#1E293B]">{formatPaise(v)}</div>
                    {/* Movement sits under the year it moved INTO, so the first
                        column has none — there is nothing before it. */}
                    {i > 0 && (
                      <div className={`text-[9px] tabular-nums ${
                        movementTone(s.movement_bps[i - 1], s.higher_is_better)}`}>
                        <MovementIcon bps={s.movement_bps[i - 1]} />{" "}
                        {formatMovement(s.movement_bps[i - 1])}
                        <span className="text-[#CBD5E1]">
                          {" "}({formatPaise(s.movement_paise[i - 1])})
                        </span>
                      </div>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RatioTable({ fys, series }: { fys: string[]; series: TrendRatioSeries[] }) {
  return (
    <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-50">
        <p className="text-xs font-semibold text-[#334155]">Ratios</p>
        <p className="text-[10px] text-[#94A3B8] mt-0.5">
          The same eleven ratios as the clause (Q) note, so a figure here cannot mean
          something different from the same figure there. The note is where the 25%
          movements are explained; this is the movement across the whole window.
        </p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px]">
          <thead className="bg-[#FAFBFC] border-b border-gray-50"><ColumnHeads fys={fys} /></thead>
          <tbody className="divide-y divide-gray-50">
            {series.map((s) => (
              <tr key={s.key}>
                <td className="px-4 py-2">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] text-[#94A3B8] tabular-nums">{s.clause}</span>
                    <span className="text-[11px] text-[#334155]">{s.label}</span>
                  </div>
                  {/* A gap is stated, never left blank — a dash reads as
                      "nothing to report", which is its opposite. */}
                  {s.unavailable_reason && (
                    <p className="text-[10px] text-amber-800 mt-1 bg-amber-50 border border-amber-100 rounded-lg px-2 py-1">
                      {s.unavailable_reason}
                    </p>
                  )}
                </td>
                {s.values_bps.map((v, i) => (
                  <td key={fys[i]} className="px-3 py-2 text-right">
                    <div className="text-[11px] tabular-nums text-[#1E293B]">
                      {s.unavailable_reason && v === null ? "Not computed" : formatBps(v, s.unit)}
                    </div>
                    {/* Deliberately uncoloured. A ratio rising is not good or
                        bad on its own — debt-equity up is a worse balance sheet,
                        current ratio up is usually a better one, and inventory
                        turnover up can be either. Colouring these would be the
                        page making a judgement it has no basis for. */}
                    {i > 0 && (
                      <div className="text-[9px] tabular-nums text-[#94A3B8]">
                        {formatMovement(s.movement_bps[i - 1])}
                      </div>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
