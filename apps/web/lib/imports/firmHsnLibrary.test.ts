// Firm HSN/SAC Library bulk-import mapper tests. Run with:
//   node --experimental-strip-types --test lib/imports/firmHsnLibrary.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { buildFirmHsnCodes } from "./firmHsnLibrary.ts";

const row = (o: Record<string, string>) => o;

test("valid rows map through with gst_rate -> gst_rate_pct and source 'import'", () => {
  const { records, errors } = buildFirmHsnCodes([
    row({ hsn_code: "998221", description: "Statutory audit services", hsn_type: "services", gst_rate: "18" }),
    row({ hsn_code: "7214", description: "Steel bars and rods", hsn_type: "goods" }),
  ]);
  assert.equal(errors.length, 0);
  assert.equal(records.length, 2);
  assert.deepEqual(records[0], {
    hsn_code: "998221", description: "Statutory audit services", hsn_type: "services",
    gst_rate_pct: 18, uqc: undefined, notes: undefined, source: "import",
  });
  assert.equal(records[1].gst_rate_pct, undefined); // optional, omitted
});

test("hsn_type is case-insensitive and normalizes to lowercase", () => {
  const { records, errors } = buildFirmHsnCodes([
    row({ hsn_code: "998221", description: "x", hsn_type: "Services" }),
  ]);
  assert.equal(errors.length, 0);
  assert.equal(records[0].hsn_type, "services");
});

test("missing code, bad code shape, missing description, bad type all reported", () => {
  const { records, errors } = buildFirmHsnCodes([
    row({ description: "no code", hsn_type: "goods" }),
    row({ hsn_code: "12", description: "x", hsn_type: "goods" }), // valid: 2 digits
    row({ hsn_code: "ABC123", description: "bad shape", hsn_type: "goods" }),
    row({ hsn_code: "998222", hsn_type: "services" }), // missing description
    row({ hsn_code: "998223", description: "x", hsn_type: "widgets" }), // bad type
  ]);
  assert.equal(records.length, 1);
  assert.equal(records[0].hsn_code, "12");
  assert.equal(errors.length, 4);
  assert.match(errors.join(" "), /code is required/i);
  assert.match(errors.join(" "), /must be 2-8 digits/i);
  assert.match(errors.join(" "), /description is required/i);
  assert.match(errors.join(" "), /must be "goods" or "services"/i);
});

test("out-of-range GST % rejected; duplicate code within the file rejected", () => {
  const { records, errors } = buildFirmHsnCodes([
    row({ hsn_code: "998221", description: "x", hsn_type: "services", gst_rate: "150" }),
    row({ hsn_code: "998222", description: "first", hsn_type: "services" }),
    row({ hsn_code: "998222", description: "dup", hsn_type: "services" }),
  ]);
  assert.equal(records.length, 1);
  assert.equal(records[0].hsn_code, "998222");
  assert.match(errors.join(" "), /GST % must be between 0 and 100/i);
  assert.match(errors.join(" "), /duplicate code/i);
});

test("uqc and notes pass through when present, omitted when blank", () => {
  const { records } = buildFirmHsnCodes([
    row({ hsn_code: "998221", description: "x", hsn_type: "services", uqc: "NOS", notes: "internal note" }),
    row({ hsn_code: "998222", description: "y", hsn_type: "services", uqc: "", notes: "" }),
  ]);
  assert.equal(records[0].uqc, "NOS");
  assert.equal(records[0].notes, "internal note");
  assert.equal(records[1].uqc, undefined);
  assert.equal(records[1].notes, undefined);
});
