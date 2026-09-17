/**
 * The GSTR-3B rows that are nil-because-underivable reach the CA.
 *
 * `table_4a_gaps` was served from the compute endpoint since GST-24 and NO
 * SCREEN RENDERED IT — written, returned over the wire, and seen by nobody.
 * That is the failure this file exists to stop coming back, so it asserts the
 * RENDER and not merely the fetch.
 *
 * Every sentence shown is the server's. Deciding in the browser which rows a
 * GSTR-3B cannot derive would be a second implementation of a statutory
 * judgement — 3.1.1 turns on §9(5), 4(D)(2) on §16(4) and the place-of-supply
 * rules — and the two would drift the first time a document type was modelled.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

import { panelSource } from "./panelSource.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const PAGE = path.join(WEB, "app/clients/[id]/compliance/gst/page.tsx");

function withoutComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
    .split("\n")
    .map((l) => l.replace(/(^|\s)\/\/.*$/, "$1"))
    .join("\n");
}

const raw = fs.readFileSync(PAGE, "utf8");
const code = withoutComments(raw);

/**
 * THE PANEL, not the whole file, and not a path either.
 *
 * A negative control found the first half the hard way: asserting `rows.map(`
 * against the whole page passed while this panel's render was replaced by a
 * dead `[].map`, because a different table on the same 3,000-line screen also
 * maps a variable called `rows`. An assertion another call site can satisfy is
 * not an assertion.
 *
 * The second half was found when the panel MOVED. It lived inline on the
 * per-client GST tab until the firm-level GSTR-3B screen needed the same three
 * panels (GST-22), and this guard had that page's path written into it — so it
 * failed on a move that did not break the rule. `panelSource` resolves the file
 * by a phrase only this panel contains, and asserts there is exactly one.
 */
function panelOf(src: string): string {
  const start = src.indexOf("export function Gstr3bUndeclarableRows");
  assert.notEqual(start, -1, "the panel that renders the server's list is gone");
  const end = src.indexOf("\nexport ", start + 1);
  return end === -1 ? src.slice(start) : src.slice(start, end);
}

const panelFile = withoutComments(panelSource("Nil because this product cannot derive it"));
const panel = panelOf(panelFile);

/** Everything the browser could spell these rows in: the screen that computes
 *  and the panel that renders. Splitting them would let a sentence move from
 *  one to the other and the "the list is the server's" test go quiet. */
const browser = code + "\n" + panelFile;

test("a nil the product cannot derive is shown to the CA", async (t) => {
  await t.test("the list is read from the server and rendered", () => {
    assert.match(panel, /rows\.map\(/,
      "the list is read and never rendered — the exact defect this replaces");
    // The row identifier, the label and the reason: dropping any one of the
    // three leaves a warning a CA cannot act on.
    for (const field of [/\{g\.row\}/, /\{g\.label\}/, /\{g\.reason\}/]) {
      assert.match(panel, field, `${field} is not rendered in the panel that reads the list`);
    }
  });

  await t.test("nothing is rendered when the server sends no rows", () => {
    assert.match(panel, /rows\.length === 0\) return null/,
      "an empty list should render nothing, not an empty panel");
  });

  await t.test("the browser decides which rows are underivable for none of them", () => {
    for (const p of [/3\.1\.1/, /4\(D\)\(2\)/, /9\(5\)/, /16\(4\)/, /\bISD\b/]) {
      assert.ok(!p.test(browser), `${p} is spelled in the browser — the list is the server's`);
    }
  });

  await t.test("it does not restate the server's reason in its own words", () => {
    for (const p of [/e-?commerce operator/i, /nil-rated/i, /Input Service Distributor/i]) {
      assert.ok(!p.test(browser), `${p} is written into the screen`);
    }
  });

  await t.test("it says a nil here is not evidence of nothing", () => {
    // The whole point. A panel that lists the rows without saying why they
    // need checking is a list of table numbers.
    assert.match(panel, /cannot derive/i);
    assert.match(panel, /check each on the portal/i);
  });

  await t.test("the comment strip does not make the scan vacuous", () => {
    assert.ok(code.length > raw.length / 2, "too much of the file was stripped");
    assert.ok(panel.length > 400, "the panel slice collapsed — the scan would be vacuous");
    assert.match(code, /<Gstr3bFindings\b/,
      "the screen no longer renders the panel at all, which is the defect this " +
      "file exists to stop coming back");
  });
});
