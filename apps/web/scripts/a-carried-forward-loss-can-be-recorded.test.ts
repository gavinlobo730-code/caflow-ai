/**
 * The computation screen can RECORD a brought-forward loss, not only list one.
 *
 * `brought_forward_losses` was read by this screen and written by nothing —
 * POST /api/itr/bf-losses has existed all along with no caller — so the panel
 * said "No carried-forward losses recorded" for every client, for ever, while
 * the engine behind it applied §72, §73, §74 and §71B correctly.
 *
 * WHAT THE BROWSER MUST NOT DECIDE
 *   How long a loss lives. §72(3) gives eight assessment years, §73(4) gives a
 *   SPECULATION loss FOUR, §74(2) and §71B eight. The old label on this panel
 *   was hardcoded as "§72 (Business, 8 yrs) · §74 (Capital, 8 yrs)" — true of
 *   three heads and silent about the fourth — which is exactly how four becomes
 *   eight. The vocabulary, the sections and every period now come from
 *   GET /api/itr/loss-types, and the expiry is derived server-side unless the
 *   CA deliberately sets one.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const PAGE = path.join(WEB, "app/clients/[id]/tax/computation/page.tsx");

function withoutComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
    .split("\n")
    .map((l) => l.replace(/(^|\s)\/\/.*$/, "$1"))
    .join("\n");
}

const raw = fs.readFileSync(PAGE, "utf8");
const code = withoutComments(raw);

test("a carried-forward loss can be recorded", async (t) => {
  await t.test("the screen posts to the endpoint that existed with no caller", () => {
    assert.match(code, /"\/api\/itr\/bf-losses"/,
      "nothing writes brought_forward_losses — the panel is read-only again");
    assert.match(code, /method:\s*"POST"/);
    assert.match(code, /original_amount_paise/);
  });

  await t.test("the amount goes through the one money parser", () => {
    // Math.round(parseFloat(x) * 100) reads "1,25,000" as ₹1.
    assert.match(code, /paiseFromRupeeInput\(lossForm\.amount\)/);
    assert.ok(!/lossForm\.amount\s*\)\s*\*\s*100/.test(code));
  });

  await t.test("the vocabulary and the sections are the server's", () => {
    assert.match(code, /"\/api\/itr\/loss-types"/);
    assert.match(code, /lossTypes\.map\(/, "the head dropdown is not built from the server's list");
    // No head, no section and no period spelled in the browser.
    for (const p of [/"business"/, /"speculation"/, /"capital_long_term"/,
                     /§72/, /§73/, /§74/, /§71B/, /8 yrs/, /4 yrs/]) {
      assert.ok(!p.test(code), `${p} is hardcoded in the screen`);
    }
  });

  await t.test("the expiry is omitted unless the CA set one", () => {
    // Sending a value always would defeat the server's derivation; sending an
    // empty string would fail the AY validator.
    assert.match(code, /lossForm\.expiry\s*\?\s*\{\s*expiry_assessment_year:/,
      "the expiry is not conditional — the derivation is bypassed or an empty AY is sent");
  });

  await t.test("the head's own rule is shown before saving", () => {
    // A CA picking "speculation" should see it is four years and reaches only
    // speculation income, in the server's words, before they commit.
    assert.match(code, /lossTypes\.find\(t => t\.loss_type === lossForm\.loss_type\)\?\.note/);
  });

  await t.test("the years that have no row at all are named", () => {
    // §32(2) and §73A carry forward indefinitely and are not in the stored
    // vocabulary, so the screen says why rather than inviting `other`.
    assert.match(code, /lossNotModelled\.map\(/);
    for (const p of [/unabsorbed depreciation/i, /73A/, /indefinitel/i]) {
      assert.ok(!p.test(code), `${p} is written into the screen`);
    }
  });

  await t.test("the year pickers come from the clock", () => {
    // THE RULE, NOT A SPELLING OF IT. This asserted the literal call
    // `assessmentYearChoicesAround(null, 10)`, which broke on 18 Sep when both
    // pickers became `<PeriodPicker kind="ay" count={10}>` — a component that
    // calls that very helper. The rule is that the list is DERIVED, whether
    // the screen derives it or a component does.
    assert.match(
      code,
      /assessmentYearChoicesAround\(null,\s*1[02]\)|<PeriodPicker[^>]*kind="ay"/,
      "the assessment-year lists are no longer derived from the clock",
    );
    assert.ok(!/value="20\d\d-\d\d"/.test(code), "a year is hardcoded as an option");
  });

  await t.test("the comment strip does not make the scan vacuous", () => {
    assert.ok(code.length > raw.length / 2, "too much of the file was stripped");
    assert.match(code, /const saveLoss = async/);
  });
});
