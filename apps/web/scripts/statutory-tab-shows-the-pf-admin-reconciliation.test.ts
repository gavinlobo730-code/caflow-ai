// StatutoryTab renders the server's own PF-admin reconciling sentence
// (statutory_summary's `pf_admin_reconciliation`) rather than only the
// already-floored challan figure (apex-payroll-yearend-10).
//
// Run with:
//   node --experimental-strip-types --test \
//     scripts/statutory-tab-shows-the-pf-admin-reconciliation.test.ts
//
// WHAT WAS WRONG
//     The PF Challan card showed only the FLOORED admin charge
//     (`total_pf_admin_paise`, the ₹500-per-establishment minimum settled
//     once on the run total), while the salary register and every payslip
//     PDF show each employee's own true, unfloored 0.5%. Nothing on this
//     screen said the two never foot to the same number for a client small
//     enough that the floor actually bit.
//
// THE FIX
//     `statutory_summary` now serves `pf_admin_reconciliation` — a sentence
//     it composes from the real per-slip sum and the floor's own top-up —
//     and this tab renders it verbatim, never recomposing it.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const PAGE = "app/clients/[id]/payroll/page.tsx";

function read(): string {
  return stripComments(fs.readFileSync(path.join(WEB, PAGE), "utf8"));
}

test("StatutoryData carries the three new reconciling fields", () => {
  const src = read();
  assert.match(src, /pf_admin_per_slip_paise\?: number/);
  assert.match(src, /pf_admin_topup_paise\?: number/);
  assert.match(src, /pf_admin_reconciliation\?: string/);
});

/** The source from `function <name>(` through to the next top-level
 *  `function` — robust against a stripped JSX comment leaving behind an
 *  empty `{\n\n}\n` expression container, which a naive "first `\n}\n`"
 *  search stops at prematurely. */
function functionBody(src: string, name: string): string {
  const m = new RegExp(`(?:^|\\n)function ${name}\\(`).exec(src);
  assert.ok(m, `function ${name} not found`);
  const start = m.index;
  const rest = src.slice(start + 1);
  const next = rest.search(/\nfunction |\nexport default function /);
  return next === -1 ? src.slice(start) : src.slice(start, start + 1 + next);
}

test("StatutoryTab renders the server's own sentence verbatim", () => {
  const body = functionBody(read(), "StatutoryTab");
  assert.match(body, /\{data\?\.pf_admin_reconciliation && \(/);
  assert.match(body, /\{data\.pf_admin_reconciliation\}/,
    "the sentence must be rendered as-is, not recomposed from the numeric fields");
});
