/**
 * Finds the buttons whose click starts an ASYNC WRITE — the shape that made one
 * click on Post Entry create eleven journals (frontend_ux-09).
 *
 * TWO THINGS ARE ASKED, AND BOTH HAVE TO HOLD
 *
 *   1. `findRawAsyncButtons` — a raw `<button>` whose click starts an async
 *      write. `components/ui/button.tsx` is the one place a repeat click is
 *      ignored: its `onClick` may return a promise, and it holds a REF (not
 *      state) from the moment the handler starts until the promise settles,
 *      disables itself, sets `aria-busy` and shows a spinner. A raw
 *      `<button onClick={save}>` has none of that, and `disabled={saving}` — the
 *      hand-rolled substitute, a flag in React state — lags the click by a
 *      render, so two clicks dispatched back to back both see `saving === false`
 *      and both reach the network.
 *
 *   2. `findDroppedPromises` — a `<Button>` whose handler STARTS an async write
 *      and does not hand the promise back. The primitive can only hold what it
 *      is given: `onClick={() => { save(); }}` and `onClick={() => void save()}`
 *      discard the promise, the guard is released on the same tick, and the
 *      screen has moved to the new component without gaining the protection it
 *      thinks it has. This is the half that makes a conversion REAL.
 *
 * WHAT COUNTS AS "ASYNC-WRITING"
 *     A click handler that runs — directly, through an inline arrow, or through a
 *     same-file function it calls — an `async` function whose body reaches a
 *     WRITE: a Supabase `.insert/.update/.upsert/.delete/.rpc`, an
 *     `api.<namespace>.<verb>(` where the verb is a mutating one, or an
 *     `apiCall`/`apiFetch`/`fetch`/`request` carrying a non-GET method. Reads are
 *     left out on purpose: a second click on Retry costs a wasted request, a
 *     second click on Post costs a duplicate voucher, and a ratchet that counts
 *     both is a number nobody acts on.
 *
 * WHAT IT DOES NOT SEE (a heuristic, and it says so)
 *     * a handler that arrives as a PROP (`onClick={props.onSave}`) — the editor
 *       that owns the promise is the one that can be asked, and it is converted
 *       where it is declared;
 *     * a write behind a helper in ANOTHER file;
 *     * a `<form onSubmit>` — a different primitive, recorded as not covered.
 *     A button it does not see is simply not counted, so the number can only
 *     understate, never invent a violation.
 *
 * Not a .test.ts on purpose: the ratchet test and any future caller both import
 * the analysis, and a helper two tests import from a third is how a test file
 * grows a second job.
 */
import ts from "typescript";

export interface RawAsyncButton {
  file: string;
  /** 1-based line of the `<button`. */
  line: number;
  /** The function the click reaches, as written. */
  handler: string;
  /** The write that makes it a write, e.g. `api.accounting.createJournalEntry`. */
  write: string;
}

/** A mutating verb on an `api.<ns>.<verb>(` call, matched as a WHOLE camelCase
 *  word at the start of the name (`payrollClientStates` is not `pay`). Anything
 *  not matching is a read (list, get, dashboard, statement, profitLoss, ...).
 *  Deliberately an allowlist: an unknown verb is not counted, so the ratchet
 *  understates rather than flagging a report download as a posting. */
const WRITE_VERB = new RegExp(
  "^(?:create|add|insert|update|edit|patch|put|delete|remove|post|save|submit|record|" +
  "issue|finali[sz]e|release|approve|reject|reverse|cancel|void|settle|import|upload|" +
  "generate|send|file|mark|pay|apply|allocate|correct|dispose|capitali[sz]e|" +
  "revalue|transition|toggle|invite|revoke|archive|restore|merge|assign|reassign|" +
  "convert|confirm|accept|decline|close|lock|unlock|sign|verify|matchMulti|unmatch|pass|" +
  "reopen|activate|deactivate|suspend|resend|resubmit|writedown|adjust|transfer|" +
  "disburse|depreciate|upsert|purge|provision|undo|set|unignore|ignore|runDue|" +
  "reconcile|reset|publish|share|link|unlink|enable|disable|retire|recompute|rename|" +
  // `clear…` is a DELETE (clearOpening drops a recorded credit-ledger balance) and `prepare…`
  // makes DRAFT documents through the sales engine (prepareDrafts): neither starts with any
  // verb above, and each sat beside a Save button the analysis did count.
  "clear|prepare)" +
  "(?:[A-Z0-9_]|$)",
);

const SUPABASE_WRITE = new Set(["insert", "update", "upsert", "delete", "rpc"]);
const FETCHERS = new Set(["apiCall", "apiFetch", "fetch", "request", "authedFetch"]);
const MUTATING_METHOD = /^(?:POST|PUT|PATCH|DELETE)$/i;

type FnLike =
  | ts.FunctionDeclaration | ts.FunctionExpression | ts.ArrowFunction | ts.MethodDeclaration;

function isFnLike(n: ts.Node): n is FnLike {
  return ts.isFunctionDeclaration(n) || ts.isFunctionExpression(n) ||
    ts.isArrowFunction(n) || ts.isMethodDeclaration(n);
}

function isAsync(fn: FnLike): boolean {
  return (ts.getCombinedModifierFlags(fn) & ts.ModifierFlags.Async) !== 0;
}

/** The function a declaration names: `function f`, `const f = () =>`, and
 *  `const f = useCallback(async () => ..., [])`. */
function declaredFunction(n: ts.Node): { name: string; fn: FnLike } | null {
  if (ts.isFunctionDeclaration(n) && n.name && n.body) return { name: n.name.text, fn: n };
  if (ts.isVariableDeclaration(n) && ts.isIdentifier(n.name) && n.initializer) {
    let init: ts.Expression = n.initializer;
    // useCallback(fn, deps) / useCallback(async () => ..., [])
    if (ts.isCallExpression(init) && ts.isIdentifier(init.expression) &&
        init.expression.text === "useCallback" && init.arguments[0]) {
      init = init.arguments[0];
    }
    if (isFnLike(init)) return { name: n.name.text, fn: init };
  }
  return null;
}

/** The last name in `a.b.c` / `a.b` / `a`. */
function tail(e: ts.Expression): string | null {
  if (ts.isIdentifier(e)) return e.text;
  if (ts.isPropertyAccessExpression(e)) return e.name.text;
  return null;
}

/** `api.accounting.createJournalEntry` -> that text, when the chain is rooted at `api`. */
function apiChain(e: ts.Expression, sf: ts.SourceFile): string | null {
  if (!ts.isPropertyAccessExpression(e)) return null;
  const text = e.getText(sf);
  return /^api\.[A-Za-z]+\.[A-Za-z]+$/.test(text) ? text : null;
}

function stringLiteralArgs(call: ts.CallExpression): string[] {
  const out: string[] = [];
  const scan = (n: ts.Node): void => {
    if (ts.isStringLiteralLike(n)) out.push(n.text);
    ts.forEachChild(n, scan);
  };
  call.arguments.forEach(scan);
  return out;
}

/** Does this CALL itself write? Returns what it is, for the message. */
function directWrite(call: ts.CallExpression, sf: ts.SourceFile): string | null {
  const callee = call.expression;
  // supabase.from(<table>).insert(...): written without a literal table name, which the python guards
  // that scan apps/web would read as a real table.
  if (ts.isPropertyAccessExpression(callee) && SUPABASE_WRITE.has(callee.name.text)) {
    const root = callee.getText(sf);
    // `.update(` / `.delete(` also name methods of plain objects and `api.x.update`;
    // the api chain is classified below, so only a `.from(...)`/`.rpc` chain is a
    // Supabase write here.
    if (callee.name.text === "rpc" || /\.from\(/.test(root) || /^(?:sb|supabase|db|client)\b/.test(root)) {
      return `.${callee.name.text}(`;
    }
  }
  const chain = apiChain(callee, sf);
  if (chain && WRITE_VERB.test(chain.slice(chain.lastIndexOf(".") + 1))) return chain;
  // apiCall(url, "POST", body) / fetch(url, { method: "POST" })
  const name = tail(callee);
  if (name && FETCHERS.has(name)) {
    const method = stringLiteralArgs(call).find((s) => MUTATING_METHOD.test(s));
    if (method) return `${name}(…, "${method}")`;
  }
  return null;
}

type ButtonEl = ts.JsxOpeningElement | ts.JsxSelfClosingElement;

/** Every `<button …>` and `<Button …>` opening tag. */
function buttonElements(sf: ts.SourceFile): ButtonEl[] {
  const out: ButtonEl[] = [];
  const walk = (n: ts.Node): void => {
    if ((ts.isJsxOpeningElement(n) || ts.isJsxSelfClosingElement(n)) &&
        ts.isIdentifier(n.tagName) && (n.tagName.text === "button" || n.tagName.text === "Button")) {
      out.push(n);
    }
    ts.forEachChild(n, walk);
  };
  walk(sf);
  return out;
}

function attribute(el: ButtonEl, name: string): ts.JsxAttribute | null {
  for (const a of el.attributes.properties) {
    if (ts.isJsxAttribute(a) && ts.isIdentifier(a.name) && a.name.text === name) return a;
  }
  return null;
}

/** Is this call's PROMISE handed back to whoever called the function it sits
 *  in — `return save()`, an arrow whose body IS the call, `return save().then(…)`
 *  — rather than dropped (`save();`, `void save();`)? */
function isReturned(call: ts.CallExpression): boolean {
  let node: ts.Node = call;
  for (;;) {
    const p: ts.Node | undefined = node.parent;
    if (!p) return false;
    if (ts.isParenthesizedExpression(p) || ts.isAsExpression(p) || ts.isNonNullExpression(p)) { node = p; continue; }
    // save().then(...) / save().catch(...) / save().finally(...)
    if (ts.isPropertyAccessExpression(p) && p.expression === node && p.parent &&
        ts.isCallExpression(p.parent) && p.parent.expression === p) { node = p.parent; continue; }
    if (ts.isReturnStatement(p)) return true;
    if (ts.isArrowFunction(p) && p.body === node) return true;
    return false;
  }
}

export interface ButtonFacts {
  /** `button` or `Button`. */
  tag: "button" | "Button";
  el: ButtonEl;
  line: number;
  onClick: ts.JsxAttribute | null;
  /** The function the click reaches, as written. */
  handler: string;
  /** What it writes, or null when it reaches no async write. */
  write: string | null;
  /** The click starts an async write and does not hand its promise back. */
  dropsPromise: boolean;
  /** Where the dropped call sits, for a fix. */
  dropSites: ts.CallExpression[];
}

/** Everything the two finders and the conversion tooling need, in one walk. */
export function analyseButtons(fileName: string, source: string): { sf: ts.SourceFile; buttons: ButtonFacts[] } {
  const sf = ts.createSourceFile(fileName, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);

  // name -> declarations (a file often declares the same name in several
  // components, so a name maps to a LIST and a handler is resolved against the
  // declarations visible from where the button sits).
  const decls = new Map<string, Array<{ fn: FnLike; node: ts.Node }>>();
  const collect = (n: ts.Node): void => {
    const d = declaredFunction(n);
    if (d) {
      const list = decls.get(d.name) ?? [];
      list.push({ fn: d.fn, node: n });
      decls.set(d.name, list);
    }
    ts.forEachChild(n, collect);
  };
  collect(sf);

  const within = (inner: ts.Node, outer: ts.Node) =>
    inner.pos >= outer.pos && inner.end <= outer.end;

  /** The declaration of `name` nearest to `from`: the innermost enclosing
   *  function that declares it, falling back to the file's top level. */
  function resolve(name: string, from: ts.Node): FnLike | null {
    const list = decls.get(name);
    if (!list) return null;
    let best: { fn: FnLike; span: number } | null = null;
    for (const d of list) {
      // The declaration's own enclosing function must contain `from` — or it is
      // top level (no enclosing function).
      let owner: ts.Node | undefined = d.node.parent;
      while (owner && !isFnLike(owner) && !ts.isSourceFile(owner)) owner = owner.parent;
      if (!owner) continue;
      if (!ts.isSourceFile(owner) && !within(from, owner)) continue;
      const span = ts.isSourceFile(owner) ? Number.MAX_SAFE_INTEGER : owner.end - owner.pos;
      if (!best || span < best.span) best = { fn: d.fn, span };
    }
    return best ? best.fn : null;
  }

  const writeCache = new Map<FnLike, string | null>();
  /** Does `fn` reach a write — directly or through a same-file function it
   *  calls? `null` is "no", a string is what it writes. */
  function writeOf(fn: FnLike, stack: Set<FnLike> = new Set()): string | null {
    if (writeCache.has(fn)) return writeCache.get(fn)!;
    if (stack.has(fn)) return null;
    stack.add(fn);
    let found: string | null = null;
    const walk = (n: ts.Node): void => {
      if (found) return;
      if (ts.isCallExpression(n)) {
        found = directWrite(n, sf);
        if (!found && ts.isIdentifier(n.expression)) {
          const callee = resolve(n.expression.text, n);
          if (callee && callee !== fn) found = writeOf(callee, stack);
        }
      }
      if (!found) ts.forEachChild(n, walk);
    };
    if (fn.body) walk(fn.body);
    stack.delete(fn);
    writeCache.set(fn, found);
    return found;
  }

  /** The write an ASYNC function reaches. A sync function cannot hand back a
   *  promise of its own, so it never "is" an async write — its CALLS are what
   *  are looked at (`startedWrites`). */
  function asyncWrite(fn: FnLike): string | null {
    return isAsync(fn) ? writeOf(fn) : null;
  }

  /** The calls inside a SYNC function body (not descending into nested
   *  functions) that start an async write, with what they write. */
  function startedWrites(fn: FnLike): Array<{ call: ts.CallExpression; write: string; name: string }> {
    const out: Array<{ call: ts.CallExpression; write: string; name: string }> = [];
    const walk = (n: ts.Node): void => {
      if (n !== fn && isFnLike(n)) return;
      if (ts.isCallExpression(n) && ts.isIdentifier(n.expression)) {
        const callee = resolve(n.expression.text, n);
        const w = callee ? asyncWrite(callee) : null;
        if (w) out.push({ call: n, write: w, name: n.expression.text });
      }
      ts.forEachChild(n, walk);
    };
    if (fn.body) walk(fn.body);
    return out;
  }

  const buttons: ButtonFacts[] = [];
  for (const el of buttonElements(sf)) {
    const tag = (el.tagName as ts.Identifier).text as "button" | "Button";
    const onClick = attribute(el, "onClick");
    const line = sf.getLineAndCharacterOfPosition(el.getStart(sf)).line + 1;
    const facts: ButtonFacts = {
      tag, el, line, onClick, handler: "", write: null, dropsPromise: false, dropSites: [],
    };
    buttons.push(facts);
    if (!onClick || !onClick.initializer || !ts.isJsxExpression(onClick.initializer) ||
        !onClick.initializer.expression) continue;
    const expr = onClick.initializer.expression;

    if (ts.isIdentifier(expr)) {
      const fn = resolve(expr.text, el);
      if (!fn) continue;
      facts.handler = expr.text;
      const direct = asyncWrite(fn);
      if (direct) { facts.write = direct; continue; }
      // A SYNC wrapper that starts an async write: it reaches one, and it hands
      // the promise back only if it returns it.
      const started = startedWrites(fn);
      if (started.length) {
        facts.write = started[0].write;
        facts.dropSites = started.filter((s) => !isReturned(s.call)).map((s) => s.call);
        facts.dropsPromise = facts.dropSites.length > 0;
      }
    } else if (isFnLike(expr)) {
      if (isAsync(expr)) {
        facts.write = writeOf(expr);
        facts.handler = "(inline async)";
      } else {
        // `() => save("draft")`, `() => { void save(); }` — a non-async arrow
        // that CALLS an async writer.
        const started = startedWrites(expr);
        if (started.length) {
          facts.handler = started[0].name;
          facts.write = started[0].write;
          facts.dropSites = started.filter((s) => !isReturned(s.call)).map((s) => s.call);
          facts.dropsPromise = facts.dropSites.length > 0;
        }
      }
    }
  }
  return { sf, buttons };
}

/** Every raw `<button>` in `source` whose click starts an async write. */
export function findRawAsyncButtons(fileName: string, source: string): RawAsyncButton[] {
  return analyseButtons(fileName, source).buttons
    .filter((b) => b.tag === "button" && b.write)
    .map((b) => ({ file: fileName, line: b.line, handler: b.handler, write: b.write as string }));
}

/** Every `<Button>` whose handler starts an async write and DISCARDS the promise,
 *  so the primitive's guard is released on the same tick. */
export function findDroppedPromises(fileName: string, source: string): RawAsyncButton[] {
  return analyseButtons(fileName, source).buttons
    .filter((b) => b.tag === "Button" && b.write && b.dropsPromise)
    .map((b) => ({ file: fileName, line: b.line, handler: b.handler, write: b.write as string }));
}
