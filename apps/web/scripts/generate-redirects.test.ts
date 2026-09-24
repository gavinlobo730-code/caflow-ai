// Proves public/_redirects can't silently drift from the app/ route tree.
// Run with: node --experimental-strip-types --test scripts/generate-redirects.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildRedirectsFile, walkPages } from "./generate-redirects.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const APP_DIR = path.join(__dirname, "..", "app");
const REDIRECTS_FILE = path.join(__dirname, "..", "public", "_redirects");

test("public/_redirects matches what the generator produces from app/ right now", () => {
  const generated = buildRedirectsFile(APP_DIR);
  const checkedIn = fs.readFileSync(REDIRECTS_FILE, "utf8");
  assert.equal(
    generated,
    checkedIn,
    "public/_redirects is stale — a page under a dynamic ([param]) route " +
      "segment was added, moved, or removed without re-running " +
      "`npm run generate:redirects` (or `next build`, which now runs it " +
      "automatically) before committing."
  );
});

test("every known client-section dynamic route is present", () => {
  const generated = buildRedirectsFile(APP_DIR);
  for (const from of [
    "/clients/:id/instructions",
    "/clients/:id/knowledge",
    "/clients/:id/year-end/xbrl",
    "/clients/:id/tax/26as",
    "/clients/:id/tax/computation",
    "/clients/:id/tax/filing",
  ]) {
    assert.ok(generated.includes(from), `missing rule for ${from}`);
  }
});

test("a deleted route's stale rule does not linger", () => {
  // Regression pin for the two dead entries found during the navigation
  // investigation: /clients/:id/coa (retired in R3.3b) and
  // /accounting/bank-statements/:id (its whole directory no longer exists).
  const generated = buildRedirectsFile(APP_DIR);
  assert.ok(!generated.includes("/clients/:id/coa"));
  assert.ok(!/\/accounting\/bank-statements/.test(generated));
});

/** Every rule in the generated file, as {from, to}. A rule is the only kind
 * of line the generator emits that ends in the 200 status code. */
function rulesIn(generated: string) {
  return generated
    .split("\n")
    .filter((l) => l.trim().endsWith("200"))
    .map((l) => {
      const [from, to] = l.trim().split(/\s+/);
      return { from, to };
    });
}

/** Cloudflare Pages counts a rule as DYNAMIC when its `from` carries a
 * `:placeholder` or a `*` splat — that is the population the 100 cap
 * applies to, and it is what this file must be measured against. Counting
 * "lines ending in 200" happens to give the same number today only because
 * the generator emits nothing static; the test below asserts that rather
 * than assuming it. */
const isDynamicRule = (from: string) => from.includes(":") || from.includes("*");

test("the dynamic-rule count stays under Cloudflare Pages' 100-dynamic-redirect cap", () => {
  // Regression pin for the "whole client workspace 404s" incident: 39
  // dynamic pages x 4 enumerated shapes each produced 156 rules, and
  // anything past position 100 in the file was silently ignored by
  // Cloudflare in production — a failure mode this repo's own local
  // verification harness didn't catch (it doesn't enforce the cap).
  //
  // THE BUDGET IS 98, WHICH IS THE REAL COUNT — a ratchet, not a ceiling
  // somebody picked. It was pinned at 90 once "for headroom", which meant
  // that by the time the tree reached 50 dynamic pages the file had crept
  // to 124 — OVER the real cap, with pages silently 404ing in production —
  // while the guard still read green against a number nobody had rechecked.
  // A budget above the truth is a budget that cannot fire. It was then
  // pinned at 99, one above the truth, which is the same mistake one rule
  // smaller: it silently admits the next page added.
  //
  // ⚠️ THE NEXT DYNAMIC PAGE ADDED BREAKS THIS, AND THAT IS THE POINT.
  // 98 + 2 = 100, which is AT the cap with no spare; +3 if it also opens a
  // new splat group, which is past it. Do not raise this number. See
  // DECISION D10 in generate-redirects.js's module doc: the collapse that
  // would buy 43 rules back was checked against the Cloudflare preview by
  // the owner and does not work — a bare path with no rule of its own 404s.
  // The route is a QUERY PARAMETER on an existing page, or a page somewhere
  // else is retired first.
  const generated = buildRedirectsFile(APP_DIR);
  const dynamic = rulesIn(generated).filter((r) => isDynamicRule(r.from));
  assert.equal(
    dynamic.length,
    98,
    `_redirects has ${dynamic.length} dynamic rules against a budget of 98 and a ` +
      "hard Cloudflare cap of 100, which fails SILENTLY. If this went UP, a route " +
      "was added — read D10 in generate-redirects.js before touching this number. " +
      "If it went DOWN, a route was retired and the budget ratchets down with it."
  );
});

test("every rule the generator emits is a dynamic one", () => {
  // The cap above is on DYNAMIC rules; Cloudflare's separate static budget
  // is 2,100 and nothing here approaches it. The two counts coincide today
  // only because every route this generator touches passes through at least
  // one [param] segment — which is the filter buildRedirectsFile applies.
  // If that ever stops being true the guard above starts charging static
  // rules against the dynamic cap, so the assumption is asserted rather
  // than left in a comment.
  const statics = rulesIn(buildRedirectsFile(APP_DIR)).filter((r) => !isDynamicRule(r.from));
  assert.deepEqual(
    statics,
    [],
    "the generator emitted a rule with no placeholder or splat — the budget " +
      "test is now counting static rules against the 100-DYNAMIC cap"
  );
});

test("the budget is spent in the shape D10 says it is", () => {
  // The count alone cannot tell a route being added from a shape changing.
  // These three are what D10's argument rests on: shapes 1 and 4 stay one
  // rule per page because no splat can express their transform, and 41 of
  // the 43 sit under /clients/ — which is why the consequence binds on that
  // subtree specifically rather than on the app in general.
  const rules = rulesIn(buildRedirectsFile(APP_DIR));
  const splats = rules.filter((r) => r.from.endsWith("/*"));
  const bare = rules.filter((r) => !r.from.endsWith("/*") && !r.from.endsWith(".txt"));
  const bareRsc = rules.filter((r) => !r.from.endsWith("/*") && r.from.endsWith(".txt"));

  assert.equal(bare.length, bareRsc.length,
    "shapes 1 and 4 are one rule per dynamic page each, so they move together");
  assert.deepEqual(
    { bare: bare.length, bareRsc: bareRsc.length, splats: splats.length },
    { bare: 43, bareRsc: 43, splats: 12 }
  );

  const underClients = bare.filter((r) => r.from.startsWith("/clients/"));
  assert.equal(underClients.length, 41,
    "D10's consequence — no new dynamic route under /clients/[id] — is aimed at " +
      "this subset. If it is no longer the bulk of the budget, re-read the decision.");
});

test("one more page under a dynamic prefix costs two rules, which is why 98 is the last safe number", () => {
  // The arithmetic the budget rests on, proved on a synthetic tree rather
  // than asserted in prose — and deliberately NOT by copying app/, which
  // would make this test a second measurement of the same thing instead of
  // a statement of the rule.
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "redirects-budget-"));
  try {
    const page = "export default function P() { return null; }";
    const mk = (...segs: string[]) => {
      const dir = path.join(tmp, ...segs);
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(path.join(dir, "page.tsx"), page);
    };
    mk("clients", "[id]", "overview");
    const before = rulesIn(buildRedirectsFile(tmp));

    mk("clients", "[id]", "insights");
    const after = rulesIn(buildRedirectsFile(tmp));

    assert.equal(after.length - before.length, 2,
      "a page added under an EXISTING splat group costs exactly its two " +
        "enumerated shapes — so 98 + 2 lands on 100, the cap itself");

    // And one that opens a NEW splat group costs three, which is past it.
    mk("clients", "[id]", "sections", "[sectionId]");
    const withNewGroup = rulesIn(buildRedirectsFile(tmp));
    assert.equal(withNewGroup.length - after.length, 3,
      "a page introducing a new dynamic segment also opens a splat group — " +
        "three rules, which from 98 is 101 and past the cap");
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});

test("a static sibling of a dynamic segment is never shadowed by that segment's splat", () => {
  // Regression pin for a real bug found while fixing the rule-count-cap
  // incident: a naive `/clients/:id/year-end/:engagementId/*` splat also
  // matches /clients/:id/year-end/xbrl/... (":engagementId" matches the
  // literal segment "xbrl" just as readily as a real id), so a request for
  // the static "xbrl" page's trailing-slash/RSC shapes would be silently
  // rewritten to the WRONG target (as if "xbrl" were an engagement id).
  // xbrl gets its OWN single-member splat group (its trailing-slash/RSC
  // shapes), sorted to win the depth tie against the colliding deeper group
  // by being more literal — while year-end's DYNAMIC siblings (checklist,
  // review, ...) keep relying on that deeper group's own splat.
  //
  // The former sales/invoices "new" vs ":invoiceId" instance of this same
  // bug no longer exists — "new" was merged into the :invoiceId route
  // itself (an id value of "new" means create-mode) specifically to remove
  // this shadow case AND its route from the rule-count budget entirely; see
  // "the create/edit route merges are reflected in the rule count" below.
  const generated = buildRedirectsFile(APP_DIR);
  // Shapes 1 & 4 (bare / bare-RSC) still can't be splat-covered — enumerated
  // same as any other dynamic route.
  for (const shape of [
    "/clients/:id/year-end/xbrl ",
    "/clients/:id/year-end/xbrl.txt",
  ]) {
    assert.ok(generated.includes(shape.trimEnd()), `missing rule for ${shape.trim()}`);
  }
  // Shapes 2 & 3 (trailing slash, RSC /index.txt) are covered by xbrl's own
  // splat group, not enumerated literally.
  assert.ok(generated.includes("/clients/:id/year-end/xbrl/*"));
  // The colliding deeper splat itself must still exist — it's safe for
  // every OTHER route sharing that group (e.g. "checklist", "review").
  assert.ok(generated.includes("/clients/:id/year-end/:engagementId/*"));
  // Ordering: xbrl's own (more literal) splat must be tried BEFORE the
  // colliding deeper group's splat, or it would never win.
  const idx = (s: string) => generated.indexOf(s);
  assert.ok(idx("/clients/:id/year-end/xbrl/*") < idx("/clients/:id/year-end/:engagementId/*"));
});

test("the create/edit route merges are reflected in the rule count", () => {
  // Regression pin: sales/invoices/new, sales/credit-notes/new,
  // sales/debit-notes/new, purchases/bills/new, purchases/credit-notes/new
  // and purchases/debit-notes/new were each merged into their sibling
  // [xId]/edit route (an id value of "new" means create-mode inside that
  // same page) specifically to cut the redirect rule count — each merge
  // removes one whole route (2 enumerated rules) plus the shadow-splat it
  // used to need (1 rule), 3 rules saved per pair. None of the six should
  // appear as their own literal "new" route/group any more.
  const generated = buildRedirectsFile(APP_DIR);
  for (const gone of [
    "/clients/:id/sales/invoices/new ",
    "/clients/:id/sales/invoices/new/*",
    "/clients/:id/sales/credit-notes/new",
    "/clients/:id/sales/debit-notes/new",
    "/clients/:id/purchases/bills/new",
    "/clients/:id/purchases/credit-notes/new",
    "/clients/:id/purchases/debit-notes/new",
  ]) {
    assert.ok(!generated.includes(gone), `stale rule for merged-away route: ${gone}`);
  }
  // Each pair's single surviving dynamic route/group must still cover both
  // create ("new") and edit (a real id) via the same rules.
  for (const group of [
    "/clients/:id/sales/invoices/:invoiceId",
    "/clients/:id/sales/credit-notes/:cnId",
    "/clients/:id/sales/debit-notes/:sdnId",
    "/clients/:id/purchases/bills/:billId",
    "/clients/:id/purchases/credit-notes/:pcnId",
    "/clients/:id/purchases/debit-notes/:dnId",
  ]) {
    assert.ok(generated.includes(`${group}/*`), `missing merged splat for ${group}`);
  }
});

test("a catch-all route segment is rejected rather than silently mishandled", () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "redirects-test-"));
  try {
    const dir = path.join(tmp, "clients", "[...slug]");
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, "page.tsx"), "export default function P() { return null; }");
    assert.throws(() => walkPages(tmp), /catch-all segment/);
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
});
