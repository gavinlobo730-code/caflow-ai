// An editor of an issued document does not ask the create-time check of it (POST-A-425). Run with:
//   node --experimental-strip-types --test scripts/an-issued-document-editor-is-not-asked-for-its-create-time-check.test.ts
//
// WHY THIS EXISTS
//     Six editors open an invoice, a bill or a note, and each knows when the document it holds is no longer a draft:
//     `const isLocked = isEdit && existing?.status !== "draft"`. An issued document's save sends only the particulars the
//     server still lets move (the note, the reference, the due date, the attached copy) and never its lines, so the check
//     that a NEW document has a vendor, a date and a line naming a catalogue item has nothing to say about it. The invoice
//     editor and the two sales note editors skipped it. The two purchase note editors and the purchase bill editor asked it,
//     so an issued note or a received bill with a line saved before the catalogue item became mandatory (migration 206), or
//     a blocked line with no clause, could not have its note or its attached copy changed whatever the screen said, and the
//     frozen lines turned red after the press.
//
// WHAT IS ASSERTED
//     The rule, over every editor that declares that lock and keeps an `attempted` flag (found by those two declarations and
//     not by a list of files): every read of `attempted`, and every read of `validation.ok` in any form, has `!isLocked` before
//     it on its line. A new editor of an issued document is held the same way without being named here (the first test names
//     the six that exist, so one that drops or renames its lock is a loud failure and not a silent exemption).
//     The checker is itself run against lines that break the rule, comments that look like code and a block comment that
//     contains `//`, so a pattern that matches nothing cannot pass. It is line-granular on purpose: a gate on one line and the
//     use on the next is a failure to be rewritten onto one line, never a silent pass.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");

function* walk(dir: string): Generator<string> {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "node_modules" || entry.name === ".next" || entry.name === "out") continue;
      yield* walk(full);
    } else if (entry.name.endsWith(".tsx")) yield full;
  }
}

/** A line with its comments removed: a block comment that opens and closes on it, then a line comment (`//` after a space or at the start, so a `//` inside a URL string is not one). */
function code(line: string): string {
  return line.replace(/\/\*.*?\*\//g, " ").replace(/(^|\s)\/\/.*$/, "$1");
}

const LOCK = /const isLocked\s*=/;
const FLAG = /const \[attempted, setAttempted\] = useState\(false\)/;
/** The two things an editor asks of a document: whether a save was attempted (for the messages) and whether the check passed. */
const ASKS = /\battempted\b|\bvalidation\.ok\b/g;

/** The lines of a source that ask the create-time check of a document without first saying `!isLocked` on the same line. A multi-line block comment is skipped; a use is the flag read or any read of `validation.ok`. */
export function ungated(src: string): string[] {
  const out: string[] = [];
  let inBlock = false;
  src.split("\n").forEach((raw, i) => {
    let line = raw;
    if (inBlock) {
      const end = line.indexOf("*/");
      if (end < 0) return;
      inBlock = false;
      line = line.slice(end + 2);
    }
    line = code(line);
    const open = line.indexOf("/*");
    if (open >= 0) { inBlock = true; line = line.slice(0, open); }
    if (FLAG.test(line) || /\bsetAttempted\b/.test(line)) return;
    for (const m of line.matchAll(ASKS)) {
      if (!line.slice(0, m.index).includes("!isLocked")) { out.push(`${i + 1}: ${raw.trim()}`); break; }
    }
  });
  return out;
}

const editors = [...walk(path.join(root, "components")), ...walk(path.join(root, "app"))]
  .map((file) => ({ file, rel: path.relative(root, file), src: fs.readFileSync(file, "utf8") }))
  .filter(({ src }) => LOCK.test(src) && FLAG.test(src));

test("the editors of an issued document are found by their lock, and there are six", () => {
  assert.deepEqual(
    editors.map((e) => e.rel).sort(),
    [
      "components/invoices/InvoiceEditor.tsx",
      "components/purchases/DebitNoteEditor.tsx",
      "components/purchases/PurchaseBillEditor.tsx",
      "components/purchases/PurchaseCreditNoteEditor.tsx",
      "components/sales/SalesCreditNoteEditor.tsx",
      "components/sales/SalesDebitNoteEditor.tsx",
    ],
    "a new editor of an issued document is held by this rule: name it here once it exists, and one that went missing is a finding",
  );
});

for (const { rel, src } of editors) {
  test(`${rel} asks the create-time check only of a document that is still a draft`, () => {
    assert.ok(src.length > 4000, "the editor was read");
    assert.ok(/\bvalidation\.ok\b/.test(src), "the editor asks a check at all, or this rule has nothing to hold");
    assert.deepEqual(ungated(src), [], "every use of `attempted` and every `!validation.ok` must also say `!isLocked`");
  });
}

test("the checker sees a use that does not say the lock before it", () => {
  const broken = [
    "  const [attempted, setAttempted] = useState(false);",
    "  async function save() {",
    "    setAttempted(true);",
    "    if (!validation.ok) { return; }",
    "    // if (!validation.ok) in a comment is not code",
    "  }",
    "  const fieldErr = (msg?: string) => (attempted && msg ? 1 : null);",
    "  const ok = !isLocked && attempted && !validation.ok;",
    "  const late = attempted && !isLocked;",
    "  const label = validation.ok ? 'a' : 'b';",
    "  {/* see x // note */}",
    "  if (!validation.ok) return;",
    "  /* a block",
    "     if (!validation.ok) return; */",
    "  if (!validation.ok) return;",
  ].join("\n");
  assert.deepEqual(ungated(broken), [
    "4: if (!validation.ok) { return; }",
    "7: const fieldErr = (msg?: string) => (attempted && msg ? 1 : null);",
    "9: const late = attempted && !isLocked;",
    "10: const label = validation.ok ? 'a' : 'b';",
    "12: if (!validation.ok) return;",
    "15: if (!validation.ok) return;",
  ]);
});
