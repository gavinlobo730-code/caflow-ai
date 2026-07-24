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
  // verification harness didn't catch (it doesn't enforce the cap). Keep
  // real headroom, not just "under 100", so normal route growth doesn't
  // immediately re-trip this.
  const generated = buildRedirectsFile(APP_DIR);
  const ruleCount = generated.split("\n").filter((l) => l.trim().endsWith("200")).length;
  assert.ok(
    ruleCount <= 90,
    `_redirects has ${ruleCount} dynamic rules — Cloudflare Pages caps dynamic ` +
      "redirects at 100; this is too close to that limit. See generate-redirects.js's " +
      "module doc for the splat-consolidation strategy that keeps this down."
  );
});

test("a static sibling of a dynamic segment is never shadowed by that segment's splat", () => {
  // Regression pin for a real bug found while fixing the rule-count-cap
  // incident: a naive `/clients/:id/sales/invoices/:invoiceId/*` splat also
  // matches /clients/:id/sales/invoices/new/... (":invoiceId" matches the
  // literal segment "new" just as readily as a real id), so a request for
  // the static "new" page's trailing-slash/RSC shapes would be silently
  // rewritten to the WRONG target (as if "new" were an invoice id). Both
  // known instances of this in the current route tree (new vs :invoiceId
  // under sales/invoices; xbrl vs :engagementId under year-end) get their
  // OWN single-member splat group (its trailing-slash/RSC shapes), sorted
  // to win the depth tie against the colliding deeper group by being more
  // literal — while their DYNAMIC siblings (edit, checklist, ...) keep
  // relying on that deeper group's own splat.
  const generated = buildRedirectsFile(APP_DIR);
  // Shapes 1 & 4 (bare / bare-RSC) still can't be splat-covered — enumerated
  // same as any other dynamic route.
  for (const shape of [
    "/clients/:id/sales/invoices/new  ",
    "/clients/:id/sales/invoices/new.txt",
    "/clients/:id/year-end/xbrl ",
    "/clients/:id/year-end/xbrl.txt",
  ]) {
    assert.ok(generated.includes(shape.trimEnd()), `missing rule for ${shape.trim()}`);
  }
  // Shapes 2 & 3 (trailing slash, RSC /index.txt) are now covered by each
  // leaf's own splat group, not enumerated literally.
  assert.ok(generated.includes("/clients/:id/sales/invoices/new/*"));
  assert.ok(generated.includes("/clients/:id/year-end/xbrl/*"));
  // The colliding deeper splats themselves must still exist — they're safe
  // for every OTHER route sharing that group (e.g. "edit", "checklist").
  assert.ok(generated.includes("/clients/:id/sales/invoices/:invoiceId/*"));
  assert.ok(generated.includes("/clients/:id/year-end/:engagementId/*"));
  // Ordering: each shadowed leaf's own (more literal) splat must be tried
  // BEFORE the colliding deeper group's splat, or it would never win.
  const idx = (s: string) => generated.indexOf(s);
  assert.ok(idx("/clients/:id/sales/invoices/new/*") < idx("/clients/:id/sales/invoices/:invoiceId/*"));
  assert.ok(idx("/clients/:id/year-end/xbrl/*") < idx("/clients/:id/year-end/:engagementId/*"));
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
