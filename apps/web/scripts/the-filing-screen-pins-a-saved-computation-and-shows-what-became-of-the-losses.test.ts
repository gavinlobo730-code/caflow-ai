/**
 * The filing screen creates a return from a saved computation, and says what became of the brought-forward losses when it is filed (POST-A-073).
 *
 * WHAT WAS WRONG
 *   `itr_filings.computation_snapshot_id` pins the computation a return is built on, and the screen never sent it, so no return made here pinned
 *   anything. The write-back of a filed return's use of each brought-forward loss reads the pinned computation, so for every return made on this
 *   screen it would have written nothing, and the review gate (IT-30) that also reads the pin could never ask its question.
 *
 * WHAT THIS HOLDS
 *   - the create form offers the client's saved computations for the year and sends the one chosen as `computation_snapshot_id`;
 *   - the choice is a named control (a label tied to the select);
 *   - what the server says about the loss records after the acknowledgement is shown (`lossRecordNote` into a callout), the way the
 *     compliance-calendar sentence is.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const PAGE = path.join(WEB, "app/clients/[id]/tax/filing/page.tsx");

function withoutComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
    .split("\n")
    .map(line => line.replace(/(^|\s)\/\/.*$/, "$1"))
    .join("\n");
}

const code = withoutComments(fs.readFileSync(PAGE, "utf8"));

test("the saved computation chosen goes to the server with the new filing", () => {
  assert.match(code, /computation_snapshot_id:\s*snapshotId \|\| null/, "a return is created without the computation it is built on");
});

test("the client's saved computations for the year are offered", () => {
  assert.match(code, /\/api\/itr\/snapshots\?client_id=\$\{encodeURIComponent\(clientId\)\}&financial_year=\$\{encodeURIComponent\(fy\)\}/);
  assert.match(code, /snapshots\.map\(/, "the computations fetched are not listed");
});

test("the choice is a named control", () => {
  assert.match(code, /<label htmlFor="itr-computation"/);
  assert.match(code, /<select id="itr-computation"/);
});

test("what the server says about the loss records is shown", () => {
  assert.match(code, /setLossNote\(lossRecordNote\(res\.data\)\)/);
  assert.match(code, /\{lossNote && \(/);
});

test("a return recorded as filed can be pinned afterwards and have its loss records updated, and the answer is shown whatever the state", () => {
  assert.match(code, /\/api\/itr\/filings\/\$\{filing\.id\}\/computation/, "a filed return made without a computation cannot be pinned");
  assert.match(code, /\/api\/itr\/filings\/\$\{filing\.id\}\/loss-records/, "a filed return cannot have its loss records updated again");
  assert.match(code, /setLossNote\(lossRecordAnswer\(res\.data\)/, "a click on the update button is answered with silence");
  assert.match(code, /<label htmlFor="itr-pin-computation"/);
  assert.match(code, /<select id="itr-pin-computation"/);
});

test("the update waits for whatever is already running, like every other button on the screen", () => {
  assert.match(code, /const actionInFlight = [^;]*\|\| savingLosses;/);
  assert.match(code, /updateLossRecords\(selectedFiling, null\)\}\s*disabled=\{actionInFlight\}/);
});
