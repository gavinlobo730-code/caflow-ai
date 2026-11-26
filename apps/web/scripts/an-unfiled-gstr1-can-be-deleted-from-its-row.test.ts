/**
 * AN UNFILED GSTR-1 CAN BE DELETED FROM ITS ROW (POST-A-547).
 *
 * The server could always delete an unfiled GSTR-1's saved working (`DELETE /api/gst-workspace/gstr1/{return_id}`) and no row
 * offered it, while the GSTR-3B row beside it had Delete. The check that every server route has a screen had been counting
 * the route as called, because a fixed route of another verb sat beside it and the address it searches for carries no verb.
 *
 * What is held here is the RULE the button follows, read off the GSTR-1 tab's own source and not off a spelling of it:
 *
 *   1. the button is drawn only for an unfiled return, and for an approved one only to somebody who may approve, which is
 *      what the route asks (`_delete_return`: a filed return is refused, an approved one needs `gst` `approve`);
 *   2. the delete asks first, sends DELETE to that return's own address, and READS the answer: this router answers a
 *      refusal as HTTP 200 with `success: false`, so an answer that is not read is a refusal shown as a deletion;
 *   3. the row waits while its delete runs, so a second click cannot ask twice.
 *
 * `scripts/drive/weekly/gstr1Delete.mjs` drives the same three in a browser.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const WEB = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(resolve(WEB, "app/clients/[id]/compliance/gst/page.tsx"), "utf8");

/** The source of one top-level function component, from its `function Name(` to the next top-level `function `. */
function component(name: string): string {
  const at = page.indexOf(`\nfunction ${name}(`);
  assert.ok(at >= 0, `${name} is gone from the GST screen`);
  const next = page.indexOf("\nfunction ", at + 1);
  return page.slice(at, next === -1 ? undefined : next);
}

const tab = component("GSTR1Tab");

test("the GSTR-1 tab has a delete of its own and it is not the GSTR-3B tab's", () => {
  assert.match(tab, /async function deleteReturn\(/, "the GSTR-1 tab has no delete");
  assert.match(tab, /`\/api\/gst-workspace\/gstr1\/\$\{id\}`,\s*\{\s*method:\s*"DELETE"\s*\}/, "the delete does not go to the GSTR-1's own address");
  assert.doesNotMatch(tab, /gst-workspace\/gstr3b\/\$\{id\}`,\s*\{\s*method:\s*"DELETE"/, "the GSTR-1 tab deletes a GSTR-3B");
});

test("the delete asks first and reads the server's answer", () => {
  const fn = tab.slice(tab.indexOf("async function deleteReturn("), tab.indexOf("async function markFiled("));
  assert.ok(fn.length > 0, "deleteReturn is not where this test reads it");
  assert.match(fn, /if \(!\(await confirmDialog\(/, "nothing is asked before the delete");
  assert.ok(fn.indexOf("confirmDialog") < fn.indexOf("apiFetch("), "the request is sent before the question is answered");
  assert.match(fn, /if \(!r\.success\) \{ setRowError\(r\.error \?\? /, "a refusal (HTTP 200, success false) is not read");
  assert.match(fn, /catch \(e\) \{\s*setRowError\(failureSentence\(e, /, "a failed request is not said");
  assert.match(fn, /finally \{ setBusyRow\(null\); \}/, "the row is not released after the request");
});

test("the button is drawn for an unfiled return only, to whoever the route admits, and waits while it runs", () => {
  const at = tab.indexOf("data-delete-gstr1");
  assert.ok(at >= 0, "the Delete button is gone from the GSTR-1 row");
  const guard = tab.slice(tab.lastIndexOf("{UNFILED.includes(", at), at);
  assert.match(guard, /\{UNFILED\.includes\(r\.status as string\) && \(r\.status === "ca_approved" \? mayApprove : mayCompute\) && \(/,
    "the button is not behind the unfiled statuses and the permission the route asks");
  const button = tab.slice(at - 300, at + 400);
  assert.match(button, /disabled=\{busyRow === r\.id\}/, "the button does not wait while its delete runs");
  assert.match(page, /const UNFILED = \["draft", "validated", "ca_approved"\];/, "the unfiled statuses moved: read `_DELETABLE_STATUSES` in the GST router again");
});
