/**
 * Multi-Currency UI preview helpers (sales/page.tsx, purchases/page.tsx).
 * The Phase 3-5 backend (apps/api/domain/currency/*) is the sole source of
 * truth for what actually gets saved — these are CLIENT-SIDE ESTIMATES ONLY,
 * shown before save so a CA can sanity-check a foreign document while typing.
 * They deliberately do a single multiply/divide rather than the backend's
 * real Decimal HALF_UP-per-component conversion, so a save can land a paisa
 * or cent away from what was previewed — never treat these as authoritative.
 */

/** Foreign-currency minor units (e.g. USD cents) × booking rate → estimated
 * base (INR) minor units (paise). Caller decides whether/when a rate is
 * usable (e.g. guard on `rate > 0`) — this function does no validation. */
export function estimateBaseMinor(foreignMinor: number, rate: number): number {
  return Math.round(foreignMinor * rate);
}


