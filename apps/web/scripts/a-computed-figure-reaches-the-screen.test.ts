/**
 * A FIGURE THE ENGINE GETS RIGHT AND NO SCREEN SHOWS IS NOT A FIXED BUG.
 *
 * CLAUDE.md states that rule about the GSTR-3B computer. This pins it for
 * three more cases the 12 September probe pass found, all the same shape: the
 * hard half landed, the surfacing did not, and the finding file recorded the
 * work as done.
 *
 *   IT-08's own working. `basic_exemption_absorbed_paise` and
 *   `basic_exemption_absorption` were computed and documented as existing "so
 *   a CA can see WHICH gain the exemption was set against … a choice a reader
 *   is entitled to check". A grep across the routers and the whole frontend
 *   found no reader at all, so the tax workspace printed ₹20,800 on a
 *   ₹5,00,000 STCG and said nothing about the ₹4,00,000 that had gone.
 *
 *   Exempt income. The Tax Computation tab renders an input, sends it, the
 *   router declares it, the engine's request declares it — and `compute()`
 *   never read it. A live field that changes nothing, silently.
 *
 *   Part-month depreciation on a disposal. `dispose` returns
 *   `part_month_depreciation_not_charged` precisely so the CA is told the gain
 *   is a whole month short; `grep -rn part_month apps/web` returned nothing.
 *
 * These are three spellings of one rule and the rule cannot be scanned for, so
 * this asserts the three by name. Each entry is a claim somebody made: a
 * screen that stops rendering one of them fails here rather than going quiet.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");

function code(file: string): string {
  return fs.readFileSync(path.join(WEB, file), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

test("the tax computation tab renders the basic-exemption absorption", () => {
  const page = code("app/clients/[id]/tax/computation/page.tsx");
  assert.match(page, /capital_gains/,
    "the capital-gains working must be read from the compute response");
  assert.match(page, /basic_exemption_absorption/,
    "the per-gain explanation is the point — a total the CA cannot check is " +
    "what IT-08 already produced");
  assert.match(page, /basic_exemption_absorbed_paise/);
});

test("the tax computation tab says what it did with exempt income", () => {
  const page = code("app/clients/[id]/tax/computation/page.tsx");
  assert.match(page, /exempt_income_paise/, "the input is still sent");
  assert.match(page, /exempt_income\??\.[a-z_]*reported_paise|exempt_income!/,
    "and the result must say the figure was received. §10 income is not part " +
    "of total income, so the tax is right without it — but a field that is " +
    "live, sent and then invisible reads as a field that does something.");
});

test("a disposal says whether part-month depreciation went uncharged", () => {
  const page = code("app/clients/[id]/fixed-assets/page.tsx");
  assert.match(page, /part_month_depreciation_not_charged/,
    "the server computes this so the CA is told the gain is a whole month " +
    "short — depreciation posts whole months, Schedule II Note 3 making the " +
    "purchase month the only pro-rated one");
});

test("the employee form can record both statutory exceptions", () => {
  // PAY-12 residual. Both columns are NOT NULL DEFAULT true (migrations 295,
  // 298) and both are read by the engine; neither was on a form, so the
  // exception could not be recorded anywhere in the product. eps_eligible
  // decides whether 8.33% is diverted to EPS on the ECR, a statutory return;
  // gratuity_act_covered decides which limb of §10(10) exempts a leaver's
  // gratuity, which is money paid.
  const modal = code("components/payroll/AddEmployeeModal.tsx");
  for (const field of ["eps_eligible", "gratuity_act_covered"]) {
    assert.match(modal, new RegExp(`${field}: form\\.${field}`),
      `${field} is not sent by the employee form`);
    assert.match(modal, new RegExp(`setForm\\(f => \\(\\{ \\.\\.\\.f, ${field}:`),
      `${field} has no control on the employee form — a field on the model ` +
      "that no form writes is the hole PAY-12 named, moved one layer up");
  }

  // And the CSV importer offers them, so a firm onboarding a roster can set
  // the exception at import rather than editing employees one by one.
  const mappers = code("lib/imports/mappers.ts");
  for (const field of ["eps_eligible", "gratuity_act_covered"]) {
    assert.match(mappers, new RegExp(`key: "${field}"`),
      `${field} is not an import column`);
  }
});
