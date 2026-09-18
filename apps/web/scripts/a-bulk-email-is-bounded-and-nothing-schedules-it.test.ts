// A bulk action that emails a customer is bounded, and nothing schedules one.
//
// Run with:
//   node --experimental-strip-types --test scripts/a-bulk-email-is-bounded-and-nothing-schedules-it.test.ts
//
// WHY THIS EXISTS (SALES-23, plus a defect with no finding)
//     The client Sales tab's bulk actions each loop one HTTP call per selected
//     row. `bulkIssueInvoices` caps at 8 through mapWithConcurrency and its own
//     comment says why: an unbounded Promise.all over a large selection
//     exhausts the browser's connection pool. `bulkSendInvoices` did NOT — and
//     it is strictly heavier, because every send generates and attaches a PDF
//     server-side. The bulk Remind added for SALES-23 is heavier still.
//
//     So the rule is stated here rather than left to the next author noticing
//     the comment two functions down.
//
// AND NOTHING AUTOMATES THE CUSTOMER-FACING ONE
//     An automated reminder cadence is an owner decision already taken the
//     other way: email is a feature and the CA presses the button. The backend
//     has no scheduled customer-facing sender either — the nightly collections
//     job flags the practice's OWN fee invoices internally and emails nobody
//     (migration 405) — and this asserts the browser half, because a
//     setInterval or a "remind everything overdue" button is exactly how such a
//     cadence arrives without a decision.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const SALES = path.join(WEB, "app", "clients", "[id]", "sales", "page.tsx");

/** A function body, by name, with `//` and block comments blanked.
 *
 * Comments go because this file's own explanation names `Promise.all` — the
 * trap every source-scanning guard in this repo has hit: a scan that reads
 * prose forbids explaining the fix.
 */
function bodyOf(src: string, name: string): string {
  const start = src.indexOf(`async function ${name}(`);
  assert.notEqual(start, -1, `${name} not found — this guard has gone vacuous`);
  let depth = 0;
  let i = src.indexOf("{", start);
  const open = i;
  for (; i < src.length; i++) {
    if (src[i] === "{") depth++;
    else if (src[i] === "}" && --depth === 0) break;
  }
  return src
    .slice(open, i + 1)
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/[^\n]*/g, "$1");
}

// Every bulk action on this screen that sends an EMAIL. Both hit one endpoint
// per selected row and both attach a server-generated PDF.
const EMAILING_BULK_ACTIONS = ["bulkSendInvoices", "bulkRemindInvoices"];

test("every bulk action that emails a customer is concurrency-bounded", () => {
  const src = fs.readFileSync(SALES, "utf8");
  for (const name of EMAILING_BULK_ACTIONS) {
    const body = bodyOf(src, name);
    assert.match(body, /mapWithConcurrency\(/,
      `${name} loops one email per row; it must cap in-flight requests the way `
      + `bulkIssueInvoices does, not run an unbounded Promise.all`);
    assert.doesNotMatch(body, /Promise\.all\(/,
      `${name} used Promise.all over the whole selection — the exact pattern `
      + `bulkIssueInvoices' own comment warns against, on the heavier action`);
  }
});

test("bulk Remind only reaches invoices the screen already calls overdue", () => {
  // POST /remind 422s on anything not overdue, so sending them would be a wall
  // of errors. isOverdueForUi is the SAME predicate the row menu uses to decide
  // whether to offer Remind at all — so what is offered in bulk and what is
  // offered per row cannot disagree.
  const body = bodyOf(fs.readFileSync(SALES, "utf8"), "bulkRemindInvoices");
  assert.match(body, /isOverdueForUi/,
    "bulk Remind must filter on the screen's own overdue predicate");
  assert.match(body, /\/remind/, "vacuity floor: it must still call the endpoint");
});

test("nothing in the browser schedules a customer-facing reminder", () => {
  // Walk app/ and components/ for a timer wrapped around the reminder endpoint.
  // The endpoint is the thing to look for, not the word "reminder": a Timeline
  // entry and a settings screen both mention reminders and neither sends one.
  const offenders: string[] = [];
  const walk = (dir: string) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, e.name);
      if (e.isDirectory()) { if (e.name !== "node_modules") walk(full); continue; }
      if (!/\.tsx?$/.test(e.name)) continue;
      const src = fs.readFileSync(full, "utf8")
        .replace(/\/\*[\s\S]*?\*\//g, "")
        .replace(/(^|[^:])\/\/[^\n]*/g, "$1");
      if (!src.includes("/remind")) continue;
      if (/setInterval|setTimeout\s*\([^)]*remind/i.test(src)) {
        offenders.push(path.relative(WEB, full));
      }
    }
  };
  for (const d of ["app", "components"]) walk(path.join(WEB, d));
  assert.deepEqual(offenders, [],
    "a timer around the reminder endpoint is an automated cadence arriving "
    + "without the decision that authorises one: " + offenders.join(", "));
});
