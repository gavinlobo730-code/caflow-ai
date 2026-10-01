// ACC-17 — the spreadsheet side of the voucher import, as pure functions. What
// the SERVER decides (balance, ledger, period, duplicate) is pinned in
// apps/api/tests/test_voucher_import.py; this is the conversion the browser owns.
//
// Run with: node --experimental-strip-types --test lib/accounting/voucherImport.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  buildVoucherLegs, chunkVouchers, mergeVoucherResults, voucherColumns,
  voucherOutcomeFrom, voucherSummarySentence, VOUCHERS_PER_REQUEST,
} from "./voucherImport.ts";
import type { VoucherImportLeg, VoucherImportResult } from "../api/index.ts";

const line = (over: Record<string, string> = {}) => ({
  voucher_no: "JV-1", date: "05-04-2026", voucher_type: "Journal", account: "Rent Expense",
  debit: "1,25,000.50", credit: "", narration: "April rent", line_narration: "", ...over,
});

test("the two layouts share their first three columns and differ after", () => {
  const lines = voucherColumns("lines").map((c) => c.key);
  const simple = voucherColumns("simple").map((c) => c.key);
  assert.deepEqual(lines.slice(0, 3), ["voucher_no", "date", "voucher_type"]);
  assert.deepEqual(simple.slice(0, 3), ["voucher_no", "date", "voucher_type"]);
  assert.ok(lines.includes("account") && lines.includes("debit") && lines.includes("credit"));
  assert.ok(simple.includes("debit_account") && simple.includes("credit_account") && simple.includes("amount"));
});

test("debit and credit are optional columns and the identifying ones are required", () => {
  const req = (l: "lines" | "simple") => voucherColumns(l).filter((c) => c.required).map((c) => c.key);
  assert.deepEqual(req("lines"), ["voucher_no", "date", "voucher_type", "account"]);
  assert.deepEqual(req("simple"), ["voucher_no", "date", "voucher_type", "debit_account", "credit_account", "amount"]);
});

test("a line sheet row is one leg, in exact paise, with the blank side nil", () => {
  const [leg] = buildVoucherLegs([line()], "lines");
  assert.equal(leg.debit_paise, 12_500_050);
  assert.equal(leg.credit_paise, 0);
  assert.equal(leg.account, "Rent Expense");
  assert.equal(leg.narration, "April rent");
  assert.equal(leg.line_narration, null);
});

test("a cell that is not an amount travels as null, never as a number", () => {
  for (const bad of ["12abc", "1e3", "1.234", "abc", "Rs. ten"]) {
    const [leg] = buildVoucherLegs([line({ debit: bad })], "lines");
    assert.equal(leg.debit_paise, null, `"${bad}" should not be an amount`);
  }
});

test("a one-row-per-voucher sheet becomes its two legs on the SAME row number", () => {
  const rows = [{ voucher_no: "PV-1", date: "05-04-2026", voucher_type: "Payment",
                  debit_account: "Rent Expense", credit_account: "HDFC Bank",
                  amount: "5,000.00", narration: "April rent" }];
  const legs = buildVoucherLegs(rows, "simple", [7]);
  assert.equal(legs.length, 2);
  assert.deepEqual(legs.map((l) => l.row), [7, 7]);
  assert.deepEqual(legs.map((l) => [l.account, l.debit_paise, l.credit_paise]),
    [["Rent Expense", 500_000, 0], ["HDFC Bank", 0, 500_000]]);
  assert.ok(legs.every((l) => l.voucher_no === "PV-1" && l.narration === "April rent"));
});

test("an unreadable amount on a simple row is null on BOTH legs, so the row is refused by number", () => {
  const legs = buildVoucherLegs([{ voucher_no: "PV-2", date: "05-04-2026", voucher_type: "Payment",
    debit_account: "A", credit_account: "B", amount: "ten", narration: "" }], "simple");
  assert.equal(legs[0].debit_paise, null);
  assert.equal(legs[1].credit_paise, null);
});

test("dates, types and ledgers go up exactly as typed — the server reads them", () => {
  const [leg] = buildVoucherLegs([line({ date: "4/1/26", voucher_type: "pAyMeNt", account: " rent expense " })], "lines");
  assert.equal(leg.date, "4/1/26");
  assert.equal(leg.voucher_type, "pAyMeNt");
  assert.equal(leg.account, "rent expense");
});

test("the preview's row numbers survive the rows the dialog held back", () => {
  const legs = buildVoucherLegs([line(), line(), line()], "lines", [1, 2, 5]);
  assert.deepEqual(legs.map((l) => l.row), [1, 2, 5]);
});

const leg = (vno: string, row: number): VoucherImportLeg => ({
  row, voucher_no: vno, date: "05-04-2026", voucher_type: "Journal", account: "A",
  debit_paise: 1, credit_paise: 0,
});

test("a request never splits a voucher, even when its lines are scattered", () => {
  // A journal sheet sorted by date scatters one voucher's lines; the server
  // judges a voucher only when it sees all of them in one request.
  const legs = [leg("A", 1), leg("B", 2), leg("A", 3), leg("C", 4), leg("B", 5)];
  const batches = chunkVouchers(legs, 2);
  assert.deepEqual(batches.map((b) => b.map((l) => l.voucher_no)),
    [["A", "A", "B", "B"], ["C"]]);
  assert.deepEqual(batches[0].map((l) => l.row), [1, 3, 2, 5]);
});

test("a long file becomes many small requests and loses no leg", () => {
  const legs: VoucherImportLeg[] = [];
  for (let i = 0; i < 200; i++) { legs.push(leg(`V${i}`, 2 * i + 1), leg(`V${i}`, 2 * i + 2)); }
  const batches = chunkVouchers(legs);
  assert.equal(VOUCHERS_PER_REQUEST, 20);
  assert.equal(batches.length, 10);
  assert.ok(batches.every((b) => new Set(b.map((l) => l.voucher_no)).size <= VOUCHERS_PER_REQUEST));
  assert.equal(batches.flat().length, 400);
});

test("vouchers with no number share one group so the server reports them together", () => {
  const batches = chunkVouchers([leg("", 1), leg("X", 2), leg("", 3)], 5);
  assert.equal(batches.length, 1);
  assert.deepEqual(batches[0].map((l) => l.row), [1, 3, 2]);
});

const verdict = (over: Partial<VoucherImportResult["results"][number]>) => ({
  voucher_no: "V", rows: [1], status: "new" as const, problems: [] as string[],
  entry_date: "2026-04-05", entry_type: "Journal", total_paise: 100, id: "x", ...over,
});

const part = (over: Partial<VoucherImportResult> = {}): VoucherImportResult => ({
  status: "posted", dry_run: false, vouchers: 3, created: 1, would_create: 0,
  already_recorded: 1, rejected: 1, created_paise: 100, would_create_paise: 0,
  results: [
    verdict({ voucher_no: "A", rows: [1, 2] }),
    verdict({ voucher_no: "B", rows: [3, 4], status: "already_recorded" }),
    verdict({ voucher_no: "C", rows: [5], status: "rejected", problems: ["Row 5: the date is blank.", "The voucher does not balance."] }),
  ], ...over,
});

test("batches' answers add up", () => {
  const m = mergeVoucherResults([part(), part({ created: 4, created_paise: 400 })]);
  assert.equal(m.vouchers, 6);
  assert.equal(m.created, 5);
  assert.equal(m.created_paise, 500);
  assert.equal(m.already_recorded, 2);
  assert.equal(m.rejected, 2);
  assert.equal(m.results.length, 6);
});

test("nothing merged is still an answer, not a crash", () => {
  const m = mergeVoucherResults([]);
  assert.equal(m.vouchers, 0);
  assert.deepEqual(m.results, []);
});

test("verdicts become the dialog's counters and lists, by voucher and rows", () => {
  const out = voucherOutcomeFrom(part());
  assert.equal(out.imported, 1);
  assert.equal(out.skipped, 1);
  assert.deepEqual(out.skippedDetail, ["Voucher B (Rows 3, 4): already on the books — nothing added"]);
  assert.deepEqual(out.errors, [
    "Voucher C (Row 5): Row 5: the date is blank. The voucher does not balance.",
  ]);
});

test("a malformed answer cannot crash the report", () => {
  const out = voucherOutcomeFrom(part({ results: undefined as unknown as [] }));
  assert.deepEqual(out.errors, []);
});

test("the summary says where the vouchers went", () => {
  const rupees = (p: number) => `₹${(p / 100).toFixed(2)}`;
  assert.equal(voucherSummarySentence(part(), "posted", rupees),
    "1 voucher posted to the ledger (₹1.00), 1 already there, 1 refused.");
  assert.match(voucherSummarySentence(part({ created: 3, created_paise: 300, rejected: 0, already_recorded: 0 }), "draft", rupees),
    /^3 vouchers saved as drafts — off the books until posted \(₹3\.00\)\.$/);
});
