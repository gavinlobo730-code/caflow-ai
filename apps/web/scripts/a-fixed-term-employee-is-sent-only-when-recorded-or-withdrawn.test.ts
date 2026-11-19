/**
 * FIXED-TERM EMPLOYMENT IS SENT ONLY WHEN SOMEBODY RECORDED IT OR IS WITHDRAWING IT, AND THE SETTLEMENT ASKS ABOUT THE EXPIRY ONLY THEN
 * (POST-A-526, migration 770).
 *
 * Where a fixed term EXPIRES, an employee is eligible for gratuity on one year of service under the contract, not five (the second
 * proviso to section 53(1) of the Code on Social Security, 2020; rule 33(1)(a) of the Social Security (Central) Rules, 2026). The
 * employee form has a box for the record and the settlement a box for the expiry. Three things about HOW they are sent matter and are
 * held here:
 *
 *   1. An ordinary save never names the two new columns. A deploy that reaches production a few minutes before the migration would
 *      otherwise make every employee edit fail on a column that is not there yet, and an employee who was never fixed-term has no
 *      "false" to record: NULL and FALSE compute alike and are kept apart, so `false` is sent only to WITHDRAW a recorded fixed term.
 *   2. The box is the person's statement and nothing else: the form never infers it from a joining date, a short service or a contract
 *      end date, and the date is optional and appears only once the box is ticked.
 *   3. The settlement asks "has the term expired?" only for an employee recorded as fixed-term, and sends the answer only then. The
 *      text read does not settle a fixed-term employee who leaves BEFORE the term ends, and the screen says so rather than promising it.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const modal = fs.readFileSync(path.join(import.meta.dirname, "..", "components/payroll/AddEmployeeModal.tsx"), "utf8");
const shared = fs.readFileSync(path.join(import.meta.dirname, "..", "components/payroll/shared.ts"), "utf8");
const drawer = fs.readFileSync(path.join(import.meta.dirname, "..", "components/payroll/EmployeeDrawer.tsx"), "utf8");
const apiTypes = fs.readFileSync(path.join(import.meta.dirname, "..", "lib/api/index.ts"), "utf8");

test("the form's state starts from what the employee row holds, and unticked for everyone else", () => {
  assert.match(modal, /fixed_term_employment: employee\?\.fixed_term_employment === true,/);
  assert.match(modal, /fixed_term_end_date: employee\?\.fixed_term_end_date \?\? "",/);
});

test("the request names the columns only to record a fixed term or to withdraw one", () => {
  assert.match(modal, /const priorFixedTerm = employee\?\.fixed_term_employment === true;/);
  assert.match(modal, /\? \{ fixed_term_employment: true, fixed_term_end_date: form\.fixed_term_end_date \|\| undefined \}/);
  assert.match(modal, /\? \{ fixed_term_employment: false \}\s*:\s*\{\}/);
  assert.match(modal, /\.\.\.fixedTermFields,/);
  // never the box's value straight into the payload: that would send `false` for every ordinary employee on every save
  assert.doesNotMatch(modal, /fixed_term_employment: form\.fixed_term_employment[,\s]/);
});

test("the box is a statement, and its date appears only once it is ticked", () => {
  assert.match(modal, /id="fixed-term"/);
  assert.match(modal, /\{form\.fixed_term_employment && \(/);
  assert.match(modal, /id="fixed-term-end"/);
  assert.match(modal, /Contract ends on \(optional\)/);
});

test("the box names the provisions it rests on and says to tick it only for a fixed-term contract", () => {
  assert.match(modal, /section 53\(1\) of the Code on Social\s+Security,\s+2020/);
  assert.match(modal, /33\(1\)\(a\) of the Social Security \(Central\) Rules,\s+2026/);
  assert.match(modal, /Tick it only for an employee engaged\s+on a fixed-term contract/);
});

test("the employee type carries both fields as optional and nullable", () => {
  assert.match(shared, /fixed_term_employment\?: boolean \| null;/);
  assert.match(shared, /fixed_term_end_date\?: string \| null;/);
});

test("nothing on the form decides it from a date or a length of service", () => {
  assert.doesNotMatch(modal, /fixed_term_employment[^\n]*(joining_date|date_of_birth)/);
});

test("the form says the waiver is on the expiry of the term and that an early exit is not settled", () => {
  assert.match(modal, /Where a fixed term expires, the employee is eligible for\s+gratuity/);
  assert.match(modal, /The settlement asks\s+whether the term has expired/);
  assert.match(modal, /not shown as eligible on one\s+year: the text does not settle it/);
  // the old sentence promised one year for every fixed-term employee
  assert.doesNotMatch(modal, /A fixed-term employee is eligible for gratuity on at least one/);
});

test("the settlement asks whether the term expired only for an employee recorded as fixed-term, and sends it only then", () => {
  assert.match(drawer, /fixed_term_employment\?: boolean \| null;/);
  assert.match(drawer, /\{employee\.fixed_term_employment === true && \(/);
  assert.match(drawer, /The fixed term has expired/);
  assert.match(drawer, /\.\.\.\(employee\.fixed_term_employment === true \? \{ fixed_term_contract_expired: fixedTermExpired \} : \{\}\),/);
  // never the box's value straight into the payload: that would name the field for every employee on every settlement
  assert.doesNotMatch(drawer, /fixed_term_contract_expired: fixedTermExpired,/);
  assert.match(apiTypes, /fixed_term_contract_expired\?: boolean;/);
});

test("the settlement's expiry box is part of what makes the form dirty", () => {
  assert.match(drawer, /leavingDate, onRetirement, onDeath, fixedTermExpired, isGovernment,/);
});

test("the settlement box says what the Code waives and what it does not settle", () => {
  assert.match(drawer, /Section 53\(1\) waives the five years of service only where the employment ends by the expiry of the fixed/);
  assert.match(drawer, /a recorded contract end date that has been reached/);
  assert.match(drawer, /the text read does not settle it/);
});
