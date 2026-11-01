// POST-A-368 (item 1) — the list of losses says where each went, from the server's answer, and does no arithmetic of its own.
//
// Run with: node --experimental-strip-types --test lib/tax/lossUses.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { lossUsesOf } from "./lossUses.ts";

const use = (over: Record<string, unknown> = {}) => ({
  filing_id: "f1", financial_year: "2025-26", return_type: "original", amount_paise: 400000, filing_found: true, acknowledgement_number: "ACK-1", ...over,
});
const record = (over: Record<string, unknown> = {}) => ({ id: "L1", hand_recorded_paise: 0, uses: [use()], ...over });

test("a record's uses and hand-recorded part are handed on exactly as the server gave them, a return's entry id being the filing's id when an older server sent none", () => {
  const out = lossUsesOf([record({ hand_recorded_paise: 100000 })]);
  assert.deepEqual(out, { L1: { hand_recorded_paise: 100000, uses: [{ ...use(), entry_id: "f1" }] } });
  const named = lossUsesOf([record({ uses: [use({ entry_id: "e-9" })] })])!.L1.uses[0];
  assert.equal(named.entry_id, "e-9");
});

test("a use recorded by hand keeps its kind and its entry id, and names no return (POST-A-368, item 2)", () => {
  const hand = lossUsesOf([record({ uses: [use({ entry_id: "manual:2024-25", filing_id: "manual:2024-25", return_type: "manual", filing_found: null, acknowledgement_number: null })] })])!.L1.uses[0];
  assert.equal(hand.return_type, "manual");
  assert.equal(hand.entry_id, "manual:2024-25");
  assert.equal(hand.filing_found, null);
  assert.equal(hand.acknowledgement_number, null);
  // an unknown kind is read as an original return, as it always was
  assert.equal(lossUsesOf([record({ uses: [use({ return_type: "updated" })] })])!.L1.uses[0].return_type, "original");
});

test("several records are keyed by their ids, and the order of the uses is the server's", () => {
  const out = lossUsesOf([record(), record({ id: "L2", uses: [use({ filing_id: "b" }), use({ filing_id: "a" })] })]);
  assert.deepEqual(Object.keys(out!), ["L1", "L2"]);
  assert.deepEqual(out!.L2.uses.map((u) => u.filing_id), ["b", "a"]);
});

test("a payload that is not a list is null, which the screen words as could not be read", () => {
  for (const bad of [null, undefined, {}, "x", 3, { data: [] }]) assert.equal(lossUsesOf(bad), null);
});

test("an empty list is a read with nothing in it, not a failure", () => {
  assert.deepEqual(lossUsesOf([]), {});
});

test("a record that does not say what happened to it is left out, not shown as unused", () => {
  const out = lossUsesOf([record({ uses: undefined }), record({ id: "L2", hand_recorded_paise: undefined }), record({ id: "L3", hand_recorded_paise: -1 }), { uses: [] }, "x", null, record({ id: "L4" })]);
  assert.deepEqual(Object.keys(out!), ["L4"]);
});

test("one malformed use makes the whole record unreadable, because showing the rest would understate where the loss went", () => {
  assert.deepEqual(lossUsesOf([record({ uses: [use(), use({ amount_paise: "4000" })] })]), {});
  assert.deepEqual(lossUsesOf([record({ uses: [use(), null] })]), {});
  assert.deepEqual(lossUsesOf([record({ uses: [use({ filing_id: 7 })] })]), {});
});

test("an unreadable list of returns stays unknown: found is null, not false", () => {
  const u = lossUsesOf([record({ uses: [use({ filing_found: null, acknowledgement_number: null })] })])!.L1.uses[0];
  assert.equal(u.filing_found, null);
  assert.equal(u.acknowledgement_number, null);
  assert.equal(lossUsesOf([record({ uses: [use({ filing_found: "yes" })] })])!.L1.uses[0].filing_found, null);
});

test("a return that is gone says so, and a revised return keeps its kind", () => {
  const out = lossUsesOf([record({ uses: [use({ filing_found: false, return_type: "revised", acknowledgement_number: "" })] })])!.L1.uses[0];
  assert.equal(out.filing_found, false);
  assert.equal(out.return_type, "revised");
  assert.equal(out.acknowledgement_number, null);
});
