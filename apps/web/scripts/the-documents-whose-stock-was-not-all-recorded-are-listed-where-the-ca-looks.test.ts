// POST-A-092 — the documents whose stock was not all recorded reach the CA, and the CA can complete them.
//
// Run with:
//   node --experimental-strip-types --test scripts/the-documents-whose-stock-was-not-all-recorded-are-listed-where-the-ca-looks.test.ts
//
// WHAT WAS WRONG
//     A sales invoice, purchase bill, credit note or debit note moves stock AFTER it is issued, and a failure there never un-issues it. The
//     response that issued it said so once, on the screen that issued it, and the only advice was to adjust stock by hand or to cancel
//     the document. Nothing found the document again afterwards. Migration 579 counts them in the database; this panel lists them and asks
//     the server to complete one.
//
// THE RULES, NOT SPELLINGS
//     * the Inventory tab renders the panel;
//     * the panel reads the finder and the retry endpoint and nothing else (no second data path, no table of its own);
//     * a failed read is SAID, never rendered as an empty panel: an empty panel means "every goods document has its stock";
//     * the list is read through objectWithLists, not trusted;
//     * the panel decides nothing: no arithmetic of its own on a figure, no date arithmetic, no stock rule; the result of a retry is the
//       server's own sentence;
//     * the one write goes through the shared single-flight Button, so a second click is ignored while one retry is working;
//     * a list cut at the server's limit says how many more there are;
//     * (migration 620) a document the CA already put right by hand can be MARKED settled with a reason, and the marks are listed with who and when and a way to
//       take one off: the panel reads them through the API, apart from the list (a failed read of one never makes the other look empty), sends the reason as
//       typed, says the server's sentences, asks before taking a mark off, and offers every button that writes only to someone the routes admit.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const WEB = path.resolve(import.meta.dirname, "..");
const PANEL = path.join("components", "inventory", "UnrecordedStockPanel.tsx");

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

test("the Inventory tab renders the panel for the client", () => {
  const src = code(path.join("app", "clients", "[id]", "inventory", "page.tsx"));
  assert.match(src, /<UnrecordedStockPanel\b[^>]*clientId=\{clientId\}/);
});

test("the panel reads the finder and the retry and nothing else", () => {
  const src = code(PANEL);
  assert.match(src, /api\.inventory\.unrecordedStock\(/);
  assert.match(src, /api\.inventory\.retryStockEffect\(/);
  assert.doesNotMatch(src, /supabase|\.from\(/, "no second data path");
  const api = code(path.join("lib", "api", "index.ts"));
  assert.match(api, /\/api\/inventory\/stock-effects\/unrecorded\?/);
  assert.match(api, /\/api\/inventory\/stock-effects\/retry`/);
});

test("a failed read is said in words, never rendered as an empty panel", () => {
  const src = code(PANEL);
  assert.match(src, /Couldn(&apos;|')t check which documents have unrecorded stock/);
  assert.match(src, /role="alert"/);
  assert.match(src, /catch \{[\s\S]{0,120}setFailed\(true\)/);
  assert.match(src, /setFailed\(got === null\)/);
});

test("the list is read through objectWithLists, not trusted", () => {
  assert.match(code(PANEL), /objectWithLists<UnrecordedStock>\([^)]*"documents"/);
});

test("the panel decides nothing: no arithmetic on a figure, no date arithmetic, and the retry's sentence is shown as it came", () => {
  const src = code(PANEL);
  assert.doesNotMatch(src, /Math\.|\*\s*100|\/\s*100|new Date\(|Date\.now|parseFloat|parseInt|Number\(/);
  assert.match(src, /text: r\.data\.message/, "the server's sentence, not a sentence of the screen's");
  assert.match(src, /r\.error \|\|/);
});

test("a refusal the client threw is shown in the server's own words, not replaced by a sentence of the screen's", () => {
  const src = code(PANEL);
  assert.match(src, /catch \(e\) \{[\s\S]{0,400}e instanceof Error && e\.message\.trim\(\) \? e\.message/);
});

test("the write asks first, in the shared dialog, and warns about a hand adjustment", () => {
  const src = code(PANEL);
  assert.match(src, /await confirmDialog\(\{/);
  assert.match(src, /already adjusted this[\s"+]*stock by hand/);
  assert.match(src, /if \(!sure\) return;[\s\S]{0,80}setBusy\(d\.document_id\)/, "the question comes before anything is sent");
  assert.doesNotMatch(src, /window\.confirm|\bconfirm\(/, "no browser pop-up");
});

test("a document that carries no goods line is not rendered as a problem", () => {
  assert.match(code(PANEL), /ok: r\.data\.recorded !== false/);
});

test("the one write goes through the shared single-flight button", () => {
  const src = code(PANEL);
  assert.match(src, /useSingleFlight\(\)/);
  assert.match(src, /<Button[\s\S]{0,200}flight=\{flight\}/);
  assert.match(src, /disabled=\{busy !== null\}/);
});

test("a list cut at the server's limit says how many more there are", () => {
  assert.match(code(PANEL), /found\.total > found\.documents\.length/);
});

// ── POST-A-092, the mark (migration 620) ─────────────────────────────────────────────────────────────────────────────────────

test("the panel reads the marks, writes one and takes one back through the API client, with the methods and paths the server has", () => {
  const src = code(PANEL);
  assert.match(src, /api\.inventory\.settledStock\(/);
  assert.match(src, /api\.inventory\.settleStockEffect\(/);
  assert.match(src, /api\.inventory\.unsettleStockEffect\(/);
  const api = code(path.join("lib", "api", "index.ts"));
  assert.match(api, /\/api\/inventory\/stock-effects\/settled\?/);
  assert.match(api, /`\/api\/inventory\/stock-effects\/settle`, \{ method: "POST"/);
  assert.match(api, /\/api\/inventory\/stock-effects\/settled\/\$\{encodeURIComponent\(settlementId\)\}`, \{ method: "DELETE" \}/);
});

/**
 * The Buttons that start a write (named by what they say) that are NOT drawn under `mayWriteBooks`, found in the syntax tree and not by
 * spelling. A button is under it when it is the last operand of an `&&` chain one of whose earlier operands is `mayWriteBooks` itself:
 * `mayWriteBooks && (...)` and `mayWriteBooks && !row.somethingElse && (...)` alike (POST-A-092: a row the retry cannot finish is not
 * offered Complete the stock, so that button carries a second condition). `!mayWriteBooks`, and one side of an `||`, are not the gate.
 */
function writeButtonsOutsideCanWrite(rel: string, labels: string[]): { drawn: string[]; unguarded: string[] } {
  const sf = ts.createSourceFile(rel, fs.readFileSync(path.join(WEB, rel), "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const drawn: string[] = [];
  const unguarded: string[] = [];
  const conjuncts = (e: ts.Expression): ts.Expression[] =>
    ts.isBinaryExpression(e) && e.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken ? [...conjuncts(e.left), ...conjuncts(e.right)] : [e];
  const visit = (node: ts.Node, guarded: boolean) => {
    if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken
        && conjuncts(node.left).some((c) => c.getText(sf) === "mayWriteBooks")) {
      visit(node.right, true);
      return;
    }
    if (ts.isJsxElement(node) && node.openingElement.tagName.getText(sf) === "Button") {
      const said = node.children.filter(ts.isJsxText).map((t) => t.text.replace(/\s+/g, " ").trim()).join(" ");
      for (const label of labels) {
        if (said.includes(label) && !said.includes(`${label}s`)) {
          drawn.push(label);
          if (!guarded) unguarded.push(label);
        }
      }
    }
    ts.forEachChild(node, (child) => visit(child, guarded));
  };
  visit(sf, false);
  return { drawn, unguarded };
}

test("both buttons that write are offered only to someone the routes admit, and a reader sees the list without them", () => {
  const src = code(PANEL);
  assert.match(src, /const \{ can: canDo, resolved: permissionsRead \} = usePermissions\(\);/);
  assert.match(src, /const mayWriteBooks = canDo\("accounting", "write"\);/);
  const found = writeButtonsOutsideCanWrite(PANEL, ["Complete the stock", "Mark as settled", "Take the mark off"]);
  assert.deepEqual([...new Set(found.drawn)].sort(), ["Complete the stock", "Mark as settled", "Take the mark off"], "a button is no longer drawn by the panel");
  assert.deepEqual(found.unguarded, [], "a button that writes is offered to someone the route would refuse");
});

test("self-test: the rule finds a write button drawn outside the permission, in each of the shapes it could be", () => {
  const real = fs.readFileSync(path.join(WEB, PANEL), "utf8");
  const tmp = path.join(WEB, "components", "inventory", "__spoiled_unrecorded_panel.tsx");
  const found = (spoiled: string) => {
    assert.notEqual(spoiled, real, "the self-test's anchor is gone");
    fs.writeFileSync(tmp, spoiled);
    try {
      return writeButtonsOutsideCanWrite(path.join("components", "inventory", "__spoiled_unrecorded_panel.tsx"), ["Complete the stock", "Mark as settled"]).unguarded;
    } finally {
      fs.rmSync(tmp, { force: true });
    }
  };
  // the permission taken off the chain: the other condition alone is not the gate
  assert.deepEqual(found(real.replace("{mayWriteBooks && !d.hand_fix_says && (", "{!d.hand_fix_says && (")), ["Complete the stock"]);
  // the permission negated, and the permission as one side of an OR
  assert.deepEqual(found(real.replace("{mayWriteBooks && !d.hand_fix_says && (", "{!mayWriteBooks && !d.hand_fix_says && (")), ["Complete the stock"]);
  assert.deepEqual(found(real.replace("{mayWriteBooks && !d.hand_fix_says && (", "{(mayWriteBooks || !d.hand_fix_says) && (")), ["Complete the stock"]);
  // and the real file, whose Complete the stock sits under a chain of two conditions, is clean
  fs.writeFileSync(tmp, real);
  try {
    assert.deepEqual(writeButtonsOutsideCanWrite(path.join("components", "inventory", "__spoiled_unrecorded_panel.tsx"), ["Complete the stock", "Mark as settled"]).unguarded, []);
  } finally {
    fs.rmSync(tmp, { force: true });
  }
});

test("a failed read of the marks is said in words, apart from the list, and never drawn as none marked", () => {
  const src = code(PANEL);
  assert.match(src, /Couldn(&apos;|')t read the documents marked as settled by hand/);
  assert.match(src, /catch \{[\s\S]{0,120}setSettledFailed\(true\)/);
  assert.match(src, /setSettledFailed\(got === null\)/);
  assert.match(src, /objectWithLists<\{ settlements: StockSettlement\[\] \}>\([^)]*"settlements"/);
});

test("the reason is sent as typed, the screen words nothing of its own for the mark, and taking one off asks first", () => {
  const src = code(PANEL);
  assert.match(src, /settleStockEffect\(\{ client_id: clientId, kind: marking\.kind, document_id: marking\.document_id, reason \}\)/, "the reason as typed, untouched");
  assert.match(src, /text: r\.data\.message/);
  assert.match(src, /setMarkError\(r\.error \|\| /);
  assert.match(src, /catch \(e\) \{[\s\S]{0,300}e instanceof Error && e\.message\.trim\(\) \? e\.message/);
  assert.match(src, /const sure = await confirmDialog\(\{\s*title: "Take the mark off\?"[\s\S]{0,420}if \(!sure\) return;[\s\S]{0,80}setBusy\(m\.id\)/, "the question comes before anything is sent");
});

test("the question is the shared Modal, closed by nothing while the write is in flight, and the box is named", () => {
  const src = code(PANEL);
  assert.match(src, /<Modal\s[\s\S]{0,200}title=\{`Mark \$\{name\} as settled by hand`\}/);
  assert.match(src, /onClose=\{saving \? \(\) => \{\} : \(\) => setMarking\(null\)\}/);
  assert.match(src, /<label htmlFor="stock-settle-reason"/);
  assert.match(src, /<textarea id="stock-settle-reason"/);
  assert.doesNotMatch(src, /fixed inset-0/, "a hand-built overlay");
});

test("the marks are listed with who marked them and when, in a region the keyboard can reach", () => {
  const src = code(PANEL);
  assert.match(src, /role="region" aria-label="Documents marked as settled by hand" tabIndex=\{0\}/);
  assert.match(src, /\{m\.settled_by_name \|\| "—"\} · \{formatDate\(m\.settled_at\)\}/);
  assert.match(src, /\{m\.reason\}/);
});
