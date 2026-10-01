// ACC-08 — the balancing leg and Enter-finishes-a-line, as pure functions.
//
// Run with: node --experimental-strip-types --test lib/journal/lineFlow.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { afterEnter, balancingLeg, isAmountless } from "./lineFlow.ts";

const L = (debit = "", credit = "") => ({ debit, credit });

test("Dr 1,000 and Cr 600 pre-fills Cr 400 on the third line", () => {
  // The item's own example, in the form the editor holds a line.
  const leg = balancingLeg([L("1000"), L("", "600")]);
  assert.deepEqual(leg, { side: "credit", amount: "400.00" });
});

test("a credit-heavy entry is offered a DEBIT", () => {
  assert.deepEqual(balancingLeg([L("250.50"), L("", "1000")]),
    { side: "debit", amount: "749.50" });
});

test("a balanced entry is offered nothing", () => {
  assert.equal(balancingLeg([L("1000"), L("", "1000")]), null);
  assert.equal(balancingLeg([L(), L()]), null, "two blank lines are balanced at nil");
});

test("a cell that is not an amount means no figure is guessed", () => {
  // The editor already flags the cell; offering a balancing figure built on
  // text that does not parse would be a guess about what the CA meant.
  assert.equal(balancingLeg([L("12abc"), L("", "600")]), null);
  assert.equal(balancingLeg([L("1,25,000"), L("", "600")]), null,
    "the amount parser refuses grouped input, and so does this");
});

test("the leg is exact in paise, never a float", () => {
  // 0.1 + 0.2 is the classic; the leg must be 0.30 to the paisa.
  assert.deepEqual(balancingLeg([L("0.10"), L("0.20"), L("", "0.00")]),
    { side: "credit", amount: "0.30" });
  assert.deepEqual(balancingLeg([L("1234567.89"), L("", "0.01")]),
    { side: "credit", amount: "1234567.88" });
});

test("excluding a line sums the others — the blank one the leg is offered TO", () => {
  const lines = [L("1000"), L("", "600"), L()];
  assert.deepEqual(balancingLeg(lines, 2), { side: "credit", amount: "400.00" });
  // Excluding the line that carries the credit changes the answer, which is the
  // reason the argument exists.
  assert.deepEqual(balancingLeg(lines, 1), { side: "credit", amount: "1000.00" });
});

test("a line is amountless only when neither side has a figure", () => {
  assert.equal(isAmountless(L()), true);
  assert.equal(isAmountless(L("0.00", "")), true);
  assert.equal(isAmountless(L("5")), false);
  assert.equal(isAmountless(L("", "5")), false);
  // An unparseable cell is NOT amountless: it is something the CA typed.
  assert.equal(isAmountless(L("abc")), false);
});

test("Enter moves to the next line, and on the last adds one only while unbalanced", () => {
  assert.deepEqual(afterEnter(0, 3, false), { kind: "focus", row: 1 });
  assert.deepEqual(afterEnter(1, 3, true), { kind: "focus", row: 2 });
  assert.deepEqual(afterEnter(2, 3, false), { kind: "add" });
  assert.deepEqual(afterEnter(2, 3, true), { kind: "stay" });
  assert.deepEqual(afterEnter(1, 2, false), { kind: "add" });
});
