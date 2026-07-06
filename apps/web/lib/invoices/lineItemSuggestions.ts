/**
 * Line-item smart suggestions (HSN/SAC UX redesign). Merges the firm's Service
 * Catalogue with the HSN/SAC master+history search into ONE ranked suggestion
 * list for the invoice line Description field, so a first-time user never
 * searches for the same thing twice: type once, see the description + code +
 * GST% (+ price when a catalogue preset has one), pick one, everything fills.
 * No framework/browser deps — pure merge/mapping logic, unit-testable under
 * `node --test`.
 *
 * GST rates/codes surfaced here remain PRE-FILL HINTS ONLY (CGST Rule
 * 46(g)/(h)) — never applied to any tax/journal computation without the
 * existing CA-review + manual-override path; every field a suggestion fills
 * stays fully editable afterwards.
 */
import type { ServiceCatalogueItem } from "../catalogue/service";
import type { InvoiceLine } from "./gst";

/** A row from GET /api/hsn/search — duplicated here (not imported) because a
 * cross-module VALUE import of ../lookups/hsn from this file breaks module
 * resolution under `node --experimental-strip-types --test` in this repo (see
 * lib/invoices/compliance.ts for the same, earlier-diagnosed constraint); the
 * shape itself is tiny and stable, so a local copy is the safer choice. */
export interface HsnSuggestionRow {
  hsn_code: string;
  description?: string | null;
  gst_rate_bps?: number | null;
  uqc?: string | null;
  hsn_type?: string | null;
  source?: "history" | "master" | null;
  reason?: string | null;
}

export type SuggestionBadge = "Service" | "SAC" | "HSN" | null;

export interface LineItemSuggestion {
  /** Stable id for keying/selection: `catalogue:<id>` or `hsn:<code>`. */
  id: string;
  badge: SuggestionBadge;
  description: string;
  hsn_sac: string;
  gst_rate_bps: number | null;
  unit: string | null;
  /** Default unit price in paise, when the source carries one (catalogue only). */
  rate_paise: number | null;
  /** "Used 3 times" / "Recently used" / null — shown as a small badge. */
  reason: string | null;
  /** The catalogue item id, so a pick can bump its usage counter. Null for HSN rows. */
  catalogueId: string | null;
}

/** Same 6-digit-SAC-prefix fallback as lib/lookups/hsn.ts's hsnTypeBadge — kept
 * in sync deliberately (see the HsnSuggestionRow comment above for why this
 * isn't a shared import). */
function hsnBadge(row: HsnSuggestionRow): SuggestionBadge {
  if (row.hsn_type === "services") return "SAC";
  if (row.hsn_type === "goods") return "HSN";
  if (!row.hsn_type && /^99\d{4}$/.test(row.hsn_code)) return "SAC";
  return null;
}

function catalogueReason(item: ServiceCatalogueItem): string | null {
  const n = item.use_count ?? 0;
  if (n <= 0) return null;
  return `Used ${n} time${n === 1 ? "" : "s"}`;
}

function fromCatalogue(item: ServiceCatalogueItem): LineItemSuggestion {
  return {
    id: `catalogue:${item.id}`,
    badge: "Service",
    description: (item.description?.trim() || item.name).trim(),
    hsn_sac: item.hsn_sac ?? "",
    gst_rate_bps: item.gst_rate_bps ?? null,
    unit: item.unit ?? null,
    rate_paise: item.default_rate_paise || null,
    reason: catalogueReason(item),
    catalogueId: item.id,
  };
}

function fromHsn(row: HsnSuggestionRow): LineItemSuggestion {
  return {
    id: `hsn:${row.hsn_code}`,
    badge: hsnBadge(row),
    description: (row.description ?? "").trim() || row.hsn_code,
    hsn_sac: row.hsn_code,
    gst_rate_bps: row.gst_rate_bps ?? null,
    unit: row.uqc ?? null,
    rate_paise: null,
    reason: row.reason ?? null,
    catalogueId: null,
  };
}

/**
 * Merge catalogue + HSN results into one ranked list: the firm's own priced
 * billing presets first (richest auto-fill — includes a price), then HSN/SAC
 * rows in the server's existing history → services → goods relevance order.
 * An HSN row whose code exactly matches a catalogue item already in the list
 * is dropped — the catalogue version wins because it also carries a price, so
 * the same code is never shown twice for one search.
 */
export function mergeLineItemSuggestions(
  catalogue: ServiceCatalogueItem[],
  hsn: HsnSuggestionRow[],
): LineItemSuggestion[] {
  const catalogueRows = catalogue.map(fromCatalogue);
  const catalogueCodes = new Set(
    catalogueRows.map((r) => r.hsn_sac).filter((code): code is string => !!code),
  );
  const hsnRows = hsn
    .filter((row) => !catalogueCodes.has(row.hsn_code))
    .map(fromHsn);
  return [...catalogueRows, ...hsnRows];
}

/** Map a picked suggestion to the line-item fields it fills. Never overwrites
 * with a value the source doesn't actually have (e.g. an HSN-only pick leaves
 * `rate` untouched) — the CA can always edit any field afterwards. */
export function suggestionToLinePatch(s: LineItemSuggestion): Partial<InvoiceLine> {
  const patch: Partial<InvoiceLine> = { description: s.description };
  if (s.hsn_sac) patch.hsn_sac = s.hsn_sac;
  if (s.gst_rate_bps != null) patch.gst_rate = Math.round(s.gst_rate_bps / 100);
  if (s.unit) patch.unit = s.unit;
  if (s.rate_paise) patch.rate = String(s.rate_paise / 100);
  return patch;
}
