"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { IndianRupee, RefreshCw, TrendingDown, Clock } from "lucide-react";
import { api } from "@/lib/api";
import type {
  ProfitabilityPayload,
  ProfitabilityStatus,
  RealizationPayload,
  ConcentrationPayload,
} from "@/lib/api";
import { objectWithLists } from "@/lib/api/shape";
import { formatPaise } from "@/lib/services/formatting";
import { cn } from "@/lib/utils";
import { PageHeader } from "@/components/ui/page-header";
import { usePermissions } from "@/lib/auth/AuthContext";
import { CostRatesPanel } from "@/components/practice/CostRatesPanel";
import { formatHours } from "@/lib/data/analytics";
import { ANALYTICS_FY_COUNT, analyticsWindowChoices, analyticsWindowOf } from "@/lib/practice/analyticsWindow";
import { financialYearChoices } from "@/lib/dates/periods";
import { todayIstISO } from "@/lib/dates/format";

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
 * NOT `PartnerGuard`, although `/practice/revenue` is, and NOT open to every Manager either: it is under
 * `FeeAccessGate` (the layout of this folder), which asks `billing:read`, the permission the three revenue endpoints
 * ask beside `analytics:read`. A Partner has it; a Manager or Executive has it only when the Partner has granted it
 * on the Team screen, and then the endpoints narrow their per-client rows (and, on profitability, their TOTALS) to
 * the caller's assigned book, deliberately and with a test pinning both directions. A screen that refused everyone
 * but a Partner would make that narrowing dead code for a granted Manager; a screen open to every Manager would show
 * the practice's fee economics to people the permission table keeps them from. The server decides; this asks.
 *
 * TWO QUESTIONS, NOT ONE, and they are kept apart on purpose. Profit is
 * revenue less what the time cost. REALIZATION is revenue against what the
 * time was WORTH at the recorded rate — so an engagement can be profitable and
 * still be recovering 60 paise in the rupee, which is the one a practice acts
 * on when it re-prices.
 *
 * REALIZATION IS THE SAME RULE (POST-A-426): revenue against what the billable time is worth at the rate each entry was
 * recorded with. Where any billable hour has no rate the server answers `null` and this draws a dash with the hours
 * that have none, and the firm's tile reads `realization_rate` (it read a key the server never sent, so it was a dash
 * whatever the books held). A window is the week, month or quarter to date or one whole financial year (POST-A-427).
 *
 * AN UNKNOWN IS A DASH, NEVER A NUMBER (POST-B-321). Revenue is the fee before
 * GST on invoices that were issued; cost is each person's COST rate times the
 * hours they recorded. Where a client's cost cannot be known — a person with no
 * cost rate recorded some of its hours, or no time was recorded against it at
 * all — the server answers `null` for its profit and margin and this screen
 * draws a dash and says why, because revenue less nothing is not a profit. A
 * client with time and no invoice is listed with its loss. The Partner sets the
 * rates in the panel at the foot of the page; every figure here is served.
 */

/** What sits under the Cost tile: which cost it is. A `null` is a dash and says why. */
function costHint(m: ProfitabilityPayload["firm_metrics"]): string {
  if (m.total_cost_paise === null) {
    return m.unrated_minutes > 0 ? "no hours have a cost rate yet" : "no time recorded against clients";
  }
  return m.cost_is_complete
    ? "time recorded against clients, at each person's cost rate"
    : "only the hours that have a cost rate";
}

/** A figure the server could not give is a dash. Never a zero: nothing here is computed. */
const DASH = "—";
const paiseOrDash = (paise: number | null | undefined) =>
  paise === null || paise === undefined ? DASH : formatPaise(paise);

/** What a realization figure leaves out, in words: fees on work nobody timed, fees on an invoice that names no
 *  engagement, and billable time that names none. The server sends the amounts; this only words them. */
function leftOut(x: {
  revenue_without_time_paise?: number;
  revenue_without_engagement_paise?: number;
  minutes_without_engagement?: number;
}): string[] {
  const notes: string[] = [];
  if ((x.revenue_without_time_paise ?? 0) > 0) notes.push(`${formatPaise(x.revenue_without_time_paise ?? 0)} on work with no billable time is left out`);
  if ((x.revenue_without_engagement_paise ?? 0) > 0) notes.push(`${formatPaise(x.revenue_without_engagement_paise ?? 0)} invoiced to no engagement is left out`);
  if ((x.minutes_without_engagement ?? 0) > 0) notes.push(`${formatHours(x.minutes_without_engagement ?? 0)} billable on no engagement is left out`);
  return notes;
}

/** What a row with no margin says instead, in words a Partner acts on. */
const STATUS_NOTE: Partial<Record<ProfitabilityStatus, string>> = {
  not_billed: "Time recorded, nothing billed",
  no_time: "No time recorded",
  unpriced: "Hours with no cost rate",
};

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
  const { can } = usePermissions();
  // The Partner sets the rates; the server (`billing:write`) is what refuses anybody else, this is courtesy.
  const canEditRates = can("billing", "write");
  const [period, setPeriod] = useState("month");
  /** This week, month and quarter to date, and the running financial year and the two before it: derived from the clock. */
  const windowChoices = useMemo(
    // India's day, because the server decides which year is running by India's day: read off the browser's own zone the
    // picker offered a year that has not started (a 422 on all three reads) or missed the one that has, around 1 April.
    () => analyticsWindowChoices(financialYearChoices(ANALYTICS_FY_COUNT, new Date(`${todayIstISO()}T12:00:00`))),
    [],
  );
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

  /** Which request is the newest. A slow answer to an older one must not overwrite a newer one (the period changed, or a
   *  rate was saved while the first load was still out): the select and the figures would then disagree. */
  const requestId = useRef(0);
  const load = useCallback(async () => {
    const mine = ++requestId.current;
    setLoading(true);
    setError(null);
    setUnread([]);
    try {
      // Two requests rather than one, because they are two endpoints; both are
      // firm-level aggregates whose answer is a row per client, not per
      // document, so neither is proportional to the ledger.
      const [p, r, c] = await Promise.all([
        api.analytics.profitability(analyticsWindowOf(period)),
        api.analytics.revenueVsEffort(analyticsWindowOf(period)),
        // 3c-3. A third bounded read for the question the list below cannot
        // answer: if the largest client leaves, what happens. Its own request
        // rather than a field on the first, because it is its own endpoint —
        // and it fails independently, so a refusal here leaves the two answers
        // above intact.
        api.analytics.concentration(analyticsWindowOf(period)),
      ]);
      if (mine !== requestId.current) return;
      const prof = p?.success
        ? objectWithLists<ProfitabilityPayload>(p.data, "by_client", "cost_rates_missing", "not_measured")
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
      if (mine !== requestId.current) return;
      setError(e instanceof Error ? e.message : "Could not load profitability.");
    } finally {
      if (mine === requestId.current) setLoading(false);
    }
  }, [period]);

  useEffect(() => {
    load();
  }, [load]);

  // What the cost-rate panel calls after a save: the CURRENT load, not the one from the render in which Save was pressed.
  const loadRef = useRef(load);
  useEffect(() => { loadRef.current = load; }, [load]);
  const reload = useCallback(() => { void loadRef.current(); }, []);

  const m = profit?.firm_metrics;
  const clients = profit?.by_client ?? [];
  const missingRates = profit?.cost_rates_missing ?? [];
  const notMeasured = profit?.not_measured ?? [];
  // `realization_rate` is keyed on the client, so the two tables join without
  // a second request. A client the realization read does not carry simply has
  // no rate — it is not zero, and a dash says so.
  const rateFor = new Map(
    (realization?.by_client ?? []).map((c) => [c.client_id, c]),
  );

  return (
    <div className="p-6 max-w-ps-data space-y-5">
      <PageHeader
        title="Profitability"
        subtitle={<>Revenue less what the time cost, per client · {(!loading && !error ? (profit?.period ?? realization?.period) : null) ?? "—"}</>}
        actions={
          <div className="flex items-center gap-2 shrink-0">
            <select
              aria-label="Period"
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              className="text-xs border border-ps-border rounded-lg px-2.5 py-1.5 bg-white text-ps-body outline-none focus:border-brand"
            >
              {windowChoices.map((p) => (
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
        }
      />

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
          <Figure label="Cost of delivery" value={paiseOrDash(m.total_cost_paise)} hint={costHint(m)} />
          <Figure label="Profit" value={paiseOrDash(m.profit_paise)}
                  hint={m.profit_paise === null
                    ? (m.clients_without_cost === 1
                      ? "1 client has no cost yet"
                      : `${m.clients_without_cost} clients have no cost yet`)
                    : m.profit_margin_pct === null ? "no revenue" : `${m.profit_margin_pct}% margin`} />
          <Figure
            label="Realization"
            value={realization?.realization_rate != null
              ? `${realization.realization_rate.toFixed(2)}×`
              : DASH}
            hint={realization
              ? [
                realization.unpriced_minutes > 0
                  ? `${formatHours(realization.unpriced_minutes)} of billable time has no billing rate`
                  : realization.total_billable_minutes > 0
                    ? (realization.billable_time_value_paise === 0
                      ? "billable time is recorded at ₹0 an hour"
                      : `${paiseOrDash(realization.avg_revenue_per_hour_paise)} / hour`)
                    : "no billable time recorded",
                ...leftOut(realization),
              ].join(" · ")
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

      {!loading && !error && m && !m.cost_is_complete && (
        <div className="bg-state-problem-surface border border-state-problem-border rounded-xl p-4 space-y-1.5">
          <p className="text-xs font-semibold text-state-problem">The profit is not shown, because some of the cost is not known.</p>
          {missingRates.length > 0 && (
            <p className="text-xs text-ps-body leading-relaxed">
              {formatHours(m.unrated_minutes)} recorded by{" "}
              {missingRates.slice(0, 3).map((c) => (missingRates.length === 1 ? c.user_name : `${c.user_name} (${formatHours(c.minutes)})`)).join(", ")}
              {missingRates.length > 3 ? ` and ${missingRates.length - 3} more` : ""}{" "}
              has no cost rate, so it is in no client&apos;s cost.{canEditRates ? " Set the rates at the foot of this page." : " A Partner sets the rates."}
            </p>
          )}
          {clients.some((c) => c.status === "no_time") && (
            <p className="text-xs text-ps-body leading-relaxed">
              {clients.filter((c) => c.status === "no_time").length} billed{" "}
              {clients.filter((c) => c.status === "no_time").length === 1 ? "client has" : "clients have"} no time
              recorded against {clients.filter((c) => c.status === "no_time").length === 1 ? "it" : "them"}, so what they cost to serve is not known.
            </p>
          )}
          {m.clients_with_cost > 0 && (
            <p className="text-xs text-ps-body leading-relaxed">
              On the {m.clients_with_cost} {m.clients_with_cost === 1 ? "client" : "clients"} whose cost is known, the profit is{" "}
              <span className="tabular-nums font-medium">{formatPaise(m.profit_on_known_paise)}</span>.
            </p>
          )}
        </div>
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
          <p className="text-sm font-semibold text-ps-ink">
            {(m?.minutes_without_client ?? 0) > 0
              ? "Nothing billed and no time recorded against a client in this period"
              : "Nothing billed and no time recorded in this period"}
          </p>
          <p className="text-xs text-ps-hint max-w-md mx-auto">
            Profitability is measured on invoices that are issued, by the
            invoice&apos;s own date (a draft or a cancelled invoice does not
            count), against the time recorded against each client. Neither
            exists for {profit?.period ?? "this period"} yet.
            {(m?.minutes_without_client ?? 0) > 0 && (
              <> {formatHours(m?.minutes_without_client ?? 0)} recorded against no client is in no client&apos;s cost.</>
            )}
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
                      <td className="px-4 py-2.5 font-medium text-ps-ink">
                        {c.client_name}
                        {STATUS_NOTE[c.status] && (
                          <span className="block text-3xs font-normal text-ps-hint">{STATUS_NOTE[c.status]}</span>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-ps-body">
                        {formatPaise(c.revenue_paise)}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-ps-body">
                        {paiseOrDash(c.cost_paise)}
                        {c.unrated_minutes > 0 && (
                          <span className="block text-3xs text-ps-hint">
                            and {formatHours(c.unrated_minutes)} with no cost rate
                          </span>
                        )}
                      </td>
                      {/* A LOSS is a `problem` and a profit is not a `ready` —
                          a profitable client is the ordinary case and painting
                          every row green spends the state vocabulary on
                          nothing. Only the direction that needs a decision is
                          coloured. */}
                      <td className={cn(
                        "px-4 py-2.5 text-right tabular-nums font-semibold",
                        c.profit_paise !== null && c.profit_paise < 0 ? "text-state-problem" : "text-ps-ink",
                      )}>
                        {paiseOrDash(c.profit_paise)}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-ps-body">
                        {c.profit_margin_pct === null ? DASH : `${c.profit_margin_pct}%`}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums text-ps-body">
                        {r?.realization_rate != null ? `${r.realization_rate.toFixed(2)}×` : DASH}
                        {r && [
                          ...(r.unpriced_minutes > 0 ? [`${formatHours(r.unpriced_minutes)} with no billing rate`] : []),
                          ...leftOut(r),
                        ].map((note) => (
                          <span key={note} className="block text-3xs text-ps-hint">{note}</span>
                        ))}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="px-4 py-2 border-t border-ps-border bg-ps-bg space-y-1">
            {notMeasured.map((sentence) => (
              <p key={sentence} className="text-3xs text-ps-hint flex items-start gap-1.5">
                <IndianRupee size={10} className="shrink-0 mt-0.5" />
                {sentence}
              </p>
            ))}
            {(realization?.not_measured ?? []).map((sentence) => (
              <p key={sentence} className="text-3xs text-ps-hint flex items-start gap-1.5">
                <Clock size={10} className="shrink-0 mt-0.5" />
                {sentence}
              </p>
            ))}
            {clients.some((c) => c.profit_paise !== null && c.profit_paise < 0) && (
              <p className="text-3xs text-state-problem flex items-center gap-1.5">
                <TrendingDown size={10} className="shrink-0" />
                {clients.filter((c) => c.profit_paise !== null && c.profit_paise < 0).length} client
                {clients.filter((c) => c.profit_paise !== null && c.profit_paise < 0).length === 1 ? "" : "s"} cost
                more to serve than they billed in this period.
              </p>
            )}
            {m && (m.minutes_without_client ?? 0) > 0 && (
              <p className="text-3xs text-ps-hint flex items-center gap-1.5">
                <Clock size={10} className="shrink-0" />
                {formatHours(m.minutes_without_client ?? 0)} recorded against no client {m.minutes_without_client === 1 ? "is" : "are"} in no
                client&apos;s cost.
              </p>
            )}
          </div>
        </div>
      )}

      {/* Only for somebody who may SET a rate (billing:write): the server's list asks the same, because a rate is derived from a
          person's pay. Outside every `loading` branch, so a rate typed here is not lost when the figures above reload. */}
      {canEditRates && <CostRatesPanel onSaved={reload} />}
    </div>
  );
}
