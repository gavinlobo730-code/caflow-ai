// Splitting one bank line across several ledgers — the arithmetic. Run with:
//   node --experimental-strip-types --test lib/banking/splitLegs.test.ts
//
// CLAUDE.md: every financial calculation has a unit test. The calculation here
// is small and the whole of it is one rule — the legs sum EXACTLY to what the
// bank moved — so what these tests really pin is the ways that rule can be
// satisfied by accident: a blank row counted as zero, a negative leg making the
// total come out right, a float turning ₹1,00,000 into 9999999.999999 paise.
import test from "node:test";
import assert from "node:assert/strict";
import {
  rupeesToPaise, filledLegs, unallocatedPaise, splitBlock, takeTheRestPaise,
  type SplitLeg,
} from "./splitLegs.ts";

const leg = (account_id: string, amount: string, key = account_id + amount): SplitLeg =>
  ({ key, account_id, amount, narration: "" });

// ── rupees → paise ───────────────────────────────────────────────────────────

test("rupeesToPaise: whole and fractional rupees are exact paise", () => {
  assert.equal(rupeesToPaise("400"), 40_000);
  assert.equal(rupeesToPaise("2200.50"), 220_050);
  assert.equal(rupeesToPaise("0.01"), 1);
});

test("rupeesToPaise: an Indian-formatted amount pasted in still works", () => {
  assert.equal(rupeesToPaise("1,00,000"), 10_000_000);
  assert.equal(rupeesToPaise(" 47,200.00 "), 4_720_000);
});

test("rupeesToPaise: empty and nonsense are 0, not NaN", () => {
  // NaN would propagate into the total and make "unallocated" unprintable —
  // and `NaN === 0` is false, so Save would be dead with nothing explaining it.
  for (const v of ["", "   ", "abc", "-"]) {
    assert.equal(rupeesToPaise(v), 0, `rupeesToPaise(${JSON.stringify(v)})`);
  }
});

test("rupeesToPaise: the float that would otherwise lose a paisa", () => {
  // 1234.56 * 100 is 123455.99999999999 in IEEE-754. Truncating it loses a
  // paisa, and a lost paisa is a split that will not tie.
  assert.equal(rupeesToPaise("1234.56"), 123_456);
  assert.equal(rupeesToPaise("8.29"), 829);
  assert.equal(rupeesToPaise("70.07"), 7007);
});

// ── which legs count ─────────────────────────────────────────────────────────

test("a blank trailing row is an invitation, not a leg", () => {
  const legs = [leg("acc-rent", "400"), leg("acc-maint", "72"), leg("", "")];
  assert.equal(filledLegs(legs).length, 2);
  assert.equal(unallocatedPaise(filledLegs(legs), 47_200), 0);
});

test("a half-filled row DOES count — it is a mistake, not an invitation", () => {
  // An amount with no ledger must block, not be quietly dropped: dropping it
  // would make the remaining legs tie and post money to nowhere the CA named.
  const legs = [leg("acc-rent", "400"), leg("acc-maint", "72"), leg("", "50")];
  assert.equal(filledLegs(legs).length, 3);
  assert.deepEqual(splitBlock(legs, 47_200), { code: "no-ledger" });
});

// ── the invariant ────────────────────────────────────────────────────────────

test("the worked example: ₹47,200 as rent + maintenance + parking", () => {
  const legs = [leg("acc-rent", "400"), leg("acc-maint", "50"), leg("acc-park", "22")];
  assert.equal(unallocatedPaise(legs, 47_200), 0);
  assert.equal(splitBlock(legs, 47_200), null);
});

test("short by a real figure, and the figure is the one to show", () => {
  const legs = [leg("acc-rent", "400"), leg("acc-maint", "50")];
  assert.deepEqual(splitBlock(legs, 47_200), { code: "short", paise: 2_200 });
});

test("over-allocated is reported as over, not as a negative shortfall", () => {
  const legs = [leg("acc-rent", "400"), leg("acc-maint", "100")];
  assert.deepEqual(splitBlock(legs, 47_200), { code: "over", paise: 2_800 });
});

test("a negative leg cannot buy a correct total", () => {
  // 600 - 128 = 472. The sum is right and the entry would be wrong: every split
  // moves the same way as the bank line, so a leg going the other way is a
  // different transaction entirely.
  const legs = [leg("acc-rent", "600"), leg("acc-maint", "-128")];
  assert.equal(unallocatedPaise(legs, 47_200), 0, "the total does tie — that is the trap");
  assert.deepEqual(splitBlock(legs, 47_200), { code: "non-positive" });
});

test("a zero leg is refused too", () => {
  const legs = [leg("acc-rent", "472"), leg("acc-maint", "0")];
  assert.deepEqual(splitBlock(legs, 47_200), { code: "non-positive" });
});

test("one leg is not a split", () => {
  assert.deepEqual(splitBlock([leg("acc-rent", "472")], 47_200), { code: "too-few" });
  assert.deepEqual(splitBlock([], 47_200), { code: "too-few" });
});

test("a line with no amount cannot be split at all", () => {
  assert.deepEqual(splitBlock([leg("a", "1"), leg("b", "1")], 0), { code: "no-amount" });
});

test("the most basic problem is reported first", () => {
  // A row with no ledger AND a total that is short must say "needs a ledger".
  // Quoting an unallocated figure computed from a row the reader has not
  // finished sends them to correct the wrong thing.
  const legs = [leg("acc-rent", "400"), leg("", "50")];
  assert.deepEqual(splitBlock(legs, 47_200), { code: "no-ledger" });
});

// ── take the rest ────────────────────────────────────────────────────────────

test("take the rest gives the last leg exactly what closes the gap", () => {
  const legs = [leg("acc-rent", "400"), leg("acc-maint", "50"), leg("acc-park", "")];
  const rest = takeTheRestPaise(legs, legs[2].key, 47_200);
  assert.equal(rest, 2_200);
  const closed = [legs[0], legs[1], leg("acc-park", String(rest! / 100), legs[2].key)];
  assert.equal(splitBlock(closed, 47_200), null);
});

test("take the rest replaces what that leg already had, rather than adding to it", () => {
  // Otherwise pressing it twice over-allocates, which is the obvious way to
  // misuse a button labelled "take the rest".
  const legs = [leg("acc-rent", "400"), leg("acc-maint", "50"), leg("acc-park", "22")];
  assert.equal(takeTheRestPaise(legs, legs[2].key, 47_200), 2_200);
});

test("take the rest declines when there is nothing left", () => {
  const legs = [leg("acc-rent", "400"), leg("acc-maint", "72"), leg("acc-park", "")];
  assert.equal(takeTheRestPaise(legs, legs[2].key, 47_200), null);
});
