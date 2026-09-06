// Finds the shape the bank-import dialog had: two or more user-triggered
// actions in ONE component, where a button that starts one is not disabled
// while another is running.
//
// Two things make this narrow enough to be worth ratcheting, and the first
// crude version of it — which reported 92 files of noise — got both wrong:
//
//   * COMPONENT scope, not file scope. A file often holds several components,
//     and a flag in one cannot possibly guard a button in another. The first
//     version claimed the account form's `saving` should block the import
//     dialog, which are different components that cannot see each other.
//
//   * only flags that mean "a request is in flight". A `copied` lowered by a
//     setTimeout is UI feedback, not work; making other buttons wait on it
//     would disable the page for two seconds after copying a link, which is a
//     worse bug than the one being fixed. Page-load spinners are excluded for
//     the same reason — no button should wait on a list refreshing.
export interface Finding {
  component: string;
  line: number;
  fn: string;
  guards: string;
  missing: string[];
}

//: Leading whitespace is allowed deliberately. Real components sit at column
//: zero, but the unit tests below write theirs inside indented template
//: literals — and with `^` anchored hard, those tests detected nothing and the
//: ones asserting "no findings" passed for the wrong reason. A rule whose own
//: negative tests are vacuous is not a rule.
const COMPONENT = /^[ \t]*(?:export\s+)?(?:default\s+)?function\s+([A-Z]\w*)\s*\(/gm;
/** The body brace of a component, NOT its destructured props.
 *
 *  `function Screen({ clientId })` puts a `{` right after the name, so taking
 *  the first one found the PARAMETER OBJECT and treated it as the whole
 *  component — which held no useState, so every component with destructured
 *  props was silently skipped. That is how a scan can report a confident number
 *  and still be blind to a third of the app. Skip the balanced parens first. */
function bodyBrace(src: string, afterName: number): number {
  let depth = 0, i = afterName;
  for (; i < src.length; i++) {
    if (src[i] === "(") depth++;
    else if (src[i] === ")" && --depth === 0) { i++; break; }
  }
  const b = src.indexOf("{", i);
  return b;
}
//: `useState(true)` counts too. A list that starts out loading is still a
//: loading flag, and treating it as absent made three Retry buttons in
//: app/memory/page.tsx read as having no guard at all.
const USESTATE = /const \[(\w+)\s*,\s*(set\w+)\]\s*=\s*useState(?:<[^>]*>)?\(\s*(?:true|false)\s*\)/g;
const FUNC = /(?:async function (\w+)|const (\w+)\s*=\s*async)/g;
/** Not "a request is in flight" — see the header. */
const NOT_IN_FLIGHT = /copied|failed|modal|open|show|expanded|dirty|touched/i;

function braceBlock(src: string, i: number): [string, number] {
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}" && --depth === 0) return [src.slice(i, j + 1), j];
  }
  return [src.slice(i), src.length];
}

/** Every match of `re` in `src`, as an array — the project targets ES5 here, so
 *  `matchAll`'s iterator cannot be spread. */
function all(re: RegExp, src: string): RegExpExecArray[] {
  const out: RegExpExecArray[] = [];
  const r = new RegExp(re.source, re.flags.includes("g") ? re.flags : re.flags + "g");
  let m: RegExpExecArray | null;
  while ((m = r.exec(src)) !== null) {
    out.push(m);
    if (m[0] === "") r.lastIndex++;
  }
  return out;
}

/** Opening tags of every <button>, with their offset. */
function buttonTags(src: string): Array<[number, string]> {
  const out: Array<[number, string]> = [];
  for (const m of all(/<button\b/g, src)) {
    let depth = 0, j = m.index + m[0].length;
    for (; j < src.length; j++) {
      const c = src[j];
      if (c === "{") depth++;
      else if (c === "}") depth--;
      else if (c === ">" && depth === 0) break;
    }
    out.push([m.index, src.slice(m.index, j + 1)]);
  }
  return out;
}

export function findConcurrentActions(source: string): Finding[] {
  const found: Finding[] = [];
  for (const cm of all(COMPONENT, source)) {
    const open = bodyBrace(source, cm.index + cm[0].length - 1);
    if (open < 0) continue;
    const body = braceBlock(source, open)[0];
    const before = source.slice(0, open).split("\n").length - 1;

    const flagOf: Record<string, string> = {};              // setX -> x
    for (const m of all(USESTATE, body)) flagOf[m[2]] = m[1];

    const actions: Array<[string, string]> = [];            // [fn, flag]
    for (const m of all(FUNC, body)) {
      const name = m[1] || m[2];
      const i = body.indexOf("{", m.index + m[0].length);
      if (i < 0) continue;
      const fbody = braceBlock(body, i)[0];
      if (fbody.indexOf("await") < 0) continue;
      const raised = Object.keys(flagOf).filter(
        (s) => new RegExp("\\b" + s + "\\(true\\)").test(fbody));
      if (raised.length !== 1) continue;
      const setter = raised[0], flag = flagOf[setter];
      if (NOT_IN_FLIGHT.test(flag)) continue;
      if (new RegExp("setTimeout\\([^)]*" + setter + "\\(false\\)").test(fbody)) continue;
      actions.push([name, flag]);
    }
    if (actions.length < 2) continue;

    const tags = buttonTags(body);
    const starts = (tag: string, fn: string) =>
      new RegExp("onClick=\\{(?:\\s*\\(\\)\\s*=>\\s*)?" + fn + "\\b").test(tag);

    // A derived flag — `const actionInFlight = saving || computing;` — guards
    // both, so the expression has to be expanded before it is read. Without
    // this the rule cannot recognise its own fix, and would demand the raw
    // flags be listed again beside it.
    const derived: Array<[string, string]> = [];
    for (const m of all(/const (\w+)\s*=\s*([^;\n]*\|\|[^;\n]*);/g, body)) {
      derived.push([m[1], m[2]]);
    }
    const expand = (expr: string) => {
      let out = expr;
      for (const [name, rhs] of derived) {
        out = out.replace(new RegExp("\\b" + name + "\\b", "g"), rhs);
      }
      return out;
    };

    const started = actions.filter(([fn]) => tags.some(([, tag]) => starts(tag, fn)));
    const flags: string[] = [];
    for (const [, f] of started) if (flags.indexOf(f) < 0) flags.push(f);
    if (flags.length < 2) continue;

    for (const [off, tag] of tags) {
      for (const [fn, flag] of started) {
        if (!starts(tag, fn)) continue;
        const d = tag.match(/disabled=\{([\s\S]*?)\}\s*(?:\n|className|onClick|>)/);
        const expr = expand(d ? d[1] : "");
        const missing = flags.filter(
          (f) => f !== flag && !new RegExp("\\b" + f + "\\b").test(expr)).sort();
        if (missing.length) {
          found.push({
            component: cm[1],
            line: before + body.slice(0, off).split("\n").length,
            fn, guards: flag, missing,
          });
        }
      }
    }
  }
  return found;
}

/** A button that calls the server and is NEVER disabled.
 *
 *  The other half of the family, and the more common one. `findConcurrentActions`
 *  only looks at components with two or more actions, so a screen with a single
 *  unguarded Delete is invisible to it — and that button needs no second button
 *  to go wrong, just an impatient double-click. Found 31 of these, 18 of which
 *  wrote something: deleteAccount, purgeSingle, retire, handleDelete, archive.
 */
export function findUnguardedActions(source: string): Finding[] {
  const out: Finding[] = [];
  const setters: string[] = [];
  for (const m of all(USESTATE, source)) setters.push(m[2]);

  for (const m of all(FUNC, source)) {
    const name = m[1] || m[2];
    const i = source.indexOf("{", m.index + m[0].length);
    if (i < 0) continue;
    const body = braceBlock(source, i)[0];
    if (body.indexOf("await") < 0) continue;
    if (!/api\.\w+\.|supabase|fetch\(/.test(body)) continue;
    // A handler that raises a flag of its own has a loading state; whether its
    // button is wired to it is a different (and much larger, mostly harmless —
    // a re-read is idempotent) question, deliberately not ratcheted here. This
    // rule is about handlers with NO loading state at all, which is what makes
    // a second click a second write.
    if (setters.some((st) => new RegExp("\\b" + st + "\\(true\\)").test(body))) continue;
    // Delegating to a wrapper that raises a flag counts as guarded, which is
    // why the button's own `disabled` is what decides below rather than this.
    for (const [off, tag] of buttonTags(source)) {
      if (!new RegExp("onClick=\\{(?:\\s*\\(\\)\\s*=>\\s*)?" + name + "\\b").test(tag)) continue;
      if (tag.indexOf("disabled=") >= 0) continue;
      out.push({
        component: "", fn: name, guards: "(nothing)", missing: ["a loading state"],
        line: source.slice(0, off).split("\n").length,
      });
    }
  }
  return out;
}

/** A button whose handler HAS a loading state that the button is not wired to.
 *
 *  The third shape, and the mildest: the work is tracked, the control just does
 *  not reflect it. All 15 found were Retry buttons on a failed load plus a
 *  suggested-prompt chip, so a repeat cost a wasted request rather than a
 *  duplicate write — which is why this was measured and recorded before it was
 *  fixed, rather than folded in silently.
 *
 *  The flag to disable on is the LOADING one, never the failure one. These
 *  handlers usually raise a pair (`loading` and `loadFailed`); wiring Retry to
 *  `loadFailed` would disable it exactly when it is needed.
 */
export function findUnwiredActions(source: string): Finding[] {
  const out: Finding[] = [];
  const flagOf: Record<string, string> = {};
  for (const m of all(USESTATE, source)) flagOf[m[2]] = m[1];

  for (const m of all(FUNC, source)) {
    const name = m[1] || m[2];
    const i = source.indexOf("{", m.index + m[0].length);
    if (i < 0) continue;
    const body = braceBlock(source, i)[0];
    if (body.indexOf("await") < 0) continue;
    if (!/api\.\w+\.|supabase|fetch\(/.test(body)) continue;
    const raised = Object.keys(flagOf)
      .filter((st) => new RegExp("\\b" + st + "\\(true\\)").test(body))
      .map((st) => flagOf[st]);
    if (!raised.length) continue;               // findUnguardedActions' job
    for (const [off, tag] of buttonTags(source)) {
      if (!new RegExp("onClick=\\{(?:\\s*\\(\\)\\s*=>\\s*)?" + name + "\\b").test(tag)) continue;
      if (tag.indexOf("disabled=") >= 0) continue;
      out.push({
        component: "", fn: name, guards: "(not wired)",
        missing: raised.filter((f) => !/fail|error/i.test(f)).sort(),
        line: source.slice(0, off).split("\n").length,
      });
    }
  }
  return out;
}
