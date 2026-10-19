// The chart-of-accounts import checks the Schedule III column against the server's vocabulary — run with:
//   node --experimental-strip-types --test lib/accounting/coaImportMapping.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { acceptedMappings, mappingProblem } from "./coaImportMapping.ts";

const PAYLOAD = {
  sections: [
    { heading: "Balance Sheet", items: ["Share Capital", "Trade Payables"] },
    { heading: "Profit & Loss", items: ["Revenue from Operations"] },
  ],
  also_accepted: ["Fixed Assets", "Long Term Borrowings"],
};

test("the accepted set is the menu plus the spellings the engine still reads", () => {
  const accepted = acceptedMappings(PAYLOAD);
  assert.deepEqual([...accepted!].sort(), [
    "Fixed Assets", "Long Term Borrowings", "Revenue from Operations", "Share Capital", "Trade Payables",
  ]);
});

test("a payload that could not be read vouches for nothing", () => {
  assert.equal(acceptedMappings(null), null);
  assert.equal(acceptedMappings(undefined), null);
  assert.equal(acceptedMappings({}), null);
  assert.equal(acceptedMappings({ sections: [] }), null);
});

test("an empty mapping is always fine, with or without a vocabulary", () => {
  assert.equal(mappingProblem(3, "", acceptedMappings(PAYLOAD)), null);
  assert.equal(mappingProblem(3, "", null), null);
});

test("a caption on the menu, an older spelling and the Fixed Assets heading are accepted", () => {
  const accepted = acceptedMappings(PAYLOAD);
  for (const value of ["Share Capital", "Revenue from Operations", "Long Term Borrowings", "Fixed Assets"]) {
    assert.equal(mappingProblem(2, value, accepted), null, value);
  }
});

test("a made-up caption names the row and the value, and says what to do", () => {
  const message = mappingProblem(7, "Miscellaneous", acceptedMappings(PAYLOAD));
  assert.match(message!, /^Row 7: "Miscellaneous" is not a Schedule III caption/);
  assert.match(message!, /leave it blank/);
});

test("a spelling in the wrong case or with a different hyphenation is not accepted", () => {
  const accepted = acceptedMappings(PAYLOAD);
  assert.notEqual(mappingProblem(2, "share capital", accepted), null);
  assert.notEqual(mappingProblem(2, "Long-term Borrowings", accepted), null); // not in THIS payload: only what the server sends counts
});

test("a non-empty mapping with no vocabulary is said to be unchecked, never silently passed", () => {
  const message = mappingProblem(4, "Share Capital", null);
  assert.match(message!, /could not be loaded/);
  assert.match(message!, /Share Capital/);
});
