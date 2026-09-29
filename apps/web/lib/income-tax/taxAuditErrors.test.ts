// Tax Audit Tracker > Add Audit — a second save for a client+FY that already
// has a row used to show Postgres's own text verbatim: "duplicate key value
// violates unique constraint \"tax_audits_client_id_financial_year_key\"".
// This is the belt-and-braces translation for the window the primary fix
// (looking the row up before saving — see app/income-tax/tax-audit/page.tsx)
// cannot close.
import test from "node:test";
import assert from "node:assert/strict";
import { duplicateAuditErrorMessage } from "./taxAuditErrors.ts";

test("a unique_violation (23505) becomes an actionable sentence", () => {
  const msg = duplicateAuditErrorMessage({
    code: "23505",
    message: 'duplicate key value violates unique constraint '
      + '"tax_audits_client_id_financial_year_key"',
  });
  assert.ok(msg);
  assert.match(msg!, /already exists/i);
  assert.match(msg!, /edit it/i);
  // The whole point: the database's own words never reach the CA.
  assert.doesNotMatch(msg!, /constraint/i);
  assert.doesNotMatch(msg!, /tax_audits_client_id_financial_year_key/);
});

test("any other error code is left for the caller's own message", () => {
  assert.equal(duplicateAuditErrorMessage({ code: "23503", message: "fk violation" }), null);
  assert.equal(duplicateAuditErrorMessage({ code: "PGRST301", message: "RLS denied" }), null);
  assert.equal(duplicateAuditErrorMessage({ message: "no code at all" }), null);
});

test("null and undefined are handled without throwing", () => {
  assert.equal(duplicateAuditErrorMessage(null), null);
  assert.equal(duplicateAuditErrorMessage(undefined), null);
});
