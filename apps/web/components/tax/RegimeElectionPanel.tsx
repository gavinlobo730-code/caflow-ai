"use client";

/**
 * WHAT CHOOSING THE OLD REGIME ACTUALLY REQUIRES — §115BAC(6), Rule 21AGA.
 *
 * Since AY 2024-25 the §115BAC regime is the DEFAULT, and opting out is not
 * one rule with two variations. A client WITH income from business or
 * profession files FORM 10-IEA by the §139(1) due date and has, in effect,
 * one return journey for life: opting out and then going back closes the old
 * regime to them permanently. A client WITHOUT such income opts out in the
 * return itself, with no form and no lock-out.
 *
 * `domain/income_tax/regime_election.py` has held all of that since it was
 * written and had NO CALLER. Its own docstring says why that mattered: a
 * missed Form 10-IEA taxes a client on the new regime for a year they planned
 * around the old one and cannot be cured after the due date, and neither
 * failure is visible in the return — it computes cleanly either way.
 *
 * This panel computes NOTHING. The route, the form, the due date, whether the
 * option is still available and every sentence come from the server.
 */
import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";

interface Election {
  financial_year: string;
  regime: "old" | "new";
  route: "form_10iea" | "in_the_return";
  form_10iea_required: boolean;
  due_date: string | null;
  election_is_available: boolean;
  history_unknown: boolean;
  reasons: string[];
}

export default function RegimeElectionPanel({
  financialYear,
  wantsOldRegime,
  hasBusinessIncome,
  isAudit,
}: {
  financialYear: string;
  wantsOldRegime: boolean;
  hasBusinessIncome: boolean;
  isAudit?: boolean;
}) {
  const [data, setData] = useState<Election | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Prior-year elections are the CA's own knowledge — the product holds no
  // filing history. Empty means "not stated", which the server answers as
  // `history_unknown` rather than as "the option is available".
  const [prior, setPrior] = useState<string[]>([]);

  const load = useCallback(async () => {
    if (!financialYear) return;
    try {
      const res = await api.incomeTax.regimeElection({
        wants_old_regime: wantsOldRegime,
        has_business_income: hasBusinessIncome,
        financial_year: financialYear,
        is_audit: isAudit,
        prior,
      }) as { success: boolean; data: Election | null; error?: string | null };
      if (res && res.success && res.data) { setData(res.data); setError(null); }
      else { setData(null); setError(res?.error ?? null); }
    } catch {
      setData(null);
    }
  }, [financialYear, wantsOldRegime, hasBusinessIncome, isAudit, prior]);

  useEffect(() => { load(); }, [load]);

  if (error) {
    return <p className="text-2xs text-state-problem bg-state-problem-surface border border-state-problem-border rounded-lg p-2.5">{error}</p>;
  }
  if (!data) return null;

  const tone = !data.election_is_available
    ? "bg-state-problem-surface border-state-problem-border text-red-900"
    : data.history_unknown || data.form_10iea_required
      ? "bg-state-attention-surface border-state-attention-border text-amber-900"
      : "bg-ps-bg border-ps-border text-ps-label";

  return (
    <div className={`rounded-lg border p-2.5 space-y-1.5 ${tone}`}>
      <p className="text-2xs font-semibold">
        {data.form_10iea_required
          ? `Form 10-IEA is required${data.due_date ? `, on or before ${data.due_date}` : ""}`
          : data.route === "in_the_return"
            ? "The election is made in the return itself — no separate form"
            : "No election is needed for the new regime"}
      </p>
      {data.reasons.map((r, i) => (
        <p key={i} className="text-2xs leading-snug">{r}</p>
      ))}

      {/* §115BAC(6)(i)'s once-only withdrawal cannot be derived from anything
          this product holds, so it is ASKED. Leaving it unanswered is a real
          answer — the server says the history is unknown rather than assuming
          the option is still there, which is the direction that would tell a
          CA the old regime is open when the client spent it years ago. */}
      {data.route === "form_10iea" && (
        <div className="pt-1 space-y-1">
          <label className="text-3xs block opacity-80">
            Earlier years, if you know them — this decides whether the option is still available
          </label>
          <div className="flex flex-wrap gap-1.5">
            {["opted_out", "withdrew"].map((action) => (
              <button
                key={action}
                type="button"
                onClick={() => setPrior((p) =>
                  p.some((x) => x.endsWith(`:${action}`))
                    ? p.filter((x) => !x.endsWith(`:${action}`))
                    : [...p, `${previousFy(financialYear)}:${action}`])}
                className={`text-3xs px-2 py-0.5 rounded border ${
                  prior.some((x) => x.endsWith(`:${action}`))
                    ? "bg-brand-dark text-white border-brand-dark"
                    : "bg-white border-ps-border text-ps-label"}`}
              >
                {action === "opted_out" ? "Opted out before" : "Withdrew before"}
              </button>
            ))}
            {prior.length > 0 && (
              <button type="button" onClick={() => setPrior([])}
                className="text-3xs px-2 py-0.5 rounded border bg-white border-ps-border text-ps-hint">
                Clear
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/** The year before this one, in the same YYYY-YY shape. Presentation only —
 *  the server validates and canonicalises whatever is sent. */
function previousFy(fy: string): string {
  const start = Number(String(fy).slice(0, 4));
  if (!Number.isFinite(start)) return fy;
  return `${start - 1}-${String(start % 100).padStart(2, "0")}`;
}
