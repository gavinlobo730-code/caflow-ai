/**
 * The next step on an empty list, rendered (frontend_ux-24). Run with:
 *   node --experimental-strip-types --test components/ui/empty-state-action.test.ts
 *
 * Same method as page-header.test.ts: `pnpm test` strips types and does not parse
 * JSX, so this transpiles the REAL empty-state-action.tsx and states.tsx with the
 * TypeScript compiler already in node_modules and renders them with
 * react-dom/server. Four things are replaced by stand-ins: `next/link` (an anchor),
 * `lucide-react` (a named svg), the skeleton spinner and the async-state helper
 * (neither is on the path under test), and `usePermissions`, whose `can` answers
 * from a set the test controls. Everything else, `cn` included, is the product's own
 * code. No browser, no layout, no pixels, and it says so.
 *
 * WHAT IT PINS: an action the caller may not perform renders NOTHING (and so does
 * the row that would hold it), the permission map still resolving renders nothing
 * (fails closed), `"anyone"` is the only way to be offered to everybody, an
 * action that renders nothing does not leave the wrapper's margin behind, and an
 * action that WRITES ignores a second click while the first is still running.
 *
 * That last one needs the real `components/ui/button.tsx`, which the action
 * renders, so this also transpiles it with its two async helpers; the one other
 * change is a `react/jsx-runtime` that records the props of each host element, so
 * the test can take the `onClick` the button actually attached and call it twice
 * on one tick — what a double-click is (the technique scripts/tsxHarness.ts uses,
 * kept local here because this file already owns its stand-ins).
 */
import { test, before, after, beforeEach } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import ts from "typescript";
import { renderToStaticMarkup } from "react-dom/server";
import React from "react";

const WEB = path.resolve(import.meta.dirname, "../..");
type Props = Record<string, unknown>;
let dir = "";
let EmptyStateAction: (p: Props) => React.ReactElement | null;
let EmptyStateActions: (p: Props) => React.ReactElement | null;
let EmptyState: (p: Props) => React.ReactElement | null;

function transpile(rel: string, replacements: Record<string, string>): string {
  const source = fs.readFileSync(path.join(WEB, rel), "utf8");
  let js = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  for (const [from, to] of Object.entries(replacements)) js = js.split(JSON.stringify(from)).join(to);
  return js;
}

before(async () => {
  dir = fs.mkdtempSync(path.join(WEB, ".empty-state-test-"));
  const utils = JSON.stringify(pathToFileURL(path.join(WEB, "lib/utils.ts")).href);
  fs.writeFileSync(path.join(dir, "link.mjs"),
    'import React from "react";\n' +
    'export default function Link({ href, children, ...rest }) {\n' +
    '  return React.createElement("a", { href, ...rest }, children);\n}\n');
  fs.writeFileSync(path.join(dir, "icons.mjs"),
    'import React from "react";\n' +
    'const icon = (name) => () => React.createElement("svg", { "data-icon": name });\n' +
    'export const Inbox = icon("Inbox");\nexport const AlertCircle = icon("AlertCircle");\nexport const RefreshCw = icon("RefreshCw");\n' +
    'export const Loader2 = icon("Loader2");\n');
  // A react/jsx-runtime that records host elements, for the one module whose handler the test calls.
  fs.writeFileSync(path.join(dir, "recording-runtime.mjs"),
    'import * as real from "react/jsx-runtime";\n' +
    'export const Fragment = real.Fragment;\n' +
    'const wrap = (fn) => (type, props, ...rest) => {\n' +
    '  if (typeof type === "string") (globalThis.__host ??= []).push({ type, props });\n' +
    '  return fn(type, props, ...rest);\n};\n' +
    'export const jsx = wrap(real.jsx);\nexport const jsxs = wrap(real.jsxs);\n');
  fs.writeFileSync(path.join(dir, "skeleton.mjs"), "export const Spinner = () => null;\n");
  fs.writeFileSync(path.join(dir, "async.mjs"), 'export const resolveAsyncState = () => "ready";\n');
  // states.tsx also draws the slow-server notice in its loading branch; this file is about EmptyState, which never
  // loads, so the notice is a stand-in that renders nothing and passes its children through.
  fs.writeFileSync(path.join(dir, "slow-notice.mjs"),
    "export const SlowServerNotice = () => null;\nexport const SlowServerScope = ({ children }) => children;\n");
  fs.writeFileSync(path.join(dir, "auth.mjs"),
    "export function usePermissions() {\n" +
    "  const granted = globalThis.__granted ?? new Set();\n" +
    "  return { can: (resource, action) => granted.has(resource + ':' + action) };\n}\n");

  fs.writeFileSync(path.join(dir, "singleFlight.mjs"), transpile("lib/async/singleFlight.ts", {}));
  fs.writeFileSync(path.join(dir, "useSingleFlight.mjs"), transpile("lib/async/useSingleFlight.ts", {
    "@/lib/async/singleFlight": '"./singleFlight.mjs"',
  }));
  fs.writeFileSync(path.join(dir, "button.mjs"), transpile("components/ui/button.tsx", {
    "react/jsx-runtime": '"./recording-runtime.mjs"',
    "lucide-react": '"./icons.mjs"',
    "@/lib/utils": utils,
    "@/lib/async/singleFlight": '"./singleFlight.mjs"',
    "@/lib/async/useSingleFlight": '"./useSingleFlight.mjs"',
  }));
  // The action is recorded too, so a raw <button> written into it (as it once was) is the one the
  // handler is taken from and the double-click below fails on it, rather than the lookup failing.
  fs.writeFileSync(path.join(dir, "empty-state-action.mjs"), transpile("components/ui/empty-state-action.tsx", {
    "react/jsx-runtime": '"./recording-runtime.mjs"',
    "next/link": '"./link.mjs"',
    "@/lib/utils": utils,
    "@/lib/auth/AuthContext": '"./auth.mjs"',
    "@/components/ui/button": '"./button.mjs"',
  }));
  fs.writeFileSync(path.join(dir, "states.mjs"), transpile("components/ui/states.tsx", {
    "lucide-react": '"./icons.mjs"',
    "@/lib/utils": utils,
    "@/components/ui/skeleton": '"./skeleton.mjs"',
    "@/components/ui/slow-server-notice": '"./slow-notice.mjs"',
    "@/components/ui/async-state": '"./async.mjs"',
  }));
  const a = await import(pathToFileURL(path.join(dir, "empty-state-action.mjs")).href);
  const s = await import(pathToFileURL(path.join(dir, "states.mjs")).href);
  EmptyStateAction = a.EmptyStateAction;
  EmptyStateActions = a.EmptyStateActions;
  EmptyState = s.EmptyState;
});

after(() => {
  if (dir) fs.rmSync(dir, { recursive: true, force: true });
  delete (globalThis as Record<string, unknown>).__granted;
  delete (globalThis as Record<string, unknown>).__host;
});

beforeEach(() => grant());

function grant(...pairs: string[]) {
  (globalThis as Record<string, unknown>).__granted = new Set(pairs);
}
const h = React.createElement;
const html = (el: React.ReactElement) => renderToStaticMarkup(el);
const action = (props: Props) => h(EmptyStateAction, { label: "New Invoice", onClick: () => {}, ...props });

test("an action the caller is permitted to perform is a button with its label", () => {
  grant("accounting:write");
  const out = html(action({ requires: ["accounting", "write"] }));
  // The Button primitive writes `type` after `class`; the attributes are the action's own as before.
  assert.match(out, /^<button class="[^"]*bg-brand[^"]*" type="button">New Invoice<\/button>$/);
});

test("an action the caller may NOT perform renders nothing at all", () => {
  grant("accounting:read");
  assert.equal(html(action({ requires: ["accounting", "write"] })), "");
});

test("while the permission map is still resolving nothing is offered (fails closed)", () => {
  grant(); // can() answers false for everything until the map arrives
  assert.equal(html(action({ requires: ["accounting", "write"] })), "");
});

test('"anyone" is offered with no grant at all, and is the only way to be', () => {
  grant();
  assert.match(html(action({ requires: "anyone", label: "View Clients" })), />View Clients</);
  grant("accounting:write");
  assert.equal(html(action({ requires: ["accounting", "read"] })), "", "a different pair is not a grant");
});

test("a link is an anchor to the screen it names, and gated the same way", () => {
  grant("accounting:approve");
  const out = html(h(EmptyStateAction, { requires: ["accounting", "approve"], label: "Migrate from Tally", href: "/migration" }));
  assert.match(out, /^<a href="\/migration" class="[^"]*">Migrate from Tally<\/a>$/);
  grant();
  assert.equal(html(h(EmptyStateAction, { requires: ["accounting", "approve"], label: "x", href: "/migration" })), "");
});

test("an action held mid-request is disabled, and a secondary one is styled apart from the primary", () => {
  // A REAL pair, not a placeholder: apps/api/tests/test_frontend_permission_names_exist.py
  // rglob()s every .ts under apps/web, this file and its comments included, and
  // reads any requires pair it finds as a gate the backend must define.
  grant("accounting:write");
  assert.match(html(action({ requires: ["accounting", "write"], disabled: true })), /^<button class="[^"]*" disabled="" type="button"/);
  const primary = html(action({ requires: ["accounting", "write"] }));
  const secondary = html(action({ requires: ["accounting", "write"], variant: "secondary" }));
  assert.notEqual(primary, secondary);
  assert.match(secondary, /border border-ps-border/);
  assert.doesNotMatch(secondary, /bg-brand/);
});

test("a row of actions shows only the permitted ones, and nothing when none is permitted", () => {
  const row = () =>
    html(h(EmptyStateActions, null,
      action({ requires: ["accounting", "write"], label: "New Invoice" }),
      action({ requires: ["accounting", "approve"], label: "Migrate from Tally", variant: "secondary" })));
  grant("accounting:write");
  const some = row();
  assert.match(some, /^<div class="flex flex-wrap items-center justify-center gap-2">/);
  assert.match(some, /New Invoice/);
  assert.doesNotMatch(some, /Migrate from Tally/);
  grant("accounting:write", "accounting:approve");
  assert.match(row(), /New Invoice.*Migrate from Tally/s, "the primary comes first");
  grant("accounting:read");
  assert.equal(row(), "", "no empty row where the buttons would be");
});

test("an empty list whose actions are all withheld keeps its explanation and no dead space", () => {
  grant("accounting:read");
  const withheld = html(h(EmptyState, {
    title: "No invoices in this period",
    description: "Nothing is dated in this period.",
    action: h(EmptyStateActions, null, action({ requires: ["accounting", "write"] })),
  }));
  assert.match(withheld, /No invoices in this period/);
  assert.match(withheld, /Nothing is dated in this period\./);
  assert.doesNotMatch(withheld, /<button|<a /);
  // the wrapper is EMPTY and says it may be hidden: `empty:hidden` is what takes
  // its margin away, so the page has no blank gap where the buttons would be
  assert.match(withheld, /<div class="mt-4 empty:hidden"><\/div>/);

  grant("accounting:write");
  const offered = html(h(EmptyState, {
    title: "No invoices in this period",
    action: h(EmptyStateActions, null, action({ requires: ["accounting", "write"] })),
  }));
  assert.match(offered, /<div class="mt-4 empty:hidden"><div class="flex[^"]*"><button/);
});

// ── an action that writes holds a repeat click ──────────────────────────────

type Handler = (e: FakeEvent) => unknown;
interface FakeEvent { currentTarget: object; prevented: boolean; stopped: boolean; preventDefault(): void; stopPropagation(): void }
const fakeClick = (): FakeEvent => ({
  currentTarget: {}, prevented: false, stopped: false,
  preventDefault() { this.prevented = true; }, stopPropagation() { this.stopped = true; },
});
const tick = () => new Promise<void>((r) => setImmediate(r));

/** Render `el` and hand back the onClick the <button> it produced carries. */
function attachedHandler(el: React.ReactElement): Handler {
  (globalThis as Record<string, unknown>).__host = [];
  html(el);
  const host = ((globalThis as Record<string, unknown>).__host as Array<{ type: string; props: Record<string, unknown> }>)
    .filter((r) => r.type === "button");
  assert.equal(host.length, 1, "one <button>");
  return host[0].props.onClick as Handler;
}

test("a second click while the first one's request is still running is ignored, and a later one runs", async () => {
  // The defect this pins (frontend_ux-09 reaching frontend_ux-24): the action was a raw
  // <button onClick={props.onClick}>, so on an empty Billing screen two quick presses of
  // Raise Invoice reached the network twice. Four screens passed `() => void handleX()`, which
  // drops the promise, so even the Button primitive could not have held them.
  grant("accounting:write");
  let calls = 0;
  let release!: () => void;
  const running = new Promise<void>((r) => { release = r; });
  const onClick = attachedHandler(action({ requires: ["accounting", "write"], onClick: () => { calls++; return running; } }));

  const first = fakeClick();
  const second = fakeClick();
  onClick(first);
  onClick(second);
  assert.equal(calls, 1, "the handler ran once for two clicks on one tick");
  assert.equal(first.prevented, false);
  assert.equal(second.prevented, true, "the repeat is swallowed, so it cannot submit a form or open the row beneath");
  assert.equal(second.stopped, true);

  release();
  await tick(); await tick();
  onClick(fakeClick());
  assert.equal(calls, 2, "once the promise settled, the action can be pressed again");
});

test("a failed request releases the action so it can be retried, and the failure is not swallowed", async () => {
  // The flight lets a rejection surface as an unhandled rejection exactly as a raw button's
  // would (lib/async/singleFlight.ts), so the test collects them: node:test fails a test on one.
  grant("accounting:write");
  let calls = 0;
  const onClick = attachedHandler(action({
    requires: ["accounting", "write"],
    onClick: () => { calls++; return Promise.reject(new Error("refused")); },
  }));
  const saved = process.listeners("unhandledRejection");
  process.removeAllListeners("unhandledRejection");
  const seen: unknown[] = [];
  process.on("unhandledRejection", (e) => { seen.push(e); });
  try {
    onClick(fakeClick());
    await tick(); await tick();
    onClick(fakeClick());
    await tick(); await tick();
    assert.equal(calls, 2, "the second press ran: a failed save is retryable");
    assert.equal(seen.length, 2, "and each failure still reached the page's own handling");
  } finally {
    process.removeAllListeners("unhandledRejection");
    saved.forEach((l) => process.on("unhandledRejection", l as (...a: unknown[]) => void));
  }
});

test("a handler that returns nothing is an ordinary click: it is never held", () => {
  grant("accounting:write");
  let calls = 0;
  const onClick = attachedHandler(action({ requires: ["accounting", "write"], onClick: () => { calls++; } }));
  onClick(fakeClick());
  onClick(fakeClick());
  assert.equal(calls, 2, "opening a form twice is not a duplicate write");
});

test("the click handler is called with no arguments, so a handler cannot be handed an event by accident", () => {
  grant("accounting:write");
  let seen: unknown[] = [];
  const onClick = attachedHandler(action({ requires: ["accounting", "write"], onClick: (...args: unknown[]) => { seen = args; } }));
  onClick(fakeClick());
  assert.deepEqual(seen, []);
});
