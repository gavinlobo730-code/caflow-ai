// The Profitability screen draws a profit or a margin the server could not give as a dash, computes none of its own,
// says what is missing in the server's words, and lets the Partner set the cost rates without losing a typed one when
// the figures reload (POST-B-321). Run with:
//   node --experimental-strip-types --test scripts/the-profitability-screen-draws-an-unknown-as-a-dash.test.ts
//
// WHY THIS EXISTS
//     The screen printed `formatPaise(c.profit_paise)` and `${c.profit_margin_pct}%` for every client, and under a table
//     whose footnote said "a client with no time recorded shows its whole revenue as profit — that is an absence of data,
//     not a margin": a margin column that drew the absence as 100%. `users.cost_rate_paise` had no screen at all, so there
//     was no way to price an hour. These are the RULES, not a spelling of the calls: nothing nullable is formatted as a
//     number, no money is made out of minutes and rates in the browser, the panel's box is read by the one rate reader,
//     and the panel is never unmounted by the reload it asks for (the shape POST-A-400 records for other screens).
//
//     The vocabulary of a row's status is held from the Python side
//     (`apps/api/tests/test_the_practices_profitability_is_true.py`), which owns it.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const ROOT = path.join(import.meta.dirname, "..");
const PAGE = "app/practice/profitability/page.tsx";
const PANEL = "components/practice/CostRatesPanel.tsx";
const API = "lib/api/index.ts";

const read = (rel: string) => fs.readFileSync(path.join(ROOT, rel), "utf8");
function code(rel: string): string {
  return read(rel)
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

test("a profit or a margin the server may answer null is never formatted as a number", () => {
  const src = code(PAGE);
  assert.doesNotMatch(src, /formatPaise\(\s*\w+\.profit_paise\s*\)/,
    "profit_paise is nullable: it goes through paiseOrDash, never straight into formatPaise");
  // a sum of nothing is not a cost of 0: the server answers null for a cost no hour of which has a rate
  assert.doesNotMatch(src, /formatPaise\(\s*(?:m\.total_cost_paise|c\.cost_paise)\s*\)/,
    "a cost the server may answer null goes through paiseOrDash");
  assert.match(src, /paiseOrDash\(\s*m\.total_cost_paise\s*\)/, "the Cost tile draws a dash for a cost nobody could price");
  assert.match(src, /paiseOrDash\(\s*c\.cost_paise\s*\)/, "so does a client row");
  assert.match(src, /paiseOrDash\(\s*c\.profit_paise\s*\)/, "the client rows draw the profit through paiseOrDash");
  assert.match(src, /paiseOrDash\(\s*m\.profit_paise\s*\)/, "the firm tile draws the profit through paiseOrDash");
  assert.match(src, /c\.profit_margin_pct === null \? DASH/, "a margin the server could not give is a dash");
  const drawn = src.match(/\$\{\s*c\.profit_margin_pct\s*\}%/g) ?? [];
  const guarded = src.match(/c\.profit_margin_pct === null \? DASH : `\$\{c\.profit_margin_pct\}%`/g) ?? [];
  assert.ok(drawn.length > 0 && drawn.length === guarded.length, "an unguarded `${margin}%` prints 'null%'");
  // a loss is judged only on a profit that is known: null < 0 is false in JavaScript, but only by accident
  assert.doesNotMatch(src, /(?<!c\.profit_paise !== null && )c\.profit_paise\s*<\s*0/,
    "a null is not a loss: test `!== null && < 0`");
});

test("the browser makes no money out of minutes, rates or revenue", () => {
  for (const rel of [PAGE, PANEL]) {
    const src = code(rel);
    assert.doesNotMatch(src, /revenue_paise\s*-\s*\w*cost_paise/, `${rel}: profit is the server's`);
    assert.doesNotMatch(src, /\b(minutes|effort_minutes)\b[^;\n]*\*[^;\n]*(rate|paise)/i, `${rel}: cost is the server's`);
    assert.doesNotMatch(src, /\b(?:cost_rate|rate)\w*\s*\*\s*\w*(minutes|hours)/i, `${rel}: same rule, other order`);
  }
});

test("the screen's footnotes are the server's sentences, and the old claim about the cost is gone", () => {
  const src = code(PAGE);
  assert.match(src, /notMeasured\.map\(/, "what the figures are and are not is rendered from the payload");
  assert.doesNotMatch(src, /at its own hourly\s+rate/, "cost is not the rate the hour bills at");
  assert.doesNotMatch(src, /shows its whole revenue as\s+profit/, "the footnote that described a 100% margin as the answer");
});

test("the payload type says null where the server does", () => {
  const api = read(API);
  const block = /export interface ProfitabilityPayload \{[\s\S]*?\n\}\n/.exec(api)?.[0] ?? "";
  assert.ok(block, "ProfitabilityPayload is declared");
  assert.match(block, /profit_paise: number \| null;[\s\S]*profit_margin_pct: number \| null;/);
  assert.match(block, /cost_is_complete: boolean;/);
  assert.match(block, /cost_rates_missing:/);
  assert.match(read(API), /listCostRates: \(\) => request<ApiResp<StaffCostRate\[\]>>/, "the cost-rate list is typed");
});

test("the cost-rate box is read by readRateInput, because a blank must not be stored as 0", () => {
  const src = code(PANEL);
  assert.match(src, /readRateInput\(/);
  assert.doesNotMatch(src, /\bpaiseFromRupeeInput\b/,
    "paiseFromRupeeInput reads a blank as 0: that would say 'these hours cost nothing' and take them off the unknown list");
  assert.match(src, /api\.billing\.setCostRate\(/, "the rate is saved through the server's door");
  assert.doesNotMatch(src, /setBillableRate|listBillableRates/, "this is what an hour COSTS, not what it bills at");
});

test("Save in the cost-rate panel is held while it is out and when nothing has changed, and names the person", () => {
  const src = code(PANEL);
  assert.match(src, /disabled=\{savingKey === m\.id \|\| !changed\}/, "a second click while saving, or a Save with nothing new, does nothing");
  assert.match(src, /changed = m\.id in drafts && drafts\[m\.id\] !== show\(m\.cost_rate_paise\)/, "changed means different from what is stored");
  assert.match(src, /aria-label=\{`Save cost per hour for \$\{name\}`\}/, "fifteen buttons that all say Save do not say whose");
  assert.match(src, /disabled=\{savingKey === m\.id\}/, "the box is held while its own save is out, so text typed then is not thrown away");
  assert.match(src, /role="status"/, "a save is said to a screen reader as well as drawn");
  assert.match(src, /refocus\.current = userId;/, "after a save the person is put back in the box, not dropped to the top of the page");
  assert.match(src, /if \(savingKey === null && refocus\.current\) \{\s*inputs\.current\[refocus\.current\]\?\.focus\(\);/,
    "...once the box is enabled again: a disabled box cannot take focus, and this one is disabled while its own save is out");
  assert.match(src, /aria-invalid=/, "a typed box that is not an amount is marked on its own row");
});

test("the panel is shown to somebody who may SET a rate and to nobody else, and the server's list asks the same", () => {
  const page = code(PAGE);
  assert.match(page, /can\("billing", "write"\)/, "the page asks for billing:write, the permission the server asks");
  assert.match(page, /\{canEditRates && <CostRatesPanel onSaved=\{reload\} \/>\}/, "the panel is mounted for that permission alone");
  assert.doesNotMatch(code(PANEL), /canEdit\b/, "the panel has no read-only mode: a rate is pay-derived and is not shown to a reader");
});

test("a slow answer to an older request cannot overwrite a newer one", () => {
  const src = code(PAGE);
  assert.match(src, /const mine = \+\+requestId\.current;/, "each load takes a number");
  assert.ok((src.match(/mine !== requestId\.current/g) ?? []).length >= 2, "an older answer, and an older failure, are dropped");
  assert.match(src, /if \(mine === requestId\.current\) setLoading\(false\)/, "an older request does not end the newer one's loading state");
  assert.match(src, /loadRef\.current = load/, "a save calls the CURRENT load (the period may have changed since Save was pressed)");
});

test("the panel is not inside any loading branch, so a rate typed in it survives the reload it asks for", () => {
  const sf = ts.createSourceFile(PAGE, read(PAGE), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let panel: ts.Node | undefined;
  const find = (n: ts.Node) => {
    if ((ts.isJsxSelfClosingElement(n) || ts.isJsxOpeningElement(n)) && n.tagName.getText(sf) === "CostRatesPanel") panel = n;
    ts.forEachChild(n, find);
  };
  find(sf);
  assert.ok(panel, "the page mounts <CostRatesPanel>");
  let underRatePermission = false;
  for (let n: ts.Node | undefined = panel.parent; n && !ts.isFunctionDeclaration(n); n = n.parent) {
    if (ts.isBinaryExpression(n) && n.operatorToken.kind === ts.SyntaxKind.AmpersandAmpersandToken) {
      assert.doesNotMatch(n.left.getText(sf), /\bloading\b/,
        "the panel sits inside a `loading` condition: the reload it asks for would unmount it and lose a typed rate");
      if (/\bcanEditRates\b/.test(n.left.getText(sf))) underRatePermission = true;
    }
    if (ts.isConditionalExpression(n)) {
      assert.doesNotMatch(n.condition.getText(sf), /\bloading\b/, "same, as a ternary");
    }
  }
  assert.ok(underRatePermission, "the panel sits under `canEditRates &&`");
  assert.match(code(PAGE), /<CostRatesPanel onSaved=\{reload\} \/>/, "a saved rate reloads the figures");
});
