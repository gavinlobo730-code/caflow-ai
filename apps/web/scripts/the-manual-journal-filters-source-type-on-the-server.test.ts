/**
 * JournalList.loadEntries keyset-pages EVERY posted journal entry for the FY
 * with journal_lines embedded, and mode 'manual' then discarded everything
 * except source_type === 'manual' in the BROWSER — so a client with
 * thousands of entries and zero manual ones paged the whole FY just to show
 * zero rows (apex-accounting-reports-11).
 *
 * THE RULE
 *
 *   `mode='manual'` adds `.eq("source_type", "manual")` to the actual
 *   query builder passed to selectAllKeyset, so a client with 0 manual
 *   entries reads 0 rows server-side. Day Book (`dayBook` true) must NOT
 *   carry that filter — it exists to show every posting.
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
  assert.match(
    body, /if\s*\(!dayBook\)\s*q\s*=\s*q\.eq\(\s*"source_type"\s*,\s*"manual"\s*\)/,
    "the query builder passed to selectAllKeyset must add " +
    '.eq("source_type", "manual") when this is the manual Journal tab ' +
    "(dayBook false), so a client with zero manual entries reads zero rows " +
    "server-side instead of paging the whole FY's postings to discard them " +
    "in the browser.",
  );
});

test("the Day Book (dayBook true) still reads every source_type", () => {
  const src = code(readFileSync(FILE, "utf8"));
  const body = loadEntriesBody(src);
  // The filter must be conditional on dayBook, not unconditional — an
  // unconditional filter would break the Day Book, which exists precisely
  // to show every posting regardless of source_type.
  assert.match(body, /if\s*\(!dayBook\)/, "the source_type filter must be conditional on dayBook");
});
