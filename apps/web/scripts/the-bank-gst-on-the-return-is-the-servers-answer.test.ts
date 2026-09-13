// A bank line's GST reaches the return, and what it cannot prove is said out
// loud on the screen that files it (BANK-24).
//
// Run with:
//   node --experimental-strip-types --test scripts/the-bank-gst-on-the-return-is-the-servers-answer.test.ts
//
// WHAT WAS WRONG
//     A CA marks a bank charge as carrying 18% GST; the posting debits GST
//     Input for real. GSTR-3B was built only from purchase bills and sales
//     invoices, so the credit never reached Table 4(A) — and the same rupees
//     came back as an unexplained books-vs-ledger ITC difference on this very
//     screen, every month.
//
// THE RULE, WHICH IS THE DURABLE HALF
//     The figures and the caveats are the SERVER's. CGST §16(2)(aa) wants a
//     supplier document a bank line does not carry, and an outward bank supply
//     has no tax invoice so GSTR-1 will not carry it — both are statutory
//     sentences, and CLAUDE.md keeps statutory reasoning in apps/api. This
//     screen renders them and derives nothing: no rate table, no inclusive
//     split, no §16 test in TypeScript.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const SCREEN = "app/clients/[id]/compliance/gst/page.tsx";

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

test("the screen renders the server's bank-line caveats", () => {
  const src = code(SCREEN);
  assert.match(src, /computeResult\.bank_line_caveats/,
    "the §16(2)(aa) and Rule 46 sentences come back on the return — a CA about "
    + "to file has to see that this credit has no 2B document behind it");
  assert.match(src, /bank_lines/,
    "and the figures those sentences are about must be shown beside them");
});

test("the screen does not work out the split itself", () => {
  // The tax-inclusive back-out lives in domain/banking/charge_gst.py and its
  // one keystroke mirror. A third copy here would be a statutory calculation
  // in the browser, and it would drift.
  const src = code(SCREEN);
  assert.doesNotMatch(src, /10000\s*\+\s*(rate|gst)/i,
    "no inclusive-GST back-out in the browser");
  // The sentences are RENDERED from the array, never written out here. A
  // hardcoded copy stops matching the day the rule changes, and it cannot name
  // the amount — the server's does. (§16(2)(aa) itself is named elsewhere on
  // this screen, in the 2B reconciliation panel, so its mere presence proves
  // nothing; what matters is that the bank-line notes come off the payload.)
  assert.match(src, /const notes = \(computeResult\.bank_line_caveats/,
    "the notes come off the payload");
  assert.match(src, /\{notes\.map\(/,
    "…and are rendered from that array rather than written out here");
});
