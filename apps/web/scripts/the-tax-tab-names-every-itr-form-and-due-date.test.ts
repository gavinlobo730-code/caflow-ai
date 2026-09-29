// app/clients/[id]/tax/page.tsx — the ITR Filing card's badge and the "Tax
// Filing Rules" box.
//
// Run with:
//   node --experimental-strip-types --test scripts/the-tax-tab-names-every-itr-form-and-due-date.test.ts
//
// TWO OMISSIONS FIXED:
//
// (1) THE BADGE NAMED ONLY FOUR OF THE SEVEN ITR FORMS ("ITR-3 / ITR-5 /
//     ITR-6 / ITR-7") although GET /api/itr/forms has served all seven since
//     IT-23 — so the badge read as though ITR-1, ITR-2 and ITR-4, which
//     between them cover most of a practice's salaried and presumptive
//     clients, were not supported at all.
//
// (2) THE "TAX FILING RULES" BOX NAMED ONLY THE ORDINARY §139(1) DATES and
//     said nothing about §44AB's audit-report date (30 September — a month
//     BEFORE the 31 October return, per compliance_engine.
//     tax_audit_report_due_date) or §92E's 30 November date for a
//     transfer-pricing report, both of which this product already computes.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const PAGE = "app/clients/[id]/tax/page.tsx";

function code(rel: string): string {
  return fs.readFileSync(path.join(ROOT, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

test("the ITR Filing badge no longer names only four of the seven forms", () => {
  const src = code(PAGE);
  assert.match(src, /badge:\s*"ITR-1 to ITR-7"/,
    "the badge must not enumerate a subset that omits ITR-1, ITR-2 and ITR-4");
  // NEGATIVE CONTROL: the old, incomplete badge string.
  assert.doesNotMatch(src, /"ITR-3 \/ ITR-5 \/ ITR-6 \/ ITR-7"/,
    "the incomplete four-form badge must be gone");
});

test("the Tax Filing Rules box names the §44AB audit-report date and the §92E date", () => {
  const src = code(PAGE);
  assert.match(src, /§44AB.*30th September/,
    "the audit report's own specified date (one month before the return) must be named");
  assert.match(src, /30th November where a §92E transfer-pricing report is required/,
    "and the transfer-pricing extension, which outranks the audit date");
});
