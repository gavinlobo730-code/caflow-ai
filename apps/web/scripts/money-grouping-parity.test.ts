/**
 * THE BROWSER AND THE BACKEND GROUP A RUPEE FIGURE THE SAME WAY.
 *
 * ── WHY THIS PAIR EXISTS ────────────────────────────────────────────────────
 * Indian grouping (decision D6) has two implementations and neither language
 * can read the other's. `apps/api/domain/money_text.py` serves every PDF,
 * email, 422 and log line; `lib/money/format.ts` serves every screen. A CA
 * reads BOTH on one page — `components/payroll/MonthlyReview.tsx` renders
 * `formatPaise` on a figure and the server's own sentence beside it — so a
 * disagreement is visible at a glance.
 *
 * And it WAS one. Until 24 September 2026 the backend used Python's own
 * thousands separator at 85 sites, so the sentence read 123,456.78 where the
 * column beside it read 1,23,456.78. Ten of those sites also inverted a
 * negative, because `//` floors and `%` follows it: -1 paise printed "-1.99".
 *
 * ── WHAT IS PINNED, AND WHAT IS DELIBERATELY NOT ────────────────────────────
 * The GROUPING is pinned, on `shared/money-grouping-vectors.json`, which both
 * suites read. The UNIT is not: a PDF writes "Rs." because ReportLab's core
 * fonts carry no U+20B9 glyph, a screen writes the sign, so neither side's
 * grouping function emits one.
 *
 * `whole_rupees` is NOT pinned to `formatWhole` and that is a decision, not an
 * omission — the fixture says why. Python truncates toward zero because the
 * year-end statements present in whole rupees; the browser falls back to
 * showing paise so an unrounded row stands out on a return-prep screen.
 * Harmonising them is the tempting mistake.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { formatPaiseBare, formatWhole, NO_FIGURE } from "../lib/money/format.ts";

const FIXTURE = JSON.parse(
  readFileSync("../../shared/money-grouping-vectors.json", "utf8"),
) as { vectors: { paise: number; grouped: string; note: string }[] };

test("every vector groups the way the backend groups it", () => {
  for (const v of FIXTURE.vectors) {
    assert.equal(
      formatPaiseBare(v.paise), v.grouped,
      `${v.paise} paise — ${v.note}\n  ` +
      "apps/api/domain/money_text.rupees_paise answers the expected value. " +
      "Two implementations of one rule have drifted; fix the one that is " +
      "wrong, do not edit the fixture to match it.",
    );
  }
});

test("the fixture still carries the cases that matter", () => {
  // A fixture quietly emptied of its hard cases passes for ever. These three
  // are the ones the sweep was about: the first figure where the two
  // conventions diverge, a crore, and a negative that is not a whole rupee.
  const seen = new Set(FIXTURE.vectors.map((v) => v.paise));
  assert.ok(FIXTURE.vectors.length >= 15, `only ${FIXTURE.vectors.length} vectors`);
  for (const must of [10000000, 1000000000, -150]) {
    assert.ok(seen.has(must), `the ${must}-paise vector has gone`);
  }
});

test("the two conventions really do differ, above a lakh", () => {
  // The premise. If en-IN and the default grouping agreed there would be no
  // defect and this whole pair would be noise.
  assert.equal(formatPaiseBare(10000000), "1,00,000.00");
  assert.equal((100000).toLocaleString("en-US", { minimumFractionDigits: 2 }),
    "100,000.00");
});

test("nothing is not zero, on this side", () => {
  // The one place the two languages deliberately differ, asserted here rather
  // than as a shared vector: a table cell with no figure is not a cell reading
  // zero, while a PDF built from a row whose column is NULL must not fail.
  assert.equal(formatPaiseBare(null), NO_FIGURE);
  assert.equal(formatPaiseBare(undefined), NO_FIGURE);
  assert.equal(formatPaiseBare(0), "0.00");
});

test("formatWhole is the browser's own rule and is not the backend's", () => {
  // Pinned so the divergence is deliberate rather than discovered. An exact
  // rupee renders whole; a figure carrying paise keeps them, where
  // domain.money_text.whole_rupees would truncate.
  // 10,000,000 paise is ONE LAKH rupees, not ten. Getting that wrong while
  // writing this test is the argument for the vectors carrying their own note.
  assert.equal(formatWhole(10000000), "₹1,00,000");
  assert.match(formatWhole(10000050), /50/,
    "formatWhole must keep the paise it was given — rounding here would be a " +
    "second implementation of CGST s.170 living in a browser");
});
