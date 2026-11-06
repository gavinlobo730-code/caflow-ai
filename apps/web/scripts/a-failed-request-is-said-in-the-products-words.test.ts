// A request that fails outright is said in the product's words, never in the browser's (POST-A-406, POST-A-382, POST-A-405). Run with:
//   node --experimental-strip-types --test scripts/a-failed-request-is-said-in-the-products-words.test.ts
//
// WHY THIS EXISTS
//     A save, a compute or a list that fails BEFORE the server's own answer has no sentence of the product's: the browser throws, and the screen printed the browser's text,
//     "Failed to fetch" for a dropped connection and `Unexpected token '<', "<html>…" is not valid JSON` for a proxy's page. Fourteen functions of `lib/data/income-tax.ts` also
//     read a refusal as `json.error ?? "Failed to …: <status text>"`, so a 422 showed "Unprocessable Entity" over the sentence the server wrote, and the GSTR-3B tab's row
//     actions held their row in a `finally` and said nothing when the request threw.
//
//     The rules, held over the tree (AST rules, not lists of spellings):
//       * `lib/api/failureSentence.ts` is the one place that says it, and imports nothing;
//       * the readers the findings name (`lib/data/income-tax.ts`, `lib/data/tds.ts`, `lib/data/gst.ts`) and the four client compliance pages call no `fetch` and read no
//         `Response.json()` of their own (the one exception is `res.clone().json()`, which reads a failed status from a copy), and read no status line;
//       * the four compliance pages show no thrown request's message themselves: no `instanceof Error` test and no `.message` read of a caught value, so what they print comes
//         through `failureSentence`;
//       * every `try` on those pages that makes a request has a `catch`, and the GSTR-3B row actions say what they caught through `failureSentence`;
//       * a file that calls `fetch` itself is either one of four that must, or on a list that only shrinks (it is empty now), and the list names the shape that keeps each there;
//       * the browser's Supabase client is made once, with the fetch that answers a dropped connection in the product's words (POST-A-413), and a change is never sent a second time by
//         `request()` (POST-A-412).
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const WEB = path.join(import.meta.dirname, "..");
const HELPER = "lib/api/failureSentence.ts";
const READERS = ["lib/data/income-tax.ts", "lib/data/tds.ts", "lib/data/gst.ts"];
const PAGES = [
  "app/clients/[id]/compliance/page.tsx",
  "app/clients/[id]/compliance/mca/page.tsx",
  "app/clients/[id]/compliance/tds/page.tsx",
  "app/clients/[id]/compliance/gst/page.tsx",
];
/** Other files whose every caught request is said through the helper too: the public page a CLIENT opens to sign an engagement letter, and the vendor statement tab. */
const ALSO_NO_RAW_MESSAGE = ["app/sign/page.tsx", "components/purchases/VendorStatementsTab.tsx"];
const PAYROLL = "app/clients/[id]/payroll/page.tsx";
const GST_PAGE = "app/clients/[id]/compliance/gst/page.tsx";
const TDS_PAGE = "app/clients/[id]/compliance/tds/page.tsx";

/** The four files that must call `fetch` themselves, and why. */
const MUST_CALL_FETCH: Record<string, string> = {
  [HELPER]: "the wrapper: it is the one `fetch` the others go through",
  "lib/supabase/plainRestFetch.ts": "the `fetch` the browser's Supabase client is made with: it passes a request on, and answers in the server's place for one that got no answer (POST-A-413)",
  "lib/api/index.ts": "`request()`'s own bounded fetch, which has its own timeout, retry and plain sentences, and says them itself",
  "lib/api/keepAwake.ts": "the keep-awake ping, which swallows its failures by design and shows nothing",
};

/**
 * Files that still read their own answer. A list that only SHRINKS: converting one leaves its entry stale and fails the test until the entry is deleted. IT IS EMPTY, which is the goal state
 * (POST-A-410 converted the last six: the purchases page's closures went to `lib/invoices/shared`, which reads through the helper, and the drawer's PDF and the three editors' uploads do too);
 * a file that needs to call `fetch` itself is one of the three above, or says here, in a sentence, what shape keeps it there.
 */
const STILL_READ_BY_THEMSELVES: Record<string, string> = {};

/** The files POST-A-410 converted: none of them calls `fetch` or reads `Response.json()` itself any more, and none of them keeps a copy of the invoice screens' request helpers. */
const CONVERTED_IN_410 = [
  "app/clients/[id]/purchases/page.tsx",
  "lib/invoices/shared.ts",
  "components/invoices/InvoiceViewDrawer.tsx",
  "components/purchases/DebitNoteEditor.tsx",
  "components/purchases/PurchaseBillEditor.tsx",
  "components/purchases/PurchaseCreditNoteEditor.tsx",
];

function read(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8");
}

function parse(rel: string, src: string): ts.SourceFile {
  const kind = rel.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  return ts.createSourceFile(rel, src, ts.ScriptTarget.Latest, true, kind);
}

function walk(node: ts.Node, visit: (n: ts.Node) => void): void {
  visit(node);
  ts.forEachChild(node, (c) => walk(c, visit));
}

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

// ── the rules, as functions of a source text, so the self-test can run them on a spoiled copy ──────────────────────

/** How many calls to the global `fetch` the file makes. */
function directFetches(rel: string, src: string): number {
  let n = 0;
  walk(parse(rel, src), (node) => {
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === "fetch") n++;
  });
  return n;
}

/** Every `x.json()` that is not read from a copy (`res.clone().json()`). */
function bareJsonReads(rel: string, src: string): string[] {
  const found: string[] = [];
  const sf = parse(rel, src);
  walk(sf, (node) => {
    if (!ts.isCallExpression(node) || node.arguments.length !== 0) return;
    const callee = node.expression;
    if (!ts.isPropertyAccessExpression(callee) || callee.name.text !== "json") return;
    const receiver = callee.expression;
    const fromACopy = ts.isCallExpression(receiver) && ts.isPropertyAccessExpression(receiver.expression) && receiver.expression.name.text === "clone";
    if (!fromACopy) found.push(`line ${sf.getLineAndCharacterOfPosition(node.getStart()).line + 1}`);
  });
  return found;
}

/** Every read of a status line. */
function statusTextReads(rel: string, src: string): string[] {
  const found: string[] = [];
  const sf = parse(rel, src);
  walk(sf, (node) => {
    if (ts.isPropertyAccessExpression(node) && node.name.text === "statusText") {
      found.push(`line ${sf.getLineAndCharacterOfPosition(node.getStart()).line + 1}`);
    }
  });
  return found;
}

/** A thrown request's message shown by the page itself: an `instanceof Error` test, or a `.message` read of a value a `catch` clause or a `.catch` callback holds. */
function rawMessageDisplays(rel: string, src: string): string[] {
  const found: string[] = [];
  const sf = parse(rel, src);
  const where = (n: ts.Node) => `line ${sf.getLineAndCharacterOfPosition(n.getStart()).line + 1}`;
  const caught = new Set<string>();
  walk(sf, (node) => {
    if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.InstanceOfKeyword
        && ts.isIdentifier(node.right) && node.right.text === "Error") {
      found.push(`${where(node)}: instanceof Error`);
    }
    if (ts.isCatchClause(node) && node.variableDeclaration && ts.isIdentifier(node.variableDeclaration.name)) {
      caught.add(node.variableDeclaration.name.text);
    }
    // `.catch((e) => …)`
    if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression) && node.expression.name.text === "catch") {
      const cb = node.arguments[0];
      if (cb && (ts.isArrowFunction(cb) || ts.isFunctionExpression(cb)) && cb.parameters[0] && ts.isIdentifier(cb.parameters[0].name)) {
        caught.add(cb.parameters[0].name.text);
      }
    }
  });
  walk(sf, (node) => {
    if (ts.isPropertyAccessExpression(node) && node.name.text === "message"
        && ts.isIdentifier(node.expression) && caught.has(node.expression.text)) {
      found.push(`${where(node)}: ${node.expression.text}.message`);
    }
  });
  return found;
}

/** The `try` statements that make a request through `apiFetch` and have no `catch` at all (a `finally` alone releases a hold and lets the failure go to nobody). */
function uncaughtTries(rel: string, src: string): string[] {
  const found: string[] = [];
  const sf = parse(rel, src);
  walk(sf, (node) => {
    if (!ts.isTryStatement(node)) return;
    let requests = false;
    walk(node.tryBlock, (n) => {
      if (ts.isCallExpression(n) && ts.isIdentifier(n.expression) && n.expression.text === "apiFetch") requests = true;
    });
    if (requests && !node.catchClause) found.push(`line ${sf.getLineAndCharacterOfPosition(node.getStart()).line + 1}`);
  });
  return found;
}

/** The functions of a module that make a request (call `fetchPlain`) and do not hand the response to the module's reader, so what they read of it is their own. */
function functionsReadingTheirOwnAnswer(rel: string, src: string, readers: string[]): string[] {
  const found: string[] = [];
  const sf = parse(rel, src);
  walk(sf, (node) => {
    if (!ts.isFunctionDeclaration(node) || !node.name || !node.body) return;
    // functions nested in another are read with their parent: only the outermost declarations are asked
    let makes = false;
    let reads = false;
    walk(node.body, (n) => {
      if (ts.isCallExpression(n) && ts.isIdentifier(n.expression)) {
        if (n.expression.text === "fetchPlain") makes = true;
        if (readers.includes(n.expression.text)) reads = true;
      }
    });
    if (makes && !reads) found.push(node.name.text);
  });
  return found;
}

/** Whether a function of that name uses `name` anywhere in its body: calls it, or hands it on (`.map(modelSentence)`). */
function functionCalls(rel: string, src: string, fn: string, name: string): boolean {
  let yes = false;
  walk(parse(rel, src), (node) => {
    if (ts.isFunctionDeclaration(node) && node.name?.text === fn && node.body) {
      walk(node.body, (n) => { if (ts.isIdentifier(n) && n.text === name) yes = true; });
    }
  });
  return yes;
}

/** Calls of `callee` whose third argument is the word "read", with the text of the path they send and the function they sit in. */
function readCallsOf(rel: string, src: string, callee: string): Array<{ path: string; fn: string }> {
  const found: Array<{ path: string; fn: string }> = [];
  walk(parse(rel, src), (node) => {
    if (!(ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === callee)) return;
    const asked = node.arguments[2];
    if (asked && ts.isStringLiteral(asked) && asked.text === "read") found.push({ path: node.arguments[0]?.getText() ?? "", fn: enclosingFunction(node) });
  });
  return found;
}

/** A path that only asks: a computation from the books, a preview, a check that never writes, an inspection of a file. The function that sends one by a path it chose is named as well. */
const ASKS_ONLY = /from-books|gstr2b\/inspect|dry_run=true|compute-amount|deductions\/preview/;
/** A request the caller calls a read (the word "read" as its own third argument) that is not one of those. */
function readCallsToAChange(rel: string, src: string, callee: string): string[] {
  return readCallsOf(rel, src, callee)
    .filter((c) => !(ASKS_ONLY.test(c.path) || c.fn === "computeFromBooks" || c.fn === "computeReturnFromBooks"))
    .map((c) => `${rel}: ${c.fn || "(top level)"} sends ${c.path.slice(0, 70)} and calls it a read`);
}

/** The `try` statements that read a paste (`JSON.parse`) and make a request in the same block: one catch then serves both, and a request that failed is told to the person as a bad paste. */
function triesThatParseAndRequest(rel: string, src: string): string[] {
  const found: string[] = [];
  const sf = parse(rel, src);
  walk(sf, (node) => {
    if (!ts.isTryStatement(node)) return;
    let parses = false;
    let requests = false;
    walk(node.tryBlock, (n) => {
      if (!ts.isCallExpression(n)) return;
      const c = n.expression;
      if (ts.isPropertyAccessExpression(c) && ts.isIdentifier(c.expression) && c.expression.text === "JSON" && c.name.text === "parse") parses = true;
      if (ts.isIdentifier(c) && c.text === "apiFetch") requests = true;
    });
    if (parses && requests) found.push(`line ${sf.getLineAndCharacterOfPosition(node.getStart()).line + 1}`);
  });
  return found;
}

/** A bare `catch { … }` (it binds nothing, so it cannot say what happened) that says a fixed sentence through `setter`: over a change, that is a claim that it did not happen. */
function bareCatchesSaying(rel: string, src: string, setter: string): string[] {
  const found: string[] = [];
  const sf = parse(rel, src);
  walk(sf, (node) => {
    if (!ts.isCatchClause(node) || node.variableDeclaration) return;
    walk(node.block, (n) => {
      if (ts.isCallExpression(n) && ts.isIdentifier(n.expression) && n.expression.text === setter && n.arguments[0] && ts.isStringLiteralLike(n.arguments[0])) {
        found.push(`line ${sf.getLineAndCharacterOfPosition(n.getStart()).line + 1}`);
      }
    });
  });
  return found;
}

/** The calls on the browser's Supabase client that change something. A `.rpc()` is a POST too, and nothing in the browser calls one. */
const TABLE_WRITES = new Set(["insert", "update", "upsert", "delete"]);

/**
 * What a block asks and what it changes, counted from its requests: `apiFetch(…)` calls (a change unless there is no method, or GET or HEAD, or the word "read" as the call's own third
 * argument) and calls on a table of the browser's Supabase client (`….from(…).insert|update|upsert|delete(…)` is a change; a `.select(…)` on a chain that writes nothing asks). The table
 * half was added after an independent read found that the rule below understood `apiFetch` only: `failureSentence` words a Supabase error by the screen's label (POST-A-413), so a table
 * write caught under "read" would have been worded as a read.
 */
function requestsMadeIn(block: ts.Node): { asks: number; changes: number } {
  let asks = 0;
  let changes = 0;
  walk(block, (n) => {
    if (!ts.isCallExpression(n)) return;
    if (ts.isIdentifier(n.expression) && n.expression.text === "apiFetch") {
      const word = n.arguments[2];
      if (word && ts.isStringLiteral(word) && word.text === "read") { asks++; return; }
      let method = "GET";
      const init = n.arguments[1];
      if (init && ts.isObjectLiteralExpression(init)) {
        for (const p of init.properties) {
          if (ts.isPropertyAssignment(p) && ts.isIdentifier(p.name) && p.name.text === "method" && ts.isStringLiteral(p.initializer)) method = p.initializer.text.toUpperCase();
        }
      }
      if (method === "GET" || method === "HEAD") asks++; else changes++;
      return;
    }
    if (!ts.isPropertyAccessExpression(n.expression)) return;
    const chain = n.expression.getText();
    if (!/\.from\(/.test(chain)) return;
    const name = n.expression.name.text;
    if (TABLE_WRITES.has(name)) changes++;
    else if (name === "select" && !/\.(insert|update|upsert|delete)\(/.test(chain)) asks++;
  });
  return { asks, changes };
}

/**
 * A catch that says a failed request through `failureSentence(e, fallback, label)` must label it as the try's requests are: "write" when any of them may change something, "read" when every
 * one only asks (no method or GET, or the word "read" as the call's own third argument; a table `.select()`). The source already throws the finished sentence by the request's own method, so the label only
 * decides what a failure that reached the screen UNCONVERTED says (the auth client's token fetch) or what the Supabase client handed back as an error object, and a label that disagrees with the request is a sentence that is wrong when that happens.
 */
function labelsThatDisagreeWithTheRequest(rel: string, src: string): string[] {
  const found: string[] = [];
  const sf = parse(rel, src);
  walk(sf, (node) => {
    if (!ts.isTryStatement(node) || !node.catchClause) return;
    const { asks, changes } = requestsMadeIn(node.tryBlock);
    if (asks + changes === 0) return;
    const wanted = changes > 0 ? "write" : "read";
    walk(node.catchClause.block, (n) => {
      if (!(ts.isCallExpression(n) && ts.isIdentifier(n.expression) && n.expression.text === "failureSentence")) return;
      const label = n.arguments[2];
      const said = label && ts.isStringLiteral(label) ? label.text : "write";
      if (said !== wanted) found.push(`line ${sf.getLineAndCharacterOfPosition(n.getStart()).line + 1}: says ${said} over a try that makes ${changes} change(s) and ${asks} read(s)`);
    });
  });
  return found;
}

/** How many `try` statements make a request (through `apiFetch` or on a table) and have a catch that says it through `failureSentence`: the population `labelsThatDisagreeWithTheRequest` reads. */
function triesThatSayWhatTheyCaught(rel: string, src: string): number {
  let n = 0;
  walk(parse(rel, src), (node) => {
    if (!ts.isTryStatement(node) || !node.catchClause) return;
    const { asks, changes } = requestsMadeIn(node.tryBlock);
    let says = false;
    walk(node.catchClause.block, (c) => { if (ts.isCallExpression(c) && ts.isIdentifier(c.expression) && c.expression.text === "failureSentence") says = true; });
    if (asks + changes > 0 && says) n++;
  });
  return n;
}

/** Every `callee(…).catch(handler)` in a file: the line, the request's method, and whether the handler takes what was thrown. */
function catchesOnRequests(rel: string, src: string, callee: string): Array<{ line: number; method: string; takesWhatWasThrown: boolean }> {
  const found: Array<{ line: number; method: string; takesWhatWasThrown: boolean }> = [];
  const sf = parse(rel, src);
  walk(sf, (node) => {
    if (!(ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression) && node.expression.name.text === "catch")) return;
    const request = node.expression.expression;
    if (!(ts.isCallExpression(request) && ts.isIdentifier(request.expression) && request.expression.text === callee)) return;
    const method = (/method:\s*["'](\w+)["']/.exec(request.getText())?.[1] ?? "GET").toUpperCase();
    const handler = node.arguments[0];
    const takesWhatWasThrown = handler !== undefined && (ts.isArrowFunction(handler) || ts.isFunctionExpression(handler)) && handler.parameters.length > 0;
    found.push({ line: sf.getLineAndCharacterOfPosition(node.getStart()).line + 1, method, takesWhatWasThrown });
  });
  return found;
}

/** A request that changes something whose failure is swallowed into `null`: `callee(…, { method: "POST" … }).catch(() => null)`, a handler that does not even take what was thrown. A change that got no answer may have gone through, and a caller that sees null says its own fixed "could not" over it. */
function writesThatSwallowTheirFailure(rel: string, src: string, callee: string): string[] {
  return catchesOnRequests(rel, src, callee)
    .filter((c) => c.method !== "GET" && c.method !== "HEAD" && !c.takesWhatWasThrown)
    .map((c) => `line ${c.line}: ${callee} ${c.method} … .catch(() => …) says nothing of what was thrown`);
}

/**
 * `await <receiver>.<method>(…)` calls in a file, split by whether each sits in a `try` block itself (not its catch or finally, and not in a function nested in it, which runs later).
 * The Supabase fetch wrapper reads the body of an answer inside its try so that a connection that dies after the headers is the drop it is (POST-A-413); a read moved out of the try
 * would pass every other rule and be worded by the client as "TypeError: network error".
 */
function awaitsInsideATry(rel: string, src: string, receiver: string, method: string): { inside: number; outside: number } {
  let inside = 0;
  let outside = 0;
  walk(parse(rel, src), (node) => {
    if (!(ts.isAwaitExpression(node) && ts.isCallExpression(node.expression))) return;
    const callee = node.expression.expression;
    if (!(ts.isPropertyAccessExpression(callee) && ts.isIdentifier(callee.expression) && callee.expression.text === receiver && callee.name.text === method)) return;
    let inTry = false;
    for (let p: ts.Node | undefined = node.parent; p; p = p.parent) {
      if (ts.isFunctionLike(p)) break;
      if (ts.isBlock(p) && p.parent && ts.isTryStatement(p.parent) && p.parent.tryBlock === p) { inTry = true; break; }
    }
    if (inTry) inside++; else outside++;
  });
  return { inside, outside };
}

/**
 * The files that build a Supabase client, however the package is brought in: a value import of `createClient` (renamed or not), `import * as ns` with `ns.createClient(…)` or
 * `new ns.SupabaseClient(…)`, `new SupabaseClient(…)`, and a dynamic `import("@supabase/supabase-js")` or `require("@supabase/supabase-js")`. A type import (`import type`, `import { type X }`)
 * builds nothing. (An independent read found the first version saw only `import { createClient }`.)
 */
function buildsASupabaseClient(rel: string, src: string): boolean {
  const PACKAGE = "@supabase/supabase-js";
  let found = false;
  const namespaces = new Set<string>();
  const sf = parse(rel, src);
  walk(sf, (node) => {
    if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier) && node.moduleSpecifier.text === PACKAGE && !node.importClause?.isTypeOnly) {
      const bindings = node.importClause?.namedBindings;
      if (bindings && ts.isNamedImports(bindings) && bindings.elements.some((el) => !el.isTypeOnly && (el.propertyName ?? el.name).text === "createClient")) found = true;
      if (bindings && ts.isNamespaceImport(bindings)) namespaces.add(bindings.name.text);
    }
    if (ts.isCallExpression(node) && node.arguments[0] && ts.isStringLiteralLike(node.arguments[0]) && node.arguments[0].text === PACKAGE
      && (node.expression.kind === ts.SyntaxKind.ImportKeyword || (ts.isIdentifier(node.expression) && node.expression.text === "require"))) found = true;
    if (ts.isNewExpression(node)) {
      const callee = node.expression;
      const name = ts.isIdentifier(callee) ? callee.text : ts.isPropertyAccessExpression(callee) ? callee.name.text : "";
      if (name === "SupabaseClient") found = true;
    }
  });
  if (!found && namespaces.size > 0) {
    walk(sf, (node) => {
      if (ts.isPropertyAccessExpression(node) && ts.isIdentifier(node.expression) && namespaces.has(node.expression.text) && node.name.text === "createClient") found = true;
    });
  }
  return found;
}

/** The name of the function declaration a node sits in, or "" at the top of the file. */
function enclosingFunction(node: ts.Node): string {
  for (let p: ts.Node | undefined = node.parent; p; p = p.parent) {
    if (ts.isFunctionDeclaration(p) && p.name) return p.name.text;
  }
  return "";
}

/** The functions in which a file calls the global `fetch`. */
function functionsCallingFetch(rel: string, src: string): string[] {
  const found: string[] = [];
  walk(parse(rel, src), (node) => {
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === "fetch") found.push(enclosingFunction(node));
  });
  return found;
}

/**
 * A request that may change something (any method but GET) labelled "read", other than a stateless estimator (a function whose name begins `compute`) or the AI reading of an
 * uploaded invoice (`handleExtract`, which proposes figures and records no bill: a reading is a proposal, not a write): its failure would say that no result came back when the
 * change may have gone through.
 */
function readLabelsOnAChange(rel: string, src: string): string[] {
  const found: string[] = [];
  walk(parse(rel, src), (node) => {
    if (!(ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === "fetchPlain")) return;
    const doing = node.arguments[2];
    const init = node.arguments[1];
    if (!doing || !ts.isStringLiteral(doing) || doing.text !== "read" || !init || !ts.isObjectLiteralExpression(init)) return;
    for (const p of init.properties) {
      const named = (ts.isPropertyAssignment(p) || ts.isShorthandPropertyAssignment(p)) && ts.isIdentifier(p.name) && p.name.text === "method";
      if (!named) continue;
      const value = ts.isPropertyAssignment(p) && ts.isStringLiteral(p.initializer) ? p.initializer.text : "(not a literal)";
      const fn = enclosingFunction(node);
      if (value.toUpperCase() !== "GET" && !/^(compute|handleExtract$)/.test(fn)) found.push(`${rel}: ${fn || "(top level)"} sends ${value} and calls it a read`);
    }
  });
  return found;
}

/** How many times a function uses `name`. */
function usesIn(rel: string, src: string, fn: string, name: string): number {
  let n = 0;
  walk(parse(rel, src), (node) => {
    if (ts.isFunctionDeclaration(node) && node.name?.text === fn && node.body) {
      walk(node.body, (c) => { if (ts.isIdentifier(c) && c.text === name) n++; });
    }
  });
  return n;
}

function imports(rel: string, src: string): number {
  let n = 0;
  walk(parse(rel, src), (node) => { if (ts.isImportDeclaration(node)) n++; });
  return n;
}

// ── the tests ───────────────────────────────────────────────────────────────────────────────────────────────────────

test("the helper is pure: it imports nothing, so `lib/api` can import it without a cycle and a test can run it under node", () => {
  assert.equal(imports(HELPER, read(HELPER)), 0);
});

test("the readers the findings name call no `fetch`, read no `Response.json()` of their own and read no status line", () => {
  for (const rel of [...READERS, ...PAGES]) {
    const src = read(rel);
    assert.equal(directFetches(rel, src), 0, `${rel} calls fetch itself: go through fetchPlain`);
    assert.deepEqual(bareJsonReads(rel, src), [], `${rel} reads a Response's JSON itself: go through jsonPlain`);
    assert.deepEqual(statusTextReads(rel, src), [], `${rel} reads a status line: a failed status is read by lib/api's errorMessage`);
  }
});

test("every function of the income-tax and GST data layers that makes a request reads its answer through the module's one reader (POST-A-382)", () => {
  // `lib/data/income-tax.ts` has `readAnswer` and `writeAnswer` (over `answerOf`) and `lib/data/gst.ts` has `gstAnswer`: a function that kept its own `json.error ?? "Failed to …"` would show a 422 as a status line again.
  assert.deepEqual(functionsReadingTheirOwnAnswer("lib/data/income-tax.ts", read("lib/data/income-tax.ts"), ["readAnswer", "writeAnswer", "answerOf"]), []);
  assert.deepEqual(functionsReadingTheirOwnAnswer("lib/data/gst.ts", read("lib/data/gst.ts"), ["gstAnswer"]), []);
  // …and the readers themselves read a failed status through the one reader of it, before they read the body as the house envelope
  for (const [rel, fn] of [["lib/data/income-tax.ts", "answerOf"], ["lib/data/gst.ts", "gstAnswer"]] as const) {
    assert.ok(functionCalls(rel, read(rel), fn, "errorMessage"), `${rel} ${fn} does not read a failed status through errorMessage`);
    assert.ok(functionCalls(rel, read(rel), fn, "jsonPlain"), `${rel} ${fn} does not read the body through jsonPlain`);
  }
});

test("a validation list is flattened without the framework's label, and a page under a failed status is said as a page", () => {
  const rel = "lib/api/index.ts";
  assert.ok(functionCalls(rel, read(rel), "errorSentence", "modelSentence"), "errorSentence does not pass a validation message through modelSentence");
  assert.ok(functionCalls(rel, read(rel), "errorSentence", "looksLikeMarkup"), "errorSentence does not ask whether a failed status carried a page");
  assert.ok(functionCalls(rel, read(rel), "refusalFrom", "looksLikeMarkup"), "refusalFrom does not ask whether a failed status carried a page");
  assert.ok(functionCalls(rel, read(rel), "request", "jsonPlain"), "request() reads the body of a success without jsonPlain");
});

test("the readers say what a request was: a change is never called a read, and the two readers pass the right word", () => {
  for (const dir of ["app", "components", "lib"]) {
    for (const rel of sourceFiles(dir)) {
      const src = read(rel);
      if (!/\bfetchPlain\(/.test(src)) continue;
      assert.deepEqual(readLabelsOnAChange(rel, src), [], `${rel} calls a change a read`);
    }
  }
  const tax = read("lib/data/income-tax.ts");
  assert.match(tax, /function readAnswer<T>\(res: Response, failed: string\): Promise<T> \{\s*return answerOf<T>\(res, failed, "read"\);/, "readAnswer no longer says it is a read");
  assert.match(tax, /function writeAnswer<T>\(res: Response, failed: string\): Promise<T> \{\s*return answerOf<T>\(res, failed, "write"\);/, "writeAnswer no longer says it is a write");
  const gst = read("lib/data/gst.ts");
  assert.match(gst, /fetchPlain\(`\$\{API_BASE\}\$\{path\}`, \{\s*method: "POST",[\s\S]*?\}, "write"\);\s*return gstAnswer<T>\(res, "write"\);/, "the GST data layer's POST no longer says it is a write");
});

test("`lib/api` calls fetch in one function each, the wrapper and request()'s bounded fetch, and a refusal in a validation list is read twice (a page under a failed status, and the list)", () => {
  assert.deepEqual(functionsCallingFetch("lib/api/index.ts", read("lib/api/index.ts")), ["fetchWithTimeout"], "lib/api/index.ts calls fetch outside fetchWithTimeout: go through fetchPlain");
  assert.deepEqual(functionsCallingFetch(HELPER, read(HELPER)), ["fetchPlain"], "the helper calls fetch outside fetchPlain");
  // authedFetch reads a failed status through errorMessage twice: for a body that is not JSON, and for a validation list (POST-A-382)
  assert.ok(usesIn("lib/data/tds.ts", read("lib/data/tds.ts"), "authedFetch", "errorMessage") >= 2, "authedFetch does not read a failed status's validation list or page through errorMessage");
});

test("a request is called a read only where it asks: the estimators, the preview, the check that never writes (independent read A)", () => {
  for (const rel of [GST_PAGE, TDS_PAGE]) {
    assert.deepEqual(readCallsToAChange(rel, read(rel), "apiFetch"), [], `${rel} calls a change a read`);
  }
  assert.deepEqual(readCallsToAChange("lib/data/tds.ts", read("lib/data/tds.ts"), "authedFetch"), [], "lib/data/tds.ts calls a change a read");
  // the population the rule reads: the four estimators on the GST page, the one on the TDS page and the three in the TDS data layer
  assert.equal(readCallsOf(GST_PAGE, read(GST_PAGE), "apiFetch").length, 4, "the GST page's estimators are not the four the rule expects");
  assert.equal(readCallsOf(TDS_PAGE, read(TDS_PAGE), "apiFetch").length, 1, "the TDS page's estimator is not the one the rule expects");
  assert.equal(readCallsOf("lib/data/tds.ts", read("lib/data/tds.ts"), "authedFetch").length, 3, "the TDS data layer's estimators are not the three the rule expects");
  // a simulation transmits, files and records nothing, so everything the wizard sends is a read
  assert.match(read("components/FilingDemoWizard.tsx"), /const doing = "read" as const;/, "the filing walk-through is no longer called a read");
});

test("a catch labels a failed request as the request it wraps was: a change is a write, a question is a read (independent read B)", () => {
  for (const rel of PAGES) {
    assert.deepEqual(labelsThatDisagreeWithTheRequest(rel, read(rel)), [], `${rel}: a catch labels a request as the other kind`);
  }
  // …and the rule sees a real population (a walk that stopped finding the tries would pass without reading any)
  const seen = PAGES.reduce((total, rel) => total + triesThatSayWhatTheyCaught(rel, read(rel)), 0);
  assert.ok(seen >= 20, `only ${seen} tries that make a request and say it through failureSentence were found`);
});

test("a paste and the request that sends it do not share a try, and a write's bare catch does not say a fixed sentence (independent read A)", () => {
  for (const rel of PAGES) {
    assert.deepEqual(triesThatParseAndRequest(rel, read(rel)), [], `${rel}: one catch serves a paste and a request, so a request that failed is told as a bad paste`);
  }
  assert.deepEqual(bareCatchesSaying(PAYROLL, read(PAYROLL), "setSaveError"), [], `${PAYROLL}: a bare catch says a fixed sentence over a write (say it through failureSentence)`);
});

test("request() says a timeout and a second silence by what the request was, and the re-send after a token refresh is no exception (independent read A)", () => {
  const rel = "lib/api/index.ts";
  const src = read(rel);
  assert.match(src, /if \(isTimeout\) throw new Error\(timedOutSentence\(doing\)\);/, "request() says the same timeout sentence for a change as for a question");
  assert.match(src, /throw new Error\(stillNoAnswerSentence\(doing\)\);/, "request() tells a change to retry in a moment after the second silence");
  assert.ok(usesIn(rel, src, "request", "plainFailure") >= 1, "the re-send after a token refresh throws the browser's error as it came");
  // a failed download is read like any other failed request, and a body that stops half way is a failed request too
  assert.ok(functionCalls(rel, src, "downloadFile", "errorMessage"), "a failed download prints `API error 422: {…}` again");
  assert.ok(functionCalls(rel, src, "downloadFile", "plainFailure"), "a download whose connection drops half way says the browser's words");
});

test("the rest of what the independent reads found stays fixed: the notices read, the calendar download, the bulk summary, the period lock's reader", () => {
  const root = read("app/clients/[id]/compliance/page.tsx");
  assert.match(root, /browserFailureOf\(error\) \? failureSentence\(error, "Couldn't load government notices\.", "read"\)/, "the notices read prints the Supabase client's \"TypeError: Failed to fetch\" as it came");
  assert.match(root, /failureSentence\(e, "Try again\.", "read"\)/, "the calendar download is called a change");
  assert.doesNotMatch(root, /Failed to mark \$\{failed\.length\}/, "the bulk summary asserts a failure over a cause that says the outcome is unknown");
  assert.match(root, /not confirmed as filed: \$\{failed\[0\]\.message\}/, "the bulk summary does not say what it knows");
  const lock = read("app/accounting/lock-year/page.tsx");
  assert.match(lock, /if \(!readable\) return \{ success: false, data: null, error: notOursSentence\(doingOf\(method\)\) \};/, "the period lock reads a body that is not JSON as a failure to update");
  assert.match(lock, /looksLikeMarkup\(text\) \? errorPageSentence\(res\.status\) : text/, "the period lock prints a gateway's page as markup");
  for (const [rel, setter] of [["app/clients/[id]/health/page.tsx", "setError(failureSentence(e, \"Failed to load\", \"read\"))"], ["app/clients/[id]/year-end/xbrl/page.tsx", "setLoadError(failureSentence(e, \"Couldn't load XBRL packages.\", \"read\"))"], ["app/clients/[id]/tax/filing/page.tsx", "setLoadError(failureSentence(e, \"Couldn't load ITR filings.\", \"read\"))"]]) {
    assert.ok(read(rel).includes(setter), `${rel}: the database read prints the Supabase client's wording for a dropped connection as it came`);
  }
});

test("the public signing page does not tell a client that their link is invalid because a gateway answered with a page", () => {
  const sign = read("app/sign/page.tsx");
  assert.match(sign, /if \(j === null\) throw new PlainFailure\("not_ours", notOursSentence\("read"\)\);/, "the letter's load reads a body that is not JSON as an answer about the link");
  assert.match(sign, /if \(j === null\) throw new PlainFailure\("not_ours", notOursSentence\("write"\)\);/, "the acceptance reads a body that is not JSON as 'try again'");
  assert.match(sign, /setCouldNotReach\(e instanceof PlainFailure\)/, "a failure to get an answer is told from a link that is not valid");
});

test("the four client compliance pages, the signing page and the vendor statement tab show no thrown request's message themselves", () => {
  for (const rel of [...PAGES, ...ALSO_NO_RAW_MESSAGE]) {
    assert.deepEqual(rawMessageDisplays(rel, read(rel)), [], `${rel} prints the message of a caught value: say it through failureSentence`);
  }
});

test("every request a compliance page makes inside a `try` is caught", () => {
  // What a catch says is the rule above (it may not print the caught value's own message) and, for the GSTR-3B row actions, the test below. A catch that leaves a value
  // unknown on purpose (the engagement question on the root page) says nothing, and that is its design.
  for (const rel of PAGES) {
    assert.deepEqual(uncaughtTries(rel, read(rel)), [], `${rel}: a try that makes a request has no catch`);
  }
});

test("the GSTR-3B tab's five row actions each catch a request that throws (POST-A-405)", () => {
  const rel = "app/clients/[id]/compliance/gst/page.tsx";
  const sf = parse(rel, read(rel));
  const wanted = new Map<string, boolean>([["updateStatus", false], ["recheck", false], ["recompute", false], ["deleteReturn", false]]);
  walk(sf, (node) => {
    if (!ts.isFunctionDeclaration(node) || !node.name || !node.body || !wanted.has(node.name.text)) return;
    // The GSTR-3B tab's actions are the ones that hold the row in `busyRow`.
    let holds = false;
    let caught = false;
    walk(node.body, (n) => {
      if (ts.isCallExpression(n) && ts.isIdentifier(n.expression) && n.expression.text === "setBusyRow") holds = true;
      if (ts.isTryStatement(n) && n.catchClause && n.finallyBlock) {
        walk(n.catchClause.block, (c) => {
          if (ts.isCallExpression(c) && ts.isIdentifier(c.expression) && c.expression.text === "failureSentence") caught = true;
        });
      }
    });
    if (holds) { assert.ok(caught, `${node.name.text} holds its row and does not say a request that throws`); wanted.set(node.name.text, true); }
  });
  for (const [name, seen] of wanted) assert.ok(seen, `the GSTR-3B tab's ${name} was not found holding a row`);
  // `markFiled` asks `updateStatus`, which says it, so the fifth action is covered by the first.
  assert.match(read(rel), /async function markFiled\(id: string, arn: string, filedDate: string\) \{\s*const ok = await updateStatus\(/);
});

test("the browser's Supabase client is made once, with the fetch that answers a dropped connection in the product's words (POST-A-413)", () => {
  const rel = "lib/supabase/client.ts";
  assert.match(read(rel), /createClient\([^;]*\{ global: \{ fetch: plainRestFetch \} \}\)/, `${rel} makes the client without plainRestFetch: a dropped connection reads \"TypeError: Failed to fetch\" at every table read and write`);
  const builders: string[] = [];
  for (const dir of ["app", "components", "lib"]) {
    for (const f of sourceFiles(dir)) if (buildsASupabaseClient(f, read(f))) builders.push(f);
  }
  assert.deepEqual(builders, [rel], "a second place makes a Supabase client, and it would not have the plain fetch");
  const mod = read("lib/supabase/plainRestFetch.ts");
  assert.match(mod, /status: 503/, "the answer for a read that got no answer is not a 503: the client would not send the read again");
  assert.match(mod, /import \{ browserFailureOf, doingOf, NO_ANSWER_CODE, noAnswerSentence \} from "\.\.\/api\/failureSentence\.ts";/, "the module takes its sentences and its code from the one module that says them");
  const reads = awaitsInsideATry("lib/supabase/plainRestFetch.ts", mod, "res", "text");
  assert.ok(reads.inside >= 1 && reads.outside === 0, `the body is not read inside the try (${reads.inside} in, ${reads.outside} out): a connection that dies after the headers is worded by the client as TypeError: network error`);
});

test("request() sends a read again after a dropped connection and a change never (POST-A-412)", () => {
  const src = read("lib/api/index.ts");
  assert.match(src, /if \(!isNetworkFailure\) throw e;\s*if \(doing === "write"\) throw plainFailure\(e, doing\);\s*await sleep\(5_000\);/, "request() waits and sends a change a second time after a dropped connection");
  assert.doesNotMatch(src, /the retry itself is POST-A-412/, "a comment still says that the retry of a change is open");
});

test("the files POST-A-410 converted call no fetch, read no body of their own and keep no copy of the invoice screens' request helpers", () => {
  for (const rel of CONVERTED_IN_410) {
    const src = read(rel);
    assert.equal(directFetches(rel, src), 0, `${rel} calls fetch itself again: go through fetchPlain/jsonPlain`);
    assert.deepEqual(bareJsonReads(rel, src), [], `${rel} reads a body with .json() itself: use jsonPlain`);
    assert.deepEqual(statusTextReads(rel, src), [], `${rel} reads a status line`);
  }
  const page = read("app/clients/[id]/purchases/page.tsx");
  const sf = parse("page.tsx", page);
  const copies: string[] = [];
  walk(sf, (node) => {
    if (ts.isFunctionDeclaration(node) && node.name && ["apiCall", "apiGet", "getAuthToken", "refreshedAuthToken"].includes(node.name.text)) copies.push(node.name.text);
  });
  assert.deepEqual(copies, [], "the purchases page keeps its own copy of a request helper the invoice screens share");
  assert.match(page, /import \{ apiCall, apiGet, getAuthToken \} from "@\/lib\/invoices\/shared";/);
  const shared = read("lib/invoices/shared.ts");
  assert.ok((shared.match(/fetchPlain\(/g) ?? []).length >= 2 && (shared.match(/jsonPlain</g) ?? []).length >= 2, "the shared helpers do not read through the helper module");
  // the uploads and the PDF say what they caught through the helper, as what they were
  for (const [rel, what] of [["components/purchases/DebitNoteEditor.tsx", '"Attachment upload failed.", "write"'], ["components/purchases/PurchaseCreditNoteEditor.tsx", '"Attachment upload failed.", "write"'], ["components/invoices/InvoiceViewDrawer.tsx", '"Unable to open PDF", "read"']] as const) {
    assert.ok(read(rel).includes(`failureSentence(e, ${what})`), `${rel}: the catch does not say what it caught through failureSentence`);
  }
  // the invoice reading's try also holds the mapping of the reading onto the form, so only a request that got no answer is told in the product's words and a defect there says the fixed sentence
  assert.ok(read("components/purchases/PurchaseBillEditor.tsx").includes('setError(e instanceof PlainFailure ? e.message : "AI extraction failed. Please enter the bill details manually.");'), "the invoice reading shows the message of any error in its try");
  // a refusal with no sentence of its own: only a 5xx, a 408 and a 429 are told to try again
  assert.match(read("lib/invoices/shared.ts"), /return res\.status >= 500 \|\| res\.status === 408 \|\| res\.status === 429\s*\?\s*`The server could not complete this request[^`]*Please try again in a moment\.`\s*:\s*`The server did not accept this request/, "a 5xx, a 408 and a 429 with no sentence are not told to try again in a moment, or another 4xx is");
});

test("the payroll page reads a body that is not JSON as what it is, and the four run actions say what was thrown (POST-A-410)", () => {
  const src = read(PAYROLL);
  assert.doesNotMatch(src, /res\.json\(\)\.catch\(\(\) => null\)/, "the reader reads a page that is not JSON as nothing again");
  assert.match(src, /throw new PlainFailure\("not_ours", !res\.ok && looksLikeMarkup\(text\) \? errorPageSentence\(res\.status\) : notOursSentence\(doing\)\);/);
  assert.match(src, /\} else if \(!res\.ok\) \{[^}]*throw new PlainFailure\("not_ours", notOursSentence\(doing\)\);/, "an empty answer under a failed status is read as nothing again");
  assert.deepEqual(writesThatSwallowTheirFailure(PAYROLL, src, "apiFetch"), [], `${PAYROLL}: a change is read as failed whatever was thrown`);
  for (const [fn, sentence] of [["createRun", "CREATE_FAILED"], ["finalizeRun", "FINALIZE_FAILED"], ["recomputeRun", "RECOMPUTE_FAILED"], ["deleteRun", "DELETE_FAILED"]]) {
    assert.ok(src.includes(`failureSentence(thrown, ${sentence}, "write")`), `${fn} does not say a request that got no answer as one`);
  }
  // the rule is live on this page only: four change requests whose catch takes what was thrown, and a read whose catch does not need to (an independent read found the other four pages hold none)
  const payrollCatches = catchesOnRequests(PAYROLL, src, "apiFetch");
  assert.ok(payrollCatches.filter((c) => c.method !== "GET" && c.takesWhatWasThrown).length >= 4, "the rule no longer sees the payroll page's four change requests");
  assert.ok(payrollCatches.some((c) => c.method === "GET" && !c.takesWhatWasThrown), "the rule no longer sees the payroll page's read that swallows its failure by design");
  // the four compliance pages make no such change today; the loop holds that none is added
  for (const rel of PAGES) assert.deepEqual(writesThatSwallowTheirFailure(rel, read(rel), "apiFetch"), [], `${rel}: a change is read as failed whatever was thrown`);
});

test("what a refused or failed GST row action says is announced to a screen reader, on both tabs (POST-A-411)", () => {
  const gst = read("app/clients/[id]/compliance/gst/page.tsx");
  assert.match(gst, /\{rowError && !filingRow && \(\s*\/\/[^\n]*\n\s*<p role="alert" className="text-sm text-state-problem/, "the GSTR-1 tab's row sentence is a plain paragraph again");
  assert.match(gst, /\{rowError && !filingRow && \(\s*\/\/[^\n]*\n\s*<div role="alert" className="text-sm px-3 py-2 rounded bg-state-attention-surface/, "the GSTR-3B tab's row sentence is a plain box again");
});

test("a file that calls fetch itself is one of four that must, or is on the list that only shrinks", () => {
  const calling = new Map<string, number>();
  for (const dir of ["app", "components", "lib"]) {
    for (const rel of sourceFiles(dir)) {
      const src = read(rel);
      if (!/\bfetch\(/.test(src)) continue;
      const n = directFetches(rel, src);
      if (n) calling.set(rel, n);
    }
  }
  const allowed = new Set([...Object.keys(MUST_CALL_FETCH), ...Object.keys(STILL_READ_BY_THEMSELVES)]);
  const strangers = [...calling.keys()].filter((rel) => !allowed.has(rel));
  assert.deepEqual(strangers, [], `these files call fetch themselves: ${strangers.join(", ")}. Go through fetchPlain/jsonPlain (lib/api/failureSentence), so that a dropped connection and a proxy's page are said in the product's words`);
  const stale = Object.keys(STILL_READ_BY_THEMSELVES).filter((rel) => !calling.has(rel));
  assert.deepEqual(stale, [], `these files no longer call fetch themselves: delete them from STILL_READ_BY_THEMSELVES (${stale.join(", ")})`);
  const gone = Object.keys(MUST_CALL_FETCH).filter((rel) => !calling.has(rel));
  assert.deepEqual(gone, [], `${gone.join(", ")} no longer calls fetch: the exception is not needed`);
  // the walk must still find the files that must call it: with the list of the others empty, finding fewer means it has stopped looking
  assert.ok(calling.size >= Object.keys(MUST_CALL_FETCH).length, `only ${calling.size} files found: the walk has stopped finding them`);
});

test("every file on the list exists and every reason is a sentence", () => {
  for (const [rel, why] of Object.entries(STILL_READ_BY_THEMSELVES)) {
    assert.ok(fs.existsSync(path.join(WEB, rel)), `${rel} is gone: delete it from the list`);
    assert.ok(why.length > 20, `${rel} has no reason`);
  }
});

// ── the rules catch what they are for ───────────────────────────────────────────────────────────────────────────────

test("self-test: the rules of POST-A-410, 412 and 413 flag a spoiled copy", () => {
  assert.equal(writesThatSwallowTheirFailure("x.tsx", "async function f() { return apiFetch('/x', { method: 'POST' }).catch(() => null); }", "apiFetch").length, 1, "a change whose failure is swallowed is not seen");
  assert.equal(writesThatSwallowTheirFailure("x.tsx", "async function f() { return apiFetch('/x', { method: \"DELETE\" }).catch(() => null); }", "apiFetch").length, 1, "a delete whose failure is swallowed is not seen");
  assert.deepEqual(writesThatSwallowTheirFailure("x.tsx", "async function f() { return apiFetch('/x').catch(() => null); }", "apiFetch"), [], "a read is flagged");
  assert.deepEqual(writesThatSwallowTheirFailure("x.tsx", "async function f() { let t; return apiFetch('/x', { method: 'POST' }).catch((e) => { t = e; return null; }); }", "apiFetch"), [], "a handler that takes what was thrown is flagged");
  assert.deepEqual(awaitsInsideATry("x.ts", "async function f() { try { const t = await res.text(); } catch (e) { throw e; } }", "res", "text"), { inside: 1, outside: 0 }, "a body read in the try is not seen");
  assert.deepEqual(awaitsInsideATry("x.ts", "async function f() { const t = await res.text(); try { g(); } catch (e) { throw e; } }", "res", "text"), { inside: 0, outside: 1 }, "a body read before the try is read as inside it");
  assert.deepEqual(awaitsInsideATry("x.ts", "async function f() { try { g(); } catch (e) { await res.text(); } }", "res", "text"), { inside: 0, outside: 1 }, "a body read in the catch is read as inside the try");
  assert.deepEqual(awaitsInsideATry("x.ts", "async function f() { try { items.map(async () => { await res.text(); }); } catch (e) { throw e; } }", "res", "text"), { inside: 0, outside: 1 }, "a body read in a function nested in the try is read as inside it");
  assert.deepEqual(awaitsInsideATry("x.ts", "async function f() { try { await other.text(); await res.json(); } catch (e) { throw e; } }", "res", "text"), { inside: 0, outside: 0 }, "another receiver or method is counted");
  assert.equal(buildsASupabaseClient("x.ts", "import { createClient } from '@supabase/supabase-js'; const c = createClient(u, k);"), true, "a Supabase client made here is not seen");
  assert.equal(buildsASupabaseClient("x.ts", "import { createClient as make } from '@supabase/supabase-js'; const c = make(u, k);"), true, "a renamed import is not seen");
  assert.equal(buildsASupabaseClient("x.ts", "import * as sb from '@supabase/supabase-js'; const c = sb.createClient(u, k);"), true, "a namespace import that builds is not seen");
  assert.equal(buildsASupabaseClient("x.ts", "import { SupabaseClient } from '@supabase/supabase-js'; const c = new SupabaseClient(u, k);"), true, "new SupabaseClient is not seen");
  assert.equal(buildsASupabaseClient("x.ts", "async function f() { const m = await import('@supabase/supabase-js'); return m.createClient(u, k); }"), true, "a dynamic import is not seen");
  assert.equal(buildsASupabaseClient("x.ts", "const m = require('@supabase/supabase-js'); const c = m.createClient(u, k);"), true, "a require is not seen");
  assert.equal(buildsASupabaseClient("x.ts", "import type { SupabaseClient } from '@supabase/supabase-js';"), false, "a type import is flagged");
  assert.equal(buildsASupabaseClient("x.ts", "import { type SupabaseClient, type Session } from '@supabase/supabase-js'; let c: SupabaseClient | null = null;"), false, "an element-level type import is flagged");
  assert.equal(buildsASupabaseClient("x.ts", "import * as sb from '@supabase/supabase-js'; let c: sb.SupabaseClient | null = null;"), false, "a namespace import used only as a type is flagged");
  assert.equal(buildsASupabaseClient("x.ts", "export async function createClient(input) { return 1; }"), false, "the product's own createClient is flagged");
  assert.doesNotMatch("const _client = createClient(url, key);", /createClient\([^;]*\{ global: \{ fetch: plainRestFetch \} \}\)/, "a client made without the plain fetch is not seen");
});

test("self-test: each rule flags a spoiled copy of the code it guards", () => {
  assert.equal(labelsThatDisagreeWithTheRequest("x.tsx", "async function f() { try { await apiFetch('/x', { method: 'DELETE' }); } catch (e) { s(failureSentence(e, 'x', 'read')); } }").length, 1, "a change labelled a read is not seen");
  assert.equal(labelsThatDisagreeWithTheRequest("x.tsx", "async function f() { try { await apiFetch('/x'); } catch (e) { s(failureSentence(e, 'x', 'write')); } }").length, 1, "a question labelled a write is not seen");
  assert.equal(labelsThatDisagreeWithTheRequest("x.tsx", "async function f() { try { await apiFetch('/x', { method: 'POST' }); } catch (e) { s(failureSentence(e, 'x')); } }").length, 0, "the default label (a write) over a change is flagged");
  assert.equal(labelsThatDisagreeWithTheRequest("x.tsx", "async function f() { try { await apiFetch('/x', { method: 'POST' }, 'read'); } catch (e) { s(failureSentence(e, 'x', 'read')); } }").length, 0, "an estimator labelled a read is flagged");
  // a table call on the Supabase client is a request too (an independent read found the rule understood apiFetch only)
  assert.equal(labelsThatDisagreeWithTheRequest("x.tsx", "async function f() { try { await supabase.from('t').update({ a: 1 }).eq('id', 1); } catch (e) { s(failureSentence(e, 'x', 'read')); } }").length, 1, "a table write labelled a read is not seen");
  assert.equal(labelsThatDisagreeWithTheRequest("x.tsx", "async function f() { try { await supabase.from('t').insert({ a: 1 }).select(); } catch (e) { s(failureSentence(e, 'x', 'read')); } }").length, 1, "an insert followed by a select is read as a question");
  assert.equal(labelsThatDisagreeWithTheRequest("x.tsx", "async function f() { try { await supabase.from('t').delete().eq('id', 1); } catch (e) { s(failureSentence(e, 'x')); } }").length, 0, "the default label over a table delete is flagged");
  assert.equal(labelsThatDisagreeWithTheRequest("x.tsx", "async function f() { try { await supabase.from('t').select('a').limit(1); } catch (e) { s(failureSentence(e, 'x', 'read')); } }").length, 0, "a table select labelled a read is flagged");
  assert.equal(labelsThatDisagreeWithTheRequest("x.tsx", "async function f() { try { await supabase.from('t').select('a').limit(1); } catch (e) { s(failureSentence(e, 'x', 'write')); } }").length, 1, "a table select labelled a write is not seen");
  assert.equal(triesThatSayWhatTheyCaught("x.tsx", "async function f() { try { await supabase.from('t').select('a'); } catch (e) { s(failureSentence(e, 'x', 'read')); } }"), 1, "a try that asks a table is not counted");
  assert.deepEqual(readCallsToAChange("x.tsx", "async function save() { return apiFetch('/api/tds-workspace/returns', { method: 'POST' }, 'read'); }", "apiFetch"), ["x.tsx: save sends '/api/tds-workspace/returns' and calls it a read"], "a change called a read is not seen");
  assert.deepEqual(readCallsToAChange("x.tsx", "async function f() { return apiFetch('/api/gst/gstr1/from-books', { method: 'POST' }, 'read'); }", "apiFetch"), [], "an estimator is flagged");
  assert.deepEqual(readCallsToAChange("x.tsx", "async function computeFromBooks() { return apiFetch(path, { method: 'POST' }, 'read'); }", "apiFetch"), [], "the compute function is flagged");
  assert.deepEqual(readCallsToAChange("x.tsx", "async function f() { return apiFetch('/api/x', { method: 'POST' }); }", "apiFetch"), [], "a call that says nothing about what it is is flagged");
  assert.equal(triesThatParseAndRequest("x.tsx", "async function f() { try { const p = JSON.parse(t); await apiFetch('/x', { body: p }); } catch { setError('Invalid JSON'); } }").length, 1, "a paste and a request in one try is not seen");
  assert.deepEqual(triesThatParseAndRequest("x.tsx", "async function f() { try { JSON.parse(t); } catch { return; } try { await apiFetch('/x'); } catch (e) { setError(e); } }"), [], "a paste on its own is flagged");
  assert.equal(bareCatchesSaying("x.tsx", "async function f() { try { await g(); } catch { setSaveError('Could not save'); } }", "setSaveError").length, 1, "a bare catch saying a fixed sentence is not seen");
  assert.deepEqual(bareCatchesSaying("x.tsx", "async function f() { try { await g(); } catch (e) { setSaveError(failureSentence(e, 'x', 'write')); } }", "setSaveError"), [], "a catch that says it through the helper is flagged");
  assert.deepEqual(bareCatchesSaying("x.tsx", "async function f() { try { await g(); } catch { setLoadFailed(true); } }", "setSaveError"), [], "a bare catch that sets a flag is flagged");
  assert.deepEqual(readLabelsOnAChange("x.ts", "async function save() { return fetchPlain('/x', { method: 'DELETE' }, 'read'); }"), ["x.ts: save sends DELETE and calls it a read"], "a change called a read is not seen");
  assert.deepEqual(readLabelsOnAChange("x.ts", "async function computeIt() { return fetchPlain('/x', { method: 'POST' }, 'read'); }"), [], "a stateless estimator is flagged");
  assert.deepEqual(readLabelsOnAChange("x.ts", "async function load() { return fetchPlain('/x', { headers: {} }, 'read'); }"), [], "a GET is flagged");
  assert.deepEqual(functionsCallingFetch("x.ts", "async function a() { return fetch('/x'); } async function fetchWithTimeout() { return fetch('/y'); }"), ["a", "fetchWithTimeout"], "the function a fetch sits in is not named");
  assert.deepEqual(functionsReadingTheirOwnAnswer("x.ts", "async function a(res: Response) { const r = await fetchPlain('/x', {}, 'read'); return readAnswer(r, 'x'); }", ["readAnswer"]), [], "a function that reads through the reader is flagged");
  assert.deepEqual(functionsReadingTheirOwnAnswer("x.ts", "async function a() { const r = await fetchPlain('/x', {}, 'read'); return r.status; }", ["readAnswer"]), ["a"], "a function with its own read is not seen");
  const incomeTax = read("lib/data/income-tax.ts");
  assert.ok(directFetches("x.ts", incomeTax.replace(/fetchPlain\(/g, "fetch(")) > 10, "fetchPlain turned back into fetch is not seen");
  assert.ok(bareJsonReads("x.ts", `${incomeTax}\nasync function f(res: Response) { return res.json(); }`).length >= 1, "a bare json read is not seen");
  assert.deepEqual(bareJsonReads("x.ts", "async function f(res: Response) { return res.clone().json(); }"), [], "a read from a copy is flagged");
  assert.ok(statusTextReads("x.ts", "const m = `Failed: ${res.statusText}`;").length === 1, "a status line is not seen");
  assert.ok(rawMessageDisplays("x.tsx", "function f(e: unknown) { return e instanceof Error ? e.message : 'x'; }").length >= 1, "instanceof Error is not seen");
  assert.ok(rawMessageDisplays("x.tsx", "async function f() { try { await g(); } catch (err) { setError(err.message); } }").length === 1, "a caught value's message is not seen");
  assert.ok(rawMessageDisplays("x.tsx", "p.catch((e) => setError(e.message));").length === 1, "a .catch callback's message is not seen");
  assert.deepEqual(rawMessageDisplays("x.tsx", "async function f() { try { await g(); } catch (err) { setError(failureSentence(err, 'x')); } }"), [], "the helper's own use is flagged");
  assert.equal(uncaughtTries("x.tsx", "async function f() { try { await apiFetch('/x'); } finally { done(); } }").length, 1, "a try with no catch is not seen");
  assert.deepEqual(uncaughtTries("x.tsx", "async function f() { try { await apiFetch('/x'); } catch (e) { setError(failureSentence(e, 'x', 'write')); } finally { done(); } }"), [], "a caught request is flagged");
  assert.deepEqual(uncaughtTries("x.tsx", "async function f() { try { await other('/x'); } finally { done(); } }"), [], "a try that makes no request is flagged");
});
