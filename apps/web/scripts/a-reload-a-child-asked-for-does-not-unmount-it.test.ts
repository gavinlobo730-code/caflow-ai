// A screen that hands its loader to a child does not replace itself with "Loading…" when the child asks for a reload
// (POST-A-400).
//
// Run with:
//   node --experimental-strip-types --test scripts/a-reload-a-child-asked-for-does-not-unmount-it.test.ts
//
// THE DEFECT
//     A component whose loader raised its loading flag on EVERY read (`setLoading(true)` as a statement of its own) and
//     which returned "Loading…" in place of itself (`if (loading) return …`) unmounted every child it had drawn whenever
//     it read again. When it handed that loader to a child (`onSaved={load}`, `onChanged={load}`, `onDone={load}`), the
//     child asked for the read that unmounted it: its confirmation, an open form and anything it had chosen were lost,
//     and the person saw the screen blank and come back without being told the save had worked. The sales cycle tab was
//     the first (POST-A-385); the practice page's tax identity card, the roster's portal access dialog, a client's
//     employees tab and the stock locations' Move stock panel were the next four, and they now block only on the first
//     read of their key (`lib/loading/firstRead`).
//
// THE RULE
//     Read per component, with the TypeScript parser: a component is refused when all three hold in its own body:
//       1. a function it declares raises `setLoading(true)` as a statement of the function's own block (not under an
//          `if`, which is how a first-read-only loader is written by hand);
//       2. it returns early on `loading` (`if (loading) return …`), so the flag replaces the whole component;
//       3. it passes that function as a prop of a component it draws (`<Child onSaved={load} />`, or a function that calls
//          it, `onChanged={() => load()}`), other than a button's `onClick` (a person pressing Retry, which holds nothing
//          to lose) and a function that closes the child before it reads (`() => { setAdding(false); load(); }`), which
//          unmounts the child on purpose.
//     A loader written through `useFirstRead` raises no flag itself and is not one.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const ROOT = path.resolve(import.meta.dirname, "..");

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(path.join(ROOT, dir), { withFileTypes: true })) {
    const rel = path.join(dir, e.name);
    if (e.isDirectory()) {
      if (e.name !== "node_modules") walk(rel, out);
    } else if (e.name.endsWith(".tsx") && !e.name.endsWith(".test.tsx")) {
      out.push(rel);
    }
  }
  return out;
}

type Fn = ts.FunctionDeclaration | ts.FunctionExpression | ts.ArrowFunction;

function isFn(n: ts.Node): n is Fn {
  return ts.isFunctionDeclaration(n) || ts.isFunctionExpression(n) || ts.isArrowFunction(n);
}

/** The block of a function, or of the function handed to `useCallback(…)`. */
function blockOf(n: ts.Node): ts.Block | null {
  if (isFn(n) && n.body && ts.isBlock(n.body)) return n.body;
  if (ts.isCallExpression(n) && ts.isIdentifier(n.expression) && n.expression.text === "useCallback") {
    const first = n.arguments[0];
    return first ? blockOf(first) : null;
  }
  return null;
}

function raisesLoadingOnEveryRead(block: ts.Block): boolean {
  return block.statements.some((s) =>
    ts.isExpressionStatement(s) && ts.isCallExpression(s.expression) &&
    ts.isIdentifier(s.expression.expression) && s.expression.expression.text === "setLoading" &&
    s.expression.arguments.length === 1 && s.expression.arguments[0].kind === ts.SyntaxKind.TrueKeyword);
}

function returnsEarlyOnLoading(block: ts.Block): boolean {
  return block.statements.some((s) => {
    if (!ts.isIfStatement(s) || !ts.isIdentifier(s.expression) || s.expression.text !== "loading") return false;
    const then = s.thenStatement;
    return ts.isReturnStatement(then) || (ts.isBlock(then) && then.statements.some(ts.isReturnStatement));
  });
}

/** Names handed, as `{name}`, to a prop of a component (a JSX tag that starts with a capital) anywhere in `node`. */
function namesHandedToChildren(node: ts.Node): Set<string> {
  const names = new Set<string>();
  const visit = (n: ts.Node) => {
    if (ts.isJsxAttribute(n) && n.initializer && ts.isJsxExpression(n.initializer) && n.initializer.expression) {
      const tag = n.parent?.parent;
      const tagName = tag && (ts.isJsxSelfClosingElement(tag) || ts.isJsxOpeningElement(tag)) ? tag.tagName.getText() : "";
      // A button's `onClick={load}` is a person pressing Retry, which holds nothing to lose; a prop a child CALLS after it
      // has done something (`onSaved`, `onChanged`, `onDone`, a table's `onRefresh`) is the shape, whether it hands the
      // loader itself (`onSaved={load}`) or a function that calls it (`onSaved={() => { close(); load(); }}`).
      if (/^[A-Z]/.test(tagName) && n.name.getText() !== "onClick") {
        const value = n.initializer.expression;
        if (ts.isIdentifier(value)) names.add(value.text);
        else if (ts.isArrowFunction(value) || ts.isFunctionExpression(value)) {
          // A function that CLOSES the child first (`setAdding(false)`, `setOpen(null)`) unmounts it on purpose, so the
          // read it then asks for loses nothing of the child's; one that leaves the child open is the shape.
          const called: string[] = [];
          let closes = false;
          const calls = (m: ts.Node) => {
            if (ts.isCallExpression(m) && ts.isIdentifier(m.expression)) {
              called.push(m.expression.text);
              const arg = m.arguments[0];
              if (/^set[A-Z]/.test(m.expression.text) && arg &&
                  (arg.kind === ts.SyntaxKind.NullKeyword || arg.kind === ts.SyntaxKind.FalseKeyword)) closes = true;
            }
            ts.forEachChild(m, calls);
          };
          calls(value.body);
          if (!closes) called.forEach((c) => names.add(c));
        }
      }
    }
    ts.forEachChild(n, visit);
  };
  visit(node);
  return names;
}

/** Every component-shaped function in a file: a function whose block returns early on `loading` is all the rule needs. */
function offendersIn(file: string): string[] {
  const src = fs.readFileSync(path.join(ROOT, file), "utf8");
  const sf = ts.createSourceFile(file, src, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const out: string[] = [];
  const visit = (n: ts.Node) => {
    const block = isFn(n) ? blockOf(n) : null;
    if (block && returnsEarlyOnLoading(block)) {
      const handed = namesHandedToChildren(block);
      for (const st of block.statements) {
        let name = "", body: ts.Block | null = null;
        if (ts.isFunctionDeclaration(st) && st.name) { name = st.name.text; body = blockOf(st); }
        if (ts.isVariableStatement(st)) {
          for (const d of st.declarationList.declarations) {
            if (ts.isIdentifier(d.name) && d.initializer) { name = d.name.text; body = blockOf(d.initializer); }
          }
        }
        if (body && raisesLoadingOnEveryRead(body) && handed.has(name)) {
          const line = sf.getLineAndCharacterOfPosition(st.getStart()).line + 1;
          out.push(`${file}:${line} ${name}`);
        }
      }
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  return out;
}

test("no screen hands a child a loader that replaces the screen with Loading on every read", () => {
  const offenders = [...walk("app"), ...walk("components")].flatMap(offendersIn);
  assert.deepEqual(offenders, [], "use lib/loading/firstRead so a reload a child asked for does not unmount the child");
});

test("the rule finds the shape it was written for (negative control)", () => {
  const dir = fs.mkdtempSync(path.join(ROOT, "scripts", ".tmp-reload-"));
  try {
    const rel = path.relative(ROOT, path.join(dir, "Sample.tsx"));
    fs.writeFileSync(path.join(ROOT, rel), `
      import { useCallback, useState } from "react";
      export default function Screen() {
        const [loading, setLoading] = useState(true);
        const load = useCallback(async () => { setLoading(true); try { await fetch("/x"); } finally { setLoading(false); } }, []);
        if (loading) return <p>Loading…</p>;
        return <Panel onSaved={load} />;
      }
      function Guarded() {
        const [loading, setLoading] = useState(true);
        const seen = { current: false };
        const load = useCallback(async () => { if (!seen.current) setLoading(true); setLoading(false); }, []);
        if (loading) return <p>Loading…</p>;
        return <Panel onSaved={load} />;
      }
      function Wrapped() {
        const [loading, setLoading] = useState(true);
        const load = useCallback(async () => { setLoading(true); setLoading(false); }, []);
        if (loading) return <p>Loading…</p>;
        return <Panel onChanged={() => load()} />;
      }
      function ClosesFirst() {
        const [loading, setLoading] = useState(true);
        const [open, setOpen] = useState(true);
        const load = useCallback(async () => { setLoading(true); setLoading(false); }, []);
        if (loading) return <p>Loading…</p>;
        return <Panel onSaved={() => { setOpen(false); load(); }} />;
      }
      function RegionOnly() {
        const [loading, setLoading] = useState(true);
        const load = useCallback(async () => { setLoading(true); setLoading(false); }, []);
        return <div>{loading ? <p>Loading…</p> : <Panel onSaved={load} />}</div>;
      }
    `);
    const found = offendersIn(rel);
    assert.equal(found.length, 2, found.join("\n"));   // Screen (the loader handed) and Wrapped (a function calling it)
    assert.ok(found.every((f) => / load$/.test(f)), found.join("\n"));
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("the four screens POST-A-400 named, and the deadlines list the rule found, read through the first-read rule", () => {
  for (const file of ["app/practice/page.tsx", "app/payroll/people/page.tsx", "app/clients/[id]/payroll/page.tsx",
                      "components/inventory/LocationsAndBatches.tsx", "app/deadlines/page.tsx"]) {
    assert.match(fs.readFileSync(path.join(ROOT, file), "utf8"), /useFirstRead\(/, file);
  }
});

test("the employee drawer, kept drawn through the reload it asks for, is given the row the reload read", () => {
  // Before, the reload unmounted the drawer and drew it again from the row it was opened on; kept drawn, it would keep
  // that row's name and status in its heading after a settlement closed the employee.
  const src = fs.readFileSync(path.join(ROOT, "app/clients/[id]/payroll/page.tsx"), "utf8");
  assert.match(src, /employee=\{employees\.find\(\(e\) => e\.id === openEmployee\.id\) \?\? openEmployee\}/);
});
