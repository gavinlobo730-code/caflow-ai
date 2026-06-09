// Health Engine — types and interfaces only (Phase 0 stub)
// Computation layer is Phase 1

export type HealthTrend = "improving" | "stable" | "declining";

export interface HealthSignal {
  signal: string;
  weight: number;      // 0–1
  value: number;       // 0–100
  label: string;
}

export interface ClientHealthScore {
  id: string;
  client_id: string;
  firm_id: string;
  financial_year: string;
  snapshot_period: string;

  overall_score: number;
  compliance_score: number;
  accounting_score: number;
  responsiveness_score: number;
  document_score: number;
  financial_score: number;

  signals: HealthSignal[];
  trend: HealthTrend | null;
  delta: number | null;

  computed_at: string;
  created_at: string;
}

export interface HealthOverride {
  id: string;
  client_id: string;
  firm_id: string;
  financial_year: string;
  snapshot_period: string;
  dimension: string;
  override_score: number;
  reason: string;
  created_by: string;
  created_at: string;
  expires_at: string | null;
}

export type HealthDimension =
  | "overall"
  | "compliance"
  | "accounting"
  | "responsiveness"
  | "document"
  | "financial";

export function scoreToLabel(score: number): string {
  if (score >= 80) return "Healthy";
  if (score >= 60) return "Fair";
  if (score >= 40) return "At Risk";
  return "Critical";
}

export function scoreToColor(score: number): string {
  if (score >= 80) return "text-emerald-400";
  if (score >= 60) return "text-yellow-400";
  if (score >= 40) return "text-orange-400";
  return "text-red-400";
}
