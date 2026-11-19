// What the independent review of the dialog sweep (POST-A-473) found in its own change. Run with:
//   node --experimental-strip-types --test scripts/a-late-answer-never-lands-in-another-dialog-and-a-failed-reread-is-not-a-failed-save.test.ts
//
//   1. The capital-gains exemption dialog can be closed while its READ is out (a dialog is held over a write only). A late answer then
//      landed in whichever record's dialog was open next: A's gain, exemption and claims shown as B's. Each read takes a number, closing
//      takes the next, only the latest answer is shown, and opening a record clears what was there.
//   2. The health override dialog stayed held through the re-read that follows its write, so a re-read that failed was shown as a failed
//      save and a second press posted a second override. The hold ends with the write; the re-read is outside it and says what it is.
//   3. The rule had lost the word "filing" from its write flags, which let the Mark as Filed dialog fall out of its scan.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const WEB = join(import.meta.dirname, "..");
const read = (rel: string) => readFileSync(join(WEB, rel), "utf8");

test("a late exemption answer is shown only if its read is still the latest, and opening a record clears the last one", () => {
  const s = read("app/income-tax/capital-gains/page.tsx");
  assert.match(s, /const seq = \+\+exemptionSeq\.current;/);
  assert.equal((s.match(/if \(seq !== exemptionSeq\.current\) return;/g) ?? []).length, 2, "the answer and the failure are both ignored when stale");
  assert.match(s, /if \(seq === exemptionSeq\.current\) setExemptLoading\(false\);/);
  assert.match(s, /async function openExemption\(r: CapitalGainsRecord\) \{\s*setExemption\(null\);/);
  assert.match(s, /exemptionSeq\.current \+= 1; setExemptFor\(null\); setExemption\(null\); setExemptLoading\(false\);/, "closing takes the next number");
});

test("the override dialog's hold ends with the write and its re-read is outside it", () => {
  const s = read("app/health/[client_id]/HealthDetailClient.tsx");
  const at = s.indexOf("async function handleAddOverride()");
  const fn = s.slice(at, s.indexOf("async function handleRemoveOverride"));
  assert.ok(fn.indexOf("written = true") > 0 && fn.indexOf("written = true") < fn.indexOf("finally"), "saved is known before the hold is let go");
  assert.ok(fn.indexOf("if (written)") > fn.indexOf("finally"), "the re-read is after the hold");
  assert.doesNotMatch(fn.slice(0, fn.indexOf("finally")), /await loadOverrides\(\)/, "no re-read inside the held block");
  assert.match(s, /\{!overrideModalOpen && overrideSaveError && /, "what the dialog said is said on the page once it has closed");
});

test("the rule knows a filing flag, and the Mark as Filed backdrop stops its click", () => {
  assert.match(read("scripts/dialogHolds.ts"), /posting\|issuing\|filing\|recording/);
  assert.match(read("app/tds/returns/page.tsx"), /onClick=\{\(e\) => \{ e\.stopPropagation\(\); if \(!filing\) setShowFiledModal\(false\); \}\}/);
});

test("a landed charge cannot be removed twice while the list is re-read", () => {
  assert.match(read("components/purchases/LandedCostPanel.tsx"), /onClick=\{\(\) => remove\(c\)\} disabled=\{saving \|\| busy\}/);
});
