// A KEYBOARD USER CAN SKIP THE MENU, SEE WHERE FOCUS IS, AND READ A HINT.
//   node --experimental-strip-types --test scripts/a-keyboard-user-can-see-where-they-are.test.ts
//
// ─────────────────────────────────────────────────────────────────────────────
// THE DEFECTS (frontend_ux-28)
// ─────────────────────────────────────────────────────────────────────────────
// Four small ones, each invisible to the people who wrote the screen:
//
//  1. NO SKIP LINK. Both shells put a top bar (a dozen-plus tab stops) ahead of
//     the page, so a keyboard user tabbed through all of it on every page load
//     (WCAG 2.4.1). Zero hits for "skip" anywhere, and neither shell's `<main>`
//     had an id to skip TO.
//  2. A PLACEHOLDER WORE THE `disabled` GREY. `ps-disabled` (#CBD5E1) is 1.48:1
//     on white. `tailwind.config.ts` leaves that token failing on purpose —
//     WCAG 1.4.3 exempts text in an INACTIVE control — and that reads like
//     permission, but a placeholder sits in a box somebody is being asked to
//     type into. Fourteen inputs wore it, and ten more wore gray-400 (2.54:1),
//     eight of them as the legacy `placeholder-gray-400`: the same defect in
//     another spelling.
//  3. `outline-none` WITH NOTHING IN ITS PLACE. Sixteen controls removed the
//     browser's focus outline and drew nothing instead — mostly the `<select>`
//     in each line-item table — so tabbing along a row of an invoice showed no
//     sign of where focus was (WCAG 2.4.7). The finding's 461 figure was mostly
//     controls that DO draw a ring; the real gap was 25 strings.
//  4. (the `main` id, above.)
//
// ─────────────────────────────────────────────────────────────────────────────
// THE RULE, stated once and held over the whole tree
// ─────────────────────────────────────────────────────────────────────────────
//  * One skip link, rendered by AppShell in the branch that draws a shell,
//    FIRST, pointing at one constant that both shells' `<main>` carry.
//  * The only colours a placeholder may wear are the four text tokens that pass
//    on the field's own surface: ps-hint, ps-label, ps-body, ps-ink — and the
//    hint token is asserted against the palette file, so lightening it breaks
//    this rather than quietly breaking every placeholder.
//  * Every class list that removes the outline also draws a focus indicator
//    (a ring, a border change, a shadow, an underline) — OR is one of the
//    three named exceptions below, each asserted to be true of its own file so
//    a stale exception fails instead of hiding a new hole.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const WEB = join(import.meta.dirname, "..");

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(join(WEB, dir))) {
    if (entry === "node_modules" || entry === ".next") continue;
    const rel = join(dir, entry).replace(/\\/g, "/");
    if (statSync(join(WEB, rel)).isDirectory()) walk(rel, out);
    else if (rel.endsWith(".tsx")) out.push(rel);
  }
  return out;
}
const FILES = ["app", "components"].flatMap((r) => walk(r));

function stripComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "))
    .replace(/^(\s*)\/\/.*$/gm, (_m, ws: string) => ws);
}
/** Comments blanked, NOT deleted, so offsets and line numbers still point at
 *  the real source. */
function code(rel: string): string {
  return stripComments(readFileSync(join(WEB, rel), "utf8"));
}
const lineOf = (src: string, idx: number) => src.slice(0, idx).split("\n").length;

// ═════════════════════════════════════════════════════════════════════════════
// 1. THE SKIP LINK AND ITS TARGET
// ═════════════════════════════════════════════════════════════════════════════

const SKIP = "components/shell/SkipToContent.tsx";
const SHELLS = ["components/shell/WorkspaceShell.tsx", "components/shell/ClientShell.tsx"];

test("the skip link points at one constant and is invisible until focused", () => {
  const src = code(SKIP);
  assert.match(src, /export\s+const\s+MAIN_CONTENT_ID\s*=\s*"main-content"/);
  assert.match(src, /href=\{`#\$\{MAIN_CONTENT_ID\}`\}/, "the link must be built from the constant");
  assert.match(src, /Skip to content/);
  const cls = /className="([^"]+)"/.exec(src)?.[1] ?? "";
  assert.match(cls, /\bsr-only\b/, "it must be visually hidden until focused");
  assert.match(cls, /\bfocus:not-sr-only\b/, "and appear when it takes focus");
  assert.match(cls, /\bfocus:ring-/, "and, once shown, draw a focus indicator of its own");
  assert.match(cls, /\bfocus:fixed\b/, "a shell is h-screen overflow-hidden; the link must not sit inside its flow");
});

test("both shells' <main> carry the target, take programmatic focus, and there is one each", () => {
  for (const rel of SHELLS) {
    const src = code(rel);
    const mains = src.match(/<main\b[^>]*>/g) ?? [];
    assert.equal(mains.length, 1, `${rel} must have exactly one <main>, found ${mains.length}`);
    assert.match(mains[0], /id=\{MAIN_CONTENT_ID\}/, `${rel}: <main> has no id for the skip link to reach`);
    assert.match(mains[0], /tabIndex=\{-1\}/,
      `${rel}: without tabIndex={-1} a jump scrolls to <main> but leaves focus in the menu`);
    assert.match(src, /import\s*\{\s*MAIN_CONTENT_ID\s*\}\s*from\s*"@\/components\/shell\/SkipToContent"/,
      `${rel} must import the constant, not spell the id`);
  }
});

test("AppShell renders the skip link once, first, and only where a shell is drawn", () => {
  const src = code("components/AppShell.tsx");
  const uses = src.match(/<SkipToContent\b/g) ?? [];
  assert.equal(uses.length, 1, "exactly one skip link");
  const link = src.indexOf("<SkipToContent");
  const bare = src.indexOf("if (!showShell)");
  assert.ok(bare >= 0 && link > bare,
    "the link is rendered before the no-shell early return, so sign-in and portal screens would point at a landmark that is not there");
  assert.ok(link < src.indexOf("<SearchModal") && link < src.indexOf("<ClientShell"),
    "it must precede the top bar, or it is not the first tab stop");
});

test("there is one skip link in the product", () => {
  const defining = FILES.filter((f) => /Skip to content/.test(code(f)));
  assert.deepEqual(defining, [SKIP], "a second 'Skip to content' is a second implementation");
});

// ═════════════════════════════════════════════════════════════════════════════
// 2. PLACEHOLDER CONTRAST
// ═════════════════════════════════════════════════════════════════════════════

/** The only text tokens a placeholder may use, each of which passes 4.5:1 on
 *  white and on `ps-bg`. `ps-disabled` is deliberately absent. */
const PLACEHOLDER_TOKENS = new Set(["ps-hint", "ps-label", "ps-body", "ps-ink"]);

/** Every colour a placeholder utility names, in either Tailwind spelling:
 *  `placeholder:text-X` and the legacy `placeholder-X`. */
function placeholderColours(src: string): string[] {
  const out: string[] = [];
  for (const m of src.matchAll(/(?<![\w-])placeholder:text-([^\s"'`}]+)/g)) out.push(m[1]);
  for (const m of src.matchAll(/(?<![\w-])placeholder-([a-z][^\s"'`}]*)/g)) out.push(m[1]);
  return out;
}

test("the placeholder detector sees both spellings", () => {
  assert.deepEqual(placeholderColours(`className="placeholder:text-ps-disabled"`), ["ps-disabled"]);
  assert.deepEqual(placeholderColours(`className="x placeholder-gray-400 y"`), ["gray-400"]);
  assert.deepEqual(placeholderColours(`className="placeholder:text-slate-300/80"`), ["slate-300/80"]);
  assert.deepEqual(placeholderColours(`className="placeholder:text-ps-hint"`), ["ps-hint"]);
  assert.deepEqual(placeholderColours(`<input placeholder="x" />`), [], "the prop is not a colour");
  assert.deepEqual(placeholderColours(`<input placeholder-id />`), ["id"], "a stray word is caught as a colour, which fails loudly rather than silently");
});

test("every placeholder in the product is a token that passes contrast", () => {
  const offenders: string[] = [];
  let seen = 0;
  for (const f of FILES) {
    for (const c of placeholderColours(code(f))) {
      seen++;
      if (!PLACEHOLDER_TOKENS.has(c)) offenders.push(`${f}: placeholder colour ${c}`);
    }
  }
  assert.ok(seen >= 25, `only ${seen} placeholder colours read — the scan is broken`);
  assert.deepEqual(offenders, [],
    "a placeholder sits in a LIVE box, so WCAG 1.4.3 applies in full. `ps-disabled` is 1.48:1 on white and " +
    "gray-400 is 2.54:1. Use `placeholder:text-ps-hint` (4.76:1):\n  " + offenders.join("\n  "));
});

function luminance(hex: string): number {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => {
    const c = parseInt(h.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

test("the hint token the rule leans on really passes, on white and on the app background", () => {
  const palette = readFileSync(join(WEB, "tailwind.config.ts"), "utf8");
  const hint = /\bhint:\s*"(#[0-9A-Fa-f]{6})"/.exec(palette)?.[1];
  const bg = /\bbg:\s*"(#[0-9A-Fa-f]{6})"/.exec(palette)?.[1];
  assert.ok(hint && bg, "could not read the hint and bg tokens from tailwind.config.ts");
  assert.ok(contrast(hint!, "#FFFFFF") >= 4.5, `ps-hint ${hint} is ${contrast(hint!, "#FFFFFF").toFixed(2)}:1 on white`);
  assert.ok(contrast(hint!, bg!) >= 4.5, `ps-hint ${hint} is ${contrast(hint!, bg!).toFixed(2)}:1 on ${bg}`);
  // The premise of the ban, asserted rather than remembered.
  const disabled = /\bdisabled:\s*"(#[0-9A-Fa-f]{6})"/.exec(palette)?.[1];
  assert.ok(disabled && contrast(disabled, "#FFFFFF") < 3,
    "ps-disabled no longer fails contrast — if the token was darkened on purpose, this ban can be reconsidered");
});

test("the palette comment says a placeholder is not an inactive control", () => {
  const palette = readFileSync(join(WEB, "tailwind.config.ts"), "utf8");
  assert.match(palette, /A PLACEHOLDER IS NOT TEXT IN AN INACTIVE CONTROL/,
    "the comment that read as permission must say it is not");
});

// ═════════════════════════════════════════════════════════════════════════════
// 3. AN OUTLINE IS NEVER REMOVED WITHOUT DRAWING SOMETHING ELSE
// ═════════════════════════════════════════════════════════════════════════════

/** A focus indicator: a ring, a border change, a shadow, an underline or a
 *  background change on focus — `focus:outline-none` does NOT count as one. */
const INDICATOR =
  /(?:focus|focus-visible|focus-within):(?:ring|border|shadow|underline|bg-|outline-(?!none))/;
const REMOVES_OUTLINE = /(?<![\w-])(?:focus:|focus-visible:)?outline-none(?![\w-])/;

interface Bag { text: string; start: number }

/** Every `className=` VALUE as one bag — a string literal, or a `{…}` read to
 *  its balanced close with strings respected — so `cn("a outline-none", b ?
 *  "focus:ring-2" : "x")` is judged as the one class list it is. */
function classBags(src: string): Bag[] {
  const bags: Bag[] = [];
  for (const m of src.matchAll(/\bclassName\s*=\s*/g)) {
    let i = (m.index ?? 0) + m[0].length;
    const start = i;
    const first = src[i];
    if (first === '"' || first === "'") {
      const end = src.indexOf(first, i + 1);
      bags.push({ text: src.slice(i, end + 1), start });
    } else if (first === "{") {
      let depth = 0;
      let quote = "";
      for (; i < src.length; i++) {
        const ch = src[i];
        if (quote) {
          if (ch === "\\") { i++; continue; }
          if (ch === quote) quote = "";
          continue;
        }
        if (ch === '"' || ch === "'" || ch === "`") { quote = ch; continue; }
        if (ch === "{") depth++;
        else if (ch === "}" && --depth === 0) break;
      }
      bags.push({ text: src.slice(start, i + 1), start });
    }
  }
  return bags;
}

interface Hole { line: number; offset: number; text: string }

/** Class lists that remove the outline and draw no focus indicator. */
export function holesIn(src: string): Hole[] {
  const holes: Hole[] = [];
  const bags = classBags(src);
  const covered = (idx: number) => bags.some((b) => idx >= b.start && idx < b.start + b.text.length);
  for (const b of bags) {
    if (REMOVES_OUTLINE.test(b.text) && !INDICATOR.test(b.text)) {
      holes.push({ line: lineOf(src, b.start), offset: b.start, text: b.text.replace(/\s+/g, " ").slice(0, 110) });
    }
  }
  // An `outline-none` that is NOT inside a className value — a shared class
  // constant, say — is judged on its own line.
  for (const m of src.matchAll(new RegExp(REMOVES_OUTLINE.source, "g"))) {
    const idx = m.index ?? 0;
    if (covered(idx)) continue;
    const ln = lineOf(src, idx);
    const text = src.split("\n")[ln - 1];
    if (!INDICATOR.test(text)) holes.push({ line: ln, offset: idx, text: text.trim().slice(0, 110) });
  }
  return holes;
}

test("the hole detector catches a removed outline with nothing in its place", () => {
  assert.equal(holesIn(`<select className="px-1 border rounded focus:outline-none text-xs" />`).length, 1);
  assert.equal(holesIn(`<input className="flex-1 text-sm outline-none" />`).length, 1);
  assert.equal(holesIn('const cls = "w-full outline-none";').length, 1, "a class constant outside a className is judged too");
  // `focus:outline-none` is not its own replacement — the bug in the first count.
  assert.equal(holesIn(`<a className="focus:outline-none" />`).length, 1);
});

test("the hole detector leaves a ring, a border change, a conditional ring and focus-visible alone", () => {
  assert.equal(holesIn(`<input className="rounded focus:outline-none focus:ring-2 focus:ring-brand" />`).length, 0);
  assert.equal(holesIn(`<input className="outline-none focus:border-brand" />`).length, 0);
  assert.equal(holesIn(`<select className="rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-brand" />`).length, 0);
  assert.equal(holesIn(
    `<button className={cn("focus:outline-none", plain ? "focus:ring-1 focus:ring-brand" : "focus:ring-2")} />`).length, 0,
    "a ring in a sibling string of the same cn() call is the same class list");
  assert.equal(holesIn(`<input className={\`mt-1 border rounded focus:outline-none focus-visible:ring-2 \${x ? "a" : "b"}\`} />`).length, 0);
  assert.equal(holesIn(`<button className="focus-visible:outline-none focus-visible:ring-2" />`).length, 0);
});

/** The three named exceptions. Each is a control that removes its own outline
 *  because something ELSE shows focus, and each is asserted true of its file. */
type Kind = "programmatic-focus" | "wrapper-shows-focus";
const EXCEPTIONS: Record<string, Kind[]> = {
  // A dialog's container, and the page landmark, take focus from code
  // (`tabIndex={-1}`) and are not controls: a ring around a whole dialog or the
  // whole page body says nothing.
  "components/ui/modal.tsx": ["programmatic-focus"],
  "components/ui/drawer.tsx": ["programmatic-focus"],
  "components/shell/WorkspaceShell.tsx": ["programmatic-focus"],
  "components/shell/ClientShell.tsx": ["programmatic-focus"],
  // A borderless input inside a bordered wrapper: the WRAPPER draws the ring
  // (`focus-within`), or — the combobox's open search row — always shows one.
  "components/ui/combobox.tsx": ["wrapper-shows-focus", "wrapper-shows-focus"],
  "components/SearchModal.tsx": ["wrapper-shows-focus"],
  "app/team/assignments/page.tsx": ["wrapper-shows-focus"],
  "app/clients/[id]/knowledge/page.tsx": ["wrapper-shows-focus"],
  "app/knowledge/page.tsx": ["wrapper-shows-focus"],
  "components/portal/TaxDeclarationTab.tsx": ["wrapper-shows-focus"],
};

/** A class list that draws its OWN focus indicator on behalf of what is inside
 *  it: a `focus-within` ring or border, or a STATIC ring (the combobox's
 *  always-open search row, which is only rendered while it has focus). */
const WRAPPER_INDICATOR = /focus-within:(?:ring|border)|(?<![\w:-])ring-\d\b/;

function exceptionHolds(kind: Kind, src: string, hole: Hole): boolean {
  if (kind === "programmatic-focus") {
    const lines = src.split("\n");
    return lines.slice(Math.max(0, hole.line - 7), hole.line + 1).some((l) => /tabIndex=\{-1\}/.test(l));
  }
  // The NEAREST earlier class list that draws a wrapper indicator, with no
  // closing `</div>`/`</label>`/`</form>` between it and the control — i.e. the
  // control is still inside that wrapper. A line window would be both too
  // short (the combobox's input sits twenty lines below its wrapper, under
  // its aria attributes) and too loose.
  const wrapper = classBags(src)
    .filter((b) => b.start < hole.offset && WRAPPER_INDICATOR.test(b.text))
    .pop();
  if (!wrapper) return false;
  return !/<\/(?:div|label|form|section)>/.test(src.slice(wrapper.start, hole.offset));
}

test("the wrapper exception holds only while the control is still inside the wrapper", () => {
  const inside = `<div className="flex focus-within:ring-2 focus-within:ring-brand"><Icon /><input className="flex-1 outline-none" /></div>`;
  const [h1] = holesIn(inside);
  assert.ok(h1 && exceptionHolds("wrapper-shows-focus", inside, h1), "an input inside a focus-within wrapper is covered");

  const after = `<div className="flex focus-within:ring-2"><Icon /></div><input className="flex-1 outline-none" />`;
  const [h2] = holesIn(after);
  assert.ok(h2 && !exceptionHolds("wrapper-shows-focus", after, h2),
    "once the wrapper has closed, a later input is NOT covered by it");

  const none = `<div className="flex"><input className="flex-1 outline-none" /></div>`;
  const [h3] = holesIn(none);
  assert.ok(h3 && !exceptionHolds("wrapper-shows-focus", none, h3), "no wrapper indicator, no exception");

  const dialog = `<div\n role="dialog"\n tabIndex={-1}\n className="bg-white outline-none">`;
  const [h4] = holesIn(dialog);
  assert.ok(h4 && exceptionHolds("programmatic-focus", dialog, h4), "a dialog container that takes programmatic focus");
  const control = `<input\n className="outline-none" />`;
  const [h5] = holesIn(control);
  assert.ok(h5 && !exceptionHolds("programmatic-focus", control, h5), "an ordinary control is not exempt");
});

test("no control removes its outline without drawing a focus indicator", () => {
  const unexplained: string[] = [];
  const used: Record<string, number> = {};
  let scanned = 0;
  for (const f of FILES) {
    const src = code(f);
    if (REMOVES_OUTLINE.test(src)) scanned++;
    for (const h of holesIn(src)) {
      const kinds = EXCEPTIONS[f] ?? [];
      const n = used[f] ?? 0;
      const kind = kinds[n];
      if (kind && exceptionHolds(kind, src, h)) { used[f] = n + 1; continue; }
      unexplained.push(`${f}:${h.line}  ${h.text}`);
    }
  }
  assert.ok(scanned > 100, `only ${scanned} files mention outline-none — the scan is broken`);
  assert.deepEqual(unexplained, [],
    "these remove the browser's focus outline and draw nothing in its place, so a keyboard user cannot see " +
    "where focus is (WCAG 2.4.7). Add `focus:ring-2 focus:ring-brand` (or `focus-visible:` on a select or " +
    "button), or put `focus-within:ring-2` on the wrapper:\n  " + unexplained.join("\n  "));
  // Every exception must still be USED — a stale one would hide the next hole in that file.
  for (const [f, kinds] of Object.entries(EXCEPTIONS)) {
    assert.equal(used[f] ?? 0, kinds.length,
      `${f} is listed with ${kinds.length} exception(s) but only ${used[f] ?? 0} still apply — trim EXCEPTIONS`);
  }
});
