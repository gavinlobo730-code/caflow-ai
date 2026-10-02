// NO SCREEN USES A NATIVE alert(), confirm() OR prompt() (frontend_ux-21).
//   node --experimental-strip-types --test scripts/no-screen-uses-a-native-popup.test.ts
//
// ─────────────────────────────────────────────────────────────────────────────
// THE DEFECT
// ─────────────────────────────────────────────────────────────────────────────
// 44 native pop-ups in 26 files stood beside 32 `confirmDialog()` calls and the
// toast system. A native dialog cannot be styled, cannot say what a statutory
// action will do, blocks the page and anything automating it, and reads as the
// BROWSER asking rather than the product — on a screen that is about to delete a
// bank account or reverse a payroll run. `lib/invoices/dirtyState.ts` held one as
// a DEFAULT, so an editor that forgot to inject its confirm UI got a browser
// dialog instead of a type error.
//
// ─────────────────────────────────────────────────────────────────────────────
// THE RULE, held from two sides
// ─────────────────────────────────────────────────────────────────────────────
//  1. `no-alert` is an ERROR in .eslintrc.json — the finding's own verify line,
//     and what stops the next one in an editor. `pnpm lint` runs it over app,
//     components and lib.
//  2. This file states the same rule over the same tree with the TypeScript parser,
//     because lint is not part of `pnpm test` and a guard that only runs when
//     somebody remembers to lint is the one that is bypassed. It mirrors ESLint's
//     own definition: a call to the global `alert` / `confirm` / `prompt`, or to the
//     same on `window` / `globalThis`, where the file declares no function or
//     variable of that name (components/team/OpenWorkPanel.tsx has a local
//     `confirm` that opens a reassign dialog and is not the global).
//
// The replacements are `confirmDialog` and `promptDialog` (components/ui/confirm-
// dialog.tsx; behaviour proved in confirm-dialog.test.ts) and `toast`.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import ts from "typescript";

const WEB = join(import.meta.dirname, "..");
const NATIVE = new Set(["alert", "confirm", "prompt"]);
const GLOBALS = new Set(["window", "globalThis", "self"]);

export interface Hit { line: number; call: string }

/** Native dialog calls in `source`, by ESLint's own definition. */
export function nativePopups(fileName: string, source: string): Hit[] {
  const sf = ts.createSourceFile(fileName, source, ts.ScriptTarget.Latest, true,
    fileName.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);

  // Anything in this file that gives one of the three names a meaning of its own.
  const declared = new Set<string>();
  const collect = (n: ts.Node): void => {
    if ((ts.isFunctionDeclaration(n) || ts.isVariableDeclaration(n) || ts.isParameter(n) ||
         ts.isImportSpecifier(n) || ts.isBindingElement(n)) &&
        n.name && ts.isIdentifier(n.name) && NATIVE.has(n.name.text)) declared.add(n.name.text);
    ts.forEachChild(n, collect);
  };
  collect(sf);

  const hits: Hit[] = [];
  const visit = (n: ts.Node): void => {
    if (ts.isCallExpression(n)) {
      // `x?.()` and `(0, alert)()` are not written in this tree; the two shapes
      // below are the ones ESLint's no-alert reports.
      const c = n.expression;
      let name: string | null = null;
      if (ts.isIdentifier(c) && NATIVE.has(c.text) && !declared.has(c.text)) name = c.text;
      else if (ts.isPropertyAccessExpression(c) && ts.isIdentifier(c.expression) &&
               GLOBALS.has(c.expression.text) && NATIVE.has(c.name.text)) name = `${c.expression.text}.${c.name.text}`;
      else if (ts.isElementAccessExpression(c) && ts.isIdentifier(c.expression) &&
               GLOBALS.has(c.expression.text) && ts.isStringLiteralLike(c.argumentExpression) &&
               NATIVE.has(c.argumentExpression.text)) name = `${c.expression.text}["${c.argumentExpression.text}"]`;
      if (name) hits.push({ line: sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1, call: name });
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  return hits;
}

function walk(dir: string, out: string[] = []): string[] {
  for (const e of readdirSync(join(WEB, dir))) {
    if (e === "node_modules" || e === ".next") continue;
    const rel = join(dir, e).replace(/\\/g, "/");
    if (statSync(join(WEB, rel)).isDirectory()) walk(rel, out);
    else if (/\.(ts|tsx)$/.test(rel) && !rel.endsWith(".test.ts") && !rel.endsWith(".d.ts")) out.push(rel);
  }
  return out;
}

// ═════════════════════════════════════════════════════════════════════════════
// THE DETECTOR
// ═════════════════════════════════════════════════════════════════════════════

test("the detector finds each native call and each way of spelling it", () => {
  const found = (src: string) => nativePopups("t.tsx", src).map((h) => h.call);
  assert.deepEqual(found(`if (!confirm("x")) return;`), ["confirm"]);
  assert.deepEqual(found(`alert("x");`), ["alert"]);
  assert.deepEqual(found(`const r = prompt("x");`), ["prompt"]);
  assert.deepEqual(found(`window.confirm("x")`), ["window.confirm"]);
  assert.deepEqual(found(`window.prompt("x")`), ["window.prompt"]);
  assert.deepEqual(found(`globalThis.alert("x")`), ["globalThis.alert"]);
  assert.deepEqual(found(`window["confirm"]("x")`), ['window["confirm"]']);
  assert.deepEqual(found(`typeof window === "undefined" ? true : window.confirm(m)`), ["window.confirm"],
    "the form dirtyState.ts held");
});

test("it leaves the replacements, other methods and a local of the same name alone", () => {
  const found = (src: string) => nativePopups("t.tsx", src).length;
  assert.equal(found(`await confirmDialog("x"); await promptDialog("y"); toast({ title: "z" });`), 0);
  assert.equal(found(`window.open(url); window.print(); window.location.reload();`), 0);
  assert.equal(found(`modal.confirm("x"); dialog.alert("y"); form.prompt("z");`), 0, "a method of something else");
  assert.equal(found(`async function confirm() { await save(); } confirm();`), 0,
    "OpenWorkPanel's own `confirm` is not the global");
  assert.equal(found(`const prompt = "x"; use(prompt);`), 0);
  assert.equal(found(`function f(alert) { alert(); }`), 0, "a parameter of that name");
  assert.equal(found(`// confirm("x")\n/* alert("y") */\nconst s = "prompt(1)";`), 0, "comments and strings are not calls");
});

// ═════════════════════════════════════════════════════════════════════════════
// THE TREE
// ═════════════════════════════════════════════════════════════════════════════

test("no file under app, components or lib calls a native alert, confirm or prompt", () => {
  const offenders: string[] = [];
  let files = 0;
  for (const rel of ["app", "components", "lib"].flatMap((d) => walk(d))) {
    files++;
    for (const h of nativePopups(rel, readFileSync(join(WEB, rel), "utf8"))) {
      offenders.push(`${rel}:${h.line}  ${h.call}()`);
    }
  }
  assert.ok(files > 500, `only ${files} files walked — the scan is broken`);
  assert.deepEqual(offenders, [],
    "use `await confirmDialog({ message, danger: true, confirmLabel })` (and keep refusing on cancel), " +
    "`await promptDialog({ message, required })` for a typed answer (null on cancel), and `toast({ title, " +
    "variant: \"destructive\" })` for a failure:\n  " + offenders.join("\n  "));
});

test("no-alert is an error in the lint config, which is the other half of the rule", () => {
  const cfg = JSON.parse(readFileSync(join(WEB, ".eslintrc.json"), "utf8")) as { rules?: Record<string, unknown> };
  const level = cfg.rules?.["no-alert"];
  assert.ok(level === "error" || level === 2 || (Array.isArray(level) && (level[0] === "error" || level[0] === 2)),
    `no-alert must be "error" in .eslintrc.json (it is ${JSON.stringify(level)})`);
});

test("useUnsavedChanges has no browser-dialog default: its confirm UI is required", () => {
  const src = readFileSync(join(WEB, "lib/invoices/dirtyState.ts"), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "");
  const sig = /export function useUnsavedChanges\(([\s\S]*?)\) \{/.exec(src)?.[1] ?? "";
  // Anchored at the end of the parameter list: a default value would continue
  // the text with `= …` and fail this.
  assert.match(sig, /confirmFn:\s*\(message: string\) => boolean \| Promise<boolean>,?\s*$/,
    "the third parameter is required and has no default: a default is a dialog nobody chose");
});
