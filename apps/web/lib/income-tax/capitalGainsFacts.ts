/**
 * Two facts a capital-gains entry cannot derive, and WHEN the screen has to
 * ask for them (IT-28, IT-19).
 *
 * THIS FILE DECIDES NOTHING. `apps/api/domain/income_tax/capital_gains_engine.py`
 * is the authority for both rules — which holding period applies, and what
 * s.55(2)(ac) makes the cost of acquisition. What lives here is only the
 * question of whether a CONTROL is worth rendering, which is a fact about this
 * form rather than about the Act, and the values below are pinned to the
 * engine's own constants from the PYTHON side by
 * `apps/api/tests/test_a_capital_gain_asks_what_it_cannot_derive.py`.
 *
 * Pinned from Python deliberately: a guard written here would assert the
 * browser against a copy of itself and pass whenever both drifted together —
 * the Schedule III caption lesson, and the same reason
 * `lib/constants/uqc.ts` is pinned that way. There is no endpoint for the
 * same reason there is none for the UQC list: three short constants that
 * move by Finance Act would be a Singapore-to-Mumbai round trip on every
 * keystroke, and the parity test already prevents the drift an endpoint
 * would.
 */

/** Asset types for which "is this security listed?" is a live, unanswered
 *  question — `capital_gains_engine._LISTING_IS_ASKED`. Everything else has
 *  already answered it: equity and equity-oriented funds are on twelve months
 *  either way, property and gold are not securities, a VDA is charged under
 *  s.115BBH whatever the holding period, `unlisted` says so in its own name,
 *  and a debt-fund unit is outside the twelve-month limb, which reaches a
 *  security "other than a unit". */
export const LISTING_IS_ASKED: readonly string[] = ["bonds", "other"];

/** Asset types s.112A charges, and therefore the ones s.55(2)(ac) can
 *  substitute a cost for — `capital_gains_engine._EQUITY_LIKE`. */
export const GRANDFATHERING_ASSET_TYPES: readonly string[] =
  ["equity", "equity_shares", "mutual_funds"];

/** s.55(2)(ac) reaches an asset "acquired before the 1st day of February,
 *  2018", so the test is strictly earlier than this date —
 *  `capital_gains_engine.SECTION_55_2_AC_ACQUIRED_BEFORE`. */
export const SECTION_55_2_AC_ACQUIRED_BEFORE = "2018-02-01";

/** Whether the listing control is worth showing for this asset type. */
export function listingIsAsked(assetType: string): boolean {
  return LISTING_IS_ASKED.includes(assetType);
}

/** Whether the 31-01-2018 fair-market-value box is worth showing. Both limbs
 *  are needed: the asset must be one s.112A charges AND it must have been
 *  acquired before the cut-off. A blank purchase date shows nothing rather
 *  than assuming either way. */
export function grandfatheringIsAsked(assetType: string, purchaseDate: string): boolean {
  if (!GRANDFATHERING_ASSET_TYPES.includes(assetType)) return false;
  if (!purchaseDate) return false;
  return purchaseDate < SECTION_55_2_AC_ACQUIRED_BEFORE;
}
