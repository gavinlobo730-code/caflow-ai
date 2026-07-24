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

test("the total dynamic-rule count stays under Cloudflare Pages' 100-dynamic-redirect cap", () => {
  // Regression pin for the "whole client workspace 404s" incident: 39
  // dynamic pages x 4 enumerated shapes each produced 156 rules, and
  // anything past position 100 in the file was silently ignored by
  // Cloudflare in production — a failure mode this repo's own local
  // verification harness didn't catch (it doesn't enforce the cap).
  //
  // The budget was previously pinned at 90 for headroom, but by the time the
  // route tree grew to 50 dynamic pages that had already crept to 124 —
  // OVER the real cap, meaning some pages were silently 404ing in
  // production. Merging each entity's "new" create route into its sibling
  // "[xId]/edit" route (an id value of "new" as a create-mode sentinel; see
  // "the create/edit route merges are reflected in the rule count" below)
  // brought that back down to 99 — the verified, real floor of this
  // approach: every further reduction would require re-architecting a
  // large, distinct-workflow section (Year-End, Compliance, or Tax) into
  // tabs, which is a real product/UX decision, not a mechanical win like
  // the route merge was (see PR #150 discussion). 99 is pinned here as the
  // known-good number rather than the old 90 — but note this leaves only 1
  // rule of headroom below the actual 100 cap: the NEXT new dynamic page
  // added to the client workspace without a matching reduction elsewhere
  // will retrip this test, and should be treated as seriously as it was
  // here, not bumped again without re-checking the real cap.
  const generated = buildRedirectsFile(APP_DIR);
  const ruleCount = generated.split("\n").filter((l) => l.trim().endsWith("200")).length;
  assert.ok(
    ruleCount <= 99,
    `_redirects has ${ruleCount} dynamic rules — Cloudflare Pages caps dynamic ` +
      "redirects at 100; this is at or over that limit. See generate-redirects.js's " +
      "module doc for the splat-consolidation strategy that keeps this down."
  );
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
