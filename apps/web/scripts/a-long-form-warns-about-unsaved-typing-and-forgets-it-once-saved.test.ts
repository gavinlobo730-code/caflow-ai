// THE LONG FORMS WARN BEFORE THEY LOSE TYPING, AND ONLY ABOUT TYPING THAT IS NOT SAVED (frontend_ux-23).
//   node --experimental-strip-types --test scripts/a-long-form-warns-about-unsaved-typing-and-forgets-it-once-saved.test.ts
//
// ─────────────────────────────────────────────────────────────────────────────
// THE DEFECT
// ─────────────────────────────────────────────────────────────────────────────
// `useUnsavedChanges` was on six document editors and on nothing else. The journal
// editor (the longest thing a CA types), the employee drawer (five forms behind one
// close button), the two asset drawers (a correction reverses and re-posts a real
// journal) and the onboarding wizard (the one form every new firm fills in) each
// threw typed work away on a backdrop click, Escape, Cancel, a section switch or a
// reload, without a word.
//
// ─────────────────────────────────────────────────────────────────────────────
// THE RULES THIS HOLDS
// ─────────────────────────────────────────────────────────────────────────────
//  1. Each long form calls `useUnsavedChanges` with a REAL dirty signal — not a
//     constant, and not only the saving flag.
//  2. Every way OUT of a drawer asks first. A drawer is left by a backdrop click,
//     a Close/Cancel button, Escape and (in the employee drawer) switching section;
//     a handler that reaches `onClose` without going through the guard is the
//     hole this change exists to shut.
//  3. A section of the employee drawer reports its dirtiness, and re-baselines
//     when its work is saved. A section that reported dirty and never said "saved"
//     would warn about changes that are already on the server — a warning people
//     learn to dismiss, which is the same as no warning.
//  4. (behaviour, through a minimal hook runner) a form is clean when it opens;
//     typing makes it dirty; typing back makes it clean; a SAVE makes it clean
//     against what the form holds on the NEXT render — not the last — because a
//     save handler clears fields in the same tick.
//
// Rules 1–3 read the TypeScript syntax tree, not a regex over source: a spelling
// such as `onClick={onClose}` is one of many ways to leave a drawer, so the check
// is "no click or key handler in this component names `onClose`".
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import ts from "typescript";
import { loadModuleWithReact } from "./tsxHarness.ts";

const WEB = join(import.meta.dirname, "..");

function parse(rel: string): ts.SourceFile {
  return ts.createSourceFile(rel, readFileSync(join(WEB, rel), "utf8"), ts.ScriptTarget.Latest, true,
    rel.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
}

/** Every function declaration in the file, by name. */
function functionsIn(sf: ts.SourceFile): Map<string, ts.FunctionDeclaration> {
  const out = new Map<string, ts.FunctionDeclaration>();
  sf.forEachChild((n) => { if (ts.isFunctionDeclaration(n) && n.name) out.set(n.name.text, n); });
  return out;
}

function walk(node: ts.Node, visit: (n: ts.Node) => void): void {
  visit(node);
  node.forEachChild((c) => walk(c, visit));
}

function callsTo(node: ts.Node, name: string): ts.CallExpression[] {
  const out: ts.CallExpression[] = [];
  walk(node, (n) => {
    if (ts.isCallExpression(n) && ts.isIdentifier(n.expression) && n.expression.text === name) out.push(n);
  });
  return out;
}

const mentions = (node: ts.Node, name: string): boolean => {
  let found = false;
  walk(node, (n) => { if (ts.isIdentifier(n) && n.text === name) found = true; });
  return found;
};

// ═════════════════════════════════════════════════════════════════════════════
// 1. A REAL DIRTY SIGNAL
// ═════════════════════════════════════════════════════════════════════════════

/** Every long form that must warn. FROZEN in the sense that a form added here
 *  is a decision; the six document editors that already did are covered by
 *  their own tests. */
const FORMS: { file: string; components: string[] }[] = [
  { file: "components/journal/JournalEditor.tsx", components: ["JournalEditor"] },
  { file: "components/purchases/PurchaseBillEditor.tsx", components: ["PurchaseBillEditor"] },
  { file: "components/payroll/EmployeeDrawer.tsx", components: ["EmployeeDrawer"] },
  { file: "app/clients/[id]/fixed-assets/page.tsx", components: ["AddAssetDrawer", "CorrectAssetDrawer"] },
  { file: "app/onboarding/page.tsx", components: ["OnboardingPage"] },
];

for (const form of FORMS) {
  for (const component of form.components) {
    test(`${component} calls useUnsavedChanges with a signal that can be false`, () => {
      const fn = functionsIn(parse(form.file)).get(component);
      assert.ok(fn, `${component} not found in ${form.file}`);
      const calls = callsTo(fn, "useUnsavedChanges");
      assert.equal(calls.length, 1, `${component} must call useUnsavedChanges exactly once`);
      const [dirtyArg, , confirmArg] = calls[0].arguments;
      assert.ok(dirtyArg, "no dirty argument");
      assert.ok(dirtyArg.kind !== ts.SyntaxKind.TrueKeyword && dirtyArg.kind !== ts.SyntaxKind.FalseKeyword,
        "a literal true/false is not a dirty signal");
      // It has to depend on something typed, not on the saving flag alone.
      const ids: string[] = [];
      walk(dirtyArg, (n) => { if (ts.isIdentifier(n)) ids.push(n.text); });
      assert.ok(ids.some((i) => i !== "saving" && i !== "busy"),
        `the signal "${dirtyArg.getText()}" names nothing that was typed`);
      assert.ok(confirmArg && confirmArg.getText() === "confirmDialog",
        "the leave question is the in-app dialog (a native confirm is refused by no-alert)");
    });
  }
}

// ═════════════════════════════════════════════════════════════════════════════
// 2. EVERY WAY OUT OF A DRAWER ASKS FIRST
// ═════════════════════════════════════════════════════════════════════════════

const DRAWERS: { file: string; component: string }[] = [
  { file: "components/payroll/EmployeeDrawer.tsx", component: "EmployeeDrawer" },
  { file: "app/clients/[id]/fixed-assets/page.tsx", component: "AddAssetDrawer" },
  { file: "app/clients/[id]/fixed-assets/page.tsx", component: "CorrectAssetDrawer" },
];

/** Handler-valued JSX attributes and listener registrations that run on a
 *  person's gesture. A SAVE finishing is not one, and calls `onClose` itself. */
function gestureHandlers(fn: ts.FunctionDeclaration): ts.Node[] {
  const out: ts.Node[] = [];
  walk(fn, (n) => {
    if (ts.isJsxAttribute(n) && /^on(Click|KeyDown|KeyUp|Submit)$/.test(n.name.getText()) && n.initializer) {
      out.push(n.initializer);
    }
    // document.addEventListener("keydown", handler)
    if (ts.isCallExpression(n) && ts.isPropertyAccessExpression(n.expression)
        && n.expression.name.text === "addEventListener") {
      out.push(...n.arguments.slice(1));
    }
  });
  return out;
}

for (const d of DRAWERS) {
  test(`${d.component}: no click or key handler reaches onClose except through the guard`, () => {
    const fn = functionsIn(parse(d.file)).get(d.component);
    assert.ok(fn, `${d.component} not found`);
    const handlers = gestureHandlers(fn);
    assert.ok(handlers.length >= 3, `found only ${handlers.length} gesture handlers — the walk is vacuous`);
    const offenders = handlers.filter((h) => mentions(h, "onClose")).map((h) => h.getText().slice(0, 80));
    assert.deepEqual(offenders, [],
      "a handler that names onClose bypasses the leave question — go through the guard");
  });

  test(`${d.component}: the guard it goes through is built on confirmLeave`, () => {
    const fn = functionsIn(parse(d.file)).get(d.component) as ts.FunctionDeclaration;
    const guardNames = ["leave", "requestClose", "guarded"];
    const defined = guardNames.filter((g) => {
      let hit = false;
      walk(fn, (n) => {
        if (ts.isVariableDeclaration(n) && ts.isIdentifier(n.name) && n.name.text === g
            && n.initializer && mentions(n.initializer, "confirmLeave")) hit = true;
      });
      return hit;
    });
    assert.ok(defined.length >= 1, `${d.component} defines no guard that asks confirmLeave()`);
  });
}

test("EmployeeDrawer: switching section asks too, and Escape asks once, not twice", () => {
  const src = readFileSync(join(WEB, "components/payroll/EmployeeDrawer.tsx"), "utf8");
  assert.match(src, /setSection\(s\.key\)/, "premise: the section tabs still exist");
  const fn = functionsIn(parse("components/payroll/EmployeeDrawer.tsx")).get("EmployeeDrawer") as ts.FunctionDeclaration;
  // Every `setSection(...)` call that is a gesture sits inside the guard.
  const tabs: ts.CallExpression[] = callsTo(fn, "setSection");
  assert.ok(tabs.length >= 1);
  for (const call of tabs) {
    let guarded = false;
    for (let p: ts.Node | undefined = call.parent; p && p !== fn; p = p.parent) {
      if (ts.isCallExpression(p) && ts.isIdentifier(p.expression) && p.expression.text === "guarded") guarded = true;
    }
    assert.ok(guarded, `${call.getText()} changes section without asking`);
  }
  // The dialog that asks is itself dismissed with Escape, so the drawer's own
  // Escape listener must not start a second question while one is open.
  assert.match(src, /asking\s*=\s*useRef\(false\)/);
  assert.match(src, /if \(asking\.current\) return;/);
});

// ═════════════════════════════════════════════════════════════════════════════
// 3. EVERY SECTION OF THE EMPLOYEE DRAWER REPORTS, AND RE-BASELINES ON SAVE
// ═════════════════════════════════════════════════════════════════════════════

/** A section that persists NOTHING has no save to re-baseline on. Named, with
 *  its reason, and checked: it must call exactly one `api.` method. */
const WORKSHEETS: Record<string, { reason: string; onlyCall: string }> = {
  ReliefSection: {
    reason: "computes §89 relief and keeps nothing — nothing is ever saved",
    onlyCall: "arrearsRelief",
  },
};

test("every *Section in the employee drawer reports dirtiness and says when it was saved", () => {
  const sections = [...functionsIn(parse("components/payroll/EmployeeDrawer.tsx"))]
    .filter(([name]) => /Section$/.test(name));
  assert.ok(sections.length >= 6, `found ${sections.length} sections; the drawer has six`);
  for (const [name, fn] of sections) {
    assert.equal(callsTo(fn, "useDirtyFields").length, 1, `${name} keeps no dirty baseline`);
    assert.equal(callsTo(fn, "useReportDirty").length, 1, `${name} never tells the drawer it is dirty`);
    const worksheet = WORKSHEETS[name];
    if (worksheet) continue; // asserted below
    assert.ok(callsTo(fn, "markSaved").length >= 1,
      `${name} never re-baselines: it would warn about changes already saved`);
  }
});

test("a section exempt from markSaved really persists nothing", () => {
  const fns = functionsIn(parse("components/payroll/EmployeeDrawer.tsx"));
  for (const [name, w] of Object.entries(WORKSHEETS)) {
    const fn = fns.get(name);
    assert.ok(fn, `${name} (${w.reason}) no longer exists — remove it from WORKSHEETS`);
    const apiCalls: string[] = [];
    walk(fn, (n) => {
      if (ts.isCallExpression(n) && ts.isPropertyAccessExpression(n.expression)) {
        const text = n.expression.getText();
        if (/^api\./.test(text)) apiCalls.push(n.expression.name.text);
      }
    });
    assert.deepEqual([...new Set(apiCalls)], [w.onlyCall],
      `${name} is exempt from markSaved because it ${w.reason}; it now calls ${apiCalls.join(", ")}`);
    assert.equal(callsTo(fn, "markSaved").length, 0, `${name} has nothing to mark saved`);
  }
});

test("a section's markSaved() runs only after its request succeeded, never in a catch", () => {
  const sections = [...functionsIn(parse("components/payroll/EmployeeDrawer.tsx"))]
    .filter(([name]) => /Section$/.test(name));
  for (const [name, fn] of sections) {
    for (const call of callsTo(fn, "markSaved")) {
      for (let p: ts.Node | undefined = call.parent; p && p !== fn; p = p.parent) {
        assert.ok(!ts.isCatchClause(p), `${name}: markSaved() inside a catch re-baselines a FAILED save`);
        if (ts.isTryStatement(p) && p.finallyBlock) {
          assert.ok(!(call.pos >= p.finallyBlock.pos && call.end <= p.finallyBlock.end),
            `${name}: markSaved() inside a finally re-baselines a FAILED save`);
        }
      }
    }
  }
});

/** State that is not something a person typed: a request in flight, an answer,
 *  a list read from the server. Everything else in a section is a form field. */
const NOT_TYPED = new Set(["busy", "err", "done", "loading", "result", "rows", "notes", "confirming"]);

test("no field a person types into is left out of its section's dirty baseline", () => {
  // A section that grows a new input and forgets to list it would warn about
  // everything except that input — and the one nobody checked is the one lost.
  const sections = [...functionsIn(parse("components/payroll/EmployeeDrawer.tsx"))]
    .filter(([name]) => /Section$/.test(name));
  assert.ok(sections.length >= 6);
  for (const [name, fn] of sections) {
    const states: string[] = [];
    walk(fn, (n) => {
      if (ts.isVariableDeclaration(n) && ts.isArrayBindingPattern(n.name) && n.initializer
          && ts.isCallExpression(n.initializer) && n.initializer.expression.getText() === "useState") {
        const first = n.name.elements[0];
        if (first && ts.isBindingElement(first) && ts.isIdentifier(first.name)) states.push(first.name.text);
      }
    });
    const [fields] = callsTo(fn, "useDirtyFields")[0].arguments;
    assert.ok(ts.isObjectLiteralExpression(fields), `${name}: useDirtyFields takes an object literal`);
    const watched = new Set(fields.properties.map((p) => (p.name ? p.name.getText() : "")));
    const typed = states.filter((s) => !NOT_TYPED.has(s));
    assert.ok(typed.length >= 4, `${name}: found only ${typed.length} form fields — the walk is vacuous`);
    const unwatched = typed.filter((s) => !watched.has(s));
    assert.deepEqual(unwatched, [],
      `${name}: typed into but not in the dirty baseline: ${unwatched.join(", ")} (add it, or name it in NOT_TYPED if nobody types it)`);
  }
});

test("the asset drawers watch everything except what the category list fills in", () => {
  const fns = functionsIn(parse("app/clients/[id]/fixed-assets/page.tsx"));
  const add = fns.get("AddAssetDrawer") as ts.FunctionDeclaration;
  const call = callsTo(add, "useDirtyFields")[0];
  const [arg] = call.arguments;
  // It names what to leave OUT, so a field added to the form later is watched.
  assert.ok(ts.isCallExpression(arg) && arg.expression.getText() === "omitKeys",
    "the baseline must be `omitKeys(form, [...])`, not a list of the fields to watch");
  assert.equal(arg.arguments[0].getText(), "form");
  const left = (arg.arguments[1] as ts.ArrayLiteralExpression).elements.map((e) => (e as ts.StringLiteral).text);
  // The category list arrives from the server and pre-selects a row, which fills
  // these four in; counting them would make the drawer dirty the moment it loaded.
  assert.deepEqual([...left].sort(),
    ["asset_category", "schedule_ii_class", "useful_life_years", "wdv_rate_percent"]);
  // …and each of them really is filled by `applyClass`, not typed. If a key is
  // removed from that function it no longer belongs in the exclusion.
  const apply = /const applyClass = useCallback\(([\s\S]*?)\}, \[\]\);/.exec(
    readFileSync(join(WEB, "app/clients/[id]/fixed-assets/page.tsx"), "utf8"))?.[1] ?? "";
  for (const k of left) assert.match(apply, new RegExp(`\\b${k}\\b`), `${k} is not set by applyClass`);
});

// ═════════════════════════════════════════════════════════════════════════════
// 4. THE BEHAVIOUR, THROUGH A MINIMAL HOOK RUNNER
// ═════════════════════════════════════════════════════════════════════════════
//
// A server render runs each hook once and never re-renders, so it cannot show a
// form becoming dirty. This is a ~40-line stand-in for the four hooks the two
// modules use — useState, useEffect, useCallback and nothing else — with real
// semantics for the parts that matter here: state persists across renders, an
// effect runs after a render whose dependencies changed, an effect's cleanup runs
// before its next run and on unmount, and a state change made by an effect
// re-renders.

interface Slot { value?: unknown; deps?: unknown[]; cleanup?: (() => void) | void; fn?: unknown }

function miniReact() {
  let slots: Slot[] = [];
  let i = 0;
  let queue: { k: number; fn: () => void | (() => void); deps?: unknown[] }[] = [];
  let again = false;
  const depsChanged = (a?: unknown[], b?: unknown[]) =>
    !a || !b || a.length !== b.length || a.some((x, j) => !Object.is(x, b[j]));
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
      if (slot.fn === undefined || depsChanged(slot.deps, deps)) queue.push({ k, fn, deps });
      slot.fn = true;
    },
    useCallback<T>(fn: T, deps: unknown[]): T {
      const k = i++;
      const slot = (slots[k] ??= {});
      if (slot.fn === undefined || depsChanged(slot.deps, deps)) { slot.value = fn; slot.deps = deps; slot.fn = true; }
      return slot.value as T;
    },
  };
  /** Run `hook(props)` as a component would: render, run the effects it queued,
   *  and render again while they changed state. */
  function mount<P, R>(hook: (p: P) => R, initial: P) {
    let props = initial;
    let result!: R;
    const settle = () => {
      for (let guard = 0; guard < 20; guard++) {
        again = false; i = 0; queue = [];
        result = hook(props);
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
      /** Re-render with the same props, after something outside changed state. */
      refresh() { settle(); },
      unmount() {
        for (const s of slots) if (typeof s.cleanup === "function") s.cleanup();
        slots = [];
      },
    };
  }
  return { react, mount };
}

type Mod = {
  useDirtyFields: <T>(f: T) => { dirty: boolean; markSaved: () => void };
  useReportDirty: (report: (d: boolean) => void, dirty: boolean) => void;
  omitKeys: <T extends object, K extends keyof T>(o: T, keys: readonly K[]) => Omit<T, K>;
};

function load() {
  const rt = miniReact();
  const mod = loadModuleWithReact<Mod>("lib/forms/useDirtyFields", rt.react);
  return { ...rt, ...mod };
}

test("a form is clean when it opens, dirty once typed into, and clean again when typed back", () => {
  const { mount, useDirtyFields } = load();
  const h = mount((f: { basic: string }) => useDirtyFields(f), { basic: "50000" });
  assert.equal(h.result.dirty, false, "an untouched form must not warn");
  h.rerender({ basic: "55000" });
  assert.equal(h.result.dirty, true);
  h.rerender({ basic: "50000" });
  assert.equal(h.result.dirty, false, "typing back to what it opened with is not a change");
});

test("a SAVE makes the form clean against what it holds on the NEXT render", () => {
  const { mount, useDirtyFields } = load();
  const h = mount((f: { basic: string; reason: string }) => useDirtyFields(f), { basic: "", reason: "" });
  h.rerender({ basic: "62000", reason: "Annual increment" });
  assert.equal(h.result.dirty, true);

  // The save handler: record, then clear the form in the same tick.
  h.result.markSaved();
  h.rerender({ basic: "", reason: "" });
  assert.equal(h.result.dirty, false,
    "the freshly emptied form must not be 'dirty' — adopting the pre-clear values as the baseline would warn on a clean form");
  h.rerender({ basic: "70000", reason: "" });
  assert.equal(h.result.dirty, true, "typing after a save is unsaved again");
});

test("a save that leaves the form as typed is clean too", () => {
  const { mount, useDirtyFields } = load();
  const h = mount((f: { pan: string }) => useDirtyFields(f), { pan: "ABCDE1234F" });
  h.rerender({ pan: "ABCDE1234G" });
  assert.equal(h.result.dirty, true);
  h.result.markSaved();
  h.rerender({ pan: "ABCDE1234G" });
  assert.equal(h.result.dirty, false, "a Profile saved and left open has nothing unsaved");
});

test("omitKeys drops exactly the named keys and keeps a field added later", () => {
  const { omitKeys, mount, useDirtyFields } = load();
  const form = { asset_name: "", asset_category: "", wdv_rate_percent: "", purchase_cost_paise: "" };
  assert.deepEqual(omitKeys(form, ["asset_category", "wdv_rate_percent"]), { asset_name: "", purchase_cost_paise: "" });
  assert.deepEqual(form, { asset_name: "", asset_category: "", wdv_rate_percent: "", purchase_cost_paise: "" },
    "the form itself is not mutated");

  // The category list filling its fields in after the drawer opens is not typing…
  const h = mount((f: typeof form) => useDirtyFields(omitKeys(f, ["asset_category", "wdv_rate_percent"])), form);
  h.rerender({ ...form, asset_category: "Plant and machinery", wdv_rate_percent: "18.1" });
  assert.equal(h.result.dirty, false, "the drawer must not be dirty the instant its categories arrive");
  // …and a person typing is, including into a field added to the form after this was written.
  h.rerender({ ...form, asset_category: "Plant and machinery", purchase_cost_paise: "1,50,000" });
  assert.equal(h.result.dirty, true);
  const later = { ...form, brand_new_field: "" };
  const g = mount((f: typeof later) => useDirtyFields(omitKeys(f, ["asset_category"])), later);
  g.rerender({ ...later, brand_new_field: "typed" });
  assert.equal(g.result.dirty, true, "a field nobody listed is still guarded");
});

test("useReportDirty tells the drawer, and says clean when the section goes away", () => {
  const { mount, useReportDirty } = load();
  const told: boolean[] = [];
  const report = (d: boolean) => { told.push(d); };
  const h = mount((p: { dirty: boolean }) => useReportDirty(report, p.dirty), { dirty: false });
  h.rerender({ dirty: true });
  h.rerender({ dirty: false });
  h.rerender({ dirty: true });
  assert.deepEqual(told, [false, true, false, true]);
  h.unmount();
  assert.equal(told[told.length - 1], false,
    "switching section unmounts one; leaving 'dirty' behind would make the next section ask about it");
});
