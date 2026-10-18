/**
 * JournalList.loadEntries keyset-pages EVERY posted journal entry for the FY
 * with journal_lines embedded, and mode 'manual' then discarded everything
 * except source_type === 'manual' in the BROWSER — so a client with
 * thousands of entries and zero manual ones paged the whole FY just to show
 * zero rows (apex-accounting-reports-11).
 *
 * THE RULE
 *
 *   The Journal tab's query adds `.eq("source_type", "manual")` to the actual
 *   query builder passed to selectAllKeyset, so a client with 0 manual
 *   entries reads 0 rows server-side.
 *
 *   THE DAY BOOK DOES NOT REACH THAT QUERY AT ALL (POST-A-091). It shows every
 *   posting, so the filter could never apply to it, and it used to share this
 *   very read and its embedded lines; it now returns BEFORE the browser's read,
 *   asking the server's `api.accounting.dayBook` for a page the database cuts.
 *   The filter is therefore unconditional on the path that remains: a
 *   conditional one would be a Day Book branch nothing can reach.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const FILE = join(import.meta.dirname, "..", "app/clients/[id]/accounting/page.tsx");

function code(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .map((l) => l.replace(/\/\/.*$/, ""))
    .join("\n");
}

function loadEntriesBody(src: string): string {
  const start = src.indexOf("const loadEntries = useCallback(");
  assert.ok(start >= 0, "expected to find loadEntries's useCallback");
  const end = src.indexOf("useEffect(() => { loadEntries(); }", start);
  assert.ok(end > start, "expected to find the end of loadEntries");
  return src.slice(start, end);
}

test("loadEntries filters source_type='manual' server-side for the Journal tab", () => {
  const src = code(readFileSync(FILE, "utf8"));
  const body = loadEntriesBody(src);
  const direct = body.slice(body.indexOf('.from("journal_entries")'));
  assert.match(
    direct, /\.eq\(\s*"source_type"\s*,\s*"manual"\s*\)/,
    "the query builder passed to selectAllKeyset must add " +
    '.eq("source_type", "manual"), so a client with zero manual entries reads ' +
    "zero rows server-side instead of paging the whole FY's postings to discard " +
    "them in the browser.",
  );
  assert.doesNotMatch(direct, /if\s*\(!dayBook\)\s*q\s*=/,
    "the filter is unconditional on the path the Day Book never takes");
});

test("the Day Book returns before the browser's read of journal_entries and asks the server", () => {
  const src = code(readFileSync(FILE, "utf8"));
  const body = loadEntriesBody(src);
  const start = body.indexOf("if (dayBook)");
  assert.ok(start >= 0 && start < body.indexOf('.from("journal_entries")'),
    "the Day Book branch must come before the direct read");
  const returned = body.indexOf("return;", start);
  assert.ok(returned > start && returned < body.indexOf('.from("journal_entries")'),
    "the Day Book branch must return before the Journal tab's direct read");
  const dayBookBranch = body.slice(start, returned + "return;".length);
  assert.match(dayBookBranch, /api\.accounting\.dayBook\(/, "the Day Book reads the server's page");
  assert.doesNotMatch(dayBookBranch, /\.from\(|selectAll/,
    "the Day Book must not read journal_entries itself: a second reader is how a file and a screen disagree");
  assert.equal((body.match(/\.from\("journal_entries"\)/g) ?? []).length, 1,
    "exactly one browser read of journal_entries remains in loadEntries, and it is the Journal tab's");
});
