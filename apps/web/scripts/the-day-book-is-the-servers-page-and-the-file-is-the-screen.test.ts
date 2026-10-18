/**
 * THE DAY BOOK IS THE SERVER'S PAGE, AND THE PDF AND EXCEL FILES ARE THE SCREEN (POST-A-091).
 *
 * Run with:
 *   node --experimental-strip-types --test scripts/the-day-book-is-the-servers-page-and-the-file-is-the-screen.test.ts
 *
 * WHAT WAS WRONG
 *     The Day Book read `journal_entries` straight over PostgREST with every entry's lines embedded, for the whole
 *     period, and summed a debit column out of them in the browser. There was no server function, so there was no PDF
 *     or Excel of the one book an auditor asks for first, and the server's export design forbids a second reader (a
 *     file and a screen that read differently).
 *
 * WHAT THIS HOLDS, FROM THE SCREEN'S SIDE
 *     The server's side (the SQL function and its Python twin agreeing, the export refusing a book that does not foot)
 *     is `apps/api/tests/test_day_book_sql_parity_pg.py` and `test_the_day_book_is_a_server_page...py`. Here:
 *       * the API client has one door to the page and the screen reads it through the shared window reader and says
 *         when it stopped (`has_more` is the server's answer, never a row count compared to a limit);
 *       * the export buttons ask for the whole PERIOD and offer both formats, and the report name is one the export
 *         type carries;
 *       * the table's Amount is the server's own total for a Day Book row, not a sum of lines it no longer has, and the
 *         Status column is not shown there (a Day Book lists posted entries only).
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const WEB = join(import.meta.dirname, "..");

function code(file: string): string {
  return readFileSync(join(WEB, file), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .map((l) => l.replace(/\/\/.*$/, ""))
    .join("\n");
}

const PAGE = "app/clients/[id]/accounting/page.tsx";

test("the api client has one door to the Day Book and it is the server's endpoint", () => {
  const src = code("lib/api/index.ts");
  assert.match(src, /dayBook:\s*\(clientId: string/, "api.accounting.dayBook is missing");
  assert.match(src, /\/api\/accounting\/day-book\?/, "the Day Book is read from /api/accounting/day-book");
  assert.match(src, /export type DayBookPage\b/);
  assert.match(src, /export type DayBookEntry\b/);
});

test("the screen reads the page through the window reader and says when it stopped", () => {
  const src = code(PAGE);
  assert.match(src, /readWindow<DayBookEntry>\(res\.data, "entries"/, "the page is read as a window");
  assert.match(src, /<ListWindowNotice[\s\S]{0,400}hasMore=\{dayBookWindow\.hasMore\}/,
    "a cut-short Day Book must say so, from the server's has_more");
  assert.doesNotMatch(src, /rows?\.length\s*===\s*(?:dayBook)?[lL]imit/,
    "has_more must never be guessed from a row count compared with the limit");
});

test("the export buttons ask for the whole period and offer both formats", () => {
  const src = code(PAGE);
  assert.match(src, /<ReportExportButtons report="day-book"[\s\S]{0,200}formats=\{\["pdf", "xlsx"\]\}/,
    "the Day Book offers a PDF and an Excel file");
  assert.match(src, /params=\{\{ start_date: journalRange\.start, end_date: journalRange\.end \}\}/,
    "the file is for the period on screen, not for the window");
  assert.match(code("lib/export/reportExport.ts"), /\|\s*"day-book"/, "the export report name is part of the type");
});

test("a Day Book row's Amount is the server's total and its Status column is not shown", () => {
  const src = code(PAGE);
  assert.match(src, /function entryAmountPaise\(e: JournalEntry\)[\s\S]{0,200}e\.debit_paise \?\?/,
    "the Amount must prefer the row's own total, which is all a Day Book row carries");
  assert.match(src, /\.\.\.\(dayBook \? \[\] : \[\{ key: "status"/,
    "a Day Book lists posted entries only, so a Status column would say Posted on every row");
  assert.doesNotMatch(src, /reduce\(\(s, l\) => s \+ l\.debit_paise, 0\)\) \/ 100/,
    "no column may re-sum lines by hand beside the helper");
});

// ── what an independent review of this change found on the screen's side (all low, all real) ─────────────────────

test("'Show more' is an ask for ONE client and period, so changing either starts from the server's window in the same render", () => {
  const src = code(PAGE);
  assert.match(src, /useState<\{ key: string; limit: number \} \| null>\(null\)/, "the ask carries the key it was made for");
  assert.match(src, /dayBookAsk && dayBookAsk\.key === dayBookKey \? dayBookAsk\.limit : undefined/);
  assert.match(src, /setDayBookAsk\(\{ key: dayBookKey, limit: n \}\)/);
  assert.doesNotMatch(src, /setDayBookLimit/, "resetting the limit in an effect after the range changed read the new period twice");
});

test("only the newest read writes the screen, and a failed read does not leave the last period's window notice up", () => {
  const src = code(PAGE);
  assert.match(src, /const entriesRequest = useRef\(0\)/);
  assert.match(src, /const mine = \+\+entriesRequest\.current/);
  assert.ok((src.match(/if \(mine !== entriesRequest\.current\) return;/g) ?? []).length >= 3,
    "the Day Book answer, the Journal answer and the failure each ignore a stale read");
  assert.match(src, /if \(mine === entriesRequest\.current\) setEntriesLoading\(false\)/);
  const failure = src.slice(src.indexOf("} catch (e) {", src.indexOf("const mine = ++entriesRequest.current")));
  assert.match(failure.slice(0, 500), /setDayBookWindow\(null\)[\s\S]{0,200}setEntriesError\(/,
    "after a failed read the notice would describe the period before it");
});

test("the Day Book table offers no CSV of its window, because the PDF and Excel files beside it are the period", () => {
  const src = code(PAGE);
  assert.match(src, /exportFilename=\{dayBook \? undefined : "journal"\}/);
  assert.doesNotMatch(src, /exportFilename=\{dayBook \? "day-book"/);
});
