// §32 depreciation is computed by the SERVER. Run with:
//   node --experimental-strip-types --test scripts/section-32-is-computed-on-the-server.test.ts
//
// WHY THIS EXISTS
//     IT Act §32 works per BLOCK OF ASSETS, at the block's rate, on the block's
//     written-down value — a different system from the Companies Act
//     Schedule II charge the accounts carry, which is per asset over a useful
//     life. Getting it wrong is not a rounding difference: the second proviso
//     to §32(1) halves a rate, §43(6)(c) has an order the deduction has to be
//     applied in, and §50 turns a collapsed block into a capital gain or loss
//     with no depreciation at all.
//
//     `domain/income_tax/section_32.py` is that computation and the endpoint
//     serves it. This pins that the screen only DISPLAYS it — CLAUDE.md, "zero
//     business logic in the frontend", which is not a style rule where a second
//     copy of a statutory rule would drift from the one that goes in a return.
//
//     It also pins the two things easiest to reintroduce as a convenience: a
//     rate table in the browser (Appendix I, which this product deliberately
//     does not hold at all) and a put-to-use date defaulted to the purchase
//     date (which would allow a full year on an asset entitled to half, or to
//     nothing).
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const PAGE = "app/income-tax/section-32/page.tsx";

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
    .replace(/\/\/.*$/gm, "");
}

test("the screen asks the endpoint and renders what comes back", () => {
  const src = code(PAGE);
  assert.match(src, /\/api\/income-tax\/section-32\?/);
  assert.match(src, /\/api\/income-tax\/section-32\/blocks/);
});

test("no depreciation arithmetic happens in the browser", () => {
  const src = code(PAGE);
  // Every figure the table shows is a *_paise field straight off the response.
  // A multiplication or a division by a rate would be the browser computing
  // depreciation, which is the one thing this page must not do.
  assert.doesNotMatch(src, /rate_percent\s*[/*]/, "a rate is applied here");
  assert.doesNotMatch(src, /[/*]\s*100\b(?!\s*[;)])/,
    "a per-cent or paise conversion crept in — formatPaise is the only one needed");
  assert.doesNotMatch(src, /opening_wdv_paise\s*[+\-]/,
    "the written-down value is rolled forward here, not on the server");
});

test("Appendix I is not mirrored in the browser", () => {
  // The engine holds no rate table either, deliberately: a block IS a rate
  // under §2(11), so the CA who decides the block has decided the rate. A
  // helpful dropdown of "the usual rates" here would be a statutory table
  // written from memory, which CLAUDE.md forbids.
  const src = code(PAGE);
  assert.doesNotMatch(src, /\[\s*5\s*,\s*10\s*,\s*15\b/, "a rate table crept in");
  assert.doesNotMatch(src, /APPENDIX_I|BLOCK_RATES|RATE_TABLE/i);
});

test("the put-to-use date is never defaulted to the purchase date", () => {
  const correction = code("lib/fixedAssets/correction.ts");
  assert.doesNotMatch(correction, /put_to_use_date\s*[:=]\s*[^;\n]*purchase_date/,
    "the second proviso to §32(1) turns on put-to-use; substituting the "
    + "purchase date would allow a full year on an asset entitled to half");
});

test("the incompleteness is shown, not just the total", () => {
  // An incomplete §32 computation looks exactly like a complete one if the
  // total is all you show — and the total is what goes in a return.
  const src = code(PAGE);
  assert.match(src, /is_complete/);
  assert.match(src, /statutory_gaps/);
  assert.match(src, /unclassified_assets/);
});

test("the §50 figure is not presented as part of the allowance", () => {
  // It is a capital gain or loss and belongs in the capital-gains schedule;
  // §74 does not let a capital loss relieve business income anyway.
  const src = code(PAGE);
  assert.match(src, /short_term_capital_gain_paise/);
  assert.doesNotMatch(src, /allowance_paise\s*[+\-]\s*\w*short_term/);
});
