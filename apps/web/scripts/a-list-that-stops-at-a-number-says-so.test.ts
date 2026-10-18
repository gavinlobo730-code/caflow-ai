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
  DIRECT_READ_WINDOW_MAX, WINDOW_STEP, nextWindowLimit, windowDescription, windowSentence,
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
