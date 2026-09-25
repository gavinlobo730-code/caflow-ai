"use client";

import { useCallback, useEffect, useState } from "react";
import { BarChart3, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import type { BenchmarkPayload, BenchmarkDistribution } from "@/lib/api";
import { objectWithLists } from "@/lib/api/shape";
import { formatPaise } from "@/lib/services/formatting";
import { currentFinancialYearLabel } from "@/lib/dateMath";
import FinancialYearPicker from "@/components/FinancialYearPicker";
import { EmptyState, ErrorState } from "@/components/ui/states";

/**
 * Where each client sits in the firm's own tax and cost distribution —
 * plan rows 3c-1, 3c-2, 3c-4 and the tax half of 3c-5, STUCK.md §1.
 *
 * ⚠️ THIS SCREEN COMPUTES NOTHING, and could not have been built until the
 * figures were stored. `/practice/profitability` next door answers the FEE
 * half, because fee revenue and cost are already aggregated one read each; a
 * client's effective tax rate is derived from that client's whole ledger, so
 * computing it for fifty clients to place one of them is CLAUDE.md's reporting
 * rule broken twice over. Migration 417 stores the aggregates, the 06:00 IST
 * sweep fills them, and this reads a few dozen rows.
 *
 * ── A DASH IS NOT A ZERO ─────────────────────────────────────────────────
 *
 * Every figure the sweep could not derive comes back NULL and is EXCLUDED from
 * its distribution — `n` says how many clients actually answered and
 * `not_measured` names the rest. So a column with no median renders a dash and
 * says who is missing, never ₹0.00: in a distribution an absent figure read as
 * zero moves every median it is counted in and makes the client it belongs to
 * read as the firm's best performer on a ratio nobody computed for them.
 *
 * ── IT RANKS AND NEVER JUDGES ────────────────────────────────────────────
 *
 * No band, no threshold, no colour saying a client is doing badly. An
 * effective tax rate above the firm's median is a fact; "high" is an opinion
 * about a client's affairs that would be read as advice.
 * `domain/practice/client_metrics` refuses the same thing on the server, and
 * `concentration.py` refuses the ICAI fee-dependence percentage for the same
 * reason.
 *
 * ── EVERY LABEL IS SERVED ────────────────────────────────────────────────
 *
 * `figure_meaning` and `money_figures` travel on the payload, so this file
 * holds no copy of the twelve figures or of which format as rupees — the
 * Schedule III caption lesson. The RATIO headings are the one thing named
 * here, because they are the question a reader is asking rather than a
 * definition the engine owns.
 *
 * ⚠️ NOT `PartnerGuard`. The endpoint is assignment-scoped, and migration
 * 417's RESTRICTIVE policy says the same thing in SQL — a Manager sees the
 * distribution of their own book, which is the honest answer to a question
 * about the firm they can see. A screen that refused everyone but a Partner
 * would make that narrowing dead code.
 */

const RATIO_LABELS: Record<string, string> = {
  effective_tax_rate_bps: "Effective tax rate",
  gst_to_turnover_bps: "GST output to turnover",
  itc_to_purchases_bps: "ITC to purchases",
  itc_reversal_rate_bps: "Credit reversed, of credit availed",
  tds_to_purchases_bps: "TDS withheld, of purchases",
  payroll_to_turnover_bps: "Payroll cost to turnover",
};

function pct(bps: number | null): string {
  if (bps === null) return "—";
  return `${(bps / 100).toFixed(2)}%`;
}

function Row({ d, format }: { d: BenchmarkDistribution; format: (v: number | null) => string }) {
  return (
    <tr className="border-t border-ps-border">
      <td className="py-2 pr-4 text-sm text-ps-body">{d.key}</td>
      <td className="py-2 pr-4 text-sm text-ps-ink tabular-nums text-right">{format(d.median)}</td>
      <td className="py-2 pr-4 text-sm text-ps-body tabular-nums text-right">{format(d.lowest)}</td>
      <td className="py-2 pr-4 text-sm text-ps-body tabular-nums text-right">{format(d.highest)}</td>
      <td className="py-2 pr-4 text-sm text-ps-hint tabular-nums text-right">{d.n}</td>
      <td className="py-2 text-3xs text-ps-hint">
        {d.not_measured.length === 0
          ? "—"
          : `not measured for ${d.not_measured.join(", ")}`}
      </td>
    </tr>
  );
}

function Table({
  title,
  rows,
  format,
  label,
  meaning,
}: {
  title: string;
  rows: BenchmarkDistribution[];
  format: (key: string) => (v: number | null) => string;
  label: (key: string) => string;
  meaning?: Record<string, string>;
}) {
  if (rows.length === 0) return null;
  return (
    <section className="bg-white rounded-xl border border-ps-border overflow-hidden">
      <h2 className="text-sm font-semibold text-ps-ink px-4 pt-4 pb-2">{title}</h2>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[680px]">
          <thead>
            <tr className="text-3xs uppercase tracking-wide text-ps-hint">
              <th className="text-left font-medium py-2 px-4">Figure</th>
              <th className="text-right font-medium py-2 pr-4">Median</th>
              <th className="text-right font-medium py-2 pr-4">Lowest</th>
              <th className="text-right font-medium py-2 pr-4">Highest</th>
              <th className="text-right font-medium py-2 pr-4">Clients</th>
              <th className="text-left font-medium py-2 pr-4">Gaps</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((d) => (
              <Row
                key={d.key}
                d={{ ...d, key: label(d.key) }}
                format={format(d.key)}
              />
            ))}
          </tbody>
        </table>
      </div>
      {meaning && (
        <dl className="px-4 pb-4 pt-2 space-y-1.5 border-t border-ps-border">
          {rows.map((d) => (
            <div key={d.key} className="text-3xs">
              <dt className="inline font-medium text-ps-body">{label(d.key)}: </dt>
              <dd className="inline text-ps-hint">{meaning[d.key] ?? ""}</dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}

export default function BenchmarkPage() {
  const [fy, setFy] = useState(currentFinancialYearLabel());
  const [data, setData] = useState<BenchmarkPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.analytics.benchmark(fy);
      if (!res?.success) throw new Error(res?.error || "Could not load the benchmark");
      // The payload's two lists and the two maps are narrowed together: a
      // frontend ahead of its backend, or a refusal answered as HTTP 200,
      // would otherwise reach `.map` on undefined. See CLAUDE.md on
      // `objectWithLists`.
      setData(objectWithLists<BenchmarkPayload>(
        res.data,
        "figures", "ratios", "subject_positions", "money_figures", "notes",
      ));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load the benchmark");
    } finally {
      setLoading(false);
    }
  }, [fy]);

  useEffect(() => { void load(); }, [load]);

  const money = new Set(data?.money_figures ?? []);
  const formatFigure = (key: string) => (v: number | null) =>
    v === null ? "—" : money.has(key) ? formatPaise(v) : String(v);

  const figureLabel = (key: string) =>
    key.replace(/_paise$/, "").replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

  return (
    <div className="p-4 md:p-6 space-y-4 max-w-5xl">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <BarChart3 size={18} className="text-ps-label" />
          <h1 className="text-base font-semibold text-ps-ink">Client benchmark</h1>
        </div>
        <div className="flex items-center gap-2">
          <FinancialYearPicker value={fy} onChange={setFy} />
          <button
            onClick={() => void load()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-ps-border bg-white px-3 py-1.5 text-sm text-ps-body hover:bg-ps-hover transition-colors"
          >
            <RefreshCw size={14} />
            Refresh
          </button>
        </div>
      </header>

      {error && <ErrorState message={error} onRetry={() => void load()} />}

      {!error && loading && (
        <p className="text-sm text-ps-hint">Loading the firm&apos;s distribution…</p>
      )}

      {!error && !loading && data && data.clients === 0 && (
        <EmptyState
          title={`No stored figures for FY ${data.financial_year}`}
          description={
            "The nightly sweep fills these at 06:00 IST, for this financial " +
            "year and the one before it. A year outside that window, or a " +
            "firm whose first sweep has not run, has no rows yet — which is " +
            "not the same as a firm whose clients had nothing to report."
          }
        />
      )}

      {!error && !loading && data && data.clients > 0 && (
        <>
          <p className="text-sm text-ps-body">
            {data.clients} client{data.clients === 1 ? "" : "s"} with stored
            figures for FY {data.financial_year}.
          </p>

          <Table
            title="Ratios"
            rows={data.ratios}
            format={() => pct}
            label={(k) => RATIO_LABELS[k] ?? k}
          />

          <Table
            title="Figures"
            rows={data.figures}
            format={formatFigure}
            label={figureLabel}
            meaning={data.figure_meaning}
          />

          <ul className="space-y-1">
            {data.notes.map((n) => (
              <li key={n} className="text-3xs text-ps-hint">{n}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
