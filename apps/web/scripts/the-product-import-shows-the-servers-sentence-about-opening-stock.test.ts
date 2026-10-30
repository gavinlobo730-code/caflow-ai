// The product import shows the server's sentence when opening stock was not recorded (POST-A-092, the bulk-import half).
//
// WHAT THE SCREEN DID
//   The bulk import counted the products the server created and the rows it refused, and said "imported". The server seeds the
//   opening stock after the insert and never fails the import when that is refused, so a stock list whose stock did not land read as
//   a success while every product showed 0 on hand. The server now answers `opening_stock` with the items that have no opening row
//   and one sentence (`domain/inventory/opening_stock_report`), and the screen puts that sentence into the import result as written.
//
// THE RULES HELD HERE, from the browser's side of a figure:
//   * the sentence is the server's: the screen words nothing and counts nothing of its own about the opening stock;
//   * it goes into the import's error list, the part of the result a person reads, and nothing is shown when there is no sentence.
//
// The backend half is `apps/api/tests/test_a_bulk_product_import_says_when_its_opening_stock_was_not_recorded.py`.
//
// Run with: node --experimental-strip-types --test scripts/the-product-import-shows-the-servers-sentence-about-opening-stock.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const PANEL = stripComments(fs.readFileSync(path.join(WEB, "components/catalogue/ProductServiceManagerPanel.tsx"), "utf8"));

test("the file is where this guard thinks it is", () => {
  assert.ok(PANEL.length > 5000, `the product panel read as ${PANEL.length} chars`);
  assert.ok(PANEL.includes("api.serviceCatalogue.bulkCreate("), "the panel no longer imports through the bulk route");
});

test("the response type carries the server's opening_stock sentence", () => {
  assert.ok(/opening_stock\?: \{ message: string \| null \};/.test(PANEL), "the bulk response type does not carry opening_stock");
});

test("the sentence is pushed into the import's errors as the server wrote it, and only when there is one", () => {
  assert.ok(/if \(res\.data\.opening_stock\?\.message\) errors\.push\(res\.data\.opening_stock\.message\);/.test(PANEL),
    "the server's opening-stock sentence is not put in the import result as written");
  assert.ok(!/opening_stock\??\.(asked|recorded|not_recorded)/.test(PANEL), "the screen counts the opening stock itself");
});
