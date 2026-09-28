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

// `scoreToLabel` and `scoreToColor` lived here and are DELETED, not moved
// (sweep-client-purchases-05). They graded on an 80/60/40 ladder of four words
// that the engine has never used — the engine's is 80/65/50/35 with five — so
// the header badge said "Fair" at 73 while the Health page it links to said
// "Good". The one band table in the browser is `lib/health/vocabulary.ts`,
// pinned to `domain/health/scoring.GRADE_BANDS` from the Python side.
