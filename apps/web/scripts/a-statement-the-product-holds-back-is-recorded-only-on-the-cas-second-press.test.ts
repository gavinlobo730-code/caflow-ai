// A TDS statement the product holds back is recorded only on the CA's own second press (POST-A-402). Run with:
//   node --experimental-strip-types --test scripts/a-statement-the-product-holds-back-is-recorded-only-on-the-cas-second-press.test.ts
//
// WHY THIS EXISTS
//     The server refuses to record a TDS statement as CA approved or filed when it holds no deductees or its quarter has not ended, unless the request
//     carries `acknowledge_incomplete`. The refusal's sentence used to end "Resubmit with acknowledge_incomplete=true to record it anyway", an
//     instruction no screen could follow, because nothing in the web app sent the flag: a CA who had filed the statement on the portal could not record
//     that it was filed. The screens now ask: the server's sentence, and "Record it anyway" / "Leave it as it is". The flag is the CA's own confirmation
//     and must never go out by itself, so this is the rule, held from the side that reads the screens:
//
//       * only two files send the flag (the helper that talks to the firm-level screen's two calls, and the client tab's status call), and each
//         sends it only inside `recordAnyway ? { acknowledge_incomplete: true } : {}`;
//       * what passes `true` for it is the "Record it anyway" button and nothing else; the buttons that begin the action pass `false` or nothing;
//       * a handler wired straight to a button takes NO parameter, because the shared Button hands its click to a handler and a click is truthy
//         (a handler that took "record it anyway" first would have sent the flag on the first press);
//       * the refusal is turned into a question only on the server's marker (`can_record_anyway === true`) and with the server's sentence, and every
//         other refusal is said as it always was.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.join(import.meta.dirname, "..");
const DATA = "lib/data/tds.ts";
const TAB = "app/clients/[id]/compliance/tds/page.tsx";
const PAGE = "app/tds/returns/page.tsx";
const ASK = "components/tds/RecordAnywayAsk.tsx";

/** The file with comments blanked (block comments, whole-line comments and trailing ones that follow a space), so a sentence in a comment is not read as code. */
function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "")
    .replace(/(\s)\/\/\s[^\n]*$/gm, "$1");
}

function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of fs.readdirSync(path.join(WEB, dir), { withFileTypes: true })) {
    const rel = path.posix.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...sourceFiles(rel));
    else if (/\.(ts|tsx)$/.test(entry.name)) out.push(rel);
  }
  return out;
}

/** The text between the bracket at `open` and its match (strings are skipped), exclusive. */
function balanced(src: string, open: number): string {
  const pairs: Record<string, string> = { "(": ")", "{": "}", "[": "]" };
  const close = pairs[src[open]];
  assert.ok(close, `no bracket at ${open}`);
  let depth = 0;
  for (let i = open; i < src.length; i++) {
    const c = src[i];
    if (c === '"' || c === "'" || c === "`") { for (i++; i < src.length && src[i] !== c; i++) if (src[i] === "\\") i++; continue; }
    if (c === src[open]) depth++;
    else if (c === close && --depth === 0) return src.slice(open + 1, i);
  }
  assert.fail("unbalanced");
}

const topLevelArgs = (inner: string): string[] => {
  const args: string[] = [];
  let depth = 0, cur = "";
  for (let i = 0; i < inner.length; i++) {
    const c = inner[i];
    if (c === '"' || c === "'" || c === "`") { const at = i; for (i++; i < inner.length && inner[i] !== c; i++) if (inner[i] === "\\") i++; cur += inner.slice(at, i + 1); continue; }
    if ("([{".includes(c)) depth++;
    if (")]}".includes(c)) depth--;
    if (c === "," && depth === 0) { args.push(cur.trim()); cur = ""; continue; }
    cur += c;
  }
  if (cur.trim()) args.push(cur.trim());
  return args;
};

/** Every call `name(…)` in `src`: its arguments, and the text of the 200 characters before it (which says whether it is a declaration). */
function callsOf(src: string, name: string): { args: string[]; before: string }[] {
  const out: { args: string[]; before: string }[] = [];
  for (const m of src.matchAll(new RegExp(`\\b${name}\\(`, "g"))) {
    const before = src.slice(Math.max(0, m.index - 40), m.index);
    if (/function\s+$/.test(before)) continue;
    out.push({ args: topLevelArgs(balanced(src, m.index + m[0].length - 1)), before });
  }
  return out;
}

test("the flag is sent from two files, and only inside the conditional that the CA's second press turns on", () => {
  const senders = [...sourceFiles("app"), ...sourceFiles("components"), ...sourceFiles("lib")].filter((rel) => code(rel).includes("acknowledge_incomplete"));
  assert.deepEqual(senders.sort(), [TAB, DATA].sort(), "a file other than the helper and the client tab sends the CA's confirmation to record an incomplete statement");
  const helper = code(DATA);
  assert.equal(helper.match(/acknowledge_incomplete/g)?.length, 2, "the helper sends the flag from other than its two calls");
  assert.equal(helper.match(/\.\.\.\(recordAnyway \? \{ acknowledge_incomplete: true \} : \{\}\)/g)?.length, 2, "the helper sends the flag other than inside `...(recordAnyway ? { acknowledge_incomplete: true } : {})`");
  const tab = code(TAB);
  assert.equal(tab.match(/acknowledge_incomplete/g)?.length, 1);
  assert.match(tab, /\.\.\.\(recordAnyway \? \{ acknowledge_incomplete: true \} : \{\}\)/, "the client tab sends the flag other than inside the conditional");
  assert.equal(helper.match(/recordAnyway = false/g)?.length, 2, "each of the two helpers takes the CA's confirmation, defaulting to false");
  assert.doesNotMatch(helper, /recordAnyway(?::\s*boolean)?\s*=\s*(?![ \t]*false\b)/, "a helper's confirmation defaults to anything but false");
});

test("on the client tab the buttons that begin a change pass no confirmation, and only the question's button passes one", () => {
  const tab = code(TAB);
  assert.match(tab, /async function updateStatus\(id: string, status: string, recordAnyway = false\)/);
  const calls = callsOf(tab, "updateStatus");
  assert.equal(calls.length, 3, "updateStatus is called from other than the two buttons and the question");
  const withThird = calls.filter((c) => c.args.length === 3);
  assert.equal(withThird.length, 1, "more than one place passes the confirmation");
  assert.deepEqual(withThird[0].args, ["heldBack.id", "heldBack.status", "true"], "the confirmation is passed for other than the statement the server held back");
  assert.match(withThird[0].before, /onConfirm=\{\(\) =>\s*$/, "the confirmation is passed from outside the question's own button");
  for (const c of calls.filter((x) => x.args.length === 2)) assert.ok(/^r\.id as string$/.test(c.args[0]) && /^"(prepared|ca_approved)"$/.test(c.args[1]), `a button passes ${c.args.join(", ")}`);
  const fn = tab.slice(tab.indexOf("async function updateStatus("));
  const body = balanced(fn, fn.indexOf("{"));
  assert.match(body, /setStatusError\(null\);\s*setHeldBack\(null\);/, "a new press does not clear the last question and the last sentence before it goes out");
  // …and a list read again clears it (a question about one of the rows of the list as it stood)
  const load = /const load = useCallback\(\(\) => \{([\s\S]*?)\}, \[clientId\]\);/.exec(tab.slice(tab.indexOf("function ReturnsTab(")));
  assert.ok(load && load[1].includes("setStatusError(null); setHeldBack(null);"), "a list read again leaves the question the server asked about one of its old rows");
});

test("the refusal becomes a question only on the server's marker, and with the server's own sentence", () => {
  const tab = code(TAB);
  assert.match(tab, /const marker = res\?\.data as \{ can_record_anyway\?: unknown \} \| null \| undefined;\s*if \(marker\?\.can_record_anyway === true && res\?\.error\) \{\s*setHeldBack\(\{ id, status, sentence: res\.error \}\);\s*return;\s*\}/);
  const helper = code(DATA);
  assert.match(helper, /\n  if \(marker\?\.can_record_anyway === true && typeof resp\.error === "string" && resp\.error\) \{\n    return new StatementIncompleteError\(/, "the helper's typed error is raised on other than the server's marker and a sentence, or never");
  assert.match(helper, /return new StatementIncompleteError\(resp\.error,/, "the typed error does not carry the server's sentence");
  assert.match(helper, /return new Error\(resp\.error \?\? fallback\);/, "any other refusal is not the plain error it was");
  const useCount = helper.match(/throw refusalOf\(resp, /g)?.length;
  assert.equal(useCount, 2, "the two calls do not both turn a refusal into the typed error");
});

test("the firm-level page: the buttons call handlers that take no parameter, and only the question's button confirms", () => {
  const page = code(PAGE);
  assert.match(page, /async function handleApprove\(\) \{ await approveStatement\(false\); \}/);
  assert.match(page, /async function handleMarkFiled\(\) \{ await markFiled\(false\); \}/);
  assert.match(page, /onClick=\{handleApprove\}/, "the approve button is not wired straight to the no-parameter handler");
  assert.match(page, /onClick=\{handleMarkFiled\}/, "the filed button is not wired straight to the no-parameter handler");
  assert.doesNotMatch(page, /onClick=\{(?:approveStatement|markFiled)\}/, "a button is wired to the handler that takes the confirmation: the click would be its first argument");
  for (const [fn, once] of [["approveStatement", "approve"], ["markFiled", "filed"]] as const) {
    const calls = callsOf(page, fn);
    assert.deepEqual(calls.map((c) => c.args.join(",")).sort(), ["false", "true"], `${fn} is called from other than its wrapper (false) and its question (true)`);
    const confirm = calls.find((c) => c.args[0] === "true")!;
    assert.match(confirm.before, /onConfirm=\{\(\) =>\s*$/, `${fn}(true) is called from outside the question's own button`);
    // drawn only while the statement it was asked about is the one on screen
    const heldAs = new RegExp(`heldBack\\?\\.kind === "${once}" && heldBack\\.returnId === returnId && \\(\\s*<RecordAnywayAsk[^>]*onConfirm=\\{\\(\\) => ${fn}\\(true\\)\\}`);
    assert.match(page, heldAs, `the ${once} question is not drawn with the ${fn}(true) button, or not only while its statement is on screen`);
  }
  assert.match(page, /if \(e instanceof StatementIncompleteError\) setHeldBack\(\{ kind: "approve", sentence: e\.message, returnId: asked \}\);\s*else setError\(/, "the approval does not ask (about the statement it was pressed on) before it says an error");
  assert.match(page, /if \(e instanceof StatementIncompleteError\) \{ setHeldBack\(\{ kind: "filed", sentence: e\.message, returnId: asked \}\); return; \}\s*setFiledError\(/, "the filing does not ask (about the statement it was pressed on) before it says an error");
  assert.match(page, /useState<\{ kind: "approve" \| "filed"; sentence: string; returnId: string \} \| null>/, "the question does not name the statement it was asked about");
  // a new approval press empties the last error, so an earlier "Approval failed" is not left standing over the question
  const approve = /async function approveStatement\(recordAnyway: boolean\) \{([\s\S]*?)\n  \}/.exec(page);
  assert.ok(approve && /setHeldBack\(null\);\s*setError\(null\);/.test(approve[1]), "a new approval press leaves the last error and the last question on the screen");
  assert.match(page, /await approveTDSReturn\(asked, recordAnyway\)/);
  assert.match(page, /markTDSFiled\(asked, prn, ackNumber, filingDate, recordAnyway\)/);
  const reset = /function clearTheFiledDialog\(\) \{([\s\S]*?)\n  \}/.exec(page);
  assert.ok(reset && reset[1].includes("setHeldBack(null)"), "a question about the last statement outlives the dialog and the next compute");
});

test("the filing question is drawn inside the dialog it belongs to, the approval's beside the buttons it answers, each only while its statement is on screen", () => {
  const page = code(PAGE);
  const dialogAt = page.indexOf("{showFiledModal && (");
  const filedAt = page.indexOf('heldBack?.kind === "filed"');
  const approveAt = page.indexOf('heldBack?.kind === "approve"');
  const actionsAt = page.indexOf('<div className="flex flex-wrap gap-3">', approveAt);     // the actions row (the JSX comment above it is blanked by code())
  assert.ok(dialogAt > 0 && filedAt > dialogAt, "the filing question is drawn outside the Mark as Filed dialog, under its backdrop");
  assert.ok(approveAt > 0 && approveAt < dialogAt, "the approval question is drawn inside the dialog");
  // beside the buttons it answers: at the top of the page it was off screen once the CA had pressed CA Approve at the foot of a long statement
  assert.ok(actionsAt > approveAt && actionsAt - approveAt < 700, "the approval question is not drawn directly above the actions row");
  assert.ok(approveAt > page.indexOf("{result && ("), "the approval question is drawn outside the block that holds the statement it asks about");
  const tab = code(TAB);
  const returnsTab = tab.slice(tab.indexOf("function ReturnsTab("));
  const askAt = returnsTab.indexOf("<RecordAnywayAsk");
  assert.ok(askAt > returnsTab.indexOf("{statusError && "), "the question is drawn above the sentence it replaces, not after it");
  assert.ok(askAt > 0 && askAt < returnsTab.indexOf("<table"), "the question is drawn after the table, away from the row that raised it");
});

test("the firm-level page's question does not outlive what it asked about: it is cleared with the statement, with what was typed, and a request in flight holds the dialog", () => {
  const page = code(PAGE);
  // the statement it was asked about is gone when the client, the form, the year or the quarter changes (the guard of the filed-statement rules lists the full reset)
  const reset = /useEffect\(\(\) => \{([\s\S]*?)\}, \[clientId, returnType, financialYear, quarter\]\)/.exec(page);
  assert.ok(reset && reset[1].includes("setHeldBack(null)"), "a question outlives the statement it asked about when the selector changes");
  // what the filing question would record is what was typed in the dialog: a changed PRN, acknowledgement or date drops it
  assert.match(page, /useEffect\(\(\) => \{\s*setHeldBack\(\(h\) => \(h\?\.kind === "filed" \? null : h\)\);\s*\}, \[prn, ackNumber, filingDate\]\);/, "the filing question outlives a changed PRN, acknowledgement or date");
  // the request that records the filing holds the dialog: the pressed button is gone (the question unmounts at the press), so nothing else would
  const filed = /async function markFiled\(recordAnyway: boolean\) \{([\s\S]*?)\n  \}/.exec(page);
  assert.ok(filed, "markFiled is gone");
  assert.ok(filed[1].indexOf("setFiling(true)") > 0 && filed[1].indexOf("setFiling(true)") < filed[1].indexOf("await markTDSFiled("), "the dialog is not held before the request goes out");
  assert.match(filed[1], /finally \{\s*setFiling\(false\);\s*\}/, "the hold is not released in a finally");
  assert.match(page, /actionInFlight = approving \|\| loading \|\| filing;/, "the page's one-action-at-a-time rule does not count the filing");
  assert.match(page, /<button onClick=\{\(\) => setShowFiledModal\(false\)\} disabled=\{filing\}/, "Cancel is live while the filing is being recorded");
  assert.match(page, /onClick=\{\(\) => \{ if \(!filing\) setShowFiledModal\(false\); \}\}/, "the backdrop closes the dialog while the filing is being recorded");
  assert.match(page, /<RecordAnywayAsk sentence=\{heldBack\.sentence\} what="filed" busy=\{filing\}/, "the filing question does not say it is busy while the request is out");
  // the dialog grew by a question: on a short screen its buttons would leave the page if it did not scroll
  assert.match(page, /relative bg-white rounded-2xl shadow-xl w-full max-w-md mx-4 p-6 space-y-4 max-h-\[90vh\] overflow-y-auto/, "the Mark as Filed dialog does not scroll on a short screen");
});

test("the question says the server's sentence, offers the two choices and sends nothing on Leave", () => {
  const ask = code(ASK);
  assert.match(ask, /<Callout tone="attention"/, "the question is not an attention callout");
  // it replaces a refusal that was announced (an error paragraph, a problem callout): without the wrapper a screen-reader user pressing CA Approve hears nothing
  assert.match(ask, /<div role="alert">\s*<Callout tone="attention"/, "the question is not announced to a screen reader");
  assert.doesNotMatch(ask, /autoFocus|\.focus\(/, "focus is moved onto a button of the question: a held Enter would confirm");
  assert.match(ask, /<p>\{sentence\}<\/p>/, "the question does not say the server's sentence as it was said");
  assert.match(ask, />\s*Record it anyway\s*</);
  assert.match(ask, />\s*Leave it as it is\s*</);
  assert.match(ask, /onClick=\{onConfirm\} disabled=\{busy\}/, "the confirm button is not the one wired to onConfirm");
  assert.match(ask, /onClick=\{onLeave\} disabled=\{busy\}/, "Leave is not wired to onLeave");
  assert.match(ask, /<button type="button" onClick=\{onLeave\} disabled=\{busy\}[^>]*>\s*Leave it as it is/, "the button that says Leave is not the one wired to onLeave");
  assert.match(ask, /<Button [^>]*onClick=\{onConfirm\}[^>]*>\s*Record it anyway/, "the button that says Record it anyway is not the one wired to onConfirm");
  assert.match(ask, /import \{ Button \} from "@\/components\/ui\/button";/, "the confirmation is not on the shared button that ignores a second press");
});

test("the scan finds what it is for (a self-test)", () => {
  assert.equal(callsOf("a(1, 2) function a(x) {} b(a(3))", "a").length, 2, "declarations are skipped and nested calls are found");
  assert.deepEqual(topLevelArgs("heldBack.id, f(1, 2), `a,b`"), ["heldBack.id", "f(1, 2)", "`a,b`"]);
  assert.equal(balanced("f(a, (b), `c)`) tail", 1), "a, (b), `c)`", "a bracket inside a string ends the span");
  // comments are blanked, so a sentence in a comment is not read as code (the files say `acknowledge_incomplete` in prose)
  assert.equal(code(DATA).includes("acknowledge_incomplete"), true);
  assert.equal(code(DATA).split("\n").some((line) => /^\s*\/\//.test(line)), false);
});
