// THE DAY A RETURN WAS FILED AT A PORTAL IS THE CA'S STATEMENT: THE BOX STARTS EMPTY AND CANNOT BE LATER THAN TODAY (PRE-A-015, thirteenth slice).
//   node --experimental-strip-types --test scripts/the-day-a-filing-was-made-at-a-portal-is-the-cas-statement-and-starts-empty.test.ts
//
// THE DEFECT
//   Nine prompts that record "I filed this" or "I paid this" at a government portal started with TODAY's date in the box (the shared Mark as Filed prompt, the ITR, GST and
//   MCA trackers' single and batch prompts, a client's MCA confirmation, the payroll File tab), and a tenth, the GST tracker's Add Filing form, sent today's date for a filing
//   recorded as Filed with no box at all. The date a return was filed is what the period lock quotes and what an ESI deposit is judged on time or late by, and recording often
//   lags the portal by days, so a date offered from the clock was the wrong date for whoever pressed Confirm without reading it. Two of the boxes only HINTED at a date after
//   today (`max`) and the rest had no bound at all, so one reached the server, whose sentence for it names a column ("filed_date cannot be in the future").
//
// THE RULE, over every DateInput whose id or aria-label names a filing (`filed`, `filing`) or the payroll tab's "payment or filing"
//   1. it is bounded by today in India (`notAfter={todayIstISO()}`, so a short form is read in the past) and REFUSES a date after it (`{ afterMax: true }`); a bare `max` is a
//      hint and lets the date through;
//   2. its value is never traced to the clock: the `useState` the box reads (an initial value or an object property of it, with or without a type argument), every call of that
//      state's setter and a plain `const x = …` assignment hold no `todayLocalISO`, `todayIstISO`, `today`, `new Date` or `Date.now`.
//   The list of boxes the rule must find is exact and so is its count, so a box that is renamed out of the rule's words, or a new one, is noticed.
//
// TWO BOXES ARE EXEMPT, BY NAME, AND THE REASONS ARE HERE
//   gstr3b-compute-filed-on : the optional "what if it were filed on" date of Compute from Books. It is a question, not a record, and a date ahead is what a CA asks it about.
//   tax-audit-filing-date   : the audit tracker also holds audits that are not started or in progress, so its dates may be planned ones. A future date on an audit recorded as
//                             completed or filed is wrong and is NOT caught here (it is written down on the ledger line).
//
// WHAT THIS DOES NOT COVER (so nobody reads it as wider than it is; each is on the ledger line PRE-A-015 as the next slice)
//   Dates that record a PAYMENT or a receipt after the fact and are not named for a filing: the advance-tax instalments' "paid on" dates, the §140A challan's "Deposited on", the
//   TDS challan date, a CGAS deposit date, the Form 15CA date, the job worker's challan date, the e-invoice and e-way acknowledgement dates and a goods-back date. They state
//   something that has already happened and are not bounded by today. Also not followed: a box named only by a template literal or by its visible label, a value passed in as a
//   prop, and whether the save handler consults the box's problem (`dates.first`): every matched box's page does today.
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

const FILES = ["app", "components"].flatMap((d) => sources(path.join(WEB, d))).map((f) => ({
  file: path.relative(WEB, f),
  code: stripComments(fs.readFileSync(f, "utf8")),
}));

/** The text of every `<DateInput …/>` in `code`, balanced on braces (an attribute may hold an arrow function with its own `>`). */
function dateInputs(code: string): string[] {
  const out: string[] = [];
  const re = /<DateInput\b/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(code))) {
    let depth = 0, i = m.index;
    while (i < code.length) {
      const c = code[i];
      if (c === "{") depth++;
      else if (c === "}") depth--;
      else if (c === ">" && depth === 0 && code[i - 1] === "/") break;
      i++;
    }
    out.push(code.slice(m.index, i + 1));
  }
  return out;
}

/** The text between the parenthesis at `open` and its match. */
function balanced(code: string, open: number): string {
  let depth = 0;
  for (let i = open; i < code.length; i++) {
    if (code[i] === "(") depth++;
    else if (code[i] === ")" && --depth === 0) return code.slice(open + 1, i);
  }
  return code.slice(open + 1);
}

const NAME = (el: string): string =>
  `${/\bid="([^"]+)"/.exec(el)?.[1] ?? ""} ${/aria-label="([^"]+)"/.exec(el)?.[1] ?? ""}`.trim();

/** A box that records a filing: named for it, and not a due date. */
const IS_A_FILING_DATE = (name: string): boolean => /filed|filing|payment or filing/i.test(name) && !/due/i.test(name);

const EXEMPT = new Set(["gstr3b-compute-filed-on Date filed", "tax-audit-filing-date"]);

// Every filing box the rule finds today, by exact name. A box that leaves the rule's words (a rename) or a new one changes this list and fails the premise.
const EXPECTED = [
  "mark-filed-date", "itr-filed-modal-date", "itr-batch-filed-date", "gst-filed-modal-date", "gst-batch-filed-date", "gst-add-filing-filed-on", "mca-filed-modal-date",
  "mca-batch-filed-date", "mca-filed-on", "mca-confirm-filing-date Filing date", "Date of the payment or filing", "itr-ack-filing-date", "itr-original-filing-date",
  "gstr1-filed-date", "gstr3b-filed-date", "gst-mark-filed-date", "tds-filing-date", ...EXEMPT,
].sort();

const BOXES = FILES.flatMap(({ file, code }) => dateInputs(code).map((el) => ({ file, code, el, name: NAME(el) })))
  .filter((b) => IS_A_FILING_DATE(b.name));

test("the premise: the rule finds exactly the filing boxes this slice is about", () => {
  assert.deepEqual(BOXES.map((b) => b.name).sort(), EXPECTED,
    "a filing box was renamed out of the rule's words, removed, or added: update EXPECTED with it (and give it a drive row)");
});

test("every filing date box is bounded by today in India and refuses a date after it", () => {
  const offenders: string[] = [];
  for (const b of BOXES) {
    if (EXEMPT.has(b.name)) continue;
    if (!/\bnotAfter=\{todayIstISO\(\)\}/.test(b.el)) offenders.push(`${b.file}: ${b.name} has no notAfter={todayIstISO()}`);
    if (!/afterMax:\s*true/.test(b.el)) offenders.push(`${b.file}: ${b.name} does not refuse a date after today ({ afterMax: true })`);
    if (/\smax=/.test(b.el)) offenders.push(`${b.file}: ${b.name} carries a bare max (a hint that lets the date through)`);
  }
  assert.deepEqual(offenders, [], "a date after today was only hinted at, so it reached the server, which words it with a column name");
});

// What feeds a box's value: the clock, in any spelling the code uses for it.
const CLOCK = /\b(?:todayLocalISO|todayIstISO|today|new\s+Date|Date\.now)\b/;

/** Where the clock reaches the state a box reads: its `useState` argument, every call of its setter, and a plain assignment. Returns the offending text. */
function clockFeeds(code: string, root: string): { found: boolean; hits: string[] } {
  const hits: string[] = [];
  let found = false;
  const state = new RegExp(`const\\s*\\[\\s*${root}\\s*,\\s*(set\\w+)\\s*\\]\\s*=\\s*useState\\s*(?:<[^()]*>)?\\s*\\(`).exec(code);
  if (state) {
    found = true;
    const init = balanced(code, state.index + state[0].length - 1);
    if (CLOCK.test(init)) hits.push(`the initial state of ${root}: useState(${init.trim().slice(0, 70)})`);
    const call = new RegExp(`\\b${state[1]}\\s*\\(`, "g");
    let m: RegExpExecArray | null;
    while ((m = call.exec(code))) {
      const arg = balanced(code, m.index + m[0].length - 1);
      if (CLOCK.test(arg)) hits.push(`a call of ${state[1]}: ${state[1]}(${arg.trim().slice(0, 70)})`);
    }
  }
  const assigned = new RegExp(`(?:const|let)\\s+${root}\\s*=([^;]*);`).exec(code);
  if (assigned) {
    found = true;
    if (CLOCK.test(assigned[1])) hits.push(`an assignment: ${root} =${assigned[1].trim().slice(0, 70)}`);
  }
  return { found, hits };
}

test("no filing date is traced to the clock: not its initial state, not a setter call, not an assignment", () => {
  const offenders: string[] = [];
  const untraced: string[] = [];
  for (const b of BOXES) {
    const value = /\bvalue=\{([^}]+)\}/.exec(b.el)?.[1] ?? "";
    const root = /^\s*([A-Za-z_$][\w$]*)/.exec(value)?.[1];
    if (!root) { untraced.push(`${b.file}: ${b.name} (no value expression)`); continue; }
    const { found, hits } = clockFeeds(b.code, root);
    if (!found) untraced.push(`${b.file}: ${b.name} (${root} is not a useState or a plain assignment here)`);
    for (const h of hits) offenders.push(`${b.file}: ${b.name} reads ${root}, and ${h}`);
  }
  assert.deepEqual(offenders, [], "the date a return was filed is the CA's statement; the software does not offer one");
  // A box whose value cannot be followed passes by default: there must be none, or each is named here with why.
  assert.deepEqual(untraced, [
    // the audit tracker's dates live in one form object (`form.filingDate`) that is built from the stored audit or an empty form
    "app/income-tax/tax-audit/page.tsx: tax-audit-filing-date (form is not a useState or a plain assignment here)",
  ].filter((u) => untraced.includes(u)), "a filing box whose value cannot be followed to its state");
});

test("the tracing reads the shapes the ten prompts used and does not pass on a re-introduction", () => {
  const sample = (src: string, root: string) => clockFeeds(stripComments(src), root);
  const bad = [
    ["const [filedForm, setFiledForm] = useState({ arn: \"\", filed_date: todayLocalISO() });", "filedForm"],
    ["const [ackDate, setAckDate] = useState(todayLocalISO());", "ackDate"],
    ["const [filedDate, setFiledDate] = useState<string>(todayLocalISO());", "filedDate"],
    ["const [filedDate, setFiledDate] = useState(\"\"); function open() { setFiledDate(todayIstISO()); }", "filedDate"],
    ["const [on, setOn] = useState(() => new Date().toISOString().slice(0, 10));", "on"],
    ["const filedDate = status === \"Filed\" ? todayLocalISO() : null;", "filedDate"],
  ] as const;
  for (const [src, root] of bad) assert.ok(sample(src, root).hits.length > 0, `not seen: ${src}`);
  const good = [
    ["const [filedForm, setFiledForm] = useState({ arn: \"\", filed_date: \"\" }); setFiledForm((p) => ({ ...p, filed_date: v }));", "filedForm"],
    ["const [filedDate, setFiledDate] = useState(\"\"); const dates = useDateProblems(); notAfter={todayIstISO()}", "filedDate"],
  ] as const;
  for (const [src, root] of good) assert.deepEqual(sample(src, root).hits, [], `wrongly flagged: ${src}`);
});

test("the GST Add Filing form asks for the receipt and the day when a filing is recorded as Filed, and keeps the row when the server declines it", () => {
  const { code } = FILES.find((f) => f.file === path.join("app", "gst", "page.tsx"))!;
  assert.match(code, /id="gst-add-filing-filed-on"/);
  assert.match(code, /status === "Filed" && !filedOn/, "a filing recorded as Filed with no date is refused in a sentence");
  assert.match(code, /status === "Filed" && !arn\.trim\(\)/, "the tracker's other prompts refuse a filing without the portal's receipt, and so does this one");
  assert.match(code, /if \(next !== "Filed"\) \{ setFiledOn\(""\); setArn\(""\); \}/, "a box that goes away takes its value with it");
  assert.match(code, /const filedDate = status === "Filed" \? filedOn : null/, "the date sent is the one typed");
  // The row is inserted before the filing is recorded; a refusal after it must not leave the dialog open over a row that now exists.
  assert.match(code, /Filing added, but not marked filed/);
});

test("the MCA Add Filing form keeps the row it inserted when the status door refuses or raises", () => {
  const { code } = FILES.find((f) => f.file === path.join("app", "mca", "page.tsx"))!;
  // The door answers a refused date as HTTP 200 with success false and a refused caller as a 403 that the API client RAISES: both leave a pending row.
  assert.match(code, /try \{\s*const res = await api\.mca\.setFilingStatus\(filing\.id/, "the call that records the filing is guarded, so a raised refusal is not left to the outer catch");
  assert.match(code, /Filing added, but not marked filed/);
  assert.match(code, /if \(declined\) \{\s*[^}]*onAdded\(filing\)/, "a declined filing is still added to the list as pending");
});

test("a date box shown again over a value its parent kept reports a date outside its range, and a panel or card is about ONE subject", () => {
  const read = (rel: string) => FILES.find((f) => f.file === rel.split("/").join(path.sep))?.code
    ?? stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));
  // The unmount withdraws a sentence; nothing else would put it back for a date after today that the parent still holds.
  assert.match(read("components/ui/date-input.tsx"), /if \(state\.outOfRange\) stateCallback\.current\?\.\(state\)/, "DateInput must report an out-of-range value when it is mounted over one");
  // The ITR acknowledgement panel and the new-filing form open and close empty, and the earlier receipt is sent only where the kind needs it.
  const itr = read("app/clients/[id]/tax/filing/page.tsx");
  assert.match(itr, /function openAckPanel\(\)/);
  assert.match(itr, /function closeAckPanel\(\)/);
  assert.match(itr, /closeAckPanel\(\);\s*\}\s*setSelectedFiling\(f\)/, "picking another return closes the panel of the first");
  assert.match(itr, /<DateInput key=\{ackKey\} id="itr-ack-filing-date"/);
  assert.match(itr, /original_filing_date: selectedKind\?\.needs_the_earlier_receipt \?/, "a box that is not on the screen sends nothing");
  // The payroll File tab keys a card by the run its own figures came from: the obligation keys are the same in every month.
  assert.match(read("components/payroll/StatutoryHandoff.tsx"), /key=\{`\$\{handoff\.run_id \|\| runId\}:\$\{o\.key\}`\}/);
});
