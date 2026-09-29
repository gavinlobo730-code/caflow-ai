/**
 * The Dashboard's "Posted Entries (FY)" card and its "View all" link both
 * navigated to the Journal tab, which JournalList (mode 'manual') filters to
 * source_type === 'manual' in the BROWSER — so a client with thousands of
 * posted entries and zero manual ones saw "No manual journal entries"
 * (apex-accounting-reports-10).
 *
 * THE RULE
 *
 *   Both dashboard actions navigate to "day-book" (the tab that renders
 *   JournalList with mode="day_book", which is unfiltered by source_type),
 *   never "journal".
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

test('the "Posted Entries (FY)" dashboard card navigates to the Day Book', () => {
  const src = code(readFileSync(FILE, "utf8"));
  const line = src.split("\n").find((l) => l.includes('label="Posted Entries (FY)"'));
  assert.ok(line, 'expected a DashCard with label="Posted Entries (FY)"');
  assert.match(
    line!, /onNavigate\("day-book"\)/,
    'the "Posted Entries (FY)" card must navigate to "day-book" (unfiltered by ' +
    'source_type), not "journal" (which JournalList filters to source_type ' +
    '=== "manual" in the browser, so a client with 0 manual entries but many ' +
    'posted ones would land on an empty screen).',
  );
});

test('the recent-entries "View all" link navigates to the Day Book', () => {
  const src = code(readFileSync(FILE, "utf8"));
  const idx = src.indexOf("View all");
  assert.ok(idx >= 0, 'expected a "View all" link');
  const before = src.slice(Math.max(0, idx - 200), idx);
  assert.match(
    before, /onNavigate\("day-book"\)/,
    'the "View all" link beside Recently Posted must navigate to "day-book", ' +
    'not "journal", for the same reason as the Posted Entries card above.',
  );
});
