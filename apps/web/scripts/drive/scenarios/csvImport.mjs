/**
 * Group: the shared import dialog (`CsvImportModal`), driven in a browser (POST-A-390).
 *
 * Ten screens import a customer, vendor, product, employee, bill or note file through the one dialog, and its "Import N rows" button awaited the
 * screen's own import call and moved the dialog to its "importing" step only AFTER the call had started. Two clicks in one tick therefore started two
 * imports of the same file. A master (a customer, a vendor, a product) is protected by the server's name, GSTIN and PAN checks, which report the second
 * copy as skipped; a bill, a note or a journal is not obviously idempotent. The repeat-click source guard named the button "NOT harmless" and listed it
 * as the one raw button of its kind; this is the browser half of that rule.
 *
 * The vendors screen stands for them: the dialog is the same component, and the only thing the screen supplies is the call.
 */
import assert from "node:assert/strict";
import { expectWrites, sameTickDouble, until } from "../kit.mjs";
import { ok } from "../stub.mjs";

export const group = "csv-import";

const BULK = /api\/vendors\/bulk$/;

/** Purchases > Vendors with the import dialog open and a one-row file chosen, so the preview offers "Import 1 row". */
async function atThePreview(env) {
  const { page, stub } = env;
  // The answer is held for a moment, so the first import is still out when the dialog is looked at again.
  stub.route({ method: "POST", re: BULK, delay: 700, reply: () => ok({ created: [{ id: "v-9", name: "Acme Traders" }], duplicates: [], errors: [] }) });
  await page.goto(env.at("/purchases/?tab=vendors"), { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Import", exact: true }).click();
  await page.locator('input[aria-label="CSV or Excel file to import"]').setInputFiles({
    name: "vendors.csv", mimeType: "text/csv", buffer: Buffer.from("name\nAcme Traders\n") });
  await page.getByRole("button", { name: /^Import \d+ rows?$/ }).waitFor({ timeout: 10000 });
}

export const scenarios = [
  {
    id: "two-clicks-on-import-in-one-tick-import-the-file-once",
    title: "Purchases > Vendors > Import: \"Import 1 row\" pressed twice in the same tick sends ONE bulk request, and the dialog reaches its done step",
    async run(env) {
      const { page, stub } = env;
      await atThePreview(env);
      await sameTickDouble(page.getByRole("button", { name: /^Import \d+ rows?$/ }));
      await expectWrites(stub, BULK, 1, "importing a file", "POST");
      await page.getByText("1 new record imported").waitFor({ timeout: 10000 });
      assert.equal(stub.writesTo(BULK, "POST").length, 1, "the file was imported more than once");
    },
  },
  {
    id: "a-single-click-on-import-imports-the-file-and-the-dialog-says-so",
    title: "Purchases > Vendors > Import: one click sends one bulk request carrying the file's row, and nothing is held back for the next file",
    async run(env) {
      const { page, stub } = env;
      await atThePreview(env);
      await page.getByRole("button", { name: /^Import \d+ rows?$/ }).click();
      await page.getByText("1 new record imported").waitFor({ timeout: 10000 });
      await expectWrites(stub, BULK, 1, "importing a file", "POST");
      const [write] = stub.writesTo(BULK, "POST");
      const sent = JSON.parse(write.body).vendors;
      assert.equal(sent.length, 1, `expected the file's one row, the request carried ${sent.length}`);
      assert.equal(sent[0].name, "Acme Traders", `the request carried ${JSON.stringify(sent[0])}`);
      // The button is gone once the import has run (the dialog is on its done step), so a late click has nothing to press.
      await until(async () => (await page.getByRole("button", { name: /^Import \d+ rows?$/ }).count()) === 0, "the Import button to go once the file was imported", 5000);
    },
  },
];
