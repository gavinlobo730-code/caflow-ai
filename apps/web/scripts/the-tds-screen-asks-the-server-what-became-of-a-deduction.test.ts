// The TDS screen's cards and Deposit column are the challan register's answer, read by the server (POST-A-273).
//
// WHAT THE SCREEN DID (found by opening the seeded demo firm in a browser, 19-10-2026)
//   * the "Pending Challans / Undeposited" card counted `challans.filter(c => c.status === "unmatched")` in the browser, and the
//     server always writes `deposited`, so the card was 0 for ever beside a word that says undeposited;
//   * the deductions table printed a "Challan No" column from `tds_deductions.challan_no`, a field nothing writes for a deduction a
//     purchase bill creates, so it was a dash for nearly every row;
//   * "Total TDS Deducted: All time" read ₹0.00 before a client was chosen, and the returns and certificates cards read 0: an
//     unknown shown as a value;
//   * the Add Challan modal closed without saying what became of the monthly deposit obligations on the compliance calendar.
//
// The backend half is `apps/api/tests/test_the_tds_screen_asks_the_server_what_became_of_a_deduction.py`. This is the other end: a
// screen that went back to counting rows it fetched itself would make the server's care pointless.
//
// Run with: node --experimental-strip-types --test scripts/the-tds-screen-asks-the-server-what-became-of-a-deduction.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const PAGE = stripComments(fs.readFileSync(path.join(WEB, "app/tds/page.tsx"), "utf8"));
const DATA = stripComments(fs.readFileSync(path.join(WEB, "lib/data/tds.ts"), "utf8"));

test("the page is where this guard thinks it is", () => {
  assert.ok(PAGE.length > 20000, `app/tds/page.tsx read as ${PAGE.length} chars`);
  assert.ok(DATA.includes("export async function fetchTdsDepositState"), "lib/data/tds.ts lost the deposit-state reader");
  assert.ok(DATA.includes("/api/tds-workspace/deposit-state"), "the reader no longer asks the server's route");
});

test("the card that says undeposited is the server's figure and not a count of rows the page fetched", () => {
  assert.ok(!/status\s*===\s*"unmatched"/.test(PAGE) && !/pendingChallans/.test(PAGE),
    "the page counts challans by a status nothing writes (create_challan always writes `deposited`)");
  assert.ok(PAGE.includes("Tax not yet deposited"), "the card is not labelled for what it shows");
  assert.ok(/depositForClient\.position\.undeposited_paise/.test(PAGE), "the card does not read the server's undeposited figure");
  assert.ok(/depositForClient\?\.position\?\.caveat/.test(PAGE), "the server's caveat about tax it cannot judge is never read");
  // A nil that judges nothing is not a figure: tax deducted with no quarter of it recorded shows a dash, not ₹0.00.
  assert.ok(/!depositForClient\.position\.figure_known\) \? "—"|!depositForClient\.position\.figure_known \? "—"/.test(PAGE),
    "the card shows the position's nil when the position judged nothing");
  assert.ok(/depositForClient\.position\.basis/.test(PAGE), "the card does not say what its figure was judged against");
  assert.ok(/\{c\.note && <p [^>]*>\{c\.note\}<\/p>\}/.test(PAGE), "the server's caveat about tax it cannot judge is never rendered");
});

test("the browser words no sentence of its own about unrecorded tax and does no arithmetic on challans", () => {
  // The words are the server's (`domain/hub/tiles.not_recorded_caveat`, `domain/tds/deposit_state.words`).
  assert.ok(!/no challan is recorded|not recorded|cannot say whether/i.test(PAGE),
    "app/tds/page.tsx words the unrecorded-tax sentence itself instead of rendering the server's");
  assert.ok(!/challans\.(reduce|filter)\(/.test(PAGE), "the page computes over its challans in the browser");
  assert.ok(!/deposited_paise\s*[-+]|undeposited_paise\s*[-+]|not_recorded_paise\s*[-+]/.test(PAGE),
    "the page does arithmetic on the server's deposit figures");
});

test("a card shows a dash and says why before a client is chosen, while it reads and when a read failed", () => {
  const cards = PAGE.slice(PAGE.indexOf("Total TDS Deducted") - 600, PAGE.indexOf("Certificates Pending") + 600);
  for (const label of ["Total TDS Deducted", "Tax not yet deposited", "Returns Due", "Certificates Pending"]) {
    assert.ok(cards.includes(`label: "${label}"`), `the ${label} card is missing`);
  }
  // Four cards, four values gated on a chosen client, and each says "Choose a client" in its sub-line.
  assert.equal((cards.match(/value:\s*!selectedClientId/g) ?? []).length, 4, "a card shows a value before a client is chosen");
  assert.equal((cards.match(/sub:\s*!selectedClientId \? "Choose a client"/g) ?? []).length, 4, "a card does not say why it shows a dash");
  // The two deposit cards are the server's, and both are gated on the answer being there and being for this client.
  assert.ok(/value: !selectedClientId \|\| !depositForClient \? "—" : formatPaise\(depositForClient\.totals\.deducted_paise\)/.test(cards),
    "the deducted total is not the server's total, or shows before it was read");
  assert.ok(/!depositForClient\?\.position/.test(cards), "the undeposited card shows a figure before the register was read, or when the position could not be");
  assert.ok(/depositStateError \? "Could not be read"/.test(cards), "a failed read of the register is not said on the card");
  assert.ok(/"The position could not be read"/.test(cards), "a position that could not be read (the rows were) is not said on the card");
  // The other two are the server's counts over all of the client's rows (`domain/tds/screen_counts`); a dash until they are read, and a
  // dash again if their read failed.
  assert.ok(/value: !selectedClientId \|\| !returnCounts \? "—" : String\(returnCounts\.not_filed\)/.test(cards),
    "the returns card is not the server's count, or shows a count before it was read");
  assert.ok(/value: !selectedClientId \|\| !certificateCounts \? "—" : String\(certificateCounts\.pending\)/.test(cards),
    "the certificates card is not the server's count, or shows a count before it was read");
  // What is shown is what was read for the client that is open.
  assert.ok(/depositState\.client_id === selectedClientId \? depositState : null/.test(PAGE),
    "an answer for another client could still be drawn");
});

test("the deductions table asks the register what became of each deduction and no longer prints the dead field", () => {
  assert.ok(!/header:\s*"Challan No"/.test(PAGE), "the table still has a Challan No column");
  assert.ok(!/accessor:\s*\(d\)\s*=>\s*d\.challan_no/.test(PAGE), "a column reads tds_deductions.challan_no, which nothing writes");
  assert.ok(/key:\s*"deposit",\s*header:\s*"Deposit"/.test(PAGE), "the Deposit column is missing");
  assert.ok(/depositForClient\?\.deductions\[d\.id\]/.test(PAGE), "the Deposit column is not keyed by the deduction's id");
  // The words are the server's: the label and the generic sentence come from the answer's legend, and a row's own sentence replaces it.
  assert.ok(/depositForClient\.legend\[row\.state\]/.test(PAGE) && /\{words\?\.label \?\? "—"\}/.test(PAGE), "the label is not the server's legend");
  assert.ok(/const sentence = row\.detail \?\? words\?\.sentence;/.test(PAGE) && /title=\{sentence\}/.test(PAGE),
    "the sentence is not the row's own or the legend's");
  // A sentence that asks for action is READ on the screen and not only in a hover title; the rest reach a screen reader.
  assert.ok(/<span className="block max-w-xs[^"]*">\{sentence\}<\/span>/.test(PAGE), "a row that needs action does not show its sentence");
  // What is about THIS row is read on the screen (a part's rupees, a challan dated before the tax); what is the same for every row of
  // a state is said once under the cards, and is a tooltip and screen-reader text in the column.
  assert.ok(/const shown = row\.state === "part" \|\| row\.dated_before === true;/.test(PAGE),
    "the rows whose sentence is shown are not the ones with a sentence of their own (part, a challan dated before the tax)");
  assert.ok(/Not deposited: \{depositForClient\.legend\.not_deposited\.sentence\}/.test(PAGE) && /\.some\(r => r\.state === "not_deposited"\)/.test(PAGE),
    "the generic not-deposited sentence is not said once under the cards when a row needs it");
  // The colour of a deposited row: a late deposit, or one with a challan dated before the tax, is not 'ready'.
  assert.ok(/row\.state === "deposited" \? \(row\.paid_late \|\| row\.dated_before \? "text-state-attention" : "text-state-ready"\)/.test(PAGE),
    "a deposit made late, or covered by a challan dated before the tax, is drawn as ready");
  assert.ok(/\{row\.due_note && <span className=\{`block text-3xs leading-snug \$\{row\.overdue \|\| row\.paid_late \? "text-state-problem" : "text-state-attention"\}`\}>/.test(PAGE),
    "the due note's colour does not follow the server's overdue and paid_late flags");
  // The CSV says what the screen says.
  assert.ok(/return \[label, row\.due_note, row\.challans && row\.challans\.length > 0 \? `challan \$\{row\.challans\.join\(", "\)\}` : null\]\s*\.filter\(Boolean\)\.join\("\. "\);/.test(PAGE),
    "the exported Deposit column drops the due note and the serials");
  // A row that is not in the answer says why, in text.
  assert.ok(/depositForClient \? "Added after the read" : "—"/.test(PAGE), "a row added after the read is a bare dash");
  assert.ok(/\{sentence && shown && <span /.test(PAGE), "the sentence of a row that needs action is computed and never drawn");
  assert.ok(/\{sentence && !shown && <span className="sr-only">/.test(PAGE), "the sentence of the other rows is not reachable by a screen reader");
  // Not yet due is not a failure: the tone follows the server's overdue flag, and the due note is the server's.
  assert.ok(/\(row\.overdue \? "text-state-problem" : "text-state-attention"\)/.test(PAGE), "a deduction not yet due is drawn like one that is late");
  assert.ok(/\{row\.due_note && <span /.test(PAGE), "the server's due note is never drawn");
  assert.ok(!/row\.label|row\.detail !== null/.test(PAGE), "the page reads a per-row label the answer no longer carries");
  assert.ok(/This deduction was added after the deposit state was read\./.test(PAGE), "a row missing from an answer that did load says the answer was never read");
  assert.ok(/\], \[depositForClient, depositStateError, choices\.labels\]\);/.test(PAGE), "the columns do not follow the deposit state and the section names");
  assert.ok(/depositStateError \? "Not read" : depositForClient \? "Added after the read" : "—"/.test(PAGE), "a row whose state was not read does not say so");
  // The manual form's typed number stays a NOTE and says so.
  assert.ok(PAGE.includes("Challan No. (a note only)"), "the deduction form's challan number is not marked as a note");
});

test("a failed read is said in words, and the cards say what they hold and when they are reading", () => {
  assert.ok(/\{depositStateError && \(\s*<Callout tone="attention" title="The deposit state could not be read">/.test(PAGE), "a failed read is a tooltip and a dash, not a sentence");
  assert.ok(PAGE.includes("Recorded here, with surcharge and cess (salary tax is in payroll)"), "the deducted card does not say it leaves salary tax (payroll's) out");
  assert.equal((PAGE.match(/\(loading \? "Reading" : "Could not be read"\)/g) ?? []).length, 2, "the returns and certificates cards show a bare dash while they read");
});

test("the screen says what it read, and the footer says which total it is", () => {
  assert.ok(/Deposit state read from \{depositForClient\.read\}/.test(PAGE), "what the answer was read from is never said");
  assert.ok(PAGE.includes("Total of the TDS Amount column:"), "the footer total is not labelled as the column's sum (the card is the server's, with surcharge and cess)");
});

test("the Add Challan form says which quarter a challan is recorded for", () => {
  assert.ok(/Record it for the quarter the\s+tax was deducted in, even if it was paid in the next one\./.test(PAGE), "the form does not say the quarter is the one the tax was deducted in");
});

test("the register's own warnings are shown, in the server's words", () => {
  assert.ok(/\{depositForClient && depositForClient\.warnings\.length > 0 && \(/.test(PAGE), "the warnings are never read, or read behind a condition that is always false");
  assert.ok(/depositForClient\.warnings\.map\(\(w, i\) => <li key=\{`\$\{w\.code\}-\$\{i\}`\}>\{w\.message\}<\/li>\)/.test(PAGE),
    "the warnings are not rendered as the server wrote them");
});

test("a challan is opened on the current financial year, and the typed challan number is a note", () => {
  assert.ok(/useState\(currentFinancialYear\(\)\)/.test(PAGE), "the Add Challan form does not open on the current financial year");
  assert.ok(!/useState\("20\d\d-\d\d"\)/.test(PAGE), "a financial year is typed into the page's source");
  assert.ok(/key: "challan_no",[^\n]*A note only/.test(PAGE), "the import template does not say its challan number is a note");
});

test("recording a challan shows what became of the monthly deposits on the compliance calendar, in the server's words", () => {
  assert.ok(/compliance_obligations\?:\s*CalendarAnswer\[\]/.test(PAGE), "the challan type does not carry the calendar answer");
  assert.ok(/setCalendarAnswers\(c\.compliance_obligations \?\? null\)/.test(PAGE), "the answer to recording a challan is dropped");
  assert.ok(/\{a\.message\}/.test(PAGE), "the server's sentence for each month is not rendered");
  assert.ok(/calendarAnswers && calendarAnswers\.length > 0/.test(PAGE), "an empty answer renders a panel (nothing to say is nothing said)");
  // The live region is on the page before anything is put in it; one mounted with its content is announced unreliably.
  assert.ok(/<div role="status" className="[^"]*">\s*\{calendarAnswers && calendarAnswers\.length > 0 && \(/.test(PAGE), "the answer is not put in an always-mounted live region");
  // Attention is for a month the server left open, not for one already filed or not on the calendar (also closed=false).
  assert.ok(/calendarAnswers\.some\(a => a\.needs_action\) \? "attention"/.test(PAGE), "the tone is not the server's needs_action");
  assert.ok(!/a\.state === "not_closed"|!a\.closed/.test(PAGE), "the page reads the state words to choose a tone");
});

test("the register is read again after anything that changes it, and a slow answer for another client is ignored", () => {
  const reads = (PAGE.match(/void refreshDepositState\(/g) ?? []).length;
  assert.ok(reads >= 4, `the deposit state is refreshed ${reads} times: on load, after a deduction, a challan and an import`);
  assert.equal((PAGE.match(/seq !== depositSeq\.current/g) ?? []).length, 2,
    "a late answer, or a late failure, for the client open a moment ago could replace the one now open");
  // A switch takes a number too, so an answer started for the previous client is stale, and starts from nothing.
  assert.ok(/openClient\.current = selectedClientId;\s*depositSeq\.current \+= 1;\s*setDepositState\(null\); setDepositStateError\(null\); setCalendarAnswers\(null\);/.test(PAGE),
    "a client switch does not take the open client, invalidate the answer in flight and clear the deposit state and the calendar answer");
  assert.ok(/void loadLists\(selectedClientId, true\);/.test(PAGE) && /if \(fresh\) \{\s*setDeductions\(\[\]\); setChallans\(\[\]\); setCertificates\(\[\]\);/.test(PAGE),
    "a client switch does not start the lists from nothing");
  // Each read takes its own number, so two overlapping reads cannot share one; a read for a client no longer open is not started.
  assert.ok(/const seq = \+\+depositSeq\.current;/.test(PAGE), "two overlapping reads can share a number");
  assert.ok(/if \(clientId !== openClient\.current\) return;/.test(PAGE), "a late write's refresh for the previous client could take the open client's read away");
  // A failure clears the figure it replaces, and a write takes the old figures down until the new answer lands.
  assert.ok(/setDepositState\(null\);\s*setDepositStateError\(e instanceof Error/.test(PAGE), "a failed read leaves the old figure beside 'Could not be read'");
  assert.ok(/if \(afterWrite\) \{ setDepositState\(null\); setDepositStateError\(null\); \}/.test(PAGE), "after a write the old figures stay until the new answer");
  assert.equal((PAGE.match(/refreshDepositState\(selectedClientId, true\)/g) ?? []).length, 3, "a deduction, a challan and an import must each take the old figures down");
  // The loading effect's guards: client A's rows never land on client B's page.
  assert.ok(/const seq = \+\+listSeq\.current;/.test(PAGE) && /if \(seq !== listSeq\.current\) return;/.test(PAGE) && /if \(seq === listSeq\.current\) setLoading\(false\);/.test(PAGE),
    "the load can land rows for the client that was open, or an older read can lower a newer one's loading flag");
});

test("the data module types the server's answer and reads no table itself for it", () => {
  const reader = DATA.slice(DATA.indexOf("export async function fetchTdsDepositState"), DATA.indexOf("export async function fetchTdsDepositState") + 600);
  assert.ok(!/getSupabaseClient|\.from\(/.test(reader), "the deposit-state reader goes round the API (rbac would never run)");
  assert.ok(/deductions: Record<string, DeductionDepositState>/.test(DATA), "the answer is not keyed by deduction id");
  assert.ok(/position: \{[\s\S]*\} \| null;/.test(DATA), "the type says the position is always there; the server answers null when it could not be read");
  assert.ok(/figure_known: boolean/.test(DATA) && /totals: \{ deducted_paise: number \}/.test(DATA), "the answer's figure_known and totals are not typed");
  assert.ok(/legend: Record<DepositStateKind, DepositStateWords>;/.test(DATA), "the answer's legend (the server's labels and sentences) is not typed");
  assert.ok(/due_note\?: string;/.test(DATA) && /overdue\?: boolean;/.test(DATA) && /paid_late\?: boolean;/.test(DATA),
    "a row's due note, overdue and paid_late flags are not typed (and optional: a key is absent when it says nothing)");
  assert.ok(/needs_action\?: boolean;/.test(DATA), "a calendar answer's needs_action is not typed");
});
