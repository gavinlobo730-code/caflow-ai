"use client";

import { useCallback, useEffect, useState } from "react";
import { IndianRupee, RefreshCw, TrendingDown, Clock } from "lucide-react";
import { api } from "@/lib/api";
import type {
  ProfitabilityPayload,
  RealizationPayload,
  ConcentrationPayload,
} from "@/lib/api";
import { objectWithLists } from "@/lib/api/shape";
import { formatPaise } from "@/lib/services/formatting";
import { cn } from "@/lib/utils";

/**
 * Which clients make the practice money — Phase 3a-2.
 *
 * ⚠️ WHAT THIS IS. `GET /api/analytics/profitability` and
 * `/revenue-vs-effort` have existed, in integer paise, assignment-scoped and
 * tested, with **zero screen callers**. The plan's own finding: "you already
 * own more analysis than the product shows." This screen adds no engine and
 * computes nothing — every figure below is served.
 *
 * WHY `/practice` AND NOT `/health`. The hub's `insights` tile points at
 * `/health`, whose panel is headed "Client health monitor" — how the CLIENT is
 * doing. Revenue less cost per client is how the PRACTICE is doing, which is
 * what `/practice/revenue`, `/practice/billing`, `/practice/collections` and
 * `/practice/ar` are. It sits beside them. Repointing the tile needs a real
 * Insights page that holds health, risk AND profitability together, which is
 * 3a-1 and a separate decision.
 *
 * NOT `PartnerGuard`, although `/practice/revenue` is. The endpoints narrow
 * their per-client rows — and, on profitability, their TOTALS — to the
 * caller's assigned book, deliberately and with a test pinning both
 * directions. A screen that refuses everyone but a Partner would make that
 * narrowing dead code and would hide a Manager's own book from them. The
 * server decides; this asks.
 *
 * TWO QUESTIONS, NOT ONE, and they are kept apart on purpose. Profit is
 * revenue less what the time cost. REALIZATION is revenue against what the
 * time was WORTH at the recorded rate — so an engagement can be profitable and
 * still be recovering 60 paise in the rupee, which is the one a practice acts
 * on when it re-prices.
 */

const PERIODS: { id: string; label: string }[] = [
  { id: "month", label: "This month" },
  { id: "quarter", label: "This quarter" },
  { id: "week", label: "This week" },
];

function Figure({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="bg-white rounded-xl border border-ps-border p-4">
      <p className="text-3xs text-ps-hint uppercase tracking-wide">{label}</p>
      <p className="text-xl font-semibold text-ps-ink mt-1 tabular-nums">{value}</p>
      {hint && <p className="text-3xs text-ps-hint mt-0.5">{hint}</p>}
    </div>
  );
}

export default function ProfitabilityPage() {
  const [period, setPeriod] = useState("month");
  const [profit, setProfit] = useState<ProfitabilityPayload | null>(null);
  const [realization, setRealization] = useState<RealizationPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  /** Which of the two reads came back unusable. NOT the same as `error`: one
   *  can fail while the other answers, and the screen still has something
   *  worth showing — see the exhaustive branches below. */
  const [unread, setUnread] = useState<string[]>([]);
  /** NOT in `unread`: concentration is an addition to this screen rather than
   *  one of the two answers it exists for, so a refusal here hides a panel and
   *  must not make the page say it could not load profitability. */
  const [concentration, setConcentration] = useState<ConcentrationPayload | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setUnread([]);
    try {
      // Two requests rather than one, because they are two endpoints; both are
      // firm-level aggregates whose answer is a row per client, not per
      // document, so neither is proportional to the ledger.
      const [p, r, c] = await Promise.all([
        api.analytics.profitability(period),
        api.analytics.revenueVsEffort(period),
        // 3c-3. A third bounded read for the question the list below cannot
        // answer: if the largest client leaves, what happens. Its own request
        // rather than a field on the first, because it is its own endpoint —
        // and it fails independently, so a refusal here leaves the two answers
        // above intact.
        api.analytics.concentration(period),
      ]);
      const prof = p?.success
        ? objectWithLists<ProfitabilityPayload>(p.data, "by_client")
        : null;
      const real = r?.success
        ? objectWithLists<RealizationPayload>(r.data, "by_client")
        : null;
      setProfit(prof);
      setRealization(real);
      setConcentration(c?.success
        ? objectWithLists<ConcentrationPayload>(c.data, "shares", "not_measured")
        : null);
      // ⚠️ `objectWithLists` ANSWERING NULL IS THE HELPER WORKING, NOT AN
      // ABSENCE TO IGNORE. A 200 whose payload is not an object leaves
      // `loading` false, `error` null and the state null all at once, and the
      // first draft of this screen had no branch for that — so it rendered the
      // heading over nothing, which is exactly what `ModuleWorklist`'s own
      // first smoke shot caught and what its docstring warns about. The
      // branches below are exhaustive and this list is what lets the refusal
      // name which half is missing.
      setUnread([
        ...(prof ? [] : ["profitability"]),
        ...(real ? [] : ["realization"]),
      ]);
      if (!prof && !real) {
        setError(p?.error || r?.error || "Could not load profitability.");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load profitability.");
    } finally {
      setLoading(false);
    }
  }, [period]);

  useEffect(() => {
    load();
  }, [load]);

  const m = profit?.firm_metrics;
  const clients = profit?.by_client ?? [];
  // `realization_rate` is keyed on the client, so the two tables join without
  // a second request. A client the realization read does not carry simply has
  // no rate — it is not zero, and a dash says so.
  const rateFor = new Map(
    (realization?.by_client ?? []).map((c) => [c.client_id, c]),
  );

  return (
    <div className="p-6 max-w-ps-data space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-ps-ink">Profitability</h1>
          <p className="text-xs text-ps-hint mt-1">
            Revenue less what the time cost, per client · {profit?.period ?? realization?.period ?? "—"}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <select
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            className="text-xs border border-ps-border rounded-lg px-2.5 py-1.5 bg-white text-ps-body outline-none focus:border-brand"
          >
            {PERIODS.map((p) => (
              <option key={p.id} value={p.id}>{p.label}</option>
            ))}
          </select>
          <button
            onClick={load}
            aria-label="Refresh"
            className="p-1.5 rounded-lg border border-ps-border text-ps-hint hover:text-brand hover:bg-ps-bg transition-colors"
          >
            <RefreshCw size={13} />
          </button>
        </div>
      </div>

      {loading && <p className="text-xs text-ps-hint">Loading…</p>}

      {!loading && error && (
        <div className="bg-white rounded-xl border border-ps-border p-6">
          <p className="text-xs text-ps-label leading-relaxed">{error}</p>
        </div>
      )}

      {!loading && !error && !m && (
        <div className="bg-white rounded-xl border border-ps-border p-6">
          <p className="text-xs text-ps-label leading-relaxed">
            The profitability figures could not be read for this period. The
            realization read {realization ? "answered" : "did not answer"}{" "}
            either. Nothing here is wrong — there is simply no answer to show,
            and a blank page would not have said so.
          </p>
        </div>
      )}

      {!loading && !error && m && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Figure label="Revenue" value={formatPaise(m.total_revenue_paise)} />
          <Figure label="Cost of delivery" value={formatPaise(m.total_cost_paise)}
                  hint="time recorded, at its rate" />
          <Figure label="Profit" value={formatPaise(m.profit_paise)}
                  hint={`${m.profit_margin_pct}% margin`} />
          <Figure
            label="Realization"
            value={realization?.overall_realization_rate
              ? `${realization.overall_realization_rate.toFixed(2)}×`
              : "—"}
            hint={realization
              ? `${formatPaise(realization.avg_revenue_per_hour_paise)} / hour`
              : "not recorded"}
          />
        </div>
      )}

      {!loading && !error && m && unread.length > 0 && (
        <p className="text-3xs text-ps-hint">
          {unread.join(" and ")} could not be read for this period, so the
          figures below are short of {unread.length === 1 ? "that one" : "those"}.
        </p>
      )}

      {/* 3c-3 — the question the table below cannot answer: if the largest
          client leaves, what happens. A book where one client is 40% of fees
          is a different business from one where the largest is 6%, and the two
          look identical on a list sorted by revenue.

          The ICAI fee-dependence threat is NAMED and no threshold is drawn —
          icai.org is refused at this environment's proxy, and a percentage
          written from memory on an independence question would hand a firm a
          clean bill of health nobody issued. Served, not decided here. */}
      {!loading && !error && concentration && concentration.clients_billed > 0 && (
        <div className="bg-white rounded-xl border border-ps-border p-5 space-y-4">
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <h2 className="text-sm font-semibold text-ps-ink">Fee concentration</h2>
              <p className="text-xs text-ps-label mt-0.5">
                Across {concentration.clients_billed}{" "}
                {concentration.clients_billed === 1 ? "client" : "clients"} billed
                {concentration.median_revenue_paise != null && (
                  <> · the middle one billed {formatPaise(concentration.median_revenue_paise)}</>
                )}
              </p>
            </div>
            <div className="flex gap-5 shrink-0 text-right">
              {([
                ["Largest", concentration.largest_share_bps],
                ["Top 3", concentration.top_3_share_bps],
                ["Top 5", concentration.top_5_share_bps],
              ] as const).map(([label, bps]) => (
                <div key={label}>
                  <p className="text-3xs text-ps-hint uppercase tracking-wide">{label}</p>
                  <p className="text-lg font-semibold text-ps-ink tabular-nums">
                    {(bps / 100).toFixed(1)}%
                  </p>
                </div>
              ))}
            </div>
          </div>

          {/* One stacked bar: the shape of the dependence in one glance, which
              a sorted table cannot show. Clients past the fifth are one band,
              because naming thirty of them is the list that already exists. */}
          <div className="flex h-3 rounded-full overflow-hidden bg-ps-muted">
            {concentration.shares.slice(0, 5).map((sh, i) => (
              <div
                key={sh.client_id}
                className={[
                  "bg-brand-dark", "bg-brand", "bg-ps-hint", "bg-ps-border", "bg-ps-muted",
                ][i]}
                style={{ width: `${sh.share_bps / 100}%` }}
                title={`${sh.client_name} — ${(sh.share_bps / 100).toFixed(1)}% · ${formatPaise(sh.revenue_paise)}`}
              />
            ))}
          </div>

          <ol className="space-y-1">
            {concentration.shares.slice(0, 5).map((sh) => (
              <li key={sh.client_id} className="flex items-baseline justify-between gap-3 text-xs">
                <span className="text-ps-body truncate">
                  <span className="text-ps-hint tabular-nums mr-1.5">{sh.rank}.</span>
                  {sh.client_name}
                </span>
                <span className="shrink-0 tabular-nums text-ps-label">
                  {(sh.share_bps / 100).toFixed(1)}% · {formatPaise(sh.revenue_paise)}
                  {sh.margin_bps != null && (
                    <span className="text-ps-hint"> · {(sh.margin_bps / 100).toFixed(0)}% margin</span>
                  )}
                </span>
              </li>
            ))}
          </ol>

          <p className="text-3xs text-ps-hint border-t border-ps-border pt-3 leading-relaxed">
            {concentration.icai_fee_dependence}
          </p>
          <ul className="space-y-1">
            {concentration.not_measured.map((sentence) => (
              <li key={sentence} className="text-3xs text-ps-hint flex gap-2">
                <span className="shrink-0">•</span>
                <span>{sentence}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {!loading && !error && m && clients.length === 0 && (
        <div className="bg-white rounded-xl border border-ps-border p-8 text-center space-y-2">
          <p className="text-sm font-semibold text-ps-ink">Nothing billed in this period</p>
          <p className="text-xs text-ps-hint max-w-md mx-auto">
            Profitability is measured on invoices issued or paid within the
            period, against the time recorded against them. Neither exists for{" "}
            {profit?.period ?? "this period"} yet.
          </p>
        </div>
      )}

      {!loading && !error && clients.length > 0 && (
        <div className="bg-white rounded-xl border border-ps-border overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-ps-border bg-ps-bg">
                  <th className="text-left font-semibold text-ps-label px-4 py-2.5">Client</th>
                  <th className="text-right font-semibold text-ps-label px-4 py-2.5">Revenue</th>
                  <th className="text-right font-semibold text-ps-label px-4 py-2.5">Cost</th>
                  <th className="text-right font-semibold text-ps-label px-4 py-2.5">Profit</th>
                  <th className="text-right font-semibold text-ps-label px-4 py-2.5">Margin</th>
                  <th className="text-right font-semibold text-ps-label px-4 py-2.5">Realization</th>
                </tr>
              </thead>
              <tbody>
                {clients.map((c) => {
                  const r = rateFor.get(c.client_id);
                  return (
                    <tr key={c.client_id} className="border-b border-ps-border last:border-0 hover:bg-ps-bg">
                      <td className="px-4 py-2.5 font-medium text-ps-ink">{c.client_name}</td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-ps-body">
                        {formatPaise(c.revenue_paise)}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-ps-body">
                        {formatPaise(c.cost_paise)}
                      </td>
                      {/* A LOSS is a `problem` and a profit is not a `ready` —
                          a profitable client is the ordinary case and painting
                          every row green spends the state vocabulary on
                          nothing. Only the direction that needs a decision is
                          coloured. */}
                      <td className={cn(
                        "px-4 py-2.5 text-right tabular-nums font-semibold",
                        c.profit_paise < 0 ? "text-state-problem" : "text-ps-ink",
                      )}>
                        {formatPaise(c.profit_paise)}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-ps-body">
                        {c.profit_margin_pct}%
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-ps-body">
                        {r?.realization_rate ? `${r.realization_rate.toFixed(2)}×` : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="px-4 py-2 border-t border-ps-border bg-ps-bg space-y-1">
            <p className="text-3xs text-ps-hint flex items-center gap-1.5">
              <IndianRupee size={10} className="shrink-0" />
              Cost is the time recorded against the client at its own hourly
              rate. A client with no time recorded shows its whole revenue as
              profit — that is an absence of data, not a margin.
            </p>
            <p className="text-3xs text-ps-hint flex items-center gap-1.5">
              <Clock size={10} className="shrink-0" />
              Realization is revenue against what that time was worth at the
              recorded rate. 1.00× recovers it exactly; below that the
              engagement is under-priced or over-served.
            </p>
            {clients.some((c) => c.profit_paise < 0) && (
              <p className="text-3xs text-state-problem flex items-center gap-1.5">
                <TrendingDown size={10} className="shrink-0" />
                {clients.filter((c) => c.profit_paise < 0).length} client
                {clients.filter((c) => c.profit_paise < 0).length === 1 ? "" : "s"} cost
                more to serve than they billed in this period.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
