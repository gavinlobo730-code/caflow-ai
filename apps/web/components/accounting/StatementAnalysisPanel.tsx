"use client";

import { useCallback, useEffect, useState } from "react";
import { Sparkles, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { objectWithLists } from "@/lib/api/shape";
import { formatPaise } from "@/lib/services/formatting";

/**
 * A short narrative over the year's P&L and Balance Sheet — Phase 3a-3.
 *
 * `GET /api/accounting/statement-analysis` has existed since the reporting
 * engine did — ratios computed from the SAME paise the statements above are
 * built from, narrated by Groq with a deterministic fallback when no key is
 * configured — and `lib/api` carried the method with NO screen caller. The
 * plan's own words: the best AI feature here was unreachable.
 *
 * ⚠️ THE RULE THIS SCREEN EXISTS UNDER, AND WHY IT IS SAFE TO RENDER.
 * "The LLM narrates figures the product computed. It never computes them."
 * `domain/financial_analysis_service.compute_ratios` aggregates the backend's
 * own totals and hands them to the model as text; the model writes prose. So
 * the RATIOS below are rendered from the payload's own numbers rather than
 * parsed out of the narrative — a figure a CA can check against the statement
 * beside it, and nothing on this panel is a number the model chose.
 *
 * `ai_generated` IS SHOWN, NOT HIDDEN. When Groq is unreachable the service
 * falls back to a deterministic sentence, which is a different kind of
 * statement and the reader is entitled to know which they are looking at. A
 * CA who catches the AI inventing a number stops trusting the software
 * entirely, and the only defence is being plain about what wrote what.
 *
 * NOT loaded on mount. It is an LLM round trip on a tab a CA opens to export
 * a spreadsheet, so it waits to be asked — and the button says what it will
 * do rather than appearing as a spinner nobody started.
 */
interface Analysis {
  narrative: string;
  ai_generated: boolean;
  ratios: {
    net_margin_pct: number;
    expense_ratio_pct: number;
    current_ratio: number;
    current_assets_paise: number;
    current_liabilities_paise: number;
  };
}

function Ratio({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <p className="text-3xs text-ps-hint uppercase tracking-wide">{label}</p>
      <p className="text-sm font-semibold text-ps-ink tabular-nums mt-0.5">{value}</p>
      {hint && <p className="text-3xs text-ps-hint">{hint}</p>}
    </div>
  );
}

export function StatementAnalysisPanel({
  clientId,
  financialYear,
  basis,
}: {
  clientId: string;
  financialYear: string;
  basis: "accrual" | "cash";
}) {
  const [data, setData] = useState<Analysis | null>(null);
  const [loading, setLoading] = useState(false);
  const [asked, setAsked] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A new year or a new basis describes different statements, so an answer
  // computed for the old pair would be a narrative about figures no longer on
  // the screen — worse than no narrative, because it reads as current.
  useEffect(() => {
    setData(null);
    setAsked(false);
    setError(null);
  }, [clientId, financialYear, basis]);

  const load = useCallback(async () => {
    setLoading(true);
    setAsked(true);
    setError(null);
    try {
      const res = await api.accounting.statementAnalysis({
        financial_year: financialYear,
        client_id: clientId,
        basis,
      }) as { success?: boolean; data?: unknown; error?: string };
      if (!res?.success) {
        setError(res?.error || "The analysis could not be produced.");
        return;
      }
      setData(objectWithLists<Analysis>(res.data));
    } catch (e) {
      setError(e instanceof Error ? e.message : "The analysis could not be produced.");
    } finally {
      setLoading(false);
    }
  }, [clientId, financialYear, basis]);

  const r = data?.ratios;

  return (
    <div className="bg-white rounded-xl border border-ps-border overflow-hidden">
      <div className="px-5 py-4 border-b border-ps-border flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-semibold text-ps-body">Statement analysis</p>
          <p className="text-3xs text-ps-hint mt-0.5">
            Liquidity and profitability over {financialYear}, from the same
            figures the statements above are built from. Advisory only — it is
            never filed anywhere.
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="shrink-0 flex items-center gap-1.5 text-xs px-3 py-1.5 border border-ps-border rounded-lg hover:bg-ps-bg text-ps-label disabled:opacity-50"
        >
          {loading ? <RefreshCw size={12} className="animate-spin" /> : <Sparkles size={12} />}
          {asked ? "Run again" : "Analyse"}
        </button>
      </div>

      <div className="px-5 py-4">
        {!asked && (
          <p className="text-3xs text-ps-hint">
            Not run yet. It reads this year&apos;s Profit &amp; Loss and Balance
            Sheet and the previous year&apos;s Profit &amp; Loss.
          </p>
        )}

        {asked && loading && <p className="text-3xs text-ps-hint">Reading the statements…</p>}

        {asked && !loading && error && (
          <p className="text-xs text-ps-label leading-relaxed">{error}</p>
        )}

        {/* The fourth state, and the one a heading over nothing comes from: a
            200 whose payload is not an object. `objectWithLists` answers null
            and this says so rather than rendering an empty card. */}
        {asked && !loading && !error && !data && (
          <p className="text-xs text-ps-label leading-relaxed">
            The analysis came back in a shape this screen could not read. The
            statements above are unaffected.
          </p>
        )}

        {asked && !loading && !error && data && (
          <div className="space-y-4">
            {r && (
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                <Ratio label="Net margin" value={`${r.net_margin_pct}%`} />
                <Ratio label="Expense ratio" value={`${r.expense_ratio_pct}%`} />
                <Ratio label="Current ratio" value={r.current_ratio.toFixed(2)}
                       hint={`${formatPaise(r.current_assets_paise)} / ${formatPaise(r.current_liabilities_paise)}`} />
                <Ratio label="Basis" value={basis === "cash" ? "Cash" : "Accrual"} />
              </div>
            )}
            <p className="text-xs text-ps-body leading-relaxed whitespace-pre-line">
              {data.narrative}
            </p>
            <p className="text-3xs text-ps-hint">
              {data.ai_generated
                ? "Written by a language model from the figures above — it narrates them and computes none of them. Read it against the statements before relying on it."
                : "Written from the figures above by a fixed rule, not by a language model. No AI key is configured, so the deterministic wording was used."}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
