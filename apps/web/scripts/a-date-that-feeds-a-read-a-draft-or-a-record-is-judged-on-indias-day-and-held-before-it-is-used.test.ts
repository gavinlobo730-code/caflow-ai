// A DATE THAT FEEDS A READ, A DRAFT OR A RECORD IS JUDGED ON INDIA'S DAY AND HELD BEFORE IT IS USED (POST-A-393).
//   node --experimental-strip-types --test scripts/a-date-that-feeds-a-read-a-draft-or-a-record-is-judged-on-indias-day-and-held-before-it-is-used.test.ts
//
// THE DEFECTS (the ledger line named six; the third is held by the server and tested in Python: tests/test_a_job_workers_challan_is_not_dated_after_the_day_the_goods_came_back.py)
//   1. A tax audit recorded as completed or filed could carry an audit date, and one recorded as filed a filing date, that had not come: the Tax Audit tracker writes the table straight from
//      the browser and nothing at any layer checked the two dates. The line is drawn by the STATUS (an audit not yet done may carry a planned day), enforced in the database by migration 584
//      (the one layer every writer meets), and asked first in the boxes with the same bound.
//   2. The stock transfer's date started from the BROWSER's day.
//   3. The ITC-04 job worker's challan date was bounded by the day the goods came back with a HINT on the box (a bound on a date box is an input hint: a day outside it is reported and still
//      handed up) and the server did not ask. The server asks now; the box makes a later day a problem the form is held for, and `DateInput` judges the day it holds again when the bound moves
//      (a remount with a `key` would drop text that cannot be read together with the problem reported for it, and the form would save a blank).
//   4. The Schedule III ageing's "As at" started from the browser's day, and a blank box (or text that is not a date) was READ: the server answers a missing date as at today, so today's
//      figures stood under a box that said nothing or said it was not a date.
//   5. The Form 15CA / 15CB fields of a purchase bill are drawn when the server SETTLES that the bill withholds under section 195 (a reading that failed or is out again leaves the block as it was), and
//      were sent whatever was drawn.
//   6. The overdue-interest panel's Prepare was live while the table for a newly typed date was still being worked out, so a draft was computed as at the box's date under a table of another's.
//
// WHAT THIS DOES NOT COVER
//   What the browser does with them (the drive: `scripts/drive/scenarios/datesAreJudgedOnIndiasDay.mjs`) and the database's refusal itself (the real-Postgres test of migration 584).
//   The control flow is read as text.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));

const TAX_AUDIT = "app/income-tax/tax-audit/page.tsx";
const TRANSFER = "components/inventory/LocationsAndBatches.tsx";
const AGEING = "app/clients/[id]/reports/ageing/page.tsx";
const BILL = "components/purchases/PurchaseBillEditor.tsx";
const INTEREST = "components/sales/OverdueInterestPanel.tsx";
const INVENTORY = "app/clients/[id]/inventory/page.tsx";
const MIGRATION_584 = path.join(WEB, "..", "api", "migrations", "584_a_tax_audit_recorded_as_completed_or_filed_does_not_carry_a_day_that_has_not_come.sql");

/** The text between the opener at `open` (a `(`, `{` or `[`) and its match, string and template literals skipped. */
function balanced(code: string, open: number): string {
  const pairs: Record<string, string> = { "(": ")", "{": "}", "[": "]" };
  assert.ok(pairs[code[open]], `balanced() needs an opener at ${open}, found ${JSON.stringify(code[open])}`);
  let depth = 0;
  for (let i = open; i < code.length; i++) {
    const c = code[i];
    if (c === '"' || c === "'" || c === "`") {
      for (i++; i < code.length && code[i] !== c; i++) if (code[i] === "\\") i++;
      continue;
    }
    if (c === "(" || c === "{" || c === "[") depth++;
    else if (c === ")" || c === "}" || c === "]") { depth--; if (depth === 0) return code.slice(open + 1, i); }
  }
  return code.slice(open + 1);
}

/** The body of the function whose header matches (the header ends at its opening brace): the braces' contents. */
function bodyOf(code: string, header: RegExp): string {
  const m = header.exec(code);
  assert.ok(m, `${header} is no longer in the file`);
  return balanced(code, m.index + m[0].length - 1);
}

/** The element `<DateInput id="…" … />`, balanced on its braces, or null. */
function dateInputWithId(code: string, id: string): string | null {
  const at = code.indexOf(`<DateInput id="${id}"`);
  if (at < 0) return null;
  let depth = 0;
  for (let i = at; i < code.length; i++) {
    const c = code[i];
    if (c === "{") depth++;
    else if (c === "}") depth--;
    else if (c === ">" && depth === 0 && code[i - 1] === "/") return code.slice(at, i + 1);
  }
  return null;
}

// ═════════════════════════════════════════════════════════════════════════════
// 1. A TAX AUDIT'S DATES ARE JUDGED BY ITS STATUS, IN THE BOX AND IN THE DATABASE
// ═════════════════════════════════════════════════════════════════════════════

test("the tax audit's boxes are bounded by India's today only when the status says the act is done, and the database's sentence is shown as it is", () => {
  const code = read(TAX_AUDIT);
  assert.match(code, /const FINISHED_STATUSES: AuditStatus\[\] = \["completed", "filed"\];/);
  assert.match(code, /const auditBound = FINISHED_STATUSES\.includes\(form\.status\) \? todayIstISO\(\) : null;/, "the audit date is not bounded by the status");
  assert.match(code, /const filingBound = form\.status === "filed" \? todayIstISO\(\) : null;/, "the filing date is not bounded by the status");
  const audit = dateInputWithId(code, "tax-audit-date");
  const filing = dateInputWithId(code, "tax-audit-filing-date");
  assert.ok(audit && filing, "a tax audit date box is gone");
  assert.doesNotMatch(audit, /\bkey=/, "the audit date box is remounted: text that cannot be read is dropped with its problem, and the form saves a blank (DateInput judges a held day again when its bound moves)");
  assert.match(audit, /notAfter=\{auditBound\}/, "the audit date box is not bounded");
  assert.match(audit, /afterMax: auditBound !== null/, "a later audit date is only hinted, not refused");
  assert.doesNotMatch(filing, /\bkey=/, "the filing date box is remounted: text that cannot be read is dropped with its problem, and the form saves a blank");
  assert.match(filing, /notAfter=\{filingBound\}/, "the filing date box is not bounded");
  assert.match(filing, /afterMax: filingBound !== null/, "a later filing date is only hinted, not refused");
  assert.match(code, /const dateRefusal = useDateRefusal\(dates\.first\);/, "the boxes' sentence is not latched");
  assert.match(code, /if \(dates\.first\) \{ setError\(null\); dateRefusal\.refuse\(\); return; \}/, "the save no longer refuses a date the box has a problem with");
  assert.doesNotMatch(code, /setError\(dates\.first\)/, "the boxes' sentence is copied into the form's error, where it stays after its cause is put right (the status switched back to in progress)");
  assert.match(code, /\{\(error \|\| dateRefusal\.shown\) && <Callout tone="problem">\{error \?\? dateRefusal\.shown\}<\/Callout>\}/, "the latched sentence is not drawn");
  assert.match(code, /\?\? auditDateRefusalMessage\(e as /, "the database's own sentence for a day that has not come is not what the screen shows");
  // ...and it comes before the generic fallback, or an Error's own message (which the supabase client builds from the same text) would be shown instead of the mapped one.
  assert.ok(code.indexOf("auditDateRefusalMessage(") < code.indexOf("(e instanceof Error ? e.message : \"Save failed\")"), "the database's sentence is asked after the generic message");
  // a planned day is allowed: the bound is never unconditional
  assert.doesNotMatch(audit, /notAfter=\{todayIstISO\(\)\}/);
  assert.doesNotMatch(filing, /notAfter=\{todayIstISO\(\)\}/);
});

test("a date box judges the day it holds again when its bound moves, and says so to its parent", () => {
  const code = read("components/ui/date-input.tsx");
  assert.match(code, /const toldAgainst = React\.useRef</, "the box does not remember which bounds its parent was last told it against");
  assert.ok((code.match(/toldAgainst\.current = \{ min, max \};/g) ?? []).length >= 4, "a report (the value's, a keystroke's, a commit's, the bound's) does not record the bounds it was made against: the box would be read twice, or from a state that has not caught up");
  const at = code.indexOf("if (toldAgainst.current.min === min && toldAgainst.current.max === max) return;");
  assert.ok(at >= 0, "a bound that moves is not noticed");
  // The bounds are recorded AFTER they are compared: recorded first, the comparison above is always equal and the effect never reports (the one mutation a text guard lets through unless the order is pinned).
  assert.match(code.slice(at, at + 200), /return;\s*toldAgainst\.current = \{ min, max \};/, "the bounds are recorded before they are compared, so a bound that moves is never reported");
  const effect = code.slice(at, at + 400);
  assert.match(effect, /if \(shown\.kind === "date"\) stateCallback\.current\?\.\(dateFieldState\(box\.text, shown\)\);/, "the day the box holds is not judged again and reported (and text that cannot be read must be left alone: its problem stays where it is)");
  assert.match(effect, /\}, \[min, max\]\);/, "the effect does not fire on the bound");
});

test("the screen and the database draw the line in the same place", () => {
  const sql = fs.readFileSync(MIGRATION_584, "utf8");
  const page = read(TAX_AUDIT);
  const statuses = (text: string) => [...text.matchAll(/'(\w+)'/g)].map((m) => m[1]).sort();
  const auditRule = /NEW\.status IN \(([^)]*)\)\s*AND NEW\.audit_date IS NOT NULL/.exec(sql);
  assert.ok(auditRule, "the audit-date rule is gone from the migration");
  const finished = /const FINISHED_STATUSES: AuditStatus\[\] = \[([^\]]*)\];/.exec(page);
  assert.ok(finished, "FINISHED_STATUSES is gone from the page");
  assert.deepEqual(statuses(auditRule[1]), [...finished[1].matchAll(/"(\w+)"/g)].map((m) => m[1]).sort(), "the page bounds the audit date for other statuses than the database refuses it for");
  assert.match(sql, /NEW\.status = 'filed'\s*AND NEW\.filing_date IS NOT NULL/, "the filing-date rule is gone from the migration");
  assert.match(page, /form\.status === "filed" \? todayIstISO\(\)/, "the page bounds the filing date for another status than the database refuses it for");
});

// ═════════════════════════════════════════════════════════════════════════════
// 2. THE STOCK TRANSFER STARTS FROM INDIA'S DAY
// ═════════════════════════════════════════════════════════════════════════════

test("the stock transfer's date starts from India's day and the file does not reach for the browser's", () => {
  const code = read(TRANSFER);
  assert.match(code, /const \[when, setWhen\] = useState\(todayIstISO\(\)\);/, "the transfer's date does not start from India's day");
  assert.doesNotMatch(code, /todayLocalISO|toLocalISO\(\s*new Date\(\s*\)\s*\)/, "the stock panel reads the browser's day");
  // ...and so does the day the page hands it as the date its position is as at: the panel takes the page's, and a page that falls back to the browser's day gives it a different one.
  const page = read(INVENTORY);
  assert.doesNotMatch(page, /asAt \|\| (?:todayLocalISO|toLocalISO\(\s*new Date\(\s*\)\s*\))/, "the inventory page falls back to the browser's day for the stock panels");
  assert.equal((page.match(/asAt \|\| todayIstISO\(\)/g) ?? []).length, 3, "one of the three stock panels is given another day than India's");
  // The stock adjustment and the NRV write-down on the same page post to the books and start from a day too.
  assert.doesNotMatch(page, /\btodayLocalISO\b|toLocalISO\(\s*new Date\(\s*\)\s*\)/, "the inventory page reads the browser's day somewhere (the adjustment's and the write-down's date start from it)");
  assert.equal((page.match(/const today = todayIstISO\(\);/g) ?? []).length, 2, "the adjustment's and the write-down's date do not both start from India's day");
});

// ═════════════════════════════════════════════════════════════════════════════
// 4. THE AGEING SCHEDULE IS NOT READ FOR A BOX THAT IS BLANK OR NOT A DATE
// ═════════════════════════════════════════════════════════════════════════════

test("the ageing schedule starts from India's day, reads nothing for a blank or unreadable As at, and says so", () => {
  const code = read(AGEING);
  assert.match(code, /const \[asOf, setAsOf\] = useState<string>\(todayIstISO\(\)\);/, "the schedule does not start from India's day");
  assert.doesNotMatch(code, /todayLocalISO|toLocalISO\(\s*new Date\(\s*\)\s*\)/, "the page reads the browser's day");
  const load = bodyOf(code, /const load = useCallback\(async \(\) => \{/);
  const firstGuard = load.indexOf("if (!asOf)");
  assert.ok(firstGuard >= 0 && firstGuard < load.indexOf("scheduleIiiAgeing("), "load() can ask the server for a schedule with no date: it answers as at today under a box that says nothing");
  assert.match(load.slice(firstGuard, firstGuard + 160), /setSchedule\(null\)/, "a blank box leaves the last date's schedule on the screen");
  const detail = bodyOf(code, /const loadDetail = useCallback\(async \(\) => \{/);
  assert.ok(detail.indexOf("!asOf") >= 0 && detail.indexOf("!asOf") < detail.indexOf("api.ageing.receivables("), "loadDetail() reads the open documents with no date");
  const box = dateInputWithId(code, "ageing-as-at");
  assert.ok(box, "the As at box is gone or has lost its id");
  assert.match(box, /onStateChange=\{dates\.watch\("asOf", "As at"\)\}/, "the box does not report what it cannot read");
  // India's day is named ONCE, as the box's starting day: any other mention is a fallback to today for a box the person emptied (`setAsOf(v || todayIstISO())`), which reads today's figures under a box that says nothing.
  assert.equal((code.match(/todayIstISO\(/g) ?? []).length, 1, "the page names India's day somewhere other than the box's starting day");
  assert.match(box, /onChange=\{\(v\) => \{ setAsOf\(v\);/, "the box does not hand up exactly what it holds");
  // A slower answer for a date the box no longer holds is dropped, in both readings and on both paths of each (the answer and the failure).
  assert.match(load, /const mine = \+\+latestSchedule\.current;[\s\S]*?if \(!asOf\)/, "load() does not count its request before the blank guard: a request still out when the box is emptied would draw its schedule under it");
  assert.ok((load.match(/if \(mine !== latestSchedule\.current\) return;/g) ?? []).length >= 2, "load() draws an answer or a failure that is not the latest asked for");
  assert.ok(load.indexOf("if (mine !== latestSchedule.current) return;") < load.indexOf("setSchedule(objectOrNull("), "load() checks that its answer is the latest only AFTER it has drawn it");
  assert.match(load, /finally \{\s*if \(mine === latestSchedule\.current\) setLoading\(false\);/, "an older request that finishes last clears the spinner of the one still out");
  assert.match(load.slice(firstGuard, firstGuard + 200), /setDetailError\(null\)/, "a blank box leaves the open documents' last failure on the screen");
  assert.ok((detail.match(/if \(mine !== latestDetail\.current\) return;/g) ?? []).length >= 2, "loadDetail() draws an answer or a failure that is not the latest asked for");
  assert.ok(detail.indexOf("if (mine !== latestDetail.current) return;") < detail.indexOf("setInvoices("), "loadDetail() checks that its answer is the latest only AFTER it has drawn it");
  assert.match(box, /latestDetail\.current \+= 1;/, "a changed date does not drop the open documents' answer still on its way");
  assert.match(code, /\{!asOf && \(\s*<Callout tone="note">\s*As at: enter the date this schedule is as at\./, "nothing tells the person why no schedule is shown");
});

// ═════════════════════════════════════════════════════════════════════════════
// 5. FORM 15CA / 15CB ARE SENT ONLY WHERE THEY ARE DRAWN
// ═════════════════════════════════════════════════════════════════════════════

test("the Form 15CA and 15CB fields of a bill are sent only when their block is drawn", () => {
  const code = read(BILL);
  // The block follows the server's SETTLED answers: an answer decides it, "nothing to read" closes it, and an error or a reading in progress leaves it as it was (a block that vanished under the
  // cursor, or with the acknowledgement typed in it, would drop the entry with no word).
  assert.match(code, /const form15Verdict = useRef\(false\);\s*if \(!tds\.loading\) \{\s*if \(tds\.data\) form15Verdict\.current = tds\.data\.tds_section === "195";\s*else if \(tds\.error === null\) form15Verdict\.current = false;\s*\}\s*const form15Drawn = form15Verdict\.current;/,
    "the fact that decides the block is not one verdict taken from the settled answers (a failed or repeated reading must leave the block as it was)");
  assert.match(code, /\{form15Drawn && \(/, "the block is not drawn by that constant");
  assert.equal((code.match(/tds_section === "195"/g) ?? []).length, 1, "the condition that draws the block is spelled out a second time: the next one to change would draw one thing and send another");
  assert.match(code, /const form15caCleared = form15Drawn && /, "the held-date check of the 15CA box asks another question than the block does");
  for (const field of ["form_15ca_ack_no", "form_15ca_filed_on", "form_15cb_udin"]) {
    const sends = [...code.matchAll(new RegExp(`${field}:\\s*([^\\n]*)`, "g"))].map((m) => m[1].trim());
    assert.ok(sends.length >= 3, `${field} is sent from fewer than the three payloads (create, edit, edit of a received bill)`);
    // `form15Drawn ? <what was typed> : undefined`: the other branch is nothing, not the same thing again.
    for (const s of sends) assert.match(s, /^form15Drawn \? \S.* : undefined,?$/, `${field} is sent whether or not its block is drawn: ${s}`);
  }
});

// ═════════════════════════════════════════════════════════════════════════════
// 6. PREPARE WAITS FOR THE TABLE OF THE DATE IN THE BOX
// ═════════════════════════════════════════════════════════════════════════════

test("the overdue-interest panel holds Prepare until the table on screen is the one for the date in the box", () => {
  const code = read(INTEREST);
  assert.match(code, /const \[asOf, setAsOf\] = useState\(todayIstISO\(\)\);/, "the panel does not start from India's day");
  assert.doesNotMatch(code, /todayLocalISO|toLocalISO\(\s*new Date\(\s*\)\s*\)/);
  const load = bodyOf(code, /const load = useCallback\(async \(\) => \{/);
  assert.match(load, /setPreview\(objectWithLists<LateInterestPreview>\([^;]*\)\);\s*setPreviewFor\(asOf\);/, "the date the table was worked out for is not remembered when the table arrives");
  // The table and the date it is for are set together and nowhere else: a failed read that also said "for this date" would leave Prepare live over the OLD table.
  assert.equal((code.match(/\bsetPreviewFor\(/g) ?? []).length, 1, "the date the table is for is set somewhere other than where the table arrives");
  assert.equal((code.match(/\bsetPreview\(/g) ?? []).length, 1, "a table is set somewhere other than where it arrives with its date");
  assert.match(load, /const mine = \+\+latest\.current;\s*if \(!\/\^\\d\{4\}-\\d\{2\}-\\d\{2\}\$\/\.test\(asOf\)\) \{ setLoading\(false\); return; \}/,
    "load() does not count its request BEFORE it tests the box: an answer still out for the date the box held would land under a box that now holds nothing (and a spinner would be left on)");
  // The empty-table line is said of a table that was worked out and for the date it was worked out for; a reading that failed is not 'nothing overdue'.
  assert.match(code, /preview \? \(\s*<p className="p-4 text-sm text-ps-hint">\s*Nothing is overdue as at \{dayLabel\(previewFor \?\? asOf\)\}\./, "the empty table is described by the box's date, or for a table that does not exist");
  assert.ok((load.match(/if \(mine !== latest\.current\) return;/g) ?? []).length >= 2, "load() draws an answer or a failure that is not the latest asked for: the older date's table could come back last");
  assert.ok(load.indexOf("if (mine !== latest.current) return;") < load.indexOf("setPreview("), "load() checks that its answer is the latest only AFTER it has drawn it");
  assert.match(load, /finally \{\s*if \(mine === latest\.current\) setLoading\(false\);/, "an older request that finishes last clears the spinner of the one still out");
  // A save or a draft reloads through the CURRENT load: the one of the render it was started in would read the old date's table and count as the latest request.
  assert.match(code, /const loadRef = useRef\(load\);\s*loadRef\.current = load;/, "the reload a save asks for is not kept current");
  assert.equal((code.match(/await loadRef\.current\(\);/g) ?? []).length, 2, "the save of terms and the draft do not both reload through the current load");
  assert.doesNotMatch(code, /await load\(\);/, "a handler reloads through the load of the render it was started in");
  // Why Prepare is held is said where it can be read once the reading is over (the button's title is not seen on a touch screen).
  assert.match(code, /\{heldReason && !loading && <Callout tone="note">\{heldReason\}<\/Callout>\}/, "after a reading that failed, nothing says in words why Prepare is held");
  assert.match(code, /title=\{held \?\? \(hasInterest/, "the held button no longer carries its reason");
  const held = /const heldReason = preview &&[\s\S]*?: null;/.exec(code);
  assert.ok(held, "heldReason is gone");
  assert.match(held[0], /previewFor !== asOf/, "Prepare is not held when the table is for another date than the box");
  assert.match(held[0], /\\d\{4\}-\\d\{2\}-\\d\{2\}/, "Prepare is held for a box that holds no date as well, which takes away the box's own sentence on the click");
  assert.doesNotMatch(held[0], /enter the date/, "a box that holds no date is held with a sentence of its own: pressing Prepare over it must answer in the sentence the panel already gave");
  const prepare = bodyOf(code, /async function prepare\(party: LateInterestParty\) \{/);
  assert.ok(prepare.indexOf("if (heldReason)") >= 0 && prepare.indexOf("if (heldReason)") < prepare.indexOf("prepareDrafts("), "prepare() can send the request while the table is another date's");
  assert.match(code, /held=\{heldReason\}/, "the rows are not told why Prepare is held");
  assert.match(code, /disabled=\{!hasInterest \|\| anyBusy \|\| held !== null\}/, "the button is live while the table is another date's");
});

// ═════════════════════════════════════════════════════════════════════════════
// 3. THE JOB WORKER'S CHALLAN DATE IS NOT AFTER THE DAY THE GOODS CAME BACK, IN THE BOX AS WELL AS AT THE SERVER
// ═════════════════════════════════════════════════════════════════════════════

test("the ITC-04 challan date makes a later day a problem and is judged again when the came-back day changes", () => {
  const code = read("components/gst/Itc04Panel.tsx");
  const box = dateInputWithId(code, "itc04-challan-date");
  assert.ok(box, "the job worker's challan date box is gone or has lost its id");
  assert.match(box, /notAfter=\{lot\.returned_on \|\| null\}/, "the challan date is not bounded by the day the goods came back");
  assert.match(box, /afterMax: true/, "a challan date after the came-back day is only hinted: the server refuses it, and the form would be sent to be told");
  assert.doesNotMatch(box, /\bkey=/, "the challan box is remounted when the came-back day changes: text that cannot be read is dropped with its problem, and the lot is recorded without a challan day, silently");
  // the came-back day itself is still bounded by India's today and the order of the two is never asked in the browser's own arithmetic
  const came = dateInputWithId(code, "itc04-came-back-on");
  assert.ok(came && /notAfter=\{todayIstISO\(\)\}/.test(came) && /afterMax: true/.test(came), "the came-back day is no longer bounded by India's today");
  assert.doesNotMatch(code, /job_worker_challan_date\s*[<>]/, "the order of the two days is decided in the browser by a comparison; the server's sentence is the rule");
});
