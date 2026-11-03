// POST-A-126 (items 4 and 5) - two ways a typed-date box lost what it held.
//
// Run with:
//   node --experimental-strip-types --test scripts/a-date-box-is-committed-before-an-overlay-closes-and-a-clear-resets-it.test.ts
//
// WHAT WAS WRONG
//     (5) A typed-date box commits on BLUR. An overlay that hears Escape and asks "you have unsaved changes" reads its dirty flag from the
//         render it is in, which has not seen a date still sitting in the box, so the question would be skipped and the date lost. The
//         employee drawer was fixed by hand. The shared Modal and Drawer, which the other overlays are moving onto, now do it once.
//         The fixed-asset Add and Correct drawers (moved onto the shared Drawer under POST-A-130) are the first that ask before closing; the
//         browser drive of Add Asset (`add-asset`) holds it end to end, and this source guard holds the routing.
//     (4) A box holding text it could not read has already told its parent "no date" (`""`), so a parent that clears to `""` changes
//         nothing the box can see and the unreadable text stayed on screen with its sentence. The contract is a remount with a key;
//         the two Clear buttons that empty date state (the shared table's and the bank book's) did not remount.
//
// THE RULES, NOT SPELLINGS
//     * the shared Modal and Drawer close on Escape through `closeAfterTheFocusedDateCommits`, reading the LATEST onClose when it runs;
//     * every typed-date box carries the marker the helper reads;
//     * any file that hears Escape ITSELF and asks before closing leaves the focused box first (or uses the helper);
//     * a Clear that sets a date filter to "" remounts the date boxes.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));

function tsx(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(path.join(WEB, dir), { withFileTypes: true })) {
    const rel = path.join(dir, e.name);
    if (e.isDirectory()) { if (e.name !== "node_modules" && e.name !== ".next") tsx(rel, out); }
    else if (e.name.endsWith(".tsx")) out.push(rel);
  }
  return out;
}

/** What is wrong with an overlay's Escape branch, as sentences (empty when it is right). */
export function escapeProblems(src: string): string[] {
  const found: string[] = [];
  if (!/import \{ closeAfterTheFocusedDateCommits \} from "@\/lib\/dates\/closeAfterDateCommit"/.test(src)) found.push("does not import the helper");
  if (!/closeAfterTheFocusedDateCommits\(\(\) => onCloseRef\.current\(\)\)/.test(src)) {
    found.push("does not close through the helper with a function that reads the LATEST onClose when it runs");
  }
  if ((src.match(/(?<!=> )onCloseRef\.current\(\)/g) ?? []).length > 0) found.push("calls onCloseRef.current() bare, which skips the commit");
  return found;
}

for (const file of ["components/ui/modal.tsx", "components/ui/drawer.tsx"]) {
  test(`${file}: Escape closes through the helper, and through nothing else`, () => {
    const src = read(file);
    assert.deepEqual(escapeProblems(src), []);
    // negative controls on the real text: each way of getting it wrong is found
    assert.notDeepEqual(escapeProblems(src.replace("closeAfterTheFocusedDateCommits(() => onCloseRef.current())", "onCloseRef.current()")), []);
    assert.notDeepEqual(escapeProblems(src.replace("closeAfterTheFocusedDateCommits(() => onCloseRef.current())", "closeAfterTheFocusedDateCommits(onClose)")), []);
    assert.notDeepEqual(escapeProblems(src.replace(/import \{ closeAfterTheFocusedDateCommits \}[^\n]*\n/, "")), []);
  });
}

test("every typed-date box carries the marker the helper reads", () => {
  const src = read("components/ui/date-input.tsx");
  assert.match(src, /\{\.\.\.\{ \[TYPED_DATE_MARKER\]: "" \}\}/);
});

test("a file that hears Escape itself and asks before closing leaves the focused box first", () => {
  const asks = /\bconfirmLeave\b|\buseUnsavedChanges\b/;
  const hearsEscape = /["']Escape["']/;
  const found = [...tsx("app"), ...tsx("components")]
    .filter((f) => !["components/ui/modal.tsx", "components/ui/drawer.tsx"].includes(f.split(path.sep).join("/")))
    .map((f) => [f, read(f)] as const)
    .filter(([, src]) => hearsEscape.test(src) && asks.test(src));
  assert.ok(found.length >= 1, "the scan found no overlay that hears Escape and asks - it is broken");
  const unsafe = found.filter(([, src]) => !/\.blur\(\)|closeAfterTheFocusedDateCommits/.test(src)).map(([f]) => f);
  assert.deepEqual(unsafe, [],
    "An overlay that hears Escape and asks about unsaved typing reads a stale dirty flag while a date box is still focused. " +
    "Call closeAfterTheFocusedDateCommits(() => latestClose()) from lib/dates/closeAfterDateCommit.");
});

/** What is wrong with the two Clear buttons that empty date state, as sentences (empty when they are right). */
export function clearProblems(table: string, book: string): string[] {
  const found: string[] = [];
  if (!/<FilterControl key=\{`\$\{f\.key\}-\$\{clearedTimes\}`\}/.test(table)) found.push("the table's filter boxes are not keyed on the clear count");
  if ((table.match(/onClick=\{clearAll\}/g) ?? []).length !== 2) found.push("a Clear button of the table does not go through clearAll");
  if (!/const clearAll = \(\) => \{ t\.clearFilters\(\); setQ\(""\); setClearedTimes\(/.test(table)) found.push("clearAll does not bump the clear count");
  if (!/<DateInput key=\{`from-\$\{clearedTimes\}`\}/.test(book) || !/<DateInput key=\{`to-\$\{clearedTimes\}`\}/.test(book)) {
    found.push("the bank book's date boxes are not keyed on the clear count");
  }
  if (!/setDateFrom\(""\); setDateTo\(""\);[^}]*setClearedTimes\(/.test(book)) found.push("the bank book's Clear does not bump the clear count");
  return found;
}

test("the shared table's Clear and the bank book's Clear remount their date boxes", () => {
  const table = read("components/ui/data-table.tsx");
  const book = read("components/banking/BankBook.tsx");
  assert.deepEqual(clearProblems(table, book), []);
  // negative controls on the real text
  assert.notDeepEqual(clearProblems(table.replace("-${clearedTimes}`", "`"), book), []);
  assert.notDeepEqual(clearProblems(table.replace("onClick={clearAll}", "onClick={() => t.clearFilters()}"), book), []);
  assert.notDeepEqual(clearProblems(table.replace("setClearedTimes((n) => n + 1);", ""), book), []);
  assert.notDeepEqual(clearProblems(table, book.replace("key={`from-${clearedTimes}`} ", "")), []);
  assert.notDeepEqual(clearProblems(table, book.replace("setClearedTimes((n) => n + 1); }}", "}}")), []);
});
