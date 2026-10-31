// AN OVERLAY'S FOCUS EFFECT RUNS WHEN IT OPENS AND CLOSES, NOT WHEN ITS PARENT RENDERS (POST-A-126 review).
//
// `components/ui/modal.tsx` and `components/ui/drawer.tsx` move focus to the first field when they open and give it back to the opener when
// they close, and they listen for Escape. The effect depended on `onClose`, and nearly every caller passes an inline arrow, so a new function
// arrived on EVERY render of the parent: the cleanup handed focus back to the opener and the setup moved it to the first field. A parent that
// re-rendered while the person was in a LATER field pulled the cursor away. It went unseen while the state lived in the overlay's own
// children, and showed when a date box (which commits on blur and so re-renders its parent exactly when the person tabs away) sat in a modal
// whose parent owned the date: the first Tab after typing a date did not leave the box.
//
// The rule, not a spelling of it: in each overlay, every effect that moves focus must have a dependency list that does not name `onClose`,
// and its body must not call `onClose` in ANY spelling (`onClose()`, `onClose?.()`, `props.onClose()`, `onClose.call(...)`): the only way
// to the latest one is through the ref that is assigned on every render. A call inside a `[]` effect would be to the one from the first
// render, which is the stale-closure bug the ref exists to avoid.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const OVERLAYS = ["components/ui/modal.tsx", "components/ui/drawer.tsx"];

function source(file: string): string {
  return readFileSync(join(import.meta.dirname, "..", file), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/(^|[^:])\/\/[^\n]*/g, "$1 ");
}

/** Every `useEffect(...)` in the source, as its body and its dependency list (null when it has none). */
function effects(src: string): { body: string; deps: string | null }[] {
  const out: { body: string; deps: string | null }[] = [];
  let from = 0;
  for (;;) {
    const start = src.indexOf("useEffect(", from);
    if (start < 0) return out;
    let depth = 0, i = start + "useEffect".length;
    for (; i < src.length; i++) {
      if (src[i] === "(") depth++;
      else if (src[i] === ")") { depth--; if (depth === 0) break; }
    }
    const call = src.slice(start, i + 1);
    const m = /,\s*(\[[^\]]*\])\s*\)$/.exec(call);
    out.push({ body: call, deps: m ? m[1] : null });
    from = i + 1;
  }
}

/** What is wrong with the focus effects of one overlay's source, as sentences (empty when it is right). */
function problems(src: string): string[] {
  const found: string[] = [];
  const focusing = effects(src).filter((e) => /\.focus\s*\(/.test(e.body));
  if (!focusing.length) found.push("no effect moves focus: the detector is looking at the wrong thing");
  for (const e of focusing) {
    if (e.deps === null) found.push("a focus effect has no dependency list, so it runs on every render");
    else if (/\bonClose\b/.test(e.deps)) found.push(`a focus effect is re-run by a changed onClose (${e.deps})`);
    // Any mention of onClose that is not the ref: onClose(), onClose?.(), props.onClose(), onClose.call(...).
    if (/\bonClose\b(?!Ref)/.test(e.body)) found.push("a focus effect calls onClose without going through the ref");
  }
  if (!/onCloseRef\.current\s*=\s*onClose\b/.test(src)) found.push("onCloseRef is not assigned the latest onClose on every render");
  if (!/onCloseRef\.current\s*\(\s*\)/.test(src)) found.push("Escape does not call the latest onClose through the ref");
  return found;
}

for (const file of OVERLAYS) {
  test(`${file}: its focus effect is not re-run by a parent's new onClose, and Escape reaches the latest one`, () => {
    assert.deepEqual(problems(source(file)), []);
  });
}

test("the detector tells the old shapes from the new, in every spelling", () => {
  const ref = "const onCloseRef = useRef(onClose); onCloseRef.current = onClose;";
  const good = `${ref} useEffect(() => { restoreRef.current = x; el.focus(); function k(){ onCloseRef.current(); } }, []);`;
  assert.deepEqual(problems(good), []);
  // The old shape: onClose in the dependency list.
  assert.ok(problems(good.replace("}, []);", "}, [onClose]);")).some((p) => p.includes("re-run by a changed onClose")));
  // A bare call, an optional call, a property call and a .call(): each reads the first render's onClose in a [] effect.
  for (const spelling of ["onClose()", "onClose?.()", "props.onClose()", "onClose.call(null)"]) {
    const bad = good.replace("onCloseRef.current()", spelling);
    assert.ok(problems(bad).some((p) => p.includes("without going through the ref")), `${spelling} was not found`);
  }
  // No dependency list at all runs on every render.
  assert.ok(problems(good.replace("}, []);", "});")).some((p) => p.includes("no dependency list")));
  // Without the ref assignment the latest onClose is never read.
  assert.ok(problems(good.replace(ref, "")).some((p) => p.includes("onCloseRef is not assigned")));
});
