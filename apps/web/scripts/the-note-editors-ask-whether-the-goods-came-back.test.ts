// The credit-note and debit-note editors ask whether the goods came back (POST-A-371, migration 581). Run with:
//   node --experimental-strip-types --test scripts/the-note-editors-ask-whether-the-goods-came-back.test.ts
//
// WHY THIS EXISTS
//     A section 34 note is also how a price, a rate or a discount is corrected, and every goods line on a note used to move stock and cost
//     whatever the note was for. The answer is now stored on the note and the SERVER obeys it, refusing to issue a note that names goods and
//     has not said. The browser's whole part is to ask, to send what was answered, and to show what is stored. This holds those three
//     things, and holds the browser to asking only: it decides nothing about stock.
//
// WHAT IS ASSERTED
//     1. Both editors render the shared control, and only for a note that NAMES goods (a line whose catalogue item is a good).
//     2. Both editors send `goods_returned` on the create AND on the edit of a draft, and only the answer that was given (never a default
//        of their own: an unanswered question is sent as nothing, so the server's refusal at issue is what the CA meets).
//     3. A copy of a note does not copy its answer.
//     4. The detail drawers show the stored answer, with "Not stated" as a real third state.
//     5. The control holds no stock rule: no quantity, cost or rate arithmetic and no call.
//
//     Each assertion is preceded by a check that the file was read, because a pattern matching nothing passes everything after it.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { goodsReturnedWords } from "../lib/inventory/goodsReturned.ts";

const root = path.resolve(import.meta.dirname, "..");
const read = (rel: string) => fs.readFileSync(path.join(root, rel), "utf8");

const EDITORS = {
  "components/sales/SalesCreditNoteEditor.tsx": "credit_note",
  "components/purchases/DebitNoteEditor.tsx": "debit_note",
} as const;
const DRAWERS = ["components/sales/SalesCreditNoteViewDrawer.tsx", "components/purchases/DebitNoteViewDrawer.tsx"];

test("the stored answer reads in words, and 'not stated' is its own state", () => {
  assert.equal(goodsReturnedWords(true), "Yes");
  assert.match(goodsReturnedWords(false), /^No \(/);
  assert.equal(goodsReturnedWords(null), "Not stated");
  assert.equal(goodsReturnedWords(undefined), "Not stated");
});

for (const [file, kind] of Object.entries(EDITORS)) {
  test(`${file} asks the question only of a note that names goods`, () => {
    const src = read(file);
    assert.ok(src.length > 2000, "the editor was read");
    assert.match(src, /import \{ GoodsReturnedChoice \} from "@\/components\/inventory\/GoodsReturnedChoice"/);
    assert.match(src, /import type \{ GoodsReturned \} from "@\/lib\/inventory\/goodsReturned"/);
    assert.match(src, /const namesGoods = lines\.some\(\(l\) => l\.product\?\.kind === "good"\)/, "a line's item says whether the note names goods");
    assert.ok(src.includes(`{namesGoods && (`), "the control is rendered only for such a note");
    assert.ok(src.includes(`<GoodsReturnedChoice kind="${kind}"`), `the control says it is for a ${kind}`);
  });

  test(`${file} sends the answer on create and on edit, and nothing it was not given`, () => {
    const src = read(file);
    assert.equal((src.match(/goods_returned: goodsAnswer,/g) ?? []).length, 2, "once in the POST body and once in the PATCH body of a draft");
    assert.match(src, /const goodsAnswer = namesGoods && goodsReturned !== null \? goodsReturned : undefined;/,
      "an unanswered question is sent as nothing, so the server's refusal at issue is what the CA meets, and no default is invented here");
    assert.match(src, /useState<GoodsReturned>\(existing\?\.goods_returned \?\? null\)/);
    assert.ok(!/useState<GoodsReturned>\([^)]*duplicateSeed/.test(src), "a copy of a note does not copy its answer");
    assert.ok(src.includes("if (!(isEdit && existing?.id) && !isCopy) return;"), "a copied note has its items looked up too, or the question is never asked of it");
    assert.ok(src.includes("[isEdit, existing?.id, clientId, isCopy]"));
    assert.ok(/goodsReturned,\s*notes,/.test(src), "the answer is part of what makes the form dirty");
  });
}

test("the detail drawers show the stored answer", () => {
  for (const file of DRAWERS) {
    const src = read(file);
    assert.ok(src.length > 2000, "the drawer was read");
    assert.match(src, /\w+\.goods_returned != null && <DetailRow label="Goods returned" value=\{goodsReturnedWords\(\w+\.goods_returned\)\} \/>/,
      `${file}: shown only when an answer was given, because a service-only note has none and "Not stated" there reads like a missing answer`);
  }
});

test("the control only asks: it holds no stock rule", () => {
  const src = read("components/inventory/GoodsReturnedChoice.tsx");
  assert.ok(src.includes("only asks the question"));
  const code = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
  // identifiers and calls, not words: the visible text legitimately says "price, rate or discount"
  for (const forbidden of [/\bquantity\b/, /_paise\b/, /\bgst_rate\w*/, /\bunit_cost\w*/, /fetch\(|apiCall\(|supabase/i, /Math\./]) {
    assert.ok(!forbidden.test(code), `the control must not contain ${forbidden}`);
  }
  // both answers are offered, and neither is pre-selected
  assert.equal((code.match(/type="radio"/g) ?? []).length, 2);
  assert.ok(code.includes("checked={value === true}") && code.includes("checked={value === false}"));
});
