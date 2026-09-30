// Run with: node --experimental-strip-types --test lib/migration/writtenTypes.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  WRITTEN_ITEM_TYPES, WRITTEN_IMPORT_TYPES, ALL_IMPORT_TYPES, isWrittenImportType,
  writtenInWords, migrationSubtitle, noClientOptionLabel, importTypeNote,
} from "./writtenTypes.ts";

test("the written types are the two masters", () => {
  assert.deepEqual([...WRITTEN_ITEM_TYPES], ["customer", "vendor"]);
  assert.deepEqual([...WRITTEN_IMPORT_TYPES], ["customers", "vendors"]);
});

test("every written import type is one the wizard offers", () => {
  for (const t of WRITTEN_IMPORT_TYPES) assert.ok((ALL_IMPORT_TYPES as readonly string[]).includes(t));
});

test("the words name exactly the written kinds and nothing else", () => {
  assert.equal(writtenInWords(), "customer and vendor masters");
});

test("the subtitle says what is written and what is not, and no longer promises a ledger import", () => {
  const s = migrationSubtitle();
  assert.match(s, /customer and vendor masters/);
  assert.match(s, /not written/);
  assert.doesNotMatch(s, /Masters, Ledgers, Journals, Balances/);
});

test("the no-client choice no longer describes a firm-level import of ledgers and journals", () => {
  const l = noClientOptionLabel();
  assert.doesNotMatch(l, /ledgers and journals/i);
  assert.match(l, /writes nothing/);
});

test("a chip is annotated exactly when the importer will not write it", () => {
  for (const t of ALL_IMPORT_TYPES) {
    assert.equal(importTypeNote(t) === "", isWrittenImportType(t), t);
  }
  assert.equal(importTypeNote("customers"), "");
  assert.notEqual(importTypeNote("ledgers"), "");
});
