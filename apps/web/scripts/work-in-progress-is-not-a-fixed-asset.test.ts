/**
 * FA-11a — the CWIP tab renders the two Schedule III schedules and decides
 * none of them.
 *
 * The bands, their labels, the two rows, which projects reach the completion
 * schedule and why, and the sentence saying capital work-in-progress is not
 * depreciated all live in `apps/api/domain/fixed_assets/cwip.py`. A copy here
 * is the shape this repository keeps having to undo — the Schedule III caption
 * list, the tax-audit thresholds, the §192 slab ladder — so it is asserted
 * rather than asked for.
 *
 * Two of the assertions are about statutory edges specifically:
 *
 *   The BAND BOUNDARY. Exactly one year falls in the SECOND band, because
 *   "less than 1 year" means less than. A browser doing its own date
 *   arithmetic would be one off-by-one from a wrong disclosure.
 *
 *   The MISSING BAND. A reportable project whose expected completion date
 *   nobody recorded renders as a gap, never as "more than 3 years". A row put
 *   in the longest band because nobody said otherwise states something false.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const TAB = path.join(WEB, "components/fixed-assets/CwipTab.tsx");
const PAGE = path.join(WEB, "app/clients/[id]/fixed-assets/page.tsx");

function withoutComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
    .split("\n")
    .map((l) => l.replace(/(^|\s)\/\/.*$/, "$1"))
    .join("\n");
}

const raw = fs.readFileSync(TAB, "utf8");
const code = withoutComments(raw);

test("work in progress is not a fixed asset", async (t) => {
  await t.test("names no band and no band label", () => {
    for (const p of [/less_than_1_year/, /more_than_3_years/,
                     /Less than 1 year/, /More than 3 years/, /1-2 years/]) {
      assert.ok(!p.test(code), `${p} is spelled in the browser`);
    }
    assert.match(code, /ag\.bucket_order\.map/);
    assert.match(code, /ag\.bucket_labels\[/);
  });

  await t.test("names neither row of the ageing schedule", () => {
    assert.ok(!/Projects in progress/.test(code));
    assert.ok(!/temporarily suspended/i.test(code));
    assert.match(code, /ag\.row_order\.map/);
    assert.match(code, /ag\.row_labels\[/);
  });

  await t.test("does no date arithmetic", () => {
    // Which band an amount falls in is a statutory boundary the server owns.
    assert.ok(!/new Date\(/.test(code), "the browser is bucketing by date");
    assert.ok(!/getFullYear|getTime\(\)/.test(code));
  });

  await t.test("the total that must tie to the balance sheet is the server's", () => {
    // The row and column sub-totals are cosmetic; the GRAND total has to
    // reconcile with the capital work-in-progress figure on the balance
    // sheet, so it comes off the wire rather than being re-added here.
    assert.match(code, /ag\.total_paise/);
  });

  await t.test("does not decide whether a project is overdue or over budget", () => {
    assert.ok(!/approved_completion_date\s*[<>]/.test(code));
    assert.ok(!/incurred_paise\s*[<>]/.test(code),
      "the over-budget test is the server's `over_approved_cost`");
    assert.match(code, /p\.over_approved_cost/);
    assert.match(code, /r\.reason/);
  });

  await t.test("an unrecorded approval reads as unrecorded, not as compliant", () => {
    assert.match(code, /approved_cost_paise === null/);
    assert.match(code, /Not recorded/);
  });

  await t.test("a reportable project with no expected date is not bucketed", () => {
    assert.match(code, /r\.bucket \?/);
    assert.match(code, /Not stated/);
  });

  await t.test("renders the server's caveat about depreciation", () => {
    assert.match(code, /does_not_depreciate/);
    assert.ok(!/AS-10/.test(code), "a statutory sentence is written here");
    assert.ok(!/available for use/.test(code), "a statutory sentence is written here");
  });

  await t.test("keeps GAPS apart from NOTES", () => {
    assert.match(code, /cs\.gaps\.map/);
    assert.match(code, /ag\.notes\.map/);
  });

  await t.test("parses typed amounts through the one money parser", () => {
    assert.match(code, /paiseFromRupeeInput/);
    assert.ok(!/parseFloat|\*\s*100\b/.test(code));
  });

  await t.test("is mounted on the fixed-assets screen, as its own tab", () => {
    const page = withoutComments(fs.readFileSync(PAGE, "utf8"));
    assert.match(page, /<CwipTab[\s/>]/);
    // Its own tab, not folded into the register: Schedule III presents it on
    // its own line and it carries no depreciation.
    assert.match(page, /id: "cwip"/);
  });

  await t.test("the comment strip does not make the scan vacuous", () => {
    assert.ok(code.length > raw.length / 2, "too much of the file was stripped");
    assert.match(code, /export function CwipTab/);
  });
});
