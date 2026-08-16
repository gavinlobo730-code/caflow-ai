// GSTR-1 classification — the vocabulary, and that it matches the database.
//
//   node --experimental-strip-types --test lib/invoices/classification.test.ts
//
// Two halves. The first pins the normalisation the form relies on. The second
// reads migration 268 and asserts the dropdowns offer exactly the values the
// CHECK constraints allow — a cross-boundary test, because this is the one
// mistake that cannot be caught on either side alone: TypeScript is happy with
// a typo'd literal, and Postgres only objects when a CA presses Save.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  DEFAULT_INVOICE_TYPE, DEFAULT_SUPPLY_TYPE, INVOICE_TYPES, SUPPLY_TYPES,
  classificationFrom, isNonStandard, toClassificationPayload,
} from "./classification.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MIGRATION = path.join(__dirname, "../../../api/migrations/268_sales_invoice_gst_classification.sql");

// ── reading an invoice back ──────────────────────────────────────────────────

test("an invoice with no classification reads as a plain taxable sale", () => {
  // The defaults are what every pre-268 invoice means. If this changes, 5,662
  // existing invoices change meaning with it.
  assert.deepEqual(classificationFrom(null), {
    supplyType: "taxable", invoiceType: "Regular", isReverseCharge: false,
  });
  assert.deepEqual(classificationFrom({}), {
    supplyType: "taxable", invoiceType: "Regular", isReverseCharge: false,
  });
});

test("a stored classification round-trips", () => {
  assert.deepEqual(
    classificationFrom({ supply_type: "zero_rated", invoice_type: "SEZ_without_payment", is_reverse_charge: true }),
    { supplyType: "zero_rated", invoiceType: "SEZ_without_payment", isReverseCharge: true },
  );
});

test("an unrecognised value falls back rather than being passed through", () => {
  // A duplicate seed is JSON from localStorage and may predate a vocabulary
  // change. Passing the stale string on would fail 268's CHECK at save time,
  // surfacing as an unexplained error on an unrelated edit.
  const state = classificationFrom({ supply_type: "vat", invoice_type: "Proforma" });
  assert.equal(state.supplyType, DEFAULT_SUPPLY_TYPE);
  assert.equal(state.invoiceType, DEFAULT_INVOICE_TYPE);
});

test("a null reverse-charge flag is false, not null", () => {
  assert.equal(classificationFrom({ is_reverse_charge: null }).isReverseCharge, false);
});

// ── building the payload ─────────────────────────────────────────────────────

test("all three fields are sent even at their defaults", () => {
  // Omitting them lets the server fall back — the exact behaviour that made
  // every invoice look like a plain taxable sale.
  assert.deepEqual(
    toClassificationPayload({ supplyType: "taxable", invoiceType: "Regular", isReverseCharge: false }),
    { supply_type: "taxable", invoice_type: "Regular", is_reverse_charge: false },
  );
});

test("correcting an SEZ draft back to Regular is sendable", () => {
  // If defaults were omitted from the payload this correction could not be
  // saved: the stored SEZ value would simply stay.
  const payload = toClassificationPayload({
    supplyType: "taxable", invoiceType: "Regular", isReverseCharge: false,
  });
  assert.equal(payload.invoice_type, "Regular");
});

test("the payload uses the API's field names, not the editor's", () => {
  const payload = toClassificationPayload({
    supplyType: "exempt", invoiceType: "Deemed_export", isReverseCharge: true,
  });
  assert.deepEqual(Object.keys(payload).sort(), ["invoice_type", "is_reverse_charge", "supply_type"]);
  assert.equal(payload.supply_type, "exempt");
  assert.equal(payload.invoice_type, "Deemed_export");
  assert.equal(payload.is_reverse_charge, true);
});

// ── drawing attention ────────────────────────────────────────────────────────

test("a plain taxable sale is not flagged as non-standard", () => {
  assert.equal(isNonStandard({ supplyType: "taxable", invoiceType: "Regular", isReverseCharge: false }), false);
});

test("any departure from a plain taxable sale is flagged", () => {
  assert.equal(isNonStandard({ supplyType: "exempt", invoiceType: "Regular", isReverseCharge: false }), true);
  assert.equal(isNonStandard({ supplyType: "taxable", invoiceType: "SEZ_with_payment", isReverseCharge: false }), true);
  assert.equal(isNonStandard({ supplyType: "taxable", invoiceType: "Regular", isReverseCharge: true }), true);
});

// ── the dropdowns match the database ─────────────────────────────────────────

/** Pull the allowed values out of `CHECK (col IN ('a', 'b'))` in the migration. */
function checkedValues(sql: string, column: string): string[] {
  const re = new RegExp(`CHECK\\s*\\(\\s*${column}\\s+IN\\s*\\(([^)]*)\\)`, "i");
  const m = re.exec(sql);
  assert.ok(m, `no CHECK constraint found for ${column} in migration 268`);
  return [...m[1].matchAll(/'([^']+)'/g)].map((x) => x[1]);
}

test("the migration is where it is expected to be", () => {
  // If 268 is ever renamed this test must be pointed at the new name rather
  // than deleted — a silently skipped cross-boundary check is worse than none.
  assert.ok(fs.existsSync(MIGRATION), `migration not found at ${MIGRATION}`);
});

test("supply type offers exactly what the CHECK constraint allows", () => {
  const sql = fs.readFileSync(MIGRATION, "utf8");
  assert.deepEqual(
    SUPPLY_TYPES.map((o) => o.value).sort(),
    checkedValues(sql, "supply_type").sort(),
  );
});

test("invoice type offers exactly what the CHECK constraint allows", () => {
  const sql = fs.readFileSync(MIGRATION, "utf8");
  assert.deepEqual(
    INVOICE_TYPES.map((o) => o.value).sort(),
    checkedValues(sql, "invoice_type").sort(),
  );
});

test("the defaults are the column defaults", () => {
  const sql = fs.readFileSync(MIGRATION, "utf8");
  assert.match(sql, new RegExp(`supply_type\\s+TEXT\\s+NOT NULL\\s+DEFAULT\\s+'${DEFAULT_SUPPLY_TYPE}'`, "i"));
  assert.match(sql, new RegExp(`invoice_type\\s+TEXT\\s+NOT NULL\\s+DEFAULT\\s+'${DEFAULT_INVOICE_TYPE}'`, "i"));
});

test("every option carries a label and a statutory note", () => {
  for (const o of [...SUPPLY_TYPES, ...INVOICE_TYPES]) {
    assert.ok(o.label.trim().length > 0, `${o.value} has no label`);
    assert.ok(o.note.trim().length > 0, `${o.value} has no note`);
  }
});
