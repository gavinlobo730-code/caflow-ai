/**
 * A GAP AND A CAVEAT ARE DIFFERENT THINGS, AND THE SCREEN HAS TO SAY WHICH.
 *
 * `app/income-tax/advance-tax/page.tsx` already stated the rule in a comment,
 * and `components/fixed-assets/CwipTab.tsx` stated it again:
 *
 *     GAPS ARE ACTIONABLE AND CAVEATS ARE NOT, and they are rendered
 *     differently for that reason — a mis-headed challan or an unpaid §140A
 *     balance needs doing something about; the statement that the interest
 *     came from the panel above needs reading once.
 *
 * Measured on 18 September over the 48 sites that render one (comments
 * stripped — see `code()` below, which this guard needed on its first run):
 * a GAP wore **11 distinct inks** and a CAVEAT **7**, and **five inks were
 * used for both** — so on the GSTR-3B screen `rule37a.caveats` came out slate (right)
 * while `rule37.interest_caveats` and `r43.caveats` came out amber, the same
 * colour as the gap list two panels above. `RcmDocumentPanel` was the extreme
 * case: its gaps and its caveats carried a BYTE-IDENTICAL class string, two
 * adjacent amber boxes, directly under a comment saying they differ.
 *
 * ── THE RULE, NOT A SPELLING OF IT ──────────────────────────────────────────
 * The fifth time a guard in this repository named a location or a class string
 * instead of its rule, it broke on a change that did not break the rule
 * (CLAUDE.md records four of them, and the GSTR-1 split was the fifth on
 * 18 September). So these tests assert BEHAVIOUR of the one component and a
 * RATCHET on the count of hand-rolled panels — never "file X contains string
 * Y".
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const ROOT = new URL("..", import.meta.url).pathname;

function tsx(dir: string, out: string[] = []): string[] {
  for (const e of readdirSync(join(ROOT, dir))) {
    const rel = join(dir, e);
    if (statSync(join(ROOT, rel)).isDirectory()) tsx(rel, out);
    else if (e.endsWith(".tsx")) out.push(rel);
  }
  return out;
}
const FILES = [...tsx("app"), ...tsx("components")];
const read = (f: string) => readFileSync(join(ROOT, f), "utf8");

/** Source with comments removed. Both of this guard's regexes matched their own
 *  explanation on the first run — `components/ui/drcr.tsx`'s docstring QUOTES
 *  `p >= 0 ? "Dr" : "Cr"` as the thing it fixed, and so does the statement
 *  screen's new comment. A guard that cannot tell code from prose about code
 *  makes the fix unwritable. */
function code(f: string): string {
  return read(f)
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}
const CALLOUT = read("components/ui/callout.tsx");
const DRCR = read("components/ui/drcr.tsx");

// ── 1. A NIL BALANCE IS ON NEITHER SIDE ────────────────────────────────────
// The customer statement read `p >= 0 ? "Dr" : "Cr"`, so a customer who had
// settled every invoice was sent a statement saying "₹0.00 Dr". Zero is not a
// debit balance; it is a square account, and Tally prints no side for it.
test("the Dr/Cr rule answers no side at nil", () => {
  assert.match(
    DRCR,
    /if \(p === null \|\| p === 0\) return null;/,
    "`sideOf` no longer answers null at zero — a settled account is about to " +
      "be described as a debtor on a statement that gets emailed out",
  );
});

test("no screen derives a ledger side from `>= 0`", () => {
  // `>= 0` is the defect itself: it puts nil on the debit side by arithmetic
  // accident. `> 0` is fine — it leaves nil to fall through.
  const SIDE_FROM_SIGN = />=\s*0\s*\?\s*["'`]Dr|>=\s*0\s*\?\s*["'`]debit/;
  const bad = FILES.filter((f) => SIDE_FROM_SIGN.test(code(f)));
  assert.deepEqual(
    bad,
    [],
    "a screen is deciding a normal side from the sign, and calling nil a debit",
  );
});

// ── 2. THE TWO LISTS ARE ONE COMPONENT'S DECISION ──────────────────────────
test("StatutoryNotes gives the two lists different tones, and the caller cannot pick", () => {
  const body = CALLOUT.slice(CALLOUT.indexOf("export function StatutoryNotes"));
  assert.match(body, /gaps=\{g\}\s+tone="attention"/, "the gaps half is not the attention tone");
  assert.match(body, /gaps=\{c\}\s+tone="note"/, "the caveats half is not the note tone");
  assert.doesNotMatch(
    CALLOUT.slice(
      CALLOUT.indexOf("export interface StatutoryNotesProps"),
      CALLOUT.indexOf("export function StatutoryNotes"),
    ),
    /\btone\??:/,
    "StatutoryNotes takes a tone prop again — which is how the distinction " +
      "came to be rendered five ways in the first place",
  );
});

test("a list with nothing in it renders nothing", () => {
  // An empty panel headed "Gaps" reads as a clean bill of health, which is the
  // one thing a gap list must never say by accident.
  assert.match(CALLOUT, /if \(!gaps\.length\) return null;/);
  assert.match(CALLOUT, /if \(!g\.length && !c\.length\) return null;/);
});

test("the component holds no vocabulary of its own", () => {
  // The Schedule III caption mistake, twice recorded in CLAUDE.md: the browser
  // must not keep a list the backend owns. A tone is passed, never looked up
  // from a gap's `kind`.
  const afterTones = CALLOUT.slice(CALLOUT.indexOf("export interface CalloutProps"));
  assert.doesNotMatch(
    afterTones,
    /\bkind\s*===|\bcode\s*===|GAP_[A-Z_]+/,
    "the callout is deciding a tone from a gap's kind — that is the server's",
  );
});

// ── 3. THE RATCHET ─────────────────────────────────────────────────────────
// Not a ban. A ban fails on the first commit and stays failing; a ratchet
// fails only on a change that makes it worse. Both counts are the exact
// figures after the 18 September adoption — no headroom, deliberately, because
// headroom is what let the last budget pass a regression silently.
const HAND_ROLLED_GAP_PANELS = 18;   // 33 on origin/main
const HAND_ROLLED_CAVEAT_PANELS = 12; // 15 on origin/main

function countMaps(needle: RegExp): number {
  let n = 0;
  for (const f of FILES) {
    if (f.endsWith("ui/callout.tsx")) continue;
    n += (code(f).match(needle) ?? []).length;
  }
  return n;
}

test("hand-rolled gap panels only ever go down", () => {
  const n = countMaps(/\bgaps\.map\(/g);
  assert.ok(
    n <= HAND_ROLLED_GAP_PANELS,
    `${n} sites render a gap list by hand, up from ${HAND_ROLLED_GAP_PANELS}. ` +
      "Use `GapList` (it takes a string, a {reason} or a {code, message}) " +
      "rather than a fifth amber div.",
  );
  if (n < HAND_ROLLED_GAP_PANELS) {
    console.log(`  note: down to ${n} — lower HAND_ROLLED_GAP_PANELS to it.`);
  }
});

test("hand-rolled caveat panels only ever go down", () => {
  const n = countMaps(/\bcaveats\.map\(/g);
  assert.ok(
    n <= HAND_ROLLED_CAVEAT_PANELS,
    `${n} sites render a caveat list by hand, up from ${HAND_ROLLED_CAVEAT_PANELS}. ` +
      "Where the payload carries both, `StatutoryNotes` renders the pair.",
  );
});

// ── 4. THE GUARDS ARE NOT VACUOUS ──────────────────────────────────────────
// Each regex is exercised against a string written HERE, so the test cannot go
// inert the day the codebase stops containing an example. The colour guard's
// vacuity check asserted the tree was still dirty, and would have gone quiet
// the moment the migration finished; this is that lesson applied.
test("the guards fire on the defect they name", () => {
  const SIDE_FROM_SIGN = />=\s*0\s*\?\s*["'`]Dr|>=\s*0\s*\?\s*["'`]debit/;
  assert.ok(SIDE_FROM_SIGN.test(`const b = (p) => \`\${r(p)} \${p >= 0 ? "Dr" : "Cr"}\``));
  assert.ok(!SIDE_FROM_SIGN.test(`const b = (p) => (p > 0 ? "Dr" : p < 0 ? "Cr" : "")`));

  assert.equal((`{x.gaps.map((g) => <p/>)}`.match(/\bgaps\.map\(/g) ?? []).length, 1);
  assert.equal((`{x.caveats.map((c) => <p/>)}`.match(/\bcaveats\.map\(/g) ?? []).length, 1);
  // `statutory_gaps.map(` must NOT be counted twice by the gaps regex.
  assert.equal((`{x.statutory_gaps.map((g) => <p/>)}`.match(/\bgaps\.map\(/g) ?? []).length, 0);
});
