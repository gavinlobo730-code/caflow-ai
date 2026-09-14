/**
 * PAY-23 — the statutory bonus register decides nothing in the browser.
 *
 * The Payment of Bonus Act 1965 is `apps/api/domain/payroll/bonus.py` and
 * `bonus_register.py`: §2(13)'s ₹21,000 eligibility ceiling, §8's thirty
 * working days, §9's five forfeiture grounds, §10's 8.33%, §11's 20%, §12's
 * ₹7,000 floor and §19's eight months. A second copy in TypeScript is the
 * shape this repository keeps having to undo — the tax-audit thresholds, the
 * §192 slab ladder, the Schedule III caption list.
 *
 * COMMENTS ARE STRIPPED BEFORE SCANNING, because a guard defeated by the
 * file's own docstring explaining what it must not do is a failure this suite
 * has already hit.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const PANEL = path.join(WEB, "components/payroll/BonusRegister.tsx");
const PAGE = path.join(WEB, "app/clients/[id]/payroll/page.tsx");

function withoutComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .map((l) => l.replace(/(^|\s)\/\/.*$/, "$1"))
    .join("\n");
}

const raw = fs.readFileSync(PANEL, "utf8");
const code = withoutComments(raw);

test("the bonus register is the server's answer", async (t) => {
  await t.test("spells no statutory figure", () => {
    // Every one of these is in the Act and in the Python engine. A literal
    // here is a second place to update when a Finance Act moves it.
    for (const n of ["21000", "21,000", "7000", "7,000", "8.33%", "20%", "833", "2000"]) {
      assert.ok(!code.includes(n), `the browser spells the statutory figure ${n}`);
    }
    // 8.33 appears once, as the DEFAULT in the form's own input state — the
    // server confines the rate and refuses anything outside §10 and §11.
    assert.equal((code.match(/8\.33/g) ?? []).length, 1);
  });

  await t.test("names no section and no ground", () => {
    assert.ok(!/§9|section 9/i.test(code), "a §9 ground is spelled here");
    assert.ok(!/fraud|sabotage|misappropriat/i.test(code),
      "the §9 grounds belong to the server's `section_9_grounds`");
  });

  await t.test("computes nothing", () => {
    // No eligibility test, no bonus arithmetic: every figure and every
    // reason on the row comes back computed.
    assert.ok(!/eligible\s*=|\* 0\.0833|8\.33\s*\/\s*100/.test(code));
    assert.match(code, /e\.payable_paise/);
    assert.match(code, /e\.reasons/);
    assert.match(code, /e\.gaps/);
  });

  await t.test("renders the server's due date rather than deriving one", () => {
    assert.match(code, /data\.due_date/);
    assert.ok(!/new Date\(/.test(code), "the browser is doing date arithmetic");
  });

  await t.test("distinguishes an unrecorded day count from zero", () => {
    // §8 needs thirty working days. `working_days == null` means nobody
    // recorded any attendance; rendering it as 0 would tell a CA the
    // employee worked no days, which is a different and damaging claim.
    assert.match(code, /working_days == null/);
  });

  await t.test("shows the minimum being the statutory one as its own fact", () => {
    assert.match(code, /rate_is_the_statutory_minimum/);
  });

  await t.test("turns typed money and percentages through the one parser", () => {
    assert.match(code, /paiseFromRupeeInput/);
    assert.match(code, /bpsFromPercentInput/);
    assert.ok(!/parseFloat|Number\([^)]*\)\s*\*\s*100/.test(code));
  });

  await t.test("offers no posting", () => {
    // The provision is a journal the CA raises: the rate is their §10/§11
    // determination and the account is their choice. A "Post this" button
    // here would be the Rule 37 button `itc_register_service` refuses.
    assert.ok(!/post|journal|provision/i.test(code.replace(/className="[^"]*"/g, "")),
      "the screen offers to post something");
  });

  await t.test("is mounted on the payroll screen", () => {
    const page = fs.readFileSync(PAGE, "utf8");
    assert.match(page, /<BonusRegisterTab/);
  });

  await t.test("the comment strip does not make the scan vacuous", () => {
    assert.ok(code.length > raw.length / 2, "too much of the file was stripped");
    assert.match(code, /export function BonusRegisterTab/);
  });
});
