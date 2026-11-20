// What "a catch around a server call that tells nobody anything" means, as a scan over the source (POST-A-515 (d)). Used by
// scripts/a-quiet-catch-around-a-server-call-says-why.test.ts; its own negative controls are in that file.
//
// scripts/silentHandlers.ts reads the function a PRESS runs. This reads every catch around a server call wherever it stands, in a handler, an
// effect or a loader, because a read that fails quietly leaves a screen drawn as if there were nothing to show (a list that is empty, a figure
// that is zero, a panel that is absent) and that is the same fault as a button that does nothing. A catch is QUIET when it is
//
//   * a `catch { ... }` block, or the handler of a `.catch(...)` on a server call, and
//   * it makes no effect the person can see (a state setter, a toast, an alert, a dialog, a callback, a navigation), throws nothing, hands
//     back no value, and records the failure for its caller (`failures.push(...)`, `failed += 1`, `error = e`) nowhere, and
//   * it carries no comment inside it saying why.
//
// A quiet catch that SAYS WHY is the review: the comment states what the screen then shows and why that is true (a prefill that leaves a
// field as it was; a recorded login event nobody waits for). One that says nothing is a finding, and the way out is either to tell the
// person or to write the reason where the next reader will look. A handler that hands back a stand-in VALUE (`() => false`, `() => ({ ok:
// false })`, `() => "kept"`) is the caller's to read, and is not judged here; `null`, `undefined` and an empty body are not values, because
// they are what a caller draws as "nothing".
//
// What it does not see, said here so it is not mistaken for more: a read that never throws because the client hands its failure back in the
// answer (the shared pager's `{ error }`, which scripts/pagerReads.ts holds), a catch whose server call is behind a name declared elsewhere,
// and what a screen does with the stand-in value a handler hands back. Those are other rules or open items, not claims this one makes.
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

/** A server call: the API client, the Supabase client, a raw request, a Postgres function, or one of the shared pagers. */
const NET = /(^|[^\w.])(api\.|supabase\b|getSupabaseClient|fetch\(|apiFetch|request\(|selectAll|selectAllKeyset|uploadWithProgress)|\.(from|rpc)\(|\.auth\./;
/** A call that makes SOMETHING visible happen, or hands the failure on. */
const TELLS = /^(set[A-Z]\w*|toast(\.\w+)?|notify\w*|(window\.)?alert|show[A-Z]\w*|ask[A-Z]\w*|confirmDialog|promptDialog|dispatch|on[A-Z]\w*|reportError|\w+\.(set[A-Z]\w*|on[A-Z]\w*)|add[A-Z]\w*Toast|say|fail\w*|report\w*|refused|\w+\.push|push\w*)$/;

export type QuietCatch = { file: string; line: number; fn: string; kind: "catch" | ".catch"; detail: string };

function descendants(node: ts.Node, fn: (c: ts.Node) => void): void {
  ts.forEachChild(node, (c) => {
    fn(c);
    descendants(c, fn);
  });
}

function callsIn(node: ts.Node): ts.CallExpression[] {
  const out: ts.CallExpression[] = [];
  if (ts.isCallExpression(node)) out.push(node);
  descendants(node, (c) => {
    if (ts.isCallExpression(c)) out.push(c);
  });
  return out;
}

const calleeText = (c: ts.CallExpression): string => c.expression.getText().replace(/\?\./g, ".");

function tells(node: ts.Node): boolean {
  return callsIn(node).some((c) => TELLS.test(calleeText(c)));
}

function throws(node: ts.Node): boolean {
  let t = ts.isThrowStatement(node);
  descendants(node, (c) => {
    if (ts.isThrowStatement(c)) t = true;
  });
  return t;
}

function returnsValue(node: ts.Node): boolean {
  let r = false;
  descendants(node, (c) => {
    if (ts.isReturnStatement(c) && c.expression && !isNothing(c.expression)) r = true;
  });
  return r;
}

/** The failure recorded for a caller to read: an assignment, `+=`, `++`, or a `.push(`. */
function records(node: ts.Node): boolean {
  let a = false;
  descendants(node, (c) => {
    if (ts.isBinaryExpression(c) && c.operatorToken.kind >= ts.SyntaxKind.FirstAssignment && c.operatorToken.kind <= ts.SyntaxKind.LastAssignment) a = true;
    if ((ts.isPostfixUnaryExpression(c) || ts.isPrefixUnaryExpression(c)) && (c.operator === ts.SyntaxKind.PlusPlusToken || c.operator === ts.SyntaxKind.MinusMinusToken)) a = true;
  });
  return a;
}

/** `null`, `undefined`, `void 0` and an empty object or array: what a caller draws as "nothing". */
function isNothing(e: ts.Expression): boolean {
  const x = ts.isParenthesizedExpression(e) ? e.expression : e;
  if (x.kind === ts.SyntaxKind.NullKeyword) return true;
  if (ts.isIdentifier(x) && x.text === "undefined") return true;
  if (ts.isVoidExpression(x)) return true;
  if (ts.isObjectLiteralExpression(x) && x.properties.length === 0) return true;
  if (ts.isArrayLiteralExpression(x) && x.elements.length === 0) return true;
  return false;
}

/** A comment of ten characters or more anywhere inside `node`'s own text (the reason the catch is quiet). */
function saysWhy(node: ts.Node): boolean {
  const text = node.getText();
  return /\/\*[\s\S]{10,}?\*\//.test(text) || /\/\/[^\n]{10,}/.test(text);
}

function functionName(n: ts.Node): string {
  for (let p: ts.Node | undefined = n.parent; p; p = p.parent) {
    if (ts.isFunctionDeclaration(p) && p.name) return p.name.text;
    if ((ts.isArrowFunction(p) || ts.isFunctionExpression(p)) && p.parent && ts.isVariableDeclaration(p.parent) && ts.isIdentifier(p.parent.name)) return p.parent.name.text;
    if (ts.isMethodDeclaration(p) && p.name) return p.name.getText();
  }
  return "(anonymous)";
}

/** The catches around a server call that were read (`examined`) and the ones among them that tell nobody anything and say nothing why. */
export function scanSource(rel: string, source: string): { examined: number; findings: QuietCatch[] } {
  const sf = ts.createSourceFile(rel, source, ts.ScriptTarget.Latest, true, rel.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const out: QuietCatch[] = [];
  let examined = 0;
  const lineOf = (n: ts.Node) => sf.getLineAndCharacterOfPosition(n.getStart()).line + 1;
  (function visit(n: ts.Node): void {
    if (ts.isTryStatement(n) && n.catchClause && NET.test(n.tryBlock.getText())) {
      examined++;
      const body = n.catchClause.block;
      if (!tells(body) && !throws(body) && !returnsValue(body) && !records(body) && !saysWhy(body)) {
        out.push({ file: rel, line: lineOf(n.catchClause), fn: functionName(n), kind: "catch", detail: body.statements.length ? body.getText().replace(/\s+/g, " ").slice(0, 80) : "(empty)" });
      }
    }
    if (ts.isCallExpression(n) && ts.isPropertyAccessExpression(n.expression) && n.expression.name.text === "catch" && n.arguments.length >= 1 && NET.test(n.expression.expression.getText())) {
      const h = n.arguments[0];
      if (ts.isArrowFunction(h) || ts.isFunctionExpression(h)) {
        examined++;
        const body = h.body;
        // A block is judged like a `catch` block. An expression body is a stand-in VALUE (`() => false`, which the caller reads) unless it is
        // nothing (`null`, `undefined`, an empty object) or a call that makes nothing visible happen.
        const quiet = ts.isBlock(body)
          ? !tells(body) && !throws(body) && !returnsValue(body) && !records(body)
          : isNothing(body) || (ts.isCallExpression(body) && !tells(body));
        if (quiet && !saysWhy(h)) {
          out.push({ file: rel, line: lineOf(n), fn: functionName(n), kind: ".catch", detail: h.getText().replace(/\s+/g, " ").slice(0, 80) });
        }
      }
    }
    ts.forEachChild(n, visit);
  })(sf);
  return { examined, findings: out };
}

function sourceFiles(webRoot: string, dir: string): string[] {
  const out: string[] = [];
  const abs = path.join(webRoot, dir);
  if (!fs.existsSync(abs)) return out;
  for (const entry of fs.readdirSync(abs, { withFileTypes: true })) {
    if (entry.name === "node_modules" || entry.name === ".next" || entry.name === "out" || entry.name.startsWith(".")) continue;
    const rel = path.posix.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...sourceFiles(webRoot, rel));
    else if (/\.(ts|tsx)$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) && !/\.d\.ts$/.test(entry.name)) out.push(rel);
  }
  return out;
}

/** Every quiet catch around a server call under `app/`, `components/`, `lib/` and `contexts/`. */
export function scanTree(webRoot: string): { filesScanned: number; examined: number; findings: QuietCatch[] } {
  const files = ["app", "components", "lib", "contexts"].flatMap((d) => sourceFiles(webRoot, d)).sort();
  const findings: QuietCatch[] = [];
  let examined = 0;
  for (const rel of files) {
    const r = scanSource(rel, fs.readFileSync(path.join(webRoot, rel), "utf8"));
    examined += r.examined;
    findings.push(...r.findings);
  }
  return { filesScanned: files.length, examined, findings };
}
