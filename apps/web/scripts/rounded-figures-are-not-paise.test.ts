/**
 * The Schedule III para 4 rounded figures are in WHOLE UNITS, not paise.
 *
 * The statements page carries two formatters that look almost identical and
 * differ in exactly one way: fmt() divides by 100 because it is handed paise,
 * fmtUnit() does not because it is handed figures the backend has already
 * rounded to hundreds, thousands, lakhs, millions or crores.
 *
 * Using the wrong one restates every figure on the page by two orders of
 * magnitude, and it does so silently — the columns still foot, the balance
 * sheet still balances, and only the magnitude is wrong. That is the kind of
 * error a CA notices after signing, so it is pinned here.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const PAGE = join(
  import.meta.dirname,
  "..",
  "app/clients/[id]/year-end/[engagementId]/financial-statements/_page.tsx",
);

function body(source: string, fn: string): string {
  const start = source.indexOf(`function ${fn}(`);
  assert.notEqual(start, -1, `${fn} not found — was it renamed?`);
  const next = source.indexOf("\nfunction ", start + 1);
  return source.slice(start, next === -1 ? source.length : next);
}

test("fmtUnit never divides — its input is already in whole units", () => {
  const src = readFileSync(PAGE, "utf8");
  const fn = body(src, "fmtUnit");
  assert.ok(
    !/\/\s*100\b/.test(fn),
    "fmtUnit divides by 100; it is handed rounded units, not paise, so this " +
      "would restate every figure on the statement by a factor of a hundred",
  );
  assert.ok(
    /maximumFractionDigits:\s*0/.test(fn),
    "a figure rounded to the nearest lakh has no decimals to show",
  );
});

test("fmt still divides — its input really is paise", () => {
  const src = readFileSync(PAGE, "utf8");
  assert.ok(
    /\/\s*100\b/.test(body(src, "fmt")),
    "fmt stopped converting paise to rupees; the pre-rounding fallback path " +
      "and every other caller depend on it",
  );
});

test("the statement components format through the injected formatter", () => {
  // Para 4's proviso requires the unit to be used uniformly across the
  // financial statements. A component reaching for fmt() directly would
  // render its rows in rupees inside a table headed "₹ in lakhs".
  const src = readFileSync(PAGE, "utf8");
  const componentsStart = src.indexOf("function BalanceSheetView(");
  assert.notEqual(componentsStart, -1);
  const components = src.slice(componentsStart);
  const strays = components.match(/\{fmt\(/g) ?? [];
  assert.deepEqual(
    strays,
    [],
    `${strays.length} component(s) call fmt() directly instead of the money ` +
      "prop, so they would ignore the chosen rounding unit",
  );
});
