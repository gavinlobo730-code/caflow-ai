/**
 * Pure HSN/SAC lookup presentation helpers (Batch 5). No framework/browser deps,
 * so this module is unit-testable under `node --test` and shared by the HsnLookup
 * component. The backend (GET /api/hsn/search) owns relevance ranking and the
 * master data; these helpers only shape how results are grouped and labelled in
 * the picker — the returned GST rate stays a pre-fill hint (CGST Rule 46(g)),
 * never used in any tax computation.
 */

/** A row from GET /api/hsn/search (canonical master merged with firm history). */
export interface HsnRow {
  hsn_code: string;
  description?: string | null;
  gst_rate_bps?: number | null;
  uqc?: string | null;
  hsn_type?: string | null;
  source?: "history" | "master" | null;
  reason?: string | null;
}

/** Which visual group a row belongs to. History always leads (the CA's own codes). */
export type HsnGroup = "history" | "services" | "goods" | "other";

export function hsnGroupOf(row: HsnRow): HsnGroup {
  if (row.source === "history") return "history";
  if (row.hsn_type === "services") return "services";
  if (row.hsn_type === "goods") return "goods";
  return "other";
}

const GROUP_ORDER: Record<HsnGroup, number> = { history: 0, services: 1, goods: 2, other: 3 };

/** Short badge distinguishing a Service (SAC) row from a Goods (HSN) row. */
export function hsnTypeBadge(row: HsnRow): "SAC" | "HSN" | null {
  if (row.hsn_type === "services") return "SAC";
  if (row.hsn_type === "goods") return "HSN";
  // Fall back to the code shape: 6-digit SAC codes start with 99.
  if (!row.hsn_type && /^99\d{4}$/.test(row.hsn_code)) return "SAC";
  return null;
}

/**
 * Group results by kind while preserving the server's within-group relevance
 * order (a stable sort keeps ties in their original, already-ranked order):
 * the firm's own history first, then Services (SAC), then Goods (HSN). This is
 * the "one unified lookup, distinguished by grouping" behaviour — no second
 * endpoint, no separate goods/services pickers.
 */
export function orderHsnResults(rows: HsnRow[]): HsnRow[] {
  return rows
    .map((row, i) => ({ row, i }))
    .sort((a, b) => {
      const g = GROUP_ORDER[hsnGroupOf(a.row)] - GROUP_ORDER[hsnGroupOf(b.row)];
      return g !== 0 ? g : a.i - b.i; // stable within a group
    })
    .map((x) => x.row);
}

/** "18% GST" / "3% GST" / "" (unknown rate stays blank — never shown as 0%). */
export function formatHsnRate(bps?: number | null): string {
  if (bps == null) return "";
  const pct = bps / 100;
  return `${Number.isInteger(pct) ? pct : pct.toFixed(2)}% GST`;
}

/** The muted secondary line for a result row: "Description · 18% GST · NOS". */
export function hsnSecondaryLine(row: HsnRow): string {
  return [row.description, formatHsnRate(row.gst_rate_bps), row.uqc]
    .filter(Boolean)
    .join(" · ");
}
