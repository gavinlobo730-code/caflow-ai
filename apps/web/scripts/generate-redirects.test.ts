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
