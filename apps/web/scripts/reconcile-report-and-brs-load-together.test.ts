// Regression guard for the Reconcile tab's "session detail" slow-load finding
// (triage sweep-client-bank-fixed-assets-02): `loadReport` used to await
// reconciliations.report(id), and only once that resolved, await
// reconciliations.brs(id) inside its own nested try — two sequential round
// trips gating the one `loadingReport` flag that shows the tie-out panel.
// Neither call depends on the other's result, so they now fire together in a
// single `Promise.all([...])`.
//
// Why this is its own narrow test rather than an entry in
// await-waterfalls.test.ts's repo-wide ratchet: that detector deliberately
// does not pair two awaits that sit in different statement lists (an
// if/try/loop body is examined on its own — see await-waterfalls.ts's own
// "WHY IT PARSES INSTEAD OF GREPPING" note), and the old code put brs()'s
// await inside a *nested* try block, a different statement list from
// report()'s. That is exactly why the general rule never caught this one, so
// it is checked directly against the function it was found in.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FILE = path.join(__dirname, "..", "components", "banking", "ReconcileTab.tsx");

/** The body of `const loadReport = useCallback(async (id) => { ... }, [])`,
 *  however many wrapper calls sit between the declaration and the arrow
 *  function — unwrapped by walking into the first call argument that is
 *  itself a function. */
function loadReportBody(source: string): ts.Block {
  const sf = ts.createSourceFile(FILE, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let found: ts.Block | null = null;
  const walk = (n: ts.Node): void => {
    if (found) return;
    if (ts.isVariableDeclaration(n) && ts.isIdentifier(n.name) && n.name.text === "loadReport") {
      let fn: ts.Node | undefined = n.initializer;
      if (fn && ts.isCallExpression(fn) && fn.arguments.length > 0) fn = fn.arguments[0];
      if (fn && (ts.isArrowFunction(fn) || ts.isFunctionExpression(fn)) && ts.isBlock(fn.body)) {
        found = fn.body;
      }
      return;
    }
    ts.forEachChild(n, walk);
  };
  walk(sf);
  if (!found) throw new Error(`could not find a "loadReport" function in ${FILE}`);
  return found;
}

/** Every `await` expression anywhere in a node, as its own source text. Does
 *  not descend further once an await is found — its text already covers
 *  everything beneath it, and this function has no await nested inside
 *  another one to miss. */
function allAwaitTexts(node: ts.Node): string[] {
  const out: string[] = [];
  const walk = (n: ts.Node): void => {
    if (ts.isAwaitExpression(n)) { out.push(n.getText()); return; }
    ts.forEachChild(n, walk);
  };
  ts.forEachChild(node, walk);
  return out;
}

test("loadReport requests report() and brs() together, not one after the other", () => {
  const source = fs.readFileSync(FILE, "utf8");
  const awaits = allAwaitTexts(loadReportBody(source));

  const withReport = awaits.filter((a) => a.includes(".report("));
  const withBrs = awaits.filter((a) => a.includes(".brs("));

  assert.equal(withReport.length, 1,
    `expected exactly one await touching reconciliations.report(), found ${withReport.length}`);
  assert.equal(withBrs.length, 1,
    `expected exactly one await touching reconciliations.brs(), found ${withBrs.length}`);
  // The regression: report() and brs() as two SEPARATE awaits (brs() gated on
  // report() having already resolved) rather than one request for both.
  assert.equal(withReport[0], withBrs[0],
    "report() and brs() must be requested by the SAME await — two separate " +
    "awaits means the second is once again waiting on the first to resolve " +
    "before it even starts.");
  assert.ok(withReport[0].includes("Promise.all"),
    "expected report() and brs() to be requested inside one Promise.all([...])");
});

test("the guard is reading the real loadReport, not an emptied-out stub", () => {
  const source = fs.readFileSync(FILE, "utf8");
  const body = loadReportBody(source);
  // setLoadingReport/setSel/setError, the try/catch/finally, and everything
  // inside it — a stub with the awaits stripped out would fail this rather
  // than passing the tests above vacuously.
  assert.ok(body.statements.length >= 3,
    "loadReport looks emptied out — check the function name still matches");
  assert.ok(source.includes("setLoadingReport(false)"),
    "loadReport should still lower its own loading flag");
});

test("a loader with two genuinely sequential awaits is still caught", () => {
  // Negative control: proves the assertions above would have failed against
  // the shape this file used to have, rather than passing on any input.
  const sf = ts.createSourceFile("t.tsx", `
    async function loadReport(id: string) {
      try {
        const res = await api.banking.reconciliations.report(id);
        try {
          const b = await api.banking.reconciliations.brs(id);
        } catch {}
      } catch (e) {}
    }
  `, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let body: ts.Block | null = null;
  const fn = sf.statements[0] as ts.FunctionDeclaration;
  body = fn.body!;
  const awaits = allAwaitTexts(body);
  const withReport = awaits.filter((a) => a.includes(".report("));
  const withBrs = awaits.filter((a) => a.includes(".brs("));
  assert.equal(withReport.length, 1);
  assert.equal(withBrs.length, 1);
  assert.notEqual(withReport[0], withBrs[0],
    "the old shape has report() and brs() as two different awaits");
});
