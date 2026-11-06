// A TDS statement is marked filed on a date the CA states, never on the day it was recorded, and the screen says when the
// compliance calendar was left open.
//
// Run with:
//   node --experimental-strip-types --test scripts/a-tds-statement-is-filed-on-a-stated-date-and-the-screen-says-what-the-calendar-did.test.ts
//
// WHAT WAS WRONG
//     The "Mark as Filed" modal on the TDS returns screen took a PRN and an acknowledgement number and nothing else, so the
//     server stamped the filing with the instant the button was pressed. A statement filed on the portal on 28 October and
//     recorded on 3 November was filed on 3 November here, which is the date the late-filing fee and the calendar both turn
//     on. The server requires the date now and never defaults it; the screen has to ask for it and must not fill it in.
//     And recording the PRN closes the calendar's obligation for the quarter on the server; where it did not, the screen
//     shows the server's own sentence.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const PAGE = path.join("app", "tds", "returns", "page.tsx");
const DATA = path.join("lib", "data", "tds.ts");

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

function sourceFiles(dir: string, out: string[] = []): string[] {
  for (const entry of fs.readdirSync(path.join(WEB, dir), { withFileTypes: true })) {
    const rel = path.join(dir, entry.name);
    if (entry.isDirectory()) { if (entry.name !== "node_modules") sourceFiles(rel, out); }
    else if (/\.(ts|tsx)$/.test(entry.name) && !/\.test\./.test(entry.name)) out.push(rel);
  }
  return out;
}

/** The text of the arguments of one call, balanced on its own parentheses. */
function argumentsOf(src: string, from: number): string {
  let depth = 0;
  for (let i = from; i < src.length; i++) {
    if (src[i] === "(") depth++;
    else if (src[i] === ")" && --depth === 0) return src.slice(from + 1, i);
  }
  throw new Error("unbalanced call");
}

function topLevelArgs(text: string): string[] {
  const args: string[] = [];
  let depth = 0, current = "";
  for (const ch of text) {
    if ("([{".includes(ch)) depth++;
    if (")]}".includes(ch)) depth--;
    if (ch === "," && depth === 0) { args.push(current.trim()); current = ""; } else current += ch;
  }
  if (current.trim()) args.push(current.trim());
  return args;
}

test("the status call carries the date the CA stated, and the helper takes it as an argument", () => {
  const src = code(DATA);
  const fn = /export async function markTDSFiled\(([\s\S]*?)\): Promise</.exec(src);
  assert.ok(fn, "markTDSFiled is gone");
  assert.match(fn[1], /filingDate:\s*string/, "the helper no longer takes a filing date");
  assert.match(src, /filing_date:\s*filingDate/, "the date is not sent to the server");
});

test("every call to markTDSFiled passes a date as its fourth argument", () => {
  const calls: string[] = [];
  for (const rel of [...sourceFiles("app"), ...sourceFiles("components"), ...sourceFiles("lib")]) {
    const src = code(rel);
    for (const m of src.matchAll(/\bmarkTDSFiled\(/g)) {
      if (src.slice(Math.max(0, m.index - 30), m.index).includes("function ")) continue;
      const args = topLevelArgs(argumentsOf(src, m.index + m[0].length - 1));
      calls.push(`${rel}: ${args.length}`);
      // Four arguments, the date the fourth; or five, where the fifth is the CA's second confirmation (POST-A-402) and nothing but that variable.
      assert.ok(args.length === 4 || args.length === 5, `${rel} calls markTDSFiled without a date`);
      assert.equal(args[3], "filingDate", `${rel} passes ${args[3]} where the date the CA stated goes`);
      if (args.length === 5) assert.equal(args[4], "recordAnyway", `${rel} passes ${args[4]} as the CA's confirmation to record the statement anyway`);
    }
  }
  assert.ok(calls.length >= 1, "no caller found: the scan has gone blind");
});

test("the screen asks for the date, starts it blank, and cannot confirm without it", () => {
  const src = code(PAGE);
  assert.match(src, /const \[filingDate, setFilingDate\] = useState\(""\)/, "the date must start blank, never today's");
  assert.doesNotMatch(src, /useState\(todayIst|useState\(new Date|setFilingDate\(todayIst|setFilingDate\(new Date/,
    "the screen fills the filing date in for the CA");
  assert.match(src, /<DateInput id="tds-filing-date"[^>]*value=\{filingDate\} onChange=\{setFilingDate\}/);
  assert.match(src, /disabled=\{!prn \|\| !filingDate \|\| filing\}/, "Confirm Filed is enabled with no date, or while the request that records the filing is out");
  assert.match(src, /markTDSFiled\(asked, prn, ackNumber, filingDate, recordAnyway\)/);
});

test("the date is cleared when the client, the form, the year or the quarter changes, so one statement's date is not carried to another", () => {
  const src = code(PAGE);
  // A computed statement belongs to the client, the form, the year and the quarter it was computed for: a changed selector left a 26Q statement
  // approved and ready to be marked filed under a "Mark 24Q as Filed" heading (the twelfth slice of the browser drive, PRE-A-015).
  const reset = /useEffect\(\(\) => \{([\s\S]*?)\}, \[clientId, returnType, financialYear, quarter\]\)/.exec(src);
  assert.ok(reset, "the reset on a changed client, form, year or quarter is gone");
  // …including the question the product asks of a statement it holds back (POST-A-402): it names a statement that is gone once the selector changes.
  for (const cleared of ["setResult(null)", "setReturnId(null)", 'setPrn("")', 'setAckNumber("")', 'setFilingDate("")', "setFiledError(null)", "setCalendarNote(null)", "setHeldBack(null)"]) {
    assert.ok(reset[1].includes(cleared), `the change does not clear ${cleared}`);
  }
});

test("the dialog belongs to one statement: opening it, computing another and a successful filing all clear it", () => {
  const src = code(PAGE);
  const clear = /function clearTheFiledDialog\(\) \{([\s\S]*?)\n  \}/.exec(src);
  assert.ok(clear, "clearTheFiledDialog is gone");
  for (const cleared of ['setPrn("")', 'setAckNumber("")', 'setFilingDate("")', "setFiledError(null)", "setHeldBack(null)"]) {
    assert.ok(clear[1].includes(cleared), `clearTheFiledDialog does not clear ${cleared}`);
  }
  const open = /function openFiledModal\(\) \{([\s\S]*?)\n  \}/.exec(src);
  assert.ok(open && open[1].includes("clearTheFiledDialog()") && open[1].includes("setShowFiledModal(true)"),
    "opening the dialog does not start it blank");
  assert.match(src, /onClick=\{openFiledModal\}/, "the button opens the dialog without clearing it");
  const compute = /async function handleCompute\(\) \{([\s\S]*?)\n  \}/.exec(src);
  assert.ok(compute && compute[1].includes("clearTheFiledDialog()") && compute[1].includes("setCalendarNote(null)"),
    "computing another statement leaves the last one's PRN, date and calendar note on screen");
  const filed = /async function markFiled\(recordAnyway: boolean\) \{([\s\S]*?)\n  \}/.exec(src);
  assert.ok(filed && filed[1].includes("clearTheFiledDialog()") && filed[1].includes("setError(null)"),
    "a successful filing leaves its PRN and date in the dialog");
});

test("a refusal of the dialog is shown IN the dialog, because the page's callout sits under the backdrop", () => {
  const src = code(PAGE);
  const filed = /async function markFiled\(recordAnyway: boolean\) \{([\s\S]*?)\n  \}/.exec(src);
  assert.ok(filed, "markFiled is gone");
  assert.doesNotMatch(filed[1], /setError\((?!null)/, "a refusal is sent to the page's callout behind the backdrop");
  assert.match(filed[1], /setFiledError\(e instanceof Error/);
  assert.match(src, /\{filedError && <Callout tone="problem">\{filedError\}<\/Callout>\}/, "the dialog never shows its error");
});

test("the date box is bounded by today in IST, refuses a date after it in a sentence and never fills it in as a value", () => {
  const src = code(PAGE);
  // `notAfter` reads a short form (15/1) in the past and gives the box's own sentence for a date typed in full after today; `afterMax` makes that a refusal
  // before anything is sent, because the server's words for a future date name a column ("filing_date cannot be in the future").
  assert.match(src, /<DateInput id="tds-filing-date"[^>]*notAfter=\{todayIstISO\(\)\}[^>]*\{ afterMax: true \}/);
  assert.doesNotMatch(src, /<DateInput id="tds-filing-date"[^>]*\smax=/, "a bare max is only a hint, and a date after today reached the server");
});

test("the server's sentence about the calendar is read through the one helper and shown, and the page decides nothing about the state", () => {
  const data = code(DATA);
  assert.match(data, /import \{ obligationNote \} from "@\/lib\/compliance\/obligationNote"/);
  assert.match(data, /calendarNote:\s*obligationNote\(resp\.data\)/, "the server's sentence about the calendar is thrown away");
  const page = code(PAGE);
  assert.match(page, /setCalendarNote\(note\)/);
  assert.match(page, /\{calendarNote && \(/, "the note is never shown");
  assert.doesNotMatch(page, /compliance_obligation/, "the page reads the block directly instead of through the helper");
});
