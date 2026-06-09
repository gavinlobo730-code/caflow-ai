/**
 * Client Health Engine — Multi-Dimension Scoring
 * Phase 1.1: compliance + accounting + document + responsiveness dimensions.
 * Financial dimension remains neutral (50) until tax/GST data is available.
 */
import { getSupabaseClient } from "@/lib/supabase/client";
import type { ComplianceEntry } from "@/lib/data/compliance";
import { getCurrentFinancialYear } from "@/lib/workspace/ClientNavContext";

export interface ComplianceScoreResult {
  overall_score: number;
  compliance_score: number;
  accounting_score: number;
  document_score: number;
  responsiveness_score: number;
  signals: Array<{ signal: string; weight: number; value: number; label: string }>;
  trend: "improving" | "stable" | "declining" | null;
  delta: number | null;
}

export interface HealthAlert {
  severity: "critical" | "warning" | "info";
  dimension: string;
  message: string;
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

  return {
    overall_score,
    compliance_score,
    accounting_score: 50,
    document_score: 50,
    responsiveness_score: 50,
    signals,
    trend: null,
    delta: null,
  };
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
 * Compute accounting score from journal entry activity.
 * High score = regular journal entries, recent activity.
 */
async function computeAccountingScore(clientId: string, firmId: string): Promise<number> {
  const supabase = getSupabaseClient();
  const thirtyDaysAgo = new Date(Date.now() - 30 * 86400000).toISOString().split("T")[0];
  const ninetyDaysAgo = new Date(Date.now() - 90 * 86400000).toISOString().split("T")[0];

  const [recentRes, quarterRes] = await Promise.all([
    supabase.from("journal_entries")
      .select("id", { count: "exact", head: true })
      .eq("firm_id", firmId).eq("client_id", clientId)
      .gte("entry_date", thirtyDaysAgo),
    supabase.from("journal_entries")
      .select("id", { count: "exact", head: true })
      .eq("firm_id", firmId).eq("client_id", clientId)
      .gte("entry_date", ninetyDaysAgo),
  ]);

  const recent = recentRes.count ?? 0;
  const quarter = quarterRes.count ?? 0;

  if (quarter === 0) return 30; // No entries — poor signal
  if (recent === 0) return 45;  // Stale — entries exist but none in 30 days
  if (recent >= 10) return 90;  // Very active
  if (recent >= 5)  return 75;
  if (recent >= 1)  return 60;
  return 50;
}

/**
 * Compute document score from fulfilled document requests.
 */
async function computeDocumentScore(clientId: string): Promise<number> {
  const supabase = getSupabaseClient();
  const { data } = await supabase.from("document_requests")
    .select("id, status")
    .eq("client_id", clientId)
    .order("created_at", { ascending: false })
    .limit(20);

  if (!data || data.length === 0) return 70; // No requests → neutral positive

  const total = data.length;
  const fulfilled = data.filter((d) => d.status === "fulfilled").length;
  const fulfillRate = fulfilled / total;

  if (fulfillRate >= 0.9) return 95;
  if (fulfillRate >= 0.7) return 80;
  if (fulfillRate >= 0.5) return 65;
  if (fulfillRate >= 0.3) return 50;
  return 35;
}

/**
 * Compute responsiveness score from portal message reply patterns.
 */
async function computeResponsivenessScore(clientId: string): Promise<number> {
  const supabase = getSupabaseClient();
  const { data } = await supabase.from("portal_messages")
    .select("id, sender_type, created_at")
    .eq("client_id", clientId)
    .order("created_at", { ascending: false })
    .limit(30);

  if (!data || data.length === 0) return 60; // No messages → neutral

  const caMessages = data.filter((m) => m.sender_type === "ca").length;
  const clientMessages = data.filter((m) => m.sender_type === "client").length;

  if (caMessages === 0) return 70; // CA hasn't messaged, can't judge responsiveness
  const responseRate = clientMessages / caMessages;

  if (responseRate >= 0.8) return 90;
  if (responseRate >= 0.5) return 75;
  if (responseRate >= 0.2) return 55;
  return 35;
}

/**
 * Derive health alerts from scores and compliance entries.
 */
export function deriveHealthAlerts(
  complianceScore: number,
  accountingScore: number,
  documentScore: number,
  entries: ComplianceEntry[]
): HealthAlert[] {
  const alerts: HealthAlert[] = [];
  const today = new Date().toISOString().split("T")[0];

  const overdue = entries.filter((e) => e.due_date < today && e.filing_status !== "filed");
  if (overdue.length > 0) {
    alerts.push({
      severity: overdue.length >= 3 ? "critical" : "warning",
      dimension: "Compliance",
      message: `${overdue.length} overdue filing${overdue.length > 1 ? "s" : ""}: ${overdue.slice(0, 2).map((e) => e.compliance_type).join(", ")}${overdue.length > 2 ? ` +${overdue.length - 2} more` : ""}`,
    });
  }

  const dueSoon = entries.filter((e) => {
    if (e.filing_status === "filed") return false;
    const diff = Math.ceil((new Date(e.due_date).getTime() - Date.now()) / 86400000);
    return diff >= 0 && diff <= 7;
  });
  if (dueSoon.length > 0) {
    alerts.push({
      severity: "warning",
      dimension: "Compliance",
      message: `${dueSoon.length} filing${dueSoon.length > 1 ? "s" : ""} due within 7 days`,
    });
  }

  if (accountingScore < 40) {
    alerts.push({
      severity: "warning",
      dimension: "Accounting",
      message: "No recent journal entries — books may be behind",
    });
  }

  if (documentScore < 45) {
    alerts.push({
      severity: "info",
      dimension: "Documents",
      message: "Multiple document requests unfulfilled by client",
    });
  }

  return alerts;
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
  const compResult = computeComplianceScore(entries, now);
  const financial_year = getCurrentFinancialYear();
  const snapshot_period = now.toISOString().slice(0, 7); // "YYYY-MM"

  // Compute additional dimensions in parallel
  const [accounting_score, document_score, responsiveness_score] = await Promise.all([
    computeAccountingScore(clientId, firmId).catch(() => 50),
    computeDocumentScore(clientId).catch(() => 50),
    computeResponsivenessScore(clientId).catch(() => 50),
  ]);

  // Weighted overall score (Phase 1.1):
  // Compliance: 50%, Accounting: 25%, Document: 15%, Responsiveness: 10%
  const overall_score = Math.round(
    compResult.compliance_score * 0.5 +
    accounting_score * 0.25 +
    document_score * 0.15 +
    responsiveness_score * 0.10
  );

  // Fetch previous snapshot for trend computation
  const { data: prev } = await supabase
    .from("client_health_scores")
    .select("overall_score, snapshot_period")
    .eq("client_id", clientId)
    .order("computed_at", { ascending: false })
    .limit(1)
    .maybeSingle();

  const delta = prev ? overall_score - prev.overall_score : null;
  const trend: "improving" | "stable" | "declining" | null =
    delta === null ? null :
    delta > 2 ? "improving" :
    delta < -2 ? "declining" : "stable";

  const result: ComplianceScoreResult = {
    overall_score,
    compliance_score: compResult.compliance_score,
    accounting_score,
    document_score,
    responsiveness_score,
    signals: compResult.signals,
    trend,
    delta,
  };

  // Upsert — one row per client per period
  await supabase.from("client_health_scores").upsert(
    {
      client_id: clientId,
      firm_id: firmId,
      financial_year,
      snapshot_period,
      overall_score,
      compliance_score: compResult.compliance_score,
      accounting_score,
      responsiveness_score,
      document_score,
      financial_score: 50,
      signals: compResult.signals,
      trend,
      delta,
      computed_at: now.toISOString(),
    },
    { onConflict: "client_id,financial_year,snapshot_period" }
  );

  return result;
}
