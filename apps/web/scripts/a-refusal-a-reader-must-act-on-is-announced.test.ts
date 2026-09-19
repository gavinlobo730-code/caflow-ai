/**
 * A FAILURE THE READER HAS TO ACT ON IS ANNOUNCED.
 *
 * ── THE DEFECT ──────────────────────────────────────────────────────────────
 * A CA presses Save, the server refuses, and the refusal is painted somewhere
 * on the page in red. To somebody using a screen reader nothing happens at
 * all: focus is still in the form, the page reports no change, and the only
 * evidence that anything went wrong is a coloured band they cannot see. On
 * 19 September 2026 there were 176 such bands and exactly ONE of them carried
 * `role="alert"`.
 *
 * Both primitives that exist for this already get it right — `Callout
 * tone="problem"` sets `role="alert"` (and only that tone does, deliberately:
 * a note about Table 12 must not be announced over a CA reading a return),
 * and `ErrorState` sets it too. What was missing was callers. `tone="problem"`
 * had ONE in the whole product, on the GSTR-1 findings panel; every other
 * screen hand-rolled its own silent band, 79 differently-spelled ones.
 *
 * ── WHY THE RULE IS "ANNOUNCED" AND NOT "USES THE PRIMITIVE" ────────────────
 * Adopting `Callout` is a design preference and belongs with the screens the
 * owner reviews. Being announced is a correctness property, and it is the one
 * worth holding at CI. So a hand-rolled band passes here IF it carries
 * `role="alert"` — which is what the four public auth screens do, because
 * their icon bubble is a considered part of a page a stranger sees and
 * dropping it for a primitive is a visible change on a sign-in form.
 *
 * ── THE BUDGET IS NOW NIL ───────────────────────────────────────────────────
 * The last 21 were finished by hand. Each has a CONSIDERED shape the primitive
 * does not have — a Retry button, a Dismiss control, a heading over a list of
 * problems, a `<Card>`, or a sentence of extra prose — so each took
 * `role="alert"` and nothing else moved. That is the rule this file states,
 * and adopting `Callout` on top of it is a design preference that belongs with
 * the screens the owner reviews.
 *
 * It stays a RATCHET rather than a flat ban so the failure message keeps
 * saying what to do; the budget is EXACT, because slack lets a regression in
 * silently — which is how the colour budget passed one last week.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const WEB = join(import.meta.dirname, "..");

function walk(dir: string, out: string[] = []): string[] {
  for (const e of readdirSync(join(WEB, dir))) {
    if (e === "node_modules" || e === ".next") continue;
    const rel = join(dir, e);
    if (statSync(join(WEB, rel)).isDirectory()) walk(rel, out);
    else if (rel.endsWith(".tsx")) out.push(rel);
  }
  return out;
}
const FILES = [...walk("app"), ...walk("components")];

/** Comments first. A guard that reads its own prose is a guard that passes on
 *  a tree full of the defect, and three in this repo have done exactly that. */
function code(rel: string): string {
  return readFileSync(join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

/** `{somethingError && <tag …>` — the shape every one of these bands has. The
 *  variable is matched on what it MEANS (err / error / failed / problem), not
 *  on one spelling: the tree holds `err`, `error`, `saveError`, `loadFailed`,
 *  `computeError`, `presError`, `reauthError` and a dozen more. */
const GUARD = /\{\s*\w*(?:rr|rror|ailed|roblem)\w*\s*&&\s*\(?\s*<(\w+)\s+([^>]*?)>/gi;
/** A RED GROUND is what makes it a refusal rather than red text in a table
 *  cell — a negative figure is not a failure, and `text-red-600` alone is on
 *  hundreds of perfectly correct money columns. */
const GROUND = /\bbg-(?:red|rose)-(?:50|100|200)\b/;

function silentBands(): { file: string; attrs: string }[] {
  const out: { file: string; attrs: string }[] = [];
  for (const f of FILES) {
    for (const m of code(f).matchAll(GUARD)) {
      const attrs = m[2];
      if (GROUND.test(attrs) && !/role="alert"/.test(attrs)) out.push({ file: f, attrs });
    }
  }
  return out;
}

/** EXACT, no headroom. Lower it when you fix one; never raise it. */
const SILENT_REFUSAL_BANDS = 0;

test("no NEW refusal band may be silent", () => {
  const found = silentBands();
  assert.ok(
    found.length <= SILENT_REFUSAL_BANDS,
    `${found.length} hand-rolled refusal bands announce nothing to a screen ` +
    `reader (budget ${SILENT_REFUSAL_BANDS}). A refusal the reader must act ` +
    `on is announced: render it with <Callout tone="problem"> (or ` +
    `<ErrorState>), or put role="alert" on the element you have.\n  ` +
    found.slice(0, 12).map((b) => b.file).join("\n  "),
  );
  assert.equal(
    found.length, SILENT_REFUSAL_BANDS,
    `${found.length} left, budget ${SILENT_REFUSAL_BANDS} — lower the budget ` +
    "in this file to what you achieved, so the next regression fails here.",
  );
});

test("the two primitives announce, which is what makes them the fix", () => {
  const callout = code("components/ui/callout.tsx");
  assert.match(callout, /role=\{tone === "problem" \? "alert" : undefined\}/,
    "Callout must announce the problem tone and only the problem tone — a " +
    "note read out over a CA is worse than one they scroll past");
  assert.match(code("components/ui/states.tsx"), /role="alert"/,
    "ErrorState is the region-sized half of the same rule");
});

test("the probe finds the bands it is about", () => {
  // A regex that matches nothing passes the ratchet for ever. This asserts the
  // probe still reaches real markup — the money-formatter guard passed on a
  // tree full of the defect for exactly this reason.
  const announced = FILES.flatMap((f) =>
    [...code(f).matchAll(GUARD)].filter(
      (m) => GROUND.test(m[2]) && /role="alert"/.test(m[2])),
  );
  assert.ok(announced.length >= 8,
    `only ${announced.length} announced hand-rolled bands found; the probe has ` +
    "stopped seeing them (a changed guard spelling, or a moved directory)");
});

test("the four public sign-in screens announce their refusal", () => {
  // These are the ones a stranger meets, and the only feedback on a wrong
  // password. They keep their own markup — the icon bubble is a considered
  // part of a client-facing page — so the rule is stated on the outcome.
  for (const f of [
    "app/login/page.tsx",
    "app/login/forgot-password/page.tsx",
    "app/signup/page.tsx",
    "app/auth/reset-password/page.tsx",
    "app/portal/login/page.tsx",
    "app/portal/activate/page.tsx",
    "app/sign/page.tsx",
  ]) {
    const bands = [...code(f).matchAll(GUARD)].filter((m) => GROUND.test(m[2]));
    assert.ok(bands.length > 0, `${f} no longer has a refusal band to check`);
    for (const b of bands) {
      assert.match(b[2], /role="alert"/,
        `${f} refuses silently — on a sign-in form the band IS the feedback`);
    }
  }
});
