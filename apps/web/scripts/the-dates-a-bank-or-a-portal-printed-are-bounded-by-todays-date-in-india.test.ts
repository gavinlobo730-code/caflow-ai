// THE DAYS A BANK OR A PORTAL PRINTED CANNOT BE AFTER TODAY IN INDIA, AND A SENTENCE ABOUT THEM GOES WHEN THEY ARE PUT RIGHT (PRE-A-015, sixteenth slice).
//   node --experimental-strip-types --test scripts/the-dates-a-bank-or-a-portal-printed-are-bounded-by-todays-date-in-india.test.ts
//
// THE DEFECT
//   An advance-tax instalment's paid-on date, the section 140A challan's deposit date, a Capital Gains Accounts Scheme deposit, the IRP's acknowledgement day, the e-way bill's own date
//   and the day Form 15CA was filed are all facts that have happened by the time they are recorded: a bank has taken the money and a portal has printed the day. None of the six boxes
//   had any bound, and five of the six reached a server that stored a day that had not come (the advance-tax instalment's paid date was already refused there). The three income-tax
//   forms also copied the date's sentence into their own error, where it stayed after the date was put right, and the answer to an EARLIER attempt (the server's refusal) sat hidden
//   under the date's sentence and came back when the date was put right.
//
// THE RULES (each read from the source as a RULE and not as one spelling of it, with the detectors tried below on the spellings that evade a looser reading; each EXECUTED by the browser
// drive, scripts/drive/scenarios/dates.mjs, whose scenarios the last test imports and requires; the server half is tests/test_the_dates_a_bank_or_a_portal_printed_are_not_after_today.py)
//   1. Each of the six boxes is bounded by today in India (`notAfter={todayIstISO()}`), refuses a later day instead of hinting at it (`{ afterMax: true }`), and reports to the hook
//      its Save reads, so the sentence it makes is the one the Save refuses with.
//   2. The e-way bill's "Valid upto" is a plan and may run ahead: it is not bounded by today.
//   3. The advance-tax Save, the section 140A challan and the reinvestment claim say a date's sentence through `useDateRefusal` and nowhere else: their handler mentions the hook that
//      holds the date problems only inside the latch call, and no call of the form's error setter takes anything from a date hook. Each handler clears what the last attempt said
//      BEFORE it refuses, and the form's own answer is shown in preference to the latch (it is the newer: a refused Delete is said over a date that was refused a moment before).
//   4. Their three writers and two deleters (lib/data/income-tax.ts) read a refusal through lib/api's `errorMessage`, so a 422 or a 4xx shows the server's sentence and not
//      "Unprocessable Entity" (FastAPI's `{"detail": …}` has no `error` key).
//   5. The Record IRN and Record E-Way Bill dialogs open on India's day (`todayIstISO()`), not the browser's: their date boxes are bounded by India's today, and a browser already on
//      the next day would open a box on a date it refuses.
//   The purchase bill editor, which copies every one of its dates' sentences into its error, is not changed by this slice and is named in the drive as the one that stays until the
//   next Save.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));
const TAX = "app/income-tax/advance-tax/page.tsx";
const CG = "app/income-tax/capital-gains/page.tsx";
const PANEL = "components/invoices/CompliancePanel.tsx";
const BILL = "components/purchases/PurchaseBillEditor.tsx";
const DATA = "lib/data/income-tax.ts";
const DRIVE = "scripts/drive/scenarios/dates.mjs";

// ── readers ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

/** The text from the opening bracket at `open` to its match, brackets included. */
function balancedFrom(code: string, open: number): string {
  const pairs: Record<string, string> = { "(": ")", "{": "}", "[": "]" };
  const start = code[open];
  const end = pairs[start];
  assert.ok(end, `no bracket at ${open}`);
  let depth = 0;
  for (let i = open; i < code.length; i++) {
    if (code[i] === start) depth++;
    else if (code[i] === end && --depth === 0) return code.slice(open, i + 1);
  }
  assert.fail(`an unbalanced ${start} at ${open}`);
}

/** The element `<DateInput … />` that carries `needle`, balanced on its braces. */
function dateInputWith(code: string, needle: string): string {
  const at = code.indexOf(needle);
  assert.ok(at > 0, `${needle} is no longer in the file`);
  const start = code.lastIndexOf("<DateInput", at);
  let depth = 0;
  for (let i = start; i < code.length; i++) {
    const c = code[i];
    if (c === "{") depth++;
    else if (c === "}") depth--;
    else if (c === ">" && depth === 0 && code[i - 1] === "/") return code.slice(start, i + 1);
  }
  assert.fail(`could not find the end of the DateInput around ${needle}`);
}

/** The text of a TOP-LEVEL function, from its header to the next top-level declaration. For a function whose parameters are a typed object (the dialogs, the data module's
 *  writers), where the first `)` and the first `{` after the header are not the end of the parameters and the start of the body. */
function topLevelText(code: string, header: string): string {
  const at = code.indexOf(header);
  assert.ok(at >= 0, `${header} is no longer in the file`);
  const next = code.slice(at + header.length).search(/\n(?:export |async |function |const |interface |type )/);
  return next < 0 ? code.slice(at) : code.slice(at, at + header.length + next);
}

/** The body, braces included, of a function with no typed parameters whose header starts with `header` (`async function handleSave(`). */
function bodyOf(code: string, header: string): string {
  const at = code.indexOf(header);
  assert.ok(at >= 0, `${header} is no longer in the file`);
  const paramsEnd = code.indexOf(")", at);
  return balancedFrom(code, code.indexOf("{", paramsEnd));
}

/** The argument text of every call `name(…)` (a method of something else, `x.name(`, is not one). */
function callsOf(code: string, name: string): string[] {
  const found: string[] = [];
  for (const m of code.matchAll(new RegExp(`(?<![\\w$.])${name}\\(`, "g"))) {
    found.push(balancedFrom(code, (m.index ?? 0) + m[0].length - 1).slice(1, -1));
  }
  return found;
}

// ── the detectors (rules, tried on samples below) ──────────────────────────────────────────────────────────────────────────────────────

/** Anything that takes a date's sentence, a date hook or its problems into a call of the form's own error setter, in any spelling. */
function copiesIntoTheError(code: string, setters: string[]): string[] {
  return setters.flatMap((s) => callsOf(code, s).filter((arg) => /\b\w*Dates\b|\.first\b|\.problems\b/.test(arg)).map((arg) => `${s}(${arg})`));
}

/** What a handler does with its date hook besides the latch: `{ latch, others }`. The latch is `if (<hook>.first) { <refusal>.refuse(); return; }` and there must be exactly one;
 *  everything else in the body that names a date hook or a `.first` is an `other`. */
function whatTheHandlerDoesWithTheHook(code: string, header: string): { hook: string | null; latches: number; others: string[] } {
  const body = bodyOf(code, header);
  const latch = /if \((\w+)\.first\) \{ \w+\.refuse\(\); return; \}/g;
  const latches = [...body.matchAll(latch)];
  const rest = body.replace(latch, " ");
  const others = [...rest.matchAll(/\b\w*Dates\b[^\n]{0,60}|[\w.]+\.first\b[^\n]{0,60}/g)].map((m) => m[0]);
  return { hook: latches[0]?.[1] ?? null, latches: latches.length, others };
}

/** Whether the handler has cleared the form's error by the time it first refuses a date. */
function clearsBeforeRefusing(code: string, header: string, clear: RegExp): boolean {
  const body = bodyOf(code, header);
  const refuse = body.indexOf(".refuse()");
  return refuse > 0 && clear.test(body.slice(0, refuse));
}

/** A dialog that opens on India's day: its date state starts from `today`, which is `todayIstISO()`, and nothing in it reads the browser's clock. */
function opensOnIndiasDay(body: string): string[] {
  const offences: string[] = [];
  if (!/const today = todayIstISO\(\);/.test(body)) offences.push("`today` is not todayIstISO()");
  if (!/useState\(today\)/.test(body)) offences.push("no date state starts from `today`");
  for (const m of body.matchAll(/new Date|Date\.now|toISOString|toLocale\w*|todayLocalISO/g)) offences.push(`reads the browser's clock: ${m[0]}`);
  return offences;
}

// ── tests ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

test("the six boxes for a day a bank or a portal printed are bounded by today in India and refuse a later day", () => {
  const boxes: Array<[string, string, string]> = [
    [TAX, "Instalment ${n} paid on", "an advance-tax instalment's paid-on date"],
    [TAX, 'id="sa-deposit-date"', "the section 140A challan's deposit date"],
    [CG, 'aria-label="CGAS deposit date"', "the Capital Gains Accounts Scheme deposit date"],
    [PANEL, 'aria-label="Acknowledgement date"', "the IRP's acknowledgement date"],
    [PANEL, 'aria-label="EWB date"', "the e-way bill's own date"],
    [BILL, 'id="bill-15ca-date"', "the day Form 15CA was filed"],
  ];
  for (const [file, needle, what] of boxes) {
    const box = dateInputWith(read(file), needle);
    assert.match(box, /notAfter=\{todayIstISO\(\)\}/, `${what} is no longer bounded by today in India (${file})`);
    assert.match(box, /\{ afterMax: true \}/, `${what} only hints at a later day: it must refuse it (${file})`);
  }
});

test("each of the six boxes reports to the hook its Save reads", () => {
  const tax = read(TAX);
  const cg = read(CG);
  const hookOf = (box: string) => /\b(\w+)\.watch\(/.exec(box)?.[1];
  // The three forms: the hook the box reports to is the hook the handler's latch asks.
  assert.equal(hookOf(dateInputWith(tax, "Instalment ${n} paid on")), whatTheHandlerDoesWithTheHook(tax, "async function handleSave(").hook, "an instalment's paid-on box reports to a hook the Save never asks");
  assert.equal(hookOf(dateInputWith(tax, 'id="sa-deposit-date"')), whatTheHandlerDoesWithTheHook(tax, "async function handleAddChallan(").hook, "the §140A deposit box reports to a hook Record challan never asks");
  assert.equal(hookOf(dateInputWith(cg, 'aria-label="CGAS deposit date"')), whatTheHandlerDoesWithTheHook(cg, "async function saveClaim(").hook, "the CGAS box reports to a hook Record claim never asks");
  // The two portal dialogs: `problem` is made from the hook the box reports to.
  const panel = read(PANEL);
  for (const [fn, needle] of [["RecordIrnModal", 'aria-label="Acknowledgement date"'], ["RecordEwayModal", 'aria-label="EWB date"']] as const) {
    const body = topLevelText(panel, `function ${fn}(`);
    const hook = hookOf(dateInputWith(body, needle));
    assert.ok(hook && new RegExp(`const problem = ${hook}\\.first\\b`).test(body), `${fn}: the box reports to a hook the dialog's \`problem\` is not made from`);
  }
  // The bill editor: the hook its box reports to is the one its Save asks.
  const bill = read(BILL);
  const billHook = hookOf(dateInputWith(bill, 'id="bill-15ca-date"'));
  assert.ok(billHook && new RegExp(`if \\(${billHook}\\.first\\)`).test(bill), "the Form 15CA box reports to a hook the bill editor's Save never asks");
});

test("an e-way bill's valid-upto day is a plan and may run ahead", () => {
  const validUpto = dateInputWith(read(PANEL), 'aria-label="Valid upto"');
  assert.doesNotMatch(validUpto, /notAfter|afterMax|max=/, "the day an e-way bill is valid upto is bounded by today again: it may run ahead of it");
  assert.match(validUpto, /notBefore=\{date \|\| null\}/, "the validity no longer begins at the bill's own date");
});

test("the advance-tax Save, the section 140A challan and the reinvestment claim say a date's sentence through the latch and nowhere else", () => {
  const tax = read(TAX);
  const cg = read(CG);
  assert.match(tax, /const advRefusal = useDateRefusal\(advDates\.first\);/);
  assert.match(tax, /const saRefusal = useDateRefusal\(saDates\.first\);/);
  assert.match(cg, /const claimRefusal = useDateRefusal\(claimDates\.first\);/);
  for (const [code, header, what] of [
    [tax, "async function handleSave(", "the advance-tax Save"],
    [tax, "async function handleAddChallan(", "the section 140A challan"],
    [cg, "async function saveClaim(", "the reinvestment claim"],
  ] as const) {
    const d = whatTheHandlerDoesWithTheHook(code, header);
    assert.equal(d.latches, 1, `${what} has ${d.latches} latch calls: it must refuse a date once, through the latch`);
    assert.deepEqual(d.others, [], `${what} does something with its date problems besides the latch (a copy of a date's sentence stays after the date is right)`);
  }
  // Nowhere in the file does a call of the form's own error setter take anything from a date hook.
  assert.deepEqual(copiesIntoTheError(tax, ["setError", "setSaError"]), [], "the advance-tax page copies a date's sentence into its error");
  assert.deepEqual(copiesIntoTheError(cg, ["setExemptError"]), [], "the capital gains page copies a date's sentence into its error");
  // What the last attempt said is cleared before this one refuses, or it hides under the date's sentence and comes back when the date is right.
  assert.ok(clearsBeforeRefusing(tax, "async function handleSave(", /setError\(null\)/), "the advance-tax Save no longer clears the answer to the last attempt before it refuses a date");
  assert.ok(clearsBeforeRefusing(tax, "async function handleAddChallan(", /setSaError\(null\)/), "the section 140A challan no longer clears the answer to the last attempt before it refuses a date");
  assert.ok(clearsBeforeRefusing(cg, "async function saveClaim(", /setExemptError\(""\)/), "the reinvestment claim no longer clears the answer to the last attempt before it refuses a date");
  // The form's own answer is shown in preference to the latch: it is the newer.
  assert.match(tax, /\(error \|\| advRefusal\.shown\) && <Callout tone="problem">\{error \|\| advRefusal\.shown\}<\/Callout>/, "the advance-tax sentence is not rendered newest first");
  assert.match(tax, /\(saError \|\| saRefusal\.shown\) && <p className="text-xs text-state-problem">\{saError \|\| saRefusal\.shown\}<\/p>/, "the section 140A sentence is not rendered newest first");
  assert.match(cg, /\(exemptError \|\| claimRefusal\.shown\) && <Callout tone="problem">\{exemptError \|\| claimRefusal\.shown\}<\/Callout>/, "the claim's sentence is not rendered newest first");
  // The claim form is opened with nothing on it.
  assert.match(cg, /setExemptError\(""\);\s*claimRefusal\.clear\(\);/, "the claim form is opened again with the last sentence on it");
});

test("the writers and the deleters behind those two forms say what the server said", () => {
  const data = read(DATA);
  const helper = topLevelText(data, "async function writeAnswer<T>(");
  assert.ok(helper.indexOf("errorMessage(res)") > 0 && helper.indexOf("errorMessage(res)") < helper.indexOf("res.json()"),
    "a failed status is no longer read by errorMessage before the body is read as the house envelope");
  for (const fn of ["saveAdvanceTaxPayments", "createSelfAssessmentChallan", "addReinvestment", "deleteReinvestment", "deleteSelfAssessmentChallan"]) {
    const body = topLevelText(data, `export async function ${fn}(`);
    assert.match(body, /writeAnswer</, `${fn} no longer reads the server's answer through writeAnswer`);
    assert.doesNotMatch(body, /statusText|json\.error \?\?/, `${fn} reads a refusal as \`json.error ?? status text\` again: a 422 shows "Unprocessable Entity"`);
  }
});

test("the Record IRN and Record E-Way Bill dialogs open on India's day, the one their date boxes are bounded by", () => {
  const panel = read(PANEL);
  for (const fn of ["RecordIrnModal", "RecordEwayModal"]) {
    assert.deepEqual(opensOnIndiasDay(topLevelText(panel, `function ${fn}(`)), [], `${fn} does not open on India's day`);
  }
});

test("the detectors tell the defect from the fix, in the spellings that evade a looser reading", () => {
  const latch = "if (advDates.first) { advRefusal.refuse(); return; }";
  const handler = (middle: string) => `async function handleSave() { setError(null); ${middle} ${latch} setSaving(true); }`;
  const good = handler("");
  assert.deepEqual(whatTheHandlerDoesWithTheHook(good, "async function handleSave(").others, []);
  assert.equal(whatTheHandlerDoesWithTheHook(good, "async function handleSave(").hook, "advDates");
  for (const copy of [
    "setError(advDates.first);",
    "setError(advDates.first ?? null);",
    "setError(String(advDates.first));",
    'setError(Object.values(advDates.problems)[0] ?? "");',
    "const s = advDates.first; setError(s);",
    "if (advDates.first) { setError(advDates.first); return; }",
  ]) {
    assert.notDeepEqual(whatTheHandlerDoesWithTheHook(handler(copy), "async function handleSave(").others, [], `not caught in the handler: ${copy}`);
  }
  for (const copy of ["setError(advDates.first);", "setError(advDates.first ?? null);", "setError(String(advDates.first));", 'setError(Object.values(advDates.problems)[0] ?? "");']) {
    assert.notDeepEqual(copiesIntoTheError(copy, ["setError"]), [], `not caught anywhere in the file: ${copy}`);
  }
  assert.deepEqual(copiesIntoTheError('setError(null); setError("Enter estimated annual tax first"); setError(e instanceof Error ? e.message : "Save failed");', ["setError"]), []);
  // The clear must come first.
  assert.ok(clearsBeforeRefusing(good, "async function handleSave(", /setError\(null\)/));
  assert.ok(!clearsBeforeRefusing(`async function handleSave() { ${latch} setError(null); }`, "async function handleSave(", /setError\(null\)/));
  // A dialog that opens on India's day, and the clocks that evade a regex for one.
  const dialog = (today: string) => `function RecordIrnModal() { ${today} const [date, setDate] = useState(today); }`;
  assert.deepEqual(opensOnIndiasDay(dialog("const today = todayIstISO();")), []);
  for (const bad of [
    "const today = todayLocalISO();",
    'const today = new Date().toISOString().slice(0, 10);',
    'const today = new Date().toLocaleDateString("en-CA");',
    "const today = todayIstISO(); const other = Date.now();",
  ]) {
    assert.notDeepEqual(opensOnIndiasDay(dialog(bad)), [], `not caught: ${bad}`);
  }
});

// The rules above are executed by the browser, and this is what the drive must hold: the module is IMPORTED, so a scenario that is deleted, renamed, commented out or moved out of the
// three zones fails here and not silently. Each table is built from rows, so what must exist is each row's scenarios.
const SIX = ["advance-tax-paid-on", "self-assessment-deposit", "cgas-deposit", "irn-acknowledgement", "eway-bill-date", "bill-form-15ca"];
const EARLIER = ["advance-tax-save", "self-assessment-challan", "reinvestment-claim"];
const DIALOGS = ["irn-dialog", "eway-bill-dialog"];

test("the browser drive holds every claim this guard states", async () => {
  const drive = await import(pathToFileURL(path.join(WEB, DRIVE)).href);
  const kit = await import(pathToFileURL(path.join(WEB, "scripts/drive/kit.mjs")).href);
  const byId = new Map<string, { id: string; contexts?: unknown }>((drive.scenarios as Array<{ id: string; contexts?: unknown }>).map((s) => [s.id, s]));
  const inThreeZones = [
    ...SIX.flatMap((r) => [`${r}-a-date-after-today-is-refused`, `${r}-the-bound-is-the-indian-day`]),
    ...EARLIER.map((r) => `${r}-the-answer-to-an-earlier-attempt-does-not-come-back`),
    ...DIALOGS.map((r) => `${r}-opens-on-the-indian-day`),
    "eway-bill-valid-upto-may-run-ahead",
  ];
  assert.deepEqual(inThreeZones.filter((id) => !byId.has(id)), [], "a scenario of the sixteenth slice is gone from scripts/drive/scenarios/dates.mjs");
  assert.deepEqual(inThreeZones.filter((id) => JSON.stringify(byId.get(id)?.contexts) !== JSON.stringify(kit.TZ_MATRIX)), [], "a scenario of the sixteenth slice no longer runs in all three zones");
  assert.ok(byId.has("reinvestment-claim-a-refused-delete-is-said-over-an-earlier-date-sentence"), "the scenario that holds a refused Delete over an earlier date sentence is gone");
  assert.ok([...byId.keys()].some((id) => id.startsWith("bill-form-15ca")), "the editor-table row for the Form 15CA date is gone");
  // The hour the second table pins is one at which the browser's day is AHEAD of India's on Kiritimati, or the table cannot tell the two days apart.
  const pin = /const AHEAD_OF_INDIA = "([^"]+)"/.exec(fs.readFileSync(path.join(WEB, DRIVE), "utf8"))?.[1];
  assert.ok(pin, "the instant the sixteenth slice re-pins to is not stated");
  const day = (zone: string) => new Date(pin as string).toLocaleDateString("en-CA", { timeZone: zone });
  assert.ok(day("Pacific/Kiritimati") > day("Asia/Kolkata"), `at ${pin} the day on Kiritimati (${day("Pacific/Kiritimati")}) is not ahead of India's (${day("Asia/Kolkata")})`);
});
