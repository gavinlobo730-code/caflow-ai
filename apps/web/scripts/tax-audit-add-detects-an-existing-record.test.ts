// Income Tax > Tax Audit Tracker > Add Audit.
//
// `public.tax_audits` is UNIQUE(client_id, financial_year) (migration 035).
// The Add Audit form defaults to the CURRENT financial year and, when opened
// from a client's own workspace, that client — exactly the pair that already
// has a row the moment the firm has tracked one audit for the year. Saving a
// second time surfaced Postgres's raw "duplicate key value violates unique
// constraint" text with no path to the record it collided with, although the
// edit UI for that very record already existed one click away.
//
// The primary fix: look the row up BEFORE the CA hits Save, and switch the
// same modal into editing it. `lib/income-tax/taxAuditErrors.test.ts` covers
// the belt-and-braces translation of a residual 23505 from the database
// itself; this is a source test for the up-front lookup, in this repo's own
// style for exactly this class of property (scripts/concurrent-actions.test.ts,
// scripts/one-request-at-a-time.test.ts) — the page has JSX and so is not
// importable by node's stripped-types runner, and the property itself is
// syntactic wiring, not arithmetic worth a unit test of its own.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PAGE = path.join(__dirname, "..", "app", "income-tax", "tax-audit", "page.tsx");
const src = fs.readFileSync(PAGE, "utf8");

test("a match is looked up scoped to firm, client AND financial year", () => {
  const at = src.indexOf('.from("tax_audits")', src.indexOf("existingMatch"));
  assert.ok(at > 0, "no tax_audits query found near the existingMatch state");
  const query = src.slice(at, at + 400);
  assert.match(query, /\.eq\("firm_id",\s*firmId\)/, "must not read across firms");
  assert.match(query, /\.eq\("client_id",\s*form\.clientId\)/,
    "must be scoped to the client the CA is currently adding for");
  assert.match(query, /\.eq\("financial_year",\s*form\.financialYear\)/,
    "must be scoped to the FY the CA is currently adding for — the page's " +
    "OWN list is filtered to a possibly different FY and must not be reused " +
    "as if it already answered this");
});

test("the lookup is skipped once a record is opened via the table's own Edit button", () => {
  const at = src.indexOf("useEffect", src.indexOf("existingMatch"));
  const body = src.slice(at, src.indexOf("}, [editAudit", at) + 40);
  assert.match(body, /if\s*\(editAudit\)\s*\{\s*setExistingMatch\(null\);\s*return;\s*\}/,
    "an explicit Edit must not be second-guessed by a query keyed on fields " +
    "the CA may be actively changing inside it");
});

test("handleSave decides UPDATE vs INSERT from the found-or-editing record, not editAudit alone", () => {
  const at = src.indexOf("async function handleSave");
  assert.ok(at > 0);
  const body = src.slice(at, src.indexOf("\n  }\n", at));
  assert.match(body, /if\s*\(target\)/,
    "a record found by the up-front lookup must take the UPDATE branch too, " +
    "or the CA's first attempt after landing on it would still try to INSERT " +
    "and hit the same constraint this fix exists to avoid");
  assert.doesNotMatch(body, /if\s*\(editAudit\)/,
    "editAudit alone is not enough — it is null for a match this lookup just " +
    "found, which is exactly the case this fix adds");
});

test("the CA is told when the form filled itself in on its own", () => {
  // Unlike an explicit "Edit" click, auto-detection has to explain itself —
  // the fields just changed under a CA who only picked a client and a year.
  assert.match(src, /existingMatch && !editAudit/);
  assert.match(src, /already exists.*editing it below|editing it below.*already exists/s);
});

test("the residual-collision translator is wired in, not re-implemented inline", () => {
  assert.match(src, /import\s*\{\s*duplicateAuditErrorMessage\s*\}\s*from\s*"@\/lib\/income-tax\/taxAuditErrors"/,
    "a second, ad-hoc 23505 check beside this one is how the two drift");
  assert.match(src, /duplicateAuditErrorMessage\(/);
});
