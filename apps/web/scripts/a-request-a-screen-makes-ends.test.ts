// A request a screen makes for itself ends, at a bound that fits what it carries (POST-A-470).
//   node --experimental-strip-types --test scripts/a-request-a-screen-makes-ends.test.ts
//
// WHAT WAS WRONG. Every JSON call through `lib/api`'s `request()` is given up on at 45 seconds, but about thirty screens and data
// modules make their own requests through `fetchPlain` (a page's own `apiFetch`, a PDF download, an upload through `fetchUpload`),
// and none of those had a bound. A request that never answered held the screen, its spinner and any dialog held over it, until the
// browser gave up, which can be minutes. POST-A-395 bounded one page and stopped, because uploads, model reads and exports go
// through the same kind of code and must not be cut off at 45 seconds.
//
// THE RULE, stated over the tree rather than as a list of the doors that exist today:
//   * outside `lib/api`, a request goes out through `fetchBounded` (lib/api's 45 seconds unless the caller passes a bound);
//   * a bare `fetchPlain` or `fetch` is an EXCEPTION, named below with its reason (keyed by file and the function it is in);
//   * a `fetchUpload` passes `timeoutMs`, or is an exception;
//   * a bound is one of the named figures (`REQUEST_BOUND_MS`, `LONG_REQUEST_BOUND_MS`, `HELD_DIALOG_MS`), never a number typed at
//     the call, and a `signal:` handed to a request is `AbortSignal.timeout(<one of them>)`, never a controller that nothing aborts.
// The exceptions list may only shrink: an entry whose call is gone fails, so it is deleted with the call.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import ts from "typescript";
import { LONG_REQUEST_BOUND_MS, REQUEST_BOUND_MS } from "../lib/api/failureSentence.ts";

const WEB = join(import.meta.dirname, "..");

const BOUNDS = new Set(["REQUEST_BOUND_MS", "LONG_REQUEST_BOUND_MS", "HELD_DIALOG_MS"]);

/** Each unbounded call left on purpose, keyed `<file>#<function it is in>`, with why. */
const EXCEPTIONS: Record<string, string> = {
  "lib/invoices/shared.ts#apiCall.doFetch":
    "Every write of the sales and purchase screens, bulk imports included: a bulk import may honestly take longer than any bound, so apiCall has NO default and a caller that holds a dialog passes { timeoutMs: HELD_DIALOG_MS } (POST-A-395).",
  "lib/supabase/plainRestFetch.ts#plainRestFetch":
    "The Supabase client's own transport, under every .from() read and write a screen makes: it carries paged exports and bulk writes, so a bound on it is a decision of its own and not a screen's request; it is left unbounded here on purpose.",
};

export type Finding = { file: string; line: number; key: string; what: string };

/** The named functions around a node, outermost first (`apiCall.doFetch`), so two helpers of one name in a file are told apart. */
function enclosingName(node: ts.Node): string {
  const names: string[] = [];
  for (let p: ts.Node | undefined = node.parent; p; p = p.parent) {
    if ((ts.isFunctionDeclaration(p) || ts.isMethodDeclaration(p)) && p.name) names.unshift(p.name.getText());
    else if (ts.isVariableDeclaration(p) && p.initializer && (ts.isArrowFunction(p.initializer) || ts.isFunctionExpression(p.initializer) || ts.isCallExpression(p.initializer))) {
      names.unshift(p.name.getText());
    }
  }
  return names.length ? names.join(".") : "<module>";
}

const isBound = (e: ts.Expression | undefined): boolean => !!e && ts.isIdentifier(e) && BOUNDS.has(e.text);

const isTimeoutSignal = (e: ts.Expression): boolean =>
  ts.isCallExpression(e) && e.expression.getText() === "AbortSignal.timeout" && isBound(e.arguments[0]);

/** Every request in `src` that is not bounded by the rule. */
export function unboundedRequests(file: string, src: string): Finding[] {
  const sf = ts.createSourceFile(file, src, ts.ScriptTarget.Latest, true, file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const out: Finding[] = [];
  const add = (n: ts.Node, what: string) =>
    out.push({ file, line: sf.getLineAndCharacterOfPosition(n.getStart()).line + 1, key: `${file}#${enclosingName(n)}`, what });
  const visit = (n: ts.Node) => {
    if (ts.isCallExpression(n) && ts.isIdentifier(n.expression)) {
      const name = n.expression.text;
      if (name === "fetch" || name === "fetchPlain") add(n, `${name} with no bound`);
      if (name === "fetchBounded" && n.arguments.length > 3 && !isBound(n.arguments[3])) add(n, "fetchBounded with a bound that is not a named figure");
      if (name === "fetchUpload") {
        const init = n.arguments[1];
        const t = init && ts.isObjectLiteralExpression(init)
          ? init.properties.find((p) => p.name?.getText() === "timeoutMs")
          : undefined;
        if (!t) add(n, "fetchUpload with no timeoutMs");
        else if (!(ts.isPropertyAssignment(t) && isBound(t.initializer))) add(n, "fetchUpload with a timeoutMs that is not a named figure");
      }
    }
    if (ts.isPropertyAssignment(n) && n.name.getText() === "signal" && ts.isObjectLiteralExpression(n.parent) && !isTimeoutSignal(n.initializer)) {
      add(n, "a signal that is not AbortSignal.timeout(<a named bound>)");
    }
    ts.forEachChild(n, visit);
  };
  visit(sf);
  return out;
}

function walk(dir: string, out: string[] = []): string[] {
  for (const e of readdirSync(join(WEB, dir))) {
    if (e === "node_modules" || e === ".next") continue;
    const rel = join(dir, e).replace(/\\/g, "/");
    if (statSync(join(WEB, rel)).isDirectory()) walk(rel, out);
    else if (/\.tsx?$/.test(rel) && !rel.includes(".test.") && !rel.startsWith("lib/api/")) out.push(rel);
  }
  return out;
}

const files = ["app", "components", "lib"].flatMap((d) => walk(d));
const findings = files.flatMap((f) => unboundedRequests(f, readFileSync(join(WEB, f), "utf8")));

test("the rule: an unbounded request is found, a bounded one is not, and a bound typed as a number is refused", () => {
  const keys = (src: string) => unboundedRequests("t.ts", src).map((f) => `${f.key} ${f.what}`);
  assert.deepEqual(keys(`async function a() { return fetchPlain("/x", {}, "read"); }`), ["t.ts#a fetchPlain with no bound"]);
  assert.deepEqual(keys(`const b = async () => fetch("/x");`), ["t.ts#b fetch with no bound"]);
  assert.deepEqual(keys(`async function c() { return fetchBounded("/x", {}, "read"); }`), []);
  assert.deepEqual(keys(`async function c() { return fetchBounded("/x", {}, "read", LONG_REQUEST_BOUND_MS); }`), []);
  assert.deepEqual(keys(`async function c() { return fetchBounded("/x", {}, "read", 600000); }`), ["t.ts#c fetchBounded with a bound that is not a named figure"]);
  assert.deepEqual(keys(`function d() { return fetchUpload("/u", { body: f }, "write", cb); }`), ["t.ts#d fetchUpload with no timeoutMs"]);
  assert.deepEqual(keys(`function d() { return fetchUpload("/u", { body: f, timeoutMs: LONG_REQUEST_BOUND_MS }, "write", cb); }`), []);
  assert.deepEqual(keys(`function e() { return apiFetch("/x", { method: "POST", signal: AbortSignal.timeout(LONG_REQUEST_BOUND_MS) }); }`), []);
  assert.deepEqual(keys(`function e() { return apiFetch("/x", { method: "POST", signal: controller.signal }); }`), ["t.ts#e a signal that is not AbortSignal.timeout(<a named bound>)"]);
  assert.deepEqual(keys(`function e() { return apiFetch("/x", { signal: AbortSignal.timeout(1000) }); }`), ["t.ts#e a signal that is not AbortSignal.timeout(<a named bound>)"]);
  // A type that names a field `signal` is not a request.
  assert.deepEqual(keys(`type T = { signal: string }; const x: T = { signal: "churn" } as T;`), ["t.ts#<module> a signal that is not AbortSignal.timeout(<a named bound>)"]);
  assert.deepEqual(keys(`type T = { signal: string };`), []);
});

test("every request a screen makes for itself is bounded, or is an exception named with its reason", () => {
  const unexcused = findings.filter((f) => !(f.key in EXCEPTIONS)).map((f) => `${f.file}:${f.line} ${f.what}`);
  assert.deepEqual(unexcused, [],
    "a request with no bound: send it through fetchBounded (REQUEST_BOUND_MS, or LONG_REQUEST_BOUND_MS for an upload, a model reading a document, an export or a firm-wide recalculation), or name it in EXCEPTIONS with why it must stay unbounded");
});

test("the exceptions list only shrinks: each entry still names an unbounded call", () => {
  const live = new Set(findings.map((f) => f.key));
  assert.deepEqual(Object.keys(EXCEPTIONS).filter((k) => !live.has(k)), [], "an exception whose call is gone: delete its entry");
  for (const [k, why] of Object.entries(EXCEPTIONS)) assert.ok(why.length > 40, `${k} gives no reason`);
});

test("the scan reads the product: the bounded door is used across the screens", () => {
  const uses = files.reduce((n, f) => n + (readFileSync(join(WEB, f), "utf8").match(/\bfetchBounded\(/g) ?? []).length, 0);
  assert.ok(uses >= 60, `only ${uses} fetchBounded calls were found: the scan is not reading the product`);
});

test("lib/api's own request() is bounded by the same named figure, and the figures are what the rule says", () => {
  assert.equal(REQUEST_BOUND_MS, 45_000);
  assert.ok(LONG_REQUEST_BOUND_MS > REQUEST_BOUND_MS);
  const api = ts.createSourceFile("index.ts", readFileSync(join(WEB, "lib/api/index.ts"), "utf8"), ts.ScriptTarget.Latest, true);
  let bound: string | null = null;
  const visit = (n: ts.Node) => {
    if (ts.isFunctionDeclaration(n) && n.name?.text === "fetchWithTimeout") {
      const find = (m: ts.Node) => {
        if (ts.isCallExpression(m) && m.expression.getText() === "setTimeout") bound = m.arguments[1]?.getText() ?? null;
        ts.forEachChild(m, find);
      };
      find(n);
    }
    ts.forEachChild(n, visit);
  };
  visit(api);
  assert.equal(bound, "REQUEST_BOUND_MS", "lib/api's request() is bounded by a figure other than the one the screens use");
  const shared = readFileSync(join(WEB, "lib/invoices/shared.ts"), "utf8");
  assert.match(shared, /export const HELD_DIALOG_MS = REQUEST_BOUND_MS;/, "a held dialog's bound is not lib/api's figure");
});
