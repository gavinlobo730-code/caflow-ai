// The import dialog fires ONE request at a time.
//
// Found by looking at the screen: "Reading…" and "Importing…" were both on the
// footer at once, because each button was disabled only by its OWN in-flight
// flag. `startMapping` and `runPreview` both call setInspected/setMapping/
// setPreview, so a read landing mid-import rewrites the dialog under a running
// upload, and whichever request finishes second overwrites the other's error.
// The import is a WRITE — the CA has to be able to tell which outcome they are
// looking at.
//
// This is a source test rather than a rendering one because that is what this
// repo has, and because the property IS syntactic: every control that starts
// work, or that changes what the work is about, has to be gated on the shared
// flag rather than on its own.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.join(__dirname, "..", "components", "banking", "AccountsPanel.tsx");
const src = fs.readFileSync(PANEL, "utf8");

/** The dialog's two in-flight flags, and the one derived from them. */
test("the two flags are combined into one, once", () => {
  assert.match(src, /const busy = checking \|\| importing;/,
    "the shared flag is what every control is gated on — if it is renamed or " +
    "removed, the assertions below stop meaning anything");
});

/** Each control that STARTS work must be gated on both, not on its own flag. */
for (const [label, handler] of [
  ["Map columns", "startMapping"],
  ["Check this mapping", "runPreview"],
  ["Import", "handleImport"],
] as const) {
  test(`"${label}" cannot be pressed while any request is in flight`, () => {
    const at = src.indexOf(`onClick={${handler}}`);
    assert.ok(at > 0, `${handler} is no longer wired to a button`);
    const button = src.slice(at, at + 400);
    assert.match(button, /disabled=\{\s*busy\b/,
      `${label} must be disabled while EITHER request runs. Gating it on its ` +
      `own flag alone is what let two fire at once.`);
  });
}

test("the file cannot be swapped out from under a running request", () => {
  const at = src.indexOf("fileRef.current?.click()");
  assert.ok(at > 0);
  assert.match(src.slice(at, at + 200), /disabled=\{busy\}/,
    "handleFile resets the mapping, the preview and the result — doing that " +
    "while a request is in flight leaves the dialog describing a different file");
});

/** Everything that CLOSES the import dialog — the footer's Cancel and the
 *  header's ✕ are two doors out of the same room, and the first version of this
 *  fix guarded only one. */
const dialog = src.slice(src.indexOf("Import Bank Statement"));

for (const [which, at] of [
  ["the header's ✕", dialog.indexOf("onClick={onClose}")],
  ["the footer's Cancel", dialog.indexOf("onClick={onClose}", dialog.indexOf("onClick={onClose}") + 1)],
] as const) {
test(`${which} is blocked while IMPORTING, and live while only reading`, () => {
  assert.ok(at > 0, `${which} is gone`);
  const button = dialog.slice(at, at + 260);
  assert.match(button, /disabled=\{importing\}/,
    "closing mid-import unmounts the dialog with the upload still in flight: " +
    "the write continues server-side and the CA never learns whether the " +
    "transactions landed");
  assert.doesNotMatch(button, /disabled=\{busy\}/,
    "a READ is abandonable — nothing has been written — so closing must stay " +
    "live during it rather than trapping the CA in the dialog");
});
}

// ─── What the outcome panel says ────────────────────────────────────────────
//
// Re-uploading a statement that was already in showed a green tick over
// "0 transactions imported", with "475 duplicates skipped" underneath. Both
// numbers were true and the whole thing read as a failure: the CA's next move
// is to try again, on a statement that is already fully imported.
//
// The counter was answering "what did this click add?". The question in the
// CA's head is "is this statement in?".

test("a re-upload leads with the outcome, not with a zero", () => {
  const panel = src.slice(src.indexOf("{result ? ("), src.indexOf("{result ? (") + 2200);
  assert.match(panel, /result\.imported === 0 && result\.duplicates_skipped > 0/,
    "nothing-new-to-add is a different sentence from nothing-happened, and " +
    "the panel has to tell them apart");
  assert.match(panel, /Already imported/,
    "the headline on that branch must say the statement IS in");
  const zeroBranch = panel.slice(panel.indexOf("result.imported === 0"));
  const headline = zeroBranch.slice(0, zeroBranch.indexOf("</p>"));
  assert.doesNotMatch(headline, /\{result\.imported\}/,
    "leading with the count is the bug: on a re-upload the count is 0 and " +
    "reads as a failure");
});

test("the duplicate line never calls a skipped row a 'duplicate' twice over", () => {
  // "475 duplicates skipped (already imported)" said the same thing twice and
  // still did not say the thing that matters — that the LINES are in the books.
  assert.doesNotMatch(src, /skipped \(already imported\)/,
    "replaced by wording that says where the lines ARE");
});
