// THE FORMS ON A CLIENT'S COMPLIANCE TABS TAKE THEIR DATES FROM A DATE BOX AND READ THE SERVER'S ANSWER (PRE-A-015, fourteenth slice).
//   node --experimental-strip-types --test scripts/the-forms-on-a-clients-compliance-tabs-read-the-answer-and-take-their-dates-from-a-date-box.test.ts
//
// THE DEFECT
//   Three forms on a client's compliance tabs (the MCA tab's Add Company and New Filing, the TDS tab's New Challan) asked for a date in a plain text box with
//   "(YYYY-MM-DD)" in its placeholder, sent whatever it held, awaited the write and dropped the answer, then closed the form (and the TDS one emptied it) as though
//   the record was saved. A blank box went to the server as "", which a DATE column cannot take, so a company or a filing typed with no date, and a challan with a
//   mistyped one, was NOT created and nothing said so. Only a director's form, fixed earlier, read its answer. (The first fix sent null for a blank filing date;
//   `mca_filings.due_date` is NOT NULL, so that was refused too: a filing's due date is REQUIRED, and the form says so.)
//
// THE RULES
//   1. No text box in the app asks for a date written out (`YYYY-MM-DD`, `dd/mm/yyyy`, `DD-MMM-YYYY`, an example such as `31/03/2026`) in its placeholder, its
//      accessible name or its label: a date is typed into a `DateInput`, which reads every form a person types and hands the parent an ISO date or says why not.
//      The list of exceptions is EMPTY. (A CSV column's `hint`, which describes a file and not a box, is not a placeholder, an aria-label or a label.)
//   2. The page-local `apiFetch` of the three client compliance pages hands a refusal back in the envelope every caller reads (`success: false` and the server's
//      sentence through `errorMessage`), so `r.error ?? "…"` can show it. The TDS page's did not.
//   3. The four forms are held by name. Each keeps its own empty form (`EMPTY_*_FORM`), opens and closes through two functions that empty it and its sentences (and
//      open does nothing while the form is open: the button stays on screen above it and a second press wiped a half-typed record), is opened from nowhere else (the
//      empty-state action calls the same function), refuses an unreadable date before any request, reads the answer (`const res = await apiFetch(…)`), RETURNS from
//      the refusal branch and only then closes, shows the sentence inside the form (`role="alert"`), holds its Save while a request is out and holds its Cancel too.
//   4. The dates: an optional one (a company's incorporation, a director's appointment) is sent as `null` when blank; a REQUIRED one (a filing's due date, a challan's
//      date) is asked for in a sentence of its own and is never sent as `null`; the incorporation date and the challan's date are bounded by today and refuse a later day (a
//      company that has a CIN has been incorporated; the bank has taken the tax by the day a challan is dated: the seventeenth slice, which reversed this file's earlier stance on the
//      challan), and the other dates are not bounded (a due date is a plan, and a director may be appointed with effect from a later day).
//   5. No write that goes through a helper named `apiFetch` drops its answer, on these pages or on any page or component of the app (POST-A-391): a RULE, read by each call's own
//      parentheses and its type argument (the payroll page's helper is generic). The ten writes that did are held by name: the answer is read straight after the call, a refusal says
//      its sentence and ENDS the function before anything closes the form or reads the list again, a failed request is said and closes nothing, the last sentence is cleared when a
//      new press begins and when the list is read again, the flag held across the request is reset in a `finally`, the Cancel of a form or dialog is held while a save is out, and the
//      sentence is drawn as an alert INSIDE the control that raised it (above the table for a row action, inside the form or the dialog for a create or a save).
//
// WHAT THIS DOES NOT COVER
//   Whether the sentence is the server's (the drive does: `tests/test_the_drives_filing_sentences_are_the_servers.py` pins the stub's words to the routers'), the other
//   client tabs (Payroll's and the firm-level pages' forms, which are not these files), a write that begins `void apiFetch(` or goes through `.then`, and what a text
//   box that names a date only in prose ("date of the payment") asks for. The control flow is read as text: a `return` inside the refusal branch, a `dates.first` gate,
//   an `if (showNew) return;` as the open function's first statement, the first close inside the try, and a `disabled=` on the Save and Cancel tags are asserted, not
//   executed; the browser drive executes them (it presses the open button again over a typed form, holds Cancel while a Save is out, and refuses over a status).
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");

function sources(dir: string): string[] {
  const out: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) { if (entry.name !== "node_modules") out.push(...sources(full)); }
    else if (/\.tsx$/.test(entry.name)) out.push(full);
  }
  return out;
}

const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));
const MCA = "app/clients/[id]/compliance/mca/page.tsx";
const TDS = "app/clients/[id]/compliance/tds/page.tsx";
const GST = "app/clients/[id]/compliance/gst/page.tsx";
const PAYROLL = "app/clients/[id]/payroll/page.tsx";

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

/** One component: from `function Name(` to the next top-level function (or the end of the file). */
function componentOf(code: string, name: string): string {
  const at = code.search(new RegExp(`\\nfunction ${name}\\(`));
  assert.ok(at >= 0, `function ${name} is no longer in the file`);
  const next = code.slice(at + 1).search(/\n(?:export default )?(?:async )?function /);
  return next < 0 ? code.slice(at) : code.slice(at, at + 1 + next);
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
// 1. NO TEXT BOX TEACHES THE SHAPE OF A DATE
// ═════════════════════════════════════════════════════════════════════════════

/** What makes a piece of text teach how a date is written: a shape spelled out, or an example of one. */
const A_DATE_WRITTEN_OUT = [
  /yyyy[-/. ]mm[-/. ]dd/i, /dd[-/. ]mm[-/. ]yy(?:yy)?/i, /dd[-/. ]mmm[-/. ]yy(?:yy)?/i, /mm[-/. ]dd[-/. ]yy(?:yy)?/i,
  /\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b/, /\b\d{4}-\d{2}-\d{2}\b/,
];
/** An attribute (or an object key) a person sees or hears on a box: placeholder, aria-label, label; a quote of any of the three kinds, and `{ "…" }`. */
const WHAT_A_BOX_SAYS = /\b(?:placeholder|aria-label|label)\s*[=:]\s*(?:\{\s*)?(?:"([^"\n]*)"|'([^'\n]*)'|`([^`]*)`)/g;
const teachesADate = (source: string) => [...source.matchAll(WHAT_A_BOX_SAYS)].map((m) => m[1] ?? m[2] ?? m[3] ?? "").filter((text) => A_DATE_WRITTEN_OUT.some((s) => s.test(text)));

test("no text box in the app asks for a date written out (the list of exceptions is empty)", () => {
  const asked: string[] = [];
  for (const root of ["app", "components"]) {
    for (const f of sources(path.join(WEB, root))) {
      for (const text of teachesADate(stripComments(fs.readFileSync(f, "utf8")))) asked.push(`${path.relative(WEB, f)}: ${text}`);
    }
  }
  assert.deepEqual(asked, [], "a date is typed into a DateInput, which reads every form and says why one cannot be read; a text box that teaches 'YYYY-MM-DD' sends whatever it holds");
});

test("the rule finds what it is for (a self-test over the spellings a developer would plausibly use)", () => {
  for (const bad of [
    'placeholder="Due Date (YYYY-MM-DD)"', "placeholder='yyyy-mm-dd'", 'placeholder={"Date (YYYY-MM-DD)"}', 'aria-label="Director\'s date (YYYY-MM-DD)"',
    'placeholder="DD-MMM-YYYY"', 'placeholder="DD.MM.YYYY"', 'placeholder="e.g. 31/03/2026"', "label: `Filed on (dd/mm/yyyy)`", 'label="Date (2026-03-31)"',
  ]) assert.equal(teachesADate(bad).length, 1, `the rule would let this through: ${bad}`);
  for (const fine of ['placeholder="Anything the next reviewer should know"', 'aria-label="Due date"', 'label="Financial year (for example 2025-26)"', 'placeholder="Amount (₹)"']) {
    assert.equal(teachesADate(fine).length, 0, `the rule would refuse this: ${fine}`);
  }
});

// ═════════════════════════════════════════════════════════════════════════════
// 2. A REFUSAL COMES BACK IN THE ENVELOPE
// ═════════════════════════════════════════════════════════════════════════════

test("the three client compliance pages hand a refusal back in the envelope every caller reads", () => {
  for (const rel of [MCA, TDS, GST]) {
    const code = read(rel);
    // (the GST and TDS pages' helper also takes `asked`: the word a caller gives for an estimator that persists nothing, POST-A-406)
    const helper = bodyOf(code, /async function apiFetch\(path: string, opts\?: RequestInit(?:, asked\?: Doing)?\) \{/);
    assert.match(helper, /if \(!res\.ok\)\s*return \{\s*success: false,\s*data: null,\s*error: await errorMessage\(res\)\s*\}/,
      `${rel}: apiFetch does not return a refusal as { success: false, error } through errorMessage: every \`r.error ?? "…"\` on the page shows the fallback over the server's sentence`);
    assert.match(code, /import \{[^}]*\berrorMessage\b[^}]*\} from "@\/lib\/api"/, `${rel} does not import errorMessage`);
  }
});

// ═════════════════════════════════════════════════════════════════════════════
// 3. THE FOUR FORMS
// ═════════════════════════════════════════════════════════════════════════════

type Form = {
  rel: string; name: string; component: string; reset: string; open: string; close: string; saving: string; error: string;
  first: string; refuse: string; dateId: string; closeCall: string;
};
const FORMS: Form[] = [
  { rel: MCA, name: "Add Company", component: "CompaniesTab", reset: "EMPTY_COMPANY_FORM", open: "openForm", close: "closeForm", saving: "saving", error: "saveError", first: "dates.first", refuse: "refusal.refuse()", dateId: "mca-company-incorporated", closeCall: "closeForm()" },
  { rel: MCA, name: "Add Director", component: "DirectorsTab", reset: "EMPTY_DIRECTOR_FORM", open: "openForm", close: "closeForm", saving: "saving", error: "saveError", first: "dates.first", refuse: "refusal.refuse()", dateId: "mca-director-appointment", closeCall: "closeForm()" },
  { rel: MCA, name: "New Filing", component: "FilingsTab", reset: "EMPTY_FILING_FORM", open: "openNew", close: "closeNew", saving: "creating", error: "newError", first: "newDates.first", refuse: "newRefusal.refuse()", dateId: "mca-new-filing-due-date", closeCall: "closeNew()" },
  // The challan's blank-box sentences (date, number, BSR code, section, year) are DERIVED from its boxes and said through the same latch (seventeenth slice), so its gate asks both.
  { rel: TDS, name: "New Challan", component: "ChallansTab", reset: "EMPTY_CHALLAN_FORM", open: "openForm", close: "closeForm", saving: "saving", error: "saveError", first: "dates.first ?? challanMissing", refuse: "refusal.refuse()", dateId: "tds-client-challan-date", closeCall: "closeForm()" },
];
const setter = (state: string) => `set${state[0].toUpperCase()}${state.slice(1)}`;

for (const f of FORMS) {
  test(`${f.name}: it has its own empty form, is opened from one place, refuses an unreadable date, reads the answer and closes only on success`, () => {
    const code = read(f.rel);
    const tab = componentOf(code, f.component);
    assert.match(code, new RegExp(`const ${f.reset} = \\{`), `${f.name} has no empty form constant`);
    assert.match(tab, new RegExp(`useState\\(\\{ \\.\\.\\.${f.reset} \\}\\)`), `${f.name}'s form does not start from ${f.reset}`);
    assert.ok(dateInputWithId(tab, f.dateId), `${f.name} has no DateInput with the id ${f.dateId}`);
    // Opening and closing empty the form and its sentences; opening does nothing while the form is open.
    for (const fn of [f.open, f.close]) {
      const body = bodyOf(tab, new RegExp(`function ${fn}\\(\\) \\{`));
      assert.match(body, new RegExp(`setForm\\(\\{ \\.\\.\\.${f.reset} \\}\\)`), `${f.name}: ${fn} does not empty the form`);
      assert.match(body, new RegExp(`${setter(f.error)}\\(null\\)`), `${f.name}: ${fn} does not clear the last sentence`);
      assert.match(body, /\.clear\(\)/, `${f.name}: ${fn} does not withdraw the date's sentence`);
    }
    // The very first statement: placed after the reset it would wipe a half-typed record all the same.
    assert.match(bodyOf(tab, new RegExp(`function ${f.open}\\(\\) \\{`)).trimStart(), /^if \(showNew\) return;/, `${f.name}: ${f.open}() does not begin by doing nothing while the form is open: pressing the button again wipes a half-typed record`);
    // …and it is opened from nowhere else: the empty-state action calls the same function.
    assert.equal((tab.match(/setShowNew\(true\)/g) ?? []).length, 1, `${f.name}: the form is opened by something other than ${f.open}() (an empty-state action that keeps the last record's values)`);
    // The save: an unreadable date is refused before any request; the answer is read; the refusal branch RETURNS; only then does the form close.
    const save = bodyOf(tab, /async function saveNew\(\) \{/);
    const gate = save.indexOf(`if (${f.first}) { ${f.refuse}; return; }`);
    const readAt = save.indexOf("const res = await apiFetch(");
    assert.ok(gate >= 0, `${f.name}: the save no longer refuses an unreadable date (\`if (${f.first}) { ${f.refuse}; return; }\`): a mistyped date would be sent as nothing`);
    assert.ok(readAt > gate, `${f.name}: the request is sent before the date has been judged`);
    const refusedAt = save.indexOf("if (!res?.success) {");
    assert.ok(refusedAt > readAt, `${f.name}: the save no longer asks \`!res?.success\` after the call`);
    const branch = balanced(save, save.indexOf("{", refusedAt));
    assert.match(branch, new RegExp(`${setter(f.error)}\\(res\\?\\.error`), `${f.name}: a refused save does not show the server's sentence inside the form`);
    assert.match(branch, /\breturn;/, `${f.name}: the refusal branch does not return: the form would close over a refusal, as before this slice`);
    // The FIRST close in the save comes after the refusal branch (a close anywhere earlier shuts the form over a refusal), and there is one.
    const closedAt = save.indexOf(f.closeCall);
    assert.ok(closedAt > refusedAt + branch.length, `${f.name}: the save closes its form before it has looked at the answer, or never`);
    // …and in the try, not in a finally (which would close the form over a refusal as well).
    assert.ok(closedAt < save.indexOf("} catch"), `${f.name}: the form is closed after the try (in a finally?), where it closes over a refusal too`);
    assert.ok(save.includes(`${setter(f.saving)}(true)`) && save.includes(`${setter(f.saving)}(false)`), `${f.name}: the save does not hold itself while a request is out`);
    // Inside the form: the sentence, the Save held while a request is out, and the Cancel held with it.
    assert.ok(tab.includes(`role="alert"`) && tab.includes(f.error), `${f.name}: the sentence is not rendered inside the form`);
    // The opening tag around a handler, so a `disabled=` elsewhere in the form cannot stand in for the one on THIS button.
    const tagAround = (needle: string, opener: string) => {
      const at = tab.indexOf(needle);
      assert.ok(at > 0, `${f.name}: no ${needle} in the form`);
      return tab.slice(tab.lastIndexOf(opener, at), tab.indexOf(">", at));
    };
    assert.match(tagAround("onClick={saveNew}", "<Button"), new RegExp(`disabled=\\{[^}]*\\b${f.saving}\\b[^}]*\\}`), `${f.name}: the Save button is not held while a request is out`);
    assert.match(tagAround(`onClick={${f.close}}`, "<button"), new RegExp(`disabled=\\{${f.saving}\\}`), `${f.name}: Cancel is live while a Save is out: a late answer acts on a form opened for another record`);
  });
}

// ═════════════════════════════════════════════════════════════════════════════
// 4. THE DATES: OPTIONAL ONES ARE NULL WHEN BLANK, REQUIRED ONES ARE ASKED FOR
// ═════════════════════════════════════════════════════════════════════════════

test("an optional date is sent as null when blank; a required one is asked for in a sentence and never sent as null", () => {
  const mca = read(MCA);
  assert.match(mca, /incorporation_date: form\.incorporation_date \|\| null/, "a company with no incorporation date typed is sent \"\", which a DATE column cannot take");
  assert.match(mca, /date_of_appointment: form\.date_of_appointment \|\| null/, "a director with no appointment date typed is sent \"\", which a DATE column cannot take");
  // A filing's due date is REQUIRED (`mca_filings.due_date` is NOT NULL): asked for, in the date's own words, and never turned into null.
  assert.doesNotMatch(mca, /due_date: form\.due_date \|\| null/, "a filing's due date is sent as null when blank: the column is NOT NULL, so the database refuses it as it refused \"\"");
  assert.match(mca, /if \(!form\.due_date\) \{ setNewError\("Due date: enter the date this form is due\."\); return; \}/, "a blank due date is no longer refused in a sentence of its own");
  // The challan's date, and the texts it is known by, are required too.
  const tds = read(TDS);
  for (const sentence of [
    "Challan date: enter the date on the challan.", "Challan number: enter the serial number printed on the challan.",
    "BSR code: enter the code of the bank branch printed on the challan.", "TDS section: enter the section this challan pays, for example 194C.", "Financial year: enter it as 2026-27.",
  ]) assert.ok(tds.includes(`"${sentence}"`), `the challan form no longer asks for it in a sentence: ${sentence}`);
});

test("the incorporation date and the challan's date are bounded by today and refuse a later day; the due date and a director's appointment are not bounded", () => {
  // A company that has a CIN has been incorporated, and the bank has taken the tax by the day a challan is dated (the seventeenth slice reversed this file's earlier stance that a
  // challan's date is judged as a day only; how far back it may go is the period lock's, and no statutory reading is assumed in the box).
  for (const [rel, id, what] of [[MCA, "mca-company-incorporated", "a company that has a CIN has been incorporated"], [TDS, "tds-client-challan-date", "the bank has taken the tax by the day a challan is dated"]] as const) {
    const box = dateInputWithId(read(rel), id);
    assert.ok(box, `the DateInput ${id} is gone`);
    assert.match(box, /notAfter=\{todayIstISO\(\)\}/, `${what}: the box ${id} is bounded by today in India`);
    assert.match(box, /\{ afterMax: true \}/, `…and a later day is refused, not merely hinted (${id})`);
  }
  // A due date is a plan, and a director may be appointed with effect from a later day.
  for (const [rel, id] of [[MCA, "mca-new-filing-due-date"], [MCA, "mca-director-appointment"]] as const) {
    const box = dateInputWithId(read(rel), id);
    assert.ok(box, `the DateInput ${id} is gone`);
    assert.doesNotMatch(box, /notAfter|afterMax|max=/, `${id} is bounded: a due date is a plan, and an appointment may be dated ahead`);
  }
});

test("the TDS tab shows what recording a challan did to the compliance calendar, in the server's words", () => {
  const tab = componentOf(read(TDS), "ChallansTab");
  assert.match(tab, /res\.data\?\.compliance_obligations/, "the challan's answer about the monthly deposit obligations is thrown away again");
  assert.ok(tab.includes("What became of the monthly deposits on the compliance calendar:"), "the answer is not shown");
});

// ═════════════════════════════════════════════════════════════════════════════
// 5. NO WRITE DROPS ITS ANSWER (POST-A-391)
// ═════════════════════════════════════════════════════════════════════════════

// Nine writes on the three pages used to be a statement that begins `await apiFetch(` and carries a write method, so nothing read what came back: the status changes of a filing
// (MCA) and of a TDS return, a director's KYC change, the creation of a TDS return and the save of a statement computed from the books, and the creation of a GSTR-1 and of a
// GSTR-3B and the save of each from the books. A refused or failed write there looked like a button that does nothing, and a refused create or save closed the form or the dialog
// as though it had worked. They read their answers now and the count is nothing: it is a RULE (a new write on these pages that drops its answer fails), no longer a count that could
// only fall. The count is made by reading each call's own parentheses, so a long body is counted.
const DROPPED_ANSWERS: Record<string, number> = { [MCA]: 0, [TDS]: 0, [GST]: 0 };

/** The statements `await apiFetch(…)` of a file whose call carries a write method, the call's own parentheses balanced. The helper may carry a type argument
 *  (`await apiFetch<unknown>(…)`: the payroll page's is generic, and a pattern that stopped at the `(` did not see such a call). */
function droppedWrites(code: string): string[] {
  const out: string[] = [];
  for (const m of code.matchAll(/^[ \t]+await apiFetch\s*(?:<[^()\n]*>)?\s*\(/gm)) {
    const call = balanced(code, m.index + m[0].length - 1);
    if (/method:\s*"(?:POST|PATCH|PUT|DELETE)"/.test(call)) out.push(call.replace(/\s+/g, " ").slice(0, 90));
  }
  return out;
}

test("no write on a client compliance page drops its answer", () => {
  for (const [rel, expected] of Object.entries(DROPPED_ANSWERS)) {
    const dropped = droppedWrites(read(rel));
    assert.equal(dropped.length, expected, `${rel}: ${dropped.length} writes drop their answer: read it (\`const res = await apiFetch(…)\` and \`!res?.success\`) and say a refusal beside the button that raised it:\n  ${dropped.join("\n  ")}`);
  }
});

test("no `await apiFetch(…)` write ANYWHERE in the app drops its answer: the rule is the app's, not a list of three pages", () => {
  // The three pages had nine; the client payroll page's PT registration removal was the tenth and the last (POST-A-391). A page of this app that names a write helper `apiFetch`
  // and awaits a POST, PATCH, PUT or DELETE without reading what comes back is a button that does nothing when the server refuses it. WHAT THIS READS is the spelling
  // `await apiFetch(…)` (with or without a type argument) in app/ and components/: a write through another name (`api.*`, `request`, a function of lib/) is outside it, and
  // that is written down as not done in POST-A-391's closing account, not covered here.
  let looked = 0;
  for (const dir of ["app", "components"]) {
    for (const file of sources(path.join(WEB, dir))) {
      const rel = path.relative(WEB, file);
      const dropped = droppedWrites(read(rel));
      looked += 1;
      assert.deepEqual(dropped, [], `${rel}: ${dropped.length} write(s) drop their answer: read it (\`const res = await apiFetch(…)\` and \`!res?.success\`) and say a refusal beside the control that raised it`);
    }
  }
  assert.ok(looked > 300, `only ${looked} files were looked at: the scan is not reading the app`);
});

/** The text of the function `name` declared after `after` in `code`, its braces balanced. */
function functionAfter(code: string, after: string, name: string): string {
  const from = code.indexOf(after);
  assert.ok(from >= 0, `\`${after}\` is not in the file`);
  const at = code.indexOf(`async function ${name}(`, from);
  assert.ok(at >= 0, `\`async function ${name}(\` is not declared after \`${after}\``);
  const brace = code.indexOf("{", code.indexOf(")", at));
  return balanced(code, brace);
}

/** `const res = await apiFetch(…)` in a handler's body and what must follow it: the refusal branch, straight after the call (nothing between), and where the branch ends. */
function afterTheCall(body: string, label: string, refusal: RegExp = /^\s*;\s*if \(!res\?\.success\) \{/) {
  const head = "const res = await apiFetch(";
  const callAt = body.indexOf(head);
  assert.ok(callAt >= 0, `${label}: its answer is not read into a variable`);
  const open = callAt + head.length - 1;
  const callEnd = open + 1 + balanced(body, open).length + 1;
  const found = refusal.exec(body.slice(callEnd));
  assert.ok(found, `${label}: the refusal is not the FIRST thing done with the answer (something comes between the call and the \`if\` that looks at it: a closer placed there closes the form over a refusal)`);
  const branchOpen = callEnd + found[0].length - 1;
  const branch = balanced(body, branchOpen);
  return { callAt, callEnd, branch, branchEnd: branchOpen + 1 + branch.length + 1 };
}

/** The opening tag that starts at `start`, up to the `>` that closes it (an arrow function's `=>` inside braces does not). */
function openingTagAt(code: string, start: number): string {
  let depth = 0;
  for (let i = start; i < code.length; i++) {
    const c = code[i];
    if (c === '"' || c === "'" || c === "`") {
      for (i++; i < code.length && code[i] !== c; i++) if (code[i] === "\\") i++;
      continue;
    }
    if (c === "{") depth++;
    else if (c === "}") depth--;
    else if (c === ">" && depth === 0) return code.slice(start, i + 1);
  }
  return code.slice(start);
}

/** What closes a form or a dialog, empties it, or reads the list again: none of it may happen before the refusal branch has ended, or in the catch. */
const CLOSERS = /\b(?:setShowNew|setShowCompute)\(false\)|\b(?:closeNew|closeForm)\(\)|\bsetComputeResult\(null\)|\bload\(\)/;

/** The JSX block `{showNew && (` or `{showCompute && (` of a component: where it starts and where its parenthesis closes. */
function blockOf(tab: string, opener: string, label: string): { at: number; end: number; text: string } {
  const at = tab.indexOf(opener);
  assert.ok(at >= 0, `${label}: \`${opener}\` is no longer in the component`);
  const text = balanced(tab, at + opener.length - 1);
  return { at, end: at + opener.length + text.length, text };
}

type Where = "row" | "form" | "compute";
type TheNine = {
  file: string; component: string; fn: string; call: RegExp; says: string; shown: string; what: string;
  /** The state held while the request is out (the Cancel beside it is held with it); null for a row action, which has none. */
  flag: string | null;
  /** Where the sentence is drawn: above the table (a row action), inside the create form, inside the compute dialog. */
  where: Where;
  /** True for the one write whose refusal may be a QUESTION and not a failure (POST-A-402): the refusal branch may begin with the server's marker that the
   *  CA can record the statement anyway, which sets the question and returns, before the sentence is said. Nothing else may come first. */
  heldBack?: true;
};
/** The nine, each by the tab that holds it, the call it makes and the line it says a refusal on. `says` is the state that sentence is held in and `shown` how the screen draws it. */
const THE_NINE: TheNine[] = [
  { file: MCA, component: "DirectorsTab", fn: "updateKYC", call: /apiFetch\(`\/api\/mca-workspace\/directors\/\$\{id\}`/, says: "setKycError", shown: "kycError", what: "a director's KYC change", flag: null, where: "row" },
  { file: MCA, component: "FilingsTab", fn: "updateStatus", call: /apiFetch\(`\/api\/mca-workspace\/filings\/\$\{id\}\/status`/, says: "setStatusError", shown: "statusError", what: "a filing's status change", flag: null, where: "row" },
  { file: TDS, component: "ReturnsTab", fn: "saveNew", call: /apiFetch\("\/api\/tds-workspace\/returns"/, says: "setNewError", shown: "newError", what: "the creation of a TDS return", flag: "creating", where: "form" },
  { file: TDS, component: "ReturnsTab", fn: "updateStatus", call: /apiFetch\(`\/api\/tds-workspace\/returns\/\$\{id\}\/status`/, says: "setStatusError", shown: "statusError", what: "a TDS return's status change", flag: null, where: "row", heldBack: true },
  { file: TDS, component: "ReturnsTab", fn: "saveComputed", call: /apiFetch\("\/api\/tds-workspace\/returns"/, says: "setSaveComputedError", shown: "saveComputedError", what: "the save of a TDS statement computed from the books", flag: "savingComputed", where: "compute" },
  { file: GST, component: "GSTR1Tab", fn: "saveNew", call: /apiFetch\("\/api\/gst-workspace\/gstr1"/, says: "setNewError", shown: "newError", what: "the creation of a GSTR-1", flag: "saving", where: "form" },
  { file: GST, component: "GSTR1Tab", fn: "saveComputed", call: /apiFetch\("\/api\/gst-workspace\/gstr1"/, says: "setSaveComputedError", shown: "saveComputedError", what: "the save of a GSTR-1 computed from the books", flag: "savingComputed", where: "compute" },
  { file: GST, component: "GSTR3BTab", fn: "saveNew", call: /apiFetch\("\/api\/gst-workspace\/gstr3b"/, says: "setNewError", shown: "newError", what: "the creation of a GSTR-3B", flag: "saving", where: "form" },
  { file: GST, component: "GSTR3BTab", fn: "saveComputed", call: /apiFetch\("\/api\/gst-workspace\/gstr3b"/, says: "setSaveComputedError", shown: "saveComputedError", what: "the save of a GSTR-3B computed from the books", flag: "savingComputed", where: "compute" },
];
const setterOf = (flag: string) => `set${flag[0].toUpperCase()}${flag.slice(1)}`;

test("the nine writes that used to drop their answer read it, hold the form or the dialog open over a refusal, and say it where the button that raised it is", () => {
  assert.equal(THE_NINE.length, 9);
  for (const n of THE_NINE) {
    const code = read(n.file);
    const tab = componentOf(code, n.component);
    const body = functionAfter(tab, `function ${n.component}(`, n.fn);
    const label = `${n.file}: ${n.what} (${n.component}.${n.fn})`;
    assert.match(body, n.call, `${label}: it does not make the call this row names`);
    assert.match(body, /const res = await apiFetch\(/, `${label}: its answer is not read into a variable`);
    assert.match(body, /if \(!res\?\.success\) \{/, `${label}: it does not look at whether the server accepted it`);
    assert.match(body, new RegExp(`${n.says}\\(res\\?\\.error \\?\\? "`), `${label}: a refusal's own sentence is not what it says`);
    // A request that failed is said through the one helper (POST-A-406): the browser's words for a dropped connection are replaced by the product's sentence there.
    assert.match(body, new RegExp(`catch \\(e\\) \\{\\s*${n.says}\\(failureSentence\\(e, "`), `${label}: a request that failed is not said`);
    // a refusal ends the function BEFORE the form closes or the list is read again: the `return` follows the sentence
    assert.match(body, new RegExp(`${n.says}\\(res\\?\\.error \\?\\? "[^"]*"\\);\\s*(?:\\/\\/[^\\n]*\\n\\s*)*return;`), `${label}: a refusal does not stop the function before the form closes`);

    // The ORDER. The refusal is the first thing done with the answer, says its sentence and returns, and nothing that closes the form or reads the list again comes before it
    // ends (a `setShowNew(false)` placed above the `if` closed the form over a refusal and every other check here stayed green: found by the independent read).
    const { callAt, branch, branchEnd } = afterTheCall(body, label);
    // …except for the one write whose refusal may be a question: its branch may BEGIN with the marker check that sets the question and returns (nothing is said, closed or read again first).
    const question = n.heldBack
      ? "const marker = res\\?\\.data as [^;]*;\\s*if \\(marker\\?\\.can_record_anyway === true && res\\?\\.error\\) \\{\\s*setHeldBack\\(\\{ id, status, sentence: res\\.error \\}\\);\\s*return;\\s*\\}\\s*"
      : "";
    assert.match(branch.trim(), new RegExp(`^${question}${n.says}\\(res\\?\\.error \\?\\? "[^"]*"\\);\\s*return;$`), `${label}: the refusal branch does more than say the sentence and return`);
    const closer = CLOSERS.exec(body);
    assert.ok(closer, `${label}: nothing closes the form or reads the list again after a success`);
    assert.ok(closer.index >= branchEnd, `${label}: \`${closer[0]}\` comes before the answer has been looked at: the form closes, or the list is read, over a refusal`);
    // …and a request that failed says so and closes nothing.
    const caught = balanced(body, body.indexOf("{", body.indexOf("catch (e)")));
    assert.doesNotMatch(caught, CLOSERS, `${label}: a request that failed closes the form or reads the list as though it had worked`);
    // The last answer is cleared when a new press begins (before anything goes out): a sentence about the last press is not about this one.
    const clearAt = body.indexOf(`${n.says}(null)`);
    assert.ok(clearAt >= 0 && clearAt < callAt, `${label}: the last sentence is not cleared when a new press begins`);
    // The flag held across the request is set before it and reset in a `finally` (a refusal and a failure both end there).
    if (n.flag) {
      const set = setterOf(n.flag);
      const onAt = body.indexOf(`${set}(true)`);
      assert.ok(onAt >= 0 && onAt < callAt, `${label}: ${set}(true) does not come before the request`);
      assert.match(body, new RegExp(`finally\\s*\\{\\s*${set}\\(false\\);?\\s*\\}`), `${label}: ${set}(false) is not in a finally: a refusal or a failure leaves the screen held`);
    }

    // WHERE the sentence is drawn: as an alert, in THIS tab (two tabs of one file each have their own `newError`), and INSIDE the control that raised it.
    const drawn = new RegExp(`\\{${n.shown} && <p role="alert" className="text-xs text-state-problem">\\{${n.shown}\\}</p>\\}`).exec(tab);
    assert.ok(drawn, `${label}: \`${n.shown}\` is not drawn as an alert`);
    if (n.where === "row") {
      // Above the table, outside every form, and cleared when the list is read again (a refusal of a row action is about the list as it stood).
      assert.ok(drawn.index < tab.indexOf("<table"), `${label}: the sentence is drawn below the table, away from the button that raised it`);
      for (const opener of ["{showNew && (", "{showCompute && ("]) {
        if (!tab.includes(opener)) continue;
        const block = blockOf(tab, opener, label);
        assert.ok(drawn.index < block.at || drawn.index >= block.end, `${label}: the sentence is drawn inside a form (${opener}), where a person who is not in it never sees it`);
      }
      const reloaded = bodyOf(tab, /const load = useCallback\((?:async )?\(\) => \{/);
      assert.match(reloaded, new RegExp(`${n.says}\\(null\\)`), `${label}: a list read again still shows the last refusal, though it was about the list as it stood`);
    } else {
      const opener = n.where === "form" ? "{showNew && (" : "{showCompute && (";
      const block = blockOf(tab, opener, label);
      assert.ok(drawn.index > block.at && drawn.index < block.end, `${label}: the sentence is not drawn inside the ${n.where === "form" ? "form" : "dialog"} that raised it`);
      // The Cancel of that form or dialog is held while the save is out: Cancel in the middle of a request, then a late refusal sets a sentence on a closed dialog
      // (and the late answer of a save that WORKED is lost).
      const cancelAt = block.text.indexOf("Cancel</button>");
      assert.ok(cancelAt > 0, `${label}: no Cancel in the ${n.where === "form" ? "form" : "dialog"}`);
      const tag = openingTagAt(block.text, block.text.lastIndexOf("<button", cancelAt));
      assert.match(tag, new RegExp(`disabled=\\{${n.flag}\\}`), `${label}: Cancel is live while the save is out`);
      // …and Cancel empties the last sentence of that dialog, so it is not there when the dialog is opened again.
      assert.match(tag, new RegExp(`${n.says}\\(null\\)`), `${label}: Cancel leaves the last sentence to be shown when the ${n.where === "form" ? "form" : "dialog"} is opened again`);
    }
  }
});

test("the TDS compute dialog's boxes that choose the statement empty the result computed for the old choice, and are held while a compute or a save is out", () => {
  // Compute 26Q, flip the Return type to 24Q, Save as Draft: the 26Q's figures were stored as a 24Q statement (found by the independent read of POST-A-391; the save sends the
  // form's type and the result is the old choice's). A change empties the result, and the boxes are held while a request is out so a late answer cannot land on a changed choice.
  const tab = componentOf(read(TDS), "ReturnsTab");
  assert.match(bodyOf(tab, /function chooseStatement\(patch: Partial<typeof computeForm>\) \{/), /setComputeResult\(null\)/, "choosing a statement does not empty the result computed for the last choice");
  for (const aria of ["Return type", "Quarter", "Financial year (for example 2025-26)"]) {
    const at = tab.indexOf(`aria-label="${aria}"`);
    assert.ok(at > 0, `the compute dialog has no box labelled ${aria}`);
    const tag = openingTagAt(tab, tab.lastIndexOf("<", at));
    assert.match(tag, /onChange=\{\(e\) => chooseStatement\(/, `${aria}: a change does not empty the computed result (it can be saved under another form)`);
    assert.match(tag, /disabled=\{actionInFlight\}/, `${aria}: the box is live while a compute or a save is out`);
  }
});

test("the tenth write, the payroll page's removal of a professional tax registration, reads its answer, accepts only a success and says the page's reading of a refusal", () => {
  const code = read(PAYROLL);
  const body = bodyOf(code, /async function removePt\(state: string\) \{/);
  const label = "the payroll page's removePt";
  assert.match(body, /apiFetch\(`\/api\/payroll\/statutory-identity\/pt\?client_id=\$\{clientId\}&state=\$\{state\}`/, `${label}: it does not make the call this row names`);
  // The refusal is the first thing done with the answer and it ACCEPTS ONLY A SUCCESS: apiFetch hands back null for an answer that is not JSON, and `=== false` read that as accepted.
  const { callAt, branch, branchEnd } = afterTheCall(body, label, /^\s*;\s*if \(\(res as \{ success\?: boolean \} \| null\)\?\.success !== true\) \{/);
  assert.match(branch.trim(), /^setSaveError\(refusalText\(res\) \?\? "Couldn't remove the registration\."\);\s*return;$/, `${label}: the refusal branch does not say the page's reading of the refusal (a string, or the 422's messages) and return`);
  const closer = CLOSERS.exec(body);
  assert.ok(closer, `${label}: nothing reads the list again after a success`);
  assert.ok(closer.index >= branchEnd, `${label}: \`${closer[0]}\` comes before the answer has been looked at`);
  assert.match(body, /catch \(e\) \{\s*setSaveError\(failureSentence\(e, "Couldn't remove the registration\.", "write"\)\);\s*\}/, `${label}: a request that failed is not said`);
  const clearAt = body.indexOf("setSaveError(null)");
  assert.ok(clearAt >= 0 && clearAt < callAt, `${label}: the last sentence is not cleared when a new press begins`);
  assert.ok(body.indexOf('setSaving("pt")') >= 0 && body.indexOf('setSaving("pt")') < callAt, `${label}: the screen is not held while the request is out`);
  assert.match(body, /finally\s*\{\s*setSaving\(null\);?\s*\}/, `${label}: the hold is not released in a finally`);
  // Drawn by a Callout whose tone is `problem`, which carries role="alert" (components/ui/callout.tsx), in the component that holds the removal.
  const component = code.slice(code.lastIndexOf("\nfunction ", code.indexOf("async function removePt(")));
  assert.match(component, /\{saveError && <Callout tone="problem">\{saveError\}<\/Callout>\}/, `${label}: the sentence is not drawn as a problem callout`);
  assert.match(fs.readFileSync(path.join(WEB, "components/ui/callout.tsx"), "utf8"), /role=\{tone === "problem" \? "alert" : undefined\}/, "a problem callout no longer carries role=alert: the tenth sentence would be silent to a screen reader");
});


test("the counter sees a long body (a self-test of the way the writes are counted)", () => {
  const code = [
    "async function a() {",
    "    await apiFetch(\"/api/x\", {",
    "      method: \"POST\",",
    "      body: JSON.stringify({ client_id: clientId, period: \"2026-09\", return_type: \"gstr1\", lines: rows.map((r) => ({ id: r.id, amount: r.amount })), notes: \"a long body with (nested) parentheses and more text\" }),",
    "    });",
    "    const res = await apiFetch(\"/api/y\", { method: \"POST\", body: \"{}\" });",
    "    await apiFetch(`/api/z?client_id=${clientId}`);",
    "    await apiFetch<unknown>(\"/api/g\", { method: \"DELETE\" });",
    "}",
  ].join("\n");
  assert.equal(droppedWrites(code).length, 2, "the long dropped write, or the one through a generic helper, is not counted, or a read or an assigned write is");
});

// ── a compute that FAILS outright (POST-A-403) ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
// `computeFromBooks` on the TDS returns tab and on the GSTR-1 and GSTR-3B tabs set `computing`, awaited the page's own `apiFetch` and cleared the flag on the line after it. A request that THROWS (a dropped
// connection, or a proxy's error page that arrives as a 200 and is not JSON, which `res.json()` rejects) skipped that line and nothing said what happened: the dialog stayed on "Computing…" with Compute held until
// the page was loaded again. They are reads (nothing is saved), which is why POST-A-391, about the writes, did not take them. They have the shape the saves have: the sentence the thrown error carries, said in the
// dialog, and the hold released in a `finally`.
const THE_THREE_COMPUTES = [
  { file: TDS, component: "ReturnsTab", failed: "Couldn't compute Form ${computeForm.return_type} from books.", what: "the TDS tab's compute" },
  { file: GST, component: "GSTR1Tab", failed: "Couldn't compute GSTR-1 from books.", what: "the GSTR-1 tab's compute" },
  { file: GST, component: "GSTR3BTab", failed: "Couldn't compute GSTR-3B from books.", what: "the GSTR-3B tab's compute" },
];

test("the three compute-from-books handlers catch a request that fails outright, say it in the dialog and release the hold in a finally", () => {
  for (const c of THE_THREE_COMPUTES) {
    const tab = componentOf(read(c.file), c.component);
    const body = functionAfter(tab, `function ${c.component}(`, "computeFromBooks");
    const label = `${c.file}: ${c.what} (${c.component}.computeFromBooks)`;
    const onAt = body.indexOf("setComputing(true)");
    const tryAt = body.indexOf("try {");
    const callAt = body.indexOf("const r = await apiFetch(");
    assert.ok(onAt >= 0 && tryAt > onAt && callAt > tryAt, `${label}: the hold is not taken before a try that holds the request`);
    // the last result, error and save sentence are emptied before the request goes out: a sentence about the last press is not about this one
    for (const cleared of ["setComputeError(null)", "setComputeResult(null)", "setSaveComputedError(null)"]) {
      const at = body.indexOf(cleared);
      assert.ok(at >= 0 && at < tryAt, `${label}: ${cleared} is not done when a new press begins`);
    }
    const caught = /catch \(e\) \{\s*setComputeError\(failureSentence\(e, `?"?([^`"]*)`?"?, "read"\)\);\s*\}/.exec(body);
    assert.ok(caught, `${label}: a request that failed is not said in the dialog`);
    assert.equal(caught[1], c.failed, `${label}: the failure's own sentence is not the refusal's wording`);
    assert.match(body, /finally \{\s*setComputing\(false\);\s*\}/, `${label}: setComputing(false) is not in a finally: a failed request leaves the dialog on "Computing…"`);
    assert.equal(body.match(/setComputing\(false\)/g)?.length, 1, `${label}: the hold is released somewhere other than the finally`);
    // a refusal says its sentence (unchanged) and a success shows the result; neither returns before the finally runs
    assert.match(body, /if \(r\.success\) setComputeResult\(r\.data as Record<string, unknown>\);\s*else setComputeError\(r\.error \?\? /, `${label}: the answer is no longer read`);
    // the sentence is an alert, so a screen reader announces it, and it is drawn inside the dialog that raised it
    const dialog = blockOf(tab, "{showCompute && (", label);
    const drawn = /\{computeError && <p role="alert" className="text-state-problem text-sm">\{computeError\}<\/p>\}/.exec(dialog.text);
    assert.ok(drawn, `${label}: the sentence is not drawn inside the compute dialog as an alert`);
  }
});

test("a handler that holds a flag across a request releases it in a finally, anywhere in the app", () => {
  // The flags a hold is taken with. The first version of this rule followed the name `computing` alone, and the independent read of POST-A-403 found the same defect under
  // another name in the same file (the GSTR-1 tab's `markingFiled`: a request that threw left "Recording…" with both buttons held until the page was loaded again).
  const HOLD = /set(Computing|Marking\w*|Saving|Busy|Posting|Submitting|Running|Generating|Approving|Filing)\(true\)/g;
  let looked = 0;
  const flags = new Set<string>();
  for (const file of [...sources(path.join(WEB, "app")), ...sources(path.join(WEB, "components"))]) {
    const rel = path.relative(WEB, file).split(path.sep).join("/");
    const code = stripComments(fs.readFileSync(file, "utf8"));
    for (const m of code.matchAll(HOLD)) {
      looked++;
      flags.add(m[1]);
      // climb out of the blocks the call sits in (an `if`, a `try`) to the function whose body it is
      let from = m.index!;
      let body = "";
      for (let guard = 0; guard < 8; guard++) {
        let depth = 0, open = -1;
        for (let i = from - 1; i >= 0; i--) {
          if (code[i] === "}") depth++;
          else if (code[i] === "{") { if (depth === 0) { open = i; break; } depth--; }
        }
        assert.ok(open >= 0, `${rel}: set${m[1]}(true) is not inside a block`);
        const header = code.slice(Math.max(0, open - 160), open);
        if (/(?:function\s*\w*\s*\([^)]*\)[^{]*|=>\s*)$/.test(header)) { body = balanced(code, open); break; }
        from = open;
      }
      assert.ok(body, `${rel}: the function that holds the flag was not found`);
      // a `finally { … set…(false) }` block, or a promise chain's `.finally(() => set…(false))` (the capital gains calculator's debounced call), which may be
      // guarded by the effect's own `cancelled` flag (the deductions screen's: a request already in flight when the inputs change must not release a newer one's hold)
      const released = new RegExp(`(?:finally \\{[^}]*|\\.finally\\(\\(\\) => (?:\\{\\s*if \\(!cancelled\\) )?)set${m[1]}\\(false\\)`);
      assert.match(body, released, `${rel}: set${m[1]}(true) is not released in a finally: a request that throws leaves the screen held ("Computing…", "Recording…")`);
    }
  }
  assert.ok(looked >= 20, `only ${looked} holds were looked at: the scan is not reading the app`);
  assert.ok(flags.has("Computing") && flags.has("MarkingFiled"), `the scan no longer finds the flags it was written for (${[...flags].join(", ")})`);
});
