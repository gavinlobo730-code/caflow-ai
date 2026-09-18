// The design tokens are the palette, and a screen reads them rather than
// spelling a colour.
//
// Run with:
//   node --experimental-strip-types --test scripts/a-screen-reads-the-palette-it-was-given.test.ts
//
// WHAT WAS WRONG
//     `tailwind.config.ts` and `app/globals.css` have carried a complete
//     PracticeSync palette since the app was built — deep blue #182350, powder
//     #AFD2FA, premium gold #B9915E, a typographic scale, the shadcn tokens —
//     and almost nothing read it. The tree held **10,933 raw hex literals
//     across 263 files**, and the banking module, 5,783 lines of the product's
//     busiest screen, used the tokens ZERO times. So the app rendered in
//     shadcn's default slate and looked like a template rather than like
//     PracticeSync, while three different "primary" colours were live at once:
//     the brand navy in the config, indigo #4338CA in banking, blue-700 on the
//     Team screen.
//
//     That is the same failure this codebase keeps finding one layer down —
//     one authority, nothing reads it, copies drift — and it had the same two
//     causes. The authority was INSUFFICIENT (`ps` had surfaces and no ink, no
//     state colours, no single primary), so every file invented what it
//     needed; and nothing checked.
//
// WHAT THIS GUARD STATES, AND WHY IT IS A LIST OF DIRECTORIES
//     Banking is the reference implementation and is held at zero. The rest of
//     the app is a ratchet on the TOTAL, which may only go down: a sweeping
//     "no hex anywhere" assertion would have to be switched off on the day it
//     was written, and a guard that is off is not a guard. Converting a
//     directory means adding it to TOKENISED and lowering the total in the
//     same commit.
//
//     THE RULE IS ABOUT TAILWIND ARBITRARY VALUES, NOT ABOUT HEX. A hex used
//     as DATA — a chart series, an inline SVG fill, a PDF colour — is a value
//     and not a class, and forbidding it would push authors into worse
//     workarounds. What is forbidden is `text-[#0F172A]`, which is a colour
//     decision taken where no designer will ever see it.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(import.meta.dirname, "..");

/** Directories held at ZERO arbitrary-value colours. Add one when it converts. */
const TOKENISED = [
  "components/banking",
  "app/clients/[id]/bank",
  "components/team",
];

/** The whole-app ceiling. It may only go DOWN.
 *
 *  MEASURED, not chosen. It was 10,283 before this commit; banking and the
 *  Team screens converting took it to 10,152, and this is that figure. A budget
 *  set to a round number above the real one is a budget with slack in it, which
 *  is a ratchet that does not ratchet. */
const ARBITRARY_COLOUR_BUDGET = 10151;

/** `text-[#0F172A]`, `hover:bg-[#F1F5F9]/50` — a colour inside a Tailwind class. */
const ARBITRARY_COLOUR = /[a-z-]+-\[#[0-9A-Fa-f]{3,8}\]/g;

function walk(dir: string, out: string[] = []): string[] {
  let entries: fs.Dirent[];
  try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return out; }
  for (const e of entries) {
    if (e.name === "node_modules" || e.name === ".next") continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out);
    else if (e.name.endsWith(".tsx") || e.name.endsWith(".ts")) out.push(p);
  }
  return out;
}

function arbitraryColours(file: string): string[] {
  return fs.readFileSync(file, "utf8").match(ARBITRARY_COLOUR) ?? [];
}

test("the reference implementations spell no colours of their own", () => {
  for (const dir of TOKENISED) {
    const offenders: string[] = [];
    for (const file of walk(path.join(ROOT, dir))) {
      const found = arbitraryColours(file);
      if (found.length) offenders.push(`${path.relative(ROOT, file)}: ${found.slice(0, 4).join(", ")}`);
    }
    assert.deepEqual(offenders, [],
      `${dir} must read the tokens in tailwind.config.ts. A colour spelled here ` +
      `is a design decision taken where no designer will see it, and it is how ` +
      `three different primaries came to be live at once.`);
  }
});

test("the rest of the app only ever holds fewer", () => {
  let total = 0;
  const worst: [number, string][] = [];
  for (const file of walk(path.join(ROOT, "app")).concat(walk(path.join(ROOT, "components")))) {
    const n = arbitraryColours(file).length;
    total += n;
    if (n) worst.push([n, path.relative(ROOT, file)]);
  }
  worst.sort((a, b) => b[0] - a[0]);
  assert.ok(total <= ARBITRARY_COLOUR_BUDGET,
    `${total} arbitrary colours, budget ${ARBITRARY_COLOUR_BUDGET}. Worst: ` +
    `${JSON.stringify(worst.slice(0, 5))}. Lower the budget when you convert a ` +
    `directory; raising it needs a reason.`);
});

test("a token a screen names actually exists", () => {
  // FOUND WHILE CONVERTING A NEW PANEL, and it is the OTHER half of this
  // guard's own rule. Reading the palette is only worth anything if the name
  // read is a name the palette holds: Tailwind emits NOTHING for a class it
  // does not know, silently, so `text-ps-state-problem` renders an error
  // message in whatever colour it inherits and `bg-ps-accent text-white` is a
  // white Save button on no background at all. Both were live.
  //
  // The mistake is one letter of structure: `state` and `money` are their own
  // groups in tailwind.config.ts, NOT children of `ps`, so the right classes
  // are `text-state-problem` and `text-money-in` — and there is no `ps-accent`
  // at all, the brand primary being `brand`. Five files had it, including this
  // very commit's own new panel, which is why the guard is the fix rather than
  // the five edits.
  //
  // THE TOKEN LIST IS READ OFF THE CONFIG rather than restated here. A second
  // copy of the vocabulary is the exact failure the whole file is about.
  const config = fs.readFileSync(path.join(ROOT, "tailwind.config.ts"), "utf8");
  const groups = ["ps", "state", "money", "brand", "gold"];
  const known = new Set<string>();
  for (const group of groups) {
    // The group's object literal: `ps: { ... }` up to the closing brace at the
    // same indent. Comments inside are ignored by the key pattern below.
    const open = config.indexOf(`\n        ${group}: {`);
    if (open === -1) { known.add(group); continue; }
    const close = config.indexOf("\n        },", open);
    const body = config.slice(open, close === -1 ? undefined : close);
    known.add(group);                                    // `bg-brand`, bare
    for (const m of body.matchAll(/^\s*"?([a-z][a-z0-9-]*)"?:\s*"/gm)) {
      known.add(m[1] === "DEFAULT" ? group : `${group}-${m[1]}`);
    }
  }
  // A vacuity floor: if the config parse silently found nothing, the scan
  // below would pass on every file.
  assert.ok(known.size >= 25, `only ${known.size} tokens parsed from the config`);

  const USED = new RegExp(
    `\\b(?:hover:|focus:|active:|group-hover:|disabled:|dark:)*` +
    `(?:text|bg|border|ring|fill|stroke|from|via|to|decoration|outline|divide|placeholder|accent|caret|shadow)-` +
    `(${groups.join("|")})-([a-z0-9-]+)`, "g");

  const offenders: string[] = [];
  for (const file of walk(path.join(ROOT, "app")).concat(walk(path.join(ROOT, "components")))) {
    const src = fs.readFileSync(file, "utf8");
    for (const m of src.matchAll(USED)) {
      const token = `${m[1]}-${m[2]}`;
      // Tailwind opacity (`text-ps-ink/70`) and the arbitrary-value form are
      // handled by the character class, which stops at `/` and `[`.
      if (!known.has(token)) offenders.push(`${path.relative(ROOT, file)}: ${token}`);
    }
  }
  assert.deepEqual(offenders, [],
    "These classes name a colour token that tailwind.config.ts does not define, " +
    "so Tailwind emits nothing and the element renders in whatever it inherits. " +
    "`state` and `money` are top-level groups, not children of `ps`; the brand " +
    "primary is `brand`.");
});

test("the token-exists guard is not vacuous", () => {
  // The negative control, inline: a class the config certainly does not hold
  // must be caught by the same parse the test above uses.
  const config = fs.readFileSync(path.join(ROOT, "tailwind.config.ts"), "utf8");
  assert.ok(!/\n\s+"?accent"?:\s*"/.test(
    config.slice(config.indexOf("\n        ps: {"), config.indexOf("\n        },", config.indexOf("\n        ps: {")))),
    "`ps.accent` now exists — the guard above needs revisiting, not this one deleting.");
});

test("the token set can express what a screen needs", () => {
  // The reason the palette went unread for so long is that it could not say
  // what a screen had to say — `ps` held four surfaces and no ink, so every
  // file reached for its own slate. These are the roles the banking conversion
  // proved were required; a token removed here sends the next author straight
  // back to a hex literal.
  const config = fs.readFileSync(path.join(ROOT, "tailwind.config.ts"), "utf8");
  for (const token of [
    // ink, four steps — three collapsed a hover convention used at 104 sites
    "ink:", "body:", "label:", "hint:", "disabled:",
    // surfaces
    "bg:", "surface:", "muted:", "hover:", "border:",
    // state: what a CA reads before they read any text
    "ready:", "attention:", "problem:", "done:",
    // money DIRECTION, which is not state — a withdrawal is not a problem
    "in:", "out:", "negative:",
  ]) {
    assert.ok(config.includes(token),
      `tailwind.config.ts no longer defines ${token} — the banking conversion ` +
      `needed it, so removing it pushes the next screen back to a hex literal.`);
  }
});

test("money direction is not the state palette", () => {
  // Found while converting banking: a first pass mapped "Deposits" to the ready
  // green and "Withdrawals" to the problem red, because those were the greens
  // and reds that file happened to hold. Both are false signals — a withdrawal
  // is half of what a bank account does, not something wrong — so the two
  // scales must stay distinct values, not aliases.
  const config = fs.readFileSync(path.join(ROOT, "tailwind.config.ts"), "utf8");
  const value = (name: string) => {
    const m = config.match(new RegExp(`"?${name}"?:\\s*"(#[0-9A-Fa-f]{6})"`));
    return m?.[1] ?? null;
  };
  const moneyIn = value("in"), moneyOut = value("out");
  const ready = value("ready"), problem = value("problem");
  assert.ok(moneyIn && moneyOut && ready && problem, "all four tokens must be defined");
  assert.notEqual(moneyIn, ready, "money in must not be the 'act on this' green");
  assert.notEqual(moneyOut, problem, "money out must not be the 'something is wrong' red");
});
