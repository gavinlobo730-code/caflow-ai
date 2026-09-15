/**
 * WHICH REGIME IS CHEAPER IS NOT THE SAME QUESTION AS WHAT CHOOSING IT
 * REQUIRES, and the browser answers neither.
 *
 * §115BAC(6) with Rule 21AGA: since AY 2024-25 the new regime is the DEFAULT.
 * A client WITH business or professional income opts out in FORM 10-IEA by the
 * §139(1) due date and has one return journey for life; a client WITHOUT such
 * income opts out in the return itself, with no form and no lock-out.
 *
 * The rule has lived in `domain/income_tax/regime_election.py` since it was
 * written with NO CALLER. Every figure, date and sentence on this panel comes
 * from `GET /api/income-tax/regime-election`.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const ROOT = join(import.meta.dirname, "..");
/** Prose is not a decision. The panel's docstring EXPLAINS §115BAC(6)'s two
 *  clauses, which is the whole point of writing it down — scanning the raw
 *  file for a rule "being decided here" fired on that explanation. The same
 *  stripper the stock-transfer guard uses, for the same reason. */
function withoutComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
    .split("\n")
    .map((l) => l.replace(/(^|\s)\/\/.*$/, "$1"))
    .join("\n");
}

const PANEL_RAW = readFileSync(join(ROOT, "components/tax/RegimeElectionPanel.tsx"), "utf8");
const PANEL = withoutComments(PANEL_RAW);
const PAGE = readFileSync(join(ROOT, "app/clients/[id]/tax/computation/page.tsx"), "utf8");
const API = readFileSync(join(ROOT, "lib/api/index.ts"), "utf8");

test("the panel asks the server and its ANSWER reaches the screen", () => {
  // Not merely that the call appears: the result must be awaited into a
  // variable and that variable must be what fills the state. The call text
  // surviving inside a dead branch is enough to satisfy a bare match, which
  // is how the first draft of this test passed on a panel that had stopped
  // using the answer.
  assert.match(PANEL, /const res = await api\.incomeTax\.regimeElection\(/,
    "the endpoint's answer must be captured");
  assert.match(PANEL, /setData\(res\.data\)/,
    "the captured answer must be what the panel renders from");
  assert.match(PANEL, /data\.reasons\.map\(/, "the server's sentences must be rendered");
  assert.match(PANEL, /\{r\}/, "each reason must reach the page");
});

test("no statutory rule is decided in the browser", () => {
  // The two clauses of §115BAC(6), the form, the deadline and the lock-out are
  // the server's. A browser that re-derived any of them would be a second
  // implementation of a rule whose failure is invisible in the return.
  const forbidden: [RegExp, string][] = [
    [/115BAC\s*\(\s*6\s*\)\s*\(/, "names a clause of §115BAC(6) and so is deciding between them"],
    [/hasBusinessIncome\s*\?\s*["'`]form_10iea/, "picks the route itself"],
    [/route\s*=\s*["'`]form_10iea/, "assigns the route itself"],
    [/"31-07"|31 July|31 October|October 31/, "spells a §139(1) due date"],
    [/election_is_available\s*=\s*(true|false)/, "decides availability itself"],
    [/history_unknown\s*=\s*(true|false)/, "decides whether the history is known"],
  ];
  for (const [re, why] of forbidden) {
    assert.ok(!re.test(PANEL), `the panel ${why}`);
  }
});

test("the due date is displayed, never computed", () => {
  assert.match(PANEL, /data\.due_date/, "the server's date must be shown");
  assert.ok(!/new Date\(|Date\.now|toISOString/.test(PANEL),
    "a date built in the browser is a second copy of the §139(1) rule");
});

test("an unknown prior history is a DISTINCT state from an unavailable option", () => {
  // Collapsing them is the dangerous direction: it would show a CA the old
  // regime as open when their client spent the option years ago.
  assert.match(PANEL, /history_unknown/);
  assert.match(PANEL, /election_is_available/);
  assert.ok(!/history_unknown\s*(\|\||&&)\s*!?\s*data\.election_is_available\s*\?[^:]*:\s*[^}]*\bsame\b/.test(PANEL));
  // They drive different presentation, so one cannot silently stand in for the
  // other.
  const tone = PANEL.slice(PANEL.indexOf("const tone"), PANEL.indexOf("return ("));
  assert.ok(tone.includes("election_is_available") && tone.includes("history_unknown"),
    "both states must be distinguishable on screen");
});

test("prior elections are SENT, not assumed", () => {
  assert.match(PANEL, /prior,?\s*\}\)/s, "the prior list must travel to the server");
  assert.match(API, /for \(const one of q\.prior \?\? \[\]\) p\.append\("prior", one\)/,
    "each prior election is a repeated query parameter");
  // Nothing may default the history to "available" on the way out.
  assert.ok(!/prior:\s*\[["'`]/.test(PANEL),
    "the panel must not seed a prior election the CA did not state");
});

test("the panel sits with the regime picker on the computation screen", () => {
  assert.match(PAGE, /<RegimeElectionPanel[\s/>]/, "the panel must be mounted");
  const picker = PAGE.indexOf('<option value="old">Old Regime</option>');
  const panel = PAGE.indexOf("<RegimeElectionPanel");
  assert.ok(picker > 0 && panel > picker,
    "the consequences of the choice belong beside the control that makes it");
});

test("the business-income fact is read off the screen, not asked twice", () => {
  // §115BAC(6)'s two clauses turn entirely on this one fact, and the
  // computation screen already has it.
  assert.match(PAGE, /hasBusinessIncome=\{[^}]*businessIncome[^}]*\}/,
    "the panel must take the figure the CA already entered");
});

test("the endpoint is a GET", () => {
  const block = API.slice(API.indexOf("regimeElection: (q: {"));
  const scoped = block.slice(0, block.indexOf("\n    },"));
  assert.ok(!/method:\s*"POST"/.test(scoped),
    "it reads and writes nothing, so it must not be a POST — a POST would " +
    "need an entry on the compute-only allowlist that every preview earns");
  assert.match(scoped, /\/api\/income-tax\/regime-election\?/);
});
