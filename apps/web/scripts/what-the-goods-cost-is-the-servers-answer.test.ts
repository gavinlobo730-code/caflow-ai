/**
 * INV-05 — the browser renders the landed-cost split and decides none of it.
 *
 * AS-2 paragraph 6 puts freight inwards and other expenditure directly
 * attributable to the acquisition in the cost of purchase; it does NOT say how
 * one freight bill is split across the lines it covered, which is why the basis
 * is an accounting policy and why `domain/inventory/landed_cost.py` holds the
 * two bases, their labels, the default, the split and every refusal.
 *
 * The particular failure this guards against is a share computed here. A
 * preview the browser worked out is not a preview of what the receipt will
 * post: the receipt runs `apportion_many` against the goods lines, applies
 * largest-remainder so the parts sum to the charge exactly, and a second
 * implementation in TypeScript would disagree in the paise — on the figure the
 * stock is carried at.
 *
 * COMMENTS ARE STRIPPED BEFORE SCANNING, because a guard defeated by the
 * file's own docstring explaining what it must not do is a failure mode this
 * suite has already hit.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const PANEL = path.join(WEB, "components/purchases/LandedCostPanel.tsx");
const PAGE = path.join(WEB, "app/clients/[id]/purchases/page.tsx");

function withoutComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
    .split("\n")
    .map((l) => l.replace(/(^|\s)\/\/.*$/, "$1"))
    .join("\n");
}

const raw = fs.readFileSync(PANEL, "utf8");
const code = withoutComments(raw);

test("what the goods cost is the server's answer", async (t) => {
  await t.test("does not name a basis or its label", () => {
    // Both the values and the labels come from `data.bases`, the same list the
    // domain module offers the refusal from. A hardcoded pair is how the
    // Schedule III caption screen came to offer five captions the classifier
    // had never heard of.
    assert.ok(!/["']quantity["']/i.test(code), "a basis value is spelled here");
    assert.ok(!/by value|by quantity/i.test(code), "a basis label is spelled here");
    assert.match(code, /data\.bases\.map/);
    assert.match(code, /data\.basis_label/);
  });

  await t.test("computes no share", () => {
    // The split is the server's. Anything that looks like apportionment
    // arithmetic here is a second implementation of largest remainder.
    assert.ok(!/landed_cost_paise\s*=/.test(code), "a share is being assigned here");
    assert.ok(!/reduce\(/.test(code), "the browser is totalling the split");
    assert.ok(!/\/\s*total_paise|total_paise\s*\*/.test(code),
      "the browser is pro-rating");
    assert.match(code, /l\.landed_cost_paise/);
    assert.match(code, /l\.total_cost_paise/);
  });

  await t.test("shows the server's refusals and notes rather than its own", () => {
    assert.match(code, /data\.weight_and_volume_refused/);
    assert.match(code, /data\.freight_outward_is_not_cost/);
    assert.match(code, /c\.why_not_in_cost/);
    assert.match(code, /res\.error/);
    // The statutory sentences live in the domain module. AS-2 is NAMED as a
    // caption here and nothing more — no paragraph is quoted.
    assert.ok(!/paragraph 6|directly attributable/i.test(code),
      "a statutory sentence is written here");
  });

  await t.test("keeps GAPS apart from NOTES", () => {
    // Gaps are actionable — nobody can yet tell. Notes are settled. The RCM
    // panel makes the same distinction for the same reason.
    // THE RULE, NOT A SPELLING OF IT. This asserted `data.gaps.map`, which broke on
  // 18 Sep when the panel moved to `<GapList>` — a change that renders the
  // same sentences and does not break the rule. Sixth time in this repo;
  // CLAUDE.md records the other five. What matters is that the array
  // REACHES a renderer, however it is spelled.
    assert.match(code, /\bgaps=\{data\.gaps\}|data\.gaps\.map/);
    assert.match(code, /data\.notes\.map/);
  });

  await t.test("parses a typed amount through the one money parser", () => {
    assert.match(code, /paiseFromRupeeInput/);
    assert.ok(!/parseFloat|\*\s*100\b/.test(code),
      "a typed rupee amount is being coerced rather than parsed");
  });

  await t.test("cannot delete a charge already in the cost of the stock", () => {
    // The server refuses it too — this is the screen not inviting the click.
    assert.match(code, /c\.is_applied\s*\?/);
  });

  await t.test("is mounted where the bill it explains is", () => {
    const page = fs.readFileSync(PAGE, "utf8");
    assert.match(page, /<LandedCostPanel[\s/>]/);
  });

  await t.test("the comment strip does not make the scan vacuous", () => {
    assert.ok(code.length > raw.length / 2, "too much of the file was stripped");
    assert.match(code, /export function LandedCostPanel/);
  });
});
