// Tests for the pure combobox matcher. Run with:
//   node --experimental-strip-types --test lib/combobox/match.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { RANK, matchScore, filterAndRank, hasExactMatch, normalize } from "./match.ts";

interface Cust {
  id: string;
  name: string;
  gstin?: string;
  pan?: string;
}
const fields = (c: Cust) => [c.name, c.gstin ?? "", c.pan ?? ""];

const ROWS: Cust[] = [
  { id: "1", name: "Acme Industries", gstin: "27AABCA1234A1Z5", pan: "AABCA1234A" },
  { id: "2", name: "Acme Corp", gstin: "29AAACA9999A1Z2" },
  { id: "3", name: "Beta Traders", gstin: "27AABCB5678B1Z9", pan: "AABCB5678B" },
  { id: "4", name: "Gamma & Co", gstin: "07AABCG1111G1Z1" },
];

test("normalize trims and lowercases", () => {
  assert.equal(normalize("  ACME  "), "acme");
  assert.equal(normalize(null), "");
  assert.equal(normalize(998314), "998314");
});

test("matchScore ranks exact > prefix > word-prefix > includes", () => {
  assert.equal(matchScore(["Acme"], "acme"), RANK.EXACT);
  assert.equal(matchScore(["Acme Industries"], "acme"), RANK.PREFIX);
  assert.equal(matchScore(["Acme Industries"], "indus"), RANK.WORD_PREFIX);
  assert.equal(matchScore(["Acme Industries"], "dustr"), RANK.INCLUDES);
  assert.equal(matchScore(["Acme"], "zzz"), RANK.NONE);
});

test("matchScore: empty query is a neutral (kept) match", () => {
  assert.equal(matchScore(["anything"], ""), RANK.WORD_PREFIX);
  assert.equal(matchScore(["anything"], "   "), RANK.WORD_PREFIX);
});

test("matchScore: word-prefix splits on separators (codes)", () => {
  assert.equal(matchScore(["IT / 998314 support"], "998"), RANK.WORD_PREFIX);
  assert.equal(matchScore(["services-998211"], "998211"), RANK.WORD_PREFIX);
});

test("matchScore: multi-token AND across fields", () => {
  // neither token is a prefix of a single field, but both appear
  assert.equal(matchScore(["Acme Industries", "Mumbai"], "acme mumbai"), RANK.TOKENS);
  assert.equal(matchScore(["Acme Industries", "Mumbai"], "acme delhi"), RANK.NONE);
});

test("filterAndRank: empty query returns input order unchanged", () => {
  assert.deepEqual(filterAndRank(ROWS, "", fields).map((r) => r.id), ["1", "2", "3", "4"]);
});

test("filterAndRank: ranks and filters; exact/prefix float up", () => {
  const r = filterAndRank(ROWS, "acme", fields).map((x) => x.name);
  // both Acme rows match by prefix; Beta/Gamma drop out
  assert.deepEqual(r, ["Acme Industries", "Acme Corp"]);
});

test("filterAndRank: search by GSTIN and PAN too", () => {
  assert.deepEqual(filterAndRank(ROWS, "AABCB", fields).map((x) => x.id), ["3"]); // pan/gstin
  assert.deepEqual(filterAndRank(ROWS, "27AABC", fields).map((x) => x.id), ["1", "3"]); // gstin prefix
});

test("filterAndRank: stable within equal rank (preserves input order)", () => {
  const rows = [
    { id: "a", name: "Zeta Ltd" },
    { id: "b", name: "Zeta Ltd" },
    { id: "c", name: "Zeta Ltd" },
  ];
  assert.deepEqual(
    filterAndRank(rows, "zeta", (r) => [r.name]).map((r) => r.id),
    ["a", "b", "c"],
  );
});

test("hasExactMatch drives the create row", () => {
  assert.equal(hasExactMatch(ROWS, "Acme Corp", fields), true);
  assert.equal(hasExactMatch(ROWS, "acme corp", fields), true); // case-insensitive
  assert.equal(hasExactMatch(ROWS, "Acme", fields), false); // prefix only, not exact
  assert.equal(hasExactMatch(ROWS, "", fields), false);
});
