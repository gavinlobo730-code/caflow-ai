/**
 * Render a real component from this repository under plain `node --test`, with
 * no DOM and no bundler — and capture what it hands to the host elements.
 *
 * WHY THIS EXISTS
 *     There is no browser harness in this repository (no Playwright browsers, no
 *     jsdom), and most of the guards in `scripts/` read SOURCE: they prove a
 *     property is written, not that it works. For a click guard that is not
 *     enough — the defect was a handler that ran twice — so this loads the
 *     actual `button.tsx` and `data-table.tsx`, renders them with
 *     `react-dom/server`, and lets a test CALL the `onClick` / `onKeyDown` the
 *     component produced, the way the browser would.
 *
 * HOW
 *     TypeScript's own `transpileModule` turns each `.ts`/`.tsx` file into
 *     CommonJS on demand (the `@/` alias and relative imports are resolved
 *     here; packages come from this app's `node_modules`). `react/jsx-runtime`
 *     is replaced by a wrapper that records the props of every HOST element
 *     (`"button"`, `"tr"`, …) as it is created, so a test can pick the handler
 *     the component attached and invoke it with a fake event.
 *
 * WHAT IT IS NOT
 *     It is a server render: effects never run, nothing is painted, focus does
 *     not move and `useSyncExternalStore` answers its server snapshot. What it
 *     proves is the logic a click or a key press reaches — which handler is
 *     attached, whether a second call is ignored, what an event's target does —
 *     not that a real browser dispatches one. A click-through is still owed.
 *
 * Not a .test.ts on purpose: every test that renders a component imports it.
 */
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import ts from "typescript";

const WEB = path.resolve(import.meta.dirname, "..");
const requireFromWeb = createRequire(path.join(WEB, "package.json"));

export interface RecordedElement {
  type: string;
  props: Record<string, unknown>;
}

const recorded: RecordedElement[] = [];

/** Host elements created since the last `startRecording()`. */
export function startRecording(): RecordedElement[] {
  recorded.length = 0;
  return recorded;
}

/** One load graph. The default one is shared by every `loadModule` call in a
 *  test process; `loadModuleWithReact` makes a private one, because a module
 *  keeps the `react` it was first given. */
interface LoadContext {
  modules: Map<string, unknown>;
  react: Record<string, unknown> | null;
}
const defaultContext: LoadContext = { modules: new Map(), react: null };

function candidates(base: string): string[] {
  return [base, `${base}.ts`, `${base}.tsx`, path.join(base, "index.ts"), path.join(base, "index.tsx")];
}

function resolveFile(spec: string, fromDir: string): string | null {
  const base = spec.startsWith("@/") ? path.join(WEB, spec.slice(2))
    : spec.startsWith(".") ? path.resolve(fromDir, spec)
    : null;
  if (!base) return null;
  for (const c of candidates(base)) {
    if (fs.existsSync(c) && fs.statSync(c).isFile()) return c;
  }
  return null;
}

/** `react`, with ONE hook answering as it does in a browser.
 *
 *  `react-dom/server` always gives `useSyncExternalStore` its SERVER snapshot,
 *  which for a subscribable like the click guard is always "idle" — so a test
 *  could never see a button render as busy. A client render reads the current
 *  snapshot, so that is what app modules get here. Nothing else in React is
 *  changed, and `react-dom/server` itself still uses the real one. */
function clientReact(): Record<string, unknown> {
  const real = requireFromWeb("react") as Record<string, unknown>;
  return {
    ...real,
    default: real,
    useSyncExternalStore: (_subscribe: unknown, getSnapshot: () => unknown) => getSnapshot(),
  };
}

/** A `react/jsx-runtime` that records the props of host elements. */
function recordingRuntime(): Record<string, unknown> {
  const real = requireFromWeb("react/jsx-runtime") as {
    jsx: (...a: unknown[]) => unknown; jsxs: (...a: unknown[]) => unknown; Fragment: unknown;
  };
  const wrap = (fn: (...a: unknown[]) => unknown) => (type: unknown, props: Record<string, unknown>, ...rest: unknown[]) => {
    if (typeof type === "string") recorded.push({ type, props });
    return fn(type, props, ...rest);
  };
  return { Fragment: real.Fragment, jsx: wrap(real.jsx), jsxs: wrap(real.jsxs) };
}

function load(file: string, ctx: LoadContext): unknown {
  const { modules } = ctx;
  const cached = modules.get(file);
  if (cached) return cached;
  const source = fs.readFileSync(file, "utf8");
  const out = ts.transpileModule(source, {
    fileName: file,
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      jsx: ts.JsxEmit.ReactJSX,
      esModuleInterop: true,
      allowImportingTsExtensions: true,
    },
  }).outputText;
  const mod: { exports: Record<string, unknown> } = { exports: {} };
  modules.set(file, mod.exports);
  const dir = path.dirname(file);
  const localRequire = (spec: string): unknown => {
    if (spec === "react/jsx-runtime" || spec === "react/jsx-dev-runtime") return recordingRuntime();
    if (spec === "react") return ctx.react ?? clientReact();
    const resolved = resolveFile(spec, dir);
    if (resolved) return load(resolved, ctx);
    return requireFromWeb(spec);
  };
  // eslint-disable-next-line no-new-func
  new Function("exports", "require", "module", "__filename", "__dirname", out)(
    mod.exports, localRequire, mod, file, dir,
  );
  modules.set(file, mod.exports);
  return mod.exports;
}

/** Load a module of this app by its `@/`-style path, e.g. `components/ui/button`. */
export function loadModule<T = Record<string, unknown>>(appPath: string): T {
  const file = resolveFile(`@/${appPath}`, WEB);
  if (!file) throw new Error(`cannot resolve ${appPath}`);
  return load(file, defaultContext) as T;
}

/** Load a module of this app, and everything it imports, against a `react` the
 *  test supplies — for a hook, whose behaviour across renders a one-shot server
 *  render cannot show. The graph is private: nothing it loads is shared with
 *  `loadModule`'s, and nothing loaded there is reused here. */
export function loadModuleWithReact<T = Record<string, unknown>>(
  appPath: string, react: Record<string, unknown>,
): T {
  const file = resolveFile(`@/${appPath}`, WEB);
  if (!file) throw new Error(`cannot resolve ${appPath}`);
  return load(file, { modules: new Map(), react: { ...react, default: react } }) as T;
}

/** The recorded host elements of a given type, in creation order. */
export function hostElements(type: string): RecordedElement[] {
  return recorded.filter((r) => r.type === type);
}

export { requireFromWeb };
