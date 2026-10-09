// The firm-level GSTR-2B drop sends files and nothing else. Run with:
//   node --experimental-strip-types --test scripts/a-2b-drop-for-many-clients-names-no-client-and-no-month.test.ts
//
// WHAT WAS MISSING
//   A 2B was reconciled one client at a time, from that client's tab, with the CA
//   choosing the client BEFORE the file — although every file already says whose
//   it is. gst-10 reads the GSTIN inside each file and routes it server-side.
//
// THE RULES ARE THE SERVER'S — `domain/gst/gstr2b_routing` decides whose a file
// is, `gstr2b_intake` the month, `services/gst_2b_bulk_service` the per-file
// answer, and `apps/api/tests/test_many_clients_2b_files_are_each_routed_by_the_
// gstin_inside_them.py` pins that no file reaches a client outside the caller's
// book. This holds the half only the screen can get wrong: there is no control
// in which to name a client or a month, the request carries the file and
// nothing else, files go one at a time so no request outlives the browser's
// 45-second abort, and what is shown is the server's status and sentence.
//
// This reads source, because the web suite has no DOM. It is the floor, not the
// ceiling: a click-through in a browser is what checks the rest.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));

const PANEL = read("components/gst/BulkGstr2bPanel.tsx");
const API = read("lib/api/index.ts");
const PAGE = read("app/gst/page.tsx");

test("the firm-level GST screen offers the drop", () => {
  assert.match(PAGE, /import \{ BulkGstr2bPanel \} from "@\/components\/gst\/BulkGstr2bPanel"/);
  assert.match(PAGE, /<BulkGstr2bPanel \/>/);
});

test("the control takes MANY files, chosen or dropped, and has nowhere to name a client or a month", () => {
  assert.match(PANEL, /<input[^>]*type="file"[^>]*multiple/);
  assert.match(PANEL, /accept="\.json,application\/json"/);
  assert.match(PANEL, /aria-label="GSTR-2B JSON files"/);
  assert.match(PANEL, /onDrop=/);
  assert.match(PANEL, /Array\.from\(e\.dataTransfer\.files \?\? \[\]\)/);
  assert.doesNotMatch(PANEL, /<select|<textarea|ClientLookup|setClient|setPeriod|type="month"/);
  assert.doesNotMatch(PANEL, /Period \(MMYYYY/);
});

test("the request carries the file and its name and nothing else — no client, no month", () => {
  const call = PANEL.slice(PANEL.indexOf("reconcileGstr2bFiles(["),
                           PANEL.indexOf("]);", PANEL.indexOf("reconcileGstr2bFiles([")));
  assert.match(call, /name: file\.name, raw_data: read\.raw/);
  assert.doesNotMatch(call, /client|period|gstin|rtnprd/i);

  const method = API.slice(API.indexOf("reconcileGstr2bFiles:"),
                           API.indexOf("createDraftBillFrom2b:"));
  assert.match(method, /"\/api\/gst-workspace\/gstr2b\/bulk"/);
  assert.match(method, /JSON\.stringify\(\{ files \}\)/);
  assert.doesNotMatch(method, /client_id|period/);
});

test("the file's own contents are the server's to read — the panel reads neither GSTIN nor month", () => {
  assert.doesNotMatch(PANEL, /JSON\.parse/);
  assert.doesNotMatch(PANEL, /rtnprd|\.gstin\b.*data|raw\.data|\["data"\]/);
  assert.match(PANEL, /readGstr2bText\(text\)/);
});

test("files go ONE AT A TIME, so no request outlives the browser's 45-second abort", () => {
  assert.match(PANEL, /for \(let i = 0; i < files\.length; i\+\+\) \{/);
  assert.doesNotMatch(PANEL, /Promise\.all|Promise\.allSettled|\.map\(async/);
  // one file per request: the array handed to the API has one element
  assert.match(PANEL, /reconcileGstr2bFiles\(\[\s*\{ name: file\.name, raw_data: read\.raw \},\s*\]\)/);
});

test("a file the browser cannot read as JSON never leaves it, and says why in the reader's words", () => {
  assert.match(PANEL, /if \(!read\.ok\) \{/);
  assert.match(PANEL, /unreadable\(file\.name, read\.error\)/);
});

test("one file's failure is one row and the rest carry on", () => {
  assert.match(PANEL, /catch \(e\) \{\s*result = failed\(file\.name,/);
  assert.match(PANEL, /\} catch \{\s*patch\(i, \{ state: "done", result: unreadable/);
});

test("the running flag comes down in a finally, so a throw cannot leave the drop disabled", () => {
  assert.match(PANEL, /setRunning\(true\);[\s\S]*?try \{[\s\S]*?\} finally \{\s*setRunning\(false\);/);
});

test("stopping is honoured between files and the rows not started say so", () => {
  assert.match(PANEL, /if \(stopRef\.current\) \{/);
  assert.match(PANEL, /patch\(j, \{ state: "skipped" \}\)/);
  assert.match(PANEL, /Not started — stopped/);
});

test("what is shown is the server's status and sentence, and the answer's list is guarded", () => {
  assert.match(PANEL, /objectWithLists<Gstr2bBulkAnswer>\(resp\.data, "results"\)/);
  assert.match(PANEL, /answer\?\.results\[0\]/);
  assert.match(PANEL, /\{res\.reason &&/);
  assert.match(PANEL, /STATUS\[res\.status\]/);
  assert.match(PANEL, /res\.problems\.map/);
});

test("a file that is not reconciled is listed with why, and an absent row is never a clean one", () => {
  for (const s of ["unmatched_gstin", "ambiguous_gstin", "refused", "unreadable", "failed"]) {
    assert.match(PANEL, new RegExp(`${s}: \\{ label:`), `${s} has a label`);
  }
  assert.match(PANEL, /belongs to no client of yours is listed and not stored/);
});

test("a reconciliation that REPLACED an earlier one says so, in IST", () => {
  assert.match(PANEL, /res\.replaced_earlier &&/);
  assert.match(PANEL, /formatIstLabelled\(res\.replaced_earlier\.reconciled_at/);
  // What it says about which download is newer is the SERVER's sentence
  // (gstr2b_intake.DOWNLOAD_NOTES), so the same file dropped twice is not told
  // "check this is the newer file". The old sentence survives only as the
  // fallback for a backend that has not redeployed.
  assert.match(PANEL, /res\.replaced_earlier\.note \?\? "Check this is the newer file\."/);
  assert.match(PANEL, /replaced_earlier\.relation === "same"/);
});

test("the panel keeps nothing in the browser and sends nothing to a portal", () => {
  assert.doesNotMatch(PANEL, /localStorage|sessionStorage|indexedDB/);
  assert.doesNotMatch(PANEL, /gst\.gov\.in|fetch\(/);
});
