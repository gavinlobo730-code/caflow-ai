// CGST Rule 138(1) with Explanation 2 — the browser half of the e-way parity.
// Run with:
//   node --experimental-strip-types --test scripts/eway-parity.test.ts
//
// WHY THIS EXISTS (SALES-17)
//     `ewayEligibility` compared `inv.taxable_amount_paise` — the value BEFORE
//     GST — against ₹50,000. Explanation 2 to Rule 138(1) defines consignment
//     value as the §15 value "and ALSO INCLUDES the central tax, State or Union
//     territory tax, integrated tax and cess charged, if any, in the document".
//     So ₹48,000 of goods at 18% is a ₹56,640 consignment and needs an e-way
//     bill, and the panel told the CA it was "usually not required". Goods that
//     move without one are detained under §129 and the penalty is the tax plus
//     an equal amount.
//
//     Two more errors in the same direction: "EXCEEDING fifty thousand rupees"
//     is strict, so ₹50,000 exactly does NOT need one and `taxable < THRESHOLD`
//     made the boundary required; and Rule 138 governs the movement of GOODS,
//     so a pure-service invoice is not a small consignment — the rule does not
//     arise at all.
//
// WHY THE RULE EXISTS TWICE
//     apps/api/domain/gst/eway.py is the authority. This panel recomputes on
//     every keystroke and a round trip per keystroke is not a panel — the same
//     reason lib/money/gstLine.ts mirrors the Python GST line maths. The two
//     are pinned by shared/eway-parity-vectors.json, which this file and
//     apps/api/tests/test_eway_parity.py both read. Change one implementation
//     and both suites fail.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  assessEway, isServiceCode, ewayEligibility, EWAY_THRESHOLD_PAISE,
} from "../lib/invoices/compliance.ts";

const VECTORS = JSON.parse(
  readFileSync("../../shared/eway-parity-vectors.json", "utf8"),
).vectors as Array<{
  label: string; why: string;
  lines: Array<Record<string, unknown>>;
  expected: Record<string, unknown>;
}>;

test("the shared vectors — every one, with the backend's own numbers", () => {
  assert.ok(VECTORS.length >= 11, "the vector file shrank");
  for (const vec of VECTORS) {
    const got = assessEway(vec.lines as never);
    const want = vec.expected;
    const pairs: Array<[string, unknown, unknown]> = [
      ["consignment_value_paise", got.consignmentValuePaise, want.consignment_value_paise],
      ["exceeds_threshold", got.exceedsThreshold, want.exceeds_threshold],
      ["verdict", got.verdict, want.verdict],
      ["goods_lines", got.goodsLines, want.goods_lines],
      ["service_lines", got.serviceLines, want.service_lines],
      ["unclassified_lines", got.unclassifiedLines, want.unclassified_lines],
      ["excluded_exempt_paise", got.excludedExemptPaise, want.excluded_exempt_paise],
      ["gaps", got.gaps.length, want.gaps],
    ];
    for (const [key, actual, expected] of pairs) {
      assert.deepEqual(actual, expected,
        `${vec.label}: ${key} — expected ${JSON.stringify(expected)}, got ` +
        `${JSON.stringify(actual)}. ${vec.why}`);
    }
  }
});

test("the threshold is ₹50,000 in paise, and it must be EXCEEDED", () => {
  assert.equal(EWAY_THRESHOLD_PAISE, 5_000_000);
  const at = assessEway([{ hsn_sac: "7306", taxable_amount_paise: 5_000_000, gst_rate_bps: 1800 }]);
  const over = assessEway([{ hsn_sac: "7306", taxable_amount_paise: 5_000_001, gst_rate_bps: 1800 }]);
  assert.equal(at.verdict, "not_required", "₹50,000 exactly does not exceed ₹50,000");
  assert.equal(over.verdict, "required");
});

test("a SAC is Chapter 99 AND digits", () => {
  for (const c of ["998211", "996511", "99"]) assert.equal(isServiceCode(c), true, c);
  for (const c of ["7306", "0401", "8471", "", null, undefined, "99abc"]) {
    assert.equal(isServiceCode(c as never), false, String(c));
  }
});

/** Comments and block comments removed, so a guard about CODE is given code.
 *  The module's own explanation quotes the defective expression verbatim — as
 *  it should, it is the history — and a bare search finds it there and passes
 *  whether or not the code came back. This project has made that mistake four
 *  times now; strip first. */
function codeOf(path: string): string {
  return readFileSync(path, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

test("the panel no longer compares the pre-GST taxable value", () => {
  // The defect as CODE, not as a number: the old test was
  // `inv.taxable_amount_paise` compared against the threshold. If that
  // expression comes back, the vectors above would still pass — they exercise
  // assessEway, and ewayEligibility could simply stop calling it.
  const SRC = codeOf("lib/invoices/compliance.ts");
  assert.doesNotMatch(SRC, /taxable_amount_paise\s*<\s*EWAY_THRESHOLD_PAISE/,
    "the threshold is being compared against the pre-GST taxable value again — " +
    "Explanation 2 to Rule 138(1) measures the consignment value INCLUDING tax");
  assert.match(SRC, /assessEway\(inv\.lines/,
    "ewayEligibility must decide through assessEway, which is the mirrored rule");
});

test("the server's answer is preferred and the mirror is only a fallback", () => {
  // apps/api/domain/gst/eway.py is the authority; this module is a mirror for
  // the window where the frontend has redeployed ahead of the backend. If the
  // preference inverts, the browser silently becomes the authority and the two
  // are then pinned only by these vectors — which is how a second classifier
  // becomes the real one.
  const SRC = codeOf("lib/invoices/compliance.ts");
  assert.match(SRC, /fromServed\(inv\.eway_assessment\)\s*\?\?\s*assessEway/,
    "ewayEligibility must prefer the served assessment and fall back to the " +
    "mirror, not the other way round");
  const PANEL_SRC = codeOf("components/invoices/CompliancePanel.tsx");
  assert.match(PANEL_SRC, /eway_assessment:\s*invoice\.eway_assessment/,
    "the panel must pass the server's assessment through");
});

test("the served answer wins over the mirror on the same lines", () => {
  // Behavioural, not textual: give the two DIFFERENT inputs and check which one
  // the answer came from. A source-shaped guard alone passes if `fromServed`
  // returns null for a perfectly good payload.
  const served = {
    consignment_value_paise: 9_999_900, threshold_paise: 5_000_000,
    exceeds_threshold: true, goods_lines: 1, service_lines: 0,
    unclassified_lines: 0, excluded_exempt_paise: 0,
    verdict: "required" as const, reason: "served reason", gaps: [],
  };
  const out = ewayEligibility({
    status: "issued", is_interstate: false, supply_state_code: "27",
    taxable_amount_paise: 100,
    // Lines that on their own would say "not required".
    lines: [{ hsn_sac: "7306", taxable_amount_paise: 100, gst_rate_bps: 1800 }],
    eway_assessment: served,
  }, false);
  assert.equal(out.warnings.some((w) => /required/.test(w)), true,
    "the browser mirror overrode the server's answer");
});

test("the Compliance panel feeds the lines, not just the header total", () => {
  // assessEway needs per-line tax and rate. A panel that passes only
  // `taxable_amount_paise` gets an empty `lines` array, and every invoice then
  // answers "every line is a service" — confidently, and wrongly.
  const PANEL = codeOf("components/invoices/CompliancePanel.tsx");
  assert.match(PANEL, /lines:\s*invoice\.lines\.map/,
    "CompliancePanel must pass the invoice's lines into ComplianceInvoice");
  for (const f of ["hsn_sac", "taxable_amount_paise", "cgst_paise", "sgst_paise", "igst_paise", "gst_rate_bps"]) {
    assert.match(PANEL, new RegExp(`${f}:\\s*l\\.${f}`),
      `the panel drops ${f}, which the consignment value is measured on`);
  }
});
