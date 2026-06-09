/**
 * Client Health Engine — Compliance Dimension Computation
 * Phase 1.0: compliance_score only.
 * Remaining dimensions (accounting, responsiveness, document, financial) are Phase 1.x.
 */
import { getSupabaseClient } from "@/lib/supabase/client";
import type { ComplianceEntry } from "@/lib/data/compliance";
import { getCurrentFinancialYear } from "@/lib/workspace/ClientNavContext";

export interface ComplianceScoreResult {
  overall_score: number;
  compliance_score: number;
  signals: Array<{ signal: string; weight: number; value: number; label: string }>;
  trend: "improving" | "stable" | "declining" | null;
  delta: number | null;
}

/**
 * Computes a 0–100 compliance score from compliance calendar entries.
 * All other dimension scores default to 50 (neutral) until Phase 1.x.
 *
 * Scoring algorithm:
 * - Base: 100
 * - Each overdue filing: -8 pts
 * - Each pending filing due ≤7 days: -4 pts
 * - Each pending filing due 8–30 days: -2 pts
 * - Filing rate ≥ 80%: +10 bonus
 * - Clamped to [0, 100]
 */
export function computeComplianceScore(
  entries: ComplianceEntry[],
  asOf: Date = new Date()
): ComplianceScoreResult {
  const today = asOf.toISOString().split("T")[0];

  const total = entries.length;
  const filed = entries.filter((e) => e.filing_status === "filed").length;
  const overdue = entries.filter(
    (e) => e.due_date < today && e.filing_status !== "filed"
  ).length;
  const dueIn7 = entries.filter((e) => {
    if (e.filing_status === "filed") return false;
    const diff = Math.ceil(
      (new Date(e.due_date).getTime() - asOf.getTime()) / 86400000
    );
    return diff >= 0 && diff <= 7;
  }).length;
  const dueIn30 = entries.filter((e) => {
    if (e.filing_status === "filed") return false;
    const diff = Math.ceil(
      (new Date(e.due_date).getTime() - asOf.getTime()) / 86400000
    );
    return diff > 7 && diff <= 30;
  }).length;

  const filingRate = total > 0 ? filed / total : 1;

  let score = 100;
  score -= Math.min(overdue * 8, 50);
  score -= Math.min(dueIn7 * 4, 20);
  score -= Math.min(dueIn30 * 2, 10);
  if (filingRate >= 0.8) score += 10;
  const compliance_score = Math.max(0, Math.min(100, Math.round(score)));

  // overall_score = compliance_score only (Phase 1.0)
  // other dimensions default to 50 (neutral) and are not factored in yet
  const overall_score = compliance_score;

  const signals = [
    {
      signal: "overdue_filings",
      weight: 0.5,
      value: overdue === 0 ? 100 : Math.max(0, 100 - overdue * 16),
      label: overdue === 0 ? "No overdue filings" : `${overdue} overdue filing${overdue > 1 ? "s" : ""}`,
    },
    {
      signal: "upcoming_7d",
      weight: 0.25,
      value: dueIn7 === 0 ? 100 : Math.max(0, 100 - dueIn7 * 25),
      label: dueIn7 === 0 ? "No urgent deadlines" : `${dueIn7} filing${dueIn7 > 1 ? "s" : ""} due in 7 days`,
    },
    {
      signal: "filing_rate",
      weight: 0.25,
      value: Math.round(filingRate * 100),
      label: `${Math.round(filingRate * 100)}% filing rate`,
    },
  ];

  return { overall_score, compliance_score, signals, trend: null, delta: null };
}

/**
 * Fetches the latest health score snapshot for a client.
 * Returns null if no snapshot exists.
 */
export async function getLatestHealthScore(
  clientId: string
): Promise<{ overall_score: number; compliance_score: number; snapshot_period: string } | null> {
  const supabase = getSupabaseClient();
  const { data } = await supabase
    .from("client_health_scores")
    .select("overall_score, compliance_score, snapshot_period")
    .eq("client_id", clientId)
    .order("computed_at", { ascending: false })
    .limit(1)
    .maybeSingle();
  return data ?? null;
}

/**
 * Computes and persists a health score snapshot for a client.
 * Called on Overview page load if no snapshot exists for current period.
 */
export async function snapshotHealthScore(
  clientId: string,
  firmId: string,
  entries: ComplianceEntry[]
): Promise<ComplianceScoreResult> {
  const supabase = getSupabaseClient();
  const now = new Date();
  const result = computeComplianceScore(entries, now);
  const financial_year = getCurrentFinancialYear();
  const snapshot_period = now.toISOString().slice(0, 7); // "YYYY-MM"

  // Fetch previous snapshot for trend computation
  const { data: prev } = await supabase
    .from("client_health_scores")
    .select("overall_score, snapshot_period")
    .eq("client_id", clientId)
    .order("computed_at", { ascending: false })
    .limit(1)
    .maybeSingle();

  const delta = prev ? result.overall_score - prev.overall_score : null;
  const trend: "improving" | "stable" | "declining" | null =
    delta === null ? null :
    delta > 2 ? "improving" :
    delta < -2 ? "declining" : "stable";

  // Upsert — one row per client per period
  await supabase.from("client_health_scores").upsert(
    {
      client_id: clientId,
      firm_id: firmId,
      financial_year,
      snapshot_period,
      overall_score: result.overall_score,
      compliance_score: result.compliance_score,
      accounting_score: 50,
      responsiveness_score: 50,
      document_score: 50,
      financial_score: 50,
      signals: result.signals,
      trend,
      delta,
      computed_at: now.toISOString(),
    },
    { onConflict: "client_id,financial_year,snapshot_period" }
  );

  return { ...result, trend, delta };
}
