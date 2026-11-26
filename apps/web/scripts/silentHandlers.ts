// What "a button that saves can end with no answer" means, as a scan over the source (POST-A-515). Used by
// scripts/a-button-that-saves-tells-the-person-when-it-fails.test.ts; its own negative controls are in that file.
//
// A HANDLER is the function a button, form or dialog is wired to: the value of an `onClick`, `onSubmit`, `onSave`, `onConfirm`, ... attribute,
// resolved through a name declared in the same file, or through an inline arrow that does nothing but call such a name. The scan asks about
// the handlers that AWAIT a server call (`api.*`, the Supabase client, `fetch`, `rpc`, the shared pagers):
//
//   H1  nothing in it makes a visible effect at all (a state setter, a toast, an alert, a dialog, a navigation, a callback) and it throws
//       nothing: whatever it does, the person is told nothing;
//   H2  a catch in it that DISCARDS the failure: empty or only logging, with no comment inside it saying why (a catch that records the
//       failure for its caller, `failures.push(...)`, `error = e`, `return { ok: false, ... }`, is not a discard);
//   H3  a failure branch (`if (!res.success) return`, `if (error) return`) that returns with no value and without a word;
//   H4  a server call outside every try, in a handler with no `.catch(`: the API helper THROWS on a failed request, so nothing then catches
//       it and the person sees the button do nothing.
//
// Only `onClick`, `onSubmit` and `onPress` are judged on a COMPONENT (`<Button onClick={save}>`); any other callback handed to a component
// (`<EditRoleModal onSave={handleEditRole}>`, `<ImportDialog onImport={...}>`) is the component's to call, and what the component does with a
// rejection is read where the component stands: the rule is about the function a person's press runs. What a component does with a callback
// is NOT read, and that is a limit of this rule, not a finding.
//
// A handler that hands its failure to a function in the same file which tells (`write(async () => ...)` whose own catch sets the message) is
// followed one level, and so is a call such as `say(...)` or `fail(...)` whose body calls a setter.
//
// A CATCH THAT IS QUIET ON PURPOSE SAYS WHY, IN A COMMENT INSIDE IT (`catch { /* the audit write must not block the save */ }`), and the
// comment is the review: H2 does not flag a quiet catch whose block carries a comment of ten characters or more, EXCEPT where the catch
// wraps the handler's FIRST server call. That call is the thing the person pressed the button for, and "the backend enforces" in a comment
// is how a refused restore stayed silent: only a call that comes after it (a timeline write, a refresh, a prefill) may be quiet on a comment.
//
// The scan is deliberately a heuristic over names: it reads what a function CALLS, not what the screen shows. A place it flags that is quiet
// on purpose in some other way belongs on the frozen list, with the flag; a place it misses is a place the rule does not reach, and the rule
// says so rather than claiming more.
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

/** A function declared in the file, found by the name a call uses and the place it is called from (two components in one file may both
 *  declare a `handleSave`; the one in the nearest enclosing scope is the one a call there means). */
type Named = (name: string, from: ts.Node) => ts.FunctionLikeDeclaration | undefined;

export type SilentClass = "H1" | "H2" | "H3" | "H4";
export type SilentFinding = { cls: SilentClass; file: string; line: number; fn: string; detail: string };

/** A server call: the API client, the Supabase client, a raw request, a Postgres function, or one of the shared pagers. */
const NET = /(^|[^\w.])(api\.|supabase\b|getSupabaseClient|fetch\(|apiFetch|request\(|selectAll|selectAllKeyset|uploadWithProgress)|\.(from|rpc)\(|\.auth\./;
/** A server call whose helper THROWS on a failed request (the API client, `fetch`): the browser's Supabase client does not, it hands back
 *  `{ error }`, and a write that ignores that answer is another rule (a-browser-write-reads-its-answer-and-says-it-in-the-products-words). */
const THROWS = /(^|[^\w.])(api\.|fetch\(|apiFetch|request\(|uploadWithProgress)/;
/** A call that makes SOMETHING happen on the screen or in the page. */
const EFFECT = /^(set[A-Z]\w*|toast(\.\w+)?|notify\w*|(window\.)?alert|show[A-Z]\w*|push\w*|add[A-Z]\w*Toast|confirmDialog|promptDialog|dispatch|on[A-Z]\w*|reportError|router\.\w+|window\.location\.\w+|navigate\w*|mutate|refetch|reload|load\w*|refresh\w*|fetch[A-Z]\w*|reset\w*|close\w*|open\w*|clear\w*|download\w*|save\w*As|\w+\.(set[A-Z]\w*|on[A-Z]\w*|click|focus|scrollIntoView|download\w*|open|print)|setTimeout)$/;
/** A call that TELLS the person (a narrower list than EFFECT: a reload is an effect and says nothing). */
const TELLS = /^(set[A-Z]\w*|toast(\.\w+)?|notify\w*|(window\.)?alert|show[A-Z]\w*|ask[A-Z]\w*|confirmDialog|promptDialog|dispatch|on[A-Z]\w*|reportError|\w+\.(set[A-Z]\w*|on[A-Z]\w*))$/;
const LOGS = /^(console\.\w+|(\w*[lL]ogger|log)\.\w+|log\w*)$/;
const HANDLER_ATTR = /^on(Click|Submit|Save|Confirm|Create|Update|Delete|Remove|Add|Approve|Send|Apply|Press|Action|Accept|Reject|Issue|Import|Upload|Finish|Complete|Post|Record|Submit\w*)$/;

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

function hasCall(node: ts.Node, re: RegExp): boolean {
  return callsIn(node).some((c) => re.test(calleeText(c)));
}

/** Whether `node` calls something that tells the person, directly or through ONE function declared in the same file. */
function tellsThrough(node: ts.Node, named: Named, re: RegExp): boolean {
  return callsIn(node).some((c) => {
    const callee = calleeText(c);
    if (re.test(callee)) return true;
    const local = /^\w+$/.test(callee) ? named(callee, c) : undefined;
    return !!local && !!local.body && hasCall(local.body, re);
  });
}

/** A callback handed to a component under a name other than the three presses (`onSave`, `onImport`, `onConfirm` ...). */
function isCallbackProp(attr: ts.JsxAttribute): boolean {
  const tag = attr.parent?.parent;
  const isElement = tag && (ts.isJsxOpeningElement(tag) || ts.isJsxSelfClosingElement(tag));
  if (!isElement) return false;
  return /^[A-Z]/.test(tag.tagName.getText()) && !/^on(Click|Submit|Press)$/.test(attr.name.getText());
}

/** Whether `n` stands inside a function handed to a function declared in the same file whose own catch does not discard the failure:
 *  `write(async () => { await api.save() })` with a `write` that catches and says it. A local function that merely happens to be called
 *  in the same handler (a reload) does not carry the failure of an unrelated call. */
function isDelegated(n: ts.Node, fnNode: ts.Node, named: Named): boolean {
  const own = ts.isAwaitExpression(n) ? n.expression : undefined;
  if (own && ts.isCallExpression(own)) {
    // `await act(() => api.save())`: the awaited call IS the wrapper
    const callee = calleeText(own);
    const local = /^\w+$/.test(callee) ? named(callee, own) : undefined;
    if (local && local.body && catchesAndTells(local.body, named)) return true;
  }
  for (let p: ts.Node | undefined = n.parent; p && p !== fnNode; p = p.parent) {
    if ((ts.isArrowFunction(p) || ts.isFunctionExpression(p)) && p.parent && ts.isCallExpression(p.parent) && p.parent.arguments.some((a) => a === p)) {
      const callee = calleeText(p.parent);
      const local = /^\w+$/.test(callee) ? named(callee, p.parent) : undefined;
      if (local && local.body && catchesAndTells(local.body, named)) return true;
    }
  }
  return false;
}

/** Whether a function body holds a catch that does not discard the failure. */
function catchesAndTells(body: ts.Node, named: Named): boolean {
  let handled = false;
  descendants(body, (d) => {
    if (ts.isCatchClause(d) && !discards(d.block, named)) handled = true;
  });
  return handled;
}

/** Whether a failure path hands the failure back to its caller instead of dropping it: an assignment, a push, or a returned value. */
function recordsFailure(block: ts.Block): boolean {
  let records = false;
  const consider = (c: ts.Node) => {
    if (ts.isBinaryExpression(c) && c.operatorToken.kind === ts.SyntaxKind.EqualsToken) records = true;
    if (ts.isCallExpression(c) && /\.(push|add|set)$/.test(calleeText(c))) records = true;
    if (ts.isReturnStatement(c) && c.expression && !/^(undefined|null|false)$/.test(c.expression.getText())) records = true;
  };
  block.statements.forEach((st) => {
    consider(st);
    descendants(st, consider);
  });
  return records;
}

function hasThrow(node: ts.Node): boolean {
  let found = ts.isThrowStatement(node);
  descendants(node, (c) => {
    if (ts.isThrowStatement(c)) found = true;
  });
  return found;
}

/** `await Promise.all(items.map(async (x) => { try { await api.f(x) } ... }))`: the awaits that matter are the inner ones, each judged
 *  where it stands, so the outer await is not counted. */
function awaitsInnerFunctions(e: ts.Expression): boolean {
  if (!ts.isCallExpression(e) || !/^Promise\.(all|allSettled|race)$/.test(calleeText(e))) return false;
  let inner = false;
  descendants(e, (d) => {
    if ((ts.isArrowFunction(d) || ts.isFunctionExpression(d)) && d.modifiers?.some((m) => m.kind === ts.SyntaxKind.AsyncKeyword)) inner = true;
  });
  return inner;
}

function netAwaits(node: ts.Node, re: RegExp = NET): ts.AwaitExpression[] {
  const out: ts.AwaitExpression[] = [];
  const consider = (c: ts.Node) => {
    if (ts.isAwaitExpression(c) && re.test(c.expression.getText()) && !awaitsInnerFunctions(c.expression)) out.push(c);
  };
  consider(node);
  descendants(node, consider);
  return out;
}

function insideTry(n: ts.Node, fnNode: ts.Node): boolean {
  for (let p: ts.Node | undefined = n.parent; p && p !== fnNode; p = p.parent) {
    if (ts.isTryStatement(p) && p.tryBlock.pos <= n.pos && n.end <= p.tryBlock.end) return true;
  }
  return false;
}

function functionName(n: ts.Node): string {
  if (ts.isFunctionDeclaration(n) && n.name) return n.name.text;
  const p = n.parent;
  if (p && ts.isVariableDeclaration(p) && ts.isIdentifier(p.name)) return p.name.text;
  if (p && ts.isCallExpression(p) && p.parent && ts.isVariableDeclaration(p.parent) && ts.isIdentifier(p.parent.name)) return p.parent.name.text;
  return "(inline)";
}

/** Whether a catch block DISCARDS the failure: it throws nothing, tells nothing, records nothing, and does at most log. */
function discards(block: ts.Block, named: Named): boolean {
  if (hasThrow(block) || tellsThrough(block, named, TELLS) || recordsFailure(block)) return false;
  return block.statements.every((st) => ts.isExpressionStatement(st) && ts.isCallExpression(st.expression) && LOGS.test(calleeText(st.expression)));
}

/** Whether a block carries a comment saying why it is quiet: any comment inside it with ten or more characters of words. */
function explainsItself(block: ts.Block, sf: ts.SourceFile): boolean {
  const comments: string[] = [];
  const take = (ranges: ts.CommentRange[] | undefined) => {
    for (const r of ranges ?? []) comments.push(sf.text.slice(r.pos, r.end));
  };
  const open = block.getStart(sf) + 1;
  take(ts.getLeadingCommentRanges(sf.text, open));
  take(ts.getTrailingCommentRanges(sf.text, open));
  take(ts.getLeadingCommentRanges(sf.text, block.statements.end));
  take(ts.getTrailingCommentRanges(sf.text, block.statements.end));
  for (const s of block.statements) {
    take(ts.getLeadingCommentRanges(sf.text, s.getFullStart()));
    take(ts.getTrailingCommentRanges(sf.text, s.getEnd()));
  }
  return comments.some((c) => c.replace(/^\/[/*]+|\*+\/$/g, "").trim().length >= 10);
}

const lineOf = (sf: ts.SourceFile, n: ts.Node): number => sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1;
const short = (s: string, n: number): string => s.replace(/\s+/g, " ").slice(0, n);

/** The silent handlers of one source file. `rel` is the path the finding is reported under. */
export function scanSource(rel: string, text: string): { handlersWithServerCall: number; findings: SilentFinding[] } {
  const sf = ts.createSourceFile(rel, text, ts.ScriptTarget.Latest, true, rel.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const findings: SilentFinding[] = [];
  let handlersWithServerCall = 0;

  // every named function-like in the file, so `onClick={save}` can be followed to `save`
  const declared = new Map<string, ts.FunctionLikeDeclaration[]>();
  const declare = (name: string, fn: ts.FunctionLikeDeclaration) => declared.set(name, [...(declared.get(name) ?? []), fn]);
  (function collect(n: ts.Node): void {
    if (ts.isFunctionDeclaration(n) && n.name && n.body) declare(n.name.text, n);
    if (ts.isVariableDeclaration(n) && ts.isIdentifier(n.name) && n.initializer) {
      let init: ts.Expression = n.initializer;
      if (ts.isCallExpression(init) && init.arguments[0] && /^(useCallback|useMemo)$/.test(init.expression.getText())) init = init.arguments[0];
      if (ts.isArrowFunction(init) || ts.isFunctionExpression(init)) declare(n.name.text, init);
    }
    ts.forEachChild(n, collect);
  })(sf);
  const scopeOf = (fn: ts.Node): ts.Node => {
    for (let p: ts.Node | undefined = fn.parent; p; p = p.parent) if (ts.isFunctionLike(p) || ts.isSourceFile(p)) return p;
    return sf;
  };
  const contains = (outer: ts.Node, inner: ts.Node): boolean => outer.pos <= inner.pos && inner.end <= outer.end;
  const named: Named = (name, from) => {
    const candidates = (declared.get(name) ?? []).filter((c) => contains(scopeOf(c), from));
    candidates.sort((a, b) => scopeOf(b).pos - scopeOf(a).pos);        // the innermost scope first
    return candidates[0];
  };

  const seen = new Set<ts.Node>();
  (function visit(n: ts.Node): void {
    if (ts.isJsxAttribute(n) && n.name && HANDLER_ATTR.test(n.name.getText()) && !isCallbackProp(n) && n.initializer && ts.isJsxExpression(n.initializer) && n.initializer.expression) {
      const e = n.initializer.expression;
      let fn: ts.FunctionLikeDeclaration | null = null;
      let label = "(inline)";
      if (ts.isIdentifier(e) && named(e.text, e)) {
        fn = named(e.text, e)!;
        label = e.text;
      } else if (ts.isArrowFunction(e) || ts.isFunctionExpression(e)) {
        fn = e;
        // `() => save(id)`: the named function is the real handler
        const body = ts.isBlock(e.body)
          ? e.body.statements.length === 1 && ts.isExpressionStatement(e.body.statements[0])
            ? (e.body.statements[0] as ts.ExpressionStatement).expression
            : null
          : e.body;
        const inner = body && ts.isAwaitExpression(body) ? body.expression : body;
        if (inner && ts.isCallExpression(inner) && ts.isIdentifier(inner.expression) && named(inner.expression.text, inner)) {
          fn = named(inner.expression.text, inner)!;
          label = inner.expression.text;
        }
      }
      if (fn && fn.body && !seen.has(fn)) {
        seen.add(fn);
        const awaits = netAwaits(fn.body);
        if (awaits.length) {
          handlersWithServerCall++;
          const where = { file: rel, fn: label !== "(inline)" ? label : functionName(fn) };
          const here = (cls: SilentClass, at: ts.Node, detail: string) => findings.push({ cls, ...where, line: lineOf(sf, at), detail });
                    if (!tellsThrough(fn.body, named, EFFECT) && !hasThrow(fn.body)) here("H1", fn, short(awaits[0].expression.getText(), 70));
          const bare = netAwaits(fn.body, THROWS).filter((a) => !insideTry(a, fn!) && !isDelegated(a, fn!, named));
          if (bare.length && !/\.catch\(/.test(fn.body.getText())) here("H4", fn, short(bare[0].expression.getText(), 70));
          descendants(fn.body, (c) => {
            if (ts.isCatchClause(c) && discards(c.block, named)) {
              const tryNode = c.parent;
              const inTry = ts.isTryStatement(tryNode) ? netAwaits(tryNode.tryBlock) : [];
              const wrapsFirstCall = inTry.length > 0 && inTry[0] === awaits[0];
              if (!inTry.length || (explainsItself(c.block, sf) && !wrapsFirstCall)) return;
              here("H2", c, "catch: " + (c.block.statements.length ? c.block.statements.map((s) => short(s.getText(), 40)).join(" ; ").slice(0, 80) : "(empty)"));
            }
            // a failure branch that returns without a word
            if (ts.isIfStatement(c) && /!\s*[\w.?]+\.success|\.success\s*===?\s*false|\b(error|err|\w+Err|\w+Error)\b/.test(c.expression.getText())) {
              const t = c.thenStatement;
              const returns = ts.isBlock(t) ? t.statements.some((s) => ts.isReturnStatement(s)) : ts.isReturnStatement(t);
              if (returns && !recordsFailure(ts.isBlock(t) ? t : ts.factory.createBlock([t as ts.Statement])) && !tellsThrough(t, named, TELLS) && !tellsThrough(c.expression, named, TELLS) && !hasThrow(t)) here("H3", c, "if (" + short(c.expression.getText(), 50) + ") return");
            }
          });
        }
      }
    }
    ts.forEachChild(n, visit);
  })(sf);

  return { handlersWithServerCall, findings };
}

function sourceFiles(webRoot: string, dir: string): string[] {
  const out: string[] = [];
  for (const entry of fs.readdirSync(path.join(webRoot, dir), { withFileTypes: true })) {
    if (entry.name === "node_modules" || entry.name === ".next" || entry.name === "out") continue;
    const rel = path.posix.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...sourceFiles(webRoot, rel));
    else if (/\.tsx$/.test(entry.name) && !/\.test\.tsx$/.test(entry.name)) out.push(rel);
  }
  return out;
}

/** Every silent handler under `app/` and `components/` (a handler is wired in JSX, so only `.tsx` files hold one). */
export function scanTree(webRoot: string): { filesScanned: number; handlersWithServerCall: number; findings: SilentFinding[] } {
  const files = [...sourceFiles(webRoot, "app"), ...sourceFiles(webRoot, "components")].sort();
  const findings: SilentFinding[] = [];
  let handlersWithServerCall = 0;
  for (const rel of files) {
    const r = scanSource(rel, fs.readFileSync(path.join(webRoot, rel), "utf8"));
    handlersWithServerCall += r.handlersWithServerCall;
    findings.push(...r.findings);
  }
  return { filesScanned: files.length, handlersWithServerCall, findings };
}

/** The key a finding is frozen under: the rule, the file and the function, never the line (an edit above it must not change it). */
export const keyOf = (f: SilentFinding): string => `${f.cls}|${f.file}|${f.fn}`;

export function countByKey(findings: SilentFinding[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const f of findings) out[keyOf(f)] = (out[keyOf(f)] ?? 0) + 1;
  return out;
}
