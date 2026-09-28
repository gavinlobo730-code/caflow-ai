/**
 * The client-health model's words, in ONE place in the browser.
 *
 * WHY THIS EXISTS (sweep-client-misc-04, sweep-health-hub-06,
 * sweep-client-purchases-05). The same seven dimensions had four sets of
 * names: the firm-level detail page, the client tab's cards (which read the
 * LEGACY flat columns — "Relationship Risk" is a constant 100 and "Financial
 * Risk" is Open Notices under another name), that tab's Add Override picker,
 * and the Overview card. A CA who wanted to override the card they could see
 * found no entry of that name in the picker. And the score badge graded on
 * its own 80/60/40 ladder, so 73 read "Fair" in the header and "Good" one
 * click away on the Health page, which shows the server's grade.
 *
 * THE AUTHORITY IS `apps/api/domain/health/scoring.py` — `DIMENSION_WEIGHTS_BP`,
 * `DIMENSION_LABELS` and `GRADE_BANDS`. This file is pinned to it FROM THE
 * PYTHON SIDE by `tests/test_one_health_vocabulary.py`, the Schedule III
 * caption lesson: a guard written here would assert the browser against a
 * copy of itself and pass whenever both drifted together.
 *
 * `gradeForScore` is a FALLBACK. Wherever the server has answered with a
 * `grade`, render that; this is for surfaces that hold only a number (the
 * clients list). It agrees with the server by construction: the server grades
 * the composite AFTER overrides, and a hard override caps the composite at 34,
 * which this ladder also calls Critical.
 *
 * Keep the literals below in the shapes they are in — the pinning test reads
 * them with a regex, and fails loudly (rather than passing vacuously) if it
 * cannot find all seven dimensions and all five bands.
 */

export type HealthDimensionKey =
  | "compliance_health"
  | "accounting_quality"
  | "work_progress"
  | "document_health"
  | "ai_risk_signals"
  | "open_notices"
  | "client_responsiveness";

export interface HealthDimensionMeta {
  key: HealthDimensionKey;
  label: string;
  /** Basis points; the seven sum to 10000. */
  weightBp: number;
  /** What moves it — help text, from the engine's own docstring. */
  description: string;
}

/** In the model's order, which is also descending weight. */
export const HEALTH_DIMENSIONS: readonly HealthDimensionMeta[] = [
  { key: "compliance_health", label: "Compliance Health", weightBp: 2500, description: "Overdue returns, late filings, pending notices" },
  { key: "accounting_quality", label: "Accounting Quality", weightBp: 2000, description: "Bank reconciliation age, unclosed periods" },
  { key: "work_progress", label: "Work Progress", weightBp: 1500, description: "Overdue and at-risk work items" },
  { key: "document_health", label: "Document Health", weightBp: 1500, description: "Outstanding requests, missing required docs" },
  { key: "ai_risk_signals", label: "AI Risk Signals", weightBp: 1000, description: "Open critical insights and warnings" },
  { key: "open_notices", label: "Open Notices", weightBp: 1000, description: "Government notices by age and deadline" },
  { key: "client_responsiveness", label: "Client Responsiveness", weightBp: 500, description: "Portal login recency, upload delay" },
];

export const HEALTH_DIMENSION_KEYS: readonly HealthDimensionKey[] =
  HEALTH_DIMENSIONS.map((d) => d.key);

const BY_KEY: ReadonlyMap<string, HealthDimensionMeta> =
  new Map(HEALTH_DIMENSIONS.map((d) => [d.key, d]));

export function dimensionMeta(key: string | null | undefined): HealthDimensionMeta | undefined {
  return key ? BY_KEY.get(key) : undefined;
}

/** The dimension's one name. An unknown key is shown as itself rather than
 *  dropped — an override recorded against a dimension the model no longer has
 *  still has to be visible so it can be removed. */
export function dimensionLabel(key: string | null | undefined): string {
  if (!key) return "Overall";
  return BY_KEY.get(key)?.label ?? key;
}

/** "25%" from 2500 bp. Integer basis points, so no float is ever displayed. */
export function weightLabel(weightBp: number): string {
  return `${weightBp / 100}%`;
}

export type HealthGrade = "Healthy" | "Good" | "Needs Attention" | "At Risk" | "Critical";

/** Highest floor first — `domain/health/scoring.GRADE_BANDS`, row for row. */
export const HEALTH_GRADE_BANDS: readonly { min: number; grade: HealthGrade }[] = [
  { min: 80, grade: "Healthy" },
  { min: 65, grade: "Good" },
  { min: 50, grade: "Needs Attention" },
  { min: 35, grade: "At Risk" },
  { min: 0, grade: "Critical" },
];

export const HEALTH_GRADES: readonly HealthGrade[] = HEALTH_GRADE_BANDS.map((b) => b.grade);

/** The band for a composite score — the FALLBACK for a surface holding only a
 *  number. Prefer the server's `grade` wherever the payload carries one. */
export function gradeForScore(score: number): HealthGrade {
  for (const band of HEALTH_GRADE_BANDS) {
    if (score >= band.min) return band.grade;
  }
  return "Critical";
}

/** Read a grade off a payload: the server's word where it is one of the five,
 *  otherwise the band of the score. A stored row can carry a legacy letter or
 *  nothing at all, and neither should reach the screen as a grade. */
export function gradeOf(serverGrade: unknown, score: number): HealthGrade {
  return typeof serverGrade === "string" && (HEALTH_GRADES as readonly string[]).includes(serverGrade)
    ? (serverGrade as HealthGrade)
    : gradeForScore(score);
}
