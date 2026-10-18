// POST-A-132. Three lists asked the database for "the latest 100" (time entries, notifications, a client's tasks) and
// showed 100 rows as though they were all of them, with a heading, a tile or an "N entries" caption computed from the
// window. The client overview counted "open tasks" from a 50-row window over ALL statuses, so a client whose completed
// tasks were due first read "0 open tasks". The server now answers `has_more` (asks for one row more than the window),
// and a screen that passes a row limit says so when the list stopped short.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import {
  DIRECT_READ_WINDOW_MAX, ENTITY_REGISTER_WINDOW_MAX, LEAD_REGISTER_WINDOW_MAX, WINDOW_STEP, nextWindowLimit,
  windowDescription, windowSentence,
} from "../lib/lists/window.ts";
import { stripComments } from "./stripComments.ts";

test("showing more widens the window by one step and stops at the ceiling", () => {
  assert.equal(nextWindowLimit(100, 500), 100 + WINDOW_STEP);
  assert.equal(nextWindowLimit(450, 500), 500);
  assert.equal(nextWindowLimit(500, 500), null);
  assert.equal(nextWindowLimit(900, 500), null);
});

test("an unreadable limit or ceiling offers no 'show more' rather than one that does nothing", () => {
  assert.equal(nextWindowLimit(Number.NaN, 500), null);
  assert.equal(nextWindowLimit(100, Number.POSITIVE_INFINITY), null);
});

test("the sentence says what is shown and that more exist", () => {
  const what = windowDescription(100, "time entries", "latest");
  assert.equal(what, "the latest 100 time entries");
  assert.equal(windowSentence(what), "Showing the latest 100 time entries. More exist that are not shown here.");
  assert.equal(
    windowDescription(100, "tasks", "first", "soonest due first"),
    "the first 100 tasks, soonest due first",
  );
});

test("the browser's direct-read ceiling equals the API's", () => {
  const py = readFileSync(join(import.meta.dirname, "..", "..", "api", "core", "list_window.py"), "utf8");
  const m = py.match(/^MAX_LIST_LIMIT\s*=\s*(\d+)/m);
  assert.ok(m, "core/list_window.py no longer declares MAX_LIST_LIMIT");
  assert.equal(DIRECT_READ_WINDOW_MAX, Number(m![1]));
});

// ── the rule, over the tree ──────────────────────────────────────────────────────────────────────────────────────────

const WEB = join(import.meta.dirname, "..");

function* walk(dir: string): Generator<string> {
  for (const name of readdirSync(dir)) {
    if (["node_modules", ".next", "out", "scripts", ".git"].includes(name)) continue;
    const path = join(dir, name);
    if (statSync(path).isDirectory()) yield* walk(path);
    else if (/\.tsx?$/.test(name) && !/\.test\./.test(name)) yield path;
  }
}

/** A file that hands a row limit to a list read: a task read with a `limit`, a time-entry read with a `limit`, or a
 *  `limit` URL parameter on an API list. */
function passesALimit(src: string): boolean {
  const code = stripComments(src);
  if (/\bset\(\s*["']limit["']/.test(code)) return true;
  // A limit written into the URL of an API list (`...?limit=${n}`), and the register hook, which asks the server for one.
  if (/[?&]limit=/.test(code)) return true;
  if (/\buseEntityRegister\b/.test(code)) return true;
  for (const m of code.matchAll(/\b(getTasks|getTasksWindow|listTimeEntries)\(\s*\{([^}]*)\}/g)) {
    if (/\blimit\b/.test(m[2])) return true;
  }
  return false;
}

/** …and says so when the list stopped short: it reads the server's (or the window read's) more-signal. */
function readsTheMoreSignal(src: string): boolean {
  return /\b(hasMore|has_more)\b/.test(stripComments(src));
}

test("a screen that passes a row limit to a list read reads whether the list stopped short", () => {
  const offenders: string[] = [];
  for (const dir of ["app", "components"]) {
    for (const file of walk(join(WEB, dir))) {
      const src = readFileSync(file, "utf8");
      if (passesALimit(src) && !readsTheMoreSignal(src)) offenders.push(relative(WEB, file));
    }
  }
  assert.deepEqual(offenders, [], "these screens pass a row limit and never ask whether the list stopped short");
});

test("the rule finds the old shape and passes the new one (negative control)", () => {
  const old = `const { entries } = await listTimeEntries({ limit: 100 }); setEntries(entries);`;
  assert.equal(passesALimit(old), true);
  assert.equal(readsTheMoreSignal(old), false);
  const fixed = `const w = await getTasksWindow({ clientId, limit }); setHasMore(w.hasMore);`;
  assert.equal(passesALimit(fixed), true);
  assert.equal(readsTheMoreSignal(fixed), true);
  const noLimit = `const t = await getTasks({ clientId });`;
  assert.equal(passesALimit(noLimit), false);
});

test("the rule has files to find: the screens this fix names pass a limit", () => {
  const named = [
    "app/time/page.tsx", "app/notifications/page.tsx", "app/clients/[id]/tasks/page.tsx", "app/work/page.tsx",
  ];
  for (const f of named) assert.ok(passesALimit(readFileSync(join(WEB, f), "utf8")), `${f} no longer passes a limit; update the list`);
});

test("the client overview counts open tasks in the database and not in a window", () => {
  const code = stripComments(readFileSync(join(WEB, "app/clients/[id]/overview/page.tsx"), "utf8"));
  assert.match(code, /countOpenTasksForClient\(/);
  assert.doesNotMatch(code, /\bgetTasks\(/);
});

// ── POST-A-259: the document drawers, the entity register and the pipeline ───────────────────────────────────────────

test("the browser's two register ceilings equal the server's", () => {
  const rel = readFileSync(join(import.meta.dirname, "..", "..", "api", "routers", "relationships.py"), "utf8");
  const lc = readFileSync(join(import.meta.dirname, "..", "..", "api", "routers", "lifecycle.py"), "utf8");
  const entity = rel.match(/^ENTITY_LIST_MAX\s*=\s*(\d+)/m);
  const lead = lc.match(/^LEAD_LIST_MAX\s*=\s*(\d+)/m);
  assert.ok(entity, "routers/relationships.py no longer declares ENTITY_LIST_MAX");
  assert.ok(lead, "routers/lifecycle.py no longer declares LEAD_LIST_MAX");
  assert.equal(ENTITY_REGISTER_WINDOW_MAX, Number(entity![1]));
  assert.equal(LEAD_REGISTER_WINDOW_MAX, Number(lead![1]));
});

const DRAWERS = [
  "components/invoices/InvoiceViewDrawer.tsx",
  "components/purchases/PurchaseBillViewDrawer.tsx",
  "components/purchases/DebitNoteViewDrawer.tsx",
  "components/purchases/PurchaseCreditNoteViewDrawer.tsx",
  "components/sales/SalesCreditNoteViewDrawer.tsx",
  "components/sales/SalesDebitNoteViewDrawer.tsx",
];

test("a document drawer asks the server for the document's own events, says if older exist, and never reads a failure as an empty history", () => {
  for (const f of DRAWERS) {
    const code = stripComments(readFileSync(join(WEB, f), "utf8"));
    assert.match(code, /documentActivityUrl\(clientId,/, `${f} does not ask for the document's own events`);
    assert.doesNotMatch(code, /\/api\/timeline\?/, `${f} reads the client's whole timeline again`);
    assert.match(code, /readDocumentActivity\(tl,/, `${f} does not read the window through the shared reader`);
    assert.match(code, /<ActivityNote status=\{activityStatus\} \/>/, `${f} does not say when older entries exist`);
    assert.match(code, /emptyActivityLine\(activityStatus\)/, `${f} draws a failed read as an empty history`);
    // The old shape: keep the client's events that name this record, in the browser.
    assert.doesNotMatch(code, /\.filter\(\(e\) => e\.entity_type ===/, `${f} filters the client's events in the browser again`);
  }
});

/**
 * Screens that decide "this list was cut short" by `rows.length === the limit they asked for`. That guess is wrong in both
 * directions (a list of exactly that many rows is reported as cut short, and a window handed back short because the caller
 * may see fewer rows hides that more exist), and the server's `has_more` is the answer (apps/api/core/list_window.py). POST-A-262
 * moved the last four (login history, approvals, the HSN library, the memory screen) onto the server's window, so the list is
 * EMPTY and a new screen may not be added to it.
 */
const STILL_GUESSING: string[] = [];

test("no list screen decides it was cut short by comparing the row count to the limit it asked for", () => {
  const offenders: string[] = [];
  for (const dir of ["app", "components", "lib"]) {
    for (const file of walk(join(WEB, dir))) {
      const code = stripComments(readFileSync(file, "utf8"));
      if (/\.length\s*===\s*[A-Z][A-Z_]*(LIMIT|WINDOW|MAX)\b/.test(code)) offenders.push(relative(WEB, file));
    }
  }
  assert.deepEqual(
    offenders.sort(), [...STILL_GUESSING].sort(),
    "a screen guesses that a list stopped from rows.length === the limit; read the server's has_more. If you fixed one of " +
    "the frozen screens, remove it from STILL_GUESSING; a new one may not be added",
  );
});

test("the screens that list the entity register or the leads read the server's window", () => {
  for (const f of [
    "app/relationships/page.tsx", "app/pipeline/page.tsx",
  ]) {
    const code = stripComments(readFileSync(join(WEB, f), "utf8"));
    assert.match(code, /readWindow</, `${f} does not read the window through the shared reader`);
  }
  for (const f of [
    "app/relationships/explorer/page.tsx", "app/relationships/ownership-map/page.tsx",
    "app/clients/[id]/relationships/page.tsx",
  ]) {
    const code = stripComments(readFileSync(join(WEB, f), "utf8"));
    assert.match(code, /useEntityRegister</, `${f} does not list the register through the windowed hook`);
    assert.match(code, /<ListWindowNotice/, `${f} does not say when more entities exist`);
  }
});

test("the rule finds the URL-limit and register-hook shapes (negative control)", () => {
  assert.equal(passesALimit("apiFetch(`/api/relationships/entities?limit=${n}`)"), true);
  assert.equal(passesALimit("const r = useEntityRegister<Entity>(100);"), true);
  assert.equal(readsTheMoreSignal("const r = useEntityRegister<Entity>(100);"), false);
});

test("the five lists POST-A-262 moved read the server's window and say when it stopped", () => {
  const screens: Array<[string, RegExp]> = [
    ["app/team/login-history/page.tsx", /readWindow<LoginEvent>\(/],
    ["app/workflows/approvals/page.tsx", /readWindow<Approval>\(/],
    ["app/settings/firm-hsn-library/page.tsx", /readWindow<FirmHsnLibraryRow>\(/],
    ["app/memory/page.tsx", /readWindow<ClientProfile>\(/],
    ["app/memory/page.tsx", /readWindow<PatternAnomaly>\(/],
  ];
  for (const [f, reader] of screens) {
    const code = stripComments(readFileSync(join(WEB, f), "utf8"));
    assert.match(code, reader, `${f} does not read its list through the shared reader`);
    assert.match(code, /<ListWindowNotice/, `${f} does not say when the list stopped short`);
  }
});

test("the HSN library's Archived tab asks the server for retired codes and does not filter a window in the browser", () => {
  const code = stripComments(readFileSync(join(WEB, "app/settings/firm-hsn-library/page.tsx"), "utf8"));
  assert.match(code, /archived_only: filter === "archived"/);
  assert.doesNotMatch(code, /rows\.filter\(\(r\) => r\.is_active === false\)/, "the Archived tab filters a window of everything again");
});
