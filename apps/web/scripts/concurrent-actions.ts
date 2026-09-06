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

const COMPONENT = /^(?:export\s+)?(?:default\s+)?function\s+([A-Z]\w*)\s*\(/gm;
const USESTATE = /const \[(\w+)\s*,\s*(set\w+)\]\s*=\s*useState(?:<[^>]*>)?\(\s*false\s*\)/g;
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
    const open = source.indexOf("{", cm.index + cm[0].length);
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
