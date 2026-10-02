// A product screen's title is written by ONE component, and the screens that
// still write their own are a frozen list that can only shrink. Run with:
//   node --experimental-strip-types --test scripts/a-screen-names-itself-through-one-component.test.ts
//
// WHAT WAS WRONG (frontend_ux-13)
//     There was no PageHeader. 125 `<h1>` in 119 files carried 28 different
//     class strings — `text-xl font-semibold text-ps-ink` on 55, then `text-lg`
//     in brand navy on 12, `text-2xl font-bold` on 8, `text-base` on 7 and a long
//     tail — so the name of a screen changed size, weight and colour as a CA
//     moved from Sales to Payroll to GST, and its main button sat beside the
//     title, under it or in a band of its own. The "back" affordance was five
//     different things; the commonest was an icon-only chevron with no
//     accessible name.
//
// THE RULE
//   A screen's `<h1>` is rendered by `components/ui/page-header.tsx`. A raw
//   `<h1` anywhere else under `app/` or `components/` fails, unless the file is
//   in the frozen list below with the reason it is not a product screen's title.
//   The list is asserted as an EQUALITY, so a file that migrates must be taken
//   off it (it only shrinks) and a new offender cannot be added by raising a
//   budget. It is the Schedule III caption lesson applied to a heading: a count
//   is one number somebody raises; a named list can only be edited with the
//   reason in view.
//
// WHAT THIS DOES NOT SAY
//   That the title is the right title, or that the page is laid out well. No
//   browser harness exists, so the placement of the actions is held by the
//   component's rendered markup (components/ui/page-header.test.ts) and not by a
//   screenshot of 119 screens.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const COMPONENT = "components/ui/page-header.tsx";

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(path.join(WEB, dir), { withFileTypes: true })) {
    const rel = path.posix.join(dir, e.name);
    if (e.isDirectory()) walk(rel, out);
    else if (e.name.endsWith(".tsx")) out.push(rel);
  }
  return out;
}

const FILES = [...walk("app"), ...walk("components")].sort();

function code(rel: string): string {
  return stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));
}

/** Every `<h1 className="…">` literal: the class string, or null where the
 *  class is an expression (the component's own). */
function h1s(src: string): Array<string | null> {
  const out: Array<string | null> = [];
  for (const m of src.matchAll(/<h1\b([^>]*)>/g)) {
    const lit = /className="([^"]*)"/.exec(m[1]);
    out.push(lit ? lit[1] : null);
  }
  return out;
}

// Frozen, and can only shrink. file -> [how many raw h1, why it is not a product
// screen's title]. Every entry is a screen with a DIFFERENT SHELL — one with no
// navigation around it, which a CA never moves between and which has no
// "primary action" row — or a heading that is not on screen at all.
const FROZEN: Record<string, { count: number; kind: "different-shell" | "print-only"; reason: string }> = {
  "app/sign/page.tsx": {
    count: 2,
    kind: "different-shell",
    reason: "the public engagement-letter signing page: a prospect's card, no shell, no login",
  },
  "app/login/page.tsx": {
    count: 1,
    kind: "different-shell",
    reason: "the sign-in screen's marketing panel, white on a dark brand surface",
  },
  "app/join/page.tsx": {
    count: 1,
    kind: "different-shell",
    reason: "the invitation landing page: a logo and a brand name on a gradient, no shell",
  },
  "app/onboarding/page.tsx": {
    count: 2,
    kind: "different-shell",
    reason: "the firm sign-up wizard (NO_SHELL_EXACT in AppShell): there is no firm yet to have navigation",
  },
  "app/portal/employee/activate/page.tsx": {
    count: 4,
    kind: "different-shell",
    reason: "the employee invitation card: an employee principal with no staff navigation",
  },
  "app/accounting/schedule-iii/page.tsx": {
    count: 1,
    kind: "print-only",
    reason: "the PRINT-ONLY centred heading of a statutory report (hidden on screen)",
  },
};

test("the scan reads the tree it claims to (not vacuous)", () => {
  assert.ok(FILES.length > 300, `only ${FILES.length} .tsx files scanned`);
  assert.ok(FILES.includes(COMPONENT));
  assert.ok(FILES.includes("app/billing/page.tsx"));
});

test("no screen writes its own <h1> unless it is frozen with a reason", () => {
  const found: Record<string, number> = {};
  for (const rel of FILES) {
    if (rel === COMPONENT) continue;
    const n = h1s(code(rel)).length;
    if (n > 0) found[rel] = n;
  }
  const frozen = Object.fromEntries(Object.entries(FROZEN).map(([f, v]) => [f, v.count]));
  assert.deepEqual(found, frozen,
    "a screen's title comes from PageHeader (components/ui/page-header.tsx): " +
    "<PageHeader title=… subtitle=… actions={…} back={…} />. If a screen was " +
    "MIGRATED, delete its entry — this list only shrinks. If a screen is genuinely " +
    "not a product screen's title, it needs an entry with the reason, which is a " +
    "decision somebody reads, not a number somebody raises.");
});

test("each frozen entry still says why", () => {
  for (const [file, { reason }] of Object.entries(FROZEN)) {
    assert.ok(reason.length > 25, `${file} has no reason`);
  }
});

test("PageHeader is the only h1 written from an expression, exactly once", () => {
  const own = h1s(code(COMPONENT));
  assert.deepEqual(own, [null], "page-header.tsx must render exactly one <h1>, with its class from a constant");
  assert.match(code(COMPONENT), /const TITLE_CLASS = "text-xl font-semibold text-ps-ink"/);
});

test("the distinct raw h1 class strings fell from 28 to the frozen few", () => {
  // The finding's measurement, redone: distinct literal class strings over
  // app/ and components/. Every one left belongs to a frozen file.
  const distinct = new Set<string>();
  for (const rel of FILES) {
    if (rel === COMPONENT) continue;
    for (const c of h1s(code(rel))) if (c !== null) distinct.add(c);
  }
  assert.ok(distinct.size <= 7, `${distinct.size} distinct raw h1 class strings remain: ${[...distinct].join(" | ")}`);
});

/** The routes AppShell draws no shell around, read from AppShell itself. */
function noShellRoutes(): { prefixes: string[]; exact: string[] } {
  const src = code("components/AppShell.tsx");
  const list = (name: string): string[] => {
    const m = new RegExp(`const ${name} = \\[([^\\]]*)\\]`).exec(src);
    assert.ok(m, `${name} not found in AppShell.tsx`);
    return [...m![1].matchAll(/"([^"]+)"/g)].map((x) => x[1]);
  };
  return { prefixes: list("NO_SHELL_PREFIXES"), exact: list("NO_SHELL_EXACT") };
}

test("a 'different shell' freeze is a route AppShell really draws no shell around", () => {
  // The freeze is only honest while it is true: a screen inside the product
  // shell has navigation, a primary-action row and a CA who moves between it and
  // its neighbours, which is exactly what PageHeader is for.
  const { prefixes, exact } = noShellRoutes();
  assert.ok(prefixes.includes("/login") && exact.includes("/onboarding"), "AppShell's lists were not read");
  for (const [file, { kind }] of Object.entries(FROZEN)) {
    if (kind !== "different-shell") continue;
    const route = "/" + file.replace(/^app\//, "").replace(/\/page\.tsx$/, "");
    const bare = prefixes.some((p) => route === p || route.startsWith(p + "/")) || exact.includes(route);
    assert.ok(bare, `${file} is frozen as a different shell but AppShell draws one around ${route}`);
  }
});

test("a raw h1 inside the product shell is a print-only heading and nothing else", () => {
  const inShell = Object.entries(FROZEN).filter(([, v]) => v.kind === "print-only").map(([f]) => f);
  assert.deepEqual(inShell, ["app/accounting/schedule-iii/page.tsx"]);
  assert.match(code("app/accounting/schedule-iii/page.tsx"), /hidden print:block[^>]*>\s*<h1\b/,
    "the one in-shell raw h1 must be the print-only heading");
});

test("every screen the migration touched still imports the component it renders", () => {
  // A <PageHeader> with no import is a compile error, which tsc catches; this
  // catches the reverse — an import left behind by a migration that was undone.
  const orphans: string[] = [];
  for (const rel of FILES) {
    if (rel === COMPONENT) continue;
    const src = code(rel);
    const imports = /import \{[^}]*\bPageHeader\b[^}]*\} from "@\/components\/ui\/page-header"/.test(src);
    const uses = /<PageHeader\b/.test(src);
    if (imports !== uses) orphans.push(`${rel} (${imports ? "imports but never renders" : "renders but does not import"})`);
  }
  assert.deepEqual(orphans, []);
});

test("a back link carries its label: no screen passes PageHeader an icon-only way back", () => {
  // The old chevron-only Link had no accessible name. PageHeader's `back` takes
  // a label, so the rule is that the label is never empty.
  const empty: string[] = [];
  for (const rel of FILES) {
    if (rel === COMPONENT) continue;
    const src = code(rel);
    for (const m of src.matchAll(/back=\{\{[^}]*label:\s*"([^"]*)"/g)) {
      if (m[1].trim() === "") empty.push(rel);
    }
  }
  assert.deepEqual(empty, []);
});
