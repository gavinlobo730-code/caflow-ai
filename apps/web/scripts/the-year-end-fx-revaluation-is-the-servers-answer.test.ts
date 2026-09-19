/**
 * THE FX REVALUATION PANEL COMPUTES NOTHING.
 *
 * AS 11 paragraph 11 retranslates a monetary item at the closing rate on the
 * balance sheet date; paragraph 13 takes the difference to the P&L. Every
 * figure on this panel — the exposure, the target, what has already been
 * posted, the delta, and every refusal — comes from
 * `POST /api/fx-revaluation/preview`, which runs the same walk the posting
 * path posts from. The closing rate is the only thing typed, because it is
 * the one fact no ledger holds.
 *
 * The engine was built, tested and unreachable: `revalue()` is the only writer
 * of `fx_revaluations` and had zero production importers, so the Unrealized
 * report this panel now sits above was a structural nil for every client.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

// `import.meta.dirname`, not `__dirname`: the suite runs under
// `node --experimental-strip-types --test`, where the file is an ES module
// and `__dirname` is not defined. It passed under `npx tsx` and failed
// under the real runner — the sibling guards all use this form.
const ROOT = join(import.meta.dirname, "..");
const PANEL = readFileSync(join(ROOT, "components/accounting/FxRevaluationPanel.tsx"), "utf8");
const PAGE = readFileSync(join(ROOT, "app/clients/[id]/accounting/page.tsx"), "utf8");
const API = readFileSync(join(ROOT, "lib/api/index.ts"), "utf8");

test("the panel asks the server for the plan and never builds one", () => {
  assert.match(PANEL, /fxRevaluation\.preview\(/,
    "the panel must ask POST /api/fx-revaluation/preview");
  assert.match(PANEL, /fxRevaluation\.run\(/,
    "the panel must post through POST /api/fx-revaluation/run");
});

test("no exchange arithmetic happens in the browser", () => {
  // THE RULE, not a spelling of it. The delta is `target - prior` and the
  // target is `foreign x rate - carrying`; either computed here would be a
  // second implementation of AS 11 that disagrees with what gets posted the
  // first time a rounding rule moves. So NO figure the server planned may
  // appear next to an arithmetic operator — a list of specific expressions
  // missed `carrying_base_paise + (r.target_paise ?? 0)` on the first draft.
  const FIGURES = [
    "foreign_outstanding", "carrying_base_paise", "target_paise",
    "prior_paise", "delta_paise", "closing_rate",
  ];
  for (const f of FIGURES) {
    // LEFT OPERAND. Every figure is in the list, so any binary operation
    // BETWEEN two of them is caught here from the left-hand one.
    // OP excludes JSX tag syntax: the `/` in `</td>` and `/>` is not division,
    // and reading it as one fired this test on `{r.foreign_outstanding}</td>`.
    const OP = "(?:[-+*]|(?<!<)/(?![>/]))";
    const after = new RegExp(`${f}[^\\n"]{0,12}?${OP}\\s*[\\w(]`);
    // RIGHT OPERAND with a literal on the left (`2 * r.delta_paise`). The gap
    // is deliberately tiny and forbids a quote: a longer one matched the
    // HYPHEN inside a Tailwind class name — `text-right ...>{r.foreign_...}` —
    // and failed this test on correct code. `-` is left out of this direction
    // entirely, because a leading minus is a sign and a binary one is already
    // caught above.
    const before = new RegExp(`${OP}\\s{0,2}[\\w.$(]{0,6}${f}`);
    assert.ok(!after.test(PANEL) && !before.test(PANEL),
      `the panel does arithmetic on ${f} — the server's plan is the answer`);
  }
  // `Math.abs` on a delta is presentation (which colour, which sign glyph),
  // not arithmetic, and is the one thing allowed to touch a figure.
  assert.ok(!/Math\.(round|floor|ceil)\(/.test(PANEL),
    "rounding a figure in the browser is re-deciding a statutory rounding rule");
});

test("the rate is sent as TYPED, not parsed into a number in the browser", () => {
  // An exchange rate is a decimal the backend reads with Decimal(str(...)).
  // Turning it into a JS float here is the `Math.round(parseFloat(x) * 100)`
  // defect in a different unit.
  assert.ok(!/parseFloat|Number\(\s*rates/.test(PANEL),
    "the closing rate must travel as the string the CA typed");
});

test("every refusal rendered is the server's sentence", () => {
  // MENTIONED IS NOT RENDERED. Asserting the key appears passed even with the
  // map replaced by an empty array, because the name still sits in the
  // interface declaration above.
  assert.match(PANEL, /\{plan\.refusal\}/, "the gate refusal must be rendered");
  // THE RULE, NOT A SPELLING OF IT. This asserted `plan.rate_gaps.map(`, which broke on
  // 18 Sep when the panel moved to `<GapList>` — a change that renders the
  // same sentences and does not break the rule. Sixth time in this repo;
  // CLAUDE.md records the other five. What matters is that the array
  // REACHES a renderer, however it is spelled.
  assert.match(PANEL, /\bgaps=\{plan\.rate_gaps\}|plan\.rate_gaps\.map\(/,
    "each rate gap must be rendered");
  assert.match(PANEL, /\{plan\.period_problem\}/, "the period refusal must be rendered");
  // MENTIONED IS NOT RENDERED still holds, and `<GapList gaps={…}>` satisfies
  // it differently from a local `.map`: the sentences are rendered by a
  // component whose own guard asserts it renders them and returns null for an
  // empty list. So the rule here is that the array reaches THAT renderer —
  // asserting a literal `{g}` would now only be asserting the old spelling.
  assert.match(
    PANEL,
    /<GapList[^>]*gaps=\{plan\.rate_gaps\}|\{g\}/,
    "the rate-gap sentences must reach a renderer that renders them",
  );
  // And it must not invent its own wording for the gates — Settings is where
  // a Partner fixes them, and the server's sentence already says so.
  assert.ok(!/multi_currency_entitled|multi_currency_enabled/.test(PANEL),
    "the panel must not re-derive which gate is down");
});

/** The RENDER block for a view, not the `else if` that only collects its
 *  currency options — the loose anchor matched that one first and sliced the
 *  wrong region, which is how this guard passed on nothing in its first
 *  draft. */
function renderBlock(view: string): string {
  const start = PAGE.indexOf(`\n  if (view === "${view}") {`);
  assert.ok(start > 0, `no render block for the ${view} view`);
  const rest = PAGE.slice(start + 1);
  const end = rest.indexOf("\n  if (view === ");
  return end > 0 ? rest.slice(0, end) : rest;
}

test("the panel is rendered on the Unrealized view, which reads what it writes", () => {
  assert.match(PAGE, /<FxRevaluationPanel[\s/>]/, "the panel must be mounted");
  const unrealized = renderBlock("unrealized");
  assert.ok(unrealized.includes("<FxRevaluationPanel"),
    "the action belongs with the report that reads fx_revaluations");
  for (const other of ["exposure", "realized", "open"]) {
    assert.ok(!renderBlock(other).includes("<FxRevaluationPanel"),
      `the panel must not appear on the ${other} view`);
  }
});

test("the empty Unrealized report is no longer the whole answer", () => {
  // Before the door existed, an empty table was all a CA saw and it meant
  // "nothing has ever been revalued" — indistinguishable from "there is
  // nothing to revalue". The panel is rendered in the empty case too.
  const unrealized = renderBlock("unrealized");
  const empty = unrealized.indexOf("<FXEmpty />");
  assert.ok(empty > 0, "the empty state should still exist");
  assert.ok(unrealized.slice(0, empty).includes("panel"),
    "the panel must render alongside the empty state, not instead of nothing");
});

test("both API methods POST and carry the client in the query string", () => {
  const block = API.slice(API.indexOf("fxRevaluation: {"));
  const scoped = block.slice(0, block.indexOf("\n    },"));
  assert.match(scoped, /preview:[\s\S]*method: "POST"/);
  assert.match(scoped, /run:[\s\S]*method: "POST"/);
  assert.ok((scoped.match(/client_id=\$\{encodeURIComponent\(clientId\)\}/g) || []).length === 2,
    "both must scope to the client and encode it");
});

test("the run button is disabled until every rate is in and the period is open", () => {
  assert.match(PANEL, /disabled=\{[^}]*missing[^}]*\}/,
    "a missing closing rate must disable the post");
  assert.match(PANEL, /disabled=\{[^}]*blocked[^}]*\}/,
    "a locked period must disable the post");
});

test("re-running is described as the correction path, not a duplicate", () => {
  // The engine posts only the delta needed to reach the new target. A CA who
  // believes a second run duplicates will avoid the button after a rate
  // changes, and the accounts stay wrong. The whole clause is asserted: the
  // first draft matched on a fragment that survived being rewritten into its
  // own opposite.
  assert.ok(
    PANEL.includes("posts only the difference, never a") &&
    /never a\s*\n?\s*second entry/.test(PANEL),
    "the panel must say that re-running corrects rather than duplicates");
  assert.ok(!/may duplicate|will duplicate|be careful/i.test(PANEL),
    "the panel must not warn a CA off the correction path");
});
