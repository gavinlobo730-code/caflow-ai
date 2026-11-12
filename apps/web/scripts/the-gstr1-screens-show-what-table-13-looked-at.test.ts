/**
 * GSTR-1's Table 13 lists twelve document natures and the builder reads three. A
 * client that issued a receipt voucher or a delivery challan filed a return whose
 * Table 13 left it out, and nothing on either GSTR-1 screen said the other nine
 * natures had not been looked at (POST-A-415).
 *
 * The server now sends `table_13_coverage`: the natures it declared, the natures
 * it did not look for, one sentence, and a count of the delivery challans issued
 * in the window. It is deliberately NOT a gap (a gap makes a return a draft and
 * is listed by the GSTR-3B tie-out as a document held out), so this is the
 * browser's half of that:
 *
 *   * the panel shows the server's sentences as served and holds no nature name
 *   * the panel renders on the coverage alone, because a return with no other
 *     finding is the commonest one and the sentence is true of it
 *   * both screens hand it over, and the data layer carries the key across
 *   * the red "n not declared" count counts what the server says is held out and
 *     not the reported rows beside them (it counted every gap, so a quarterly
 *     filer's two caveats read "2 not declared")
 *   * the coverage reaches nothing that decides a status
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const read = (p: string) => readFileSync(path.join(WEB, p), "utf8");
const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/^\s*\/\/.*$/gm, " ");

const panelRaw = read("components/gst/Gstr1Findings.tsx");
const panel = strip(panelRaw);
const firmPage = strip(read("app/gst/gstr1/page.tsx"));
const clientPage = strip(read("app/clients/[id]/compliance/gst/page.tsx"));
const dataRaw = read("lib/data/gst.ts");
const data = strip(dataRaw);

test("the strip does not make the scan vacuous", () => {
  assert.ok(panel.includes("Gstr1Findings"));
  assert.ok(panelRaw.length - panel.length > 500, "there were comments to strip");
  assert.ok(firmPage.includes("Gstr1Findings") && clientPage.includes("Gstr1Findings"));
});

test("the panel shows the server's two sentences and none of its own", () => {
  assert.match(panel, /coverage\.note/, "the standing note is the server's");
  assert.match(panel, /challans\.note/, "the challan sentence is the server's");
  // No nature of the form and no phrase about one: the vocabulary belongs to apps/api.
  for (const phrase of [
    "Receipt Voucher", "Payment Voucher", "Refund Voucher", "Revised Invoice",
    "Delivery Challan", "unregistered person", "did not look",
  ]) {
    assert.ok(!panel.includes(phrase), `${phrase} is written in the panel — the sentences are served`);
  }
});

test("the panel renders on the coverage alone, and says nothing when the server sent none", () => {
  // The early return must ask for the coverage too, or a return with no error,
  // warning or gap — the commonest — would hide the sentence entirely.
  const early = panel.match(/if \(([^)]*)\) return null;/);
  assert.ok(early, "the early return was not found");
  assert.match(early![1], /!coverage/, "the early return does not wait for the coverage");
  // And it makes nothing up: both blocks are behind the served object.
  assert.match(panel, /\{coverage && coverage\.note && \(/);
  assert.match(panel, /\{challans && challansNeedAnswer && \(/);
});

test("a challan the books hold, or a register that could not be read, is asked about and a settled zero is not", () => {
  assert.match(panel, /!challans\.read \|\| \(challans\.count \?\? 0\) > 0/);
  // An unknown count is never compared as if it were zero.
  assert.ok(!/challans\.count\s*(===|>=|<=|<)\s*0/.test(panel), "an unread count must not be treated as zero");
});

test("both screens hand the coverage to the panel", () => {
  const firm = firmPage.match(/<Gstr1Findings[\s\S]*?\/>/);
  const client = clientPage.match(/<Gstr1Findings[\s\S]*?\/>/);
  assert.ok(firm && client, "both screens render the panel");
  assert.match(firm![0], /coverage=\{result\.table_13_coverage\}/);
  assert.match(client![0], /coverage=\{computeResult\.table_13_coverage as Table13Coverage \| null \| undefined\}/);
  assert.equal((firmPage.match(/<Gstr1Findings/g) ?? []).length, 1, "one rendering on the firm screen");
  assert.equal((clientPage.match(/<Gstr1Findings/g) ?? []).length, 1, "one rendering on the client screen");
});

test("the data layer declares the key on both shapes and carries it across", () => {
  assert.equal((data.match(/table_13_coverage\?: Table13Coverage \| null;/g) ?? []).length, 2,
    "both the screen's result and the raw reply declare it");
  assert.match(data, /table_13_coverage: result\.table_13_coverage,/, "the mapping carries it");
  assert.match(data, /export interface Table13Coverage/);
});

test("the coverage decides no status: the readiness test does not read it", () => {
  const ready = data.match(/const readyToFile =[\s\S]*?;/);
  assert.ok(ready, "the readiness test was not found");
  assert.ok(!ready![0].includes("table_13_coverage"), "a sentence true of every return must not make every return a draft");
});

test("the red 'not declared' count counts what the server says is held out", () => {
  assert.ok(!/payload_gaps\.length\}\s*not declared/.test(firmPage), "it counts every gap, reported rows included");
  assert.match(firmPage, /heldOutGaps\(result\.payload_gaps\)\.length\} not declared/);
  assert.match(panel, /export function heldOutGaps/);
  // One definition: the panel's own split uses it too.
  assert.match(panel, /const withheld = heldOutGaps\(gaps\)/);
  // An absent stamp reads as held out, the old rendering.
  assert.match(panel, /g\.withheld !== false/);
});
