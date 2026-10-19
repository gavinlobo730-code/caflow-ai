// An ITR return is marked filed by recording its acknowledgement, never by a "Move to Filed" button, and the screen says
// when the compliance calendar was left open.
//
// Run with:
//   node --experimental-strip-types --test scripts/an-itr-return-is-filed-by-its-acknowledgement-and-the-screen-says-what-the-calendar-did.test.ts
//
// WHAT WAS WRONG
//     The filing screen offered "Move to <next status>" at every status, so at Ready for Filing it read "Move to Filed"
//     beside the acknowledgement form. Pressing it sent a transition to `filed`, which the server accepted: the return went
//     terminal with no acknowledgement number and no filing date, and the acknowledgement could never be recorded after
//     it. The server refuses that transition now; the screen must not offer it. And recording the acknowledgement now closes
//     the calendar's ITR obligation on the server; where it did not, the screen shows the server's own sentence.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const PAGE = path.join("app", "clients", "[id]", "tax", "filing", "page.tsx");

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

/** The page's own `STATUS_ORDER` and `nextStatus`, evaluated: a rule about what the function ANSWERS, not how it is spelled. */
function theScreensWalk(): { order: string[]; next: (current: string) => string | null } {
  const src = code(PAGE);
  const order = /const STATUS_ORDER = (\[[^\]]*\]);/.exec(src);
  assert.ok(order, "STATUS_ORDER is gone");
  const fn = /const nextStatus = \(current: string\) => \{([\s\S]*?)\n  \};/.exec(src);
  assert.ok(fn, "nextStatus is gone");
  const statusOrder = JSON.parse(order[1].replace(/'/g, '"')) as string[];
  const next = new Function("STATUS_ORDER", `return (current) => {${fn[1]}\n};`)(statusOrder) as (c: string) => string | null;
  return { order: statusOrder, next };
}

test("the screen never offers a move to Filed: no status leads to it", () => {
  const { order, next } = theScreensWalk();
  assert.ok(order.includes("filed") && order.length >= 5, "the walk lost a status");
  for (const status of order) {
    assert.notEqual(next(status), "filed", `"Move to Filed" is offered from ${status}`);
  }
  assert.equal(next("ready_for_filing"), null, "Ready for Filing is left by recording the acknowledgement");
});

test("every earlier step is still offered", () => {
  const { next } = theScreensWalk();
  assert.equal(next("draft"), "review");
  assert.equal(next("review"), "partner_review");
  assert.equal(next("partner_review"), "ready_for_filing");
});

test("no call to the transition door names filed", () => {
  assert.doesNotMatch(code(PAGE), /new_status:\s*["']filed["']/);
});

test("the acknowledgement's answer is read through the one helper and shown, and the page decides nothing about the state", () => {
  const src = code(PAGE);
  assert.match(src, /import \{ obligationNote \} from "@\/lib\/compliance\/obligationNote"/);
  assert.match(src, /setCalendarNote\(obligationNote\(res\.data\)\)/, "the server's sentence about the calendar is thrown away");
  assert.match(src, /\{calendarNote && \(/, "the note is never shown");
  assert.doesNotMatch(src, /compliance_obligation/, "the page reads the block directly instead of through the helper");
});
