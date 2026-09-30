// The client tax and compliance screens report what the server did, read the
// columns that exist, and derive what the statute derives. Run with:
//   node --experimental-strip-types --test scripts/the-tax-and-compliance-screens-say-what-the-server-said.test.ts
//
// ─────────────────────────────────────────────────────────────────────────────
// WHAT WAS WRONG (the 27 September 2026 root-cause pass, items 2–13)
// ─────────────────────────────────────────────────────────────────────────────
// Nine defects on seven screens, and they fall into four shapes — which is why
// this is one guard rather than nine:
//
//   1. A RESULT AWAITED AND DROPPED. The tax computation saved its snapshot
//      and never looked at the answer, so every company, firm and LLP snapshot
//      the regime CHECK refused read as saved. The notice extractor closed its
//      panel on a 502. Add Director closed its form on a refusal.
//   2. A REFUSAL READ OFF THE WRONG KEY. FastAPI's HTTPException body is
//      `{"detail": "..."}` with no `error`, so every `res.error ?? "Failed"`
//      on a page with its own `apiFetch` showed the word "Failed" over the
//      sentence the server wrote. Normalised once per page, through
//      lib/api's `errorMessage`, rather than at forty call sites.
//   3. A COLUMN THAT DOES NOT EXIST. The TDS register read `deduction_date`,
//      `taxable_amount_paise` and `tds_amount_paise` — none of them columns of
//      `tds_deductions` — so real deductions showed a blank date and ₹0.00.
//      The §197 certificate insert omitted `firm_id`, so RLS refused it.
//   4. A SECOND ANSWER TO A STATUTORY QUESTION. The assessment year was its own
//      picker beside the financial year (IT Act §2(9): AY = FY + 1), and the
//      client MCA screen divided PAISE by the RUPEE crore — capital 100× large.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { formatCroreLakh, NO_FIGURE } from "../lib/money/format.ts";

const WEB = join(import.meta.dirname, "..");

/** Source with comments stripped — several of these files now EXPLAIN the
 *  defect they removed by quoting it, and prose is not code. */
function code(rel: string): string {
  return readFileSync(join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

const COMPUTATION = "app/clients/[id]/tax/computation/page.tsx";
const FILING = "app/clients/[id]/tax/filing/page.tsx";
const AS26 = "app/clients/[id]/tax/26as/page.tsx";
const COMPLIANCE = "app/clients/[id]/compliance/page.tsx";
const TDS = "app/clients/[id]/compliance/tds/page.tsx";
const MCA = "app/clients/[id]/compliance/mca/page.tsx";
const GST = "app/clients/[id]/compliance/gst/page.tsx";
const REGISTRATIONS = "components/gst/RegistrationsTab.tsx";

test("a page's own apiFetch hands a refusal back as the server's sentence", () => {
  // GST joined the list with gst-09: its 2B upload refuses a file for another
  // month or another registration with a 422, and the screen read `.error`.
  for (const page of [COMPUTATION, FILING, AS26, COMPLIANCE, MCA, GST]) {
    const src = code(page);
    const at = src.indexOf("async function apiFetch(");
    assert.ok(at >= 0, `${page} no longer has its own apiFetch — move this assertion with it`);
    const body = src.slice(at, src.indexOf("\n}", at));
    assert.match(body, /if \(!res\.ok\) return \{ success: false, data: null, error: await errorMessage\(res\) \}/,
      `${page}'s apiFetch returns a refusal's raw body, whose sentence is under ` +
      "`detail` — so every `res.error ?? \"Failed\"` on the page shows \"Failed\".");
    assert.match(src, /import \{ errorMessage \} from "@\/lib\/api"/,
      `${page} must read the sentence through lib/api's errorMessage, not a copy of it`);
  }
});

test("the snapshot's own result is read, and a refusal is said beside the figures", () => {
  const src = code(COMPUTATION);
  assert.match(src, /const snapRes = await apiFetch\("\/api\/itr\/snapshots"/,
    "the snapshot POST is awaited and dropped again");
  assert.match(src, /if \(!snapRes\?\.success\)/);
  assert.match(src, /Computed, but the snapshot was NOT saved: /);
  assert.doesNotMatch(src, /\n\s*await apiFetch\("\/api\/itr\/snapshots"/,
    "an unassigned await of the snapshot POST is the defect");
});

test("the assessment year follows the financial year and is not chosen", () => {
  for (const page of [COMPUTATION, FILING]) {
    const src = code(page);
    assert.match(src, /const ay = [^;\n]*assessmentYearFor\(fy\)/,
      `${page}: IT Act §2(9) — the AY is the FY plus one, derived, never a second picker`);
    assert.doesNotMatch(src, /\bsetAy\b/, `${page} can set the AY independently again`);
    assert.match(src, /<YearPicker kind="ay" value=\{ay\} onChange=\{\(\) => \{\}\} disabled/,
      `${page} must SHOW the derived AY read-only`);
  }
});

test("the TDS register reads the columns tds_deductions has", () => {
  const src = code(TDS);
  const at = src.indexOf("function DeductionsTab(");
  const tab = src.slice(at, src.indexOf("\nfunction ", at + 1));
  for (const phantom of ["deduction_date", "taxable_amount_paise", "tds_amount_paise"]) {
    assert.doesNotMatch(tab, new RegExp(`\\br\\.${phantom}\\b`),
      `${phantom} is not a column of tds_deductions (migration 014)`);
  }
  for (const real of ["transaction_date", "payment_amount_paise", "tds_paise"]) {
    assert.match(tab, new RegExp(`\\br\\.${real}\\b`), `the register no longer shows ${real}`);
  }
});

test("a §197 certificate is inserted with the firm it belongs to", () => {
  const src = code(TDS);
  const at = src.indexOf('.from("tds_lower_deduction_certificates").insert({');
  assert.ok(at >= 0, "the certificate insert moved — and its payload must stay INLINE");
  const payload = src.slice(at, src.indexOf("})", at));
  assert.match(payload, /\bfirm_id:/,
    "firm_id is NOT NULL with no default and RLS checks it — without it every insert 403s");
});

test("the client MCA screen renders capital through the one crore/lakh rule", () => {
  const src = code(MCA);
  assert.doesNotMatch(src, /function crore\(/, "a per-screen crore() is back");
  assert.doesNotMatch(src, /\/\s*10000000\b/, "paise divided by the RUPEE crore is the 100× defect");
  assert.match(src, /formatCroreLakh\(c\.authorized_capital_paise/);
  assert.match(src, /formatCroreLakh\(c\.paid_up_capital_paise/);
  // And the firm screen shares it rather than keeping its own copy.
  assert.match(code("app/mca/page.tsx"), /formatCroreLakh\(c\.auth_capital_paise\)/);
  assert.doesNotMatch(code("app/mca/page.tsx"), /function fmtLakhs\(/);
});

test("formatCroreLakh converts PAISE, not rupees", () => {
  // ₹50,00,000 — fifty lakh — is 5,00,00,000 paise. The defect showed it as
  // "₹50.00 Cr" by dividing paise by 1,00,00,000.
  assert.equal(formatCroreLakh(500_000_000), "₹50.00 L");
  assert.equal(formatCroreLakh(2_500_000_000), "₹2.50 Cr");
  assert.equal(formatCroreLakh(123_456_789_000_000), "₹1,23,456.79 Cr");
  assert.equal(formatCroreLakh("1000000000"), "₹1.00 Cr", "PostgREST sends a bigint as a string");
  assert.equal(formatCroreLakh(1_234_500), "₹12,345.00", "below a lakh it is the full figure");
  assert.equal(formatCroreLakh(null), NO_FIGURE, "nothing is not ₹0");
  assert.equal(formatCroreLakh(undefined), NO_FIGURE);
});

test("Add Director reads its result and sends no empty date", () => {
  const src = code(MCA);
  assert.match(src, /const res = await apiFetch\("\/api\/mca-workspace\/directors", \{/,
    "the Add Director POST is awaited and dropped again");
  assert.match(src, /date_of_appointment: form\.date_of_appointment \|\| null/,
    "a blank date must go as null — \"\" is an invalid DATE in Postgres");
  assert.match(src, /<input type="date" value=\{form\.date_of_appointment\}/);
});

test("the notice extractor keeps its panel open on a refusal", () => {
  const src = code(COMPLIANCE);
  const at = src.indexOf("async function extract()");
  const fn = src.slice(at, src.indexOf("\n  }\n", at));
  assert.match(fn, /const res = await apiFetch\(/, "the extract result is dropped again");
  assert.match(fn, /if \(!res\?\.success\) \{[\s\S]*?setExtractError\([\s\S]*?return;/,
    "a refusal must set the error and return BEFORE the panel is closed");
  assert.match(fn, /finally \{\s*setExtracting\(false\)/,
    "without finally a thrown request leaves \"Extracting…\" on the button for good");
});

test("a failed registrations read is not reported as a client with no GSTIN", () => {
  const src = code(REGISTRATIONS);
  assert.match(src, /loadFailed \? null : rows\.length === 0 \?/,
    "the empty state is a claim about the client and may only follow a successful read");
});
