// A screen that keeps its data in localStorage says so, on the screen and on
// the card that leads to it.
//
// Run with:
//   node --experimental-strip-types --test scripts/a-browser-only-screen-says-so.test.ts
//
// WHY THIS EXISTS (ACC-06)
//     /accounting/recurring, /accounting/budget and /accounting/retainer store
//     everything the CA enters in this browser's localStorage — no table, no
//     RLS, no sharing, no scheduler. A partner who sets a recurring template up
//     on their laptop finds nothing on the office machine; clearing site data
//     loses the lot.
//
//     None of that was stated anywhere, and the hub card actively said the
//     opposite: "Automate monthly, quarterly & yearly entries", when nothing
//     posts a due template. A CA had every reason to believe the firm's
//     recurring journals were configured.
//
// WHAT THIS IS NOT
//     Not the fix. Firm-scoped tables with RLS and the scheduler posting drafts
//     is the fix, and it is a migration. The finding names this notice as the
//     interim in its own words. The rule this test states is the durable half:
//     a screen whose only store is localStorage must SAY SO, so a fourth one
//     cannot appear quietly.
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

test("the three known browser-only screens are exactly these three", () => {
  // If a fourth appears, this fails and whoever added it decides: is it a
  // per-viewer convenience (allowlist it with the reason) or is it somebody's
  // work (it needs the notice, and really it needs a table).
  const found = pagesTouchingLocalStorage().filter((p) => !(p in CONVENIENCE_ONLY));
  assert.deepEqual(found, [
    "app/accounting/budget/page.tsx",
    "app/accounting/recurring/page.tsx",
    "app/accounting/retainer/page.tsx",
  ]);
  // Every allowlist entry must still be a page that exists, so a deleted
  // screen cannot leave a stale exemption behind for the next one to inherit.
  for (const rel of Object.keys(CONVENIENCE_ONLY)) {
    assert.equal(fs.existsSync(path.join(WEB, rel)), true, `${rel} is allowlisted but gone`);
  }
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

test("each of them renders the notice", () => {
  for (const p of ["app/accounting/budget/page.tsx",
                   "app/accounting/recurring/page.tsx",
                   "app/accounting/retainer/page.tsx"]) {
    const src = code(read(p));
    assert.match(src, /<BrowserOnlyNotice/, `${p} does not say where its data lives`);
    assert.match(src, /import BrowserOnlyNotice from "@\/components\/BrowserOnlyNotice"/, p);
  }
});

test("there is ONE notice, not three copies of a sentence", () => {
  const c = code(read("components/BrowserOnlyNotice.tsx"));
  assert.match(c, /Saved in this browser only/);
  // The sentence must not be spelled out again on any page.
  for (const p of ["app/accounting/budget/page.tsx",
                   "app/accounting/recurring/page.tsx",
                   "app/accounting/retainer/page.tsx"]) {
    assert.doesNotMatch(code(read(p)), /Saved in this browser only/,
      `${p} carries its own copy of the sentence`);
  }
});

test("the notice states the three things that are actually lost", () => {
  const c = code(read("components/BrowserOnlyNotice.tsx"));
  assert.match(c, /Nobody else in the\s+firm can see them/);
  assert.match(c, /not be here on another device/);
  assert.match(c, /clearing site data removes them permanently/);
});

test("each screen also names what IT specifically does not do", () => {
  // The generic sentence is the same everywhere; the second one is not, and it
  // is the one that stops a CA relying on the wrong thing.
  const recurring = code(read("app/accounting/recurring/page.tsx"));
  assert.match(recurring, /Nothing posts a due template/);
  const budget = code(read("app/accounting/budget/page.tsx"));
  assert.match(budget, /ACTUALS beside them are read from the ledger and are real/);
  const retainer = code(read("app/accounting/retainer/page.tsx"));
  assert.match(retainer, /not a sales invoice in the books/);
});

test("the hub card no longer promises automation it cannot deliver", () => {
  const hub = code(read("app/accounting/page.tsx"));
  assert.doesNotMatch(hub, /Automate monthly, quarterly & yearly entries/,
    "the Recurring card promised automation; nothing posts a due template");
  // All three cards carry the flag, and the flag is rendered.
  assert.equal((hub.match(/notShared: true/g) ?? []).length, 3);
  assert.match(hub, /card\.notShared && \(/);
  assert.match(hub, /Saved in this browser only — not shared with the firm/);
});
