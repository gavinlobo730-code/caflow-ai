// apex-sales-purchases-08: the Sales Invoices tile labels read "Outstanding
// This FY" / "Issued This FY" / "Paid This FY" unconditionally, although the
// underlying figures are scoped to whatever PERIOD the picker on that tab is
// set to — so picking "All Time" or "Last FY" still showed a tile headed
// "This FY" over the figure for a different period entirely. Separately, the
// "Paid" tile only summed FULLY paid invoices at their gross total, so a
// partially-paid invoice — real cash the client actually collected —
// contributed nothing to it.
//
// THE FIX
//     The three labels are built from periodOptionLabel(periodMode,
//     financialYear), the same helper the Purchases tab already uses for its
//     own period-scoped heading, so the label always names the period the
//     figure below it is actually for. "Paid" now sums paid_paise (cash
//     actually received) across BOTH "paid" and "partially_paid" invoices.
//
// Run with:
//   node --experimental-strip-types --test scripts/sales-tiles-name-the-selected-period.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const SRC = stripComments(fs.readFileSync(path.join(WEB, "app/clients/[id]/sales/page.tsx"), "utf8"));

test("periodOptionLabel is imported from lib/dates/periods", () => {
  assert.match(SRC, /import \{[^}]*periodOptionLabel[^}]*\} from "@\/lib\/dates\/periods";/);
});

test("the three summary tiles are labelled with the selected period, not a hardcoded 'This FY'", () => {
  assert.doesNotMatch(SRC, /label="Outstanding This FY"/);
  assert.doesNotMatch(SRC, /label="Issued This FY"/);
  assert.doesNotMatch(SRC, /label="Paid This FY"/);
  assert.match(SRC, /label=\{`Outstanding — \$\{periodOptionLabel\(periodMode, financialYear\)\}`\}/);
  assert.match(SRC, /label=\{`Issued — \$\{periodOptionLabel\(periodMode, financialYear\)\}`\}/);
  assert.match(SRC, /label=\{`Paid — \$\{periodOptionLabel\(periodMode, financialYear\)\}`\}/);
});

test("the Paid tile sums paid_paise across BOTH paid and partially_paid invoices", () => {
  assert.match(
    SRC,
    /if \(inv\.status === "paid" \|\| inv\.status === "partially_paid"\) paid \+= inv\.paid_paise \?\? 0;/,
  );
  // The negative control: the old line summed only fully-paid invoices, at
  // their GROSS total.
  assert.doesNotMatch(SRC, /if \(inv\.status === "paid"\) paid \+= inv\.total_paise;/);
});
