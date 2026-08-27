// The pattern a rule made from a bulk coding would carry. Run with:
//   node --experimental-strip-types --test lib/banking/narrationPattern.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { commonNarrationPattern, MIN_PATTERN_LENGTH } from "./narrationPattern.ts";

test("it finds the run every line shares", () => {
  // The real case this was built for: a CA selects the bank's charge lines and
  // codes them all to Bank Charges. "GST @9% ON BANK CHARGES" is common to
  // both — "GST" sits inside CGST and SGST, which a substring matcher is
  // perfectly happy with, and rule_matches is a substring matcher.
  const p = commonNarrationPattern([
    "CGST @9% ON BANK CHARGES",
    "SGST @9% ON BANK CHARGES",
  ]);
  assert.equal(p, "GST @9% ON BANK CHARGES");
});

test("it narrows to what ALL of them share, not what most do", () => {
  const p = commonNarrationPattern([
    "CGST @9% ON BANK CHARGES",
    "SGST @9% ON BANK CHARGES",
    "NEFT CHARGES APR2026",
  ]);
  assert.equal(p, "CHARGES");
});

test("the pattern it returns actually matches every line it was given", () => {
  // The property that matters, stated as the server states it: rule_matches
  // does `pattern.lower() in narration.lower()`. A pattern that does not
  // satisfy this for every line is a rule that silently misses lines the CA
  // watched it being built from.
  const cases = [
    ["UPI/RAMESH KUMAR/9812", "UPI/RAMESH KUMAR/4471"],
    ["ATM WDL MUMBAI 12", "ATM WDL PUNE 44"],
    ["SALARY APR2026", "SALARY MAY2026", "SALARY JUN2026"],
  ];
  for (const lines of cases) {
    const p = commonNarrationPattern(lines);
    assert.ok(p.length >= MIN_PATTERN_LENGTH, `no pattern for ${JSON.stringify(lines)}`);
    for (const l of lines) {
      assert.ok(l.toLowerCase().includes(p.toLowerCase()),
        `"${p}" does not appear in "${l}" — the rule would not fire on a line ` +
        "the CA just coded");
    }
  }
});

test("it is the LONGEST such run, not merely a run", () => {
  // "SALARY" alone would match, and would also match "SALARY ADVANCE". The
  // longest shared run is the most specific rule the evidence supports.
  const p = commonNarrationPattern(["SALARY APR2026", "SALARY MAY2026"]);
  assert.equal(p, "SALARY");
  // And the trailing "0" the two share is dropped, not kept: it is an artefact
  // of these two lines and would fail to match "…PAYOUT 10" next month.
  const q = commonNarrationPattern(["NEFT SALARY PAYOUT 01", "NEFT SALARY PAYOUT 02"]);
  assert.equal(q, "NEFT SALARY PAYOUT");
  assert.ok("NEFT SALARY PAYOUT 10".includes(q),
    "the pattern must still match the eleventh payout, not just the first two");
});

test("one line has nothing in common with itself", () => {
  // The whole narration would come back — reference number, month and all —
  // and a rule built on it could never fire a second time.
  assert.equal(commonNarrationPattern(["NEFT CHARGES APR2026"]), "");
  assert.equal(commonNarrationPattern([]), "");
});

test("a run that is only digits and separators is refused", () => {
  // Every line of an April statement contains "2026". A rule on it would fire
  // on all of them and, because match_rule takes the FIRST rule that fires,
  // would also block every real rule behind it.
  assert.equal(commonNarrationPattern(["PAID 2026-04-01", "RECD 2026-04-09"]), "");
});

test("a run shorter than the floor is refused", () => {
  // " TO " appears in a great many narrations.
  assert.equal(commonNarrationPattern(["A TO B", "C TO D"]), "");
  assert.ok(MIN_PATTERN_LENGTH >= 4,
    "the floor may not be lowered to 3 — two- and three-character runs appear " +
    "in most narrations on a statement");
});

test("lines with nothing in common produce nothing", () => {
  assert.equal(commonNarrationPattern(["SALARY", "RENT"]), "");
});

test("an empty or blank line makes the whole answer empty", () => {
  // Not "ignore it and pattern the rest": a blank narration shares nothing, so
  // any pattern returned would be one that does NOT match every selected line.
  assert.equal(commonNarrationPattern(["BANK CHARGES", ""]), "");
  assert.equal(commonNarrationPattern(["BANK CHARGES", "   "]), "");
});

test("matching ignores case but the answer keeps the statement's own", () => {
  const p = commonNarrationPattern(["BANK CHARGES LEVIED", "bank charges applied"]);
  assert.equal(p, "BANK CHARGES");  // edge space trimmed, original casing kept
});

test("leading and trailing punctuation is trimmed off", () => {
  const p = commonNarrationPattern(["X/BANK CHARGES/1", "Y/BANK CHARGES/2"]);
  assert.equal(p, "BANK CHARGES");
});
