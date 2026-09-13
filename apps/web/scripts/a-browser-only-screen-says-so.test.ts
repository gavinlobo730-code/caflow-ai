// No screen keeps the CA's work in this browser, and the ones that did cannot
// come back.
//
// Run with:
//   node --experimental-strip-types --test scripts/a-browser-only-screen-says-so.test.ts
//
// WHAT THIS WAS, AND WHAT IT IS NOW (ACC-06)
//     `/accounting/recurring`, `/accounting/budget` and `/accounting/retainer`
//     stored everything the CA entered in localStorage — no table, no RLS, no
//     sharing, no scheduler. This file began as the honest interim: it asserted
//     that each of them SAID SO, on the screen and on the hub card, so a CA
//     could not believe the firm's recurring journals were configured when they
//     were one laptop's private note.
//
//     All three are on the database now — `recurring_journal_templates`
//     (migration 377), `account_budgets` (376), and `billing_schedules`, which
//     was already built and had no caller. So the file inverts: it no longer
//     checks that a warning is present, it checks that none is NEEDED.
//
// THE RULE IT STATES, WHICH IS THE DURABLE HALF
//     A page under app/ may reach localStorage only for a per-viewer
//     convenience — a remembered tab, a dismissed hint, a few seconds of state
//     between two pages of one flow. Anything that is the user's WORK belongs
//     in a table. A fourth such screen fails here rather than appearing
//     quietly, and MOVED_TO_THE_DATABASE stops the first three regressing.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");

function read(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8");
}
function code(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/^\s*\/\/.*$/gm, " ");
}

/** Every page under app/ that reaches localStorage at all. */
function pagesTouchingLocalStorage(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (e.name === "node_modules" || e.name === ".next" || e.name.startsWith(".")) continue;
      const p = path.join(dir, e.name);
      if (e.isDirectory()) walk(p);
      else if (e.name === "page.tsx" && /localStorage\.(getItem|setItem)/.test(code(fs.readFileSync(p, "utf8")))) {
        out.push(path.relative(WEB, p));
      }
    }
  };
  walk(path.join(WEB, "app"));
  return out.sort();
}

// Screens that read or write localStorage but are NOT storing the user's work
// there — a remembered tab, a collapsed panel, a dismissed hint. May only
// grow with a reason written beside the entry.
const CONVENIENCE_ONLY: Record<string, string> = {
  "app/ai-assistant/page.tsx":
    "A chat transcript with a TTL, purged on expiry. Nothing depends on it and " +
    "every answer is reproducible by asking again — losing it costs a scroll, " +
    "not a record.",
  "app/notifications/whatsapp/page.tsx":
    "The last 20 messages SENT FROM THIS BROWSER, as a convenience for reusing " +
    "one. It is not the delivery record and nothing reads it back: the send " +
    "itself goes through the API. ⚠️ It does read like a log, and if this " +
    "screen ever becomes the place a CA checks whether a reminder went out, " +
    "it needs a table — a per-browser list would then be answering a question " +
    "about the firm with one machine's memory.",
  "app/onboarding/page.tsx":
    "Reads the handover written by signup below and REMOVES it when onboarding " +
    "finishes. A few seconds of state between two pages of one flow.",
  "app/signup/page.tsx":
    "Writes that handover. Same flow, same seconds.",
};

// The three screens that WERE browser-only. Each must stay on the database,
// and none may keep a warning that is no longer true — a CA who reads a false
// warning stops believing the next one.
const MOVED_TO_THE_DATABASE: Record<string, string> = {
  "app/accounting/budget/page.tsx":
    "ACC-06. `account_budgets` (migration 376) holds the figures and " +
    "GET /api/accounting/budgets serves them with the actuals read once from " +
    "account_period_balances. The old screen ALSO computed those actuals in " +
    "the browser, firm-wide, with four unpaged reads of journal_lines — " +
    "PostgREST truncates at ~1000 rows and says nothing, so every variance on " +
    "a real client was wrong.",
  "app/accounting/retainer/page.tsx":
    "ACC-06, and this one was never a missing feature. `billing_schedules` " +
    "(migration 073) has carried arrangement IN ('retainer','one_time'," +
    "'package') since 2024, billing_service generates a DRAFT invoice per " +
    "schedule per period THROUGH THE SALES ENGINE, and " +
    "api.billing.listSchedules/createSchedule/generate were already in the " +
    "frontend client with no callers. What the screen did instead was mint a " +
    "document headed TAX INVOICE under the firm's own GSTIN, numbered from a " +
    "browser-local counter (so two devices collide and Rule 46(b) cannot " +
    "hold) and taxed at a hardcoded CGST 9% + SGST 9% (so wrong for every " +
    "inter-state client), with a Print button — and saved it to localStorage.",
  "app/accounting/recurring/page.tsx":
    "ACC-06, the last of the three and the only genuine build. " +
    "`recurring_journal_templates` (migration 377), " +
    "services/recurring_journal_service.py and the daily sweep replace a " +
    "browser store, a browser cadence engine, and a 'Post Now' button that " +
    "posted STRAIGHT TO THE LEDGER dated today rather than the occurrence.",
};

test("no page under app/ stores the user's work in this browser", () => {
  // If a fourth appears, this fails and whoever added it decides: is it a
  // per-viewer convenience (allowlist it with the reason) or is it somebody's
  // work (it needs a table)?
  const found = pagesTouchingLocalStorage().filter((p) => !(p in CONVENIENCE_ONLY));
  assert.deepEqual(found, []);
  // Every allowlist entry must still be a page that exists, so a deleted
  // screen cannot leave a stale exemption behind for the next one to inherit.
  for (const rel of Object.keys(CONVENIENCE_ONLY)) {
    assert.equal(fs.existsSync(path.join(WEB, rel)), true, `${rel} is allowlisted but gone`);
  }
});

test("a screen already moved onto the database does not come back", () => {
  for (const [rel, why] of Object.entries(MOVED_TO_THE_DATABASE)) {
    const src = code(read(rel));
    assert.doesNotMatch(src, /localStorage\.(getItem|setItem)/,
      `${rel} is storing work in this browser again — ${why}`);
    assert.doesNotMatch(src, /BrowserOnlyNotice/,
      `${rel} keeps a warning that is no longer true`);
  }
});

test("the browser-only notice is gone, not merely unused", () => {
  // It was the honest interim while three screens had nowhere else to put
  // their data. With none left, keeping the component is an invitation to
  // write a fourth such screen and label it rather than fix it.
  assert.equal(fs.existsSync(path.join(WEB, "components/BrowserOnlyNotice.tsx")), false,
    "BrowserOnlyNotice has no users — delete it rather than leaving it to hand");
});

test("the team page stores no permissions of its own", () => {
  // A DEFECT WITH NO FINDING, found by this sweep. app/team/page.tsx wrote a
  // member→module→boolean map into localStorage and rendered it as an access
  // matrix headed "Toggle access per member per module. Changes are saved
  // instantly. Overrides the role default for that individual."
  //
  // Every clause was false: the map reached no other user, device or server;
  // core/permissions.py has no per-member override concept; and rbac() decides
  // every request from the ROLE alone. A Partner who unticked Payroll for an
  // Executive believed they had removed access, and had not.
  //
  // It also carried its own ROLE_DEFAULTS, which had drifted in the direction
  // that matters: an Executive was shown as reaching Clients and Tasks only,
  // when the backend grants them Accounting, GST, Income Tax, MCA, Reports and
  // TDS besides.
  const src = code(read("app/team/page.tsx"));
  assert.doesNotMatch(src, /localStorage\.setItem/,
    "the team page must write no permissions to this browser");
  assert.doesNotMatch(src, /localStorage\.getItem/,
    "and must read none back");
  // MISSED ON THE FIRST PASS, twice, and both misses are the same shape: an
  // assertion that a call EXISTS somewhere in the file, when the file has two
  // components and only one of them needed to keep it.
  //
  //   • `localStorage.removeItem` stayed inside purgeLegacyOverrides even
  //     after nothing called it, so a browser kept its stale overrides.
  //   • `api.identity.roleMatrix()` stayed in RolePermissionsCard after the
  //     matrix grid stopped asking, so the grid could render an empty object
  //     and show every member as reaching nothing.
  //
  // Both are pinned to the CALL SITE now, and the matrix to both components.
  assert.match(src, /localStorage\.removeItem/);
  assert.match(src, /purgeLegacyOverrides\(firmId\);/,
    "a browser carrying old overrides must have them purged, so nobody sees a " +
    "member marked 'custom' for a restriction that never existed");
  assert.doesNotMatch(src, /const ROLE_DEFAULTS/,
    "the browser copy of core/permissions.py is back");
  assert.equal((src.match(/api\.identity\.roleMatrix\(\)/g) ?? []).length, 2,
    "BOTH the access grid and the role-permissions card must ask the server; " +
    "one of them falling back to a literal is how the copy came back last time");
  // And the grid must not invite a click it cannot honour.
  assert.doesNotMatch(src, /onChange=\{\(\) => togglePermission/);
  assert.match(src, /There is no per-person override/,
    "the screen must say access is decided by role");
});

test("no hub card claims to be browser-only any more", () => {
  const hub = code(read("app/accounting/page.tsx"));
  assert.doesNotMatch(hub, /Automate monthly, quarterly & yearly entries/,
    "the Recurring card promised automation before anything posted a due template");
  assert.equal((hub.match(/notShared: true/g) ?? []).length, 0,
    "all three screens are on the database; a card saying otherwise is a false warning");
});

test("the retainer screen raises a real draft, not a rendered one", () => {
  // The specific things the old screen did, each forbidden by name because
  // each was independently wrong.
  const src = code(read("app/accounting/retainer/page.tsx"));
  assert.doesNotMatch(src, /TAX INVOICE/,
    "the screen must not render a tax invoice — POST /api/billing/schedules/" +
    "{id}/generate raises a real draft through the sales engine, and the CA " +
    "issues it from Billing");
  assert.doesNotMatch(src, /window\.print/,
    "and must not offer to print one");
  assert.doesNotMatch(src, /\bcgst\b|\bsgst\b/i,
    "GST on the practice's own invoice is computed by the sales engine from " +
    "the place of supply — a hardcoded CGST 9% + SGST 9% is the wrong tax for " +
    "every inter-state client");
  assert.doesNotMatch(src, /generateInvoiceNo/,
    "the invoice number comes from the firm's own series, not a browser " +
    "counter — CGST Rule 46(b) requires it unique for a financial year");
  assert.match(src, /api\.billing\.generate\(/);
  assert.match(src, /api\.billing\.listSchedules\(/);
});

test("the recurring screen generates a draft and computes no dates", () => {
  const src = code(read("app/accounting/recurring/page.tsx"));
  // The old "Post Now" wrote status: "posted" straight to the ledger, dated
  // TODAY rather than the occurrence — a rent journal due on the 1st and
  // remembered on the 7th landed on the 7th.
  assert.doesNotMatch(src, /status:\s*["']posted["']/,
    "this screen must never ask for a posted entry — generation produces a " +
    "DRAFT the CA reviews");
  assert.doesNotMatch(src, /createJournalEntry/,
    "it goes through /api/recurring-journals, which records the occurrence " +
    "and cannot generate the same one twice");
  // `nextDueDate()` and `isDueToday()` were a second cadence engine in the
  // browser, free to disagree with the one the recurring invoices use.
  assert.doesNotMatch(src, /function nextDueDate|function isDueToday/,
    "the cadence is domain/recurrence.py's answer, shared with the recurring " +
    "invoices — not a copy in the browser");
  assert.match(src, /api\.recurringJournals\.(list|generate|runDue)\(/);
});
