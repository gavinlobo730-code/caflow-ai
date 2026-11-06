// THE DAYS A BANK OR A PORTAL PRINTED, AND THE DAY GOODS CAME BACK, CANNOT BE AFTER TODAY IN INDIA, AND A SENTENCE ABOUT THEM GOES WHEN THEY ARE PUT RIGHT (PRE-A-015, sixteenth, seventeenth and eighteenth slices).
//   node --experimental-strip-types --test scripts/the-dates-a-bank-or-a-portal-printed-are-bounded-by-todays-date-in-india.test.ts
//
// THE DEFECT
//   An advance-tax instalment's paid-on date, the section 140A challan's deposit date, a Capital Gains Accounts Scheme deposit, the IRP's acknowledgement day, the e-way bill's own date
//   and the day Form 15CA was filed are all facts that have happened by the time they are recorded: a bank has taken the money and a portal has printed the day. None of the six boxes
//   had any bound, and five of the six reached a server that stored a day that had not come (the advance-tax instalment's paid date was already refused there). The three income-tax
//   forms also copied the date's sentence into their own error, where it stayed after the date was put right, and the answer to an EARLIER attempt (the server's refusal) sat hidden
//   under the date's sentence and came back when the date was put right.
//   The seventeenth slice holds four more boxes to the same rules: the day a lot of goods came back on FORM GST ITC-04, the day a whole challan's goods came back (which stops the
//   s.143 clock), and the day on a TDS challan on the firm's TDS screen and on a client's TDS tab (the bank has taken the tax by the day it is dated).
//   The eighteenth slice adds two more facts (the day customs issued an export's shipping bill, and the day a foreign supplier's no-PE declaration is dated), says the supplier form's answers
//   beside its Save and a recurring invoice's blank first day and window out of order through the latch, and holds the days that are a PLAN (a recurring template's window, the day a return is furnished in the
//   §234A working) and the filters that write nothing (the stock register's as-at day and an item's ledger window) to their own rules.
//
// THE RULES (each read from the source as a RULE and not as one spelling of it, with the detectors tried below on the spellings that evade a looser reading; each EXECUTED by the browser
// drive, scripts/drive/scenarios/dates.mjs, whose scenarios the last test imports and requires; the server half is tests/test_the_dates_a_bank_or_a_portal_printed_are_not_after_today.py)
//   1. Each of the twelve boxes is bounded by today in India (`notAfter={todayIstISO()}`), refuses a later day instead of hinting at it (`{ afterMax: true }`), and reports to the hook
//      its Save reads, so the sentence it makes is the one the Save refuses with.
//   2. The e-way bill's "Valid upto" is a plan and may run ahead: it is not bounded by today.
//   3. The advance-tax Save, the section 140A challan, the reinvestment claim, Record this lot, Record goods back and the two TDS challan forms say a date's sentence through `useDateRefusal`
//      and nowhere else: their handler mentions the hook that
//      holds the date problems only inside the latch call, and no call of the form's error setter takes anything from a date hook. Each handler clears what the last attempt said
//      BEFORE it refuses, and the form's own answer is shown in preference to the latch (it is the newer: a refused Delete is said over a date that was refused a moment before).
//      For the four forms of the seventeenth slice the rule is stated the other way round, as what an ANSWER may be made of (nothing, the server's sentence, or a failed request's own
//      sentence), because a rule that lists the names to avoid is blind to the next name for a sentence derived from the boxes (`challanMissing`, `lotProblem`, a builder's `.error`).
//      The sentence of an answer is said in the form that raised it, beside its button, and for the goods-back rows in the row of the challan it is about.
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
const ITC04 = "components/gst/Itc04Panel.tsx";
const SALES_CYCLE = "components/sales/SalesCycleTab.tsx";
const TDS_FIRM = "app/tds/page.tsx";
const TDS_CLIENT = "app/clients/[id]/compliance/tds/page.tsx";
const INVOICE_EDITOR = "components/invoices/InvoiceEditor.tsx";
const PURCHASES = "app/clients/[id]/purchases/page.tsx";
const SALES_PAGE = "app/clients/[id]/sales/page.tsx";
const INVENTORY = "app/clients/[id]/inventory/page.tsx";
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
  return setters.flatMap((s) => callsOf(code, s).filter((arg) => /\b(?:\w*Dates|dates)\b|\.first\b|\.problems\b/.test(arg)).map((arg) => `${s}(${arg})`));
}

/** The value each call of an answer setter hands over: its argument, or the `text:` of an object argument (`{ line, text }`, `{ id, text }`). */
function answersGiven(code: string, setter: string): string[] {
  return callsOf(code, setter).map((raw) => {
    const arg = raw.trim();
    if (!arg.startsWith("{")) return arg;
    const at = arg.indexOf("text:");
    return at < 0 ? arg : arg.slice(at + "text:".length, arg.lastIndexOf("}")).trim();
  });
}

/** What a form's own answer may be made of: nothing, the server's sentence, or a failed request's own sentence (each with a literal for when it said none). Everything else, whatever
 *  it is called, is a copy of a sentence about the boxes (a date hook, a derived `…Missing` or `…Problem`, a builder's `.error`, a literal naming a blank box): that is said through the
 *  latch and goes when the box is right. Stated as what is allowed, so a new name for a derived sentence cannot slip past a list of names. */
const AN_ANSWER = [
  /^null$/,
  /^""$/,
  /^res\??\.error(?: (?:\?\?|\|\|) "[^"]*")?$/,
  /^e instanceof Error(?: && e\.message)? \? e\.message : "[^"]*"$/,
];

/** The calls of `setters` in `code` that hand over anything but an answer; `extra` is what the form may also say itself, by exact pattern. */
function notAnAnswer(code: string, setters: string[], extra: RegExp[] = []): string[] {
  return setters.flatMap((s) => answersGiven(code, s).filter((v) => ![...AN_ANSWER, ...extra].some((ok) => ok.test(v))).map((v) => `${s}(${v})`));
}

/** The allowances in `patterns` that no call of `setters` in `code` uses. An allowance for a sentence the form no longer says would keep permitting its return, so each must match a live call. */
function allowancesNobodyUses(code: string, setters: string[], patterns: RegExp[]): string[] {
  const said = setters.flatMap((s) => answersGiven(code, s));
  return patterns.filter((ok) => !said.some((v) => ok.test(v))).map((ok) => String(ok));
}

// What the supplier form and the recurring invoice template say THEMSELVES in their answer, each a sentence about a box that is NOT a date (it answers a press and is withdrawn by the next). The catch of the
// template's Save names its variable `err`, the supplier form's `e`. A sentence about a date box (unreadable, blank, after today, out of order) is not here: it is the latch's.
const SUPPLIER_SENTENCES = [
  /^"Name is required"$/, /^gstinIssue$/,
  /^"Opening balance must be an amount in rupees, "\s*\+\s*"e\.g\. 125000 or 125000\.50 — without commas\."$/,
  /^"TDS rate must be a percentage, e\.g\. 10 or 7\.5\."$/, /^"Treaty rate must be a percentage, e\.g\. 10 or 7\.5\."$/,
  /^"Withholding nil on business profits rests on the payee having no permanent establishment in India — tick the no-PE declaration, or choose a different nature of income\."$/,
  /^dup\.duplicate_reason\s*\?\?\s*"Not added — [^"]*"$/,
];
const TEMPLATE_SENTENCES = [
  /^err instanceof Error \? err\.message : "[^"]*"$/,
  /^"Select a customer"$/, /^"Title is required"$/, /^"Select a Product\/Service for every line item"$/, /^"Add at least one line item"$/,
  /^`"\$\{bad\.description\.trim\(\)\}": enter the rate and quantity as plain `\s*\+\s*"numbers, without commas — e\.g\. 125000 and 2\."$/,
];

/** The latch calls in a body: `if (<condition>) { <refusal>.refuse(); return; }`, the condition read with its brackets balanced (it may hold `problems[`back-${id}`]` or `!(a ?? "")`). */
function latchesIn(body: string): Array<{ condition: string; text: string }> {
  const found: Array<{ condition: string; text: string }> = [];
  for (const m of body.matchAll(/if \(/g)) {
    const at = m.index ?? 0;
    const condition = balancedFrom(body, at + 3);
    const tail = /^ \{ \w+\.refuse\(\); return; \}/.exec(body.slice(at + 3 + condition.length));
    if (tail) found.push({ condition: condition.slice(1, -1), text: body.slice(at, at + 3 + condition.length + tail[0].length) });
  }
  return found;
}

const A_DATE_HOOK = /\b(?:\w*Dates|dates)\b/;

/** What a handler does with its date hook besides the latch: `{ hook, latches, others }`. The latch is `if (<condition>) { <refusal>.refuse(); return; }` and there must be exactly one;
 *  the hook is the date hook its condition asks; everything else in the body that names a date hook or a `.first` is an `other`. */
function whatTheHandlerDoesWithTheHook(code: string, header: string): { hook: string | null; latches: number; others: string[] } {
  const body = bodyOf(code, header);
  const latches = latchesIn(body);
  let rest = body;
  for (const l of latches) rest = rest.replace(l.text, " ");
  const others = [...rest.matchAll(/\b(?:\w*Dates|dates)\b[^\n]{0,60}|[\w.]+\.first\b[^\n]{0,60}/g)].map((m) => m[0]);
  return { hook: latches[0] ? (A_DATE_HOOK.exec(latches[0].condition)?.[0] ?? null) : null, latches: latches.length, others };
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

test("the twelve boxes for a day that has happened by the time it is recorded are bounded by today in India and refuse a later day", () => {
  const boxes: Array<[string, string, string]> = [
    [TAX, "Instalment ${n} paid on", "an advance-tax instalment's paid-on date"],
    [TAX, 'id="sa-deposit-date"', "the section 140A challan's deposit date"],
    [CG, 'aria-label="CGAS deposit date"', "the Capital Gains Accounts Scheme deposit date"],
    [PANEL, 'aria-label="Acknowledgement date"', "the IRP's acknowledgement date"],
    [PANEL, 'aria-label="EWB date"', "the e-way bill's own date"],
    [BILL, 'id="bill-15ca-date"', "the day Form 15CA was filed"],
    [ITC04, 'id="itc04-came-back-on"', "the day a lot of goods came back (ITC-04)"],
    [SALES_CYCLE, "Date the goods came back, challan", "the day a whole challan's goods came back"],
    [TDS_FIRM, 'id="tds-challan-date"', "the day on a TDS challan (the firm's TDS screen)"],
    [TDS_CLIENT, 'id="tds-client-challan-date"', "the day on a TDS challan (a client's TDS tab)"],
    [INVOICE_EDITOR, 'id="inv-sb-date"', "the day customs issued the shipping bill"],
    [PURCHASES, 'id="no-pe-on"', "the day a foreign supplier's no-PE declaration is dated"],
  ];
  for (const [file, needle, what] of boxes) {
    const box = dateInputWith(read(file), needle);
    assert.match(box, /notAfter=\{todayIstISO\(\)\}/, `${what} is no longer bounded by today in India (${file})`);
    assert.match(box, /\{ afterMax: true \}/, `${what} only hints at a later day: it must refuse it (${file})`);
  }
});

test("each box reports to the hook its Save reads", () => {
  const tax = read(TAX);
  const cg = read(CG);
  const hookOf = (box: string) => /\b(\w+)\.watch\(/.exec(box)?.[1];
  // The three forms: the hook the box reports to is the hook the handler's latch asks.
  assert.equal(hookOf(dateInputWith(tax, "Instalment ${n} paid on")), whatTheHandlerDoesWithTheHook(tax, "async function handleSave(").hook, "an instalment's paid-on box reports to a hook the Save never asks");
  assert.equal(hookOf(dateInputWith(tax, 'id="sa-deposit-date"')), whatTheHandlerDoesWithTheHook(tax, "async function handleAddChallan(").hook, "the §140A deposit box reports to a hook Record challan never asks");
  assert.equal(hookOf(dateInputWith(cg, 'aria-label="CGAS deposit date"')), whatTheHandlerDoesWithTheHook(cg, "async function saveClaim(").hook, "the CGAS box reports to a hook Record claim never asks");
  // The four of the seventeenth slice.
  const itc = read(ITC04);
  assert.equal(hookOf(dateInputWith(itc, 'id="itc04-came-back-on"')), whatTheHandlerDoesWithTheHook(itc, "async function record(").hook, "the came-back box reports to a hook Record this lot never asks");
  const sc = read(SALES_CYCLE);
  assert.equal(hookOf(dateInputWith(sc, "Date the goods came back, challan")), whatTheHandlerDoesWithTheHook(sc, "async function markBack(").hook, "a goods-back box reports to a hook Record goods back never asks");
  // The handlers are looked up INSIDE their own component: the client TDS page holds four `saveNew`, and the first match is not necessarily this form's.
  const tdsFirm = topLevelText(read(TDS_FIRM), "function AddChallanModal(");
  assert.equal(hookOf(dateInputWith(tdsFirm, 'id="tds-challan-date"')), whatTheHandlerDoesWithTheHook(tdsFirm, "async function handleAdd(").hook, "the firm TDS challan box reports to a hook Add never asks");
  const tdsClient = topLevelText(read(TDS_CLIENT), "function ChallansTab(");
  assert.equal(hookOf(dateInputWith(tdsClient, 'id="tds-client-challan-date"')), whatTheHandlerDoesWithTheHook(tdsClient, "async function saveNew(").hook, "the client TDS challan box reports to a hook Save never asks");
  // The two portal dialogs: `problem` is made from the hook the box reports to.
  const panel = read(PANEL);
  for (const [fn, needle] of [["RecordIrnModal", 'aria-label="Acknowledgement date"'], ["RecordEwayModal", 'aria-label="EWB date"']] as const) {
    const body = topLevelText(panel, `function ${fn}(`);
    const hook = hookOf(dateInputWith(body, needle));
    assert.ok(hook && new RegExp(`const problem = ${hook}\\.first\\b`).test(body), `${fn}: the box reports to a hook the dialog's \`problem\` is not made from`);
  }
  // The eighteenth slice: the supplier form's declaration box reports to the hook its Save's latch asks (looked up inside the form's own component: the page holds other forms with a handleSave),
  // and the invoice editor's shipping bill box to the hook its Save asks.
  const vendors = topLevelText(read(PURCHASES), "function Vendors(");
  assert.equal(hookOf(dateInputWith(vendors, 'id="no-pe-on"')), whatTheHandlerDoesWithTheHook(vendors, "async function handleSave(").hook, "the declaration box reports to a hook the supplier form's Save never asks");
  const editor = read(INVOICE_EDITOR);
  const sbHook = hookOf(dateInputWith(editor, 'id="inv-sb-date"'));
  assert.ok(sbHook && new RegExp(`if \\(${sbHook}\\.first\\)`).test(editor), "the shipping bill box reports to a hook the invoice editor's Save never asks");
  // The block is drawn for a supply that leaves India and ONLY then can its number, date and port code be seen, judged and put right: a value typed while the block was drawn and left behind
  // when the supply type was changed back must not be sent from a box nobody can see (the server refuses a date after today and a port code that is not six characters, and the person would be
  // told about a field that is not on the screen; the first version gated the date alone and a five-character port code still got through). One condition draws the block and decides the three
  // fields, and all three payloads (an issued invoice's soft fields, a draft's, a new invoice) spread the one gated object and name none of the three themselves.
  assert.match(editor, /const showsShippingBill = \(supplyType === "zero_rated" \|\| supplyStateCode === "96"\) && invoiceType === "Regular";/, "the shipping bill block's condition is no longer the one named showsShippingBill");
  assert.match(editor, /const shippingBillSent = showsShippingBill \? \{\s*shipping_bill_no: shippingBillNo\.trim\(\) \|\| undefined,\s*shipping_bill_date: shippingBillDate \|\| undefined,\s*port_code: portCode\.trim\(\)\.toUpperCase\(\) \|\| undefined,\s*\} : \{\};/,
    "the shipping bill number, date and port code are no longer gated together on the block being drawn");
  assert.match(editor, /\{showsShippingBill && \(/, "the shipping bill block is no longer drawn by the condition that gates its fields");
  assert.equal((editor.match(/\.\.\.shippingBillSent,/g) ?? []).length, 3, "a payload no longer spreads the gated shipping bill fields");
  for (const key of ["shipping_bill_no", "shipping_bill_date", "port_code"]) {
    assert.equal((editor.match(new RegExp(`\\b${key}:`, "g")) ?? []).length, 1, `${key} is named in a payload outside the gated object, so it is sent from a box that may not be drawn`);
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

test("the forms of the sixteenth and seventeenth slices say a date's sentence through the latch and nowhere else", () => {
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

test("Record this lot, Record goods back and the two TDS challan forms say a date's sentence through the latch and nowhere else, and show the newest answer", () => {
  const itc = read(ITC04);
  const sc = read(SALES_CYCLE);
  // The two TDS forms are looked up inside their own component (the firm page and the client page hold other forms with a `handleAdd`/`saveNew` and a setter of the same name).
  const tdsFirm = topLevelText(read(TDS_FIRM), "function AddChallanModal(");
  const tdsClient = topLevelText(read(TDS_CLIENT), "function ChallansTab(");
  for (const [code, header, what] of [
    [itc, "async function record(", "Record this lot"],
    [sc, "async function markBack(", "Record goods back"],
    [tdsFirm, "async function handleAdd(", "the firm's Add challan"],
    [tdsClient, "async function saveNew(", "a client's New Challan"],
  ] as const) {
    const d = whatTheHandlerDoesWithTheHook(code, header);
    assert.equal(d.latches, 1, `${what} has ${d.latches} latch calls: it must refuse a date once, through the latch`);
    assert.deepEqual(d.others, [], `${what} does something with its date problems besides the latch (a copy of a date's sentence stays after the date is right)`);
  }
  // THE ANSWER IS WHAT THE SERVER SAID. Every call of the form's answer setter hands over nothing, the server's sentence or a failed request's own: a sentence about the boxes (the date,
  // a blank box, a quantity that is not one) is derived and latched, whatever the derived value is called. The firm dialog also says three sentences about its amounts itself, and each
  // of its four amount boxes withdraws the answer the moment it changes, so they cannot outlive the box (asserted just below).
  const AMOUNT_SENTENCES = [/^"Amount must be in rupees[^"]*"$/, /^"Surcharge, interest and penalty (?:must be|together come)[^"]*"$/];
  assert.deepEqual(notAnAnswer(itc, ["setLotError"]), [], "the ITC-04 panel says something besides the server's answer in its lot answer");
  assert.deepEqual(notAnAnswer(sc, ["setBackAnswer"]), [], "the goods-back block says something besides the server's answer in its answer");
  assert.deepEqual(notAnAnswer(tdsFirm, ["setError"], AMOUNT_SENTENCES), [], "the firm TDS challan dialog says something besides the server's answer (or an amount's sentence) in its error");
  assert.deepEqual(notAnAnswer(tdsClient, ["setSaveError"]), [], "the client TDS Challans tab says something besides the server's answer in its error");
  assert.equal((tdsFirm.match(/(?:setAmtRupees|setSurchargeRupees|setInterestRupees|setPenaltyRupees)\(e\.target\.value\); setError\(null\);/g) ?? []).length, 4, "an amount box of the firm dialog no longer withdraws the error when it changes");
  // The ITC-04 panel's page-level message line says only that a lot was recorded.
  assert.deepEqual(callsOf(itc, "setMsg").filter((a) => a.trim() !== "null" && !/type: "ok"/.test(a)), [], "the ITC-04 panel's message line says something besides a success");
  // The older name-based reading still holds on the files: nothing takes a date hook into a setter.
  assert.deepEqual(copiesIntoTheError(itc, ["setMsg", "setLotError"]), [], "the ITC-04 panel copies a date's sentence into its answer");
  assert.deepEqual(copiesIntoTheError(sc, ["setBackAnswer"]), [], "the goods-back block copies a date's sentence into its answer");
  assert.deepEqual(copiesIntoTheError(tdsFirm, ["setError"]), [], "the firm TDS challan dialog copies a date's sentence into its error");
  assert.deepEqual(copiesIntoTheError(tdsClient, ["setSaveError"]), [], "the client TDS Challans tab copies a date's sentence into its error");
  // What the last press said is cleared before this one refuses.
  assert.ok(clearsBeforeRefusing(itc, "async function record(", /setLotError\(null\)/), "Record this lot no longer clears the answer to the last press before it refuses a date");
  assert.ok(clearsBeforeRefusing(sc, "async function markBack(", /setBackAnswer\(null\)/), "Record goods back no longer clears the answer to the last press before it refuses a date");
  assert.ok(clearsBeforeRefusing(tdsFirm, "async function handleAdd(", /setError\(null\)/), "the firm's Add challan no longer clears the answer to the last press before it refuses a date");
  assert.ok(clearsBeforeRefusing(tdsClient, "async function saveNew(", /setSaveError\(null\)/), "a client's New Challan no longer clears the answer to the last press before it refuses a date");
  // The newest answer is shown first.
  assert.match(itc, /\(lotAnswer \|\| lotRefusal\.shown\) && \(\s*<p role="alert"[^>]*>\{lotAnswer \|\| lotRefusal\.shown\}<\/p>/, "the lot's sentence is not rendered newest first");
  assert.match(tdsFirm, /\(error \|\| refusal\.shown\) && <Callout tone="problem">\{error \|\| refusal\.shown\}<\/Callout>/, "the firm TDS challan sentence is not rendered newest first");
  assert.match(tdsClient, /\(saveError \|\| refusal\.shown\) && <p role="alert"[^>]*>\{saveError \|\| refusal\.shown\}<\/p>/, "the client TDS challan sentence is not rendered newest first");
  // THE GOODS-BACK SENTENCE IS IN THE ROW OF THE CHALLAN IT IS ABOUT, beside its button: the server's answer for that challan (named, since the server's sentence names none) is
  // shown over the sentence about the box, a late answer to another challan is not shown in this row, and both are withdrawn when the tab is left.
  assert.match(sc, /const backSaid = \(c: DeliveryChallan\): string \| null =>\s*\(backAnswer && backAnswer\.id === c\.id \? `\$\{c\.document_no\}: \$\{backAnswer\.text\}` : null\) \|\| \(backTried === c\.id \? backRefusal\.shown : null\);/, "the goods-back sentence is not made per challan, newest first");
  assert.match(sc, /\{backSaid\(c\) && <p role="alert"[^>]*>\{backSaid\(c\)\}<\/p>\}/, "the goods-back sentence is not rendered in the row it is about");
  assert.match(sc, /setTab\(id\);[^}]*setBackTried\(null\); setBackAnswer\(null\); backRefusal\.clear\(\);/, "leaving the tab no longer withdraws the goods-back sentences");
  // The sentence about a goods-back box is derived from the box and latched (the date's sentence, or the missing date named with its challan).
  assert.match(sc, /const backProblem = backTried === null \? null\s*: \(backDates\.problems\[`back-\$\{backTried\}`\] \?\? \(\(backOn\[backTried\] \?\? ""\) \? null : `Enter the date the goods on \$\{backNo \?\? "the challan"\} came back\.`\)\);\s*const backRefusal = useDateRefusal\(backProblem\);/, "the goods-back box's sentences are not derived from the box and latched");
  // A blank challan date, number and BSR code (and, on a client's tab, the section and the year) are sentences about the boxes too: derived and latched, and not an answer.
  assert.match(tdsFirm, /const challanMissing = !challanDate \? "Challan date: enter the date on the challan\."\s*: !serialNo\.trim\(\) \? "Challan number: [^"]*"\s*: !bsrCode\.trim\(\) \? "BSR code: [^"]*" : null;\s*const refusal = useDateRefusal\(dates\.first \?\? challanMissing\);/, "the firm TDS challan dialog's blank-box sentences are not derived and latched");
  assert.match(tdsClient, /const challanMissing = !form\.challan_date \? "Challan date: enter the date on the challan\."\s*: !form\.challan_no\.trim\(\) \? "Challan number: [^"]*"\s*: !form\.bsr_code\.trim\(\) \? "BSR code: [^"]*"\s*: !form\.section\.trim\(\) \? "TDS section: [^"]*"\s*: !form\.financial_year\.trim\(\) \? "Financial year: [^"]*" : null;\s*const refusal = useDateRefusal\(dates\.first \?\? challanMissing\);/, "the client TDS tab's blank-box sentences are not derived and latched");
  // The lot form's other sentences (the builder's) are derived from the boxes too.
  assert.match(itc, /const lotProblem = lotDates\.first \?\? \(lotBuilt && !lotBuilt\.ok \? lotBuilt\.error : null\);\s*const lotRefusal = useDateRefusal\(lotProblem\);/, "the lot form's sentences are not derived from its boxes and latched");
  // The lot's answer is for the lot that raised it, and an answer to another line is not shown in the open form.
  assert.match(itc, /const \[lotError, setLotError\] = useState<\{ line: string; text: string \} \| null>\(null\);/, "the lot's answer is no longer tied to its line");
  assert.match(itc, /const lotAnswer = lotError && lotError\.line === lotFor \? lotError\.text : null;/, "an answer to another line is shown in the open lot form");
  // …and "Record a lot" is held while a request is out (`saving` is the panel's), or a form opened for another line meanwhile would be closed by this one's success.
  const toggleAt = itc.indexOf("Record a lot");
  assert.match(itc.slice(itc.lastIndexOf("<button", toggleAt), toggleAt), /disabled=\{saving\}/, "\"Record a lot\" is live while a lot is being recorded");
  // A lot form opened (or closed) holds nothing of the last one: its boxes, its answer and its latched sentence.
  assert.match(itc, /setLotFor\(lotFor === l\.challan_line_id \? null : l\.challan_line_id\);\s*setLot\(\{ \.\.\.BLANK_LOT \}\);\s*setLotError\(null\);\s*lotRefusal\.clear\(\);/, "a lot form is opened again with the last answer or sentence on it");
  // The firm dialog cannot be left while Add is out, by its X or by Cancel (the client tab holds its Cancel in the same way).
  assert.equal((tdsFirm.match(/onClick=\{onClose\} disabled=\{saving\}/g) ?? []).length, 2, "the firm TDS challan dialog can be closed while Add is out");
  assert.match(tdsClient, /<button onClick=\{closeForm\} disabled=\{saving\}/, "the client TDS challan form can be cancelled while Save is out");
  // The server's refusal reaches the screen as the sentence it is (the catch used to throw it away; FastAPI answers a refusal with an error status, which arrives as a thrown sentence).
  assert.match(bodyOf(itc, "async function record("), /catch \(e\) \{[^}]*setLotError\(\{ line: line\.challan_line_id, text: e instanceof Error \? e\.message/, "Record this lot throws away the sentence of a refusal that arrives as an error status");
  assert.match(bodyOf(sc, "async function markBack("), /catch \(e\) \{\s*setBackAnswer\(\{ id: challan\.id, text: e instanceof Error \? e\.message/, "Record goods back throws away the sentence of a refusal that arrives as an error status");
  assert.match(bodyOf(tdsFirm, "async function handleAdd("), /catch \(e\) \{\s*setError\(e instanceof Error \? e\.message/, "the firm's Add challan throws away the sentence of a refusal that arrives as an error status");
});

test("the supplier form and the recurring invoice template say a date's sentence through the latch and nowhere else, and the supplier form says its answers beside Save", () => {
  // The supplier form is looked up inside its own component (the purchases page holds other forms with a `handleSave`), and the template editor inside its own (the sales page holds others).
  const vendors = topLevelText(read(PURCHASES), "function Vendors(");
  const recurring = topLevelText(read(SALES_PAGE), "function RecurringEditor(");
  // The box's own sentence first, then the sentence about the date on file (POST-A-388, `an-edit-screen-does-not-say-saved-over-a-date-it-was-asked-to-remove.test.ts` holds that half): both are
  // derived from what the boxes hold, so both are the latch's.
  assert.match(vendors, /const noPeRefusal = useDateRefusal\(noPeDates\.first \?\? noPeCleared\);/, "the supplier form's declaration sentence is not latched");
  const v = whatTheHandlerDoesWithTheHook(vendors, "async function handleSave(");
  assert.equal(v.latches, 1, `the supplier form's Save has ${v.latches} latch calls: it must refuse a date once, through the latch`);
  assert.deepEqual(v.others, [], "the supplier form's Save does something with its date problems besides the latch (a copy of a date's sentence stays after the date is right)");
  assert.deepEqual(copiesIntoTheError(vendors, ["setFormError", "setMsg"]), [], "the supplier form copies a date's sentence into its answer");
  // The same rule stated as what an answer MAY be made of (a rule that lists names to avoid is blind to the next name for a derived sentence, `setFormError(noPeRefusal.shown)` or a literal naming the
  // declaration's date): nothing, the server's sentence, a failed request's own, or one of the sentences the form says ITSELF about a box that is not a date, each of which answers a press and is
  // withdrawn by the next. A sentence about a DATE box, under whatever name, is the latch's.
  assert.deepEqual(notAnAnswer(vendors, ["setFormError"], SUPPLIER_SENTENCES), [],
    "the supplier form's answer holds something that is not nothing, the server's sentence, a failed request's own or one of its allowed sentences about a box that is not a date: a sentence about a DATE box belongs to the latch, and a sentence that was only reworded (or a catch variable renamed) is updated in SUPPLIER_SENTENCES");
  assert.deepEqual(allowancesNobodyUses(vendors, ["setFormError"], SUPPLIER_SENTENCES), [], "SUPPLIER_SENTENCES allows a sentence the supplier form no longer says: delete it, or it permits the sentence's return");
  assert.ok(clearsBeforeRefusing(vendors, "async function handleSave(", /setFormError\(null\)/), "the supplier form's Save no longer clears the answer to the last press before it refuses a date");
  // The answer to a press is said BESIDE Save (the form is long and the page's message line is above all of it), newest first, and the page's message line is not used by the Save for an error.
  assert.match(vendors, /\(formError \|\| noPeRefusal\.shown\) && <p role="alert"[^>]*>\{formError \|\| noPeRefusal\.shown\}<\/p>\}\s*<div className="flex gap-3 justify-end">/, "the supplier form's answer is not said beside Save, newest first");
  assert.doesNotMatch(bodyOf(vendors, "async function handleSave("), /setMsg\(\{ type: "err"/, "the supplier form's Save says an error in the page's message line again, above the whole form");
  // A form opened afresh or closed holds nothing of the last press.
  assert.match(vendors, /useLayoutEffect\(\(\) => \{ setFormError\(null\); clearNoPeRefusal\(\); \}, \[showForm, editingVendor\?\.id, editOpened, clearNoPeRefusal\]\);/, "the supplier form is opened again with the last answer or sentence on it");
  // Opening the vendor that is ALREADY on the form is a form opened afresh too (neither the form's visibility nor the vendor's id changes): the edit counter is bumped by openEdit, named by the
  // effect above, and part of the declaration box's key so its text is reset with the rest.
  assert.match(bodyOf(vendors, "function openEdit("), /setEditOpened\(\(n\) => n \+ 1\);/, "opening a vendor to edit no longer counts as a form opened afresh");
  assert.match(vendors, /key=\{`\$\{editingVendor\?\.id \?\? "new"\}-\$\{editOpened\}`\}\s*id="no-pe-on"/, "the declaration box keeps its text when the vendor on the form is opened again");
  // The template editor: a blank first day is a sentence about the box, derived from it and latched; the editor's answers are cleared first and the newest is shown first.
  assert.match(recurring, /const startMissing = startDate \? null : "Start date: enter the date of the first invoice\.";/, "the template editor's blank-first-day sentence is not derived");
  // The window's ORDER is a fact about the two boxes, so it is derived and latched beside the others (copied into the form's own error it stayed on the form after the cause was fixed), and the
  // Save asks it in the same breath as the dates' own.
  assert.match(recurring, /const orderProblem = startDate && endDate && endDate < startDate \? "End date cannot be before start date" : null;\s*const refusal = useDateRefusal\(recurringDates\.first \?\? startMissing \?\? orderProblem\);/, "the template editor's order sentence is not derived and latched");
  assert.match(bodyOf(recurring, "async function submit("), /if \(recurringDates\.first \?\? startMissing \?\? orderProblem\) \{ refusal\.refuse\(\); return; \}/, "the template editor's Save no longer asks the order sentence with the others");
  assert.doesNotMatch(recurring, /setError\("End date cannot be before start date"\)/, "the template editor copies the order sentence into its own error again");
  const r = whatTheHandlerDoesWithTheHook(recurring, "async function submit(");
  assert.equal(r.latches, 1, `the template editor's Save has ${r.latches} latch calls: it must refuse a date once, through the latch`);
  assert.deepEqual(r.others, [], "the template editor's Save does something with its date problems besides the latch");
  assert.deepEqual(copiesIntoTheError(recurring, ["setError"]), [], "the template editor copies a date's sentence into its error");
  // …and as what its answer may be made of: nothing, the server's sentence, a failed request's own (here the catch's variable is `err`), or one of the sentences it says ITSELF about a box that is
  // not a date. The blank first day, the window out of order and every other sentence about a date are the latch's, so `setError("Start date: …")` is caught whatever it is called.
  assert.deepEqual(notAnAnswer(recurring, ["setError"], TEMPLATE_SENTENCES), [],
    "the template editor's error holds something that is not nothing, the server's sentence, a failed request's own or one of its allowed sentences about a box that is not a date: a sentence about a DATE box belongs to the latch, and a sentence that was only reworded (or a catch variable renamed) is updated in TEMPLATE_SENTENCES");
  assert.deepEqual(allowancesNobodyUses(recurring, ["setError"], TEMPLATE_SENTENCES), [], "TEMPLATE_SENTENCES allows a sentence the template editor no longer says: delete it, or it permits the sentence's return");
  assert.ok(clearsBeforeRefusing(recurring, "async function submit(", /setError\(null\)/), "the template editor's Save no longer clears the answer to the last press before it refuses a date");
  assert.match(recurring, /\(error \|\| refusal\.shown\) && <Callout tone="problem">\{error \|\| refusal\.shown\}<\/Callout>/, "the template editor's sentence is not rendered newest first");
  // Both boxes report to the hook the latch asks.
  const hookOf = (box: string) => /\b(\w+)\.watch\(/.exec(box)?.[1];
  assert.equal(hookOf(dateInputWith(recurring, 'id="rec-inv-start"')), r.hook, "the template's start box reports to a hook its Save never asks");
  assert.equal(hookOf(dateInputWith(recurring, 'id="rec-inv-end"')), r.hook, "the template's end box reports to a hook its Save never asks");
});

test("the days that are a PLAN are not bounded by today, and the stock filters read what their boxes hold", () => {
  const recurring = topLevelText(read(SALES_PAGE), "function RecurringEditor(");
  const start = dateInputWith(recurring, 'id="rec-inv-start"');
  const end = dateInputWith(recurring, 'id="rec-inv-end"');
  assert.doesNotMatch(start, /notAfter|afterMax|max=/, "the first invoice's day is bounded by today again: a template may begin ahead of it");
  assert.doesNotMatch(end, /notAfter|afterMax|max=/, "the day a template stops is bounded by today again: it may run ahead of it");
  assert.match(end, /notBefore=\{startDate \|\| null\}/, "the day a template stops no longer begins at its first day");
  assert.match(recurring, /useState\(existing\?\.start_date \?\? todayIstISO\(\)\)/, "a new template no longer begins on India's day");
  // The day a return is furnished in the §234A working is a what-if as well as a fact: the working may be asked what filing on a later day would cost, so it is not bounded either.
  assert.doesNotMatch(dateInputWith(read(TAX), 'id="at-furnished-on"'), /notAfter|afterMax|max=/, "the day the return was furnished is bounded by today again: the §234A working may be asked about a later day");
  // The stock register's as-at heading prints a date as a date (not the ISO text), and a ledger window whose To day is before its From day is not read.
  const inventory = read(INVENTORY);
  assert.match(inventory, /Closing value as at \$\{formatDate\(asAt\)\}/, "the stock register's heading prints the as-at day as ISO text again");
  const ledger = topLevelText(inventory, "function StockLedgerDrillDown(");
  assert.match(ledger, /const windowReversed = !!startDate && !!endDate && endDate < startDate;/, "the ledger window's order is no longer judged");
  assert.match(bodyOf(ledger, "const load = useCallback(async () =>").replace(/^\{\s*/, "{ "), /if \(windowReversed\) \{[^}]*return;\s*\}/, "a window in the wrong order is read again");
  assert.match(ledger, /windowReversed \? \(\s*<p role="alert"[^>]*>\s*The To day is before the From day/, "a window in the wrong order is not said in a sentence");
  // An answer to an EARLIER window is not applied over the window on the boxes: each read has its own number, and the answer, the failure and the end of the wait ask whether it is still the latest.
  const loadBody = bodyOf(ledger, "const load = useCallback(async () =>");
  assert.match(ledger, /const loadSeqRef = useRef\(0\);/, "the ledger window has no request sequence");
  assert.match(loadBody, /const seq = \+\+loadSeqRef\.current;\s*const isCurrent = \(\) => seq === loadSeqRef\.current;/, "a ledger read has no number of its own");
  assert.equal((loadBody.match(/if \(!isCurrent\(\)\) return;/g) ?? []).length, 2, "a slow answer (or failure) of an earlier window is applied over the latest again");
  assert.match(loadBody, /finally \{\s*if \(isCurrent\(\)\) setLoading\(false\);/, "an earlier window's answer ends the wait of the latest");
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
  // The positive rule: what an answer may be, tried on the spellings that slipped past the name list (found by the independent read of the seventeenth slice).
  for (const fine of [
    "setError(null);", 'setError("");', 'setLotError({ line: l, text: res.error || "That return was refused." });', 'setBackAnswer({ id: c.id, text: e instanceof Error ? e.message : "x" });',
    'setSaveError(res?.error ?? "The challan was not recorded.");', 'setSaveError(e instanceof Error && e.message ? e.message : "The challan was not recorded.");',
  ]) assert.deepEqual(notAnAnswer(fine, ["setError", "setLotError", "setBackAnswer", "setSaveError"]), [], `refused as a copy but it is an answer: ${fine}`);
  for (const copy of [
    'setError("Challan date: enter the date on the challan."); return;', "setError(challanMissing);", "setSaveError(challanMissing);", "setLotError(built.error);",
    "setLotError({ line: l, text: built.error });", "setLotError({ line: l, text: lotProblem });", "setBackAnswer({ id: c.id, text: backProblem });", "setError(refusal.shown);",
    'setSaveError("Challan number: enter the serial number printed on the challan.");', "setError(dates.first ?? null);", 'setBackAnswer({ id: c.id, text: `${c.document_no}: ${backProblem}` });',
  ]) assert.notDeepEqual(notAnAnswer(copy, ["setError", "setLotError", "setBackAnswer", "setSaveError"]), [], `not caught by the positive rule: ${copy}`);
  // The eighteenth slice's two forms, whose own sentences about boxes that are not dates are allowed by exact pattern and nothing else is.
  for (const fine of ['setFormError("Name is required");', "setFormError(gstinIssue);", 'setFormError(e instanceof Error ? e.message : "Save failed");', "setFormError(null);"]) {
    assert.deepEqual(notAnAnswer(fine, ["setFormError"], SUPPLIER_SENTENCES), [], `refused as a copy but it is the supplier form's own answer: ${fine}`);
  }
  for (const copy of ["setFormError(noPeRefusal.shown);", 'setFormError("Declaration dated: enter the day the declaration was signed.");', "setFormError(noPeDates.first);", "setFormError(declarationProblem);"]) {
    assert.notDeepEqual(notAnAnswer(copy, ["setFormError"], SUPPLIER_SENTENCES), [], `not caught by the positive rule on the supplier form: ${copy}`);
  }
  for (const fine of ['setError("Select a customer");', 'setError(err instanceof Error ? err.message : "Save failed");', "setError(null);"]) {
    assert.deepEqual(notAnAnswer(fine, ["setError"], TEMPLATE_SENTENCES), [], `refused as a copy but it is the template editor's own answer: ${fine}`);
  }
  assert.deepEqual(allowancesNobodyUses('setError("Select a customer"); setError(null);', ["setError"], [/^"Select a customer"$/, /^"A sentence that was deleted"$/]), ['/^"A sentence that was deleted"$/'], "an allowance no call uses is not found");
  for (const copy of ['setError("Start date: enter the date of the first invoice.");', 'setError("End date cannot be before start date");', "setError(orderProblem);", "setError(startMissing);", "setError(refusal.shown);"]) {
    assert.notDeepEqual(notAnAnswer(copy, ["setError"], TEMPLATE_SENTENCES), [], `not caught by the positive rule on the template editor: ${copy}`);
  }
  // …and the latch is found in the shapes the four forms use: a nullish gate, a bracketed condition, a negated parenthesis.
  for (const gate of [
    "if (dates.first ?? challanMissing) { refusal.refuse(); return; }",
    "if (backDates.problems[`back-${challan.id}`] || !(backOn[challan.id] ?? \"\")) { backRefusal.refuse(); return; }",
    "if (lotDates.first || !built.ok) { lotRefusal.refuse(); return; }",
  ]) {
    const one = whatTheHandlerDoesWithTheHook(`async function go() { setX(null); ${gate} setSaving(true); }`, "async function go(");
    assert.equal(one.latches, 1, `the latch is not found: ${gate}`);
    assert.deepEqual(one.others, [], `the latch is read as a copy: ${gate}`);
    assert.ok(one.hook, `the latch's hook is not found: ${gate}`);
  }
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
const SIX = ["advance-tax-paid-on", "self-assessment-deposit", "cgas-deposit", "irn-acknowledgement", "eway-bill-date", "bill-form-15ca",
  "itc04-came-back", "goods-back", "firm-tds-challan", "client-tds-challan", "shipping-bill", "vendor-no-pe-declaration"]; // the six of the sixteenth slice, the four of the seventeenth and the two of the eighteenth
const EARLIER = ["advance-tax-save", "self-assessment-challan", "reinvestment-claim", "itc04-record-lot", "goods-back-record", "firm-tds-challan-add", "client-tds-challan-save", "vendor-save", "recurring-invoice-save"];
// The eighteenth slice's rows of the editor table and its scenarios of its own: the five write forms, the recurring invoice's edit and window, and the three boxes that write nothing.
const EIGHTEENTH = ["recurring-invoice-template", "sales-invoice-shipping-bill", "vendor-no-pe-declaration", "catalogue-opening-stock-date", "catalogue-import-opening-stock-date",
  "recurring-invoice-edit-an-untouched-stop-date-is-sent-back", "recurring-invoice-edit-a-cleared-stop-date-clears-it", "recurring-invoice-a-reversed-window-is-refused-in-a-sentence",
  "advance-tax-return-furnished-on", "stock-register-as-at", "stock-ledger-window",
  "shipping-bill-a-future-date-left-behind-in-a-block-that-is-no-longer-drawn-is-not-sent"];
const DIALOGS = ["irn-dialog", "eway-bill-dialog"];
// The four forms of the seventeenth slice whose date is REQUIRED, and the recurring invoice template's first day of the eighteenth: pressed over a blank date they say so, and the sentence goes
// once a date is typed.
const REQUIRED = ["itc04-record-lot", "goods-back-record", "firm-tds-challan-add", "client-tds-challan-save", "recurring-invoice-template"];
// Scenarios of the reads of the seventeenth slice that run once (they type no date that a zone could read differently): a quantity's sentence, the held controls, the sentence in its row.
const ONCE = [
  "itc04-a-quantity-that-is-not-a-quantity-is-asked-for-and-the-sentence-goes-when-it-is-right",
  "firm-tds-challan-close-and-cancel-are-held-while-add-is-out",
  "itc04-record-a-lot-is-held-while-a-lot-is-out",
  "goods-back-the-sentence-is-in-the-row-it-is-about-and-leaves-with-the-tab",
  "stock-ledger-window-a-late-answer-to-an-earlier-window-is-not-shown",
  "vendor-edit-opened-again-holds-none-of-the-last-answer",   // the eighteenth slice: opening the vendor already on the supplier form is a form opened afresh
];

test("the browser drive holds every claim this guard states", async () => {
  const drive = await import(pathToFileURL(path.join(WEB, DRIVE)).href);
  const kit = await import(pathToFileURL(path.join(WEB, "scripts/drive/kit.mjs")).href);
  const byId = new Map<string, { id: string; contexts?: unknown }>((drive.scenarios as Array<{ id: string; contexts?: unknown }>).map((s) => [s.id, s]));
  const inThreeZones = [
    ...SIX.flatMap((r) => [`${r}-a-date-after-today-is-refused`, `${r}-the-bound-is-the-indian-day`, `${r}-india-has-moved-on-to-the-next-day`]),
    ...REQUIRED.map((r) => `${r}-a-blank-date-is-asked-for-and-the-sentence-goes-when-one-is-typed`),
    "itc04-a-lot-form-opened-again-holds-none-of-the-last-answer-or-sentence",
    ...EARLIER.map((r) => `${r}-the-answer-to-an-earlier-attempt-does-not-come-back`),
    ...DIALOGS.map((r) => `${r}-opens-on-the-indian-day`),
    "eway-bill-valid-upto-may-run-ahead",
    ...EIGHTEENTH,
  ];
  assert.deepEqual(inThreeZones.filter((id) => !byId.has(id)), [], "a scenario of the sixteenth slice is gone from scripts/drive/scenarios/dates.mjs");
  assert.deepEqual(inThreeZones.filter((id) => JSON.stringify(byId.get(id)?.contexts) !== JSON.stringify(kit.TZ_MATRIX)), [], "a scenario of the sixteenth slice no longer runs in all three zones");
  assert.deepEqual(ONCE.filter((id) => !byId.has(id)), [], "a scenario of the reads of the seventeenth slice is gone from scripts/drive/scenarios/dates.mjs");
  assert.ok(byId.has("reinvestment-claim-a-refused-delete-is-said-over-an-earlier-date-sentence"), "the scenario that holds a refused Delete over an earlier date sentence is gone");
  assert.ok([...byId.keys()].some((id) => id.startsWith("bill-form-15ca")), "the editor-table row for the Form 15CA date is gone");
  // The hour the second table pins is one at which the browser's day is AHEAD of India's on Kiritimati, or the table cannot tell the two days apart.
  const pin = /const AHEAD_OF_INDIA = "([^"]+)"/.exec(fs.readFileSync(path.join(WEB, DRIVE), "utf8"))?.[1];
  assert.ok(pin, "the instant the sixteenth slice re-pins to is not stated");
  const day = (zone: string) => new Date(pin as string).toLocaleDateString("en-CA", { timeZone: zone });
  assert.ok(day("Pacific/Kiritimati") > day("Asia/Kolkata"), `at ${pin} the day on Kiritimati (${day("Pacific/Kiritimati")}) is not ahead of India's (${day("Asia/Kolkata")})`);
  // …and the hour at which INDIA has moved on while UTC and Los Angeles have not, or a bound taken from UTC's day (or from a browser behind India) cannot be told from India's.
  const next = /const INDIA_NEXT_DAY = "([^"]+)"/.exec(fs.readFileSync(path.join(WEB, DRIVE), "utf8"))?.[1];
  assert.ok(next, "the instant at which India's day is ahead of UTC's is not stated");
  const dayThen = (zone: string) => new Date(next as string).toLocaleDateString("en-CA", { timeZone: zone });
  assert.ok(dayThen("Asia/Kolkata") > dayThen("UTC"), `at ${next} the day in India (${dayThen("Asia/Kolkata")}) is not ahead of UTC's (${dayThen("UTC")})`);
  assert.ok(dayThen("Asia/Kolkata") > dayThen("America/Los_Angeles"), `at ${next} the day in India (${dayThen("Asia/Kolkata")}) is not ahead of Los Angeles' (${dayThen("America/Los_Angeles")})`);
});
