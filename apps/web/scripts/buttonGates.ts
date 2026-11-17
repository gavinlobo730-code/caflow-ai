// The helpers the two button-gate tests share (POST-A-455): the pair a route asks, read off its router; the pair a
// screen's gate asks; and whether the gate is the nearest condition enclosing a button. Kept out of the test files so
// that importing them does not register a second copy of another file's tests.
import assert from "node:assert/strict";

/** The decorator's block, from `@router.<method>("<path>"` up to the next decorator. */
function routeBlock(src: string, method: string, path: string): string {
  const at = src.indexOf(`@router.${method}("${path}"`);
  assert.ok(at >= 0, `no ${method.toUpperCase()} ${path}`);
  const next = src.indexOf("@router.", at + 1);
  return src.slice(at, next < 0 ? undefined : next);
}

/** The pair a route's `rbac(...)` asks. */
export function routePair(src: string, method: string, path: string): string {
  const m = routeBlock(src, method, path).match(/rbac\("([a-z_]+)",\s*"([a-z_]+)"\)/);
  assert.ok(m, `${method.toUpperCase()} ${path} asks no pair`);
  return `${m[1]}:${m[2]}`;
}

/**
 * The pair a route asks of the person INSIDE its handler (a `can_user` call on the current user), for a route whose
 * decorator admits more people than one of its steps does (a GST return's status route takes `gst` `compute` and asks
 * `gst` `approve` before an approval or a filing).
 */
export function innerPair(src: string, method: string, path: string): string {
  const m = routeBlock(src, method, path).match(/can_user\(current_user, "([a-z_]+)", "([a-z_]+)"\)/);
  assert.ok(m, `${method.toUpperCase()} ${path} asks no pair of the person inside it`);
  return `${m[1]}:${m[2]}`;
}

/**
 * The pair a gate asks in a screen's source: a variable set from a permission check, a `Can` component, or a check written inline.
 * A variable declared in more than one component of a file (each tab asks for itself) must be declared with ONE pair: where two
 * declarations disagree, the answer is null, so a wrong pair in the second or the third cannot hide behind a right one in the first.
 */
export function gatePair(src: string, gate: string): string | null {
  const inline = gate.match(/^(?:<Can resource="([a-z_]+)" action="([a-z_]+)"|can\("([a-z_]+)", "([a-z_]+)"\))/);
  if (inline) return src.includes(gate) ? `${inline[1] ?? inline[3]}:${inline[2] ?? inline[4]}` : null;
  const declared = [...src.matchAll(new RegExp(`\\b${gate.replace(/^!/, "")} = [^;\\n]*can(?:Do)?\\("([a-z_]+)", "([a-z_]+)"\\)`, "g"))]
    .map((m) => `${m[1]}:${m[2]}`);
  if (declared.length === 0) return null;
  return declared.every((d) => d === declared[0]) ? declared[0] : null;
}

/**
 * Whether a line names the gate AS a condition of its own: the whole token (not `mayWrite` inside `mayWriteBooks`), not negated
 * (a leading `!` unless the gate is written with one), not one side of an `||`, and not sitting in a ternary's branch
 * (`x ? mayA : mayB`; `) : mayA ? (` is a condition of its own), where it says nothing about the button drawn under the line.
 */
export function namesGate(line: string, gate: string): boolean {
  const esc = gate.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const lead = /^[\w$!]/.test(gate) ? "(?<![\\w$.!])" : "";
  const tail = /[\w$]$/.test(gate) ? "(?![\\w$])" : "";
  for (const m of line.matchAll(new RegExp(`${lead}${esc}${tail}`, "g"))) {
    const before = line.slice(0, m.index).trimEnd();
    const after = line.slice((m.index ?? 0) + m[0].length).trimStart();
    if (before.endsWith("||") || after.startsWith("||")) continue;
    if (before.endsWith("?") || (before.endsWith(":") && before.includes(" ? "))) continue;
    return true;
  }
  return false;
}

/**
 * A line that opens the condition a JSX child or a statement is drawn under: one ending `… && (` or `… ? (`, a `<Can …>`,
 * an `if (…`, or an expression that draws its element on the same line (`mayX && <Button …`).
 */
const OPENS = /&& \($|\? \($|<Can |\bif \(|^\{?[^<>]*&& </;
/** A line that closes one: `)}`, `</tag>}`, `/>}` or `</Can>`. */
/** The line between a ternary's two branches. */
const ELSE = /^\)\s*:\s*\($/;
const CLOSES = /^\)\}$|<\/[A-Za-z.]+>\}$|\/>\}$|^<\/Can>$/;

/**
 * The gate is on the NEAREST condition that ENCLOSES the button: walking back from the button's line, a condition that
 * opened and closed above it (a neighbour's) is stepped over, and the first opener still open must name the gate. Comment
 * lines are skipped. `nth` picks the nth occurrence of the anchor (0-based) where one screen draws the same call twice.
 */
export function gatedBy(src: string, anchor: string, gate: string, nth = 0): boolean {
  let at = -1;
  for (let k = 0; k <= nth; k += 1) {
    at = src.indexOf(anchor, at + 1);
    assert.ok(at >= 0, `the button ${anchor} (occurrence ${nth}) is gone`);
  }
  const lines = src.slice(0, at + anchor.length).split("\n").reverse();
  let depth = 0;
  let inElse = false;    // the button is in the `) : (` branch of a ternary, so the opener of that ternary decides the OTHER branch
  for (const [i, line] of lines.entries()) {
    const t = line.trim();
    if (i > 40) break;
    if (t.startsWith("//") || t.startsWith("{/*") || t.startsWith("*")) continue;
    const opens = OPENS.test(t);
    if (i === 0) { if (opens) return namesGate(t, gate); continue; }
    if (opens && CLOSES.test(t)) continue;                 // opens and closes on one line: a neighbour
    if (opens && t.startsWith(")") && depth > 0) continue;  // `) : x ? (` between two branches of a closed neighbour
    if (CLOSES.test(t)) { depth += 1; continue; }
    if (depth === 0 && ELSE.test(t)) { inElse = true; continue; }
    if (opens) {
      if (depth === 0) return !(inElse && /\? \($/.test(t)) && namesGate(t, gate);
      depth -= 1;
    }
  }
  return false;
}
