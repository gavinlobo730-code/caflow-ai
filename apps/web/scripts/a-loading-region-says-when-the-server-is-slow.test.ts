// A LOADING REGION SAYS WHEN THE SERVER IS SLOW, AND KEEPS IT AWAKE WHILE THE TAB IS OPEN (frontend_ux-05).
//   node --experimental-strip-types --test scripts/a-loading-region-says-when-the-server-is-slow.test.ts
//
// ─────────────────────────────────────────────────────────────────────────────
// THE DEFECT
// ─────────────────────────────────────────────────────────────────────────────
// The API sleeps on a free tier and a cold start takes up to a minute. The 29-09-2026 walk-through recorded
// skeletons of five to fifteen seconds on nearly every non-trivial screen and some past thirty, and the only
// words a CA ever got came AFTER a failure ("it may be waking up"). `AsyncBoundary`, `PageLoader` and every
// skeleton drew grey blocks indefinitely, and the one mitigation was a single /health ping when AuthContext
// mounted — so a CA who worked for twenty minutes on what was already on screen met the cold start in the
// middle of the day.
//
// ─────────────────────────────────────────────────────────────────────────────
// WHAT THIS HOLDS, AND HOW
// ─────────────────────────────────────────────────────────────────────────────
// THE RULE, as source: every function in components/ui/skeleton.tsx that renders a loading region (a
// `role="status"`) also renders the shared `SlowServerNotice`, `PageLoader` and `AsyncBoundary` included, so a
// new skeleton cannot be written without it. It is judged by what the function renders and not by a list of
// today's skeletons, and it is run on the real file and, as a negative control, on the same file with one
// notice removed.
//
// THE BEHAVIOUR, rendered: the real components through the TSX harness. A server render runs no effects, so
// what it can prove is the structure — exactly ONE notice region per loading boundary, none over data, over an
// error or over an empty state, and a skeleton nested in `AsyncBoundary` not saying it a second time. The
// behaviour over time (silent, then the sentence, then a Retry, reset when the region leaves) runs the real
// hook and the real component under a minimal hook runner and node's mock timers.
//
// NO RETRY BY ITSELF, AND ONLY EVER ON A READ: `onRetry` is called in exactly one place, inside the Retry
// button's click; the notice component is imported only by the two files that draw loading placeholders, so it
// can never sit inside a form or a button that is saving. A Retry that re-sent a write would be a duplicate
// voucher, which is why `lib/api` does not retry a timeout either.
//
// WHAT IT DOES NOT PROVE: that a browser paints the sentence or that a screen reader reads it once. The walk
// does that where a browser exists (scripts/smoke-walk.mjs, `slowServerScenario`: the API held for 24 s, the
// sentence at about three seconds, a Retry at about twenty, both gone with the data) — and it has not been
// run by a screen reader.
import test, { mock } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import ts from "typescript";
import { loadModule, loadModuleWithReact, requireFromWeb } from "./tsxHarness.ts";
import { WAKING_SENTENCE as WALK_SENTENCE } from "./walkAudits.mjs";
import { WAKING_SENTENCE, WAKING_NOTICE_AFTER_MS, RETRY_OFFERED_AFTER_MS } from "../lib/async/slowServer.ts";

const WEB = join(import.meta.dirname, "..");
const read = (rel: string) => readFileSync(join(WEB, rel), "utf8");
const React = requireFromWeb("react") as typeof import("react");
const { renderToStaticMarkup } = requireFromWeb("react-dom/server") as typeof import("react-dom/server");
const h = React.createElement;

function parse(rel: string, text = read(rel)): ts.SourceFile {
  return ts.createSourceFile(rel, text, ts.ScriptTarget.Latest, true, rel.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
}
function walk(node: ts.Node, visit: (n: ts.Node) => void): void {
  visit(node);
  node.forEachChild((c) => walk(c, visit));
}
const tagName = (n: ts.Node): string | null =>
  ts.isJsxSelfClosingElement(n) || ts.isJsxOpeningElement(n) ? n.tagName.getText() : null;

// ═════════════════════════════════════════════════════════════════════════════
// 1. THE RULE, AS SOURCE
// ═════════════════════════════════════════════════════════════════════════════

/** The skeleton file's loading regions that render no `SlowServerNotice`, by function name. */
function regionsWithoutNotice(text: string): { regions: string[]; missing: string[] } {
  const sf = parse("components/ui/skeleton.tsx", text);
  const regions: string[] = [];
  const missing: string[] = [];
  sf.forEachChild((n) => {
    if (!ts.isFunctionDeclaration(n) || !n.name || !n.body) return;
    // A function that draws a loading REGION says so with role="status" on something it renders.
    let isRegion = false;
    let hasNotice = false;
    walk(n.body, (c) => {
      if (ts.isJsxAttribute(c) && c.name.getText() === "role"
        && c.initializer && ts.isStringLiteral(c.initializer) && c.initializer.text === "status") isRegion = true;
      if (tagName(c) === "SlowServerNotice") hasNotice = true;
    });
    if (n.name.text === "Spinner") return; // an inline control indicator in a button, not a region of the page
    if (isRegion) { regions.push(n.name.text); if (!hasNotice) missing.push(n.name.text); }
  });
  return { regions, missing };
}

test("every loading region in skeleton.tsx renders the shared notice, PageLoader included", () => {
  const { regions, missing } = regionsWithoutNotice(read("components/ui/skeleton.tsx"));
  assert.ok(regions.length >= 10, `found only ${regions.length} loading regions (${regions.join(", ")}) — the walk is vacuous`);
  assert.ok(regions.includes("PageLoader") && regions.includes("TableSkeleton"));
  assert.deepEqual(missing, [], `a loading region with no SlowServerNotice: ${missing.join(", ")}`);
});

test("negative control: the same file with one notice removed names the region that lost it", () => {
  const text = read("components/ui/skeleton.tsx");
  const broken = text.replace('<SlowServerNotice className="col-span-full" />', "");
  assert.notEqual(broken, text, "premise: the notice was there to remove");
  const { missing } = regionsWithoutNotice(broken);
  assert.equal(missing.length, 1);
  assert.match(missing[0], /DashboardSkeleton|CardGridSkeleton/);
});

test("the pieces of a region and the inline spinner are the only role-less or exempt functions", () => {
  const sf = parse("components/ui/skeleton.tsx");
  const exported: string[] = [];
  sf.forEachChild((n) => { if (ts.isFunctionDeclaration(n) && n.name) exported.push(n.name.text); });
  const { regions } = regionsWithoutNotice(read("components/ui/skeleton.tsx"));
  const others = exported.filter((f) => !regions.includes(f)).sort();
  // Parts of a region (they never stand alone) and the spinner. A new one in this list is a decision.
  assert.deepEqual(others, ["ClientHeaderSkeleton", "MetricCardSkeleton", "Skeleton", "SkeletonText", "Spinner"]);
});

/** What AsyncBoundary does about the notice, read from its source. */
function boundaryFacts(text: string): { noticeRetry: string; scoped: boolean } {
  const sf = parse("components/ui/states.tsx", text);
  let boundary: ts.FunctionDeclaration | undefined;
  sf.forEachChild((n) => { if (ts.isFunctionDeclaration(n) && n.name?.text === "AsyncBoundary") boundary = n; });
  assert.ok(boundary, "AsyncBoundary not found");
  let noticeRetry = "";
  let scoped = false;
  walk(boundary, (n) => {
    if (tagName(n) === "SlowServerNotice" && ts.isJsxSelfClosingElement(n)) {
      n.attributes.properties.forEach((p) => {
        if (ts.isJsxAttribute(p) && p.name.getText() === "onRetry" && p.initializer && ts.isJsxExpression(p.initializer)) {
          noticeRetry = p.initializer.expression?.getText() ?? "";
        }
      });
    }
    if (ts.isJsxOpeningElement(n) && n.tagName.getText() === "SlowServerScope") scoped = true;
  });
  return { noticeRetry, scoped };
}

test("AsyncBoundary's loading branch renders the notice with its own onRetry, around a skeleton in a scope", () => {
  const facts = boundaryFacts(read("components/ui/states.tsx"));
  assert.equal(facts.noticeRetry, "onRetry", "the boundary's Retry must be the region's own read-again, the one its error state calls");
  assert.ok(facts.scoped, "the skeleton it was given must sit in a SlowServerScope, or the sentence is said twice");
});

test("negative control: a boundary that lost its scope, or its retry, is caught", () => {
  const text = read("components/ui/states.tsx");
  const unscoped = text.replace(/<\/?SlowServerScope>/g, "");
  assert.notEqual(unscoped, text, "premise: the scope was there to remove");
  assert.equal(boundaryFacts(unscoped).scoped, false);
  const noRetry = text.replace("<SlowServerNotice onRetry={onRetry} />", "<SlowServerNotice />");
  assert.notEqual(noRetry, text, "premise: the retry was there to remove");
  assert.equal(boundaryFacts(noRetry).noticeRetry, "");
});

test("onRetry is called in exactly one place — the Retry button's click — and never by the hook or the watch", () => {
  const sf = parse("components/ui/slow-server-notice.tsx");
  const calls: ts.CallExpression[] = [];
  walk(sf, (n) => { if (ts.isCallExpression(n) && n.expression.getText() === "onRetry") calls.push(n); });
  assert.equal(calls.length, 1);
  let insideOnClick = false;
  for (let p: ts.Node | undefined = calls[0]; p; p = p.parent) {
    if (ts.isJsxAttribute(p) && p.name.getText() === "onClick") insideOnClick = true;
  }
  assert.ok(insideOnClick, "an automatic retry would re-send a request the server may still be answering");
  for (const f of ["lib/async/slowServer.ts", "lib/async/useSlowServerNotice.ts"]) {
    assert.doesNotMatch(read(f).replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, ""), /onRetry/, `${f} must not know how to retry`);
  }
});

test("the notice is imported only by the two files that draw loading placeholders", () => {
  const importers: string[] = [];
  const visit = (dir: string) => {
    for (const name of readdirSync(dir)) {
      if (name === "node_modules" || name === ".next" || name === "out" || name.startsWith(".")) continue;
      const full = join(dir, name);
      if (statSync(full).isDirectory()) { visit(full); continue; }
      if (!/\.tsx?$/.test(name) || /\.test\.ts$/.test(name)) continue;
      if (/from\s+["']@\/components\/ui\/slow-server-notice["']/.test(readFileSync(full, "utf8"))) importers.push(relative(WEB, full));
    }
  };
  for (const d of ["app", "components", "lib"]) visit(join(WEB, d));
  // A loading placeholder is what a READ shows. Nothing that is saving renders this, so a Retry here can never
  // send a write twice.
  assert.deepEqual(importers.sort(), ["components/ui/skeleton.tsx", "components/ui/states.tsx"]);
});

test("the walk's copy of the sentence is the screen's, word for word", () => {
  assert.equal(WALK_SENTENCE, WAKING_SENTENCE);
});

// ═════════════════════════════════════════════════════════════════════════════
// 2. THE STRUCTURE, RENDERED
// ═════════════════════════════════════════════════════════════════════════════

type Cmp = React.ComponentType<Record<string, unknown>>;
const states = loadModule<{ AsyncBoundary: Cmp }>("components/ui/states");
const skeletons = loadModule<Record<string, Cmp>>("components/ui/skeleton");
const noticesIn = (html: string) => (html.match(/data-slow-server-notice="/g) ?? []).length;

test("each loading region renders exactly one notice region, silent until its effect starts a clock", () => {
  for (const name of ["PageLoader", "TableSkeleton", "DashboardSkeleton", "ListSkeleton", "CardGridSkeleton",
    "FormSkeleton", "TimelineSkeleton", "StatementSkeleton", "TransactionListSkeleton", "ChartSkeleton"]) {
    const html = renderToStaticMarkup(h(skeletons[name]));
    assert.equal(noticesIn(html), 1, `${name} must render one notice region`);
    assert.match(html, /data-slow-server-notice="quiet"/);
    assert.doesNotMatch(html, new RegExp(WAKING_SENTENCE.slice(0, 20)), `${name} must be silent on first paint`);
  }
});

test("a bare table skeleton carries it too", () => {
  assert.equal(noticesIn(renderToStaticMarkup(h(skeletons.TableSkeleton, { bare: true }))), 1);
});

test("AsyncBoundary: one notice while loading, and none over an error, an empty state or the data", () => {
  const { AsyncBoundary } = states;
  const body = h("p", null, "the table");
  assert.equal(noticesIn(renderToStaticMarkup(h(AsyncBoundary, { loading: true }, body))), 1, "the default spinner");
  assert.equal(noticesIn(renderToStaticMarkup(h(AsyncBoundary, { loading: true, onRetry: () => {} }, body))), 1);
  assert.equal(noticesIn(renderToStaticMarkup(h(AsyncBoundary, { loading: false }, body))), 0, "never over data");
  assert.equal(noticesIn(renderToStaticMarkup(h(AsyncBoundary, { loading: false, error: "boom" }, body))), 0, "never over an error");
  assert.equal(noticesIn(renderToStaticMarkup(
    h(AsyncBoundary, { loading: false, isEmpty: true, empty: h("p", null, "none") }, body))), 0, "never over an empty state");
});

test("a skeleton inside AsyncBoundary does not say it a second time", () => {
  const { AsyncBoundary } = states;
  const html = renderToStaticMarkup(
    h(AsyncBoundary, { loading: true, onRetry: () => {}, skeleton: h(skeletons.TableSkeleton, { rows: 3 }) }, h("p", null, "x")));
  assert.equal(noticesIn(html), 1, "the boundary's own notice speaks; the skeleton's is covered by the scope");
  const bare = renderToStaticMarkup(h(skeletons.TableSkeleton, { rows: 3 }));
  assert.equal(noticesIn(bare), 1, "premise: outside a boundary the same skeleton does carry its own");
});

// ═════════════════════════════════════════════════════════════════════════════
// 3. THE BEHAVIOUR OVER TIME
// ═════════════════════════════════════════════════════════════════════════════
//
// A minimal stand-in for the hooks the notice uses — useState, useEffect, useCallback, createContext and
// useContext — with real semantics for what matters here: state persists across renders, an effect runs after
// a render whose dependencies changed, its cleanup runs before its next run and on unmount, and a state change
// made outside a render (a timer) is picked up by the next `refresh()`.

interface Slot { value?: unknown; deps?: unknown[]; cleanup?: (() => void) | void; ran?: boolean }

function miniReact() {
  let slots: Slot[] = [];
  let i = 0;
  let queue: { k: number; fn: () => void | (() => void); deps?: unknown[] }[] = [];
  let again = false;
  const changed = (a?: unknown[], b?: unknown[]) => !a || !b || a.length !== b.length || a.some((x, j) => !Object.is(x, b[j]));
  const react = {
    useState<T>(init: T | (() => T)): [T, (v: T | ((p: T) => T)) => void] {
      const k = i++;
      const slot = (slots[k] ??= { value: typeof init === "function" ? (init as () => T)() : init });
      const set = (v: T | ((p: T) => T)) => {
        const next = typeof v === "function" ? (v as (p: T) => T)(slot.value as T) : v;
        if (!Object.is(next, slot.value)) { slot.value = next; again = true; }
      };
      return [slot.value as T, set];
    },
    useEffect(fn: () => void | (() => void), deps?: unknown[]) {
      const k = i++;
      const slot = (slots[k] ??= {});
      if (!slot.ran || changed(slot.deps, deps)) queue.push({ k, fn, deps });
      slot.ran = true;
    },
    useCallback<T>(fn: T, deps: unknown[]): T {
      const k = i++;
      const slot = (slots[k] ??= {});
      if (!slot.ran || changed(slot.deps, deps)) { slot.value = fn; slot.deps = deps; slot.ran = true; }
      return slot.value as T;
    },
    createContext<T>(value: T) { return { _v: value, Provider: () => null }; },
    useContext<T>(ctx: { _v: T }): T { return ctx._v; },
  };
  function mount<P, R>(render: (p: P) => R, initial: P) {
    let props = initial;
    let result!: R;
    const settle = () => {
      for (let guard = 0; guard < 20; guard++) {
        again = false; i = 0; queue = [];
        result = render(props);
        for (const e of queue) {
          const s = slots[e.k];
          if (typeof s.cleanup === "function") s.cleanup();
          s.cleanup = e.fn(); s.deps = e.deps;
        }
        if (!again) return;
      }
      throw new Error("render loop");
    };
    settle();
    return {
      get result() { return result; },
      rerender(next: P) { props = next; settle(); },
      refresh() { settle(); },
      unmount() { for (const s of slots) if (typeof s.cleanup === "function") s.cleanup(); slots = []; },
    };
  }
  return { react, mount };
}

type HookMod = {
  useSlowServerNotice: (pending: boolean, o?: { canRetry?: boolean }) => { phase: string; restart: () => void };
};

function loadHook() {
  const rt = miniReact();
  const mod = loadModuleWithReact<HookMod>("lib/async/useSlowServerNotice", rt.react);
  return { ...rt, ...mod };
}

test("the hook is quiet for three seconds, says so at three, offers retry at twenty — and a hidden clock is the mocked one", () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const { mount, useSlowServerNotice } = loadHook();
    const m = mount((pending: boolean) => useSlowServerNotice(pending, { canRetry: true }), true as boolean);
    assert.equal(m.result.phase, "quiet");
    mock.timers.tick(WAKING_NOTICE_AFTER_MS - 1); m.refresh();
    assert.equal(m.result.phase, "quiet", "a warm server answers inside this");
    mock.timers.tick(1); m.refresh();
    assert.equal(m.result.phase, "waking");
    mock.timers.tick(RETRY_OFFERED_AFTER_MS - WAKING_NOTICE_AFTER_MS); m.refresh();
    assert.equal(m.result.phase, "stalled");
    m.unmount();
  } finally { mock.timers.reset(); }
});

test("the sentence is gone in the very render the data arrives, not an effect later", () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const { mount, useSlowServerNotice } = loadHook();
    const m = mount((pending: boolean) => useSlowServerNotice(pending), true as boolean);
    mock.timers.tick(5_000); m.refresh();
    assert.equal(m.result.phase, "waking");
    m.rerender(false);
    assert.equal(m.result.phase, "quiet", "for one frame over the data the sentence would still be on screen");
    m.unmount();
  } finally { mock.timers.reset(); }
});

test("a region that finishes cancels both of its timers; so does unmounting", () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  const realClear = globalThis.clearTimeout;
  const cleared: unknown[] = [];
  globalThis.clearTimeout = ((handle?: Parameters<typeof clearTimeout>[0]) => {
    cleared.push(handle);
    return realClear(handle);
  }) as typeof clearTimeout;
  try {
    const { mount, useSlowServerNotice } = loadHook();
    const m = mount((pending: boolean) => useSlowServerNotice(pending), true as boolean);
    m.rerender(false);
    assert.equal(cleared.length, 2, "the data arrived: neither the 3 s nor the 20 s timer may be left to fire");
    mock.timers.tick(60_000); m.refresh();
    assert.equal(m.result.phase, "quiet", "no stale timer fires into a region that is no longer pending");

    cleared.length = 0;
    const again = mount((pending: boolean) => useSlowServerNotice(pending), true as boolean);
    again.unmount();
    assert.equal(cleared.length, 2, "unmounting is the same as finishing");
  } finally {
    globalThis.clearTimeout = realClear;
    mock.timers.reset();
  }
});

test("restart puts the region back to quiet and the next offer is twenty seconds after the NEW request", () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const { mount, useSlowServerNotice } = loadHook();
    const m = mount((pending: boolean) => useSlowServerNotice(pending, { canRetry: true }), true as boolean);
    mock.timers.tick(21_000); m.refresh();
    assert.equal(m.result.phase, "stalled");
    m.result.restart(); m.refresh();
    assert.equal(m.result.phase, "quiet");
    mock.timers.tick(RETRY_OFFERED_AFTER_MS - 1); m.refresh();
    assert.equal(m.result.phase, "waking");
    mock.timers.tick(1); m.refresh();
    assert.equal(m.result.phase, "stalled");
    m.unmount();
  } finally { mock.timers.reset(); }
});

// The component, driven under the same runner. Its output is a React element tree, read directly.

type El = { type: unknown; props: Record<string, unknown> };
const isEl = (x: unknown): x is El => typeof x === "object" && x !== null && "props" in (x as object);
function flat(children: unknown): unknown[] {
  return (Array.isArray(children) ? children : [children]).flatMap((c) => (Array.isArray(c) ? flat(c) : [c]));
}
function findAll(root: unknown, pick: (e: El) => boolean): El[] {
  const out: El[] = [];
  const go = (n: unknown) => {
    if (!isEl(n)) return;
    if (pick(n)) out.push(n);
    flat(n.props.children).forEach(go);
  };
  go(root);
  return out;
}
const textOf = (root: unknown): string =>
  flat(isEl(root) ? root.props.children : root).map((c) => (typeof c === "string" ? c : isEl(c) ? textOf(c) : "")).join("");

function loadNotice() {
  const rt = miniReact();
  const mod = loadModuleWithReact<{ SlowServerNotice: (p: Record<string, unknown>) => unknown }>(
    "components/ui/slow-server-notice", rt.react);
  return { ...rt, ...mod };
}

test("the notice: empty and silent, then the sentence once, then a Retry only where it can read again", () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    let retried = 0;
    const { mount, SlowServerNotice } = loadNotice();
    const m = mount((p: Record<string, unknown>) => SlowServerNotice(p), { onRetry: () => { retried++; } });
    const root = () => m.result as El;
    assert.equal(root().props["data-slow-server-notice"], "quiet");
    assert.equal(root().props.role, "status");
    assert.equal(root().props["aria-live"], "polite");
    assert.equal(textOf(root()), "", "nothing is said inside the first three seconds");

    mock.timers.tick(WAKING_NOTICE_AFTER_MS); m.refresh();
    assert.equal(root().props["data-slow-server-notice"], "waking");
    assert.equal(textOf(root()), WAKING_SENTENCE);
    assert.equal(findAll(root(), (e) => e.type === "button").length, 0, "no Retry yet: a request is still on its way");

    mock.timers.tick(RETRY_OFFERED_AFTER_MS - WAKING_NOTICE_AFTER_MS); m.refresh();
    assert.equal(root().props["data-slow-server-notice"], "stalled");
    assert.equal(textOf(root()).startsWith(WAKING_SENTENCE), true, "the sentence stays, unchanged");
    const [button] = findAll(root(), (e) => e.type === "button");
    assert.ok(button, "a Retry is offered where the region can read again");
    assert.equal(retried, 0, "nothing retried by itself");

    (button.props.onClick as () => void)();
    assert.equal(retried, 1, "pressing it calls the region's own read-again, once");
    m.refresh();
    assert.equal(root().props["data-slow-server-notice"], "quiet", "and the offer is withdrawn while the new request runs");
    m.unmount();
  } finally { mock.timers.reset(); }
});

test("the notice with no onRetry never draws a button, however long the wait", () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const { mount, SlowServerNotice } = loadNotice();
    const m = mount((p: Record<string, unknown>) => SlowServerNotice(p), {});
    mock.timers.tick(RETRY_OFFERED_AFTER_MS * 3); m.refresh();
    const root = m.result as El;
    assert.equal(root.props["data-slow-server-notice"], "stalled");
    assert.equal(findAll(root, (e) => e.type === "button").length, 0, "a button that does nothing is worse than none");
    assert.equal(textOf(root), WAKING_SENTENCE);
    m.unmount();
  } finally { mock.timers.reset(); }
});

test("a notice told it is not pending starts no clock and says nothing", () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    const { mount, SlowServerNotice } = loadNotice();
    const m = mount((p: Record<string, unknown>) => SlowServerNotice(p), { pending: false });
    mock.timers.tick(60_000); m.refresh();
    assert.equal((m.result as El).props["data-slow-server-notice"], "quiet");
    m.unmount();
  } finally { mock.timers.reset(); }
});

// ═════════════════════════════════════════════════════════════════════════════
// 4. THE KEEP-ALIVE IS ONE CONTROLLER, STARTED BY AUTHCONTEXT
// ═════════════════════════════════════════════════════════════════════════════

test("AuthContext reuses ONE keep-awake controller: warm up on mount, start while signed in, stop on the way out", () => {
  const sf = parse("lib/auth/AuthContext.tsx");
  const calls: Record<string, number> = {};
  const idents = new Set<string>();
  walk(sf, (n) => {
    if (ts.isCallExpression(n)) {
      const callee = n.expression.getText();
      calls[callee] = (calls[callee] ?? 0) + 1;
    }
    if (ts.isIdentifier(n)) idents.add(n.text);
  });
  assert.equal(calls["browserKeepAwake"], 1, "one controller is built");
  assert.equal(calls["awake.warmUp"], 1, "the old mount-time ping, now the controller's");
  assert.equal(calls["awake.start"], 1);
  assert.ok((calls["awake.stop"] ?? 0) >= 1 && (calls["keepAwake.current?.stop"] ?? 0) >= 1, "stopped on sign-out and on unmount");
  assert.ok(!idents.has("setInterval"), "a second timer in AuthContext is a second keep-alive");
  const text = read("lib/auth/AuthContext.tsx");
  assert.doesNotMatch(text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, ""), /\/health/,
    "the /health URL belongs to lib/api/keepAwake, the one place that knows it");
  // It is keyed on whether somebody is signed in, so a sign-out (a state change, not an unmount) stops it.
  assert.match(text, /const signedIn = user !== null;[\s\S]*?\[signedIn\]\);/);
});

test("keepAwake is the only place that builds the API's /health URL", () => {
  const offenders: string[] = [];
  const visit = (dir: string) => {
    for (const name of readdirSync(dir)) {
      if (name === "node_modules" || name === ".next" || name === "out" || name.startsWith(".")) continue;
      const full = join(dir, name);
      if (statSync(full).isDirectory()) { visit(full); continue; }
      if (!/\.tsx?$/.test(name) || /\.test\.ts$/.test(name)) continue;
      const code = readFileSync(full, "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
      // A template that starts at the API's own base and ends in /health. A page link to the Client health screen,
      // or a route that ends in /health under some client id, is not it.
      if (/`\$\{(apiBase|base|BASE_URL|process\.env\.NEXT_PUBLIC_API_URL[^}]*)\}\/health`/.test(code)) offenders.push(relative(WEB, full));
    }
  };
  for (const d of ["app", "components", "lib"]) visit(join(WEB, d));
  assert.deepEqual(offenders, ["lib/api/keepAwake.ts"]);
});
