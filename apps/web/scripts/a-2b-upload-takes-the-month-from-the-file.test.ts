// The client GST tab's GSTR-2B upload is a file chooser that reads the month and
// the GSTIN off the file (gst-09). Run with:
//   node --experimental-strip-types --test scripts/a-2b-upload-takes-the-month-from-the-file.test.ts
//
// WHAT WAS WRONG
//   The tab asked for the period to be TYPED ("Period (MMYYYY e.g. 042025)") and
//   for a multi-megabyte JSON to be PASTED into a textarea. The file already
//   says which month it is for and whose it is, so a month typed against the
//   wrong file was accepted — and the server, which then wrote the file's
//   documents under the TYPED month, replaced that month's reconciliation with
//   another month's documents. The RULE is the server's
//   (`domain/gst/gstr2b_intake`, pinned by
//   `tests/test_a_2b_file_says_which_month_and_whose.py`); this holds the half a
//   server cannot: the screen has no box in which to type a month, the file is
//   chosen or dropped, the server's reading of it is what enables the upload,
//   and the upload sends nothing the file does not already say.
//
//   This reads source, because the web suite has no DOM. It is the floor, not
//   the ceiling: a click-through in a browser is what checks the rest.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const PAGE = stripComments(fs.readFileSync(
  path.join(WEB, "app/clients/[id]/compliance/gst/page.tsx"), "utf8"));

/** The GSTR-2B tab's own source — from its function to the next top-level one. */
function tab(): string {
  const at = PAGE.indexOf("function GSTR2BTab(");
  assert.ok(at >= 0, "GSTR2BTab is gone — move this assertion with it");
  const next = PAGE.indexOf("\nfunction ", at + 1);
  return PAGE.slice(at, next === -1 ? undefined : next);
}

test("the tab takes a FILE, chosen or dropped", () => {
  const t = tab();
  assert.match(t, /<input[^>]*type="file"/);
  assert.match(t, /accept="\.json,application\/json"/);
  assert.match(t, /onDrop=/);
  assert.match(t, /onDragOver=/);
  assert.match(t, /e\.dataTransfer\.files\?\.\[0\]/);
  assert.match(t, /file\.text\(\)/);
});

test("there is nowhere to type a month or paste a file", () => {
  const t = tab();
  assert.doesNotMatch(t, /<textarea/);
  assert.doesNotMatch(t, /Period \(MMYYYY/);
  assert.doesNotMatch(t, /Paste the GSTR-2B JSON/);
  assert.doesNotMatch(t, /const \[period, setPeriod\]/);
  assert.doesNotMatch(t, /const \[jsonText/);
});

test("the month shown is the one the SERVER read off the file", () => {
  const t = tab();
  assert.match(t, /"\/api\/gst-workspace\/gstr2b\/inspect"/);
  assert.match(t, /const period = inspection\?\.ok \? inspection\.period : null/);
  assert.match(t, /gstPeriodLabel\(inspection\.period\)/);
  assert.match(t, /read from the file/);
});

test("the file is read through the one helper, which does not read the month", () => {
  const t = tab();
  assert.match(t, /readGstr2bText\(text\)/);
  assert.doesNotMatch(t, /JSON\.parse/, "the tab parses nothing itself");
  assert.doesNotMatch(t, /rtnprd/, "the month is the server's to read");
  assert.doesNotMatch(t, /raw\??\.data\b|\["data"\]/, "the file's envelope is the server's to read");
});

test("the upload is enabled only for a file the server cleared, and sends no period", () => {
  const t = tab();
  assert.match(t, /disabled=\{loading \|\| reading \|\| !raw \|\| !inspection\?\.ok\}/);
  assert.match(t, /if \(!raw \|\| !inspection\?\.ok\) return;/);
  assert.match(t, /body: JSON\.stringify\(\{ client_id: clientId, raw_data: raw \}\)/);
  // The upload body is the one above; a `period:` key anywhere in a request body
  // in this tab would be a second source for the month.
  assert.doesNotMatch(t, /JSON\.stringify\(\{[^}]*\bperiod\b/);
});

test("a refusal is shown in words, in an alert, beside the file", () => {
  const t = tab();
  assert.match(t, /role="alert"/);
  assert.match(t, /This file was not uploaded\./);
  assert.match(t, /inspection\.refusals\.map/);
  assert.match(t, /objectWithLists<Inspection2B>\(resp\.data, "refusals", "problems"\)/);
});

test("the multi-registration caveat the server serves is rendered", () => {
  const t = tab();
  assert.match(t, /inspection\.registration_caveat/);
});

test("the page's own apiFetch hands a refusal back as the server's sentence", () => {
  // FastAPI's HTTPException body is {"detail": "..."}; without this the 2B
  // upload's 422 showed "Upload failed" over the sentence saying why.
  const at = PAGE.indexOf("async function apiFetch(");
  const body = PAGE.slice(at, PAGE.indexOf("\n}", at));
  assert.match(body, /if \(!res\.ok\) return \{ success: false, data: null, error: await errorMessage\(res\) \}/);
  assert.match(PAGE, /import \{ errorMessage \} from "@\/lib\/api"/);
});
