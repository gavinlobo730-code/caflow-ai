/**
 * The shapes the amortisation reclassification screen reads (POST-A-345, stage 3), and the one place they are checked.
 *
 * THIS MODULE DECIDES NOTHING. Which assets move, what each move is made of, which balance sheets it changes and every reason a batch
 * must not be posted are `apps/api/services/amortisation_reclass_service`'s answers, served as figures in paise and sentences in
 * words. What is here is the type of that answer and the one check that a payload is the kind of thing the screen can read: `{}` and
 * `[]` are both truthy, and a screen that maps over `assets` on either throws (lib/api/shape.ts says why that rule exists).
 *
 * The field names are the server's, and a test on the API side reads this file and fails if one stops being served
 * (`test_the_screens_types_name_exactly_the_keys_the_server_serves` in
 * `tests/test_an_intangible_assets_amortisation_moves_to_its_own_ledger.py`).
 */
import { objectWithLists } from "@/lib/api/shape";

export type ReclassAsset = {
  asset_id: string;
  asset_code: string;
  asset_name: string;
  /** "moves" (journals are posted) or "pointed_only" (nothing was depreciated, so the asset is only pointed at its own ledger). */
  outcome: string;
  register_paise: number;
  posted_by_depreciation_paise: number;
  carried_over_paise: number;
  /** Moved in the entry dated the stated date. */
  moves_as_at_paise: number;
  /** Moved in entries dated each later financial year end, or today: the months posted after the stated date. */
  moves_later_paise: number;
  journal_count: number;
};

export type ReclassLedger = { id: string; code?: string | null; name?: string | null };

/** A ledger the server offers for the part of the depreciation an asset brought over with it: it holds a credit and looks the part. */
export type ReclassCandidate = ReclassLedger & { credit_paise: number };

export type ReclassedAsset = {
  asset_id: string;
  asset_code: string | null;
  asset_name: string | null;
  /** False for an asset created pointing at its own ledger: it has no move to undo. */
  moved_by_reclassification: boolean;
  /** Its move did not finish (an entry of it is still posted with the asset back on the shared ledger, or the asset points at the new
   *  ledger and the ledger holds a different amount for it from the register's): Undo finishes taking it back. */
  unfinished: boolean;
};

export type ReclassPreview = {
  as_at: string;
  ready: boolean;
  refusals: string[];
  assets: ReclassAsset[];
  excluded: { asset_id: string; asset_code: string | null; reason: string }[];
  reclassified: ReclassedAsset[];
  own_ledger: ReclassLedger | null;
  shared_ledger: ReclassLedger | null;
  carried_over_ledger: ReclassLedger | null;
  carried_over_candidates: ReclassCandidate[];
  carried_over_total_paise: number;
  /** Every date an entry will be dated, in order: the stated date (only if something moves then) and each later year end or today. */
  entry_dates: string[];
  /** The dates, after the stated one, on which the months posted since are moved. */
  later_dates: string[];
  journals_to_post: number;
  /** Assets that will have an entry posted for them, and assets that are only pointed at the new ledger (nothing depreciated yet). */
  moves_count: number;
  pointed_only_count: number;
  total_to_move_paise: number;
  financial_years: { label: string; fixed: boolean; note: string }[];
};

export type ReclassFailure = {
  asset_id: string;
  asset_code: string;
  reason: string;
  /** Some of its entries are still posted and the asset stays pointed at the new ledger: Undo finishes it. */
  partly_moved?: boolean;
  live_entry_ids?: string[];
};

export type ReclassPostResult = {
  as_at: string;
  moved: { asset_id: string; asset_code: string; moved_paise: number; journal_entry_ids: string[] }[];
  skipped: { asset_id: string; asset_code: string; reason: string }[];
  failed: ReclassFailure[];
  total_moved_paise: number;
};

/** What the screen asks first, on every open: a few rows from the register, no balance and no journal line. */
export type ReclassSummary = {
  /** Intangible assets still in the shared ledger. */
  unmoved: number;
  /** Assets with a live reclassification entry: the ones an Undo can act on. */
  moved: number;
  unfinished: number;
  excluded: number;
  moved_assets: ReclassedAsset[];
  /** Why the feature cannot work for this practice (no Accumulated Amortisation ledger, or two), in words. */
  refusal: string | null;
  own_ledger: { id: string; name?: string | null } | null;
};

/** A preview payload the screen can read, or null. The lists are named because `{}` passes a plain object check. */
export function readPreview(data: unknown): ReclassPreview | null {
  return objectWithLists<ReclassPreview>(
    data, "refusals", "assets", "excluded", "reclassified", "carried_over_candidates", "entry_dates", "later_dates", "financial_years");
}

export function readPostResult(data: unknown): ReclassPostResult | null {
  return objectWithLists<ReclassPostResult>(data, "moved", "skipped", "failed");
}

export function readSummary(data: unknown): ReclassSummary | null {
  return objectWithLists<ReclassSummary>(data, "moved_assets");
}
