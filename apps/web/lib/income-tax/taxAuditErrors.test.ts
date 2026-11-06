// Tax Audit Tracker > Add Audit — a second save for a client+FY that already
// has a row used to show Postgres's own text verbatim: "duplicate key value
// violates unique constraint \"tax_audits_client_id_financial_year_key\"".
// This is the belt-and-braces translation for the window the primary fix
// (looking the row up before saving — see app/income-tax/tax-audit/page.tsx)
// cannot close.
import test from "node:test";
import assert from "node:assert/strict";
import { AUDIT_DATE_REFUSAL_HINT, auditDateRefusalMessage, duplicateAuditErrorMessage } from "./taxAuditErrors.ts";

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

// Migration 584: an audit recorded as completed or filed does not carry a day that has not come. The trigger's sentence is written for a person; it is raised as a check violation
// with a hint, and only that pair is the sentence (another CHECK of the table raises 23514 in the database's own words).
const SENTENCE = "The filing date of a tax audit recorded as filed cannot be 20 Nov 2026: that day has not come (today in India is 06 Nov 2026). Record the day the report was filed on the portal.";

test("the date refusal of migration 584 is its own sentence", () => {
  assert.equal(AUDIT_DATE_REFUSAL_HINT, "tax_audits_dates_follow_the_status");
  assert.equal(auditDateRefusalMessage({ code: "23514", hint: AUDIT_DATE_REFUSAL_HINT, message: SENTENCE }), SENTENCE);
  assert.equal(auditDateRefusalMessage({ code: "23514", hint: AUDIT_DATE_REFUSAL_HINT, message: `  ${SENTENCE}  ` }), SENTENCE);
});

test("any other error is not the date refusal: a CHECK of the table in the database's words, another code, no hint", () => {
  assert.equal(auditDateRefusalMessage({ code: "23514", message: 'new row for relation "tax_audits" violates check constraint "tax_audits_status_check"' }), null);
  assert.equal(auditDateRefusalMessage({ code: "23514", hint: "something_else", message: SENTENCE }), null);
  assert.equal(auditDateRefusalMessage({ code: "23505", hint: AUDIT_DATE_REFUSAL_HINT, message: SENTENCE }), null);
  assert.equal(auditDateRefusalMessage({ code: "23514", hint: AUDIT_DATE_REFUSAL_HINT, message: "   " }), null);
  assert.equal(auditDateRefusalMessage({ code: "23514", hint: AUDIT_DATE_REFUSAL_HINT }), null);
  assert.equal(auditDateRefusalMessage(null), null);
  assert.equal(auditDateRefusalMessage(undefined), null);
});
