// The dashboard shows a first-run checklist the server computes, in place of a welcome
// card that appeared once. Run with:
//   node --experimental-strip-types --test scripts/the-first-run-checklist-replaces-the-welcome-card.test.ts
//
// WHY THIS EXISTS (market_and_trust-16)
//     After onboarding a new owner landed on a dismissible card of five links shown ONCE
//     (`?welcome=1`) — nothing tracked progress, so a firm that closed the tab after adding
//     a client could not see that an invoice and a statement were still ahead of it.
//     `GET /api/onboarding/status` existed and nothing called it. These are the RULES: the
//     card is gone, the checklist is the server's, the browser counts nothing and reads no
//     table, a failed call hides it rather than showing an unknown as a value, and the one
//     thing kept in the browser is a collapsed flag, with every access guarded.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const DASH = "app/DashboardContent.tsx";
const CARD = "components/onboarding/FirstRunChecklist.tsx";
const LIB = "lib/onboarding/firstRun.ts";
const API = "lib/api/index.ts";

function code(rel: string): string {
  return fs.readFileSync(path.join(ROOT, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

test("the one-time welcome card is gone and the checklist is rendered in its place", () => {
  const src = code(DASH);
  assert.match(src, /<FirstRunChecklist\s*\/>/, "the dashboard renders the checklist");
  assert.doesNotMatch(src, /\bNEXT_STEPS\b/, "the five hard-coded links are gone");
  assert.doesNotMatch(src, /\bshowWelcome\b|\bsetShowWelcome\b/, "no welcome state: the card no longer appears once");
  assert.doesNotMatch(src, /Workspace ready|Welcome to PracticeSync/, "the welcome copy is gone with the card");
});

test("?welcome=1 is still cleared from the address bar and switches nothing on", () => {
  const src = code(DASH);
  assert.match(src, /params\.delete\("welcome"\)/);
  assert.match(src, /replaceState/);
});

test("the checklist is fetched from the server's status endpoint through the api client", () => {
  assert.match(code(API), /firstRun:\s*\{[\s\S]*?\/api\/onboarding\/status/, "the endpoint that had no caller");
  const card = code(CARD);
  assert.match(card, /api\.firstRun\.status\(/);
  assert.match(card, /readFirstRun\(/, "the payload is read through the shape guard, not trusted");
  assert.match(card, /shouldShow\(/);
});

test("the browser counts nothing and reads no table: every tick is the server's", () => {
  for (const rel of [CARD, LIB]) {
    const src = code(rel);
    assert.doesNotMatch(src, /getSupabaseClient|supabase\.from\(|\.from\(\s*["'](clients|client_sales_invoices|bank_statements|users)["']/,
      `${rel}: a tick worked out from a table is a second rule`);
    assert.doesNotMatch(src, /\.length\s*(>|>=|===)\s*[01]\b[^;\n]*(client|invoice|statement|colleague)/i,
      `${rel}: deciding a step is done by counting rows`);
  }
  // the three states survive: the card distinguishes "could not check" from "not done"
  const card = code(CARD);
  assert.match(card, /Could not be checked/);
  assert.match(card, /done === null/);
});

test("a failed call or a refusal renders nothing rather than an unknown shown as a value", () => {
  const card = code(CARD);
  assert.match(card, /catch\s*\{[\s\S]*?setPayload\(null\)/);
  assert.match(card, /if \(!shouldShow\(checklist\)\) return null;/);
  // the payload is narrowed to an object at the setter and READ through the shape guard
  assert.match(card, /setPayload\(r && r\.success \? objectOrNull</);
  assert.match(card, /useMemo\(\(\) => readFirstRun\(payload\)/);
});

test("the only thing kept in the browser is whether THIS person collapsed the card, and every access is guarded", () => {
  const card = code(CARD);
  const uses = card.match(/localStorage\.(getItem|setItem)\(/g) ?? [];
  assert.equal(uses.length, 2, "a read and a write of one flag, nothing else");
  assert.match(card, /COLLAPSED_KEY/);
  assert.equal((card.match(/localStorage/g) ?? []).length, 2, "no other localStorage reference");
  // each access sits inside a try
  assert.match(card, /try\s*\{\s*setCollapsed\(window\.localStorage\.getItem\(COLLAPSED_KEY\)/);
  assert.match(card, /try\s*\{\s*window\.localStorage\.setItem\(COLLAPSED_KEY/);
  // and it is read in an effect, never during render (this app is a static export)
  assert.doesNotMatch(card, /useState\([^)]*localStorage/);
});

test("collapsing leaves the progress visible, so the card is never hidden by the person", () => {
  const card = code(CARD);
  assert.match(card, /role="progressbar"/);
  // the progress bar and the heading sit outside the collapsed branch
  const collapsedBranch = card.indexOf("!collapsed ?");
  assert.ok(collapsedBranch > card.indexOf('role="progressbar"'), "the steps are what collapses, not the header");
});

test("a step opens an existing screen; no route was added for it", () => {
  const lib = code(LIB);
  for (const href of ["/clients", "/accounting/invoices", "/accounting/banking", "/team"]) {
    assert.ok(lib.includes(`"${href}"`), href);
    assert.ok(fs.existsSync(path.join(ROOT, "app", ...href.split("/").filter(Boolean), "page.tsx")), `${href} is a real screen`);
  }
});
