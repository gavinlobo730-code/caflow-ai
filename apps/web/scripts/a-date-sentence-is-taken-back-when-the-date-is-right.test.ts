// A DATE'S SENTENCE A FORM SAYS IS TAKEN BACK WHEN THE DATE IS RIGHT (POST-A-381).
//   node --experimental-strip-types --test scripts/a-date-sentence-is-taken-back-when-the-date-is-right.test.ts
//
// THE DEFECT
//   A date box tells its form, through `useDateProblems`, that the text in it is not a date (or is a day the box refuses). A Save over
//   such a box copied the sentence into the form's own error, `if (dates.first) { setError(dates.first); return; }`, and the form's error
//   is cleared by the NEXT attempt and nothing else. So the person corrected the date and the red sentence stayed: the screen said the
//   date was wrong about a date that was right, and the person pressed Save again for nothing. On 16-11-2026 that was 80 copies on 60
//   screens, among them the purchase bill and sales invoice editors, the GST, MCA, income-tax and payroll screens and the DSC tracker.
//
// THE FIX
//   `useDateProblems().refuseWith(setError)` says the first sentence through the form's own message and TAKES IT BACK when that
//   sentence stops being a problem (the date is right, blank where it may be, or wrong for another reason the box now says). What it
//   said is compared by identity, so an answer the form shows in the same place afterwards (the server's refusal, the next attempt's
//   own sentence) is never taken back. A message that is an object takes a `wrap`, and a message whose empty value is "" says so.
//
// THE RULE (as source, over every screen): no call takes a date hook's `.first` and keeps it (a setter, a callback to the page, a note);
// it is said through `refuseWith` or the `useDateRefusal` latch. The exceptions are named below with why they cannot linger: a toast,
// which goes by itself, and the computations that run on their own as the boxes change (a debounced figure).
import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import ts from "typescript";
import { loadModuleWithReact } from "./tsxHarness.ts";

const WEB = join(import.meta.dirname, "..");
const read = (rel: string) => readFileSync(join(WEB, rel), "utf8");

/**
 * Where a date hook's sentence is handed on as it is, by file: the call that takes it and why that cannot linger. A toast goes by itself; a
 * computation that runs on its own as the boxes change sets its error again, or clears it, on every change.
 */
const HANDED_ON: Record<string, { sinks: string[]; why: string }> = {
  "app/income-tax/advance-tax/page.tsx": { sinks: ["setComputeError", "setLateError"], why: "the figures and the late interest are computed on their own as the boxes change (debounced effects), so the error is set again, or cleared, on every change" },
  "app/income-tax/capital-gains/page.tsx": { sinks: ["setComputeError"], why: "the gain is computed on its own as the boxes change (a debounced effect), so the error is set again, or cleared, on every change" },
  "app/client-portal/page.tsx": { sinks: ["toast"], why: "a toast, which goes by itself" },
  "app/clients/[id]/tax/filing/page.tsx": { sinks: ["toast"], why: "a toast, which goes by itself" },
  "components/invoices/InvoiceViewDrawer.tsx": { sinks: ["onError", "onError", "onError"], why: "each panel hands it to the page's toast, which goes by itself" },
  "components/purchases/PurchaseBillViewDrawer.tsx": { sinks: ["onError", "onError", "onError"], why: "each panel hands it to the drawer's toast, which goes by itself" },
};

/** Calls that take a date hook's sentence and are built to withdraw it: the latch, and refuseWith (which takes the setter, not the sentence). */
const WITHDRAWS = new Set(["useDateRefusal"]);

function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(join(WEB, dir))) {
    if (name === "node_modules" || name === ".next" || name === "out" || name.startsWith(".")) continue;
    const rel = `${dir}/${name}`;
    if (statSync(join(WEB, rel)).isDirectory()) out.push(...sourceFiles(rel));
    else if (/\.tsx?$/.test(rel) && !/\.test\.tsx?$/.test(rel)) out.push(rel);
  }
  return out;
}

/** In one file: the names bound to `useDateProblems()`, the setters that take one of them's `.first`, and the `refuseWith` calls. */
export function copiesIn(rel: string, text: string): { hooks: string[]; copies: { hook: string; setter: string; line: number }[]; refusals: number } {
  const sf = ts.createSourceFile(rel, text, ts.ScriptTarget.Latest, true, rel.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const hooks = new Set<string>();
  const findHooks = (n: ts.Node) => {
    if (ts.isVariableDeclaration(n) && ts.isIdentifier(n.name) && n.initializer && ts.isCallExpression(n.initializer)
      && n.initializer.expression.getText(sf) === "useDateProblems") hooks.add(n.name.text);
    ts.forEachChild(n, findHooks);
  };
  findHooks(sf);
  const copies: { hook: string; setter: string; line: number }[] = [];
  let refusals = 0;
  const visit = (n: ts.Node) => {
    if (ts.isCallExpression(n) && ts.isPropertyAccessExpression(n.expression) && n.expression.name.text === "refuseWith"
      && hooks.has(n.expression.expression.getText(sf))) refusals++;
    if (ts.isPropertyAccessExpression(n) && n.name.text === "first" && hooks.has(n.expression.getText(sf))) handedOn(n, n.expression.getText(sf), 0);
    ts.forEachChild(n, visit);
  };
  const isFunction = (p: ts.Node) => ts.isArrowFunction(p) || ts.isFunctionExpression(p) || ts.isFunctionDeclaration(p) || ts.isMethodDeclaration(p);
  /**
   * The call this sentence is handed to: the nearest call whose ARGUMENTS hold it, without leaving the function it is written in. A
   * sentence first put in a variable (`const problem = ok ? dates.first : null; ... setError(problem)`) is followed to every place that
   * variable is read in the same function: the drive found the computation's loan date spelt that way, which the first rule did not see.
   */
  function handedOn(n: ts.Node, hook: string, depth: number) {
    for (let child: ts.Node = n, p = n.parent; p; child = p, p = p.parent) {
      if (isFunction(p)) break;
      if (ts.isVariableDeclaration(p) && child === p.initializer && ts.isIdentifier(p.name) && depth < 3) {
        const name = p.name.text;
        let scope: ts.Node = p;
        while (scope.parent && !isFunction(scope) && !ts.isSourceFile(scope)) scope = scope.parent;
        const uses = (u: ts.Node) => {
          if (ts.isIdentifier(u) && u.text === name && u !== p.name
            && !(ts.isPropertyAccessExpression(u.parent) && u.parent.name === u)) handedOn(u, hook, depth + 1);
          ts.forEachChild(u, uses);
        };
        uses(scope);
        break;
      }
      if (ts.isCallExpression(p) && p.arguments.some((a) => a === child)) {
        const callee = p.expression.getText(sf);
        // A hook's dependency list names the sentence to re-run when it changes; it says nothing.
        const deps = ts.isArrayLiteralExpression(child) && /^use(Effect|LayoutEffect|Memo|Callback)$/.test(callee);
        if (!deps && !WITHDRAWS.has(callee)) copies.push({ hook, setter: callee, line: sf.getLineAndCharacterOfPosition(p.getStart()).line + 1 });
        break;
      }
    }
  }
  visit(sf);
  return { hooks: [...hooks], copies, refusals };
}

const FILES = ["app", "components", "lib"].flatMap(sourceFiles);

test("no call takes a date hook's sentence and keeps it: it is said through refuseWith or the latch, which take it back", () => {
  const problems: string[] = [];
  const seen: Record<string, string[]> = {};
  for (const f of FILES) {
    for (const c of copiesIn(f, read(f)).copies) (seen[f] ??= []).push(`${c.setter}@${c.line}`);
  }
  for (const [f, found] of Object.entries(seen)) {
    const sinks = found.map((x) => x.split("@")[0]).sort();
    const listed = [...(HANDED_ON[f]?.sinks ?? [])].sort();
    if (JSON.stringify(sinks) !== JSON.stringify(listed)) {
      problems.push(`${f}: a date's sentence is handed to ${found.join(", ")}, where it stays after the date is put right; say it with refuseWith(set) or useDateRefusal${listed.length ? ` (the list names ${listed.join(", ")})` : ""}`);
    }
  }
  for (const f of Object.keys(HANDED_ON)) if (!seen[f]) problems.push(`${f} is on the list and hands no date sentence on any more: take it off`);
  assert.deepEqual(problems, []);
});

test("the walk is not vacuous: it finds the date hooks and the refusals said through them", () => {
  let hooks = 0, refusals = 0;
  for (const f of FILES) { const r = copiesIn(f, read(f)); hooks += r.hooks.length; refusals += r.refusals; }
  assert.ok(hooks > 60, `found only ${hooks} date hooks`);
  assert.ok(refusals >= 80, `found only ${refusals} refusals said through refuseWith`);
});

test("self-test: a copy, a copy inside an object, a refusal said through refuseWith, a callback, the latch, an effect, and a sentence put in a variable first", () => {
  const sample = `
    const dates = useDateProblems();
    function save() {
      if (dates.first) { setError(dates.first); return; }
      if (dates.first) { setMsg({ type: "err", text: dates.first }); return; }
      if (dates.first) { dates.refuseWith(setError); return; }
      setError(other.first);
      if (dates.first) { onError(dates.first); return; }
      const refusal = useDateRefusal(dates.first);
      useEffect(() => { if (dates.first) setLive(dates.first); }, [dates.first]);
      const problem = ready ? dates.first : null;
      if (problem) { setCompute(problem); return; }
      const latched = dates.first ?? missing;
      const held = useDateRefusal(latched);
    }`;
  const r = copiesIn("Sample.tsx", sample);
  assert.deepEqual(r.copies.map((c) => [c.setter, c.line]), [["setError", 4], ["setMsg", 5], ["onError", 8], ["setLive", 10], ["setCompute", 12]]);
  assert.equal(r.refusals, 1);
});

// ── the behaviour, run on the real hook ─────────────────────────────────────────────────────────────────────────────────

/** Just enough of React for one hook: state that persists, refs, callbacks, and effects that run after a render whose deps changed. */
function miniReact() {
  let slots: { value?: unknown; deps?: unknown[]; cleanup?: unknown; ran?: boolean }[] = [];
  let i = 0;
  let queue: { k: number; fn: () => unknown; deps?: unknown[] }[] = [];
  let again = false;
  const changed = (a?: unknown[], b?: unknown[]) => !a || !b || a.length !== b.length || a.some((x, j) => !Object.is(x, b[j]));
  const react = {
    useState<T>(init: T | (() => T)) {
      const k = i++;
      const slot = (slots[k] ??= { value: typeof init === "function" ? (init as () => T)() : init });
      const set = (v: T | ((p: T) => T)) => {
        const next = typeof v === "function" ? (v as (p: T) => T)(slot.value as T) : v;
        if (!Object.is(next, slot.value)) { slot.value = next; again = true; }
      };
      return [slot.value as T, set] as const;
    },
    useRef<T>(init: T) { const k = i++; return ((slots[k] ??= { value: { current: init } }).value) as { current: T }; },
    useCallback<T>(fn: T, deps: unknown[]) {
      const k = i++;
      const slot = (slots[k] ??= {});
      if (!slot.ran || changed(slot.deps, deps)) { slot.value = fn; slot.deps = deps; slot.ran = true; }
      return slot.value as T;
    },
    useEffect(fn: () => unknown, deps?: unknown[]) {
      const k = i++;
      const slot = (slots[k] ??= {});
      if (!slot.ran || changed(slot.deps, deps)) queue.push({ k, fn, deps });
      slot.ran = true;
    },
  };
  function mount<R>(render: () => R) {
    let result!: R;
    const settle = () => {
      for (let guard = 0; guard < 20; guard++) {
        again = false; i = 0; queue = [];
        result = render();
        for (const e of queue) { const s = slots[e.k]; if (typeof s.cleanup === "function") (s.cleanup as () => void)(); s.cleanup = e.fn(); s.deps = e.deps; }
        if (!again) return;
      }
      throw new Error("render loop");
    };
    settle();
    return { get result() { return result; }, refresh: settle, unmount() { slots = []; } };
  }
  return { react, mount };
}

type Listener = (state: { status: string; message?: string }) => void;
type TakenBack = <T>(set: (v: T | ((p: T) => T)) => void, said: T, stillTrue: boolean, empty?: T) => void;
type Hook = { watch: (k: string, l: string) => Listener; first: string | null; refuseWith: <T>(set: (v: T | ((p: T) => T)) => void, wrap?: (s: string) => T, empty?: T) => void };

function harness() {
  const { react, mount } = miniReact();
  const mod = loadModuleWithReact<{ useDateProblems: () => Hook }>("lib/dates/useDateProblems", react);
  // The form's own message is state of the same component, so a taken-back sentence re-renders it.
  let message: unknown = null;
  let setMessage!: (v: unknown) => void;
  const view = mount(() => {
    const [m, set] = react.useState<unknown>(null);
    message = m; setMessage = set as (v: unknown) => void;
    return mod.useDateProblems();
  });
  // `set` is the component's own setter, as a form hands it to refuseWith; `answer` is the form showing something else, then rendering.
  return { view, get message() { return message; }, get set() { return setMessage; }, answer: (v: unknown) => { setMessage(v); view.refresh(); } };
}

const UNREADABLE = { status: "invalid", message: "31/02/2026 is not a date." };
const READ = { status: "valid" };

test("a date's sentence is said on Save and taken back the moment the date is right", () => {
  const h = harness();
  const watch = h.view.result.watch("bill", "Bill date");
  watch(UNREADABLE); h.view.refresh();
  h.view.result.refuseWith(h.set as never); h.view.refresh();
  assert.equal(h.message, "Bill date: 31/02/2026 is not a date.");
  watch(READ); h.view.refresh();
  assert.equal(h.message, null, "the sentence stayed after the date was put right");
});

test("an answer the form showed after the sentence is never taken back", () => {
  const h = harness();
  const watch = h.view.result.watch("bill", "Bill date");
  watch(UNREADABLE); h.view.refresh();
  h.view.result.refuseWith(h.set as never); h.view.refresh();
  h.answer("The server refused: the period is locked.");
  watch(READ); h.view.refresh();
  assert.equal(h.message, "The server refused: the period is locked.");
});

test("while the date is still wrong the sentence stays, and an object message is taken back to its empty value", () => {
  const h = harness();
  const watch = h.view.result.watch("bill", "Bill date");
  watch(UNREADABLE); h.view.refresh();
  h.view.result.refuseWith(h.set as never, (text: string) => ({ type: "err", text }) as never, "" as never); h.view.refresh();
  assert.deepEqual(h.message, { type: "err", text: "Bill date: 31/02/2026 is not a date." });
  watch(UNREADABLE); h.view.refresh();
  assert.deepEqual(h.message, { type: "err", text: "Bill date: 31/02/2026 is not a date." }, "a date still wrong lost its sentence");
  watch(READ); h.view.refresh();
  assert.equal(h.message, "", "an object message is taken back to the empty value the form uses");
});

test("refuseWith says nothing when every date is a date", () => {
  const h = harness();
  h.view.result.watch("bill", "Bill date")(READ); h.view.refresh();
  h.view.result.refuseWith(h.set as never); h.view.refresh();
  assert.equal(h.message, null);
});

test("negative control: the purchase bill editor's old copy is named by the rule", () => {
  const rel = "components/purchases/PurchaseCycleTab.tsx";
  const text = read(rel);
  const old = text.replace(/(\w+)\.refuseWith\(setMsg, \(text\) => \(\{ type: "err" as const, text \}\)\)/, 'setMsg({ type: "err", text: $1.first })');
  assert.notEqual(old, text, "premise: the tab says a date's sentence through refuseWith");
  assert.equal(copiesIn(rel, old).copies.length, 1);
});

// ── a sentence a form says about its own two dates ────────────────────────────────────────────────────────────────────

test("an end-before-start sentence is taken back once the window is in order, and a later answer is kept", () => {
  const { react, mount } = miniReact();
  const mod = loadModuleWithReact<{ useTakenBackWhenFixed: TakenBack }>("lib/dates/useDateProblems", react);
  const ORDER = "The end date cannot be before the start date.";
  let reversed = true;
  let message: unknown = null;
  let set!: (v: unknown) => void;
  const view = mount(() => {
    const [m, s] = react.useState<unknown>(null);
    message = m; set = s as (v: unknown) => void;
    mod.useTakenBackWhenFixed(s as never, ORDER as never, reversed);
  });
  set(ORDER); view.refresh();
  assert.equal(message, ORDER, "said while the window is reversed");
  reversed = false; view.refresh();
  assert.equal(message, null, "the sentence stayed after the window was put in order");
  reversed = true; view.refresh();
  set("The server refused the template."); view.refresh();
  reversed = false; view.refresh();
  assert.equal(message, "The server refused the template.", "a later answer was taken back");
});

test("the journal and bill templates take their end-before-start sentence back", () => {
  for (const [rel, setter, cond] of [
    ["components/purchases/RecurringBills.tsx", "setErr", "!!endDate && endDate < startDate"],
    ["app/accounting/recurring/page.tsx", "setFormError", "!!form.end_date && form.end_date < form.start_date"],
  ] as const) {
    const src = read(rel);
    assert.ok(src.includes(`useTakenBackWhenFixed(${setter}, END_BEFORE_START, ${cond});`), `${rel}: the order sentence is not taken back when the window is put in order`);
    assert.ok(src.includes(`${setter}(END_BEFORE_START)`), `${rel}: the order sentence is not said through the named constant the take-back compares`);
  }
});

test("negative control: the payroll filing form's old hand-off to the page's note is named by the rule", () => {
  // Found by the browser drive, not by the first spelling of this rule (which looked only at setters): the form handed the sentence to
  // the page's note through `onError`, and the note stayed after the date was put right.
  const rel = "components/payroll/StatutoryHandoff.tsx";
  const text = read(rel);
  const old = text.replace("if (dates.first ?? missing) { refusal.refuse(); return; }", "if (dates.first) { onError(dates.first); return; }");
  assert.notEqual(old, text, "premise: the form says the date's sentence through the latch");
  assert.deepEqual(copiesIn(rel, old).copies.map((c) => c.setter), ["onError"]);
});

test("negative control: the computation's old loan-date copy, put in a variable before it was said, is named by the rule", () => {
  // Found by the browser drive, not by the second spelling of this rule (which followed the sentence only to the call it sits in): the
  // computation put the sentence in a variable first and said the variable, and the sentence stayed after the date was put right.
  const rel = "app/clients/[id]/tax/computation/page.tsx";
  const text = read(rel);
  const old = text.replace(
    'if (offers("s80ee") && sanctionDates.first) { sanctionDates.refuseWith(setComputeError); return; }',
    'const sanctionProblem = offers("s80ee") ? sanctionDates.first : null;\n    if (sanctionProblem) { setComputeError(sanctionProblem); return; }',
  );
  assert.notEqual(old, text, "premise: the computation says the loan date's sentence through refuseWith");
  assert.deepEqual(copiesIn(rel, old).copies.map((c) => c.setter), ["setComputeError"]);
});
