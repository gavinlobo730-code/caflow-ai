"use client";

/**
 * AS 11 PERIOD-END REVALUATION — the action beside the report that reads it.
 *
 * AS 11 paragraph 11 retranslates a monetary item held in a foreign currency
 * at the CLOSING rate on each balance sheet date; paragraph 13 takes the
 * difference to the profit and loss account. The engine
 * (`domain/currency/fx_revaluation_service.py`) has done this correctly since
 * Multi-Currency Phase 4 and had no caller at all, so `fx_revaluations` was
 * never written and the Unrealized report above was a structural nil.
 *
 * THIS COMPONENT COMPUTES NOTHING. Every figure — the exposure, the target,
 * what has already been posted, the delta, and every refusal — comes from
 * `POST /api/fx-revaluation/preview`, which runs the same walk the posting
 * path posts from. The closing rate is the only thing typed here, because it
 * is the one fact no ledger holds.
 */
import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import { formatPaise } from "@/lib/services/formatting";
import { Callout, GapList } from "@/components/ui/callout";
import { objectWithLists } from "@/lib/api/shape";

interface PlanRow {
  currency: string;
  item_type: string;
  item_ref: string | null;
  foreign_outstanding: number;
  carrying_base_paise: number;
  closing_rate: string | null;
  target_paise: number | null;
  prior_paise: number | null;
  delta_paise: number | null;
  run_count: number;
  rate_gap: string | null;
}

interface Plan {
  active: boolean;
  refusal: string | null;
  period_end: string;
  reversal_date?: string;
  rows: PlanRow[];
  currencies: string[];
  rate_gaps: string[];
  would_post: number;
  period_problem?: string | null;
}

function delta(paise: number | null) {
  if (paise === null || paise === 0) return <span className="font-mono text-ps-hint">—</span>;
  const cls = paise > 0 ? "text-green-700" : "text-state-problem";
  return <span className={`font-mono ${cls}`}>{paise > 0 ? "+" : "−"}{formatPaise(Math.abs(paise))}</span>;
}

export default function FxRevaluationPanel({
  clientId,
  periodEnd,
  onPosted,
}: {
  clientId: string;
  periodEnd: string;
  onPosted: () => void;
}) {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [rates, setRates] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [posting, setPosting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [posted, setPosted] = useState<string | null>(null);

  const load = useCallback(async (withRates: Record<string, string>) => {
    if (!clientId || clientId === "_placeholder" || !periodEnd) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.accounting.fxRevaluation.preview(clientId, {
        period_end: periodEnd,
        closing_rates: withRates,
      }) as { success: boolean; data: Plan | null; error?: string | null };
      if (res && res.success && res.data) setPlan(objectWithLists<Plan>(res.data, "rows"));
      else { setPlan(null); setError(res?.error ?? null); }
    } catch {
      setPlan(null);
    } finally {
      setLoading(false);
    }
  }, [clientId, periodEnd]);

  // The first call deliberately sends NO rates: the answer is what tells the
  // CA which currencies need one.
  useEffect(() => { setRates({}); setPosted(null); load({}); }, [load]);

  if (!plan) {
    return loading ? <p className="text-xs text-ps-hint">Checking foreign exposure…</p> : null;
  }
  if (!plan.active) {
    return (
      <div className="bg-ps-bg border border-ps-border rounded-lg px-3 py-2 text-xs text-ps-label">
        {plan.refusal}
      </div>
    );
  }
  if (plan.rows.length === 0) {
    return (
      <div className="bg-ps-bg border border-ps-border rounded-lg px-3 py-2 text-xs text-ps-label">
        No open foreign monetary items at {plan.period_end}, so AS 11 has nothing to
        retranslate.
      </div>
    );
  }

  const missing = plan.rows.some((r) => r.rate_gap);
  const blocked = Boolean(plan.period_problem);

  const post = async () => {
    setPosting(true);
    setError(null);
    try {
      const res = await api.accounting.fxRevaluation.run(clientId, {
        period_end: plan.period_end,
        closing_rates: rates,
      }) as { success: boolean; data: { adjustments?: unknown[] } | null; error?: string | null };
      if (res && res.success) {
        const n = res.data?.adjustments?.length ?? 0;
        setPosted(`Posted ${n} revaluation ${n === 1 ? "entry" : "entries"}, each auto-reversed on ${plan.reversal_date}.`);
        await load(rates);
        onPosted();
      } else {
        setError(res?.error ?? "The revaluation was not posted.");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "The revaluation was not posted.");
    } finally {
      setPosting(false);
    }
  };

  return (
    <div className="bg-white rounded-xl border border-ps-muted p-3 space-y-3">
      <div>
        <p className="text-xs font-semibold text-ps-body">
          Revalue open foreign items at {plan.period_end}
        </p>
        <p className="text-2xs text-ps-hint mt-0.5">
          AS 11 retranslates a monetary item at the closing rate on the balance sheet
          date and takes the difference to the profit and loss account. The entry is
          posted at {plan.period_end} and auto-reversed on {plan.reversal_date}, so the
          documents keep their original booking rates.
        </p>
      </div>

      {plan.period_problem && (
        <div className="bg-state-attention-surface border border-state-attention-border rounded-lg px-3 py-2 text-xs text-amber-900">
          {plan.period_problem}
        </div>
      )}

      <div className="overflow-hidden rounded-lg border border-ps-muted">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-ps-muted text-ps-hint">
              <th className="px-3 py-2 text-left font-semibold">Currency</th>
              <th className="px-3 py-2 text-left font-semibold">Item</th>
              <th className="px-3 py-2 text-right font-semibold">Foreign open</th>
              <th className="px-3 py-2 text-right font-semibold">Carrying (₹)</th>
              <th className="px-3 py-2 text-right font-semibold">Closing rate</th>
              <th className="px-3 py-2 text-right font-semibold">Already posted</th>
              <th className="px-3 py-2 text-right font-semibold">This run</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-ps-bg">
            {plan.rows.map((r, i) => (
              <tr key={`${r.currency}-${r.item_type}-${r.item_ref ?? ""}-${i}`} className="hover:bg-ps-bg">
                <td className="px-3 py-2 font-mono text-ps-body">{r.currency}</td>
                <td className="px-3 py-2 text-ps-label capitalize">{r.item_type}</td>
                <td className="px-3 py-2 text-right font-mono text-ps-body">{r.foreign_outstanding}</td>
                <td className="px-3 py-2 text-right font-mono text-ps-body">{formatPaise(r.carrying_base_paise)}</td>
                <td className="px-3 py-2 text-right">
                  <input
                    id={`fx-rate-${r.currency}`}
                    inputMode="decimal"
                    className="w-24 border border-ps-border rounded px-2 py-1 text-right font-mono"
                    placeholder="0.0000"
                    value={rates[r.currency] ?? ""}
                    onChange={(e) => {
                      const next = { ...rates, [r.currency]: e.target.value };
                      setRates(next);
                    }}
                    onBlur={() => load(rates)}
                  />
                </td>
                <td className="px-3 py-2 text-right font-mono text-ps-label">
                  {r.prior_paise === null ? "—" : formatPaise(r.prior_paise)}
                </td>
                <td className="px-3 py-2 text-right">{delta(r.delta_paise)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <GapList gaps={plan.rate_gaps} tone="attention" />

      {error && <Callout tone="problem">{error}</Callout>}
      {posted && (
        <p className="text-xs text-green-800 bg-green-50 border border-green-200 rounded px-2 py-1">{posted}</p>
      )}

      <div className="flex items-center justify-between gap-3">
        <p className="text-2xs text-ps-hint">
          {/* Re-running is the CORRECTION path, not a duplicate: the engine posts
              only the delta needed to reach the new target. Saying so is what
              stops a CA from avoiding the button after a rate changes. */}
          Re-running after a rate is corrected posts only the difference, never a
          second entry.
        </p>
        <button
          type="button"
          onClick={post}
          disabled={posting || missing || blocked || plan.would_post === 0}
          className="px-3 py-1.5 rounded bg-brand-dark text-white text-xs font-medium disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {posting ? "Posting…" : plan.would_post === 0 ? "Nothing to post" : `Post ${plan.would_post} entr${plan.would_post === 1 ? "y" : "ies"}`}
        </button>
      </div>
    </div>
  );
}
