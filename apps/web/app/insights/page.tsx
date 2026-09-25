"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { RefreshCw, ArrowRight, ShieldAlert, HeartPulse, ListChecks } from "lucide-react";
import { api } from "@/lib/api";
import type {
  ComplianceRiskPayload,
  RelationshipHealthPayload,
  RecommendationsPayload,
} from "@/lib/api";
import { objectWithLists } from "@/lib/api/shape";
import { formatPaise } from "@/lib/services/formatting";
import { cn } from "@/lib/utils";

/**
 * Insights — Phase 3a-5, and the destination D1's `insights` tile has been
 * pointing away from.
 *
 * ⚠️ WHAT THIS REPLACED. The hub tile is labelled "Insights", asks "Health,
 * risk and profitability", and its `firm_href` was `/health` — a client health
 * monitor, which is one of the three. Its own comment in
 * `domain/hub/tiles.py` said "Its own contents are Phase 3a." This is those
 * contents, and the tile points here now.
 *
 * NO ENGINE IS ADDED. `compliance-risk`, `relationship-health` and
 * `recommendations` are computed, tested and assignment-scoped, and all three
 * had ZERO screen callers — `lib/api` carried the methods and nothing pressed
 * them. Every figure below is served.
 *
 * ⚠️ AND THE ONE THING CHECKED BEFORE SURFACING ANY OF IT: CLAUDE.md records
 * that "the modules named intelligence and memory analyse TASKS, not money"
 * and that `cash_flow_risk_months` is literally the two months with the most
 * tasks. That warning is about `memory_repository`, not this service, and it
 * was checked rather than assumed. `risk_score` here is built from the
 * client's own compliance records — overdue count, due within seven days, any
 * history of filing late — and `outstanding_paise` is summed off invoices with
 * status Issued or Overdue. Real records and real money. A figure that looked
 * financial and was derived from task volume would not be rendered here
 * however well the endpoint worked.
 *
 * RECOMMENDATIONS COME FIRST because they are the only section that says what
 * to DO; the two score tables are the evidence under it.
 */

const PRIORITY_RANK: Record<string, number> = {
  critical: 0, high: 1, medium: 2, low: 3,
};

/** A ranked ladder, so the `sev` tokens rather than the three unranked states
 *  — the distinction `tailwind.config.ts` records at length. */
const PRIORITY_CHIP: Record<string, string> = {
  critical: "bg-sev-critical-surface text-sev-critical border-sev-critical-border",
  high: "bg-sev-high-surface text-sev-high border-sev-high-border",
  medium: "bg-sev-medium-surface text-sev-medium border-sev-medium-border",
  low: "bg-sev-low-surface text-sev-low border-sev-low-border",
};

const RISK_CHIP: Record<string, string> = {
  critical: "bg-sev-critical-surface text-sev-critical",
  high: "bg-sev-high-surface text-sev-high",
  medium: "bg-sev-medium-surface text-sev-medium",
  low: "bg-sev-low-surface text-sev-low",
};

const HEALTH_CHIP: Record<string, string> = {
  healthy: "bg-sev-ok-surface text-sev-ok",
  at_risk: "bg-sev-medium-surface text-sev-medium",
  critical: "bg-sev-critical-surface text-sev-critical",
};

function Section({
  icon: Icon, title, hint, children,
}: {
  icon: typeof ShieldAlert; title: string; hint: string; children: React.ReactNode;
}) {
  return (
    <div className="bg-white rounded-xl border border-ps-border overflow-hidden">
      <div className="px-5 py-4 border-b border-ps-border">
        <p className="text-xs font-semibold text-ps-body flex items-center gap-2">
          <Icon size={13} className="text-ps-hint shrink-0" />
          {title}
        </p>
        <p className="text-3xs text-ps-hint mt-0.5">{hint}</p>
      </div>
      {children}
    </div>
  );
}

export default function InsightsPage() {
  const [risk, setRisk] = useState<ComplianceRiskPayload | null>(null);
  const [health, setHealth] = useState<RelationshipHealthPayload | null>(null);
  const [recs, setRecs] = useState<RecommendationsPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [unread, setUnread] = useState<string[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setUnread([]);
    try {
      // Three firm-level aggregates, each answering a row per client rather
      // than per document, so none is proportional to the ledger.
      const [a, b, c] = await Promise.all([
        api.intelligence.recommendations(),
        api.intelligence.complianceRisk(),
        api.intelligence.relationshipHealth(),
      ]);
      const r = a?.success
        ? objectWithLists<RecommendationsPayload>(a.data, "recommendations") : null;
      const k = b?.success
        ? objectWithLists<ComplianceRiskPayload>(b.data, "clients") : null;
      const h = c?.success
        ? objectWithLists<RelationshipHealthPayload>(c.data, "clients") : null;
      setRecs(r); setRisk(k); setHealth(h);
      // Three reads, any of which can answer 200 with an unusable payload —
      // `loading` false, no error, state null. Naming which is missing is what
      // keeps a heading from sitting over nothing.
      setUnread([
        ...(r ? [] : ["recommendations"]),
        ...(k ? [] : ["compliance risk"]),
        ...(h ? [] : ["relationship health"]),
      ]);
    } catch {
      setRecs(null); setRisk(null); setHealth(null);
      setUnread(["recommendations", "compliance risk", "relationship health"]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const recRows = [...(recs?.recommendations ?? [])].sort(
    (x, y) => (PRIORITY_RANK[x.priority] ?? 9) - (PRIORITY_RANK[y.priority] ?? 9),
  );
  const riskRows = [...(risk?.clients ?? [])]
    .filter((c) => c.risk_score > 0)
    .sort((x, y) => y.risk_score - x.risk_score);
  const healthRows = [...(health?.clients ?? [])]
    .filter((c) => c.health_level !== "healthy")
    .sort((x, y) => x.health_score - y.health_score);

  return (
    <div className="p-6 max-w-ps-data mx-auto space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-ps-ink">Insights</h1>
          <p className="text-xs text-ps-hint mt-1">
            What needs attention across the clients you can see — computed from
            their own records, never estimated.
          </p>
        </div>
        <button
          onClick={load}
          aria-label="Refresh"
          className="shrink-0 p-1.5 rounded-lg border border-ps-border text-ps-hint hover:text-brand hover:bg-ps-bg transition-colors"
        >
          <RefreshCw size={13} />
        </button>
      </div>

      {loading && <p className="text-xs text-ps-hint">Loading…</p>}

      {!loading && unread.length === 3 && (
        <div className="bg-white rounded-xl border border-ps-border p-6">
          <p className="text-xs text-ps-label leading-relaxed">
            None of the three intelligence reads answered. Nothing here is
            wrong — there is simply no answer to show, and a blank page would
            not have said so.
          </p>
        </div>
      )}

      {!loading && unread.length > 0 && unread.length < 3 && (
        <p className="text-3xs text-ps-hint">
          {unread.join(" and ")} could not be read, so {unread.length === 1
            ? "that section is" : "those sections are"} missing below.
        </p>
      )}

      {!loading && recs && (
        <Section
          icon={ListChecks}
          title="What to do"
          hint="Proactive compliance, client and operational recommendations, worst first."
        >
          {recRows.length === 0 ? (
            <p className="px-5 py-8 text-center text-xs text-ps-hint">
              Nothing recommended right now.
            </p>
          ) : (
            <div className="divide-y divide-ps-border">
              {recRows.map((r, i) => (
                <div key={`${r.title}-${i}`} className="px-5 py-3 flex items-start gap-3">
                  <span className={cn(
                    "shrink-0 text-3xs font-semibold px-2 py-0.5 rounded-full border uppercase tracking-wide",
                    PRIORITY_CHIP[r.priority] ?? PRIORITY_CHIP.low,
                  )}>
                    {r.priority}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-medium text-ps-ink">{r.title}</p>
                    {r.detail && <p className="text-3xs text-ps-hint mt-0.5">{r.detail}</p>}
                    {r.action && <p className="text-3xs text-ps-label mt-0.5">{r.action}</p>}
                  </div>
                  {r.client_id && (
                    <Link
                      href={`/clients/${r.client_id}/overview`}
                      className="shrink-0 text-ps-hint hover:text-brand"
                      aria-label="Open the client"
                    >
                      <ArrowRight size={13} />
                    </Link>
                  )}
                </div>
              ))}
            </div>
          )}
        </Section>
      )}

      {!loading && risk && (
        <Section
          icon={ShieldAlert}
          title="Compliance risk"
          hint="Scored on each client's own records — what is overdue, what falls due inside seven days, and whether they have filed late before."
        >
          {riskRows.length === 0 ? (
            <p className="px-5 py-8 text-center text-xs text-ps-hint">
              No client is carrying compliance risk — nothing overdue, nothing
              due inside a week.
            </p>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-ps-border bg-ps-bg">
                  <th className="text-left font-semibold text-ps-label px-4 py-2.5">Client</th>
                  <th className="text-right font-semibold text-ps-label px-4 py-2.5">Overdue</th>
                  <th className="text-right font-semibold text-ps-label px-4 py-2.5">Due in 7 days</th>
                  <th className="text-right font-semibold text-ps-label px-4 py-2.5">Risk</th>
                </tr>
              </thead>
              <tbody>
                {riskRows.map((c) => (
                  <tr key={c.client_id} className="border-b border-ps-border last:border-0 hover:bg-ps-bg">
                    <td className="px-4 py-2.5">
                      <Link href={`/clients/${c.client_id}/compliance`} className="font-medium text-ps-ink hover:text-brand">
                        {c.client_name}
                      </Link>
                      {c.late_filing_history > 0 && (
                        <span className="ml-2 text-3xs text-ps-hint">
                          filed late {c.late_filing_history}×
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-ps-body">{c.overdue_count}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-ps-body">{c.due_soon_count}</td>
                    <td className="px-4 py-2.5 text-right">
                      <span className={cn(
                        "text-3xs font-semibold px-2 py-0.5 rounded-full",
                        RISK_CHIP[c.risk_level] ?? RISK_CHIP.low,
                      )}>
                        {c.risk_score}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Section>
      )}

      {!loading && health && (
        <Section
          icon={HeartPulse}
          title="Clients needing attention"
          hint="Open and overdue work against what they owe. Outstanding is real money — invoices issued or overdue — not a figure derived from task counts."
        >
          {healthRows.length === 0 ? (
            <p className="px-5 py-8 text-center text-xs text-ps-hint">
              Every client you can see is healthy on this measure.
            </p>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-ps-border bg-ps-bg">
                  <th className="text-left font-semibold text-ps-label px-4 py-2.5">Client</th>
                  <th className="text-right font-semibold text-ps-label px-4 py-2.5">Overdue tasks</th>
                  <th className="text-right font-semibold text-ps-label px-4 py-2.5">Overdue invoices</th>
                  <th className="text-right font-semibold text-ps-label px-4 py-2.5">Outstanding</th>
                  <th className="text-right font-semibold text-ps-label px-4 py-2.5">Health</th>
                </tr>
              </thead>
              <tbody>
                {healthRows.map((c) => (
                  <tr key={c.client_id} className="border-b border-ps-border last:border-0 hover:bg-ps-bg">
                    <td className="px-4 py-2.5">
                      <Link href={`/clients/${c.client_id}/overview`} className="font-medium text-ps-ink hover:text-brand">
                        {c.client_name}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-ps-body">{c.overdue_tasks}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-ps-body">{c.overdue_invoices}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-ps-body">
                      {formatPaise(c.outstanding_paise)}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <span className={cn(
                        "text-3xs font-semibold px-2 py-0.5 rounded-full",
                        HEALTH_CHIP[c.health_level] ?? HEALTH_CHIP.at_risk,
                      )}>
                        {c.health_score}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Section>
      )}

      {!loading && (
        <p className="text-3xs text-ps-hint">
          Profitability and realization are the third of this tile&apos;s three
          questions and live beside the rest of the practice&apos;s commercial
          position — <Link href="/practice/profitability" className="text-blue-600 hover:underline">Practice → Profitability</Link>.
        </p>
      )}
    </div>
  );
}
