// Recording a GST return the CA filed on the portal, and a leave entitlement
// nobody has recorded.
//
// Run with:
//   node --experimental-strip-types --test scripts/a-filed-return-is-recorded-with-its-acknowledgement.test.ts
//
// GST-23 — the ARN and the filing date had nowhere to go
//     PATCH /gst-workspace/{gstr1,gstr3b}/{id}/status has accepted `arn` and
//     `filed_date` since migration 036's columns were finally written to, and
//     it calls record_filing, which writes the public.filings row
//     journal_period_lock_reason reads. No screen ever sent either: both tabs
//     PATCHed {status, ca_approved} and nothing more, and the GSTR-1 tab had
//     no submitted step at all — its chain stopped at ca_approved. So the
//     period lock, when it happened, was created against no acknowledgement
//     and a defaulted date, and the §37(3) correction window is measured from
//     exactly that date.
//
// PAY-24 — an entitlement nobody set is not twelve days
//     app/payroll/attendance/page.tsx substituted 12 casual / 12 sick / 15
//     earned for an employee with no leave_balances row, and computed
//     "Remaining" against the invention.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const GST = fs.readFileSync(path.join(WEB, "app/clients/[id]/compliance/gst/page.tsx"), "utf8");
const ATT = fs.readFileSync(path.join(WEB, "app/payroll/attendance/page.tsx"), "utf8");

/** Source with comments stripped — what actually runs and renders. */
function code(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/^\s*\/\/.*$/gm, " ");
}

// ── GST-23 ───────────────────────────────────────────────────────────────────

test("both GST tabs can record a filing, through one dialog", () => {
  const ui = code(GST);
  assert.match(ui, /function MarkFiledDialog/,
    "there must be one dialog, not a copy per tab — the two returns lock the " +
    "period through the same record_filing");
  // Rendered by both.
  assert.equal((ui.match(/<MarkFiledDialog/g) ?? []).length, 2,
    "both the GSTR-1 and GSTR-3B tabs must render it");
  // Offered by both.
  assert.equal((ui.match(/Mark as filed/g) ?? []).length, 2,
    "both tabs must offer the action");
});

test("the ARN and the real filing date are what get sent", () => {
  const ui = code(GST);
  assert.equal((ui.match(/arn: arn \|\| undefined, filed_date: filedDate/g) ?? []).length, 2,
    "both tabs must send the acknowledgement and the date the CA gives");
  // An empty ARN goes as undefined rather than "": the column is nullable and
  // an empty string is a recorded acknowledgement of nothing.
  assert.doesNotMatch(ui, /arn:\s*arn\s*,/,
    "an unrecorded ARN must be omitted, not sent as an empty string");
  // MISSED ON THE FIRST PASS: the above only proves the two markFiled()
  // helpers BUILD the pair. Dropping `...(extra ?? {})` from the PATCH body
  // left both helpers intact and both fields unsent — which is precisely the
  // defect, since the endpoint has always accepted them and no screen ever
  // sent one. Both request bodies are pinned now.
  assert.equal(
    (ui.match(/JSON\.stringify\(\{ status, ca_approved: true, \.\.\.\(extra \?\? \{\}\) \}\)/g) ?? []).length,
    2,
    "both status PATCHes must carry what markFiled() passes them; the ARN and " +
    "the date are dropped otherwise, silently");
});

test("the date is required and the ARN is not", () => {
  const ui = code(GST);
  assert.match(ui, /disabled=\{saving \|\| !filedDate\}/,
    "the date is what the period lock and the §37(3) window key on");
  assert.match(ui, /can be left blank and added later/,
    "the dialog must say the ARN is optional — a CA marking a return filed " +
    "without it to hand must still be able to record reality");
});

test("a refusal from the workspace router is shown, not swallowed", () => {
  const ui = code(GST);
  // The GST workspace answers a declined request as HTTP 200 with
  // {success: false}. GSTR1Tab.updateStatus used to ignore that entirely and
  // call load(), so a refused approval looked like a successful one.
  assert.equal((ui.match(/if \(!r\.success\) \{ setRowError/g) ?? []).length >= 2, true,
    "every status PATCH must check res.success");
  assert.doesNotMatch(
    ui.slice(ui.indexOf("function GSTR1Tab"), ui.indexOf("function GSTR3BTab")),
    /await apiFetch\(`\/api\/gst-workspace\/gstr1\/\$\{id\}\/status`[\s\S]{0,200}\}\);\s*load\(\);/,
    "the GSTR-1 tab must not PATCH and reload without reading the answer");
});

test("the action is offered only on an approved return", () => {
  const ui = code(GST);
  // A draft has nothing to file; a submitted one is already recorded and the
  // server refuses the transition. A control that exists to be told no is the
  // dead-control fault this codebase keeps removing.
  const marks = [...ui.matchAll(
    /\{r\.status === "ca_approved" && \([^]{0,400}?setFilingRow\(\{/g)];
  assert.equal(marks.length, 2, "both tabs must gate it on ca_approved");
  // And never offered on a draft or a return already recorded as filed.
  assert.doesNotMatch(ui, /\{r\.status === "draft"[^]{0,400}?setFilingRow\(\{/);
  assert.doesNotMatch(ui, /\{r\.status === "submitted"[^]{0,400}?setFilingRow\(\{/);
});

test("a submitted GSTR-1 says whether an ARN was recorded", () => {
  const ui = code(GST);
  assert.match(ui, /filed — no ARN recorded/,
    "an absent acknowledgement is a fact worth showing, not a blank cell");
});

// ── PAY-24 ───────────────────────────────────────────────────────────────────

test("an unrecorded leave entitlement is not filled in with 12/12/15", () => {
  const ui = code(ATT);
  assert.doesNotMatch(ui, /casual_leave_balance \?\? 12/);
  assert.doesNotMatch(ui, /sick_leave_balance \?\? 12/);
  assert.doesNotMatch(ui, /earned_leave_balance \?\? 15/);
  for (const k of ["casual", "sick", "earned"]) {
    assert.match(ui, new RegExp(`existing\\?\\.${k}_leave_balance \\?\\? null`),
      `${k} leave must come back null where no row exists`);
  }
});

test("Remaining is not computed against an allocation nobody set", () => {
  const ui = code(ATT);
  assert.match(ui, /allotted == null \? null : allotted - \(used \?\? 0\)/,
    "remaining must be null where the entitlement is");
  assert.doesNotMatch(ui, /const clRem = \(form\.casual_leave_balance \?\? lb\.casual_leave_balance\) -/,
    "the old subtraction against a possibly-invented figure is back");
});

test("the screen says what it does not do", () => {
  const ui = code(ATT);
  assert.match(ui, /has not been recorded for \{leaveYear\}; it is not/,
    "an em dash needs a sentence saying it is not zero and not a default");
  assert.match(ui, /accrues leave monthly or carries a\s+balance into the next year/,
    "accrual and carry-forward are not modelled and the screen must say so");
});

test("saving nothing writes nothing", () => {
  const ui = code(ATT);
  assert.match(ui, /if \(lb\.casual_leave_balance == null\s*&& lb\.sick_leave_balance == null\s*&& lb\.earned_leave_balance == null\)/,
    "an upsert of three nulls creates a row that says 'recorded' and holds " +
    "no entitlement — the same ambiguity, one table down");
});
