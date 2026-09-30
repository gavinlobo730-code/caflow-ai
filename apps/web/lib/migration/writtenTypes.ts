/**
 * What the Tally importer actually WRITES, in words the screen can print.
 *
 * The importer parses and validates six kinds of Tally item and writes exactly
 * two — customer and vendor masters (`WRITTEN_ITEM_TYPES` in
 * apps/api/domain/tally/migration_service.py). The Migration Center's heading
 * still promised "Masters, Ledgers, Journals, Balances", so the sentence a CA
 * read BEFORE starting an import promised four things and delivered one
 * (ACCOUNTING-06); the honest sentence existed, but only after the run.
 *
 * The vocabulary is the SERVER's. This file is a keystroke mirror of it, pinned
 * from the Python side by
 * apps/api/tests/test_the_migration_screen_says_what_the_importer_writes.py —
 * a guard written in apps/web would assert the page against a copy of itself
 * and pass whenever both drifted together. There is deliberately no endpoint:
 * it is a two-element constant that changes when somebody writes a third
 * importer, and that change is a code change here too.
 *
 * Pure (no React, no browser), so it runs under `node --test`.
 */

/** The item kinds `_import_single_item` creates a row for. Singular, as the
 *  items carry them. */
export const WRITTEN_ITEM_TYPES = ["customer", "vendor"] as const;

/** The job's own import types are PLURAL and the items' singular; these are the
 *  plural spellings of the two above (`_CLIENT_SCOPED_IMPORT_TYPES`). */
export const WRITTEN_IMPORT_TYPES = ["customers", "vendors"] as const;

/** Every import type the wizard offers, written or not. The job accepts all six
 *  and validates them; only the two above reach the books. */
export const ALL_IMPORT_TYPES = [
  "ledgers", "journals", "customers", "vendors", "opening_balances", "masters",
] as const;

export function isWrittenImportType(importType: string): boolean {
  return (WRITTEN_IMPORT_TYPES as readonly string[]).includes(importType);
}

/** "customer and vendor masters" — built from the constant, never typed, so the
 *  copy cannot say a third thing the code does not do. */
export function writtenInWords(): string {
  const kinds = [...WRITTEN_ITEM_TYPES];
  const head = kinds.slice(0, -1).join(", ");
  const list = kinds.length > 1 ? `${head} and ${kinds[kinds.length - 1]}` : kinds[0];
  return `${list} masters`;
}

/** The heading under "Migration Center". States what is written first and what
 *  is not straight after, because the second half is the one a CA will plan
 *  around. */
export function migrationSubtitle(): string {
  return `Import ${writtenInWords()} from Tally. Ledgers, journals and opening balances `
    + `are read and checked but not written into the books — record those through the `
    + `chart of accounts, a journal or the opening-balance screens.`;
}

/** The "no client" choice in the target-client picker. The old label read
 *  "firm-level ledgers and journals", which described an import that writes
 *  nothing: customers and vendors are per-client masters, and they are the only
 *  things written. */
export function noClientOptionLabel(): string {
  return `No client — a firm-level job writes nothing, because only ${writtenInWords()} are written and each belongs to a client`;
}

/** A note beside an import-type chip the importer will not write; empty for one
 *  it will. */
export function importTypeNote(importType: string): string {
  return isWrittenImportType(importType) ? "" : "read and checked, not written";
}
