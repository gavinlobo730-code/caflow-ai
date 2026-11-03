// The product form shows the server's sentence when a single product's opening stock was not recorded (POST-A-092, the single-product half).
//
// WHAT THE SCREEN DID
//   Creating or editing a product saved the row and showed "created" or "updated". The server seeds the opening stock after the save and
//   logs, not raises, when that is refused, so a product whose opening stock did not land read as a success while its Stock column showed 0.
//   The server now answers `opening_stock` with one sentence, as it already does for the bulk import, and the form shows it as written.
//
// THE RULES HELD HERE, from the browser's side of a figure:
//   * the sentence is the server's: the form words nothing and counts nothing of its own about the opening stock;
//   * it is shown AFTER the "saved" it follows (the product exists) and only when there is one, through `onNotice` (an amber "succeeded, with a
//     consequence" sentence) and not as an error, which a host that passes none still gets through `onError`;
//   * EVERY host of the form passes `onNotice`, and the catalogue panel, which closes itself when a product created from an invoice or bill line is
//     handed to that line, stays open when there is a sentence so its own toast is not taken with it (an independent review found the sentence
//     was lost on exactly that path);
//   * the item type carries the key, so a screen that reads it is type-checked.
//
// The backend half is `apps/api/tests/test_a_single_product_says_when_its_opening_stock_was_not_recorded.py`.
//
// Run with: node --experimental-strip-types --test scripts/the-product-form-shows-the-servers-sentence-about-opening-stock.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));

/** What is wrong with the form's handling of the opening-stock sentence, as sentences (empty when it is right). */
export function formProblems(src: string): string[] {
  const found: string[] = [];
  const saved = src.indexOf("onSaved(res.data);");
  const said = src.indexOf("const said = res.data.opening_stock?.message;");
  const shown = src.indexOf("if (said) (onNotice ?? onError)(said);");
  if (saved === -1) found.push("the form no longer reports the save");
  if (said === -1) found.push("the form does not read the server's opening_stock sentence");
  if (shown === -1) found.push("the sentence is not shown through onNotice (falling back to onError), or is shown even when there is none");
  if (saved !== -1 && shown !== -1 && shown < saved) found.push("the sentence is shown before the save it follows");
  if (/opening_stock\??\.(asked|recorded|not_recorded|checked)/.test(src)) found.push("the form counts the opening stock itself");
  return found;
}

test("the file is where this guard thinks it is", () => {
  const src = read("components/catalogue/ProductServiceFormModal.tsx");
  assert.ok(src.length > 3000, `the product form read as ${src.length} chars`);
  assert.ok(src.includes("api.serviceCatalogue.create(") && src.includes("api.serviceCatalogue.update("), "the form no longer saves through the catalogue routes");
});

test("the form shows the server's sentence as written, after the save, and only when there is one", () => {
  assert.deepEqual(formProblems(read("components/catalogue/ProductServiceFormModal.tsx")), []);
});

test("each way of getting it wrong is found (negative controls on the real source)", () => {
  const src = read("components/catalogue/ProductServiceFormModal.tsx");
  assert.notDeepEqual(formProblems(src.replace("if (said) (onNotice ?? onError)(said);", "")), []);
  assert.notDeepEqual(formProblems(src.replace("const said = res.data.opening_stock?.message;", "const said = null as string | null;")), []);
  assert.notDeepEqual(formProblems(src.replace("onSaved(res.data);", "")), []);
  assert.notDeepEqual(formProblems(src.replace("if (said) (onNotice ?? onError)(said);", "if (said) onError(said);")), [], "a sentence shown as an error is found");
  assert.notDeepEqual(formProblems(src.replace("if (said) (onNotice ?? onError)(said);", "if (said) (onNotice ?? onError)(said); const n = res.data.opening_stock?.recorded;")), []);
  const before = src.replace("onSaved(res.data);", "").replace("if (said) (onNotice ?? onError)(said);", "if (said) (onNotice ?? onError)(said);\n      onSaved(res.data);");
  assert.notDeepEqual(formProblems(before), [], "a sentence shown before the save it follows is found");
});

test("the item type carries the sentence", () => {
  const types = read("lib/catalogue/service.ts");
  assert.ok(/opening_stock\?: \{ message: string \| null \};/.test(types), "ServiceCatalogueItem does not carry opening_stock");
});

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(path.join(WEB, dir), { withFileTypes: true })) {
    const rel = path.join(dir, e.name);
    if (e.isDirectory()) { if (e.name !== "node_modules" && e.name !== ".next") walk(rel, out); }
    else if (e.name.endsWith(".tsx")) out.push(rel);
  }
  return out;
}

/** Every `<ProductServiceFormModal ...>` use in a source, with whether it passes `onNotice`. */
export function formUses(src: string): { line: number; passesNotice: boolean }[] {
  const found: { line: number; passesNotice: boolean }[] = [];
  const re = /<ProductServiceFormModal\b([\s\S]*?)\/>/g;
  for (let m = re.exec(src); m; m = re.exec(src)) {
    found.push({ line: src.slice(0, m.index).split("\n").length, passesNotice: /\bonNotice=/.test(m[1]) });
  }
  return found;
}

test("every host of the product form passes onNotice", () => {
  const hosts = [...walk("app"), ...walk("components")]
    .filter((f) => !f.endsWith("ProductServiceFormModal.tsx"))
    .map((f) => [f, read(f)] as const)
    .filter(([, src]) => src.includes("<ProductServiceFormModal"));
  assert.ok(hosts.length >= 3, `only ${hosts.length} hosts of the form were found - the scan is broken`);
  const without = hosts.flatMap(([f, src]) => formUses(src).filter((u) => !u.passesNotice).map((u) => `${f}:${u.line}`));
  assert.deepEqual(without, [], "a host that passes no onNotice shows the sentence as a red error for something that is not a failure");
  // negative control: a host that forgot it is found
  assert.deepEqual(formUses("<ProductServiceFormModal clientId={c} onSaved={f} onError={g} />").map((u) => u.passesNotice), [false]);
});

test("a product created from a line stays in the panel when there is a sentence to read, so the panel's own toast is not taken with it", () => {
  const panel = read("components/catalogue/ProductServiceManagerPanel.tsx");
  assert.match(panel, /function handlePick\(item: ServiceCatalogueItem, opts\?: \{ stayOpen\?: boolean \}\)/);
  assert.match(panel, /if \(!opts\?\.stayOpen\) onClose\(\);/);
  assert.match(panel, /handlePick\(item, \{ stayOpen: Boolean\(item\.opening_stock\?\.message\) \}\)/);
  assert.match(panel, /onNotice=\{\(msg\) => showToast\(msg, "warning"\)\}/);
  // negative controls on the real text
  assert.doesNotMatch(panel.replace("if (!opts?.stayOpen) onClose();", "onClose();"), /if \(!opts\?\.stayOpen\) onClose\(\);/);
});

