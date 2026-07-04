/**
 * Client Health — thin wrapper over the canonical backend engine
 * (routers/health.py, Product Bible Chapter 16: 7 weighted dimensions +
 * statutory hard overrides). All scoring logic is server-side; this file
 * only fetches, triggers an on-demand calculation when none exists yet
 * (the backend has no scheduled recalculation job — computing is always
 * caller-triggered), and derives a short presentational alert list from an
 * already-fetched breakdown.
 */
import { api } from "@/lib/api";
import type { ApiResp } from "@/lib/api";

export interface HealthDimension {
  score: number;
  weight: number;
  weighted: number;
}

export interface ClientHealth {
  client_id: string;
  client_name: string;
  overall_score: number;
  grade: string;
  trend: "improving" | "stable" | "declining" | null;
  dimensions: Record<string, HealthDimension>;
  hard_override: string | null;
  hard_override_reason: string | null;
  is_critical: boolean;
  is_at_risk: boolean;
  last_calculated_at: string | null;
}

export interface HealthAlert {
  severity: "critical" | "warning" | "info";
  dimension: string;
  message: string;
}

export const DIMENSION_LABELS: Record<string, string> = {
  compliance_health: "Compliance",
  accounting_quality: "Accounting",
  work_progress: "Work Progress",
  document_health: "Documents",
  ai_risk_signals: "AI Risk Signals",
  open_notices: "Notices",
  client_responsiveness: "Responsiveness",
};

/** The backend's trend is a signed integer delta string ("+15"/"-5"/"+0").
 * Converted to the word-label the existing HealthBadge components render,
 * using the same >2 / <-2 thresholds the old client-side formula used (so a
 * ±1–2 point fluctuation still reads as "stable", not a false signal). */
function parseTrend(trend: string | null | undefined): "improving" | "stable" | "declining" | null {
  if (!trend) return null;
  const n = parseInt(trend, 10);
  if (Number.isNaN(n)) return null;
  if (n > 2) return "improving";
  if (n < -2) return "declining";
  return "stable";
}

interface RawClientHealth {
  client_id: string;
  client_name: string;
  overall_score: number;
  grade: string;
  trend: string | null;
  dimensions: Record<string, HealthDimension>;
  hard_override: string | null;
  hard_override_reason: string | null;
  is_critical: boolean;
  is_at_risk: boolean;
  last_calculated_at: string | null;
}

function toClientHealth(raw: RawClientHealth): ClientHealth {
  return { ...raw, trend: parseTrend(raw.trend) };
}

/** Latest health score, without triggering a calculation. Null if none
 * exists yet (a client that has never been visited/calculated). */
export async function getLatestHealthScore(clientId: string): Promise<ClientHealth | null> {
  try {
    const res = (await api.health.client(clientId)) as ApiResp<RawClientHealth>;
    return toClientHealth(res.data);
  } catch {
    return null;
  }
}

/** Fetches the client's current health score, calculating one on first
 * visit if none exists yet. */
export async function getOrCalculateClientHealth(clientId: string): Promise<ClientHealth | null> {
  const existing = await getLatestHealthScore(clientId);
  if (existing) return existing;
  try {
    const res = (await api.health.calculate(clientId)) as ApiResp<RawClientHealth>;
    return toClientHealth(res.data);
  } catch {
    return null;
  }
}

/** Bulk latest scores for a client list (badges) — one request regardless
 * of list size, matching the prior single-query perf fix's intent. */
export async function getLatestHealthScores(clientIds: string[]): Promise<Record<string, number>> {
  if (clientIds.length === 0) return {};
  const res = (await api.health.scores()) as ApiResp<Array<{ client_id: string; overall_score: number }>>;
  const wanted = new Set(clientIds);
  const map: Record<string, number> = {};
  for (const row of res.data ?? []) {
    if (wanted.has(row.client_id)) map[row.client_id] = row.overall_score;
  }
  return map;
}

/** Presentational-only: derive a short alert list from an already-fetched
 * health breakdown (no extra network calls). A statutory hard override
 * (Product Bible Ch.16 — notice deadline missed, GSTR-3B overdue >2mo,
 * etc.) is always critical; any dimension scoring below 50 gets a
 * lightweight callout. */
export function deriveHealthAlerts(health: ClientHealth): HealthAlert[] {
  const alerts: HealthAlert[] = [];
  if (health.hard_override && health.hard_override_reason) {
    alerts.push({ severity: "critical", dimension: "Compliance", message: health.hard_override_reason });
  }
  for (const [key, dim] of Object.entries(health.dimensions)) {
    if (dim.score < 50) {
      const label = DIMENSION_LABELS[key] ?? key;
      alerts.push({
        severity: dim.score < 35 ? "critical" : "warning",
        dimension: label,
        message: `${label} scoring ${dim.score}/100`,
      });
    }
  }
  return alerts;
}
