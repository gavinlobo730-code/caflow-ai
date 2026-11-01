// A statutory remittance tied to a ledger entry that no longer records the payment says so, in the server's words, and the link can be taken back
// (POST-A-272, the ESI / professional-tax side).
//
// WHAT WAS MISSING
//   The TDS challan's list says when the entry it is tied to was reversed or deleted. A remittance tied to such an entry was in neither list on the
//   payroll hand-off screen: it had a link, so it was not "paid but not matched", and nothing said the ledger no longer showed its payment.
//   The server now lists those apart (`stale_links` on `remittance-reconciliation`, with `ledger_link.label` and `.note`) and takes a link back
//   (`DELETE /api/payroll/clients/{id}/remittances/{id}/payment`)
//   (`apps/api/tests/test_a_remittance_tied_to_an_entry_that_was_reversed_or_deleted_says_so.py`).
//
// WHAT THIS HOLDS FROM THE BROWSER'S SIDE
//   * the panel reads `stale_links` from the same answer as the unmatched list and an older server's answer without it is an empty list;
//   * it draws the server's `label` and `note` as written and decides nothing about which state a link is in;
//   * the one action is "Take the link back", offered for every state but `unknown` (a ledger that could not be read is not a reason to undo a
//     link), through the shared single-click button, through the API client's DELETE, and followed by a re-read;
//   * the result banner sits above both lists, so a refusal is shown whichever list is on screen;
//   * the panel is drawn when only stale links exist.
//
// Run with: node --experimental-strip-types --test scripts/a-remittance-tied-to-an-entry-that-stopped-recording-the-payment-says-so-and-can-be-untied.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));

const PANEL = read("components/payroll/StatutoryHandoff.tsx");
const API = read("lib/api/index.ts");

test("the files are where this guard thinks they are", () => {
  assert.ok(PANEL.length > 10000 && API.length > 100000, "a file read as nearly empty");
});

test("the API client asks for the stale links and takes a link back with a DELETE on the payment path", () => {
  assert.ok(/stale_links\?: StaleRemittanceLink\[\]/.test(API), "the reconciliation answer does not type stale_links (optional: an older server sends none)");
  assert.ok(/unlinkRemittancePayment: \(clientId: string, remittanceId: string\) =>[\s\S]{0,260}\/remittances\/\$\{remittanceId\}\/payment`,\s*\{ method: "DELETE" \}/.test(API),
    "the take-back is not a DELETE on the remittance's payment path");
  assert.ok(/state: "reversed" \| "deleted" \| "draft" \| "reversal" \| "missing" \| "unknown";\s*label: string;\s*note: string \| null;/.test(API),
    "the stale link's reading is not the server's state, label and note");
});

test("the panel reads stale_links with the unmatched list, and an older server's answer is an empty list", () => {
  assert.ok(/setStale\(res\?\.success \? \(res\.data\?\.stale_links \?\? \[\]\) : \[\]\);/.test(PANEL), "stale_links is not read from the answer, or not defaulted");
  assert.ok(/catch \{ setRows\(\[\]\); setStale\(\[\]\); \}/.test(PANEL), "a failed read leaves an earlier list on screen");
});

test("the server's label and note are drawn as written and the screen decides no state", () => {
  assert.ok(/\{r\.ledger_link\.label\}/.test(PANEL) && /r\.ledger_link\.note && <p[^>]*>\{r\.ledger_link\.note\}<\/p>/.test(PANEL), "the label or the note is not drawn from the server");
  const block = PANEL.slice(PANEL.indexOf("{stale.length > 0 && ("), PANEL.indexOf("{rows.length > 0 && (<>"));
  assert.ok(block.length > 400, "the stale block could not be found");
  assert.ok(!/is_reversed|deleted_at|is_posted|reversal_of/.test(block), "the browser reads the entry's flags itself");
  assert.ok(!/"Tied to an entry|was reversed|was deleted|still a draft/.test(block), "a state's sentence is written in the browser");
});

test("Take the link back is offered for every state but unknown, through the shared button, and the lists are read again", () => {
  assert.ok(/r\.ledger_link\.can_take_back && \(\s*<Button variant="plain" size="none" onClick=\{\(\) => unlink\(r\.id\)\} disabled=\{busy !== null\}/.test(PANEL),
    "the take-back is not the shared button gated on the server's can_take_back");
  assert.ok(!/\.state\s*(===|!==)/.test(PANEL), "the panel reads a state word instead of the server's judgement");
  const fn = PANEL.slice(PANEL.indexOf("async function unlink("), PANEL.indexOf("// Nothing outstanding is the ordinary state"));
  assert.ok(/api\.payroll\.unlinkRemittancePayment\(clientId, remittanceId\)/.test(fn), "the call does not go through the API client");
  assert.ok(/if \(!res\?\.success\) throw new Error\(res\?\.error \?\? /.test(fn), "a refusal is not shown");
  assert.ok(/await load\(\);\s*onLinked\(\);/.test(fn), "the lists are not read again after a take-back");
  assert.ok(!/<button/.test(block(PANEL)), "a raw button was added to the panel");
});

function block(src: string): string {
  return src.slice(src.indexOf("function UnmatchedRemittances("), src.indexOf("// ─── the screen"));
}

test("the result banner sits above both lists and the panel is drawn when only stale links exist", () => {
  const panel = block(PANEL);
  const banner = panel.indexOf("{note && (");
  assert.ok(banner > 0 && banner < panel.indexOf("{stale.length > 0 && (") && banner < panel.indexOf("{rows.length > 0 && (<>"),
    "a refusal would be hidden when only one of the lists is on screen");
  assert.ok(/if \(!loaded \|\| \(rows\.length === 0 && stale\.length === 0\)\) return null;/.test(panel), "the panel is hidden when only stale links exist");
});
