// The pages a person sees before they are inside the product wear one named style, white words on it stay where
// they read, and the sign-in says nothing about who uses the product (POST-A-446).
//
// Run with:
//   node --experimental-strip-types --test scripts/a-front-door-page-wears-the-front-door.test.ts
//
// WHAT WAS WRONG
//     The invitation page drew a blue-to-indigo wash from three Tailwind classes written on that one page, and the
//     owner asked on 15-11-2026 for it to be kept and used on the other front-door pages. A second copy of a literal
//     is how this codebase's palette drifted before (tailwind.config.ts records 10,933 raw hex literals in 263 files),
//     so the wash is ONE named style, `bg-front-door`, and `components/FrontDoor.tsx` is the one layout that wears
//     it; the sign-in page draws its own two columns on the same style.
//
//     The sign-in page also closed on "© 2026 PracticeSync AI — Trusted by accounting firms across India", the first
//     thing a practising CA would read at the demo, and no firm used the product. Its first feature line said "All
//     compliance in one place" of a product that prepares returns for the CA to file and holds professional tax for
//     four states. Both are gone, and the claim half of this guard is what keeps a sentence about who uses the product
//     off every page listed here.
//
// WHAT IT STATES
//     1. The wash's own stops, read from the config, give white text 4.5:1 (WCAG 1.4.3) or better wherever
//        (x/w + y/h) / 2 is at most 0.75, which is the top half and the left half of the page, and do NOT give it at
//        the bottom-right corner. Both figures are computed, so moving a stop is checked, and the second is why a
//        word on the wash sits above the card or in the left half.
//     2. Every front-door page wears it, through the layout or the named style, and its error boundary does too.
//     3. Nothing else wears it: never behind a working screen, where it would compete with figures.
//     4. A word on the wash is white: the wordmark, the sign-in page's left half, the engagement letter's heading.
//     5. No front-door page says anything about who uses the product.
//     6. The literal the invitation page used to carry is written nowhere.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(import.meta.dirname, "..");
const read = (rel: string) => fs.readFileSync(path.join(ROOT, rel), "utf8");

/** The pages a person sees before they are inside the product, and how each wears the wash. */
const PAGES: Record<string, "layout" | "style"> = {
  "app/login/page.tsx": "style",
  "app/signup/page.tsx": "layout",
  "app/login/forgot-password/page.tsx": "layout",
  "app/auth/reset-password/page.tsx": "layout",
  "app/portal/login/page.tsx": "layout",
  "app/portal/activate/page.tsx": "layout",
  "app/portal/employee/activate/page.tsx": "layout",
  "app/sign/page.tsx": "layout",
  "app/join/page.tsx": "layout",
  "app/not-found.tsx": "layout",
};

/** The error boundaries of the signed-out trees. */
const ERROR_BOUNDARIES = [
  "app/login/error.tsx",
  "app/signup/error.tsx",
  "app/join/error.tsx",
  "app/sign/error.tsx",
  "app/auth/error.tsx",
  "app/portal/error.tsx",
];

/** Files allowed to name the layout or the style besides the pages: the layout itself and the boundary it serves. */
const MACHINERY = ["components/FrontDoor.tsx", "components/ModuleErrorBoundary.tsx"];

function stripComments(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`])\/\/.*$/gm, "$1");
}

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(path.join(ROOT, dir), { withFileTypes: true })) {
    const rel = path.join(dir, e.name);
    if (e.isDirectory()) {
      if (e.name === "node_modules") continue;
      walk(rel, out);
    } else if (/\.(tsx?|jsx?)$/.test(e.name) && !/\.test\.tsx?$/.test(e.name)) {
      out.push(rel);
    }
  }
  return out;
}

// ── 1. contrast, computed from the config's own stops ───────────────────────────────────────────────────────────

function wash(): { direction: string; stops: string[] } {
  const config = read("tailwind.config.ts");
  const m = /"front-door":\s*"linear-gradient\(([^)]*)\)"/.exec(config);
  assert.ok(m, "tailwind.config.ts no longer declares backgroundImage.front-door as a linear gradient");
  const parts = m[1].split(",").map((p) => p.trim());
  return { direction: parts[0], stops: parts.slice(1) };
}

function rgb(hex: string): number[] {
  const h = hex.replace("#", "");
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
}

function luminance(c: number[]): number {
  const lin = c.map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
}

function contrast(a: number[], b: number[]): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** The wash's colour at position t along its line, the stops evenly spaced as CSS spaces stops with no position. */
function colourAt(stops: string[], t: number): number[] {
  const cs = stops.map(rgb);
  const seg = Math.min(cs.length - 2, Math.floor(t * (cs.length - 1)));
  const f = t * (cs.length - 1) - seg;
  return cs[seg].map((v, i) => v + (cs[seg + 1][i] - v) * f);
}

const WHITE = [1, 1, 1];

test("the wash runs to the bottom right, so (x/w + y/h) / 2 is where a point falls on it", () => {
  const { direction, stops } = wash();
  assert.equal(direction, "to bottom right",
    "the region rule below assumes `to bottom right`; a different direction moves where white reads");
  assert.ok(stops.every((s) => /^#[0-9A-Fa-f]{6}$/.test(s)), `every stop is a plain six-digit hex: ${stops.join(", ")}`);
});

test("white reads at 4.5:1 or better over the top half and the left half of the wash", () => {
  const { stops } = wash();
  // The worst point of the top half (x/w = 1, y/h = 0.5) and of the left half (x/w = 0.5, y/h = 1) are both 0.75.
  for (let i = 0; i <= 75; i++) {
    const t = i / 100;
    const ratio = contrast(WHITE, colourAt(stops, t));
    assert.ok(ratio >= 4.5, `white on the wash at ${t.toFixed(2)} is ${ratio.toFixed(2)}:1, below WCAG 1.4.3's 4.5:1`);
  }
});

test("white does NOT read at the bottom-right corner, which is why no word sits there", () => {
  // Not a goal: a statement of the region rule's reason. If a stop moves and this starts passing, the comment in
  // tailwind.config.ts and components/FrontDoor.tsx should be loosened with it rather than left warning of nothing.
  const { stops } = wash();
  assert.ok(contrast(WHITE, colourAt(stops, 1)) < 4.5);
});

// ── 2 and 3. who wears it ─────────────────────────────────────────────────────────────────────────────────────

test("every front-door page wears the wash, and so does each signed-out tree's error boundary", () => {
  for (const [file, how] of Object.entries(PAGES)) {
    const src = stripComments(read(file));
    if (how === "layout") {
      assert.match(src, /<FrontDoor[\s>]/, `${file} does not render <FrontDoor>`);
    } else {
      assert.match(src, /\bbg-front-door\b/, `${file} does not wear bg-front-door`);
    }
    assert.doesNotMatch(src, /\bbg-ps-bg\b[^"]*min-h-screen|min-h-screen[^"]*\bbg-ps-bg\b/,
      `${file} still draws a full-height page on the plain application background`);
  }
  for (const file of ERROR_BOUNDARIES) {
    assert.match(stripComments(read(file)), /<ModuleErrorBoundary[^>]*\bfrontDoor\b/, `${file} does not pass frontDoor`);
  }
});

test("no other error page wears the wash: a copied error.tsx would draw it beside the navigation", () => {
  // The boundary's `frontDoor` prop is the style by another door. 43 error pages exist and a new one is made by copying one,
  // so the set that passes it is held equal to the six signed-out trees' (the independent review of 16-11-2026).
  const passing = walk("app").filter((f) => f.endsWith("/error.tsx") && /<ModuleErrorBoundary[^>]*\bfrontDoor\b/.test(stripComments(read(f))));
  assert.deepEqual(passing.sort(), [...ERROR_BOUNDARIES].sort());
});

test("nothing else wears the wash: never behind a working screen", () => {
  const allowed = new Set([...Object.keys(PAGES), ...MACHINERY]);
  const offenders: string[] = [];
  for (const file of [...walk("app"), ...walk("components"), ...walk("lib")]) {
    if (allowed.has(file)) continue;
    const src = stripComments(read(file));
    if (/\bbg-front-door\b/.test(src) || /<FrontDoor[\s>]/.test(src) || /<FrontDoorWordmark[\s>]/.test(src)) {
      offenders.push(file);
    }
  }
  assert.deepEqual(offenders, [], "these files wear the front door and are not a page a person sees before they are inside");
});

test("the boundary's front-door branch tells nobody to use a navigation a signed-out page does not have", () => {
  const src = stripComments(read("components/ModuleErrorBoundary.tsx"));
  const branch = src.slice(src.indexOf("if (frontDoor)"), src.indexOf("return (", src.indexOf("if (frontDoor)") + 30));
  assert.ok(branch.includes("<FrontDoor"), "the front-door branch is not where this guard expects it");
  assert.doesNotMatch(branch, /navigation/i);
});

// ── 4. words on the wash are white ──────────────────────────────────────────────────────────────────────────────

const SIZE_OR_ALIGN = new Set(["xs", "sm", "base", "lg", "xl", "2xl", "3xl", "4xl", "2xs", "3xs", "center", "left", "right"]);

function colourClasses(fragment: string): string[] {
  return [...fragment.matchAll(/(?<![\w:-])text-([a-z0-9-]+(?:\/\d+)?)/g)]
    .map((m) => m[1])
    .filter((c) => !SIZE_OR_ALIGN.has(c));
}

test("a word on the wash is white", () => {
  const door = stripComments(read("components/FrontDoor.tsx"));
  const mark = door.slice(door.indexOf("export function FrontDoorWordmark"), door.indexOf("export function FrontDoor("));
  assert.deepEqual([...new Set(colourClasses(mark))], ["white"], "the wordmark");

  const login = stripComments(read("app/login/page.tsx"));
  const start = login.indexOf("hidden lg:flex");
  const end = login.indexOf("<FrontDoorWordmark", start);
  assert.ok(start > 0 && end > start, "the sign-in page's left half is not where this guard expects it");
  assert.deepEqual([...new Set(colourClasses(login.slice(start, end)))], ["white"], "the sign-in page's left half");

  const sign = stripComments(read("app/sign/page.tsx"));
  const open = sign.indexOf("<FrontDoor");
  const firstCard = sign.indexOf("{loading &&", open);
  assert.ok(open > 0 && firstCard > open, "the engagement letter's heading is not where this guard expects it");
  assert.deepEqual([...new Set(colourClasses(sign.slice(open, firstCard)))], ["white"], "the engagement letter's heading");
});

test("below its heading the engagement letter puts nothing on the wash but white surfaces", () => {
  // `card={false}`: the page draws its own cards, so each of its top-level blocks must open on a white surface. Read by the
  // page's own layout (its direct children are indented six spaces): a line there that is neither the heading, a
  // conditional block opening on `bg-white`, nor its close, is something drawn straight on the wash (the "Powered by"
  // line this change removed, in grey, would be one).
  const src = read("app/sign/page.tsx");
  const body = src.slice(src.indexOf("<FrontDoor"), src.indexOf("</FrontDoor>")).split("\n").slice(1);
  const offenders: string[] = [];
  let inHeading = false;
  body.forEach((line, i) => {
    if (!/^ {6}\S/.test(line)) return;
    const text = line.trim();
    if (text.startsWith("{/*") || text === ")}") return;
    if (text.includes("text-white") && text.startsWith("<div")) { inHeading = true; return; }
    if (inHeading && text === "</div>") { inHeading = false; return; }
    if (/^\{.*&& \($/.test(text) && /bg-white/.test(body[i + 1] ?? "")) return;
    offenders.push(text);
  });
  assert.deepEqual(offenders, []);
});

test("the sign-in page's right column is the wordmark and the card, and nothing after the card", () => {
  const login = stripComments(read("app/login/page.tsx"));
  const column = login.indexOf("flex-1 flex items-center justify-center");
  const card = login.indexOf("rounded-2xl bg-white p-8 shadow-2xl", column);
  assert.ok(column > 0 && card > column, "the sign-in page's right column is not where this guard expects it");
  const before = login.slice(column, card);
  assert.deepEqual(colourClasses(before), [], "a word above the card in the right column");
  assert.match(before, /<FrontDoorWordmark className="lg:hidden mb-6" \/>/);
  assert.match(login, /<\/p>\s*<\/div>\s*<\/div>\s*<\/div>\s*<\/div>\s*\);\s*\}\s*$/,
    "something follows the card in the right column, on the wash, where the bottom-right corner reads at 2.5:1");
});

// ── 5. no claim about who uses the product ─────────────────────────────────────────────────────────────────────

const CLAIMS: RegExp[] = [
  /trusted by/i,
  /used by/i,
  /loved by/i,
  /relied on by/i,
  /across india/i,
  /\b(?:leading|top|no\.?\s*1|number one)\b[^"<]{0,40}\b(?:firms?|practices?|platform|software)\b/i,
  /\b\d[\d,.]*\s*(?:\+|k\b|lakh|crore)?\s*(?:firms|practices|cas\b|chartered accountants|clients|users|businesses|customers)\b/i,
  /all compliance/i,
  /returns prepared/i,
  /ready to (?:file|upload)/i,
];

test("no front-door page says anything about who uses the product", () => {
  const offenders: string[] = [];
  for (const file of [...Object.keys(PAGES), ...MACHINERY]) {
    const src = stripComments(read(file));
    for (const re of CLAIMS) {
      const m = re.exec(src);
      if (m) offenders.push(`${file}: "${m[0]}"`);
    }
  }
  assert.deepEqual(offenders, []);
});

test("the claim patterns catch the sentences they were written for", () => {
  // A negative control on the patterns themselves, so a pattern that silently matches nothing is caught here.
  const shipped = [
    "© 2026 PracticeSync AI — Trusted by accounting firms across India",
    "All compliance in one place",
    "Used by 500+ CA firms",
    "India's leading practice software",
    "Returns prepared from the books, filed by you on the portal",
  ];
  for (const sentence of shipped) {
    assert.ok(CLAIMS.some((re) => re.test(sentence)), `no pattern catches: ${sentence}`);
  }
  for (const fine of ["Sign in to view your documents, invoices and statements.", "Client health, deadlines, revenue"]) {
    assert.ok(!CLAIMS.some((re) => re.test(fine)), `a pattern catches an ordinary sentence: ${fine}`);
  }
});

// ── 6. one copy ───────────────────────────────────────────────────────────────────────────────────────────────

test("the wash is written once, in the config, and no page spells it with Tailwind classes", () => {
  const offenders = [...walk("app"), ...walk("components"), ...walk("lib")].filter((f) =>
    /from-blue-600[^"]*via-indigo-900|via-indigo-900[^"]*to-blue-400/.test(read(f)));
  assert.deepEqual(offenders, []);
});
