"use client";

/**
 * Cash Flow Forecast — what a client's bank balance is expected to do.
 *
 * ⚠️ WHAT THIS REPLACED, because three things about it were wrong in kind
 * rather than in detail (3b-2):
 *
 *  · ITS ONLY INFLOW WAS `fee_invoices` — the PRACTICE'S OWN FEE NOTES to the
 *    client. So a client turning over crores was shown a forecast whose entire
 *    income was the fee they pay their accountant. Their own receivables did
 *    not appear at all.
 *  · ITS OPENING BALANCE WAS TYPED. Every closing figure is carried forward
 *    from it, so the whole projection hung off a keystroke — on a client whose
 *    bank ledger the product holds.
 *  · Its only outflow was loan EMIs. No supplier payables.
 *
 * It computed all of it in the browser off four PostgREST reads. The rule is
 * `apps/api/domain/cash_flow/forecast.py` now and this screen decides nothing:
 * it renders the months, the two overdue totals, the documents with no due
 * date, and — on every answer — the legs that are deliberately not priced.
 */

import { useState } from "react";
import Link from "next/link";
import { ArrowLeft, TrendingDown, Loader2 } from "lucide-react";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { useClientPicker } from "@/lib/workspace/useClientPicker";
import { objectWithLists } from "@/lib/api/shape";
import { formatWhole } from "@/lib/money/format";
import { Callout, StatutoryNotes } from "@/components/ui/callout";
import { api } from "@/lib/api";

// ─── The served shape ─────────────────────────────────────────────────────────

interface ForecastMonth {
  period: string;
  label: string;
  opening_paise: number;
  inflows_paise: number;
  outflows_paise: number;
  closing_paise: number;
  by_kind: Record<string, number>;
  is_shortfall: boolean;
}

interface UndatedFlow {
  amount_paise: number;
  kind: string;
  reference: string;
}

interface Forecast {
  as_at: string;
  opening_paise: number;
  months: ForecastMonth[];
  first_shortfall: string | null;
  overdue_in_paise: number;
  overdue_out_paise: number;
  undated: UndatedFlow[];
  unpriced: { leg: string; why: string }[];
  gaps: string[];
}

const KIND_LABELS: Record<string, string> = {
  receivable: "Receivables",
  payable: "Payables",
  loan_emi: "Loan EMI",
};

/** ₹ from integer paise, grouped the Indian way. One formatter, shared. */
function rs(paise: number): string {
  return `${paise < 0 ? "-" : ""}₹${formatWhole(Math.abs(paise))}`;
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function CashFlowForecastPage() {
  const { clients, clientId, setClientId } = useClientPicker();
  const [months, setMonths] = useState("6");
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [asked, setAsked] = useState(false);

  async function handleGenerate() {
    if (!clientId) {
      setError("Choose a client first.");
      return;
    }
    setLoading(true);
    setError(null);
    setForecast(null);
    setAsked(true);
    try {
      const json = await api.cashFlowForecast(clientId, Number(months));
      if (!json.success) throw new Error(json.error ?? "Could not build the forecast");
      // `objectWithLists`, not a cast: a 200 with an unusable payload otherwise
      // leaves loading false, error null and state set — and the next `.map`
      // throws on a heading that has already rendered.
      const shaped = objectWithLists<Forecast>(json.data, "months", "undated", "unpriced", "gaps");
      if (!shaped) throw new Error("The forecast came back in a shape this screen cannot read.");
      setForecast(shaped);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not build the forecast");
    } finally {
      setLoading(false);
    }
  }

  const maxFlow = forecast && forecast.months.length
    ? Math.max(
        ...forecast.months.flatMap((m) => [m.inflows_paise, m.outflows_paise]),
        1,
      )
    : 1;

  return (
    <div className="p-6 max-w-ps-data mx-auto space-y-5">
      <div className="flex items-center gap-3">
        <Link href="/reports" className="text-ps-hint hover:text-ps-label">
          <ArrowLeft size={16} />
        </Link>
        <div>
          <h1 className="text-xl font-semibold text-ps-ink">Cash Flow Forecast</h1>
          <p className="text-sm text-ps-hint mt-0.5">
            Expected receipts and payments, from the client&rsquo;s own open documents
          </p>
        </div>
      </div>

      <div className="bg-white rounded-xl border border-ps-border p-5 flex flex-wrap items-end gap-4">
        <div className="flex-1 min-w-[200px]">
          <label className="block text-xs font-medium text-ps-label mb-1">Client *</label>
          <ClientLookup clients={clients} value={clientId} onChange={setClientId} />
        </div>
        <div>
          <label className="block text-xs font-medium text-ps-label mb-1">Months</label>
          <select
            value={months}
            onChange={(e) => setMonths(e.target.value)}
            className="px-3 py-2 text-sm bg-white border border-ps-border-strong rounded-md text-ps-ink focus:outline-none focus:ring-2 focus:ring-brand"
          >
            {["3", "6", "12"].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </div>
        <button
          onClick={handleGenerate}
          disabled={loading || !clientId}
          className="px-4 py-2 text-sm font-medium bg-brand text-white rounded-md hover:bg-brand-dark disabled:opacity-50 inline-flex items-center gap-2"
        >
          {loading && <Loader2 size={14} className="animate-spin" />}
          {loading ? "Building…" : "Build forecast"}
        </button>
        <p className="w-full text-3xs text-ps-hint">
          The opening balance is read from the client&rsquo;s own bank and cash ledgers.
          It is not typed.
        </p>
      </div>

      {error && <Callout tone="problem">{error}</Callout>}

      {/* The four states are exhaustive. A 200 with nothing in it used to leave
          a heading over an empty page. */}
      {!loading && !error && !asked && (
        <div className="bg-white rounded-xl border border-ps-border p-10 text-center">
          <p className="text-sm text-ps-hint">Choose a client and build the forecast.</p>
        </div>
      )}

      {forecast && (
        <>
          {forecast.first_shortfall && (
            <Callout tone="problem">
              <span className="inline-flex items-center gap-2">
                <TrendingDown size={14} />
                Cash runs negative in{" "}
                {forecast.months.find((m) => m.period === forecast.first_shortfall)?.label
                  ?? forecast.first_shortfall}.
              </span>
            </Callout>
          )}

          <div className="bg-white rounded-xl border border-ps-border overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-ps-hint border-b border-ps-border">
                  <th className="px-5 py-3 text-left font-medium">Month</th>
                  <th className="px-3 py-3 text-right font-medium">Opening</th>
                  <th className="px-3 py-3 text-right font-medium">In</th>
                  <th className="px-3 py-3 text-right font-medium">Out</th>
                  <th className="px-3 py-3 text-right font-medium">Closing</th>
                  <th className="px-5 py-3 text-left font-medium w-40">Flow</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ps-border">
                {forecast.months.map((m) => (
                  <tr key={m.period} className={m.is_shortfall ? "bg-state-problem-surface" : ""}>
                    <td className="px-5 py-3 text-ps-ink">{m.label}</td>
                    <td className="px-3 py-3 text-right tabular-nums text-ps-label">{rs(m.opening_paise)}</td>
                    <td className="px-3 py-3 text-right tabular-nums text-state-ready">{rs(m.inflows_paise)}</td>
                    <td className="px-3 py-3 text-right tabular-nums text-state-problem">{rs(m.outflows_paise)}</td>
                    <td className={`px-3 py-3 text-right tabular-nums font-semibold ${m.is_shortfall ? "text-state-problem" : "text-ps-ink"}`}>
                      {rs(m.closing_paise)}
                    </td>
                    <td className="px-5 py-3">
                      <div className="flex flex-col gap-0.5">
                        <div className="h-1.5 bg-state-ready rounded-full"
                             style={{ width: `${Math.round((m.inflows_paise / maxFlow) * 100)}%` }} />
                        <div className="h-1.5 bg-state-problem rounded-full"
                             style={{ width: `${Math.round((m.outflows_paise / maxFlow) * 100)}%` }} />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {(forecast.overdue_in_paise > 0 || forecast.overdue_out_paise > 0) && (
            <div className="bg-white rounded-xl border border-ps-border p-5">
              <h2 className="text-sm font-semibold text-ps-ink mb-1">Already overdue</h2>
              <p className="text-xs text-ps-hint mb-3">
                Not in any month above. A document that fell due in the past is not
                money arriving next month, and putting it in the first month would
                make the forecast optimistic exactly where it is being relied on.
              </p>
              <div className="flex gap-8 text-sm">
                <div>
                  <p className="text-xs text-ps-hint">Owed to the client</p>
                  <p className="font-semibold tabular-nums text-state-ready">{rs(forecast.overdue_in_paise)}</p>
                </div>
                <div>
                  <p className="text-xs text-ps-hint">Owed by the client</p>
                  <p className="font-semibold tabular-nums text-state-problem">{rs(forecast.overdue_out_paise)}</p>
                </div>
              </div>
            </div>
          )}

          {forecast.undated.length > 0 && (
            <div className="bg-white rounded-xl border border-ps-border p-5">
              <h2 className="text-sm font-semibold text-ps-ink mb-1">No due date recorded</h2>
              <p className="text-xs text-ps-hint mb-3">
                Outstanding, and in no month above — a forecast is read as a claim
                about WHEN, and nothing here records when these fall due.
              </p>
              <ul className="space-y-1 text-sm">
                {forecast.undated.map((u, i) => (
                  <li key={`${u.reference}-${i}`} className="flex justify-between gap-4">
                    <span className="text-ps-label">
                      {KIND_LABELS[u.kind] ?? u.kind} · {u.reference}
                    </span>
                    <span className="tabular-nums text-ps-ink">{rs(u.amount_paise)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* `StatutoryNotes`, not a fifth amber div. The split is the one this
              codebase already makes: a GAP is actionable (no bank ledger in the
              chart; an EMI whose date nobody recorded) and a CAVEAT is read
              once (the statutory and payroll legs are not priced, and why).
              The tones are the component's, not this screen's. */}
          <StatutoryNotes
            title="What these figures do not include"
            gaps={forecast.gaps}
            caveats={forecast.unpriced.map((u) => u.why)}
            bulleted
          />
        </>
      )}
    </div>
  );
}
