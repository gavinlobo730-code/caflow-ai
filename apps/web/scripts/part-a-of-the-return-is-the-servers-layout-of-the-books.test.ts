/**
 * PART A OF ITR-3, ITR-5 AND ITR-6 IS THE SERVER'S LAYOUT OF THE BOOKS, AND THE BROWSER ADDS NOTHING TO IT (POST-A-070).
 *
 * `domain/income_tax/books_schedules.py` decides which box of the return each figure of the books answers, what is left for the CA to
 * split, and the tie-out that proves nothing was dropped. The screen is a READ of `GET /api/itr/filings/{id}/books-schedules`
 * (`components/tax/BooksSchedulesPanel.tsx`) and the §32 screen records which row of the return a block is declared on. What is held here:
 *
 *   * THE PANEL COMPUTES NOTHING: no arithmetic on a figure, no rate, no box path typed in the browser. A path it shows is the server's,
 *     so the screen cannot drift from the Department's schema the server holds it against.
 *   * THE LAYOUT IS CHECKED ON ARRIVAL, not trusted: the filing screen reads `success` (the workspace router answers a refusal as HTTP 200
 *     and a form with no balance sheet is one), takes its lists through `objectWithLists`, and treats the layout as one more action in
 *     flight, so two requests never run together.
 *   * IT SAYS WHAT IT IS NOT: the printed sheet carries "keying aid, not a return", that nothing was submitted, and that the placement
 *     table is not confirmed, in the panel itself, because the sheet is what gets carried to the desk.
 *   * THE §32 SCREEN HOLDS NO LIST OF ROWS AND NO RATE: the rows come from the server, which reads them off the Department's schema; the row is
 *     recorded through its own door (the block's own save replaces the whole row and this screen does not hold what it would put back).
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const WEB = join(import.meta.dirname, "..");
const read = (rel: string) => readFileSync(join(WEB, rel), "utf8");
/** Comments out: this file's neighbours explain in prose what they forbid. */
const code = (rel: string) => read(rel).replace(/\/\*[\s\S]*?\*\//g, " ").replace(/^\s*\/\/.*$/gm, " ");

const PANEL = "components/tax/BooksSchedulesPanel.tsx";
const FILING = "app/clients/[id]/tax/filing/page.tsx";
const SECTION_32 = "app/income-tax/section-32/page.tsx";

test("the panel does no arithmetic on a figure and holds no rate or box path of its own", () => {
  const src = code(PANEL);
  assert.doesNotMatch(src, /\.reduce\(|Math\.|\*\s*100|\/\s*100|parseFloat|parseInt|Number\(/, "the panel computes");
  assert.doesNotMatch(src, /amount_paise\s*[-+*]|[-+*]\s*\w+\.amount_paise/, "the panel adds or subtracts a figure");
  assert.doesNotMatch(src, /ITR\.ITR\d|PARTA_|ScheduleD|Rate\d{1,3}\b/, "a box path or a rate is typed in the browser");
});

test("the panel is typed to the server's answer and shows its sentences", () => {
  // Comments out: a field named only in a comment is a field the panel never reads.
  const src = code(PANEL);
  for (const field of ["tie_out", "mapping_confirmed", "to_key_by_hand", "not_split_paise", "question", "parts_under", "unplaced",
                       "negative_notes", "figures_without_a_box", "notes"]) {
    assert.ok(new RegExp(`\\b${field}\\b`).test(src), `the panel never reads ${field}`);
  }
});

test("a count of lines is not printed as money, and the wording does not promise more than whole-rupee boxes can", () => {
  const src = code(PANEL);
  assert.match(src, /unit: "paise" \| "count"/);
  assert.match(src, /c\.unit === "count"/);
  // The tie-out's two renderings of a difference go through the unit.
  assert.doesNotMatch(src, /formatPaiseBare\(c\.(difference|expected|actual)_paise\)/, "a check's number is printed without its unit");
  // 'should agree' on boxes that are each rounded to whole rupees is a claim of equality the form cannot meet.
  assert.doesNotMatch(src, /they should agree/);
  assert.match(src, /to within that rounding/);
});

test("a depreciation figure the row has no box for is shown on the row, and the gaps are listed once", () => {
  const src = code(PANEL);
  assert.match(src, /r\.figures_without_a_box\.map/);
  assert.match(src, /r\.notes\.map/);
  // dep.gaps are inside sheet.gaps already; rendering both lists printed every depreciation gap twice.
  assert.equal((src.match(/<GapList gaps=\{(sheet|dep)\.gaps\}/g) ?? []).length, 1, "the gaps are listed more than once");
});

test("the printed sheet says it is a keying aid, that nothing was submitted, and that the table is not confirmed", () => {
  const src = read(PANEL);
  assert.match(src, /data-print-scope/);
  assert.match(src, /A keying aid, not a return/);
  assert.match(src, /does not file, and nothing here has been submitted/);
  assert.match(src, /NOT been read against the form's instructions/);
  assert.match(src, /!sheet\.mapping_confirmed/, "the unconfirmed notice must depend on the server's flag, not be a constant");
});

test("a total whose parts the books do not hold is not offered as a figure to key", () => {
  const src = read(PANEL);
  assert.match(src, /s\.role === "box"/);
  assert.match(src, /Key its parts under/);
  assert.match(src, /is not split in the books/);
  // A figure the form's names do not place is shown beside the boxes it could be, and not written into one.
  assert.match(src, /not written into a box/);
});

test("the filing screen checks the layout on arrival and counts it as an action in flight", () => {
  const src = code(FILING);
  const fn = src.slice(src.indexOf("async function loadBooksSchedules"), src.indexOf("async function loadBooksSchedules") + 1100);
  assert.match(fn, /\/api\/itr\/filings\/\$\{filing\.id\}\/books-schedules/);
  assert.match(fn, /if \(!res\.success\)/, "a refusal arrives as HTTP 200 with success:false");
  assert.match(fn, /objectWithLists<BooksSchedules>\(res\.data, "gaps"\)/);
  assert.match(src, /actionInFlight = [^;]*booksLoading/);
  const button = src.slice(src.indexOf("loadBooksSchedules(selectedFiling)") - 80, src.indexOf("loadBooksSchedules(selectedFiling)") + 260);
  assert.match(button, /disabled=\{actionInFlight\}/);
});

test("a sheet belongs to the filing it was built for: choosing another clears it and a late answer is dropped", () => {
  const src = code(FILING);
  const choose = src.slice(src.indexOf("function chooseFiling"), src.indexOf("function chooseFiling") + 520);
  for (const clear of ["setSheet(null)", "setSheetError(null)", "setBooksSchedules(null)", "setBooksError(null)"]) {
    assert.ok(choose.includes(clear), `choosing a filing does not run ${clear}`);
  }
  assert.match(choose, /sheetFor\.current = f\?\.id \?\? null/);
  // Every way of changing the selection goes through it: no bare setter is left beside it.
  assert.equal((src.match(/setSelectedFiling\(/g) ?? []).length, 1, "the one call is inside chooseFiling; a bare setter elsewhere leaves a sheet under the wrong filing");
  assert.match(src, /onClick=\{\(\) => chooseFiling\(f\)\}/);
  assert.match(src, /onClick=\{\(\) => chooseFiling\(null\)\}/);
  // Both loaders look again after the await: the CA may have chosen another filing while the request was out.
  for (const loader of ["loadKeyingSheet", "loadBooksSchedules"]) {
    const fn = src.slice(src.indexOf(`async function ${loader}`), src.indexOf(`async function ${loader}`) + 1500);
    const after = fn.slice(fn.indexOf("await apiFetch"));
    assert.ok(after.indexOf("sheetFor.current !== filing.id") > -1 && after.indexOf("sheetFor.current !== filing.id") < after.indexOf("setSheet") + 400,
      `${loader} does not drop an answer for a filing that is no longer open`);
    assert.ok(after.indexOf("sheetFor.current !== filing.id") < after.search(/set(Sheet|BooksSchedules)\(objectWithLists/),
      `${loader} checks the filing after it has already stored the answer`);
  }
});

test("one printable sheet is open at a time", () => {
  const src = code(FILING);
  const keying = src.slice(src.indexOf("async function loadKeyingSheet"), src.indexOf("async function loadKeyingSheet") + 400);
  const books = src.slice(src.indexOf("async function loadBooksSchedules"), src.indexOf("async function loadBooksSchedules") + 400);
  assert.match(keying, /setBooksSchedules\(null\)/);
  assert.match(books, /setSheet\(null\)/);
});

test("the §32 screen holds no list of rows and no rate, and records a row through its own door", () => {
  const src = code(SECTION_32);
  assert.doesNotMatch(src, /PlantMachinery|FurnitureFittings|IntangibleAssets|Building\.Rate|Rate\d{1,3}\b/);
  assert.match(src, /\/api\/income-tax\/section-32\/itr-rows/);
  assert.match(src, /\/api\/income-tax\/section-32\/blocks\/row/);
  const dialog = src.slice(src.indexOf("function AddBlockDialog"));
  assert.match(dialog, /\.\.\.\(itrRow \? \{ itr_schedule_row: itrRow \} : \{\}\)/,
    "the dialog must not send the row when none was chosen, or re-adding a block would clear the row somebody recorded");
  const row = src.slice(src.indexOf("async function recordRow"), src.indexOf("async function recordRow") + 700);
  assert.match(row, /itr_schedule_row: row/);
  assert.doesNotMatch(row, /opening_wdv_paise|assets_remain/, "the row's door must not carry the block's other facts");
});

test("the §32 screen waits for one write before starting another", () => {
  const src = code(SECTION_32);
  assert.match(src, /const busy = savingBusiness \|\| savingRow !== null/);
  assert.match(src, /disabled=\{busy\}\s*\n\s*onChange=\{e => recordRow/);
  assert.equal((src.match(/disabled=\{busy\}/g) ?? []).length >= 3, true, "the two §32(1)(iia) buttons and the row select all wait");
});
