/**
 * POST-A-104 — an invoice line raised from a sales order keeps the order line it bills through every hand-off the browser makes, and an
 * order made on the screen carries the catalogue item an invoice line will need.
 *
 * The helper tests (`lib/sales/orderInvoiceSeed.test.ts`) hold the seed → editor detail and the editor line → payload. What they cannot
 * see is the two hand-offs inside components: a draft re-opened in the editor maps its stored lines to editor lines, and dropping the link
 * there would make the next save re-insert every line without it (a draft's lines are deleted and inserted again), quietly unbilling
 * the order; and the sales-cycle form builds the lines it sends, and an order line with no catalogue item seeds an invoice line the
 * editor will not save until a product is picked, which then overwrites the order's price.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

/** The body of a top-level function, by brace depth from its declaration. */
function functionBody(src: string, name: string): string {
  const at = src.search(new RegExp(`function\\s+${name}\\s*\\(`));
  assert.ok(at >= 0, `function ${name} not found`);
  const open = src.indexOf("{", src.indexOf(")", at));
  let depth = 0;
  for (let i = open; i < src.length; i++) {
    if (src[i] === "{") depth++;
    else if (src[i] === "}" && --depth === 0) return src.slice(open, i + 1);
  }
  throw new Error(`function ${name} does not close`);
}

test("a draft re-opened in the editor keeps each line's order link, and the save hands the whole line to the payload", () => {
  const editor = code("components/invoices/InvoiceEditor.tsx");
  assert.match(functionBody(editor, "detailLinesToEditorLines"), /salesOrderLineId:\s*l\.sales_order_line_id\b/);
  assert.match(editor, /lines\.filter\(isValidLine\)\.map\(toInvoiceLinePayload\)/,
    "the save must hand each whole editor line to the one payload builder, which sends the link");
});

test("the editor says on the line that it bills an order, and offers to stop", () => {
  const editor = code("components/invoices/InvoiceEditor.tsx");
  assert.match(editor, /line\.salesOrderLineId\s*&&/);
  assert.match(editor, /Bills a line of a sales order/);
  assert.match(editor, /setLine\(idx,\s*\{\s*salesOrderLineId:\s*undefined\s*\}\)/);
});

test("an order, quotation or challan line made on the screen sends the catalogue item it was picked from", () => {
  const tab = code("components/sales/SalesCycleTab.tsx");
  const build = tab.slice(tab.indexOf("const buildLines"), tab.indexOf("async function save"));
  assert.match(build, /service_catalogue_id:\s*l\.service_catalogue_id/);
  assert.match(build, /is_service:\s*l\.is_service/);
  assert.match(tab, /<ServiceCataloguePicker[\s\S]*?ariaLabel=\{`Line \$\{i \+ 1\} product or service`\}/);
});
