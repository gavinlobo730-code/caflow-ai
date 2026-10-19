// A CA corrects what the model read from a notice before approving it. Run with:
//   node --experimental-strip-types --test scripts/a-ca-can-correct-a-staged-notice-reading-before-approving.test.ts
//
// WHY THIS EXISTS
//     A staged notice offered Approve and nothing between, and approval makes the response task with the due date on the reading and
//     tells the partners. The compliance tab now has a Correct button beside Approve that opens the reading as fields and sends only
//     what changed. The rules (the vocabulary, the dates, the lengths) are the server's; this holds that the screen sends a patch,
//     shows the server's refusal, closes only on success, and offers Correct only where Approve is.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
function code(rel: string): string {
  return fs.readFileSync(path.join(ROOT, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}
const PAGE = "app/clients/[id]/compliance/page.tsx";
const MODAL = "components/compliance/EditNoticeReadingModal.tsx";

test("the page sends a PATCH of only what changed to the reading door, and shows the server's sentence on a refusal", () => {
  const src = code(PAGE);
  assert.match(src, /\/api\/document-intelligence-v2\/notices\/\$\{editing\.id as string\}\/reading/);
  assert.match(src, /method: "PATCH"/);
  assert.match(src, /body: JSON\.stringify\(patch\)/);
  assert.match(src, /setEditError\(res\?\.error \?\? "The correction could not be saved\. Nothing was changed\."\)/);
});

test("only success closes the modal, a second press while saving does nothing, and the list is re-read", () => {
  const src = code(PAGE);
  assert.match(src, /if \(!editing \|\| editBusy\) return;/);
  const afterRefusal = src.slice(src.indexOf("The correction could not be saved. Nothing was changed.\");\n        return;"));
  assert.match(afterRefusal, /setEditing\(null\);\s*await loadNotices\(\);/);
});

test("Correct is offered only on a notice still pending review, beside Approve", () => {
  const src = code(PAGE);
  // the status cell is `n.ca_approved ? (<approved arm>) : (<pending arm>)`; the header also says "CA Approved", so the arms are found
  // from the ternary and not from the first occurrence of a word
  const ternary = src.indexOf("n.ca_approved ? (");
  const approvedAt = src.indexOf("✓ Approved", ternary);
  const pendingAt = src.indexOf("Pending review", approvedAt);
  const approveAt = src.indexOf("CA Approve", pendingAt);
  assert.ok(ternary > 0 && approvedAt > ternary && pendingAt > approvedAt && approveAt > pendingAt, "the notice status cell has changed shape");
  const approvedArm = src.slice(ternary, pendingAt);
  const pendingArm = src.slice(pendingAt, approveAt);
  assert.doesNotMatch(approvedArm, /Correct/, "an approved notice offers no correction (the server refuses it)");
  assert.match(pendingArm, /Correct/, "a pending notice offers Correct before CA Approve");
});

test("the modal sends nothing when nothing changed, and refuses to save over a date box holding text that is not a date", () => {
  const src = code(MODAL);
  assert.match(src, /const patch = buildCorrection\(notice, form\);/);
  assert.match(src, /disabled=\{busy \|\| unchanged \|\| !!dates\.first\}/);
  assert.match(src, /dates\.watch\("response_due_date", "Response due on"\)/);
});

test("the modal says the model's reading is kept and shows the server's sentence", () => {
  const src = code(MODAL);
  assert.match(src, /The model&apos;s own reading is kept alongside|The model's own reading is kept alongside/);
  assert.match(src, /role="alert"/);
});
