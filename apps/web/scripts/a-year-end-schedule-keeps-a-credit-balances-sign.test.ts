// The year-end Cash & Bank schedule shows an overdrawn (credit-balance) bank
// account as NEGATIVE, matching the backend's own financial-statements API,
// instead of silently flipping it positive (apex-payroll-yearend-05).
//
// Run with:
//   node --experimental-strip-types --test \
//     scripts/a-year-end-schedule-keeps-a-credit-balances-sign.test.ts
//
// WHAT WAS WRONG
//     `fmt(paise)` in schedules/_page.tsx did `Math.abs(paise)` and never
//     restored the sign, so a credit-balance bank account rendered as a
//     POSITIVE amount on every row it appeared in, including the schedule's
//     own Total row — the same table both read through this one function.
//
// THE FIX
//     The same pattern components/payroll/EmployeeDrawer.tsx's own fmt()
//     already uses: the magnitude through formatPaise, " Cr" appended for a
//     negative figure.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const FILE = "app/clients/[id]/year-end/[engagementId]/schedules/_page.tsx";

function read(): string {
  return stripComments(fs.readFileSync(path.join(WEB, FILE), "utf8"));
}

test("fmt no longer discards the sign with an unconditional Math.abs", () => {
  const src = read();
  const m = /function fmt\(paise: number\): string \{([\s\S]*?)\n\}/.exec(src);
  assert.ok(m, "fmt(paise) not found");
  const body = m[1];
  assert.match(body, /formatPaise\(Math\.abs\(paise\)\)/,
    "the magnitude must still go through the one formatter");
  assert.match(body, /\(paise < 0 \? " Cr" : ""\)/,
    "a negative figure must be marked, the same way EmployeeDrawer's fmt() does");
});

test("formatPaise is imported from the one money-formatting module", () => {
  const src = read();
  assert.match(src, /import \{ formatPaise \} from "@\/lib\/money\/format"/);
});

test("both the per-line cells and the Total row read through fmt — there is no second formatter", () => {
  const src = read();
  const fmtCalls = src.match(/\bfmt\(/g) ?? [];
  // renderCell's per-line call and the totals-row call in ScheduleTable, plus
  // fmt's own definition is not a call — at least two call sites.
  assert.ok(fmtCalls.length >= 2, `expected at least 2 calls to fmt(), found ${fmtCalls.length}`);
  assert.doesNotMatch(src, /Intl\.NumberFormat/,
    "a second, local Intl.NumberFormat is the old, sign-discarding implementation");
});
