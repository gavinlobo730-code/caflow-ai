// Trial Balance CSV parsing tests (C4) — run with:
//   node --experimental-strip-types --test lib/accounting/trialBalanceParser.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { parseCSV, detectType, parseAmount, buildParsedAccounts } from "./trialBalanceParser.ts";

const SAMPLE_CSV = `Account Name,Account Code,Debit Balance,Credit Balance,Account Type
Cash in Hand,1001,50000,0,Asset
Bank - HDFC Current,1002,250000,0,Asset
Sundry Debtors,1003,180000,0,Asset
Capital Account,3001,0,500000,Equity
Sales Account,4001,0,450000,Revenue
Purchase Account,5001,300000,0,Expense`;

test("successful import: a full sample CSV parses into correct paise amounts and types", () => {
  const rows = parseCSV(SAMPLE_CSV);
  const [headers, ...dataRows] = rows;
  assert.deepEqual(headers, ["Account Name", "Account Code", "Debit Balance", "Credit Balance", "Account Type"]);

  const colMap = { nameCol: 0, codeCol: 1, drCol: 2, crCol: 3, typeCol: 4 };
  const accounts = buildParsedAccounts(dataRows, colMap);

  assert.equal(accounts.length, 6);
  assert.deepEqual(accounts[0], {
    account_name: "Cash in Hand", account_code: "1001", account_type: "asset",
    dr_balance: "50000", cr_balance: "0", dr_paise: 50_000_00, cr_paise: 0,
  });
  assert.equal(accounts[3].account_type, "equity");
  assert.equal(accounts[3].cr_paise, 500_000_00);

  const totalDr = accounts.reduce((s, a) => s + a.dr_paise, 0);
  const totalCr = accounts.reduce((s, a) => s + a.cr_paise, 0);
  assert.equal(totalDr, 780_000_00);
  assert.equal(totalCr, 950_000_00);
});

test("quoted fields with embedded commas and escaped quotes parse correctly", () => {
  const csv = 'Name,Amount\n"Smith, Jones & Co","1,000.00"\n"He said ""hi""",500';
  const rows = parseCSV(csv);
  assert.deepEqual(rows[1], ["Smith, Jones & Co", "1,000.00"]);
  assert.deepEqual(rows[2], ['He said "hi"', "500"]);
});

test("account type auto-detection matches common ledger naming", () => {
  assert.equal(detectType("Sales Account"), "revenue");
  assert.equal(detectType("Purchase Account"), "expense");
  assert.equal(detectType("Rent Expense"), "expense");
  assert.equal(detectType("Sundry Debtors"), "asset");
  assert.equal(detectType("Sundry Creditors / Payable"), "liability");
  assert.equal(detectType("Capital Account"), "equity");
  assert.equal(detectType("Unrecognized Ledger Name"), "asset"); // conservative default
});

test("amount parsing strips currency symbols/commas and treats parens as negative-then-absolute", () => {
  assert.equal(parseAmount("50000"), 50_000_00);
  assert.equal(parseAmount("1,000.00"), 1_000_00);
  assert.equal(parseAmount("₹1,234.56"), 1_234_56);
  assert.equal(parseAmount("(500)"), 500_00); // always positive — Dr/Cr column decides sign
  assert.equal(parseAmount(""), 0);
  assert.equal(parseAmount("not a number"), 0);
});

test("rows with a blank account name are dropped from the parsed account list", () => {
  const rows = [["", "1", "100", "0", "Asset"], ["Valid Account", "2", "200", "0", "Asset"]];
  const accounts = buildParsedAccounts(rows, { nameCol: 0, codeCol: 1, drCol: 2, crCol: 3, typeCol: 4 });
  assert.equal(accounts.length, 1);
  assert.equal(accounts[0].account_name, "Valid Account");
});
