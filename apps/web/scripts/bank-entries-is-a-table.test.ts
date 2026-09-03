// The Entries screen is a TABLE with a fixed Action column and ONE verb. Run with:
//   node --experimental-strip-types --test scripts/bank-entries-is-a-table.test.ts
//
// WHY THIS EXISTS
//     The queue was once a list of cards whose primary button sat at x≈625 on
//     one row and x≈1251 on the next; the eye had to re-find it on every line.
//     Nothing a test of BEHAVIOUR would notice was wrong — every button worked
//     — it was simply slow to use. The fix was one line per transaction and an
//     Action column that is a fixed strip you run straight down. This file is
//     what stops it drifting back, because "make the row a bit more flexible"
//     is a change nobody would flag in review.
//
//     The screen was rebuilt around ENTRIES on 2026-09-03
//     (docs/architecture/09-bank-entries.md): the draft is on the row, the
//     state is a stored column, and the verb is Pass. The properties below are
//     the same ones the old queue test held, re-pointed at the new files.
//
// WHAT IS ASSERTED
//     1. The list renders the shared DataTable with the six columns, in order —
//        Spent and Received SEPARATE, and an Entry column that says what the
//        line is or is about to become (the column the old screen had removed,
//        which is why "where did the suggestion go" had no answer).
//     2. The action is rowActions — the fixed trailing column — and no column's
//        render carries a primary button.
//     3. ONE verb. Pass, on the row and in the modal. Not Post, not Match, not
//        Add, not Record: those were three words for one act.
//     4. The row offers no ranked candidate list; candidates live in the modal,
//        behind opening the line. The two ways out of an unanswerable line —
//        find the document, split it — are the largest controls in the modal.
//
//     Each assertion is preceded by a check that the parse found anything at
//     all, because a selector that silently matches nothing passes every test
//     after it.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const TAB = path.join(__dirname, "..", "components", "banking", "EntriesTab.tsx");
const MODAL = path.join(__dirname, "..", "components", "banking", "EntryDetailModal.tsx");

const tab = () => fs.readFileSync(TAB, "utf8");
const modal = () => fs.readFileSync(MODAL, "utf8");

/** Every button's visible text. A <button …> tag spans lines and its
 *  attributes contain `=>`, so the tag cannot be matched with `[^>]*`; the
 *  label is instead the tail of the chunk before each </button>, after the
 *  last tag close (`">`, `}>` or `/>`). Both plain text and the string
 *  literals of a `{cond ? "…" : "Pass"}` expression count. */
function buttonLabels(src: string): string[] {
  const chunks = src.split("</button>").slice(0, -1);
  return chunks.flatMap((chunk) => {
    const cut = Math.max(chunk.lastIndexOf('">'), chunk.lastIndexOf("}>"), chunk.lastIndexOf("/>"));
    const tail = chunk.slice(cut + 2);
    const quoted = [...tail.matchAll(/"([^"]*)"/g)].map((q) => q[1]);
    const plain = tail.replace(/\{[\s\S]*?\}/g, " ").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
    return quoted.concat(plain);
  }).map((x) => x.trim()).filter(Boolean);
}

test("the files exist and are not trivially short", () => {
  assert.ok(tab().length > 10_000, "EntriesTab.tsx is suspiciously short");
  assert.ok(modal().length > 8_000, "EntryDetailModal.tsx is suspiciously short");
});

test("the list is the shared DataTable, not a hand-rolled table or cards", () => {
  const s = tab();
  assert.match(s, /<DataTable\b/, "Entries must render the shared DataTable");
  assert.match(s, /columns=\{columns\}/, "it must pass its column set");
  assert.doesNotMatch(s, /<table\b/, "no hand-rolled <table> beside the DataTable");
});

test("the columns are the six, in order, with Entry present and Spent/Received separate", () => {
  const s = tab();
  const decl = s.slice(s.indexOf("const columns: Column<Entry>[]"));
  assert.ok(decl.length > 500, "the columns declaration came back empty");
  const body = decl.slice(0, decl.indexOf("\n  ];"));
  assert.ok(body.length > 400, "the columns body came back empty");
  const headers = [...body.matchAll(/header:\s*"([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(headers, ["Date", "Bank narration", "Entry", "Spent", "Received", "Status"],
    "the column set changed. Entry is the column that says what the line is or " +
    "is about to become — the one the old screen removed. Spent and Received are " +
    "SEPARATE on purpose. Action is rowActions, always last.");
});

test("the action is the fixed trailing column, and no column renders a primary button", () => {
  const s = tab();
  assert.match(s, /rowActions=\{actionCell\}/, "the row's one control must be rowActions");
  const decl = s.slice(s.indexOf("const columns: Column<Entry>[]"));
  const body = decl.slice(0, decl.indexOf("\n  ];"));
  assert.doesNotMatch(body, /<button/, "a column's render is producing a button");
});

test("one verb: Pass — on the row and in the modal; never Post, Match, Add or Record", () => {
  for (const [name, src] of [["EntriesTab", tab()], ["EntryDetailModal", modal()]] as const) {
    const labels = buttonLabels(src);
    assert.ok(labels.length > 5, `${name}: only ${labels.length} button labels matched`);
    assert.ok(labels.includes("Pass"), `${name}: expected "Pass" among ${JSON.stringify(labels)}`);
    for (const bad of ["Post", "Match", "Add", "Record"]) {
      assert.ok(!labels.includes(bad), `${name}: offers "${bad}" as a button label — the verb is Pass`);
    }
  }
});

test("the row offers no ranked candidate list; the modal does, behind opening the line", () => {
  const s = tab();
  assert.doesNotMatch(s, /\.suggestions\b/, "the row is reaching into ranked candidates — they belong in the modal");
  assert.doesNotMatch(s, /confidence_label/, "confidence badges belong to the modal's list, not the row");
  assert.match(modal(), /t\.suggestions/, "the modal must offer the candidates");
});

test("the two ways out of an unanswerable line are the largest controls in the modal", () => {
  const m = modal();
  for (const label of ["Find the ", "Split across several"]) {
    const at = m.indexOf(label);
    assert.ok(at > 0, `"${label}" is missing from the modal`);
    const btn = m.lastIndexOf("<button", at);
    const cls = m.slice(btn, at);
    assert.match(cls, /text-xs/, `"${label}" is back to a smaller type size than the rest of the modal`);
    assert.match(cls, /px-3 py-1\.5/, `"${label}" is back to a link-sized hit area`);
  }
});

test("the state is read, never decided, in the browser", () => {
  // The old screen kept its own copy of "which rows are confident"
  // (readyRow / confidentMatch). The database decides entry_state now, and a
  // browser-side reimplementation is exactly the drift 09-bank-entries.md
  // exists to prevent.
  for (const src of [tab(), modal()]) {
    assert.doesNotMatch(src, /\bconfidentMatch\b|\breadyRow\b|\breadyToAdd\b/,
      "a browser-side confidence rule is back");
  }
  assert.match(tab(), /t\.entry_state/, "the row must read the stored state");
});
