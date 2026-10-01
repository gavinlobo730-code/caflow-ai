// The Time screen shows what the SERVER says an hour is worth, says "no rate" for
// an entry nobody priced, records which engagement an hour belongs to, and keeps
// a blank rate box apart from a typed 0. Run with:
//   node --experimental-strip-types --test scripts/the-time-screen-prices-an-hour-from-the-server.test.ts
//
// WHY THIS EXISTS (practice_management-11)
//     The screen multiplied `hourly_rate_paise x duration` in the browser — a
//     column no timer-started entry carried — so a hour with no rate showed
//     nothing at all and looked the same as one worth nothing; the timer never
//     sent an engagement; and `api.billing.unbilledWork` had no screen. These
//     are the RULES, not a spelling of the calls: no arithmetic that makes money
//     out of minutes in the browser, one reader for a typed rate, one reader for
//     the unbilled answer, and the tabs that show fee economics are offered only
//     to somebody the server will answer.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const PAGE = "app/time/page.tsx";
const COMPONENTS_DIR = "components/time";

function code(rel: string): string {
  return fs.readFileSync(path.join(ROOT, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

const files = [PAGE, ...fs.readdirSync(path.join(ROOT, COMPONENTS_DIR))
  .filter((f) => f.endsWith(".tsx")).map((f) => `${COMPONENTS_DIR}/${f}`)];

test("the screens that show time never turn minutes into money themselves", () => {
  for (const rel of files) {
    const src = code(rel);
    assert.doesNotMatch(src, /\b(duration_minutes|minutes)\b[^;\n]*\*[^;\n]*rate/i,
      `${rel}: an hour's value is the server's (value_paise), not minutes x rate worked out here`);
    assert.doesNotMatch(src, /rate\w*\s*\*\s*\w*(duration|minutes)/i, `${rel}: same rule, other order`);
    assert.doesNotMatch(src, /\b6000\b/, `${rel}: /6000 is minutes x paise x 100 spelled out`);
    assert.doesNotMatch(src, /\.reduce\([^)]*value_paise/, `${rel}: the unbilled total is the server's aggregate`);
  }
});

test("an entry with no rate says so, and the figure shown is the server's", () => {
  const src = code(PAGE);
  assert.match(src, /value_paise/, "the list reads the server's value");
  assert.match(src, /No rate/, "an unpriced entry says so instead of showing nothing");
  assert.doesNotMatch(src, /hourly_rate_paise\s*\*/, "the legacy column is not multiplied in the browser");
});

test("the timer and a manual entry send the engagement, and the picker is the one component", () => {
  const src = code(PAGE);
  assert.match(src, /engagement_id:\s*startEngagementId/, "the timer carries the chosen engagement");
  assert.match(src, /engagement_id:\s*manualEngagementId/, "a manual entry carries it too");
  assert.equal((src.match(/<EngagementPicker\b/g) ?? []).length, 2, "both dialogs ask for it");
  const picker = code(`${COMPONENTS_DIR}/EngagementPicker.tsx`);
  assert.match(picker, /getEngagementChoices\(/, "the picker shows what the server served");
  assert.doesNotMatch(picker, /billable_rate_paise|rate_paise/, "the override is fee economics, not shown to a person choosing where an hour goes");
});

test("a rate box is read by readRateInput, because a blank must not be stored as 0", () => {
  for (const rel of files) {
    const src = code(rel);
    assert.doesNotMatch(src, /\bpaiseFromRupeeInput\b/,
      `${rel}: paiseFromRupeeInput reads a blank as 0, which on a billing rate means "bills at nothing" ` +
      `and takes the hour OFF the no-rate list — use readRateInput`);
  }
  assert.match(code(PAGE), /readRateInput\(/);
  assert.match(code(`${COMPONENTS_DIR}/BillingRatesPanel.tsx`), /readRateInput\(/);
  assert.match(code(`${COMPONENTS_DIR}/UnbilledWorkPanel.tsx`), /readRateInput\(/);
});

test("the unbilled answer is read through readUnbilledWork, and no-rate time is its own section", () => {
  const src = code(`${COMPONENTS_DIR}/UnbilledWorkPanel.tsx`);
  assert.match(src, /readUnbilledWork\(/, "a payload is not trusted as a shape until it has been read");
  assert.match(src, /no_rate/, "time with no rate is shown apart from the value");
  assert.match(src, /api\.billing\.unbilledWork\(/, "the screen calls the endpoint that had no caller");
});

test("fee economics are offered only to somebody the server will answer", () => {
  const src = code(PAGE);
  assert.match(src, /can\("billing",\s*"read"\)/);
  assert.match(src, /canSeeBilling\s*&&\s*tab === "unbilled"/);
  assert.match(src, /canSeeBilling\s*&&\s*tab === "rates"/);
});

test("none of it keeps the user's work in the browser", () => {
  for (const rel of files) {
    assert.doesNotMatch(code(rel), /localStorage|sessionStorage/, `${rel}`);
  }
});

test("the rate edit on the billing-rates panel goes through the API, never PostgREST", () => {
  const src = code(`${COMPONENTS_DIR}/BillingRatesPanel.tsx`);
  assert.doesNotMatch(src, /\.from\(\s*"(users|fee_engagements)"\s*\)/,
    "a write the browser makes itself is a write rbac() never saw");
  assert.match(src, /api\.billing\.setBillableRate\(/);
  assert.match(src, /api\.engagements\.setBillableRate\(/);
});
