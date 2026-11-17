// POST-A-075 — the unforeseen-income panel's box for the year's total income. Blank is "not given" (the server then offers no
// surcharge and says so), never ₹0; text that is not an amount is a problem in words, never a figure.
//
// Run with:
//   node --experimental-strip-types --test lib/tax/unforeseenTotalIncome.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { offerSequence, readTotalIncome } from "./unforeseenTotalIncome.ts";

test("a blank box is not given, not nil", () => {
  assert.deepEqual(readTotalIncome(""), { kind: "absent" });
  assert.deepEqual(readTotalIncome("   "), { kind: "absent" });
});

test("an amount is read by the one parser, to the paise", () => {
  assert.deepEqual(readTotalIncome("12500000"), { kind: "amount", paise: 1_250_000_000 });
  assert.deepEqual(readTotalIncome("12500000.5"), { kind: "amount", paise: 1_250_000_050 });
  assert.deepEqual(readTotalIncome("0"), { kind: "amount", paise: 0 });
});

for (const text of ["1e7", "12abc", "1,25,00,000", ".", "1.234"]) {
  test(`text that is not an amount is a problem, not a figure (${JSON.stringify(text)})`, () => {
    const r = readTotalIncome(text);
    assert.equal(r.kind, "problem");
  });
}

test("a total below zero is refused in words", () => {
  const r = readTotalIncome("-5");
  assert.equal(r.kind, "problem");
  assert.match((r as { message: string }).message, /below zero/);
});


// An independent review (17-11-2026): the box stayed editable while an offer was in flight and the late answer was applied anyway, so
// the offer could show a surcharge computed for a total the person had already changed.
test("only the latest offer's answer is current, and editing the total supersedes every offer in flight", () => {
  const seq = offerSequence();
  const first = seq.next();
  assert.equal(seq.isCurrent(first), true);
  const second = seq.next();
  assert.equal(seq.isCurrent(first), false, "an older offer's answer is not applied over a newer one");
  assert.equal(seq.isCurrent(second), true);
  seq.supersede();
  assert.equal(seq.isCurrent(second), false, "an answer for a total the person has since changed is dropped");
  assert.equal(seq.isCurrent(seq.next()), true);
});

test("the panel takes a ticket per offer, drops a superseded answer, and supersedes on every edit of the total", () => {
  const here = path.dirname(fileURLToPath(import.meta.url));
  const panel = fs.readFileSync(path.join(here, "..", "..", "components", "tax", "UnforeseenIncomePanel.tsx"), "utf8");
  const offer = panel.slice(panel.indexOf("async function offer()"), panel.indexOf("function include("));
  assert.match(offer, /const ticket = offers\.current\.next\(\);/);
  const call = offer.indexOf("await listUnforeseenIncomeCandidates(");
  const guard = offer.indexOf("if (!offers.current.isCurrent(ticket)) return;");
  assert.ok(call > 0 && guard > call && guard < offer.indexOf("setCandidates("), "the answer is applied before it is checked to be current");
  assert.match(offer, /catch \(e\) \{\s*if \(!offers\.current\.isCurrent\(ticket\)\) return;/);
  assert.match(offer, /finally \{\s*if \(offers\.current\.isCurrent\(ticket\)\) setBusy\(false\);/);
  assert.match(panel, /id="unforeseen-total-income"\s*onChange=\{e => \{ offers\.current\.supersede\(\);/);
});
