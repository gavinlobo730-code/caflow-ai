/**
 * A GSTR-1 gap is either a document the payload does not carry or a report
 * about a row it does, and `Gstr1Findings` headed both "Not declared in this
 * return".
 *
 * The second kind's own reasons say the opposite — "Table 12 files the code
 * exactly as recorded — correct it on the invoice line" — so a CA read a
 * reported HSN or unit as a document missing from a return that carries it,
 * and went looking for an invoice that was never held back.
 *
 * `domain/gst/gstr1_builder.REPORTED_NOT_WITHHELD` has been the one vocabulary
 * since GST-18 and nothing carried it across the wire. The server stamps
 * `withheld` per gap now; this file holds the browser's half of that:
 *
 *   * the panel renders TWO groups, from the server's own answer
 *   * it keeps NO list of kinds, because a second copy of a vocabulary is the
 *     Schedule III caption mistake
 *   * an ABSENT `withheld` reads as withheld, so a frontend deployed ahead of
 *     its backend renders exactly as it did before
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const raw = readFileSync(
  path.join(WEB, "components/gst/Gstr1Findings.tsx"),
  "utf8",
);

// COMMENTS STRIPPED FIRST. The file's own header explains both headings, so a
// scan over the raw text finds every phrase this asserts about and would pass
// on a component that rendered nothing at all.
const src = raw.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/^\s*\/\/.*$/gm, " ");

test("the strip does not make the scan vacuous", () => {
  assert.ok(src.includes("Gstr1Findings"), "the component survives the strip");
  assert.ok(raw.length - src.length > 500, "there were comments to strip");
});

test("the panel splits the gaps into two groups", () => {
  assert.match(src, /withheld\.map\(/, "the held-out documents are their own list");
  assert.match(src, /reported\.map\(/, "the reported rows are their own list");
  assert.doesNotMatch(
    src,
    /\bgaps\.map\(/,
    "one list under one heading is what said something false about half of it",
  );
});

test("an absent withheld reads as WITHHELD", () => {
  // `g.withheld !== false` and `g.withheld === false`, never a truthiness
  // test: `!g.withheld` would put an un-stamped gap in the reported group and
  // change what every existing backend renders.
  assert.match(src, /withheld !== false/);
  assert.match(src, /withheld === false/);
  assert.doesNotMatch(src, /\(g\) => !g\.withheld/);
});

test("the heading for the second group does not claim the row was dropped", () => {
  assert.match(src, /Filed as recorded/);
  const notDeclared = src.match(/Not declared in this return/g) ?? [];
  assert.equal(notDeclared.length, 1, "exactly one group may claim that");
});

test("the panel keeps NO list of gap kinds", () => {
  // The server decides. Every kind this repository has: a mention of any of
  // them here would be a second vocabulary, drifting from the moment a kind
  // is added on the Python side.
  for (const kind of [
    "hsn_digits_below_requirement",
    "hsn_is_not_a_code",
    "cancelled_documents_not_read",
    "return_caveat",
    "uqc_not_recorded",
    "SEZ_WOP",
  ]) {
    assert.doesNotMatch(
      src,
      new RegExp(kind),
      `${kind} is named in the panel — the vocabulary belongs to apps/api`,
    );
  }
});
