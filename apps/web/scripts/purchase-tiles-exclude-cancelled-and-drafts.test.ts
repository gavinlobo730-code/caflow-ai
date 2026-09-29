// apex-sales-purchases-07 / sweep-accounting-hub-1-02: the Purchase Bills
// tab's "Bills in Selected Period" / "Total Bills (Selected Period)" tiles
// summed total_paise over EVERY bill in the period, including CANCELLED ones
// (never a real supply), and "Outstanding Payable" computed from
// net_payable_paise excluding only paid/cancelled (so a DRAFT — not yet
// received, no journal posted — still counted) instead of the GENERATED
// outstanding_paise column, which alone accounts for partial payments and
// credit/debit notes.
//
// THE FIX
//     `live` excludes both cancelled and draft bills. The period tiles and
//     count are computed over `live` only (with a "(+N cancelled)" aside on
//     the count), and the payable tile reads outstanding_paise with a
//     net_payable_paise fallback.
//
// Run with:
//   node --experimental-strip-types --test scripts/purchase-tiles-exclude-cancelled-and-drafts.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const SRC = stripComments(fs.readFileSync(path.join(WEB, "app/clients/[id]/purchases/page.tsx"), "utf8"));

test("`live` bills exclude both cancelled and draft", () => {
  assert.match(
    SRC,
    /const live = bills\.filter\(\(b\) => !\["cancelled", "draft"\]\.includes\(b\.status\)\);/,
  );
});

test("the payable tile reads the GENERATED outstanding_paise column, falling back to net_payable_paise", () => {
  assert.match(
    SRC,
    /const totalPayable = live\.filter\(\(b\) => b\.status !== "paid"\)\s*\n\s*\.reduce\(\(s, b\) => s \+ Number\(b\.outstanding_paise \?\? b\.net_payable_paise\), 0\);/,
  );
  // The negative control: the old line summed net_payable_paise directly and
  // filtered only paid/cancelled — never excluding a draft, never reading the
  // generated column.
  assert.doesNotMatch(
    SRC,
    /bills\.filter\(\(b\) => !\["paid", "cancelled"\]\.includes\(b\.status\)\)\s*\n\s*\.reduce\(\(s, b\) => s \+ b\.net_payable_paise, 0\);/,
  );
});

test("the period total and count are computed over `live`, not the unfiltered `bills`", () => {
  assert.match(SRC, /const totalThisFy = live\.reduce\(\(s, b\) => s \+ b\.total_paise, 0\);/);
  assert.match(SRC, /\{loadFailed \? "—" : live\.length\}/);
  assert.doesNotMatch(SRC, /const totalThisFy = bills\.reduce\(\(s, b\) => s \+ b\.total_paise, 0\);/);
  assert.doesNotMatch(SRC, /\{loadFailed \? "—" : bills\.length\}/);
});

test("PurchaseBillRow itself carries outstanding_paise so the tile can read it", () => {
  const m = /interface PurchaseBillRow \{([\s\S]*?)\n\}/.exec(SRC);
  assert.ok(m, "PurchaseBillRow interface not found");
  assert.match(m[1], /outstanding_paise\?: number \| null;/);
});
