// accounting-18 — the spreadsheet side of the fixed-asset register import, as pure
// functions. What the SERVER decides (category, basis, position, duplicate,
// re-upload) is pinned in apps/api/tests/test_opening_register_import.py; this is
// the conversion the browser owns.
//
// Run with: node --experimental-strip-types --test lib/fixedAssets/openingRegister.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  buildOpeningRegisterRows, openingRegisterColumns, openingRegisterHeadline,
  openingRegisterOutcome, openingRegisterWarnings, positionChoices,
  type OpeningRegisterResult,
} from "./openingRegister.ts";

const sheetRow = (over: Record<string, string> = {}) => ({
  asset_code: "TAG-001", asset_name: "CNC lathe", asset_category: "Plant & Machinery",
  purchase_date: "12-06-2021", cost: "12,50,000.50", accumulated_depreciation: "4,10,000.25",
  depreciation_method: "WDV", put_to_use_date: "", salvage_value: "", useful_life_years: "",
  wdv_rate_percent: "", it_block_key: "", location: "", notes: "", ...over,
});

test("the identifying columns and the two figures that make it a position are required", () => {
  const req = openingRegisterColumns().filter((c) => c.required).map((c) => c.key);
  assert.deepEqual(req, ["asset_code", "asset_name", "asset_category", "purchase_date",
    "cost", "accumulated_depreciation"]);
});

test("the method is not a required column, because Land has none to state", () => {
  const m = openingRegisterColumns().find((c) => c.key === "depreciation_method");
  assert.equal(m?.required, false);
});

test("the category hint names what the SERVER holds, and says something where it could not be asked", () => {
  const hint = (cats?: string[]) =>
    openingRegisterColumns(cats).find((c) => c.key === "asset_category")?.hint ?? "";
  assert.equal(hint(["Land", "Vehicles"]), "One of: Land, Vehicles");
  assert.match(hint(), /Schedule II category/);
  assert.match(hint([]), /Schedule II category/);
});

test("a row is converted to exact paise and nothing is decided", () => {
  const [r] = buildOpeningRegisterRows([sheetRow()]);
  assert.equal(r.cost_paise, 125_000_050);
  assert.equal(r.accumulated_depreciation_paise, 41_000_025);
  assert.equal(r.salvage_value_paise, 0);
  // Dates, the category and the method go up exactly as typed — the server reads them.
  assert.equal(r.purchase_date, "12-06-2021");
  assert.equal(r.asset_category, "Plant & Machinery");
  assert.equal(r.depreciation_method, "WDV");
});

test("a blank REQUIRED amount is unknown, never a nil", () => {
  const [r] = buildOpeningRegisterRows([sheetRow({ accumulated_depreciation: "  ", cost: "" })]);
  assert.equal(r.accumulated_depreciation_paise, null);
  assert.equal(r.cost_paise, null);
});

test("a written nil is a nil", () => {
  const [r] = buildOpeningRegisterRows([sheetRow({ accumulated_depreciation: "0" })]);
  assert.equal(r.accumulated_depreciation_paise, 0);
});

test("a cell that is not an amount travels as null, never as a number", () => {
  for (const bad of ["12abc", "1e3", "1.234", "abc", "Rs. ten"]) {
    const [r] = buildOpeningRegisterRows([sheetRow({ cost: bad, accumulated_depreciation: bad, salvage_value: bad })]);
    assert.equal(r.cost_paise, null, bad);
    assert.equal(r.accumulated_depreciation_paise, null, bad);
    assert.equal(r.salvage_value_paise, null, bad);
  }
});

test("blank optional text is null so the server can tell 'not stated' from a value", () => {
  const [r] = buildOpeningRegisterRows([sheetRow({ put_to_use_date: " ", it_block_key: "" })]);
  assert.equal(r.put_to_use_date, null);
  assert.equal(r.it_block_key, null);
  const [s] = buildOpeningRegisterRows([sheetRow({ put_to_use_date: "01-07-2021", it_block_key: "PM15" })]);
  assert.equal(s.put_to_use_date, "01-07-2021");
  assert.equal(s.it_block_key, "PM15");
});

test("the preview's row numbers survive the rows the dialog held back", () => {
  const rows = buildOpeningRegisterRows([sheetRow(), sheetRow(), sheetRow()], [2, 3, 9]);
  assert.deepEqual(rows.map((r) => r.row), [2, 3, 9]);
  assert.deepEqual(buildOpeningRegisterRows([sheetRow(), sheetRow()]).map((r) => r.row), [1, 2]);
});

const result = (over: Partial<OpeningRegisterResult> = {}): OpeningRegisterResult => ({
  as_at: "2026-03-31", dry_run: false, received: 4, created: 2, would_create: 0,
  already_recorded: 1, rejected: 1, cost_paise: 30_000_00, accumulated_paise: 10_000_00,
  net_paise: 20_000_00, by_category: [], gaps: [], next_depreciation_month: "2026-04",
  ledger_note: "Nothing was posted to the ledger.",
  rows: [
    { row: 1, asset_code: "A1", status: "new", problems: [], warnings: ["A rate that departs."], id: "x" },
    { row: 2, asset_code: "A2", status: "new", problems: [], warnings: [], id: "y" },
    { row: 3, asset_code: "A3", status: "already_recorded", problems: [], warnings: [], id: "z" },
    { row: 4, asset_code: "A4", status: "rejected", problems: ["The cost is nil.", "No category."], warnings: [], id: null },
  ], ...over,
});

test("verdicts become the dialog's counters and lists, by code and row", () => {
  const out = openingRegisterOutcome(result());
  assert.equal(out.imported, 2);
  assert.equal(out.skipped, 1);
  assert.deepEqual(out.skippedDetail, ["Asset A3 (row 3): already on the register — nothing added"]);
  assert.deepEqual(out.errors, ["Asset A4 (row 4): The cost is nil. No category."]);
});

test("a malformed answer cannot crash the report", () => {
  const out = openingRegisterOutcome(result({ rows: undefined as unknown as [] }));
  assert.deepEqual(out.errors, []);
  assert.deepEqual(openingRegisterWarnings(result({ rows: undefined as unknown as [] })), []);
});

test("the headline says where the register stands", () => {
  const rupees = (p: number) => `₹${(p / 100).toFixed(2)}`;
  assert.equal(openingRegisterHeadline(result(), rupees),
    "2 assets brought over as at 2026-03-31 — cost ₹30000.00, accumulated depreciation "
    + "₹10000.00, net block ₹20000.00; 1 already on the register; 1 refused.");
  assert.equal(openingRegisterHeadline(result({ created: 0, already_recorded: 0, rejected: 0 }), rupees),
    "0 assets brought over as at 2026-03-31.");
});

test("warnings are those of assets that landed, each with its asset", () => {
  assert.deepEqual(openingRegisterWarnings(result()), ["Asset A1 (row 1): A rate that departs."]);
});

test("the positions offered are the 31 Marches that have passed, derived from the clock", () => {
  const oct2026 = positionChoices(4, new Date(2026, 9, 1));
  assert.deepEqual(oct2026.map((c) => c.value),
    ["2026-03-31", "2025-03-31", "2024-03-31", "2023-03-31"]);
  assert.match(oct2026[0].label, /31 March 2026/);
  assert.match(oct2026[0].label, /FY 2025-26/);
  // A year that has not ended is not offered — nothing can be stated as at it.
  assert.ok(!oct2026.some((c) => c.value === "2027-03-31"));
});

test("the year ends on its own last day and not a day before", () => {
  assert.ok(!positionChoices(4, new Date(2027, 2, 30)).some((c) => c.value === "2027-03-31"));
  assert.equal(positionChoices(4, new Date(2027, 2, 31))[0].value, "2027-03-31");
});
