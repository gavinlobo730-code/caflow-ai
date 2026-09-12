// A challan 281 is not all tax, and the CA is told what the month owes. Run with:
//   node --experimental-strip-types --test scripts/the-challan-records-what-was-actually-paid.test.ts
//
// WHY THIS EXISTS (TDS-08, TDS-30)
//
//     migration 037 gave tds_challans a surcharge_paise, interest_paise and
//     penalty_paise column in 2025, and a minor_head defaulting to '200'.
//     Nothing ever wrote to any of them: the Add Challan modal sent ONE
//     amount, the endpoint booked the whole of it as tds_paise, and a deposit
//     that was partly s.201(1A) interest went into the books as if it were all
//     tax. The section then read as over-deposited, and the deductee annexure
//     could not foot against the challan sheet.
//
//     The other half is what the CA does BEFORE recording a challan. Every
//     deduction is already a row in tds_deductions and nothing added them up,
//     so on the 5th of the month they exported to Excel to work out what was
//     due by the 7th — the exact workflow this product exists to replace.
//
// WHAT IS ASSERTED, AND WHAT IS NOT
//
//     Not the arithmetic. s.201(1A)'s two rates and two clocks, the calendar
//     month convention and s.234E's daily fee live in
//     apps/api/domain/tds/interest.py, and apps/api/tests/
//     test_what_being_late_costs_a_deductor.py pins them. CLAUDE.md: zero
//     business logic in the frontend. What is asserted here is that the screen
//     COLLECTS the heads and RENDERS the server's answer — the two halves that
//     were missing while the engine was fine.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(import.meta.dirname, "..");
const PAGE = fs.readFileSync(path.join(ROOT, "app/tds/page.tsx"), "utf8");
const DATA = fs.readFileSync(path.join(ROOT, "lib/data/tds.ts"), "utf8");

// The modal's request payload, sliced out so a field held in STATE and then
// left out of the body cannot pass for one that is sent. That exact weakness
// let four negative controls pass silently on the fixed-asset drawer.
const CREATE = PAGE.slice(
  PAGE.indexOf("const saved = await createTdsChallan({"),
  PAGE.indexOf("      onAdded(saved);"),
);

test("the modal sends every head of the challan, not just one amount", () => {
  assert.ok(CREATE.length > 0, "the createTdsChallan payload could not be found");
  for (const field of ["surcharge_paise", "interest_paise", "penalty_paise", "minor_head"]) {
    assert.match(CREATE, new RegExp(`${field}:`),
      `the challan payload omits ${field} — migration 037 has the column and ` +
      `nothing wrote to it, so a deposit that was partly interest was booked as tax`);
  }
});

test("every typed rupee figure goes through the one money parser", () => {
  // Math.round(parseFloat(x) * 100) reads "1,25,000" as one rupee. The three
  // new fields are amounts like any other.
  for (const setter of ["surchargeRupees", "interestRupees", "penaltyRupees"]) {
    assert.match(
      PAGE,
      new RegExp(`paiseFromRupeeInput\\(${setter}`),
      `${setter} must be parsed by lib/money/rupeeInput, not coerced`);
  }
});

test("a split larger than the total is refused before the round trip", () => {
  assert.match(
    PAGE,
    /surchargePaise \+ interestPaise \+ penaltyPaise > amtPaise/,
    "the components are part OF the total, not additions to it — without this " +
    "the CA sees a server 422 with no idea which figure to change");
});

test("the minor head can be a 400 and cannot be anything else", () => {
  assert.match(PAGE, /value="400"/,
    "migration 037 defaults minor_head to '200' and nothing could send a 400, " +
    "so a deposit against a demand raised on regular assessment could not be recorded");
  assert.match(PAGE, /e\.target\.value === "400" \? "400" : "200"/,
    "the minor head is one of two values; a free string would reach a CHECK-less " +
    "column and be wrong forever");
});

test("the deposit-due worksheet is on the challans tab", () => {
  assert.match(PAGE, /<DepositDuePanel clientId=/,
    "the worksheet must be where the CA records the challan — that is the " +
    "sequence: work out what is due, then pay it, then record it");
  assert.match(DATA, /export async function fetchDepositDue/);
  assert.match(DATA, /\/api\/tds-workspace\/deposit-due/);
});

test("the worksheet computes nothing in the browser", () => {
  const PANEL = PAGE.slice(
    PAGE.indexOf("function DepositDuePanel("),
    PAGE.indexOf("// ─── Add Challan Modal"),
  );
  assert.ok(PANEL.length > 0, "the DepositDuePanel could not be found");
  // Every figure it shows is a field of the server's answer. A local rate, a
  // local due date or a local sum is a second implementation of a statutory
  // rule that apps/api already owns.
  //
  // The test is ARITHMETIC, not the mention of a rate: the panel's own amber
  // sentence tells the CA that s.201(1A)(ii) runs at 1.5% a month, and saying
  // so is the point of it. What must not appear is a calculation.
  for (const forbidden of [
    /\*\s*1\.5\b/, /\*\s*0\.015\b/, /\*\s*150\b/, /\*\s*200\b/,
    /\/\s*10_?000\b/, /_paise\s*[*/]/, /[*/]\s*\w*_paise\b/,
  ]) {
    assert.ok(!forbidden.test(PANEL),
      `the panel appears to compute rather than render: ${forbidden}`);
  }
  assert.ok(!/const\s+\w*[Dd]ue\w*\s*=\s*new Date/.test(PANEL),
    "the Rule 30(2) due date is the server's — services/compliance_engine.py " +
    "derives it, including the March exception");
});

test("a failed worksheet load does not read as a clear month", () => {
  const PANEL = PAGE.slice(
    PAGE.indexOf("function DepositDuePanel("),
    PAGE.indexOf("// ─── Add Challan Modal"),
  );
  // The CATCH, not the whole panel. `phase: "error"` also appears in the
  // discriminated union's TYPE declaration, so scanning the panel for it
  // passed on a catch that had been changed to report a clean empty result —
  // a declaration reading as a use, which is the same weakness that let four
  // negative controls pass silently on the fixed-asset drawer.
  const CATCH = PANEL.slice(PANEL.indexOf(".catch("), PANEL.indexOf("}, [clientId, month]);"));
  assert.ok(CATCH.length > 0, "the panel's failure handler could not be found");
  assert.match(CATCH, /phase: "error"/,
    "a CA who reads 'nothing due' off a request that never landed does not pay");
  assert.ok(!/phase: "ok"/.test(CATCH),
    "a failed load must not be rendered as a successful, empty worksheet");
  assert.match(PANEL, /this is a failed check, not a clear month/);
});

test("the worksheet always says what it does not cover", () => {
  const PANEL = PAGE.slice(
    PAGE.indexOf("function DepositDuePanel("),
    PAGE.indexOf("// ─── Add Challan Modal"),
  );
  // s.192 salary tax is computed in payroll and never reaches tds_deductions,
  // so a total read as "the month's TDS" is only part of it. The server sends
  // the sentence; the screen must render it unconditionally, not only when the
  // worksheet is empty.
  const covers = PANEL.split("state.sheet.covers");
  assert.ok(covers.length >= 3,
    "the scope note must render beside a populated worksheet too, not only an empty one");
});
