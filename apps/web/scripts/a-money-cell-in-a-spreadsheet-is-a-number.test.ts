/**
 * A CA WHO TYPES =SUM() ON AN EXPORTED TRIAL BALANCE GETS THE TOTAL.
 *
 * ── THE DEFECT ──────────────────────────────────────────────────────────────
 * Every browser export built its money as a STRING:
 *
 *     "Budget (₹)": (r.budget_paise / 100).toFixed(2)
 *
 * `XLSX.utils.json_to_sheet` types a cell from the JavaScript value, so a
 * string becomes `t: "s"` — a TEXT cell. Excel's `=SUM()` skips text, so the
 * amount column of an exported trial balance, P&L or balance sheet totalled
 * **0**. And silently: SheetJS writes no `ignoredErrors`, so the little green
 * "number stored as text" triangle that would at least hint at it never
 * appears either.
 *
 * The figures were right. The file could not be used as a spreadsheet, which
 * is the only reason to export one.
 *
 * ── THE RULE ────────────────────────────────────────────────────────────────
 * A workbook is built by `lib/export/xlsx.buildWorkbook`, whose money cells are
 * NUMBERS carrying an Indian number FORMAT. That is asserted two ways: no
 * export may call `json_to_sheet` directly (the door), and the helper must
 * actually produce a numeric cell (the behaviour), because a door everything
 * goes through is worth nothing if what comes out the other side is still a
 * string.
 *
 * ── AND A CSV CELL IS THE OPPOSITE ──────────────────────────────────────────
 * A CSV cell must be a bare string with no grouping and no ₹, which is why the
 * AIS screen — whose `exportRows` feeds BOTH — re-types the money on the way
 * into the sheet and leaves the CSV's rows alone. The two formats want
 * different things and one row set cannot serve both.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import * as XLSX from "xlsx";
import { buildWorkbook, moneyCell, INR_FORMAT } from "../lib/export/xlsx.ts";

const WEB = join(import.meta.dirname, "..");

function walk(dir: string, out: string[] = []): string[] {
  for (const e of readdirSync(join(WEB, dir))) {
    if (e === "node_modules" || e === ".next") continue;
    const rel = join(dir, e);
    if (statSync(join(WEB, rel)).isDirectory()) walk(rel, out);
    else if (rel.endsWith(".tsx") || rel.endsWith(".ts")) out.push(rel);
  }
  return out;
}
const FILES = [...walk("app"), ...walk("components"), ...walk("lib")];

function code(rel: string): string {
  return readFileSync(join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

/** The one place a workbook may be assembled, plus the template downloader.
 *
 *  `CsvImportModal` builds a TEMPLATE — a header row, a hint row and one
 *  example — with no money in it at all, so it has nothing to format and is
 *  named here rather than routed through a helper that would only get in its
 *  way. */
const MAY_BUILD_A_SHEET_BY_HAND = [
  "lib/export/xlsx.ts",
  "components/CsvImportModal.tsx",
];

test("no export assembles a workbook by hand", () => {
  const offenders = FILES.filter(
    (f) => !MAY_BUILD_A_SHEET_BY_HAND.some((a) => f.replace(/\\/g, "/").endsWith(a)),
  ).filter((f) => /XLSX\.utils\.(?:json_to_sheet|aoa_to_sheet)/.test(code(f)));
  assert.deepEqual(offenders, [],
    "an export builds its own sheet, so its money is whatever type the rows " +
    "happen to hold. Use buildWorkbook from lib/export/xlsx:\n  " +
    offenders.join("\n  "));
});

test("the allowlist names files that exist and still build a sheet", () => {
  for (const rel of MAY_BUILD_A_SHEET_BY_HAND.slice(1)) {
    const hit = FILES.find((f) => f.replace(/\\/g, "/").endsWith(rel));
    assert.ok(hit, `${rel} is allowlisted and does not exist`);
    assert.match(code(hit!), /XLSX\.utils\.(?:json_to_sheet|aoa_to_sheet)/,
      `${rel} is allowlisted and no longer builds a sheet — drop the exemption`);
  }
});

test("a money cell comes out of the helper as a NUMBER Excel can add", () => {
  // THE BEHAVIOUR, not the call. A door everything goes through is worth
  // nothing if what comes out is still a string, so this builds a real
  // workbook and reads the cell back.
  const wb = buildWorkbook(XLSX, {
    rows: [
      { Account: "Bank", "Amount (₹)": moneyCell(1_23_456_78) },
      { Account: "Cash", "Amount (₹)": moneyCell(50_00) },
      { Account: "Unset", "Amount (₹)": moneyCell(null) },
    ],
    moneyColumns: ["Amount (₹)"],
    sheetName: "TB",
  });
  const ws = wb.Sheets["TB"];
  assert.equal(ws["B2"].t, "n", "the first money cell is not numeric");
  assert.equal(ws["B2"].v, 123456.78);
  assert.equal(ws["B2"].z, INR_FORMAT, "and it must carry the Indian format");
  assert.equal(ws["B3"].v, 50);
  // A FIGURE NOBODY HOLDS IS AN EMPTY CELL, NOT A ZERO — the distinction this
  // product makes everywhere, and a spreadsheet is where somebody adds it up.
  assert.ok(!ws["B4"] || ws["B4"].v === null || ws["B4"].v === undefined,
    "an absent figure was written as a value");
  // The label column is untouched — formatting it would be a rupee sign on a
  // name.
  assert.equal(ws["A2"].t, "s");
  assert.equal(ws["A2"].z, undefined);
});

test("the header freezes and the columns are not clipped", () => {
  const wb = buildWorkbook(XLSX, {
    rows: [{ "A very long account name indeed": "x", N: 1 }],
    moneyColumns: ["N"],
    sheetName: "S",
  });
  const ws = wb.Sheets["S"];
  assert.ok(ws["!freeze"], "the header row must freeze — a statement scrolls");
  assert.ok((ws["!cols"] as { wch: number }[])[0].wch > 20,
    "a long header must not be clipped to the default width");
});

test("moneyCell is exact for the figures this product holds", () => {
  // paise are integers and an IEEE double carries 2^53, so `paise / 100` is
  // exact well past any balance a practice meets. Pinned so nobody "fixes" it
  // into a float round.
  assert.equal(moneyCell(1_18_000_50), 118000.5);
  assert.equal(moneyCell(-150), -1.5);
  assert.equal(moneyCell(1), 0.01);
  assert.equal(moneyCell(null), null);
  assert.equal(moneyCell(undefined), null);
  // PostgREST hands a bigint back as a string.
  assert.equal(moneyCell("123456"), 1234.56);
  assert.equal(moneyCell("not a number"), null);
});
