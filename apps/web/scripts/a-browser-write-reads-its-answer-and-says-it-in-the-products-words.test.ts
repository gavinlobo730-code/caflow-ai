// A write the browser makes through the Supabase client reads its answer and says a failure in the product's words (POST-A-414). Run with:
//   node --experimental-strip-types --test scripts/a-browser-write-reads-its-answer-and-says-it-in-the-products-words.test.ts
//
// WHY THIS EXISTS
//     The browser's Supabase client does not throw: a write hands back `{ error }`, and for a request that got no answer that error is a PLAIN
//     OBJECT whose `message` is already the product's sentence (`lib/supabase/plainRestFetch`, POST-A-413) and whose `code` says so. A screen
//     that printed `error.message`, or threw `new Error(error.message)`, said it right without being edited. Four did not: the sales page's
//     customer on/off switch printed a fixed "Failed to deactivate customer" for any error, so a change that may have gone through was told
//     as a failure; the tax audit form threw the plain object and its catch read `instanceof Error`, so it said "Save failed"; the income-tax
//     notices' status buttons discarded the answer altogether, so a refused change looked made; and the chart-of-accounts import counted
//     `rows - errors` after ONE insert statement, so a refused import said all but one account had gone in.
//
// THE RULE, over every `.ts`/`.tsx` under app/, components/ and lib/ (an AST rule, not a list of the screens above):
//     a call chain that writes through the client (`.from(<table>)` followed somewhere by `.insert(`, `.update(`, `.upsert(` or `.delete(`),
//     when awaited,
//       1. binds its answer's `error` (a write whose answer is discarded says nothing when it fails);
//       2. reads that error: wherever the code branches on it (`if (error)`, `error ? … : …`), the branch says it, through `error.message`,
//          `failureSentence(error, …)` or `browserFailureOf(error)`, or rethrows it;
//       3. a raw `throw error` (the plain object) is caught by a catch that says what it caught through `failureSentence`, because
//          `instanceof Error` is false for it and the catch's own fixed sentence would be shown instead.
//     A write that is not awaited where it is made (handed to `Promise.all`, returned) is not judged here; there is none today.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const WEB = path.join(import.meta.dirname, "..");
const WRITES = new Set(["insert", "update", "upsert", "delete"]);

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

function parse(rel: string, src: string): ts.SourceFile {
  return ts.createSourceFile(rel, src, ts.ScriptTarget.Latest, true, rel.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
}

function walk(node: ts.Node, visit: (n: ts.Node) => void): void {
  visit(node);
  ts.forEachChild(node, (c) => walk(c, visit));
}

/** Whether a call chain is a write through the Supabase client: `.from(<anything>)` and, after it, a write method. */
function isClientWrite(call: ts.Expression): boolean {
  let sawWrite = false;
  let sawFrom = false;
  let node: ts.Expression = call;
  while (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)) {
    const name = node.expression.name.text;
    if (WRITES.has(name)) sawWrite = true;
    if (name === "from" && sawWrite) sawFrom = true;
    node = node.expression.expression;
  }
  return sawWrite && sawFrom;
}

/** The innermost function around a node. */
function enclosingFunction(node: ts.Node): ts.Node | null {
  let n: ts.Node | undefined = node.parent;
  while (n && !ts.isFunctionDeclaration(n) && !ts.isFunctionExpression(n) && !ts.isArrowFunction(n) && !ts.isMethodDeclaration(n)) n = n.parent;
  return n ?? null;
}

/** Whether `node` mentions the identifier `name` in a way that says it: `.message`, handed to the helper, or rethrown. */
function says(node: ts.Node, name: string): boolean {
  let found = false;
  walk(node, (n) => {
    if (ts.isPropertyAccessExpression(n) && ts.isIdentifier(n.expression) && n.expression.text === name && n.name.text === "message") found = true;
    if (ts.isCallExpression(n) && ts.isIdentifier(n.expression) && /^(failureSentence|browserFailureOf)$/.test(n.expression.text)
        && n.arguments[0] && ts.isIdentifier(n.arguments[0]) && n.arguments[0].text === name) found = true;
    if (ts.isThrowStatement(n) && n.expression && ts.isIdentifier(n.expression) && n.expression.text === name) found = true;
    // A helper of the screen's own that is handed the error (`duplicateAuditErrorMessage(err)`) is judged where it is called, not here.
    if (ts.isCallExpression(n) && n.arguments.some((a) => ts.isIdentifier(a) && a.text === name) && !(ts.isIdentifier(n.expression) && n.expression.text === "Boolean")) found = true;
  });
  return found;
}

/** Whether a condition is a test of the error: `error`, `!error`, `error && …`, `error || …`. */
function testsError(cond: ts.Expression, name: string): boolean {
  if (ts.isIdentifier(cond)) return cond.text === name;
  if (ts.isParenthesizedExpression(cond)) return testsError(cond.expression, name);
  if (ts.isBinaryExpression(cond)
      && (cond.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken || cond.operatorToken.kind === ts.SyntaxKind.BarBarToken)) {
    return testsError(cond.left, name) || testsError(cond.right, name);
  }
  return false;
}

/** The problems with one source: each is "<file>:<line> <what>". */
function problemsIn(rel: string, src: string): string[] {
  const sf = parse(rel, src);
  const out: string[] = [];
  const at = (n: ts.Node) => `${rel}:${sf.getLineAndCharacterOfPosition(n.getStart()).line + 1}`;
  walk(sf, (node) => {
    if (!ts.isAwaitExpression(node) || !ts.isCallExpression(node.expression) || !isClientWrite(node.expression)) return;
    // 1. the answer is bound, with its error
    const decl = node.parent;
    // The whole answer kept in one name (`const row = await …`; `lib/data/deleteRowAndConfirm`): its `.error` is read, and said in the
    // client's own words or through the helper.
    if (ts.isVariableDeclaration(decl) && ts.isIdentifier(decl.name)) {
      const fn = enclosingFunction(node);
      const body = fn ? fn.getText() : "";
      const id = decl.name.text;
      const said = new RegExp(`\\b${id}\\.error\\.message\\b|\\b(failureSentence|browserFailureOf)\\(\\s*${id}\\.error\\b`).test(body);
      if (!said) out.push(`${at(node)} the write's answer is kept as ${id} and its error is not said`);
      return;
    }
    if (!ts.isVariableDeclaration(decl) || !ts.isObjectBindingPattern(decl.name)) {
      out.push(`${at(node)} the write's answer is not read: a refused write, or one that got no answer, says nothing`);
      return;
    }
    const errorBinding = decl.name.elements.find((el) => (el.propertyName ?? el.name).getText() === "error");
    if (!errorBinding || !ts.isIdentifier(errorBinding.name)) {
      out.push(`${at(node)} the write's answer is read without its error`);
      return;
    }
    const name = errorBinding.name.text;
    const fn = enclosingFunction(node);
    if (!fn) return;
    let read = false;
    walk(fn, (n) => {
      if (n === errorBinding.name) return;
      if (ts.isIdentifier(n) && n.text === name && n.pos > decl.end) read = true;
      // 2. every branch on the error says it
      if ((ts.isIfStatement(n) && testsError(n.expression, name) && !says(n.thenStatement, name))
          || (ts.isConditionalExpression(n) && testsError(n.condition, name) && !says(n.whenTrue, name))) {
        out.push(`${at(n)} a branch on the write's error does not say it (it shows a fixed sentence or nothing)`);
      }
      // 3. a raw rethrow is said by its catch through the helper
      if (ts.isThrowStatement(n) && n.expression && ts.isIdentifier(n.expression) && n.expression.text === name) {
        let p: ts.Node | undefined = n.parent;
        while (p && !(ts.isTryStatement(p) && p.tryBlock.pos <= n.pos && n.end <= p.tryBlock.end)) p = p.parent;
        const clause = p && ts.isTryStatement(p) ? p.catchClause : undefined;
        if (!clause || !/\bfailureSentence\(/.test(clause.block.getText())) {
          out.push(`${at(n)} the write's error is thrown as it came (a plain object) and its catch does not say it through failureSentence`);
        }
      }
    });
    if (!read) out.push(`${at(node)} the write's error is bound and never read`);
  });
  // Two writes in one function walk it twice: a problem is said once.
  return [...new Set(out)];
}

test("every browser write through the Supabase client reads its answer and says a failure in the product's words", () => {
  const files = ["app", "components", "lib"].flatMap(sourceFiles);
  const writes = files.filter((f) => /\.(insert|update|upsert|delete)\(/.test(fs.readFileSync(path.join(WEB, f), "utf8")));
  assert.ok(writes.length >= 5, `the scan found ${writes.length} files with a write: it is reading nothing`);
  const problems = files.flatMap((f) => problemsIn(f, fs.readFileSync(path.join(WEB, f), "utf8")));
  assert.deepEqual(problems, []);
});

test("the four screens POST-A-414 found are judged by the rule (each is a write it can see)", () => {
  for (const f of ["app/clients/[id]/sales/page.tsx", "app/income-tax/tax-audit/page.tsx", "app/income-tax/notices/page.tsx",
                   "app/accounting/coa-import/page.tsx"]) {
    const sf = parse(f, fs.readFileSync(path.join(WEB, f), "utf8"));
    let n = 0;
    walk(sf, (node) => { if (ts.isAwaitExpression(node) && ts.isCallExpression(node.expression) && isClientWrite(node.expression)) n++; });
    assert.ok(n > 0, `${f}: the rule sees no write in it`);
  }
});

test("the chart-of-accounts import does not count a refused insert as rows imported, and says when the count is not known", () => {
  const src = fs.readFileSync(path.join(WEB, "app/accounting/coa-import/page.tsx"), "utf8");
  assert.doesNotMatch(src, /inserted:\s*toInsert\.length\s*-\s*errors\.length/, "one insert statement: a refusal added nothing");
  assert.match(src, /browserFailureOf\(err\) === "no_answer" \? null : 0/);
  assert.match(src, /is not known\. Open the chart of accounts to see before you import again/);
});

test("self-test: the rule flags each shape it was written against, and passes the shapes it allows", () => {
  const flagged = (src: string) => problemsIn("Sample.tsx", src);
  // the notices' status buttons: the answer discarded
  assert.equal(flagged(`async function f(sb) { await sb.from(table).update({ a: 1 }).eq("id", 1); }`).length, 1);
  // the customer switch: a fixed sentence for any error
  assert.equal(flagged(`async function f(sb, toast) { const { error } = await sb.from(table).update({ a: 1 }).eq("id", 1);
    if (error) { toast("Failed to deactivate customer"); return; } }`).length, 1);
  // the tax audit: a raw rethrow caught by `instanceof Error`
  assert.equal(flagged(`async function f(sb, set) { try { const { error: err } = await sb.from(table).insert({}); if (err) throw err; }
    catch (e) { set(e instanceof Error ? e.message : "Save failed"); } }`).length, 1);
  // bound and never read
  assert.equal(flagged(`async function f(sb) { const { error } = await sb.from(table).delete().eq("id", 1); return 1; }`).length, 1);
  // allowed: the client's own sentence, a converted rethrow, the helper, a raw rethrow said by the helper
  assert.deepEqual(flagged(`async function f(sb, set) { const { error } = await sb.from(table).insert({}); if (error) set(error.message); }`), []);
  assert.deepEqual(flagged(`async function f(sb) { const { error } = await sb.from(table).insert({}); if (error) throw new Error(error.message); }`), []);
  assert.deepEqual(flagged(`async function f(sb, set) { const { error } = await sb.from(table).upsert({}); if (error) set(failureSentence(error, "x", "write")); }`), []);
  assert.deepEqual(flagged(`async function f(sb, set) { try { const { error: err } = await sb.from(table).insert({}); if (err) throw err; }
    catch (e) { set(failureSentence(e, "Save failed", "write")); } }`), []);
  // a read is not a write
  assert.deepEqual(flagged(`async function f(sb) { await sb.from(table).select("*"); }`), []);
  // the whole answer kept in one name: its error said, or not
  assert.deepEqual(flagged(`async function f(sb) { const row = await sb.from(table).delete().eq("id", 1).select("id"); if (row.error) return row.error.message; }`), []);
  assert.equal(flagged(`async function f(sb) { const row = await sb.from(table).delete().eq("id", 1).select("id"); if (row.error) return "Delete failed"; }`).length, 1);
});
