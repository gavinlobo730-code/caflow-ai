// Which fee-invoice statuses are owed. Run with:
//   node --experimental-strip-types --test lib/constants/feeInvoiceStatus.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  FEE_INVOICE_STATUSES, OWED_FEE_INVOICE_STATUSES, isOwedFeeInvoice,
} from "./feeInvoiceStatus.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MIGRATIONS = path.join(__dirname, "../../../api/migrations");

/** The status list of the LAST migration that (re)defines the CHECK — found
 *  by number, never by naming a file, so a later migration widening it is the
 *  one this reads. */
function checkFromMigrations(): { file: string; statuses: string[] } {
  const files = fs.readdirSync(MIGRATIONS).filter((f) => /^\d+_.*\.sql$/.test(f)).sort();
  let found: { file: string; statuses: string[] } | null = null;
  for (const f of files) {
    const sql = fs.readFileSync(path.join(MIGRATIONS, f), "utf8");
    const m = /ADD\s+CONSTRAINT\s+fee_invoices_status_check\s+CHECK\s*\(\s*status\s+IN\s*\(([^)]*)\)/i.exec(sql);
    if (m) found = { file: f, statuses: Array.from(m[1].matchAll(/'([^']+)'/g), (x) => x[1]) };
  }
  assert.ok(found, "no migration defines fee_invoices_status_check — this guard is looking at nothing");
  return found;
}

test("the vocabulary is the database CHECK's, in full", () => {
  const { file, statuses } = checkFromMigrations();
  assert.deepEqual([...FEE_INVOICE_STATUSES], statuses,
    `lib/constants/feeInvoiceStatus.ts disagrees with ${file}; place any new status on one side of the owed line`);
});

test("owed is Issued, Sent and Overdue — and every owed status exists", () => {
  assert.deepEqual([...OWED_FEE_INVOICE_STATUSES].sort(), ["Issued", "Overdue", "Sent"]);
  for (const s of OWED_FEE_INVOICE_STATUSES) {
    assert.ok((FEE_INVOICE_STATUSES as readonly string[]).includes(s), `${s} is not a status the table can hold`);
  }
});

test("a draft, a paid and a cancelled invoice are not owed", () => {
  // Draft is the one that shipped as a debt: the aged report kept
  // `status !== "Paid"` and offered a WhatsApp reminder for it.
  for (const s of ["Draft", "Paid", "Cancelled"]) assert.equal(isOwedFeeInvoice(s), false, s);
  for (const s of ["Issued", "Sent", "Overdue"]) assert.equal(isOwedFeeInvoice(s), true, s);
});

test("an absent or unknown status is not owed", () => {
  assert.equal(isOwedFeeInvoice(null), false);
  assert.equal(isOwedFeeInvoice(undefined), false);
  assert.equal(isOwedFeeInvoice(""), false);
  // Case matters: the CHECK is case-sensitive, so "issued" cannot be stored.
  assert.equal(isOwedFeeInvoice("issued"), false);
});
