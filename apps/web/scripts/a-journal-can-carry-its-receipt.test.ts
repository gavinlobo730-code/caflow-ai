// ACC-25, the frontend half. The kernel, the model and the database have all
// taken supporting documents since migration 138; the journal editor had no
// control, so the reason for a coding lived in somebody's email.
//
// Narrow on purpose. What must not change: the editor SENDS them, it does not
// re-implement the server's scheme rule, an existing entry's attachments are
// shown rather than silently dropped on the next save, and a link opens
// without handing the app's tab to somebody else's host.
//
// Run with: node --experimental-strip-types --test scripts/a-journal-can-carry-its-receipt.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const EDITOR = path.join(__dirname, "..", "components", "journal", "JournalEditor.tsx");
const PAGE = path.join(__dirname, "..", "app", "clients", "[id]", "accounting",
                       "journal", "[entryId]", "edit", "_page.tsx");
const editor = stripComments(fs.readFileSync(EDITOR, "utf8"));
const page = stripComments(fs.readFileSync(PAGE, "utf8"));

test("the editor collects supporting documents", () => {
  assert.match(editor, /const \[attachments, setAttachments\] = useState/);
  assert.match(editor, /aria-label="Document name"/);
  assert.match(editor, /aria-label="Document link"/);
});

test("what is collected is what is sent", () => {
  // The payload, not just the state — a control whose value never leaves the
  // component is the defect this closes, one layer up.
  assert.match(editor, /narration: narration\.trim\(\),\s*lines: out,\s*attachments,/);
  assert.match(page, /attachments: payload\.attachments,/);
});

test("an existing entry's attachments are loaded, not dropped", () => {
  // Without this, opening a posted entry and saving it would silently remove
  // every document already on it.
  assert.match(editor, /existing\?\.attachments \?\? \[\]/);
});

test("the browser does not keep its own copy of the scheme rule", () => {
  // domain/attachments is the one place that decides what a safe link is, and
  // its vocabulary is closed rather than sanitised. A second, weaker check
  // here would diverge and teach a CA the wrong limit.
  assert.doesNotMatch(editor, /javascript:|startsWith\(["'`]https/,
    "the editor is re-implementing the server's link rule");
});

test("a stored link cannot reach back into this tab", () => {
  // The link is somebody else's host by construction; window.opener would hand
  // it this app's tab.
  assert.match(editor, /target="_blank" rel="noreferrer"/);
});

test("an attachment can be taken off again", () => {
  // A CA who attached the wrong receipt must be able to remove it — a one-way
  // control on a document that justifies a ledger entry is the wrong
  // affordance.
  assert.match(editor, /setAttachments\(attachments\.filter\(\(_, j\) => j !== i\)\)/);
});

test("a locked OR POSTED entry shows its documents and offers no controls", () => {
  // Bounded to the panel — the lines table below it has readOnly gates of its
  // own, and an unbounded slice counted those too.
  const from = editor.indexOf("Supporting documents");
  const to = editor.indexOf('<div className="overflow-x-auto">', from);
  assert.ok(from >= 0 && to > from, "the panel's bounds moved — re-anchor this test");
  const panel = editor.slice(from, to);
  // BOTH gates, counted. A first draft matched the phrase once and passed with
  // the ADD row ungated, because the remove button's own gate satisfied it.
  const gates = panel.match(/\{!attachmentsReadOnly && \(/g) ?? [];
  assert.equal(gates.length, 2,
    "both the remove button and the add row must be gated");
  // And the gate must be the STRICTER one. `readOnly` alone is a locked period
  // or a filed return; a POSTED entry is otherwise editable and still cannot
  // take a document, because prevent_posted_journal_modification lets its
  // header move only inside edit_posted_journal — which rewrites LINES and
  // carries no attachments. Gating on readOnly would render an add control
  // whose value the PATCH refuses.
  assert.doesNotMatch(panel, /\{!readOnly && \(/,
    "the panel must gate on attachmentsReadOnly, which also covers a posted entry");
  assert.match(editor, /const attachmentsReadOnly = readOnly \|\| isPosted;/);
});

test("a posted entry's documents are not sent on a correction", () => {
  // The server refuses them with a sentence; sending them anyway would turn
  // every correction of a posted entry into a 422.
  assert.match(page, /entry\?\.is_posted \? \{\} : \{ attachments: payload\.attachments \}/);
});

test("a DRAFT correction sends them", () => {
  // The half that was missing: the editor rendered the control on an entry
  // being corrected and the PATCH sent everything except it, so the CA typed a
  // link and lost it with no error.
  assert.match(page, /attachments: payload\.attachments/);
});
