// The deductions workspace recomputes when the REQUEST changes, not on every
// keystroke. Run with:
//   node --experimental-strip-types --test scripts/a-computation-refires-only-when-the-request-changes.test.ts
//
// WHY THIS EXISTS (IT-34)
//
//     The effect that calls /api/income-tax/compute — twice, once per regime —
//     depended on the whole of `state`. `state` changes on every keystroke in
//     every field, including a donation's DESCRIPTION, which no computation
//     reads: `Donation80G.description` is carried on the dataclass in
//     apps/api/domain/income_tax/itr_engine.py and never referenced. So typing
//     a donee's name fired two RBAC-gated backend calls per character, 400ms
//     apart.
//
//     The debounce made that survivable and did not make it right. A
//     description typed slowly is one round trip per word.
//
// THE RULE, NOT A LIST OF FIELDS
//
//     The dependency is the serialised REQUEST, with the descriptions
//     stripped. A hand-written dependency array of twenty field names would go
//     stale the first time a field was added — which is how the effect came to
//     depend on `state` in the first place.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const PAGE = fs.readFileSync(
  path.resolve(import.meta.dirname, "../app/income-tax/deductions/page.tsx"),
  "utf8",
);

test("the compute effect does not depend on the whole of state", () => {
  const effect = PAGE.slice(
    PAGE.indexOf("  useEffect(() => {\n    let cancelled = false;"),
    PAGE.indexOf("// Old regime is the only response"),
  );
  assert.ok(effect.length > 0, "the debounced compute effect could not be found");
  assert.ok(!/\}, \[state\]\);/.test(effect),
    "typing a donation description must not re-fire two backend computations");
  assert.match(effect, /\}, \[computeKey\]\);/);
});

test("the dependency is the request, minus what the answer cannot depend on", () => {
  assert.match(PAGE, /const computeKey = useMemo\(\(\) => JSON\.stringify\(\{/);
  const key = PAGE.slice(PAGE.indexOf("const computeKey = useMemo"),
                         PAGE.indexOf("useEffect(() => {\n    let cancelled = false;"));
  assert.ok(!key.includes("description"),
    "a donation's description reaches no figure, warning or total — keying on " +
    "it is the defect this fixes");
  for (const field of ["amount_paise", "deduction_pct",
                       "subject_to_qualifying_limit", "paid_in_cash"]) {
    assert.ok(key.includes(field),
      `${field} DOES change the answer and must stay in the key`);
  }
});

test("the request itself still sends the descriptions", () => {
  // The key is a dependency, not a payload. The API's request shape is the
  // API's, and narrowing it here would be a second change wearing this one's
  // clothes.
  const req = PAGE.slice(PAGE.indexOf("const baseReq = useMemo"),
                         PAGE.indexOf("const computeKey = useMemo"));
  assert.match(req, /description: d\.description/);
});

test("the debounce stays", () => {
  // Narrowing the dependency reduces the number of DISTINCT requests; it does
  // not stop a rupee figure being typed digit by digit.
  assert.match(PAGE, /setTimeout\([\s\S]{0,4000}?\}, 400\);/);
});
