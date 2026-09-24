// A register is as wide as the register (D11).
//
// THE MEASUREMENT THAT MADE THIS A RULE. 59 pages rendered a DataTable or a
// <table> inside a centred container and did it at NINE different widths:
//
//     19  max-w-7xl      7  max-w-4xl      2  max-w-[1400px]
//     15  max-w-5xl      3  max-w-3xl      2  max-w-2xl
//      8  max-w-6xl      2  max-w-screen-2xl   1  max-w-xl
//
// from 576px to 1400px, with no rule behind the spread — each page picked one
// when it was written, usually by copying the page beside it. `payroll/reports`
// rendered a table inside 576px on a 1440 screen. A register that cannot show
// its columns is the one thing a CA reading a ledger cannot work around.
//
// WHAT THIS ASSERTS
//
// One token, `max-w-ps-data`, on every centred container that holds a table —
// unless that container is NAMED below with a reason. The value then moves in
// `tailwind.config.ts` rather than in 59 files, and the nine widths cannot
// re-accumulate: a new data screen written with `max-w-5xl` because that is
// what its neighbour had fails here.
//
// WHY THE EXCEPTIONS ARE A LIST AND NOT A PREDICATE. "Holds a table" is what a
// scan can see; "IS a register" is the rule, and the two come apart in one
// direction only — a page can hold a small computed working (a two-limb §18(6)
// comparison, a tax reconciliation) inside what is really a form or a
// single-column list. No regex tells those apart, so each is named with the
// reason it is not a register, and the list may only SHRINK.
//
// WHAT THIS DELIBERATELY DOES NOT ASSERT: the reading half — "prose and forms
// keep a 65-75 character measure". Of 102 pages that centre a container,
// exactly ONE ran to a data width without holding a table, and that page
// renders its rows through a custom component rather than table markup, so it
// is a limit of this scan and not a page to narrow. A classifier good enough
// to tell prose from a card grid is a judgement, not a regex.
//
// Run with: node --experimental-strip-types --test scripts/a-page-is-as-wide-as-what-it-holds.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const APP = path.join(__dirname, "..", "app");

/**
 * Centred containers that hold table markup and are NOT registers. Each entry
 * is one route and the reason, and the count below is a ratchet.
 *
 * A route appears here when SOME container in it is exempt; the scan cannot
 * attribute a width to a tab body, so the exemption is per file. That is the
 * honest granularity — see the two `clients/[id]` entries, where the exempt
 * container was converted anyway BECAUSE its siblings were, and only one
 * container per file is genuinely a reading measure.
 */
const NOT_A_REGISTER: Record<string, string> = {
  "portal/employee":
    "The employee portal. One person's own payslips and §192 working, read " +
    "top to bottom — self-scoped and read-only by construction (PAY-26). A " +
    "personal document at 1600px is a reading measure thrown away.",
};

/** Pages whose grid is a row of cards and which hold no table at all. Listed,
 *  not silently skipped, so a page that LATER grows one is caught. */
const GRID_BUT_NOT_A_REGISTER = new Set([
  "settings/branding", "work", "time", "workflows/approvals",
  "clients/[id]/tax/26as",
]);

function pages(dir: string, acc: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) pages(p, acc);
    else if (e.name === "page.tsx") acc.push(p);
  }
  return acc;
}

/** Every centred container's max-width, in file order. A tabbed screen has one
 *  per tab body, and they must agree or the page reflows as you switch tabs. */
function containerWidths(src: string): string[] {
  const out: string[] = [];
  for (const m of src.matchAll(/className=(?:"([^"]*)"|\{`([^`]*)`\})/g)) {
    const cls = m[1] ?? m[2] ?? "";
    if (!cls.includes("mx-auto") || !cls.includes("max-w-")) continue;
    for (const w of cls.match(/max-w-[\w[\]%.-]+/g) ?? []) out.push(w);
  }
  return out;
}

const ALL = pages(APP).map((file) => {
  const src = fs.readFileSync(file, "utf8");
  return {
    route: path.relative(APP, path.dirname(file)),
    widths: containerWidths(src),
    table: /<DataTable|<table/.test(src),
  };
});

/** A width a page PICKED, as against the token or an unrelated utility measure
 *  (`max-w-sm` on a caption, `max-w-2xl` on a centred error card). Only the
 *  container sizes the nine-width spread was measured over count. */
const PICKED = /^max-w-(3xl|4xl|5xl|6xl|7xl|screen-|\[)/;

test("the scan still finds the pages, so nothing below passes vacuously", () => {
  assert.ok(ALL.length > 120, `only ${ALL.length} pages found — the walk is wrong`);
  const centred = ALL.filter((p) => p.widths.length > 0);
  assert.ok(centred.length > 80,
    `only ${centred.length} pages centre a container — the matcher is wrong`);
  const onToken = ALL.filter((p) => p.widths.includes("max-w-ps-data"));
  assert.ok(onToken.length > 50,
    `only ${onToken.length} pages use the token — the conversion is not what ` +
    `this guard was written against`);
});

test("a register is as wide as the register", () => {
  const wrong = ALL.filter((p) => p.table && !(p.route in NOT_A_REGISTER))
                   .flatMap((p) => p.widths.filter((w) => PICKED.test(w))
                                           .map((w) => `${p.route} (${w})`));
  assert.deepEqual(wrong, [],
    "these render a table inside a hand-picked width. Use `max-w-ps-data` — " +
    "one token, so the figure moves in tailwind.config.ts and not in 59 " +
    "files. If it is genuinely not a register, name it in NOT_A_REGISTER " +
    "with the reason.");
});

test("the token is declared once, and it is the D11 figure", () => {
  const cfg = fs.readFileSync(path.join(__dirname, "..", "tailwind.config.ts"), "utf8");
  assert.match(cfg, /"ps-data":\s*"1600px"/,
    "the data width lives in the token file, not in 59 pages");
});

test("the exemption list only shrinks, and every entry is real", () => {
  // A budget, not a door. An exemption added rather than removed is the nine
  // widths coming back one page at a time.
  assert.ok(Object.keys(NOT_A_REGISTER).length <= 1,
    "a new exemption — convert the page, or make the case in the review");
  for (const [route, why] of Object.entries(NOT_A_REGISTER)) {
    const p = ALL.find((x) => x.route === route);
    assert.ok(p, `${route} is exempted here and no longer exists — remove it`);
    assert.ok(p!.table,
      `${route} holds no table, so it was never in scope — remove it`);
    assert.ok(why.length > 60, `${route}'s reason says too little to check`);
  }
});

test("the grid-only pages stay listed, so an exemption cannot outlive its reason", () => {
  for (const route of GRID_BUT_NOT_A_REGISTER) {
    const p = ALL.find((x) => x.route === route);
    assert.ok(p, `${route} is exempted here and no longer exists — remove it`);
    assert.equal(p!.table, false,
      `${route} now renders a table, so it is a register after all: give it ` +
      `max-w-ps-data and take it off this list`);
  }
});
