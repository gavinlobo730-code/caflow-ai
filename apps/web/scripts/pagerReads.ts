// What "a read through the shared pager that reads its error" means, as a scan over the source (POST-A-527). Used by
// scripts/a-pager-read-reads-its-error.test.ts; its own negative controls are in that file.
//
// `lib/supabase/selectAll.ts` exports two pagers, `selectAll` and `selectAllKeyset`. Both HAND A FAILURE BACK as `{ data, error }` and
// neither throws: a page that fails ends the read with the rows gathered so far and the error beside them. A caller that takes `data`
// alone therefore draws a refused read as an empty list, and a read that stopped partway as the whole list; wrapping the call in a `try`
// does not help, because nothing throws. Four client pickers had exactly that, with a `catch` written to cover it that never ran.
//
// THE RULE: the answer of an awaited pager call must be taken as `const { data, error } = await selectAll(...)` (or `error: someName`),
// or as `const r = await selectAll(...)` with `r.error` read, and the error must be USED: named again somewhere in the same function
// (a condition, a throw, a setter, a return). Taking `error` and never looking at it is the same fault with a longer spelling. A call
// whose answer is returned straight to the caller (`return selectAll(...)`, `return await selectAll(...)`) hands the error on and is not
// judged here; the caller is.
//
// What it does not see: a pager call behind a name declared elsewhere (a helper that wraps `selectAll`), a result passed into another
// function before its `error` is read, and what a screen does with the error once it is used. Those are other rules or open items.
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const PAGERS = new Set(["selectAll", "selectAllKeyset"]);

export type PagerRead = { file: string; line: number; fn: string; why: string };

function descendants(node: ts.Node, fn: (c: ts.Node) => void): void {
  ts.forEachChild(node, (c) => {
    fn(c);
    descendants(c, fn);
  });
}

function enclosingFunction(n: ts.Node): ts.Node {
  for (let p: ts.Node | undefined = n.parent; p; p = p.parent) {
    if (ts.isFunctionLike(p) || ts.isSourceFile(p)) return p;
  }
  return n;
}

function functionName(n: ts.Node): string {
  for (let p: ts.Node | undefined = n.parent; p; p = p.parent) {
    if (ts.isFunctionDeclaration(p) && p.name) return p.name.text;
    if ((ts.isArrowFunction(p) || ts.isFunctionExpression(p)) && p.parent && ts.isVariableDeclaration(p.parent) && ts.isIdentifier(p.parent.name)) return p.parent.name.text;
    if (ts.isMethodDeclaration(p) && p.name) return p.name.getText();
  }
  return "(anonymous)";
}

/** How many times `name` is referenced inside `scope`, counting every identifier with that text (the declaration included). */
function mentions(scope: ts.Node, name: string): number {
  let n = 0;
  descendants(scope, (c) => {
    if (ts.isIdentifier(c) && c.text === name) n++;
  });
  return n;
}

export function scanSource(rel: string, source: string): { examined: number; findings: PagerRead[] } {
  const sf = ts.createSourceFile(rel, source, ts.ScriptTarget.Latest, true, rel.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const findings: PagerRead[] = [];
  let examined = 0;
  const lineOf = (n: ts.Node) => sf.getLineAndCharacterOfPosition(n.getStart()).line + 1;
  (function visit(n: ts.Node): void {
    if (ts.isAwaitExpression(n) && ts.isCallExpression(n.expression) && ts.isIdentifier(n.expression.expression) && PAGERS.has(n.expression.expression.text)) {
      const at = (why: string) => findings.push({ file: rel, line: lineOf(n), fn: functionName(n), why });
      const parent = n.parent;
      // `return await selectAll(...)`: handed on, and the caller is judged where it stands.
      if (ts.isReturnStatement(parent)) {
        ts.forEachChild(n, visit);
        return;
      }
      examined++;
      if (ts.isVariableDeclaration(parent) && parent.initializer === n) {
        const scope = enclosingFunction(n);
        if (ts.isObjectBindingPattern(parent.name)) {
          const errorEl = parent.name.elements.find((e) => (e.propertyName ? e.propertyName.getText() === "error" : e.name.getText() === "error"));
          if (!errorEl) at("the answer is taken as `{ data }` and its `error` is never read");
          else if (!ts.isIdentifier(errorEl.name)) at("the `error` is taken apart without being named");
          else if (mentions(scope, errorEl.name.text) < 2) at(`the \`error\` is taken as \`${errorEl.name.text}\` and never looked at`);
        } else if (ts.isIdentifier(parent.name)) {
          const name = parent.name.text;
          let readsError = false;
          descendants(scope, (c) => {
            if (ts.isPropertyAccessExpression(c) && ts.isIdentifier(c.expression) && c.expression.text === name && c.name.text === "error") readsError = true;
          });
          if (!readsError) at(`the answer is held as \`${name}\` and \`${name}.error\` is never read`);
        } else {
          at("the answer is taken apart in a shape the scan cannot follow");
        }
      } else if (ts.isExpressionStatement(parent)) {
        at("the answer is thrown away");
      } else {
        at("the answer is used in a shape the scan cannot follow");
      }
    }
    ts.forEachChild(n, visit);
  })(sf);
  return { examined, findings };
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

/** Every awaited pager call under `app/`, `components/`, `lib/` and `contexts/`, except the pagers' own file. */
export function scanTree(webRoot: string): { filesScanned: number; examined: number; findings: PagerRead[] } {
  const files = ["app", "components", "lib", "contexts"].flatMap((d) => sourceFiles(webRoot, d)).filter((f) => f !== "lib/supabase/selectAll.ts").sort();
  const findings: PagerRead[] = [];
  let examined = 0;
  for (const rel of files) {
    const r = scanSource(rel, fs.readFileSync(path.join(webRoot, rel), "utf8"));
    examined += r.examined;
    findings.push(...r.findings);
  }
  return { filesScanned: files.length, examined, findings };
}
