// A PRINTED SCREEN IS NOT CLIPPED, NOT BLANKED, AND NAMES ITS CLIENT (PRE-A-016).
//   node --experimental-strip-types --test scripts/a-printed-screen-is-not-clipped-or-blanked.test.ts
//
// ─────────────────────────────────────────────────────────────────────────────
// WHAT WENT WRONG, AND THE RULE THAT REPLACES IT
// ─────────────────────────────────────────────────────────────────────────────
// A practice still signs off on paper, and "Print" on a statement did one of two
// things. On /reports the page's only print rule hid every child of <body> and
// re-showed `.report-print-root`: a descendant cannot override an ancestor's
// `display: none`, the report sits inside the shell inside a body child, so the
// printout was BLANK. Everywhere else there was no print rule at all, and both
// shells are `h-screen overflow-hidden`, which a printer reads as "one page
// tall, clip the rest" — a long statement printed as its first screenful, under
// the whole navigation bar.
//
// Four rules, none of them a spelling of the old code:
//
//   A. NO PRINT RULE HIDES THE DOCUMENT AND RE-SHOWS A PART. A rule inside
//      `@media print` that reaches from the document root (`body > *`, `body *`,
//      `html`, `:root`, `#__next`, a bare `*`) and sets `display: none` removes
//      an ancestor of the content, and nothing below can undo it. And `@media
//      print` lives in ONE file (globals.css), so the next one is reviewed
//      beside this.
//   B. THE FRAME DOES NOT CLIP A PRINTOUT, AND THE CHROME IS NOT PRINTED. Every
//      class list in a shell that fixes the height to the viewport or clips
//      overflow says how it prints; every component the shells draw around the
//      page is either `print:hidden` at its root or on the not-chrome list with
//      its reason. The set of components is DERIVED from what `layout.tsx`,
//      `AppShell` and the two shells render, so a banner added next month is
//      refused until somebody says how it prints.
//   C. A PRINT BUTTON IS NOT PRINTED, AND PRINTS THE PAGE IT IS ON. Every
//      `window.print()` is a frozen file -> count table that can only shrink;
//      the control sits inside something `print:hidden` (or is itself); none
//      sits inside a `.map` callback (every row would print the same page, the
//      three "Print as PDF" rows on Financial Reports did); a screen that prints
//      one region marks it `data-print-scope`; the one in a modal nothing opens
//      is checked to still be unreachable.
//   D. A PRINTOUT NAMES WHOSE BOOKS IT IS: the client workspace draws
//      `PrintHeader` (print-only) in <main>, and the scoped-print rule keeps it.
//
// WHAT THIS DOES NOT PROVE. It reads source. That a long page really comes out
// as several sheets was driven in headless Chromium against the exported app
// (the commit message has the numbers), and no pixel of it is asserted here.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync, existsSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
const read = (rel: string) => readFileSync(join(WEB, rel), "utf8");
const code = (rel: string) => stripComments(read(rel));

/** Every product source file (the tests beside it are not the product). */
function sourceFiles(exts: string[]): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(join(WEB, dir))) {
      const rel = `${dir}/${name}`;
      if (name === "node_modules" || name.startsWith(".")) continue;
      if (statSync(join(WEB, rel)).isDirectory()) { walk(rel); continue; }
      if (!exts.some((e) => name.endsWith(e))) continue;
      if (/\.test\.[cm]?tsx?$/.test(name)) continue;
      out.push(rel);
    }
  };
  for (const d of ["app", "components", "lib"]) walk(d);
  return out;
}

// ═════════════════════════════════════════════════════════════════════════════
// A. NO PRINT RULE HIDES THE DOCUMENT
// ═════════════════════════════════════════════════════════════════════════════

/** The bodies of every `@media print { ... }` in a source, brace-matched. */
function printBlocks(src: string): string[] {
  const blocks: string[] = [];
  const re = /@media\s+print\b[^{]*\{/g;
  for (let m = re.exec(src); m; m = re.exec(src)) {
    let depth = 1;
    let i = m.index + m[0].length;
    const start = i;
    for (; i < src.length && depth > 0; i++) {
      if (src[i] === "{") depth++;
      else if (src[i] === "}") depth--;
    }
    blocks.push(src.slice(start, i - 1));
  }
  return blocks;
}

/** A selector that starts at the document root, or is everything. */
const FROM_THE_ROOT = /^(?:\*|html\b|body\b|:root\b|#__next\b)/;

/** The selectors, inside print blocks, that set `display: none` from the root. */
function documentHidingSelectors(src: string): string[] {
  const found: string[] = [];
  for (const block of printBlocks(src)) {
    for (const rule of block.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      if (!/display\s*:\s*none/i.test(rule[2])) continue;
      for (const sel of rule[1].split(",")) {
        const s = sel.replace(/\/\*[\s\S]*?\*\//g, "").trim();
        if (s && FROM_THE_ROOT.test(s)) found.push(s);
      }
    }
  }
  return found;
}

test("the detector fires on the rule that printed /reports blank, and on its siblings", () => {
  const old = `@media print {
    /* Hide everything except the report content */
    body > * { display: none !important; }
    .report-print-root { display: block !important; }
    nav, aside, header, footer, [data-sidebar] { display: none !important; }
  }`;
  assert.deepEqual(documentHidingSelectors(old), ["body > *"]);
  assert.deepEqual(documentHidingSelectors(`@media print { body * { display:none } }`), ["body *"]);
  assert.deepEqual(documentHidingSelectors(`@media print { html { display : none } }`), ["html"]);
  assert.deepEqual(documentHidingSelectors(`@media print { :root { display: none } }`), [":root"]);
  assert.deepEqual(documentHidingSelectors(`@media print { #__next > div { display: none } }`), ["#__next > div"]);
  assert.deepEqual(documentHidingSelectors(`@media print { * { display: none } }`), ["*"]);
  assert.deepEqual(documentHidingSelectors(`@media print { nav, body > * { display: none } }`), ["body > *"],
    "one selector in a list is enough");
  assert.deepEqual(documentHidingSelectors("@media print {\n  body > * {\n    display: none !important;\n  }\n}"), ["body > *"]);
});

test("the detector leaves alone what is not that rule", () => {
  assert.deepEqual(documentHidingSelectors(`@media print { nav, aside { display: none } }`), []);
  assert.deepEqual(documentHidingSelectors(`@media print { tr { break-inside: avoid; } }`), []);
  assert.deepEqual(documentHidingSelectors(`@media print { body { margin: 0 } }`), [],
    "styling the body is not hiding it");
  assert.deepEqual(documentHidingSelectors(`body > * { display: none }`), [],
    "a screen rule is not a print rule");
  assert.deepEqual(documentHidingSelectors(
    `@media print { main:has([data-print-scope]) *:not([data-print-scope]) { display: none !important; } }`), [],
    "a rule rooted in <main> keeps the shell and everything on the way to the page");
  assert.deepEqual(documentHidingSelectors(`@media screen { body > * { display: none } } @media print { a { color: #000 } }`), []);
});

test("no print rule in the app hides the document and re-shows a part", () => {
  const offenders: string[] = [];
  for (const rel of sourceFiles([".tsx", ".ts", ".css", ".mjs"])) {
    const raw = rel.endsWith(".css") ? read(rel).replace(/\/\*[\s\S]*?\*\//g, "") : code(rel);
    for (const sel of documentHidingSelectors(raw)) offenders.push(`${rel}: ${sel}`);
  }
  assert.deepEqual(offenders, [], "a print rule that hides body children cannot be undone by a descendant: " +
    "the report is INSIDE them, so the page prints blank");
});

test("`@media print` is written in app/globals.css and nowhere else", () => {
  const where: string[] = [];
  for (const rel of sourceFiles([".tsx", ".ts", ".css", ".mjs"])) {
    const raw = rel.endsWith(".css") ? read(rel).replace(/\/\*[\s\S]*?\*\//g, "") : code(rel);
    if (/@media\s+print\b/.test(raw)) where.push(rel);
  }
  assert.deepEqual(where, ["app/globals.css"],
    "print CSS in a page's <style jsx> is how /reports came to print blank. Use `print:` variants on the element, " +
    "or the one block in globals.css");
});

// ═════════════════════════════════════════════════════════════════════════════
// B. THE FRAME DOES NOT CLIP, AND THE CHROME IS NOT PRINTED
// ═════════════════════════════════════════════════════════════════════════════

const SHELLS = ["components/shell/WorkspaceShell.tsx", "components/shell/ClientShell.tsx"];

/** Every literal `className="..."` in a source. */
function classLists(src: string): string[] {
  return [...src.matchAll(/className="([^"]*)"/g)].map((m) => m[1]);
}

const CLIPS = /(?<![\w:-])(?:overflow-hidden|overflow-y-auto|overflow-auto|overflow-y-scroll)(?![\w-])/;
const VIEWPORT_HEIGHT = /(?<![\w:-])h-screen(?![\w-])/;
const has = (list: string, token: string) => list.split(/\s+/).includes(token);

/** What a class list that fixes the height to the viewport or clips is missing for print. */
function printGaps(list: string): string[] {
  const gaps: string[] = [];
  if (VIEWPORT_HEIGHT.test(list)) {
    if (!has(list, "print:h-auto")) gaps.push("print:h-auto");
    if (/(?<![\w:-])flex(?![\w-])/.test(list) && !has(list, "print:block")) gaps.push("print:block");
  }
  if (CLIPS.test(list) && !has(list, "print:overflow-visible")) gaps.push("print:overflow-visible");
  return gaps;
}

test("the gap detector reads a class list, not a spelling", () => {
  assert.deepEqual(printGaps("flex h-screen flex-col overflow-hidden bg-ps-bg"),
    ["print:h-auto", "print:block", "print:overflow-visible"], "the shell as it was");
  assert.deepEqual(printGaps("flex flex-col h-screen overflow-hidden bg-ps-bg print:block print:h-auto print:overflow-visible"), []);
  assert.deepEqual(printGaps("min-h-0 flex-1 overflow-y-auto outline-none"), ["print:overflow-visible"], "<main> as it was");
  assert.deepEqual(printGaps("min-h-0 flex-1 overflow-y-auto outline-none print:overflow-visible"), []);
  assert.deepEqual(printGaps("rounded-xl border"), [], "a class list that clips nothing owes nothing");
  assert.deepEqual(printGaps("flex-1 overflow-x-auto"), [], "horizontal scroll of a table is not a clip of the page");
});

for (const rel of SHELLS) {
  test(`${rel}: every class list that fixes the height or clips says how it prints`, () => {
    const lists = classLists(code(rel));
    assert.ok(lists.length >= 2, `${rel}: found ${lists.length} class lists; the frame and <main> are two`);
    const bad = lists.map((l) => ({ l, gaps: printGaps(l) })).filter((x) => x.gaps.length);
    assert.deepEqual(bad, [], `${rel}: a shell frame that is one viewport tall clips a long statement to its first screen`);
    // The vacuity floor: both the frame and <main> are among them.
    assert.ok(lists.some((l) => VIEWPORT_HEIGHT.test(l)), `${rel}: no h-screen frame found`);
    assert.ok(lists.some((l) => CLIPS.test(l) && !VIEWPORT_HEIGHT.test(l)), `${rel}: no scrolling <main> found`);
  });
}

/** Tags a file renders: capitalised JSX elements. */
function renderedComponents(src: string): string[] {
  return [...new Set([...src.matchAll(/<([A-Z][A-Za-z0-9]*)\b/g)].map((m) => m[1]))];
}

/** Everything the page is drawn inside or around: the root layout, the app shell, the two shells. */
const FRAME_FILES = ["app/layout.tsx", "components/AppShell.tsx", ...SHELLS];

/** Not chrome, each with why. The shells and providers draw no box of their own, and a print-only line
 *  must print. */
const NOT_CHROME: Record<string, string> = {
  AuthProvider: "context provider, draws nothing",
  AuthGuard: "renders its children or a redirect, no chrome of its own",
  WorkspaceProvider: "context provider, draws nothing",
  ClientNavProvider: "context provider, draws nothing",
  MonitoringInit: "starts error reporting, renders nothing",
  AppShell: "chooses a shell",
  WorkspaceShell: "the frame: held by the class-list rule above",
  ClientShell: "the frame: held by the class-list rule above",
  PrintHeader: "print-only on purpose: held by the PrintHeader test below",
};

/** Chrome, and where its root class list is, with a token that identifies that list. The proof is that the
 *  list carrying the token also carries `print:hidden`. */
const CHROME: Record<string, { file: string; anchor: string }> = {
  WorkspaceTopBar: { file: "components/shell/WorkspaceTopBar.tsx", anchor: "relative shrink-0" },
  ClientTopBar: { file: "components/shell/ClientTopBar.tsx", anchor: "relative shrink-0" },
  SecureAccountBanner: { file: "components/shell/SecureAccountBanner.tsx", anchor: "px-4 pt-3" },
  SkipToContent: { file: "components/shell/SkipToContent.tsx", anchor: "sr-only" },
  SearchModal: { file: "components/SearchModal.tsx", anchor: "fixed inset-0 z-50" },
  // Toaster renders only a viewport; the class list that places it is in the primitive.
  Toaster: { file: "components/ui/toast.tsx", anchor: "fixed top-0 z-[100]" },
  ConfirmDialogHost: { file: "components/ui/confirm-dialog.tsx", anchor: "fixed inset-0 z-[80]" },
};

test("every component the frame draws is classified: chrome that does not print, or not chrome", () => {
  const drawn = new Set<string>();
  for (const rel of FRAME_FILES) for (const c of renderedComponents(code(rel))) drawn.add(c);
  const classified = new Set([...Object.keys(NOT_CHROME), ...Object.keys(CHROME)]);
  assert.deepEqual([...drawn].filter((c) => !classified.has(c)).sort(), [],
    "a component drawn around the page is chrome until proved otherwise: it prints on every sheet. " +
    "Put `print:hidden` on its root and list it in CHROME, or say why it is not chrome in NOT_CHROME");
  assert.deepEqual([...classified].filter((c) => !drawn.has(c)).sort(), [],
    "a classified component the frame no longer draws: delete its entry so the table only shrinks");
  assert.deepEqual(Object.keys(NOT_CHROME).filter((c) => c in CHROME), []);
});

/** Every double-quoted string literal in a source that contains `anchor`. */
function literalsContaining(src: string, anchor: string): string[] {
  return [...src.matchAll(/"([^"\n]*)"/g)].map((m) => m[1]).filter((s) => s.includes(anchor));
}

for (const [name, { file, anchor }] of Object.entries(CHROME)) {
  test(`${name}: the class list that places it carries print:hidden`, () => {
    assert.ok(existsSync(join(WEB, file)), `${file} is gone`);
    const lists = literalsContaining(code(file), anchor);
    assert.ok(lists.length >= 1, `${file}: no class list containing "${anchor}" - the anchor is stale`);
    for (const l of lists) {
      assert.ok(has(l, "print:hidden"), `${file}: "${l.slice(0, 70)}..." is drawn on every printed sheet`);
    }
  });
}

// ═════════════════════════════════════════════════════════════════════════════
// C. A PRINT BUTTON
// ═════════════════════════════════════════════════════════════════════════════

/** The class lists of the <div> elements that enclose `idx`, outermost first. Div-only on purpose: every
 *  print button here sits in a div, and a stack of one tag is a stack that is hard to get wrong. */
function enclosingDivClasses(src: string, idx: number): string[] {
  const stack: string[] = [];
  const re = /<\/div>|<div\b[^>]*>/g;
  for (let m = re.exec(src); m && m.index < idx; m = re.exec(src)) {
    if (m[0] === "</div>") stack.pop();
    else if (!m[0].endsWith("/>")) stack.push(/className="([^"]*)"/.exec(m[0])?.[1] ?? "");
  }
  return stack;
}

/** The class list of the element whose opening tag contains `idx`. */
function ownClasses(src: string, idx: number): string {
  const open = src.lastIndexOf("<", idx);
  const close = src.indexOf(">", idx);
  const tag = src.slice(open, close + 1);
  return /className="([^"]*)"/.exec(tag)?.[1] ?? "";
}

/** Whether `idx` is inside the callback of a `.map(` that is still open. */
function insideMapCallback(src: string, idx: number): boolean {
  const before = src.slice(0, idx);
  const at = before.lastIndexOf(".map(");
  if (at < 0) return false;
  let depth = 0;
  for (const ch of before.slice(at + 4)) {
    if (ch === "(") depth++;
    else if (ch === ")") depth--;
    if (depth === 0) return false;
  }
  return depth > 0;
}

const PRINT_CALL = /window\.print\(\)/g;

test("the helpers read a button's surroundings", () => {
  const src = `<div className="a"><div className="b print:hidden"><button onClick={() => window.print()}>P</button></div></div><button onClick={() => window.print()}/>`;
  const first = src.indexOf("window.print()");
  assert.deepEqual(enclosingDivClasses(src, first), ["a", "b print:hidden"]);
  const second = src.lastIndexOf("window.print()");
  assert.deepEqual(enclosingDivClasses(src, second), [], "the second button is outside both divs");
  assert.equal(ownClasses(`<button className="x print:hidden" onClick={() => window.print()}>`, 40), "x print:hidden");
  const inMap = `{ROWS.map((r) => (<div><button onClick={() => window.print()} /></div>))}`;
  assert.equal(insideMapCallback(inMap, inMap.indexOf("window.print")), true);
  const afterMap = `{ROWS.map((r) => (<div>{r}</div>))}<button onClick={() => window.print()} />`;
  assert.equal(insideMapCallback(afterMap, afterMap.indexOf("window.print")), false, "the map has closed");
  assert.equal(insideMapCallback(`<button onClick={() => window.print()} />`, 20), false);
});

/** How each file's print button prints, and why it may stay. Frozen: a new window.print() has to be added here with
 *  its reason, and a deleted one has to take its row with it (equality in both directions). */
type How = "page" | "region" | "statement" | "unreachable";
const PRINT_SITES: Record<string, { count: number; how: How; reason: string }> = {
  "app/reports/page.tsx": { count: 1, how: "page",
    reason: "the generated report is the page; its controls and the card header are print:hidden, each report carries its own title" },
  "app/accounting/schedule-iii/page.tsx": { count: 1, how: "page",
    reason: "the statements are the page; a print-only heading names the client and the year" },
  "app/clients/[id]/tax/filing/page.tsx": { count: 1, how: "region",
    reason: "prints the keying sheet only (data-print-scope), under the client's name" },
  "app/clients/[id]/accounting/page.tsx": { count: 3, how: "statement",
    reason: "P&L, Balance Sheet and Cash Flow each print their own statement; the sub-tab bar and the controls are print:hidden" },
  "app/payroll/page.tsx": { count: 1, how: "unreachable",
    reason: "inside PayslipModal, which nothing opens (setViewSlip is only ever called with null); the live payslip is the server PDF" },
};

function printSites(): Record<string, number> {
  const found: Record<string, number> = {};
  for (const rel of sourceFiles([".tsx", ".ts"])) {
    const n = (code(rel).match(PRINT_CALL) ?? []).length;
    if (n) found[rel] = n;
  }
  return found;
}

test("window.print() is called from exactly the screens that are accounted for, and the list only shrinks", () => {
  const expected = Object.fromEntries(Object.entries(PRINT_SITES).map(([k, v]) => [k, v.count]));
  assert.deepEqual(printSites(), expected,
    "a new Print button needs a row here with how it prints; a removed one must take its row with it");
});

for (const [rel, site] of Object.entries(PRINT_SITES)) {
  test(`${rel}: ${site.how} - the Print control is not printed and does not print a list of rows`, () => {
    const src = code(rel);
    const calls = [...src.matchAll(PRINT_CALL)].map((m) => m.index as number);
    assert.equal(calls.length, site.count);
    for (const idx of calls) {
      assert.equal(insideMapCallback(src, idx), false,
        `${rel}: window.print() inside a .map callback prints the SAME page from every row`);
      if (site.how === "unreachable") continue;
      const inherited = [ownClasses(src, idx), ...enclosingDivClasses(src, idx)];
      assert.ok(inherited.some((l) => has(l, "print:hidden")),
        `${rel}: the Print control is itself on the printed page (no print:hidden on it or on a <div> around it)`);
    }
  });
}

test("a statement tab's own chrome is not printed", () => {
  const src = code("app/clients/[id]/accounting/page.tsx");
  const bar = src.indexOf("{TABS.map(");
  assert.ok(bar > 0, "the sub-tab bar moved: re-point this at it");
  assert.ok(enclosingDivClasses(src, bar).some((l) => has(l, "print:hidden")),
    "the sub-tab bar is drawn above every printed statement");
});

test("a screen that prints one region marks the region, and the stylesheet knows the mark", () => {
  const filing = code("app/clients/[id]/tax/filing/page.tsx");
  const from = filing.indexOf("function KeyingSheetPanel");
  const to = filing.indexOf("window.print()", from);
  assert.ok(from > 0 && to > from);
  assert.ok(/data-print-scope/.test(filing.slice(from, to)),
    "KeyingSheetPanel prints, so its root carries data-print-scope - without it Print prints the whole filing screen");
  const css = read("app/globals.css").replace(/\/\*[\s\S]*?\*\//g, "");
  const blocks = printBlocks(css).join("\n");
  assert.match(blocks, /main:has\(\[data-print-scope\]\)/, "the scoped-print rule is gone from globals.css");
  assert.match(blocks, /:not\(\[data-print-header\]\)/, "the rule would drop the client's name");
  assert.match(blocks, /display:\s*none\s*!important/);
  // The files that mark a scope are exactly the files that print one region.
  const marking = sourceFiles([".tsx"]).filter((rel) => /data-print-scope/.test(code(rel)));
  const regions = Object.entries(PRINT_SITES).filter(([, s]) => s.how === "region").map(([k]) => k);
  assert.deepEqual(marking.sort(), regions.sort());
});

test("the payslip modal's Print is still unreachable (or its row must be re-judged)", () => {
  const src = code("app/payroll/page.tsx");
  const calls = [...src.matchAll(/setViewSlip\(\s*([^)]*)\)/g)].map((m) => m[1].trim());
  assert.ok(calls.length >= 1, "the onClose call is the floor: the premise moved");
  assert.deepEqual(calls.filter((a) => a !== "null"), [],
    "something now opens PayslipModal: its Print sits in a fixed overlay inside the shell and must be made to print " +
    "(or deleted) before the 'unreachable' row can go");
});

// ═════════════════════════════════════════════════════════════════════════════
// D. A PRINTOUT NAMES WHOSE BOOKS IT IS
// ═════════════════════════════════════════════════════════════════════════════

test("the client workspace prints the client's name, once, and only on paper", () => {
  const shell = code("components/shell/ClientShell.tsx");
  assert.equal((shell.match(/<PrintHeader\b/g) ?? []).length, 1);
  const main = /<main\b[^>]*>([^]*?)<\/main>/.exec(shell)?.[1] ?? "";
  assert.match(main, /<PrintHeader\s*\/>/, "PrintHeader belongs inside <main>: it prints with the page, ahead of it");
  const fw = code("components/shell/WorkspaceShell.tsx");
  assert.ok(!/PrintHeader/.test(fw), "the firm-level screens are not one client's books; they name their own subject");

  const header = code("components/shell/PrintHeader.tsx");
  const root = /<div\s+data-print-header\s+className="([^"]*)"/.exec(header);
  assert.ok(root, "PrintHeader's root carries data-print-header (the scoped-print rule keeps it)");
  assert.ok(has(root![1], "hidden") && has(root![1], "print:block"), "it is drawn on paper only");
  assert.match(header, /useClientNav\(\)/, "the name comes from the one client lookup");
  assert.match(header, /from "@\/lib\/dates\/format"/, "the date is written by the one date module");
  assert.match(header, /todayIstISO/, "the day is the Indian one");
  assert.match(header, /if \(!client\) return null/, "an unresolved client prints nothing, not a blank label");
  assert.match(header, /"beforeprint"/, "the day is taken when the print starts, not when the page last rendered");
});
