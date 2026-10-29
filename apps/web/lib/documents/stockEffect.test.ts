import { test } from "node:test";
import assert from "node:assert/strict";
import {
  UNREADABLE_STOCK_EFFECT, bulkStockSentence, issuedMessage, stockEffectProblem, stockEffectSummary,
} from "./stockEffect.ts";

// POST-A-092. The decision the browser makes about `stock_effect` on an issue response, as a decision: absent and recorded say
// nothing, anything else says something, and a payload that cannot be read never reads as fine.

const bad = { recorded: false, goods_lines: 2, moved_lines: 1, journal: "not_posted", problem: "This sales invoice was issued, but the journal was not posted." };

test("a response with no stock_effect says nothing, because stock is not involved", () => {
  for (const data of [{ id: "x" }, { id: "x", stock_effect: null }, { id: "x", stock_effect: undefined }, null, undefined, "issued", 5, []]) {
    assert.equal(stockEffectProblem(data), null, JSON.stringify(data));
  }
});

test("a recorded stock effect says nothing", () => {
  assert.equal(stockEffectProblem({ stock_effect: { recorded: true, problem: null } }), null);
  assert.equal(stockEffectProblem({ stock_effect: { recorded: true, problem: "ignored when recorded" } }), null);
});

test("a stock effect that was not recorded is the server's sentence, trimmed and otherwise untouched", () => {
  assert.equal(stockEffectProblem({ stock_effect: bad }), bad.problem);
  assert.equal(stockEffectProblem({ stock_effect: { ...bad, problem: "  Spaced.  " } }), "Spaced.");
});

test("a present field in the wrong shape reads as a problem and never as silence", () => {
  for (const effect of ["recorded", 1, true, [], {}, { recorded: "yes" }, { recorded: false }, { recorded: false, problem: "" },
    { recorded: false, problem: "   " }, { recorded: false, problem: 7 }, { problem: "x" }]) {
    const got = stockEffectProblem({ stock_effect: effect });
    assert.ok(got !== null, JSON.stringify(effect));
  }
  assert.equal(stockEffectProblem({ stock_effect: {} }), UNREADABLE_STOCK_EFFECT);
  assert.equal(stockEffectProblem({ stock_effect: "recorded" }), UNREADABLE_STOCK_EFFECT);
  assert.equal(stockEffectProblem({ stock_effect: { problem: "x" } }), "x");
});

test("the issued message is a success unless stock was not recorded, and then a warning that carries the sentence", () => {
  assert.deepEqual(issuedMessage("Invoice issued", { id: "x" }), { text: "Invoice issued", type: "success" });
  assert.deepEqual(issuedMessage("Invoice issued", { stock_effect: { recorded: true } }), { text: "Invoice issued", type: "success" });
  const warned = issuedMessage("Invoice issued", { stock_effect: bad });
  assert.equal(warned.type, "warning");
  assert.equal(warned.text, `Invoice issued. ${bad.problem}`);
});

test("a bulk run counts the problems and keeps the first sentence", () => {
  const responses = [{ id: "a" }, { stock_effect: bad }, { stock_effect: { recorded: true } }, { stock_effect: { ...bad, problem: "Second." } }, null];
  assert.deepEqual(stockEffectSummary(responses), { count: 2, first: bad.problem });
  assert.deepEqual(stockEffectSummary([]), { count: 0, first: null });
  assert.deepEqual(stockEffectSummary([{ id: "a" }, { id: "b" }]), { count: 0, first: null });
});

test("the bulk sentence is absent for none, singular for one and counted for several", () => {
  assert.equal(bulkStockSentence({ count: 0, first: null }), null);
  assert.equal(bulkStockSentence({ count: 1, first: "Why." }), "One of them did not record all of its stock effect. For example: Why.");
  assert.equal(bulkStockSentence({ count: 3, first: "Why." }), "3 of them did not record all of their stock effect. For example: Why.");
});
