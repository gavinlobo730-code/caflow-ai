// A credit note or a purchase debit note asks "did the goods come back?" wherever the browser makes one (POST-A-378). Run with:
//   node --experimental-strip-types --test scripts/a-note-that-can-move-stock-asks-whether-the-goods-came-back-wherever-it-is-made.test.ts
//
// WHY THIS EXISTS
//     POST-A-371 made a credit note or a purchase debit note say whether its goods came back, and the server refuses to ISSUE a note that names goods and has not said. Only the two
//     note editors asked, so a note made anywhere else (the credit note raised from the invoice drawer, the debit note raised from the bill drawer, the two CSV imports) was a draft the CA
//     could not issue until they opened it in the editor to answer. The server also answers `stock_not_moved` when it left stock alone because the answer was no, and no screen printed it.
//
//     The rule, over the tree (AST, not a list of spellings):
//       * every `apiCall("/api/credit-notes/" | "/api/debit-notes/", "POST", payload)` in the browser either carries a `goods_returned` property in an object literal or hands over a
//         payload a builder made, and the builders (`lib/imports/mappers.ts`) are held to carry it by their own tests; the sites that hand over a builder's payload are NAMED here, so a new
//         site fails until someone reads it;
//       * every place that issues such a note prints the server's `stock_not_moved` sentence (`stockNotMovedSentence` / `bulkStockNotMovedSentence`).
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const WEB = path.join(import.meta.dirname, "..");

function parse(rel: string, src: string): ts.SourceFile {
  return ts.createSourceFile(rel, src, ts.ScriptTarget.Latest, true, rel.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
}
function walk(node: ts.Node, visit: (n: ts.Node) => void): void {
  visit(node);
  ts.forEachChild(node, (c) => walk(c, visit));
}
function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of fs.readdirSync(path.join(WEB, dir), { withFileTypes: true })) {
    if (entry.name === "node_modules" || entry.name === ".next" || entry.name === "out") continue;
    const rel = path.posix.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...sourceFiles(rel));
    else if (/\.(ts|tsx)$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) && !/\.d\.ts$/.test(entry.name)) out.push(rel);
  }
  return out;
}
const read = (rel: string) => fs.readFileSync(path.join(WEB, rel), "utf8");

const NOTE_ENDPOINTS = new Set(["/api/credit-notes/", "/api/debit-notes/"]);

/** Every POST that creates a credit note or a purchase debit note: where, and whether its payload is an object literal that names `goods_returned`, a payload handed over by name, or neither. */
function noteCreations(rel: string, src: string): Array<{ line: number; endpoint: string; payload: "carries" | "lacks" | "by-name"; name?: string }> {
  const found: Array<{ line: number; endpoint: string; payload: "carries" | "lacks" | "by-name"; name?: string }> = [];
  const sf = parse(rel, src);
  walk(sf, (node) => {
    if (!(ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === "apiCall")) return;
    const [url, method, payload] = node.arguments;
    if (!url || !ts.isStringLiteralLike(url) || !NOTE_ENDPOINTS.has(url.text)) return;
    if (!method || !ts.isStringLiteralLike(method) || method.text !== "POST") return;
    const line = sf.getLineAndCharacterOfPosition(node.getStart()).line + 1;
    if (payload && ts.isObjectLiteralExpression(payload)) {
      const names = payload.properties.some((p) => (ts.isPropertyAssignment(p) || ts.isShorthandPropertyAssignment(p)) && ts.isIdentifier(p.name) && p.name.text === "goods_returned");
      found.push({ line, endpoint: url.text, payload: names ? "carries" : "lacks" });
    } else {
      found.push({ line, endpoint: url.text, payload: "by-name", name: payload ? payload.getText() : "" });
    }
  });
  return found;
}

/** The sites that hand over a payload a CSV builder made. A new one has to be read and added. */
const BUILT_BY_AN_IMPORT: Record<string, string> = {
  "app/clients/[id]/sales/page.tsx": "note",
  "app/clients/[id]/purchases/page.tsx": "note",
};

test("every place the browser creates a credit note or a purchase debit note carries the answer or hands over a builder's payload", () => {
  const sites: Array<{ rel: string; line: number; endpoint: string; payload: string; name?: string }> = [];
  for (const dir of ["app", "components", "lib"]) {
    for (const rel of sourceFiles(dir)) for (const s of noteCreations(rel, read(rel))) sites.push({ rel, ...s });
  }
  const lacking = sites.filter((s) => s.payload === "lacks");
  assert.deepEqual(lacking.map((s) => `${s.rel}:${s.line}`), [], "a note is made without the question: add goods_returned (and ask it with GoodsReturnedChoice)");
  const byName = sites.filter((s) => s.payload === "by-name");
  for (const s of byName) {
    assert.equal(BUILT_BY_AN_IMPORT[s.rel], s.name, `${s.rel}:${s.line} hands over "${s.name}" and nothing says a builder made it: read it, then name it in BUILT_BY_AN_IMPORT`);
  }
  // …and the rule sees a real population: the two editors, the two drawer modals, and the two imports
  assert.ok(sites.filter((s) => s.payload === "carries").length >= 4, "the rule no longer sees the four places that ask");
  assert.equal(byName.length, 2, "the rule no longer sees the two imports");
  assert.deepEqual([...new Set(sites.map((s) => s.endpoint))].sort(), ["/api/credit-notes/", "/api/debit-notes/"]);
});

test("the four places that ask are the two editors and the two drawer modals, and each shows the choice only for a note that names goods", () => {
  const places: Array<[string, string]> = [
    ["components/sales/SalesCreditNoteEditor.tsx", "credit_note"],
    ["components/purchases/DebitNoteEditor.tsx", "debit_note"],
    ["components/invoices/InvoiceViewDrawer.tsx", "credit_note"],
    ["components/purchases/PurchaseBillViewDrawer.tsx", "debit_note"],
  ];
  for (const [rel, kind] of places) {
    const src = read(rel);
    assert.match(src, new RegExp(`<GoodsReturnedChoice kind="${kind}"`), `${rel} does not ask`);
  }
  for (const rel of ["components/invoices/InvoiceViewDrawer.tsx", "components/purchases/PurchaseBillViewDrawer.tsx"]) {
    const src = read(rel);
    assert.match(src, /const namesGoods = useNamesGoods\(clientId, /, `${rel} does not look up whether a line is a good`);
    assert.match(src, /\{namesGoods && <GoodsReturnedChoice /, `${rel} shows the choice for a note that names no goods`);
    assert.match(src, /goods_returned: namesGoods && goodsReturned !== null \? goodsReturned : undefined,/, `${rel} sends an answer for a note that names no goods, or sends none for one that does`);
  }
});

test("the two imports whose notes can move stock offer the column, and the two that cannot do not", () => {
  const mappers = read("lib/imports/mappers.ts");
  const columns = (name: string) => new RegExp(`export const ${name}: ImportColumn\\[\\] = \\[[\\s\\S]*?\\n\\];`).exec(mappers)?.[0] ?? "";
  assert.match(columns("SALES_CREDIT_NOTE_IMPORT_COLUMNS"), /goodsReturnedColumn\("credit_note"\)/);
  assert.match(columns("PURCHASE_DEBIT_NOTE_IMPORT_COLUMNS"), /goodsReturnedColumn\("debit_note"\)/);
  assert.doesNotMatch(columns("SALES_DEBIT_NOTE_IMPORT_COLUMNS"), /goodsReturnedColumn/);
  assert.doesNotMatch(columns("PURCHASE_CREDIT_NOTE_IMPORT_COLUMNS"), /goodsReturnedColumn/);
  // and the strict read is switched on by exactly those two builders: the parsers take the flag and each builder says it
  assert.match(mappers, /parseSalesNoteRows\(rows, "credit_note_date", customers, invoices, services, true\)/);
  assert.match(mappers, /parseSalesNoteRows\(rows, "debit_note_date", customers, invoices, services, false\)/);
  assert.match(mappers, /parsePurchaseNoteRows\(rows, "debit_note_date", vendors, bills, services, true\)/);
  assert.match(mappers, /parsePurchaseNoteRows\(rows, "credit_note_date", vendors, bills, services, false\)/);
});

test("every place that issues a credit note or a purchase debit note prints the sentence the server says when it left stock alone", () => {
  const sales = read("app/clients/[id]/sales/page.tsx");
  const purchases = read("app/clients/[id]/purchases/page.tsx");
  // single issue
  assert.match(sales, /const left = stockNotMovedSentence\(result\.data\);\s*showToast\(joinSentences\(\["Credit note issued", lateNote, stock, left\]\)/, "the sales page's single issue does not print it");
  assert.match(purchases, /const left = stockNotMovedSentence\(result\.data\);\s*setMsg\(\{ type: "ok", text: left \? joinSentences\(\["Debit note issued", left\]\)/, "the purchases page's single issue does not print it");
  // bulk issue
  assert.match(sales, /const left = bulkStockNotMovedSentence\(results\.flatMap\([^;]*\), "credit_note"\);/, "the sales page's bulk issue does not print it, or says it as a debit note");
  assert.match(purchases, /const left = bulkStockNotMovedSentence\(results\.flatMap\([^;]*\), "debit_note"\);/, "the purchases page's bulk issue does not print it, or says it as a credit note");
  // the issue calls themselves: the rule is that none of the four is added without the sentence
  const issuesCreditNote = (sales.match(/apiCall\(`\/api\/credit-notes\/\$\{[^}]+\}\/issue`/g) ?? []).length;
  const issuesDebitNote = (purchases.match(/apiCall\(`\/api\/debit-notes\/\$\{[^}]+\}\/issue`/g) ?? []).length;
  assert.equal(issuesCreditNote, 2, "the sales page issues a credit note somewhere new: print the sentence there too");
  assert.equal(issuesDebitNote, 2, "the purchases page issues a debit note somewhere new: print the sentence there too");
});

test("the catalogue lookup of the two drawer modals forgets the last answer when the items change, and a failed read is never 'a good'", () => {
  const hook = read("lib/inventory/useNamesGoods.ts");
  // the effect's first act is to forget: a different set of items is a different question, and its answer is false until it is answered
  assert.match(hook, /useEffect\(\(\) => \{[\s\S]*?setNamesGoods\(false\);[\s\S]*?if \(!key\) return;/, "the lookup no longer resets to false when the set of items changes");
  // the decision is the pure rule's (a read that failed is not an answer), and the hook does not decide from the rows itself again
  assert.match(hook, /setNamesGoods\(namesGoodsFrom\(\{ data, error \}\)\)/, "the answer is not decided by the rule that reads a failed read as 'not a good'");
  assert.ok(!/\.some\(/.test(hook), "the hook decides from the rows itself again, beside the rule that reads an error");
});

test("the question is worded for the note's own kind wherever the control is drawn", () => {
  const choice = read("components/inventory/GoodsReturnedChoice.tsx");
  assert.match(choice, /\{goodsReturnedQuestion\(kind\)\}/, "the control does not take its question from the helper that words it for the note's kind");
  assert.ok(!choice.includes("Did the goods come back?"), "the control spells the credit note's question for both kinds: a purchase debit note's goods go back to the supplier");
});

// ── the rule is not blind ───────────────────────────────────────────────────────────────────────────────────────────────────────
test("self-test: a note made without the answer, with it, and by name are told apart", () => {
  const without = 'async function f() { await apiCall("/api/credit-notes/", "POST", { client_id: c, lines }, token); }';
  const withIt = 'async function f() { await apiCall("/api/debit-notes/", "POST", { client_id: c, goods_returned: g, lines }, token); }';
  const shorthand = 'async function f() { const goods_returned = 1; await apiCall("/api/credit-notes/", "POST", { client_id: c, goods_returned }, token); }';
  const byName = 'async function f() { await apiCall("/api/credit-notes/", "POST", note, token); }';
  const other = 'async function f() { await apiCall("/api/credit-notes/", "PATCH", { lines }, token); await apiCall("/api/sales-debit-notes/", "POST", { lines }, token); }';
  assert.deepEqual(noteCreations("x.tsx", without).map((s) => s.payload), ["lacks"]);
  assert.deepEqual(noteCreations("x.tsx", withIt).map((s) => s.payload), ["carries"]);
  assert.deepEqual(noteCreations("x.tsx", shorthand).map((s) => s.payload), ["carries"]);
  assert.deepEqual(noteCreations("x.tsx", byName).map((s) => [s.payload, s.name]), [["by-name", "note"]]);
  assert.deepEqual(noteCreations("x.tsx", other), [], "a PATCH, and a note that moves no stock, are not part of the rule");
});
