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

/**
 * TDS is a purely domestic, INR-only concept (IT Act §194) — the backend
 * always converts a foreign document's taxable value to base (INR) BEFORE
 * applying the vendor's TDS rate (apps/api/routers/purchase_bills.py calls
 * dc.to_base() ahead of TDSComputer.resolve_tds()), never off the raw
 * foreign figure. Applying the rate to the un-converted foreign taxable
 * would understate/overstate the preview by the exchange-rate factor.
 * `tdsRateBps` is basis points out of 10000 (e.g. 200 = 2%).
 */
export function estimateForeignTds(baseTaxableMinor: number, tdsRateBps: number): number {
  return Math.floor((baseTaxableMinor * tdsRateBps) / 10000);
}

/**
 * Converts an INR (base) minor-unit amount back to the foreign currency at
 * the same booking rate — used to show what a foreign vendor is actually
 * owed net of an INR-only deduction (TDS has no foreign-currency
 * representation on the backend; see estimateForeignTds above).
 * Returns 0 when the rate isn't usable yet (still being typed).
 */
export function convertBaseToForeignMinor(baseMinor: number, rate: number): number {
  return rate > 0 ? Math.round(baseMinor / rate) : 0;
}
