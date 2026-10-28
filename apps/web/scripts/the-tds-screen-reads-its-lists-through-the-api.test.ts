// The TDS screen reads a client's deductions, challans, returns and certificates through the API, which orders, cuts and counts them, and
// the browser adds nothing up (POST-A-276, POST-A-278).
//
// WHAT THE SCREEN DID (found by the independent reviews of the deposit-state change, 20-10-2026)
//   * it fetched `tds_deductions`, `tds_challans`, `tds_returns` and `tds_certificates` itself over PostgREST, where `rbac()` and the
//     caller's client assignment never run, and paged a client's whole year of deductions into the browser;
//   * it counted "Returns Due" (returns not in a filed status) and "Certificates Pending" over those rows, derived a return's Overdue state
//     from its due date in the browser and summed the gross and tax columns for the footer;
//   * the Challans tab's Status column printed a field `create_challan` always writes as `deposited`;
//   * it kept a copy of fifteen sections and their names, which held neither §194T nor §195, so a challan under either could not be
//     recorded on it.
//
// The backend half is `apps/api/tests/test_the_tds_screen_reads_its_four_lists_as_windows_the_server_cuts_and_counts.py`. This is the
// other end: a screen that went back to reading the tables, or to adding rows up, would make the server's care pointless.
//
// Run with: node --experimental-strip-types --test scripts/the-tds-screen-reads-its-lists-through-the-api.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const WEB = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));
const PAGE = read("app/tds/page.tsx");
const TAB = read("app/clients/[id]/compliance/tds/page.tsx");
const DATA = read("lib/data/tds.ts");

test("the page is where this guard thinks it is", () => {
  assert.ok(PAGE.length > 20000, `app/tds/page.tsx read as ${PAGE.length} chars`);
  assert.ok(TAB.length > 20000, `the client's TDS tab read as ${TAB.length} chars`);
});

test("the TDS screen reads no table itself: no database client, no pager, no firm id", () => {
  assert.ok(!/getSupabaseClient|selectAll|getFirmId|\.from\(\s*["']tds_/.test(PAGE),
    "app/tds/page.tsx reads a table straight from the database again (rbac() and the client assignment never run there)");
  for (const reader of ["listTdsDeductions", "listTdsChallans", "listTdsReturns", "listTdsCertificates"]) {
    assert.ok(PAGE.includes(`${reader}(clientId`), `the page does not read through ${reader}`);
  }
});

test("the data module's four readers ask the API for a window at the ceiling and read it as a window", () => {
  for (const [fn, endpoint, field] of [["listTdsDeductions", "deductions", "deductions"], ["listTdsChallans", "challans", "challans"],
    ["listTdsReturns", "returns", "returns"], ["listTdsCertificates", "certificates", "certificates"]]) {
    const at = DATA.indexOf(`export const ${fn}`);
    assert.ok(at > 0, `${fn} is missing`);
    const body = DATA.slice(at, at + 520);
    assert.ok(body.includes(`/api/tds-workspace/${endpoint}?`) && body.includes(`"${field}"`), `${fn} does not ask /${endpoint} for its ${field}`);
  }
  assert.ok(/limit=\$\{TDS_REGISTER_WINDOW_MAX\}/.test(DATA) && /readWindow<T>\(resp\.data, rowsField, TDS_REGISTER_WINDOW_MAX\)/.test(DATA),
    "the readers do not ask for the ceiling or do not read the answer as a window");
});

test("every figure on the screen is the server's: no sum, no count and no overdue test over rows the page holds", () => {
  assert.ok(!/(deductions|challans|returns|certificates)\.(reduce|filter)\(/.test(PAGE), "the page adds up or counts a list it holds");
  assert.ok(!/todayIstISO|r\.due_date\s*<|c\.status === "pending"/.test(PAGE), "the page decides Overdue or Pending itself");
  assert.ok(!/const FILED\b|FILED\.has/.test(PAGE), "the page keeps its own list of filed statuses");
  assert.ok(/deductionTotals\.payment_amount_paise/.test(PAGE) && /deductionTotals\.tds_paise/.test(PAGE), "the footer is not the server's totals");
  assert.ok(/returnCounts\.not_filed/.test(PAGE) && /returnCounts\.filed/.test(PAGE) && /returnCounts\.overdue/.test(PAGE), "the Returns tab is not the server's counts");
  assert.ok(/certificateCounts\.pending/.test(PAGE), "the Certificates Pending card is not the server's count");
});

test("a list that the server cut short says so, and a refused read is said, not shown as an empty list", () => {
  assert.equal((PAGE.match(/<ListWindowNotice /g) ?? []).length, 3, "deductions, challans and certificates each say when the server stopped them");
  assert.ok(/setTableError\(failures\.length > 0\)/.test(PAGE) && /Promise\.allSettled\(/.test(PAGE), "a failed list is not said");
  assert.ok(!/arrayOrEmpty/.test(TAB.replace(/`arrayOrEmpty`[^\n]*/g, "")), "the client's TDS tab reads a window as a bare array (every list would read as empty)");
  assert.equal((TAB.match(/loadTdsWindow\(clientId, "/g) ?? []).length, 4, "the four tabs do not all read their window the same way");
  assert.equal((TAB.match(/<ListWindowNotice /g) ?? []).length, 4, "a tab does not say when the server cut its list short");
  assert.equal((TAB.match(/setRows\(rows\); setMore\(hasMore\); setLoadError\(null\);/g) ?? []).length, 4, "a tab drops the server's has_more");
});

test("the Challans tab prints no Status column (the server writes `deposited` for every challan) and shows the minor head instead", () => {
  assert.ok(!/"Section", "Status"/.test(PAGE), "the Challans tab has a Status column again");
  assert.ok(/\["BSR Code", "Payment Date", "Challan No\.", "Amount", "Period", "FY", "Section", "Minor head"\]/.test(PAGE), "the Challans tab's columns changed");
  assert.ok(/\{minorHeadLabel\(c\.minor_head\)\}/.test(PAGE), "the list does not tell a demand payment (400) from tax paid over (200)");
  assert.ok(!/MINOR_HEAD_LABEL\[c\.minor_head/.test(PAGE), "the list reads the head with a fallback to 200: an unknown head would read as the ordinary one");
  // The client's own Compliance -> TDS Challans tab says the same thing in the same words, from the same module.
  assert.ok(!/<th[^>]*>Status<\/th>/.test(TAB.slice(TAB.indexOf("function ChallansTab"), TAB.indexOf("function ReturnsTab"))),
    "the client's Challans tab prints a Status column again (the one value the server writes)");
  assert.ok(/<th[^>]*>Minor head<\/th>/.test(TAB) && /\{minorHeadLabel\(r\.minor_head\)\}/.test(TAB), "the client's Challans tab does not show the minor head");
  // The words are held once, in lib/tds/minorHead.ts.
  const MODULE = read("lib/tds/minorHead.ts");
  assert.equal((MODULE.match(/\b200 — TDS payable by the deductor/g) ?? []).length, 1, "the minor heads are spelled twice");
  assert.ok(!/200 — TDS payable by the deductor/.test(PAGE) && !/200 — TDS payable by the deductor/.test(TAB), "a page spells the minor heads itself");
});

test("the screen holds no copy of the sections or their names: they are the server's", () => {
  assert.ok(!/SECTION_LABELS|DEDUCTIBLE_SECTIONS/.test(PAGE), "the page keeps a table of sections or names");
  assert.ok(!/"194LA"|"194Q"|"206C"|Contractor payments|Professional \/ technical fees/.test(PAGE), "a section or a name is spelled in the page");
  assert.ok(/\{choices\.challan\.map\(c => <option key=\{c\.section\} value=\{c\.section\}>\{sectionOptionText\(c\.section, choices\.labels\)\}<\/option>\)\}/.test(PAGE),
    "the Add Challan form is not offered the server's list of sections");
  assert.ok(/\{choices\.deductible\.map\(k => \(\s*<option key=\{k\} value=\{k\}>\{sectionOptionText\(k, choices\.labels\)\}<\/option>/.test(PAGE),
    "the deduction form is not offered the server's list of sections");
  assert.ok(/options: choices\.filterable\.map\(\(k\) => \(\{ value: k, label: sectionOptionText\(k, choices\.labels\) \}\)\)/.test(PAGE),
    "the Section filter is not every section a recorded deduction can carry (the limbs the form offers and the sections a challan names)");
  assert.ok(/listTdsSections\(\)/.test(PAGE) && /sectionChoices\(r\)/.test(PAGE), "the page does not read the server's sections once");
  assert.ok(/\{choicesError && \(/.test(PAGE), "a failed read of the sections is not said");
});

test("the deductions can be listed for one financial year, the server narrows both the rows and the totals, and a client starts at every year", () => {
  // POST-A-294: a register longer than the ceiling is cut to its latest rows, and without a year the older ones could not be reached.
  assert.ok(/financial_year=\$\{encodeURIComponent\(financialYear\)\}/.test(DATA), "the data module does not send the year to the server");
  assert.ok(/listTdsDeductions\(clientId, year \|\| null\)/.test(PAGE), "the page does not ask the server for the chosen year");
  assert.ok(/<YearPicker value=\{yearFilter\} placeholder="All years"/.test(PAGE), "the deductions have no year control");
  assert.ok(!/deductions\.filter\(|\.filter\(\(?d\)? => [^)]*financial_year/.test(PAGE), "the page narrows a year itself over rows the server cut");
  assert.ok(/setYearFilter\(""\);/.test(PAGE) && /void loadLists\(selectedClientId, true, ""\)/.test(PAGE),
    "a client switch must start from every year and read with it (a year chosen for the last client must not narrow this one's)");
  assert.ok(/Choose a financial year above to see the older ones/.test(PAGE), "a cut register does not say how to reach the older rows");
  // No client open: the picker is off and the handler does nothing (a read with no client is refused and shows the table-missing banner),
  // and a year change takes the previous choice's footer and cut notice down at once instead of printing them under the new year's name.
  assert.ok(/disabled=\{loading \|\| !selectedClientId\}/.test(PAGE) && /if \(!selectedClientId\) return;\s*setYearFilter\(v\);/.test(PAGE),
    "the year picker can be used with no client open");
  assert.ok(/setYearFilter\(v\); setDeductionTotals\(null\); setCut\(\(c\) => \(\{ \.\.\.c, deductions: false \}\)\);/.test(PAGE),
    "a year change leaves the previous choice's totals and cut notice under the new year's name");
});

test("anything that writes reads the lists again instead of prepending to them", () => {
  assert.ok(!/setDeductions\(prev|setChallans\(prev/.test(PAGE), "a write is prepended to a list in the browser, so the totals describe a list the server never made");
  assert.equal((PAGE.match(/void loadLists\(selectedClientId, false\)/g) ?? []).length, 3, "a deduction, a challan and an import must each read the lists again");
});

test("a read for a client that is no longer open takes no number, so it cannot throw away the read of the client that is", () => {
  const at = PAGE.indexOf("async function loadLists(");
  assert.ok(at > 0, "loadLists is missing");
  const head = PAGE.slice(at, at + 400);
  const guard = head.indexOf("if (clientId !== openClient.current) return;");
  const take = head.indexOf("const seq = ++listSeq.current;");
  assert.ok(guard > 0 && take > guard, "loadLists must refuse a client that is not the open one BEFORE it takes a read number (a modal's answer after a client switch)");
});

test("an empty list says whether it was read: reading, refused, or truly empty", () => {
  assert.equal((PAGE.match(/<ListNotRead /g) ?? []).length, 2, "the Challans and Certificates tabs must each say when their list was not read");
  assert.ok(/error=\{listErrors\.deductions\}/.test(PAGE), "the deductions table is not told its read was refused");
  assert.ok(/challans\.length === 0 && \(loading \|\| listErrors\.challans\)/.test(PAGE), "the Challans tab says 'none added' about a list nobody has read");
  assert.ok(/certificates\.length === 0 && \(loading \|\| listErrors\.certificates\)/.test(PAGE) && /certificates\.length === 0 && !loading && !listErrors\.certificates/.test(PAGE),
    "the Certificates tab says 'none' about a list nobody has read");
});
