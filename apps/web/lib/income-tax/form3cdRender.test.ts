// Form 3CD clause rendering — the bug was a screen with a JSON.stringify
// fallback and no branch for the two shapes every derived clause actually
// returns: a list, and an object whose own fields need the SAME treatment.
//
// Found live: clause 26 (§43B sums) rendered ~755 duplicated, unformatted
// lines — 29 vendor names each repeated 25-36 times, each one wrapped in
// literal quotes and commas as though a JSON array were dumped as text. The
// duplication itself is fixed upstream, in
// apps/api/domain/income_tax/section_43b_h.py (one gap line per VENDOR, not
// per bill) — these tests are about the OTHER half: even a short, already
// deduplicated gap list must render as a clean list, never as JSON.
import test from "node:test";
import assert from "node:assert/strict";
import { humanizeKey, renderClauseValue } from "./form3cdRender.ts";

test("a plain string or number renders as itself", () => {
  assert.equal(renderClauseValue("business"), "business");
  assert.equal(renderClauseValue(42), "42");
  assert.equal(renderClauseValue(0), "0");
});

test("null and undefined are an em dash, not the word null", () => {
  assert.equal(renderClauseValue(null), "—");
  assert.equal(renderClauseValue(undefined), "—");
});

test("a list of gap sentences is one bulleted line each, not a JSON array", () => {
  const gaps = [
    "Sharma Traders: MSMED classification not recorded, covering 30 bills this year.",
    "Gupta & Sons: 5 bills with no date, so the §15 period cannot be measured.",
  ];
  const out = renderClauseValue(gaps);
  assert.equal(out, `• ${gaps[0]}\n• ${gaps[1]}`);
  // The exact shape of the old bug: JSON.stringify wraps every element in
  // quotes and joins them with a comma.
  assert.doesNotMatch(out, /",\s*"/, "still looks like a JSON array literal");
  assert.doesNotMatch(out, /^\[/, "still opens like a JSON array literal");
});

test("clause 26's own shape — an object whose gaps field is a list — formats both levels", () => {
  // Exactly what services/form_3cd_service.py._clause_22_and_26 hands back
  // for clause "26": {msme_sums_disallowed_paise, gaps: [...]}.
  const clause26Value = {
    msme_sums_disallowed_paise: 1_18_000,
    gaps: [
      "Acme Tools: MSMED classification not recorded, covering 12 bills this year.",
      "Beta Traders: MSMED classification not recorded, covering 3 bills this year.",
    ],
  };
  const out = renderClauseValue(clause26Value);
  assert.match(out, /^Msme sums disallowed paise: 118000$/m,
    "the scalar field reads as a label, not a raw JSON key");
  assert.match(out, /^Gaps: /m);
  assert.match(out, /• Acme Tools: MSMED classification/);
  assert.match(out, /• Beta Traders: MSMED classification/);
  // The defining symptom: no braces, no quoted-and-comma-joined text.
  assert.doesNotMatch(out, /[{}]/, "still looks like a JSON object literal");
  assert.doesNotMatch(out, /",\s*"/, "still looks like a JSON array literal");
});

test("an empty list or object is an em dash, not brackets or braces", () => {
  assert.equal(renderClauseValue([]), "—");
  assert.equal(renderClauseValue({}), "—");
});

test("a boolean reads as Yes/No, not true/false", () => {
  assert.equal(renderClauseValue(true), "Yes");
  assert.equal(renderClauseValue(false), "No");
});

test("humanizeKey turns a snake_case field name into a label", () => {
  assert.equal(humanizeKey("msme_sums_disallowed_paise"), "Msme sums disallowed paise");
  assert.equal(humanizeKey("gaps"), "Gaps");
});

test("a gap sentence's own section citation is never re-cased", () => {
  // humanizeKey is applied to OBJECT KEYS only; renderClauseValue must pass a
  // string value straight through untouched, capital § and all.
  const out = renderClauseValue("§43B(h) reaches a MICRO or SMALL enterprise only.");
  assert.equal(out, "§43B(h) reaches a MICRO or SMALL enterprise only.");
});
