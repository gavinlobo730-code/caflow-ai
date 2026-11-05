// THE STATUTORY-VALUES, ENGAGEMENT-LETTER AND STOCK FORMS SAY THEIR REFUSALS WHERE THE PERSON IS LOOKING, KEEP THEIR DATES IN ORDER AND LEAVE NOTHING STALE (PRE-A-015, fifteenth slice).
//   node --experimental-strip-types --test scripts/the-notification-letter-and-lot-forms-bound-their-dates-and-say-their-refusals-inside-the-dialog.test.ts
//
// THE DEFECTS
//   1. The statutory values screen is a full-screen overlay over a page whose message line sits BEHIND it. Every sentence its Record button had (a state code that is not two
//      letters, the required fields, a band amount with a comma, the server's refusal of a set with a hole in it) went to that line, so pressing Record over a gap looked like a
//      button that did nothing. Only the date's own sentence was said inside the dialog.
//   2. A notification the CA has read has been issued, but its date box took any day; a lot is made before it is recorded, but its manufacture-date box took any day; and an
//      engagement letter or a lot could be made to lapse before it starts: the Expiry boxes hinted (`notBefore`) and the forms sent it.
//   3. The Move stock panel started with today and could be cleared, and a cleared date went to the server as "", which answered in pydantic's words; a quantity such as "1,500"
//      raised inside the service and came back as a generic failure.
//   4. A sentence that is a function of what the boxes hold (a date that is not a day, two dates out of order, a required date missing) was copied into the form's error, where it
//      stayed after the cause was fixed; Close and Cancel were live while a request was out (a lot created behind a Cancel); and the button that opens the statutory dialog still
//      ran from the keyboard behind the overlay, emptying a form that was being sent.
//
// THE RULES (each read from the source, asserted as text, and EXECUTED by the browser drive: scripts/drive/scenarios/dates.mjs, rows `statutory-values-pt-notification`,
// `new-engagement-letter-dates`, `stock-transfer-date`, `stock-lot-dates` and the scenarios named in DRIVE_HOLDS below, which the last test here requires to exist)
//   1. The statutory values `save()` puts NOTHING that is a refusal on the page's message line (every `setMsg(` in it is the success message, whatever its spelling): its refusals
//      are `formError`, rendered inside the dialog with `role="alert"`; the success message and a failed load or removal, which happen on the page, use `msg`. Close and Cancel
//      wait for a Record that is out, each on its own element; `reset()` clears the sentence; the open button does nothing while the form is open.
//   2. The notification date is bounded by today in India and refuses a later day (`notAfter={todayIstISO()}` and `{ afterMax: true }`); the day a notification TAKES EFFECT is
//      not bounded, because a notice made now is for the next April. A notification that names no reference or no day is said through the latch, DERIVED from the boxes.
//   3. A letter's Expiry date and a lot's Expires date are refused in a sentence when they are before the Start / Manufacture date, the sentence DERIVED from the two boxes and
//      said through `useDateRefusal` (once a Create was tried, withdrawn when the dates are in order), and the Expiry box is anchored after its start; a lot's Manufactured date is
//      bounded by today; an expiry is a plan and is not.
//   4. The Move stock panel asks for a cleared date in a sentence (derived, through the latch), refuses a quantity it cannot read in a sentence before sending, and names its date
//      box (`aria-label`); this slice names the lot dialog's two boxes too. The panel and the lot dialog say a date's sentence only through `useDateRefusal`.
//   5. Close and Cancel of the new-letter modal, the lot dialog and the godown dialog wait for a request that is out. The new-letter modal brings its sentence into view (its card
//      scrolls) and words a refusal through the one helper every screen that calls `fetch` itself is meant to use (`errorMessage`).
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));
const SV = "app/settings/statutory-values/page.tsx";
const ENG = "app/engagements/page.tsx";
const LOC = "components/inventory/LocationsAndBatches.tsx";
const DRIVE = "scripts/drive/scenarios/dates.mjs";

/** The text between the opener at `open` (a `(`, `{` or `[`) and its match, string and template literals skipped. */
function balanced(code: string, open: number): string {
  let depth = 0;
  for (let i = open; i < code.length; i++) {
    const c = code[i];
    if (c === '"' || c === "'" || c === "`") { for (i++; i < code.length && code[i] !== c; i++) if (code[i] === "\\") i++; continue; }
    if (c === "(" || c === "{" || c === "[") depth++;
    else if (c === ")" || c === "}" || c === "]") { depth--; if (depth === 0) return code.slice(open + 1, i); }
  }
  return code.slice(open + 1);
}
const bodyOf = (code: string, header: RegExp): string => {
  const m = header.exec(code);
  assert.ok(m, `${header} is no longer in the file`);
  return balanced(code, m.index + m[0].length - 1);
};
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
/** The text of the top-level function `name` (to the next top-level `function`). */
function functionText(code: string, name: string): string {
  const start = code.indexOf(`function ${name}(`);
  assert.ok(start > 0, `function ${name} is no longer in the file`);
  const next = code.indexOf("\nfunction ", start + 10);
  return code.slice(start, next < 0 ? undefined : next);
}
/** The argument of every call to `callee(` in `code`, balanced (so `setMsg({ text, type: "ok" })` is read whole whatever the order of its keys). */
function callsTo(code: string, callee: string): string[] {
  const out: string[] = [];
  for (let at = code.indexOf(`${callee}(`); at >= 0; at = code.indexOf(`${callee}(`, at + 1)) out.push(balanced(code, at + callee.length));
  return out;
}

test("the statutory values dialog says its refusals inside itself, not on the page's message line behind it", () => {
  const code = read(SV);
  const save = bodyOf(code, /async function save\(\) \{/);
  // The RULE: nothing in save() that is a refusal reaches the page's line. Every call to setMsg in it is the success message (or clears the line), in whatever spelling.
  const toThePage = callsTo(save, "setMsg");
  assert.ok(toThePage.length >= 2, "save() no longer clears the page's line and says Recorded: the scan is broken");
  for (const call of toThePage) {
    assert.ok(call.trim() === "null" || (/["']ok["']/.test(call) && !/["']err["']/.test(call)),
      `save() puts something on the page's message line that is not the success message, which the full-screen dialog covers: setMsg(${call.slice(0, 80)})`);
  }
  for (const sentence of ["State must be the two-letter code", "the amounts must be plain figures in rupees, without commas", "The set was refused."]) {
    assert.ok(save.includes(sentence), `save() no longer has the sentence: ${sentence}`);
  }
  assert.ok(code.includes("are all "), "the sentence for a notification that names no source or day no longer exists");
  // …each of them through formError, and the server's refusal and a thrown request too.
  assert.ok((save.match(/setFormError\(/g) ?? []).length >= 5, "save() sets formError fewer times than it has refusals (state, band, server, thrown, and clearing it)");
  assert.match(save, /setFormError\(body\.error \|\| body\.detail \|\| "The set was refused\."\)/, "the server's sentence is not said inside the dialog");
  assert.match(save, /setFormError\(e instanceof Error \? e\.message : "The request failed\."\)/, "a thrown request is not said inside the dialog");
  assert.match(code, /\(refusal\.shown \?\? formError\) &&[\s\S]{0,80}role="alert"/, "the sentence is not rendered inside the dialog");
  // The success message is still the page's (the dialog has closed by then).
  assert.match(save, /setMsg\(\{ type: "ok"/);
  // A notification that names no reference or no day is said through the latch, DERIVED from the three boxes, and goes when they are filled.
  assert.match(code, /const missing = !reference\.trim\(\) \|\| !notifiedOn \|\| !effectiveFrom \? REQUIRED_SENTENCE : null;/, "the sentence for a missing reference or day is not derived from the boxes");
  assert.match(code, /const refusal = useDateRefusal\(dates\.first \?\? missing\);/, "the missing-day sentence is not said through the latch");
  assert.match(save, /if \(dates\.first \?\? missing\) \{\s*refusal\.refuse\(\);\s*return;\s*\}/, "save() does not refuse an unreadable or missing day through the latch");
  assert.doesNotMatch(save, /REQUIRED_SENTENCE/, "save() copies the missing-day sentence into formError again: it stays after the boxes are filled");
  // Close and Cancel wait for a Record that is out, each on its OWN element, so a late answer cannot act on a closed dialog.
  assert.match(code, /<button onClick=\{\(\) => setShowForm\(false\)\} disabled=\{saving\} aria-label="Close"/, "the close button is live while a Record is out");
  assert.match(code, /<button onClick=\{\(\) => setShowForm\(false\)\} disabled=\{saving\}\s+className="px-4 py-1\.5 text-sm text-ps-label/, "Cancel is live while a Record is out");
  // Opened again, the dialog holds nothing of the last one, and the open button does nothing while the form is open (Enter on it from behind the overlay emptied the form).
  assert.match(bodyOf(code, /function reset\(\) \{/), /setFormError\(null\)/, "reset() leaves the last refusal on the form");
  assert.match(code, /onClick=\{\(\) => \{ if \(showForm\) return; reset\(\); refusal\.clear\(\); setShowForm\(true\); \}\}/, "the open button is not guarded while the form is open");
  assert.equal((code.match(/setShowForm\(true\)/g) ?? []).length, 1, "the form is opened from more than one place: each must empty it");
});

test("the notification date is bounded by today and refuses a later day; the day it takes effect is not bounded", () => {
  const code = read(SV);
  const notified = dateInputWith(code, 'id="sv-notified-on"');
  assert.match(notified, /notAfter=\{todayIstISO\(\)\}/, "a notification that has been read has been issued: its date is bounded by today in India");
  assert.match(notified, /\{ afterMax: true \}/, "…and a later day is refused, not merely hinted");
  const effective = dateInputWith(code, 'id="sv-effective-from"');
  assert.doesNotMatch(effective, /notAfter|afterMax|max=/, "the day a notification takes effect may be ahead (a notice made now for the next April)");
});

test("an engagement letter refuses an expiry before its start, in a sentence derived from the boxes, and withdraws it when the dates are in order", () => {
  const code = read(ENG);
  const modal = functionText(code, "CreateEngagementModal");
  const submit = bodyOf(modal, /async function handleSubmit\(e: React\.FormEvent\) \{/);
  assert.match(modal, /const orderProblem = form\.start_date && form\.expiry_date && form\.expiry_date < form\.start_date \? "Expiry date: it cannot be before the start date\." : null;/,
    "the order of the two dates is not a sentence derived from the boxes");
  assert.match(modal, /const refusal = useDateRefusal\(dates\.first \?\? orderProblem\);/, "the order sentence is not said through the latch");
  assert.match(submit, /if \(dates\.first \?\? orderProblem\) \{ refusal\.refuse\(\); return; \}/, "an unreadable date or two dates out of order are not refused before any request");
  assert.doesNotMatch(submit, /setErr\(dates\.first\)|setErr\("Expiry date/, "a date's sentence is copied into the form's error again: it stays after the date is put right");
  // The Expiry box is anchored after the Start box (a short form such as 15/6 is read in the year after it).
  const expiry = dateInputWith(modal, 'aria-label="Expiry date"');
  assert.match(expiry, /anchor=\{form\.start_date \|\| null\} notBefore=\{form\.start_date \|\| null\}/, "the Expiry box is no longer anchored after the Start box");
  // The card scrolls when the window is short: the sentence is brought into view, and rendered.
  assert.match(modal, /sentenceRef\.current\?\.scrollIntoView\?\.\(\{ block: "nearest" \}\)/, "the sentence is not brought into view in a card that scrolls");
  assert.match(modal, /\{sentence && <div ref=\{sentenceRef\}><Callout tone="problem">\{sentence\}<\/Callout><\/div>\}/, "the sentence is not rendered");
  // Close and Cancel wait for a Create that is out, each on its own element; the dialog is opened empty.
  assert.match(modal, /<button onClick=\{onClose\} disabled=\{saving\} aria-label="Close"/, "the header Close is live while a Create is out");
  assert.match(modal, /onClick=\{onClose\}\s+disabled=\{saving\}\s+className="flex-1 rounded-lg border/, "Cancel is live while a Create is out");
  assert.match(modal, /if \(open\) \{\s*clearRefusal\(\);[\s\S]{0,700}setErr\(null\);/, "the dialog is opened again with the last refusal on it");
  // The page words a refusal through the one helper (a validation error's detail is a list: "[object Object]").
  assert.match(code, /if \(!res\.ok\) throw new Error\(await errorMessage\(res\)\);/, "the page's own fetch reads a refusal itself again");
  assert.match(code, /import \{ errorMessage \} from "@\/lib\/api\/index";/);
});

test("a stock lot's manufacture date is bounded by today and its expiry may not precede it; the transfer panel asks for a cleared date and a quantity it can read", () => {
  const code = read(LOC);
  const made = dateInputWith(code, 'aria-label="Manufactured (optional)"');
  assert.match(made, /notAfter=\{todayIstISO\(\)\}/, "a lot is made before it is recorded: the box is bounded by today in India");
  assert.match(made, /\{ afterMax: true \}/, "…and a later day is refused, not merely hinted");
  const expires = dateInputWith(code, 'aria-label="Expires (optional)"');
  assert.doesNotMatch(expires, /afterMax|max=/, "an expiry is a plan and may be any day");
  assert.match(expires, /anchor=\{made \|\| null\} notBefore=\{made \|\| null\}/, "the Expires box is no longer anchored after the Manufactured box");
  assert.ok(code.includes('aria-label="Date the stock moved"'), "the transfer's date box is unnamed again");

  const lot = functionText(code, "BatchModal");
  const transfer = functionText(code, "TransferPanel");
  const save = bodyOf(lot, /async function save\(\) \{/);
  const move = bodyOf(transfer, /async function move\(\) \{/);
  // A lot that lapses before it was made, and a transfer with no date, are sentences DERIVED from the boxes and said through the latch: withdrawn when the boxes are right.
  assert.match(lot, /const orderProblem = made && expires && expires < made \? "Expires: it cannot be before the manufacture date\." : null;/, "the lot's order sentence is not derived from the boxes");
  assert.match(lot, /const refusal = useDateRefusal\(dates\.first \?\? orderProblem\);/);
  assert.match(save, /if \(dates\.first \?\? orderProblem\) \{ refusal\.refuse\(\); return; \}/, "the lot dialog does not refuse dates out of order before any request");
  assert.match(transfer, /const clearedProblem = !when \? "Date: enter the date the stock moved\." : null;/, "a cleared transfer date is not a sentence derived from the box");
  assert.match(transfer, /const refusal = useDateRefusal\(dates\.first \?\? clearedProblem\);/);
  assert.match(move, /if \(dates\.first \?\? clearedProblem\) \{ refusal\.refuse\(\); return; \}/, "the Move stock panel does not refuse a cleared or unreadable date before any request");
  for (const [name, body, action] of [["Move stock panel", transfer, move], ["lot dialog", lot, save]] as const) {
    assert.doesNotMatch(action, /setError\(dates\.first\)/, `the ${name} copies the date's sentence into its error again: it stays after the date is put right`);
    assert.match(body, /\(refusal\.shown \?\? error\) && <Callout tone="problem">\{refusal\.shown \?\? error\}<\/Callout>/, `the ${name} does not render the date's sentence`);
  }
  // A quantity the server cannot read is refused here, in a sentence, before anything is sent.
  assert.match(move, /if \(parseQuantity\(quantity\) === null\) \{ setError\("Quantity: enter a number, like 5 or 12\.5 \(up to three decimals\)\."\); return; \}/,
    "the Move stock panel sends a quantity it cannot read (\"1,500\" raised inside the service and answered 500)");
  // Close and Cancel wait for a Create that is out (the lot dialog and the godown dialog share the screen and the rule).
  for (const [name, body] of [["lot dialog", lot], ["godown dialog", functionText(code, "GodownModal")]] as const) {
    assert.match(body, /<button onClick=\{onClose\} disabled=\{saving\}/, `the ${name}'s Cancel is live while a Create is out`);
  }
});

// Each rule above is held by the text AND by the browser; this is the list of what the drive must hold, so a scenario that is deleted or renamed fails here and not silently.
const DRIVE_HOLDS = [
  "statutory-values-pt-notification", "statutory-values-every-refusal-is-said-inside-the-dialog",
  "statutory-values-a-notification-that-names-no-source-or-date-is-refused-and-the-sentence-goes-when-it-is-filled",
  "statutory-values-a-notification-date-after-today-is-refused-and-an-effective-date-ahead-is-sent",
  "statutory-values-a-notification-date-is-bounded-by-the-indian-day", "statutory-values-close-and-cancel-are-held-while-a-record-is-out",
  "statutory-values-the-form-is-opened-afresh-after-a-refusal", "statutory-values-the-open-button-does-nothing-while-the-form-is-open",
  "new-engagement-letter-dates", "new-engagement-letter-an-expiry-before-the-start-is-refused", "new-engagement-letter-a-short-expiry-is-read-after-the-start",
  "new-engagement-letter-close-and-cancel-are-held-while-a-create-is-out", "new-engagement-letter-is-opened-afresh-after-a-refusal",
  "new-engagement-letter-a-refusal-is-in-view-at-a-short-window", "new-engagement-letter-a-validation-list-from-the-server-is-said-as-a-sentence",
  "stock-transfer-date", "stock-transfer-a-cleared-date-is-asked-for-and-nothing-is-sent",
  "stock-transfer-an-unreadable-date-is-refused-and-the-sentence-goes-when-it-is-put-right", "stock-transfer-a-quantity-that-is-not-a-number-is-refused-and-nothing-is-sent",
  "stock-lot-dates", "stock-lot-a-manufacture-date-after-today-and-an-expiry-before-it-are-refused", "stock-lot-a-short-expiry-is-read-after-the-manufacture-date",
  "stock-lot-a-manufacture-date-is-bounded-by-the-indian-day", "stock-lot-cancel-is-held-while-the-lot-is-being-created", "stock-godown-cancel-is-held-while-the-godown-is-being-created",
];

test("the browser drive holds every claim this guard states as text", () => {
  const drive = fs.readFileSync(path.join(WEB, DRIVE), "utf8");
  const missing = DRIVE_HOLDS.filter((id) => !drive.includes(`id: "${id}"`));
  assert.deepEqual(missing, [], "a scenario this guard relies on is gone from scripts/drive/scenarios/dates.mjs");
});
