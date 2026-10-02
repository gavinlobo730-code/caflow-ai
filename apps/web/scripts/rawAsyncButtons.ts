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
 *   2. `findDroppedPromises` — a `<Button>` (or any other tag in `GUARDED_PRIMITIVES`,
 *      which render the Button primitive) whose handler STARTS an async write
 *      and does not hand the promise back. The primitive can only hold what it
 *      is given: `onClick={() => { save(); }}` and `onClick={() => void save()}`
 *      discard the promise, the guard is released on the same tick, and the
 *      screen has moved to the new component without gaining the protection it
 *      thinks it has. This is the half that makes a conversion REAL.
 *
 * WHAT COUNTS AS "ASYNC-WRITING"
 *     A click handler that runs — directly, through an inline arrow, or through a
 *     same-file function it calls — an `async` function whose body reaches a
 *     WRITE: a Supabase `.insert/.update/.upsert/.delete/.rpc`, a call on one of
 *     the product's API clients (`api.<namespace>.<verb>(`, `yearEndApi.…`,
 *     `partyCreditsApi.…`) that WRITES, or an `apiCall`/`apiFetch`/`fetch`/
 *     `request` carrying a non-GET method. Reads are left out on purpose: a
 *     second click on Retry costs a wasted request, a second click on Post costs
 *     a duplicate voucher, and a ratchet that counts both is a number nobody acts
 *     on.
 *
 *     WHICH CLIENT METHOD WRITES IS READ OFF THE CLIENT, NOT OFF ITS SPELLING.
 *     The first version asked whether the method's NAME began with a mutating verb
 *     (`WRITE_VERB`) and only on a chain of exactly `api.<ns>.<verb>`. Both were
 *     blind in ways that mattered: 71 of the 338 methods in lib/api/index.ts that
 *     send a POST, PUT, PATCH or DELETE begin with no listed verb —
 *     `invoices.fromEngagement` (the Raise Invoice button), `clients.permanentDelete`,
 *     `banking.categorize`, `reconciliations.complete`, `billing.run`,
 *     `identity.forceLogout` — a chain one level deeper (`api.accounting.fxRevaluation
 *     .run`) was never looked at, and `yearEndApi.notes.generateAll` is rooted at a
 *     second client the pattern did not name, so the year-end notes screen read as
 *     having no write at all. `writingClientMethods` therefore parses the three
 *     client files and takes every method whose own body sends a mutating HTTP
 *     method; `WRITE_VERB` stays as the fallback for a chain the clients do not
 *     define (a method added since, or a fixture). A POST that only COMPUTES — a
 *     preview, a parse, a question put to the assistant — is a read, and is named in
 *     `READS_BY_POST` with its reason rather than guessed at by a prefix.
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
import { readFileSync } from "node:fs";
import { join } from "node:path";
import ts from "typescript";

/** The JSX tags that hand their click to `components/ui/button.tsx` and so hold a repeat click
 *  exactly as `<Button>` does — which also means each one can only hold a promise it is GIVEN.
 *
 *  `EmptyStateAction` is the second: the next step on an empty list, where a screen's "Raise
 *  Invoice" or "Generate All Notes" is often the first thing a new practice presses. It used to be
 *  a raw `<button onClick={props.onClick}>` typed `() => void`, so a write behind it was invisible
 *  to both finders, and four screens wrote `onClick={() => void handleX()}` on it — the promise
 *  dropped, the guard the commit message promised released on the same tick.
 *
 *  A tag belongs here only while its source really renders `<Button>`; the ratchet test reads
 *  each one's file and fails if that stops being true. A tag that is a raw `<button>` underneath
 *  must NOT be listed, or every table below would read it as guarded. */
export const GUARDED_PRIMITIVES = ["Button", "EmptyStateAction"] as const;
const GUARDED_TAGS: ReadonlySet<string> = new Set(GUARDED_PRIMITIVES);

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
 *  word at the start of the name (`payrollClientStates` is not `pay`).
 *
 *  THE FALLBACK, NOT THE RULE. Which method of a client writes is read off the client
 *  (`writingClientMethods`); this applies only to a chain the client files do not define — a
 *  method added since, or a fixture — and it can only ADD a write, never remove one the client
 *  derives. It is an allowlist for that reason: an unknown verb on an unknown chain is not counted,
 *  so the ratchet understates rather than flagging a report download as a posting. */
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

const WEB = join(import.meta.dirname, "..");

/** The product's API clients: the identifier a screen calls them by, and the file that
 *  defines them. A client added without a line here is a client the analysis cannot see,
 *  and `a-button-that-writes-…` asserts every `export const <x>Api` / `api` object under
 *  lib/api is named. */
export const API_CLIENTS: Readonly<Record<string, string>> = {
  api: "lib/api/index.ts",
  yearEndApi: "lib/api/yearEnd.ts",
  partyCreditsApi: "lib/api/partyCredits.ts",
};

/** Client methods that send a POST and WRITE NOTHING — each with why. Keyed `<client>.<path>`.
 *
 *  A POST is the right verb for a read whose input is too big or too private for a query
 *  string, so the HTTP method alone over-counts; and a prefix such as `preview…` is the same
 *  spelling-matching the derivation replaced. So the exceptions are named, each is asserted
 *  to be a real method that still sends a POST (a stale entry fails), and any POST method
 *  the client gains is counted as a write until somebody says otherwise: the direction that
 *  gets a repeat click held, not the one that lets a duplicate through. */
export const READS_BY_POST: Readonly<Record<string, string>> = {
  "api.documents.parse": "reads an uploaded document and returns what it found; the bill is created by a later call",
  "api.assistant.ask": "puts a question to the model and returns the answer",
  "api.copilotV2.quickChat": "one stateless question to the model, nothing stored",
  "api.accounting.fxRevaluation.preview": "the dry run of the revaluation; `run` is the posting",
  "api.banking.postingPreview": "what posting this bank line would book; `post` books it",
  "api.banking.reconciliations.preview": "the tie-out as if more lines were reconciled; documented read-only",
  "api.billing.previewRun": "which schedules a run would bill; `run` bills them",
  "api.payroll.previewSettlement": "what a leaver is owed; documented read-only, recording is a separate call",
  "api.payroll.valuePerquisites": "Rule 3 valuation; computes only, recording is a separate call",
  "api.payroll.arrearsRelief": "s.89(1) relief worked out; computes only",
  "api.payroll.esicMappedIpCheck": "compares a pasted list of numbers with the run; documented as storing nothing",
  "api.gstReturns.gstr1WithAmendments": "builds the GSTR-1 and the amendments it owes for the period; files and stores nothing",
};

let clientWritesCache: ReadonlySet<string> | null = null;

/** Every method of the API clients whose own body sends a POST, PUT, PATCH or DELETE, as
 *  `<client>.<namespace>[.<namespace>…].<method>` — read off the client files, so a method
 *  is a write because of what it sends and not because of what it is called. */
export function writingClientMethods(): ReadonlySet<string> {
  if (clientWritesCache) return clientWritesCache;
  const found = new Set<string>();
  for (const [root, rel] of Object.entries(API_CLIENTS)) {
    const text = readFileSync(join(WEB, rel), "utf8");
    const sf = ts.createSourceFile(rel, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
    const sendsMutating = (body: ts.Node): boolean => {
      let hit = false;
      const walk = (n: ts.Node): void => {
        if (hit) return;
        if (ts.isStringLiteralLike(n) && MUTATING_METHOD.test(n.text) && n.parent) {
          const p = n.parent;
          // `{ method: "POST" }`, or `apiCall(url, "POST", body)` / `fetch(url, "POST")`
          if (ts.isPropertyAssignment(p) && ts.isIdentifier(p.name) && p.name.text === "method") hit = true;
          else if (ts.isCallExpression(p)) {
            const callee = tail(p.expression);
            if (callee !== null && (FETCHERS.has(callee) || callee === "downloadFile")) hit = true;
          }
        }
        ts.forEachChild(n, walk);
      };
      walk(body);
      return hit;
    };
    const visit = (path: string[], obj: ts.ObjectLiteralExpression): void => {
      for (const prop of obj.properties) {
        if (!(ts.isPropertyAssignment(prop) || ts.isMethodDeclaration(prop)) || !prop.name) continue;
        const name = ts.isIdentifier(prop.name) || ts.isStringLiteralLike(prop.name) ? prop.name.text : null;
        if (name === null) continue;
        let init: ts.Node = ts.isPropertyAssignment(prop) ? prop.initializer : prop;
        while (ts.isParenthesizedExpression(init) || ts.isAsExpression(init)) init = init.expression;
        if (ts.isObjectLiteralExpression(init)) { visit([...path, name], init); continue; }
        if (sendsMutating(init)) found.add([root, ...path, name].join("."));
      }
    };
    const declared = (n: ts.Node): void => {
      if (ts.isVariableDeclaration(n) && ts.isIdentifier(n.name) && n.name.text === root && n.initializer) {
        let init: ts.Expression = n.initializer;
        while (ts.isAsExpression(init) || ts.isSatisfiesExpression(init) || ts.isParenthesizedExpression(init)) init = init.expression;
        if (ts.isObjectLiteralExpression(init)) visit([], init);
      }
      ts.forEachChild(n, declared);
    };
    declared(sf);
  }
  clientWritesCache = found;
  return found;
}

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

/** `api.accounting.createJournalEntry` -> that text, when the chain is rooted at one of the
 *  product's API clients (`api`, `yearEndApi`, `partyCreditsApi`) and may run any number of
 *  namespaces deep (`api.accounting.fxRevaluation.run`). */
function apiChain(e: ts.Expression, sf: ts.SourceFile): string | null {
  if (!ts.isPropertyAccessExpression(e)) return null;
  const text = e.getText(sf);
  const root = text.split(".")[0];
  if (!Object.prototype.hasOwnProperty.call(API_CLIENTS, root)) return null;
  return /^[A-Za-z]+(?:\.[A-Za-z0-9]+)+$/.test(text) ? text : null;
}

/** Does a call on an API client write? Derived from the client first (what the method
 *  sends), and from its name only for a chain the client files do not define. */
function clientCallWrites(chain: string): boolean {
  if (chain in READS_BY_POST) return false;
  if (writingClientMethods().has(chain)) return true;
  return WRITE_VERB.test(chain.slice(chain.lastIndexOf(".") + 1));
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
  // supabase.from("customers").insert(...) — a REAL table name even in a comment or a fixture:
  // tests/test_frontend_tables_exist.py and test_direct_write_tables_are_role_guarded.py scan every
  // file under apps/web for `.from("<name>")`, and a made-up name reads as a write to a table that
  // does not exist and is covered by no policy.
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
  if (chain && clientCallWrites(chain)) return chain;
  // apiCall(url, "POST", body) / fetch(url, { method: "POST" })
  const name = tail(callee);
  if (name && FETCHERS.has(name)) {
    const method = stringLiteralArgs(call).find((s) => MUTATING_METHOD.test(s));
    if (method) return `${name}(…, "${method}")`;
  }
  return null;
}

type ButtonEl = ts.JsxOpeningElement | ts.JsxSelfClosingElement;

/** Every `<button …>` opening tag and every guarded primitive's (`<Button …>`, `<EmptyStateAction …>`). */
function buttonElements(sf: ts.SourceFile): ButtonEl[] {
  const out: ButtonEl[] = [];
  const walk = (n: ts.Node): void => {
    if ((ts.isJsxOpeningElement(n) || ts.isJsxSelfClosingElement(n)) &&
        ts.isIdentifier(n.tagName) && (n.tagName.text === "button" || GUARDED_TAGS.has(n.tagName.text))) {
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
    // `id && save(id)`, `id ? save(id) : undefined`: the promise is the VALUE of the expression
    // when the call runs, so it is handed back wherever the expression is. Only the RIGHT side of
    // a short-circuit counts — the left one is the condition, not what comes back.
    if (ts.isBinaryExpression(p) && p.right === node &&
        (p.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken ||
         p.operatorToken.kind === ts.SyntaxKind.BarBarToken ||
         p.operatorToken.kind === ts.SyntaxKind.QuestionQuestionToken)) { node = p; continue; }
    if (ts.isConditionalExpression(p) && (p.whenTrue === node || p.whenFalse === node)) { node = p; continue; }
    // save().then(...) / save().catch(...) / save().finally(...)
    if (ts.isPropertyAccessExpression(p) && p.expression === node && p.parent &&
        ts.isCallExpression(p.parent) && p.parent.expression === p) { node = p.parent; continue; }
    if (ts.isReturnStatement(p)) return true;
    if (ts.isArrowFunction(p) && p.body === node) return true;
    return false;
  }
}

export interface ButtonFacts {
  /** `button`, or a guarded primitive (`Button`, `EmptyStateAction`). */
  tag: "button" | (typeof GUARDED_PRIMITIVES)[number];
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
    const tag = (el.tagName as ts.Identifier).text as ButtonFacts["tag"];
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

/** Every `<Button>` (or other guarded primitive) whose handler starts an async write and
 *  DISCARDS the promise, so the primitive's guard is released on the same tick. */
export function findDroppedPromises(fileName: string, source: string): RawAsyncButton[] {
  return analyseButtons(fileName, source).buttons
    .filter((b) => b.tag !== "button" && b.write && b.dropsPromise)
    .map((b) => ({ file: fileName, line: b.line, handler: b.handler, write: b.write as string }));
}
