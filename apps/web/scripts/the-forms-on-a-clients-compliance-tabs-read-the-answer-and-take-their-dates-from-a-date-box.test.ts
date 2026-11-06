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
//   5. The writes on the three pages whose answer is still dropped are COUNTED, by reading each call's own parentheses, and the count can only fall: `DROPPED_ANSWERS`.
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
    const helper = bodyOf(code, /async function apiFetch\(path: string, opts\?: RequestInit\) \{/);
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
// 5. WRITES WHOSE ANSWER IS STILL DROPPED
// ═════════════════════════════════════════════════════════════════════════════

// The writes on the three pages whose answer is still dropped (a statement that begins `await apiFetch(` and carries a write method, so nothing reads what came back):
// the status changes of a filing (MCA) and of a TDS return, a director's KYC change, the creation of a TDS return and the save of a statement computed from the books,
// and the creation of a GSTR-1 and of a GSTR-3B and the save of each from the books. Each is written on the ledger line PRE-A-015 as found and not changed. The count is
// made by reading each call's own parentheses, so a long body is counted; it can only fall.
const DROPPED_ANSWERS: Record<string, number> = { [MCA]: 2, [TDS]: 3, [GST]: 4 };

/** The statements `await apiFetch(…)` of a file whose call carries a write method, the call's own parentheses balanced. */
function droppedWrites(code: string): string[] {
  const out: string[] = [];
  for (const m of code.matchAll(/^[ \t]+await apiFetch\(/gm)) {
    const call = balanced(code, m.index + m[0].length - 1);
    if (/method:\s*"(?:POST|PATCH|PUT|DELETE)"/.test(call)) out.push(call.replace(/\s+/g, " ").slice(0, 90));
  }
  return out;
}

test("the writes whose answer is still dropped are counted, and the count only falls", () => {
  for (const [rel, expected] of Object.entries(DROPPED_ANSWERS)) {
    const dropped = droppedWrites(read(rel));
    assert.ok(dropped.length <= expected, `${rel}: ${dropped.length} writes drop their answer, up from ${expected}: read the answer (\`const res = await apiFetch(…)\` and \`!res?.success\`):\n  ${dropped.join("\n  ")}`);
    assert.equal(dropped.length, expected, `${rel}: ${expected - dropped.length} fewer writes drop their answer: lower DROPPED_ANSWERS to ${dropped.length} so the count stays exact`);
  }
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
    "}",
  ].join("\n");
  assert.equal(droppedWrites(code).length, 1, "the long dropped write is not counted, or a read or an assigned write is");
});
