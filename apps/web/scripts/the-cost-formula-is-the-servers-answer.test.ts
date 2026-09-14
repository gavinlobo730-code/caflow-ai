/**
 * INV-02 — the browser renders the cost formula and decides nothing about it.
 *
 * AS-2 paragraph 14 permits two cost formulas, paragraph 16 makes the choice a
 * property of the enterprise's inventories, paragraph 17 refuses standard
 * cost, and AS-5 paragraph 29/32 govern a change. All of that lives in
 * `apps/api/domain/inventory/costing.py`. A second copy in TypeScript is the
 * shape this repository keeps having to undo — the Schedule III caption list,
 * the tax-audit thresholds, the §192 slab ladder — so it is asserted rather
 * than asked for.
 *
 * COMMENTS ARE STRIPPED BEFORE SCANNING. A guard defeated by the file's own
 * docstring explaining what it must not do is the failure mode this suite has
 * already hit once: the source scan on the sales-cycle service passed because
 * the module NAMED the thing it does not call.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const PANEL = path.join(WEB, "components/inventory/CostFormulaPanel.tsx");
const PAGE = path.join(WEB, "app/clients/[id]/inventory/page.tsx");

function withoutComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .map((l) => l.replace(/(^|\s)\/\/.*$/, "$1"))
    .join("\n");
}

const raw = fs.readFileSync(PANEL, "utf8");
const code = withoutComments(raw);

test("the cost formula is the server's answer", async (t) => {
  await t.test("names neither formula in the browser", () => {
    // The VALUES and the LABELS both come from `policy.methods`. A hardcoded
    // option list is how the Schedule III caption screen came to offer five
    // captions the classifier had never heard of.
    assert.ok(!/["']fifo["']/i.test(code), "a formula value is spelled here");
    assert.ok(!/moving_average/i.test(code), "a formula value is spelled here");
    assert.ok(!/first-in|weighted average/i.test(code),
      "a formula label is spelled here");
  });

  await t.test("renders the method list the server sent", () => {
    assert.match(code, /policy\.methods\.map/);
  });

  await t.test("does not decide whether a change may take effect from a date", () => {
    // No date arithmetic and no comparison against the last movement: the
    // server refuses, with its sentence, against the ledger as it stands at
    // the moment of the change.
    assert.ok(!/new Date\(/.test(code), "the browser is doing date arithmetic");
    assert.ok(!/last_movement\s*[<>]/.test(code),
      "the browser is deciding whether a date is allowed");
    assert.match(code, /earliest_date_a_change_can_take_effect/);
  });

  await t.test("shows the server's refusal rather than one of its own", () => {
    assert.match(code, /res\.error/);
    assert.ok(!/AS-5 paragraph/.test(code), "a statutory sentence is written here");
    assert.ok(!/AS-2 paragraph 1[67]/.test(code), "a statutory sentence is written here");
    assert.match(code, /policy\.standard_cost_refused/);
    assert.match(code, /policy\.as5_disclosure/);
  });

  await t.test("distinguishes WHICH formula is in force from WHETHER anybody chose", () => {
    // A client with nothing recorded is on the weighted average and has not
    // said so. Collapsing the two tells a CA a decision was taken that was not.
    assert.match(code, /policy\.is_recorded/);
    assert.match(code, /policy\.unrecorded_means/);
  });

  await t.test("is mounted where the figures it explains are", () => {
    const page = fs.readFileSync(PAGE, "utf8");
    assert.match(page, /<CostFormulaPanel/);
  });

  await t.test("the comment strip does not make the scan vacuous", () => {
    // If `withoutComments` ever removed everything, every "not present"
    // assertion above would pass for the wrong reason.
    assert.ok(code.length > raw.length / 2, "too much of the file was stripped");
    assert.match(code, /export function CostFormulaPanel/);
  });
});
