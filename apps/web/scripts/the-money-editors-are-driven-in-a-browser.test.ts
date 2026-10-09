// THE MONEY EDITORS ARE DRIVEN IN A BROWSER, NIGHTLY, AND NOTHING WAITS ON IT (PRE-A-015).
//   node --experimental-strip-types --test scripts/the-money-editors-are-driven-in-a-browser.test.ts
//
// ─────────────────────────────────────────────────────────────────────────────
// WHY THIS FILE EXISTS
// ─────────────────────────────────────────────────────────────────────────────
// Every guard for the money editors (the repeat-click guard, the row keyboard, the unsent drafts, the typed
// dates) is a SOURCE guard, and CLAUDE.md says at each of them that nothing was clicked because there is no
// browser. `scripts/driveMoneyEditors.mjs` is the browser: it serves the smoke build, signs in, and drives the
// editors a CA posts money through, and the first time it ran it found eight places where two clicks in one tick
// sent two requests (the Issue of an invoice and of each kind of note, the Receive of a bill, the Delete Draft of
// an invoice and of a bill) and a reversal reason the screen collected and threw away. All eight had passed
// every source guard.
//
// This file needs no Chromium and cannot tell whether the drive PASSES. What it holds is that the drive can
// neither be quietly removed nor quietly stop looking at what it was written to look at:
//
//   1. it is not a trigger of its own, a required check, or a reason for Playwright to join the package;
//   2. `pnpm test` can never pick it up (node's runner takes any `*.test.*`, `test-*` file or `test` directory);
//   3. its scenarios are discovered, not listed, every module has the shape the runner needs, and the six groups
//      the finding names are all present;
//   4. it signs in as the SAME person the walk does (the four identity objects), so the two cannot drift;
//   5. the date scenarios run under three browser contexts that straddle UTC, with the clock pinned;
//   6. every date field it drives is a real `DateInput` in the editor it says, and an editor it drives cannot
//      gain a date field the drive does not know about without this failing;
//   7. it fails a scenario on everything the walk fails a route on, and on any native dialog.
//
// NEGATIVE CONTROLS (measured, in the commit message): add a push trigger; add `@playwright/test` to
// package.json; name a scenario file `test-x.mjs`; change one value of the drive's FAKE_USER; add a DateInput
// to the journal editor. Each fails one test here.
import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import ts from "typescript";
import * as fixtures from "./drive/fixtures.mjs";
import { TZ_MATRIX } from "./drive/kit.mjs";

const WEB = join(import.meta.dirname, "..");
const REPO = join(WEB, "..", "..");
const read = (p: string) => readFileSync(p, "utf8");
const DRIVE = join(WEB, "scripts", "driveMoneyEditors.mjs");
const DRIVE_DIR = join(WEB, "scripts", "drive");
const SCENARIO_DIR = join(DRIVE_DIR, "scenarios");
const WORKFLOW = join(REPO, ".github", "workflows", "smoke-walk.yml");

function allFiles(dir: string, out: string[] = []): string[] {
  for (const e of readdirSync(dir)) {
    const p = join(dir, e);
    if (statSync(p).isDirectory()) allFiles(p, out);
    else out.push(p);
  }
  return out;
}

// ═════════════════════════════════════════════════════════════════════════════
// 1. NOT A TRIGGER, NOT A REQUIRED CHECK, NOT A DEPENDENCY
// ═════════════════════════════════════════════════════════════════════════════

test("the drive is not a trigger, a required check or a reason for Playwright to be a dependency", () => {
  const text = read(WORKFLOW);
  const on = text.slice(text.indexOf("\non:"), text.indexOf("\njobs:"));
  assert.doesNotMatch(on, /^\s+push:/m, "a push trigger makes the nightly a check somebody waits on");
  assert.doesNotMatch(on, /^\s*paths(-ignore)?:/m);
  const pkg = JSON.parse(read(join(WEB, "package.json")));
  const deps = { ...pkg.dependencies, ...pkg.devDependencies };
  for (const name of ["@playwright/test", "playwright", "playwright-core", "@axe-core/playwright"]) {
    assert.equal(name in deps, false, `${name} is the walk's job's dependency, never the product's`);
  }
  assert.equal("drive" in pkg.scripts || "test:drive" in pkg.scripts, false,
    "a package script for the drive would put a browser run next to `pnpm test`");
});

// ═════════════════════════════════════════════════════════════════════════════
// 2. `pnpm test` NEVER RUNS IT
// ═════════════════════════════════════════════════════════════════════════════

test("nothing under scripts/drive can be picked up by node's test runner", () => {
  // `node --test` with no arguments takes every `*.test.*`, `*-test.*`, `*_test.*` and `test-*` file and
  // every file under a directory called `test`. The drive needs a browser; run by `pnpm test` it would fail
  // every pull request for want of one.
  const files = [DRIVE, ...allFiles(DRIVE_DIR)];
  assert.ok(files.length >= 8, `only ${files.length} drive files found`);
  for (const f of files) {
    const rel = relative(WEB, f);
    const base = f.split("/").pop() as string;
    assert.doesNotMatch(base, /\.test\.|[-_]test\.|^test[-.]/, `${rel} would be run by \`pnpm test\``);
    assert.equal(rel.split("/").includes("test"), false, `${rel} sits under a directory called test`);
  }
});

// ═════════════════════════════════════════════════════════════════════════════
// 3. THE SCENARIOS
// ═════════════════════════════════════════════════════════════════════════════

const GROUPS_THE_FINDING_NAMES = ["double-dispatch", "keyboard", "drafts", "dates", "delete-and-prompt", "escape"];

test("scenarios are discovered from their directory, so a file cannot be written and forgotten", () => {
  const src = read(DRIVE);
  assert.match(src, /readdirSync\(SCENARIO_DIR\)/, "the runner no longer discovers scenario modules from the directory");
  assert.match(src, /SCENARIO_DIR = path\.join\(__dirname, "drive", "scenarios"\)/);
});

test("every scenario module has the shape the runner needs, ids are unique and the six groups are all present", () => {
  const files = readdirSync(SCENARIO_DIR).filter((f) => f.endsWith(".mjs"));
  assert.ok(files.length >= 6, `only ${files.length} scenario files`);
  const groups = new Map<string, number>();
  const ids = new Set<string>();
  for (const f of files) {
    const text = read(join(SCENARIO_DIR, f));
    const g = /export const group = "([a-z-]+)";/.exec(text);
    assert.ok(g, `${f} must export \`group\` as a plain string`);
    assert.match(text, /export const scenarios = /, `${f} must export \`scenarios\``);
    groups.set(g![1], (groups.get(g![1]) ?? 0) + 1);
    // Scenario ids are the string after `id:` (a literal) or built from a table; the table-built ones are
    // checked by the runner at load (a duplicate id would overwrite in the report) — here only literals.
    for (const m of text.matchAll(/^\s+id: "([a-z0-9-]+)",\s*$/gm)) {
      const key: string = `${g![1]}/${m[1]}`;
      assert.equal(ids.has(key), false, `scenario id ${key} appears twice`);
      ids.add(key);
    }
  }
  for (const want of GROUPS_THE_FINDING_NAMES) assert.ok(groups.has(want), `the drive has no \`${want}\` scenarios`);
  assert.ok(ids.size >= 20, `only ${ids.size} literal scenario ids: the drive has been hollowed out`);
});

test("the double-dispatch group presses twice inside ONE tick, and counts writes on the stub, not on the button", () => {
  const src = read(join(SCENARIO_DIR, "doubleDispatch.mjs"));
  assert.match(src, /sameTickDouble\(/);
  assert.match(src, /expectWrites\(/);
  const kit = read(join(DRIVE_DIR, "kit.mjs"));
  // The two clicks are dispatched inside a single page.evaluate. Playwright's own dblclick() waits for the page
  // between the events and so tests a slower person than the one who posted eleven journals.
  assert.match(kit, /\.evaluate\(\(el\) => \{ el\.click\(\); el\.click\(\); \}/, "the double press is no longer one tick");
  assert.doesNotMatch(src, /\.dblclick\(/, "dblclick() waits between the events: it is not the defect");
  // Every controls the finding names is driven.
  for (const control of ["Post Entry", "Save & Issue", "Record Payment", "Issue", "Receive", "Delete"]) {
    assert.ok(src.includes(control), `the double-dispatch group no longer drives ${control}`);
  }
});

test("the stub keeps a log of every write and a quiet check that starts counting when it is asked", () => {
  const stub = read(join(DRIVE_DIR, "stub.mjs"));
  assert.match(stub, /writes\.push\(\{[^}]*via: "api"/, "the stub no longer records API writes");
  assert.match(stub, /writes\.push\(\{[^}]*via: "postgrest"/, "the stub no longer records PostgREST writes");
  // "Exactly one" is only a claim if the first write has had time to arrive: `quiet` counts from the CALL.
  const quiet = /async quiet\([^)]*\)\s*\{([\s\S]*?)\n    \},/.exec(stub);
  assert.ok(quiet, "the stub has no `quiet`");
  assert.match(quiet![1], /touch\(\);/, "quiet() must restart its clock when it is called, or it counts zero writes before the first arrives");
});

// ═════════════════════════════════════════════════════════════════════════════
// 4. THE SAME PERSON THE WALK SIGNS IN AS
// ═════════════════════════════════════════════════════════════════════════════

function walkIdentity(): Record<string, unknown> {
  const text = read(join(WEB, "scripts", "smoke-walk.mjs"));
  const sf = ts.createSourceFile("smoke-walk.mjs", text, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
  const wanted = ["FAKE_USER", "FAKE_SESSION", "FAKE_USERS_ROW", "FAKE_FIRM_ROW"];
  const decls: string[] = [];
  for (const stmt of sf.statements) {
    if (!ts.isVariableStatement(stmt)) continue;
    for (const d of stmt.declarationList.declarations) {
      if (ts.isIdentifier(d.name) && wanted.includes(d.name.text)) decls.push(stmt.getText(sf));
    }
  }
  assert.equal(decls.length, wanted.length, "the walk no longer declares its four identity objects at the top level");
  return new Function(`${decls.join("\n")}\nreturn { ${wanted.join(", ")} };`)() as Record<string, unknown>;
}

test("the drive signs in as exactly the person, user row and firm the walk does", () => {
  const walk = walkIdentity();
  for (const name of ["FAKE_USER", "FAKE_SESSION", "FAKE_USERS_ROW", "FAKE_FIRM_ROW"]) {
    assert.deepEqual((fixtures as Record<string, unknown>)[name], walk[name],
      `${name} differs from smoke-walk.mjs: the two would sign in as different people, and a guard chain the walk ` +
      "satisfies (a users row with a firm, a firms.name) could send the drive to the onboarding wizard");
  }
});

// ═════════════════════════════════════════════════════════════════════════════
// 5. THE DATE SCENARIOS' CONTEXTS AND CLOCK
// ═════════════════════════════════════════════════════════════════════════════

/** Minutes east of UTC on a given instant, from the zone's own rules. */
function offsetMinutes(timeZone: string, at: Date): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).formatToParts(at);
  const get = (t: string) => Number(parts.find((p) => p.type === t)!.value);
  const asUtc = Date.UTC(get("year"), get("month") - 1, get("day"), get("hour"), get("minute"));
  return Math.round((asUtc - Math.floor(at.getTime() / 60000) * 60000) / 60000);
}

test("the date scenarios run under three contexts that straddle UTC, at a clock where today is one day in all three", () => {
  assert.equal(TZ_MATRIX.length, 3);
  const at = new Date(fixtures.NOW);
  const offsets = TZ_MATRIX.map((c) => offsetMinutes(c.timezoneId, at));
  assert.ok(offsets.some((o) => o < 0), `no context is west of UTC at the pinned clock: ${offsets}`);
  assert.ok(offsets.some((o) => o >= 12 * 60), `no context is far east of UTC (UTC+12 or more) at the pinned clock: ${offsets}`);
  assert.equal(new Set(TZ_MATRIX.map((c) => c.locale)).size, 3, "the three contexts should differ in locale too");
  // The point of the pinned instant: the browser's "today" is the same calendar day in every zone, so a
  // difference between the contexts is a defect in a field and never a day the clock happened to fall on.
  const days = TZ_MATRIX.map((c) => new Intl.DateTimeFormat("en-CA", { timeZone: c.timezoneId }).format(at));
  assert.equal(new Set(days).size, 1, `today differs between the contexts: ${days.join(", ")}`);
  const dates = read(join(SCENARIO_DIR, "dates.mjs"));
  assert.match(dates, /contexts: TZ_MATRIX/, "the date scenarios do not run under the matrix");
  // FY 2026-27 at the pinned clock, so that `15/1` has one answer: January of the NEXT year.
  assert.match(fixtures.NOW, /^2026-(0[4-9]|1[0-2])-/, "the pinned clock should be inside April-December so 15/1 is next January");
  assert.match(dates, /15\/01\/2027/, "the short-form claim (15/1 is 15 January of the next year) is no longer asserted");
});

test("the runner pins the clock for every scenario and applies out/_headers as Cloudflare would", () => {
  const src = read(DRIVE);
  assert.match(src, /context\.clock\.setFixedTime\(new Date\(NOW\)\)/, "scenarios no longer run at a pinned clock");
  assert.match(src, /parseHeadersFile\(/, "out/_headers is not applied");
  assert.match(src, /securitypolicyviolation/, "a policy violation no longer fails a scenario");
  assert.match(src, /out\/_headers does not exist/, "a build without out/_headers is no longer refused");
  assert.match(src, /_redirects/, "the export is no longer served through its own _redirects rules");
});

// ═════════════════════════════════════════════════════════════════════════════
// 6. THE DATE FIELDS IT DRIVES ARE REAL, AND NONE IS ADDED UNSEEN
// ═════════════════════════════════════════════════════════════════════════════

/** The DateInput elements of a file, each as its `id` or its `aria-label`. */
function dateInputsOf(rel: string): string[] {
  const text = read(join(WEB, rel));
  const out: string[] = [];
  for (const m of text.matchAll(/<DateInput\b([\s\S]*?)(?:\/>|>)/g)) {
    const attrs = m[1];
    const id = /\bid="([^"]+)"/.exec(attrs)?.[1];
    const label = /\baria-label="([^"]+)"/.exec(attrs)?.[1];
    out.push(id ? `#${id}` : label ? `[${label}]` : "(unnamed)");
  }
  return out;
}

/** What the date scenarios drive, per editor file: the fields by id or aria-label. */
const DRIVEN: Record<string, string[]> = {
  "components/journal/JournalEditor.tsx": ["#je-date"],
  "components/invoices/InvoiceEditor.tsx": ["#inv-date", "#inv-due-date"],
  "components/purchases/PurchaseBillEditor.tsx": ["#bill-date", "#bill-due-date"],
  "components/invoices/InvoiceViewDrawer.tsx": ["[Payment date]", "[Credit note date]", "[Debit note date]"],
  "components/purchases/PurchaseBillViewDrawer.tsx": ["[Payment date]", "[Debit note date]", "[Credit note date]"],
};

/** Date fields in those same editors that the drive does NOT yet drive, each with why. A table that can only
 *  shrink: a field added to a driven editor must get a scenario row or be named here. */
const NOT_YET_DRIVEN: Record<string, Record<string, string>> = {
  "components/invoices/InvoiceEditor.tsx": { "#inv-sb-date": "the shipping bill date of an export invoice; shown only for exports (second slice)" },
  "components/purchases/PurchaseBillEditor.tsx": { "#bill-15ca-date": "the Form 15CA date; shown only for a foreign payee (second slice)" },
};

test("every date field the drive types into is a real DateInput in the editor it names", () => {
  const dates = read(join(SCENARIO_DIR, "dates.mjs"));
  for (const [file, fields] of Object.entries(DRIVEN)) {
    const have = dateInputsOf(file);
    for (const f of fields) {
      assert.ok(have.includes(f), `${file} no longer has a DateInput ${f}: the drive would be typing into nothing`);
      const needle = f.startsWith("#") ? f : f.slice(1, -1);
      assert.ok(dates.includes(needle), `the date scenarios never mention ${needle}, so ${f} of ${file} is not driven`);
    }
  }
});

test("a driven editor cannot gain a date field the drive does not know about", () => {
  for (const [file, driven] of Object.entries(DRIVEN)) {
    const known = new Set([...driven, ...Object.keys(NOT_YET_DRIVEN[file] ?? {})]);
    const have = dateInputsOf(file);
    const unknown = have.filter((f) => !known.has(f));
    assert.deepEqual(unknown, [],
      `${file} has date field(s) the drive does not drive and the table does not name: ${unknown.join(", ")}. Add a row ` +
      "to EDITORS in scripts/drive/scenarios/dates.mjs (the claims are the same for every date), or name it in NOT_YET_DRIVEN with why.");
    // …and the table cannot name a field that has gone.
    for (const named of Object.keys(NOT_YET_DRIVEN[file] ?? {})) {
      assert.ok(have.includes(named), `${file}: ${named} is named as not yet driven but is not a DateInput there`);
    }
  }
});

// ═════════════════════════════════════════════════════════════════════════════
// 7. WHAT FAILS A SCENARIO
// ═════════════════════════════════════════════════════════════════════════════

test("a scenario fails on an uncaught exception, a console error, a CSP violation, a foreign host and a native dialog", () => {
  const src = read(DRIVE);
  assert.match(src, /page\.on\("pageerror"/);
  assert.match(src, /m\.type\(\) !== "error"/, "a console error no longer counts");
  assert.match(src, /__cspViolations/);
  assert.match(src, /escaped\.add\(/, "a request for a host that is not the stub is no longer recorded");
  assert.match(src, /exit\(failed\.length \|\| escaped\.size \? 1 : 0\)/, "a foreign-host request no longer fails the run");
  // The one native dialog allowed is the browser's own leave-site prompt, which the drive accepts so a reload
  // does not hang. Anything else is the product asking with the browser's voice.
  assert.match(src, /d\.type\(\) === "beforeunload"/);
  assert.match(src, /a native \$\{d\.type\(\)\} dialog was shown/);
  // And the report is written BEFORE the exit, or a failing run would leave none.
  assert.ok(src.indexOf("fs.writeFileSync(reportPath") < src.lastIndexOf("process.exit("), "the report must be written before the final exit");
  // Exit 2 is "could not tell": nothing ran, no export, no Playwright.
  assert.match(src, /No scenarios were found/);
  assert.ok(existsSync(join(DRIVE_DIR, "kit.mjs")));
});
