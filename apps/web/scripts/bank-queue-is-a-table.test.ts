// The Categorize queue is a TABLE with a fixed Action column. Run with:
//   node --experimental-strip-types --test scripts/bank-queue-is-a-table.test.ts
//
// WHY THIS EXISTS
//     The queue was a list of cards. Each card stacked a name line, a date line
//     and a control row, and the control row laid out left-to-right from
//     whatever text preceded it — so the primary button sat at x≈625 on a
//     matched row and x≈1251 on the next one. The eye had to re-find the button
//     on every line. Nothing was broken in any way a test of BEHAVIOUR would
//     notice: every button worked, and every row could be cleared. It was
//     simply slow to use, and the person using it could not say why.
//
//     The fix was to copy what QuickBooks does — one line per transaction, and
//     an Action column that is a fixed vertical strip you run straight down.
//     This file is what stops it drifting back, because "make the row a bit
//     more flexible" is a change nobody would flag in review.
//
// WHAT IS ASSERTED
//     1. The queue renders a <table>, with the eight expected column headers in
//        order — including Spent and Received as SEPARATE money columns.
//     2. The action button is in the LAST cell of the row. That is the whole
//        point: a button in the Description or Category cell moves with the
//        text beside it.
//     3. The vocabulary is two verbs. "Post" was our internal word for what
//        happens after a click and it confused the reader, who saw Post, Add
//        and Match for two distinct acts.
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
const PAGE = path.join(__dirname, "..", "app", "clients", "[id]", "bank", "page.tsx");

/** The BankMatchQueue component's source, from its declaration to the next
 *  top-level declaration. Everything asserted here is inside it. */
function queueSource(): string {
  const src = fs.readFileSync(PAGE, "utf8");
  const start = src.indexOf("function BankMatchQueue(");
  assert.ok(start > 0, "BankMatchQueue not found — has the component been renamed?");
  const rest = src.slice(start + 1);
  const nextTop = rest.search(/\n(?:function|const|interface|export) /);
  return nextTop > 0 ? rest.slice(0, nextTop) : rest;
}

test("the parse finds the queue component and it is not trivially short", () => {
  const s = queueSource();
  assert.ok(s.length > 5_000,
    `queueSource() returned ${s.length} chars — the slice is wrong, and every ` +
    "assertion below would pass against an empty string");
});

test("the queue is a table, not a list of cards", () => {
  const s = queueSource();
  assert.match(s, /<table\b/, "the Categorize queue must render a <table>");
  assert.match(s, /<thead>/, "a table with no header row has no columns to align to");
});

test("the columns are the eight, in order, with Spent and Received separate", () => {
  const s = queueSource();
  const thead = s.slice(s.indexOf("<thead>"), s.indexOf("</thead>"));
  assert.ok(thead.length > 100, "the <thead> slice came back empty");

  // The text inside each <th>…</th>. The select-all cell holds JSX whose
  // attribute values contain ">" (`selected.size > 0`), so a naive
  // `<th[^>]*>` closes early on it — keep only cells whose content is a plain
  // short label, which is exactly what a column heading is.
  const headers = [...thead.matchAll(/<th\b[^>]*>([\s\S]*?)<\/th>/g)]
    .map((m) => m[1].replace(/<[^>]*>/g, "").trim())
    .filter((h) => /^[A-Za-z][A-Za-z ]{1,24}$/.test(h));

  assert.deepEqual(headers, [
    "Date", "Description", "Payee", "Category or match", "Spent", "Received", "Action",
  ], "the column set changed — the first <th> is the select-all checkbox and has no text");
});

test("the action button is in the LAST cell of the row", () => {
  const s = queueSource();
  const tbody = s.slice(s.indexOf("<tbody"), s.indexOf("</tbody>"));
  assert.ok(tbody.length > 1_000, "the <tbody> slice came back empty");

  // The first <tr> in the body is the transaction line itself; the expanded
  // detail row follows it and is a single colSpan cell, so it is skipped.
  const rowStart = tbody.indexOf("<tr");
  const rowEnd = tbody.indexOf("</tr>", rowStart);
  const row = tbody.slice(rowStart, rowEnd);
  assert.ok(row.includes("<td"), "no cells found in the transaction row");

  const cells = row.split(/<td\b/).slice(1);
  assert.equal(cells.length, 8, `expected 8 cells in the row, found ${cells.length}`);

  const actionCell = cells[cells.length - 1];
  assert.match(actionCell, /isMatch \? "Match" : "Add"/,
    "the primary Add/Match button must live in the last cell — a button in any " +
    "earlier cell moves horizontally with the text beside it, which is the bug " +
    "this layout exists to fix");

  // And nowhere else. `Match`/`Add` appearing in an earlier cell would mean a
  // second, differently-positioned primary action.
  const earlier = cells.slice(0, -1).join("");
  assert.doesNotMatch(earlier, /isMatch \? "Match" : "Add"/,
    "a primary action button appears outside the Action column");
});

test("two verbs, not three — the queue no longer says Post", () => {
  const s = queueSource();
  // Button LABELS only. The word legitimately appears in identifiers
  // (postRow), in status values ("posted") and in prose explaining which side
  // of a transfer posts the journal — none of those are what the reader
  // clicks, so scan the text between <button …> and </button> and nothing else.
  const labels = [...s.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)]
    .map((m) => m[1])
    // Strip JSX expressions down to just their string literals: the action
    // button's text is `{busy ? "…" : isMatch ? "Match" : "Add"}`.
    .flatMap((body) => [...body.matchAll(/"([^"]*)"/g)].map((q) => q[1])
      .concat(body.replace(/\{[\s\S]*?\}/g, " ").trim()))
    .map((x) => x.trim())
    .filter(Boolean);

  assert.ok(labels.length > 5,
    `only ${labels.length} button labels matched — the scan is not finding them`);
  assert.ok(labels.includes("Match") && labels.includes("Add"),
    `expected both verbs among the labels, got: ${JSON.stringify(labels)}`);
  assert.ok(!labels.includes("Post"),
    'the queue offers "Post" as a button label. Match links this line to a ' +
    "document that already exists; Add creates the entry from a category. " +
    '"Post" is what happens next, not a third thing the reader chooses.');
});
