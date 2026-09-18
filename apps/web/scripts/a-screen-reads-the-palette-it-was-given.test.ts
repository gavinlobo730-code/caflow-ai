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
const ARBITRARY_COLOUR_BUDGET = 10152;

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
