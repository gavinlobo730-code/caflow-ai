/**
 * A BOX THAT IS TYPED IN AND CANNOT BE READ IS REFUSED BY NAME, AND IS NEVER SAVED AS NOTHING (POST-A-571, POST-A-569), driven in a browser.
 *
 * A form that read a box with `reader(text) ?? 0` turned the reader's refusal into a figure nobody typed: a revised basic typed 45,00 would be
 * saved as a basic of nothing, a quotation line with a rate of 12,50 as a rate of nothing. Each form now asks first. Against a stubbed server,
 * in Chromium:
 *
 *   1. an employee's Salary revisions: a Basic of 45,00 is refused in a sentence that names the box and sends nothing; a Basic grouped the way
 *      amounts are written (45,000) is sent once, as the paise it names;
 *   2. Sales > Quotes, Orders & Challans > New quotation: a rate of 12,50 is refused in a sentence that names the line's box and sends nothing;
 *      a rate of 1,250 and a quantity of 2 are sent once, as typed.
 *
 * Each scenario types one date and none turns on what day it is, so each runs once.
 */
import assert from "node:assert/strict";
import { openEmployeeDrawer, openSalesCycleForm, typeAndLeave } from "../scenarios/dates.mjs";

export const group = "unreadable-boxes";

const REVISION = /employees\/emp-1\/salary-revisions$/;
const QUOTATION = /api\/sales-cycle\/quotations$/;

export const scenarios = [
  {
    id: "a-revised-basic-that-cannot-be-read-is-refused-by-name-and-a-grouped-one-is-sent-as-the-paise-it-names",
    title: "Payroll > an employee > Salary revisions: Basic 45,00 is refused naming Basic and nothing is sent; Basic 45,000 is sent once as 45,00,000 paise",
    async run(env) {
      const { page, stub } = env;
      await openEmployeeDrawer("Salary revisions")(env);
      // The amount first and the date second, the order the date scenario of this form uses.
      // By the start of its name: while the box holds text that is not an amount, its label also carries "Not an amount.".
      const basic = page.getByLabel(/^Basic/);
      await basic.fill("45,00");
      await typeAndLeave(page.locator("#drawer-revision-effective-from"), "01/04/2026");
      const save = page.getByRole("button", { name: "Record revision", exact: true });
      await save.click();
      await page.getByText(/^Basic cannot be read\./).waitFor({ timeout: 8000 })
        .catch(() => { throw new Error("a Basic that cannot be read was not refused in a sentence that names it"); });
      await stub.quiet();
      assert.equal(stub.writesTo(REVISION, "POST").length, 0, "a revision whose Basic cannot be read WAS SENT");

      await basic.fill("45,000");
      await save.click();
      await stub.quiet();
      const sent = stub.writesTo(REVISION, "POST");
      assert.equal(sent.length, 1, `expected one revision, saw ${sent.length}`);
      assert.equal(JSON.parse(sent[0].body).basic_paise, 45_000_00, "a Basic of 45,000 was not sent as the paise it names");
    },
  },
  {
    id: "a-quotation-line-whose-rate-cannot-be-read-is-refused-by-name-and-a-grouped-rate-is-sent",
    title: "Sales > Quotes, Orders & Challans > New quotation: a rate of 12,50 is refused naming the line's box and nothing is sent; 1,250 at a quantity of 2 is sent once",
    async run(env) {
      const { page, stub } = env;
      await openSalesCycleForm("Quotations & Proforma", "QT/2026-27/0001")(env);
      await page.getByLabel("Line 1 quantity").fill("2");
      await page.getByLabel("Line 1 rate (₹)").fill("12,50");
      const save = page.getByRole("button", { name: "Save", exact: true });
      await save.click();
      await page.getByText(/^Line 1 rate cannot be read\./).waitFor({ timeout: 8000 })
        .catch(() => { throw new Error("a rate that cannot be read was not refused in a sentence that names the line"); });
      await stub.quiet();
      assert.equal(stub.writesTo(QUOTATION, "POST").length, 0, "a quotation whose rate cannot be read WAS SENT");

      await page.getByLabel("Line 1 rate (₹)").fill("1,250");
      await save.click();
      await stub.quiet();
      const sent = stub.writesTo(QUOTATION, "POST");
      assert.equal(sent.length, 1, `expected one quotation, saw ${sent.length}`);
      const line = JSON.parse(sent[0].body).lines[0];
      assert.equal(line.rate_paise, 125_000, "a rate of 1,250 was not sent as the paise it names");
      assert.equal(line.quantity, 2);
    },
  },
];
