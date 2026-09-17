// CGST Rule 48(4) — the browser half of the IRN-scope parity.
// Run with:
//   node --experimental-strip-types --test scripts/irn-parity.test.ts
//
// WHY THIS EXISTS (SALES-18)
//     `irnEligibility` was the ONLY implementation of Rule 48(4)'s scope test
//     in this repository. A statutory rule living solely in the browser bundle
//     breaks the house rule that computation, validation and statutory rules
//     live in apps/api, and it is what let SALES-17 — the e-way threshold
//     measured on the pre-GST taxable value — sit unnoticed: a wrong number in
//     a TypeScript file has no Python twin to disagree with it and no parity
//     vector to fail.
//
//     It also declined the whole PERSON-side limb of the rule with one fixed
//     sentence on every invoice — "E-invoicing applies only above your firm's
//     turnover threshold — confirm before generating" — because nothing held
//     an aggregate turnover. Migration 401 does now (GST-17), so the server
//     answers that limb with a real figure.
//
// WHY THE RULE EXISTS TWICE
//     apps/api/domain/gst/irn_scope.py is the authority. This panel recomputes
//     on every keystroke and a round trip per keystroke is not a panel — the
//     same reason scripts/eway-parity.test.ts exists beside it. The two are
//     pinned by shared/irn-parity-vectors.json, which this file and
//     apps/api/tests/test_irn_parity.py both read. Change one implementation
//     and both suites fail.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  assessIrnScope, irnEligibility, irnThresholdFor, irnRegistrationState,
  fromServedIrn, IRN_THRESHOLDS, IRN_COMMENCEMENT,
  type ServedIrnScope,
} from "../lib/invoices/compliance.ts";

const VECTORS = JSON.parse(
  readFileSync("../../shared/irn-parity-vectors.json", "utf8"),
).vectors as Array<{
  label: string; why: string;
  input: Record<string, unknown>;
  expected: Record<string, unknown>;
}>;

test("the shared vectors — every one, with the backend's own numbers", () => {
  assert.ok(VECTORS.length >= 23, "the vector file shrank");
  for (const vec of VECTORS) {
    const got = assessIrnScope(vec.input as never);
    const want = vec.expected;
    const pairs: Array<[string, unknown, unknown]> = [
      ["verdict", got.verdict, want.verdict],
      ["supply_in_scope", got.supplyInScope, want.supply_in_scope],
      ["threshold_paise", got.thresholdPaise, want.threshold_paise],
      ["turnover_exceeds", got.turnoverExceeds, want.turnover_exceeds],
      ["turnover_unknown", got.turnoverUnknown, want.turnover_unknown],
      ["gaps", got.gaps.length, want.gaps],
    ];
    for (const [key, actual, expected] of pairs) {
      assert.deepEqual(actual, expected,
        `${vec.label}: ${key} — expected ${JSON.stringify(expected)}, got ` +
        `${JSON.stringify(actual)}. ${vec.why}`);
    }
  }
});

test("the six notified thresholds, and each in force from its own date", () => {
  // ⚠️ [S]-graded. Written from knowledge; the Python module carries the
  // reasoning and tests/test_which_supplies_must_carry_an_irn.py pins them too.
  assert.deepEqual(IRN_THRESHOLDS.map((r) => [r[0], r[1]]), [
    ["2020-10-01", 500_00_00_000_00],
    ["2021-01-01", 100_00_00_000_00],
    ["2021-04-01",  50_00_00_000_00],
    ["2022-04-01",  20_00_00_000_00],
    ["2022-10-01",  10_00_00_000_00],
    ["2023-08-01",   5_00_00_000_00],
  ]);
  assert.equal(IRN_COMMENCEMENT, "2020-10-01");
  // Nothing was notified before commencement: null means there was no
  // threshold, not that none was found.
  assert.equal(irnThresholdFor("2020-09-30").paise, null);
  assert.equal(irnThresholdFor("2020-10-01").paise, 500_00_00_000_00);
  // The day before a step still takes the previous threshold.
  assert.equal(irnThresholdFor("2022-03-31").paise, 50_00_00_000_00);
  assert.equal(irnThresholdFor("2022-04-01").paise, 20_00_00_000_00);
  assert.equal(irnThresholdFor("2026-06-01").paise, 5_00_00_000_00);
});

test("the turnover limb is EXCEEDS, not reaches", () => {
  const base = { treatment: "regular" as const, recipient_gstin: "27ABCDE1234F1Z5", invoice_date: "2026-06-01" };
  assert.equal(assessIrnScope({ ...base, highest_aato_paise: 5_00_00_000_00 }).verdict, "not_required");
  assert.equal(assessIrnScope({ ...base, highest_aato_paise: 5_00_00_000_00 + 1 }).verdict, "required");
});

test("an unrecorded turnover is NOT zero, and the two answer differently", () => {
  const base = { treatment: "regular" as const, recipient_gstin: "27ABCDE1234F1Z5", invoice_date: "2026-06-01" };
  const unknown = assessIrnScope({ ...base, highest_aato_paise: null });
  const nil = assessIrnScope({ ...base, highest_aato_paise: 0 });
  assert.equal(unknown.verdict, "required");
  assert.equal(unknown.turnoverUnknown, true);
  assert.equal(nil.verdict, "not_required");
  assert.equal(nil.turnoverUnknown, false);
});

test("registration has three states and the third is named, not guessed", () => {
  assert.equal(irnRegistrationState("27ABCDE1234F1Z5"), "registered");
  assert.equal(irnRegistrationState("  27abcde1234f1z5 "), "registered");
  assert.equal(irnRegistrationState(null), "unregistered");
  assert.equal(irnRegistrationState(""), "unregistered");
  assert.equal(irnRegistrationState("27ABCDE"), "malformed");
  // A malformed GSTIN goes the SAFE way — B2B — and says so.
  const out = assessIrnScope({
    treatment: "regular", recipient_gstin: "27ABCDE",
    invoice_date: "2026-06-01", highest_aato_paise: 10_00_00_000_00,
  });
  assert.equal(out.supplyInScope, true);
  assert.equal(out.gaps.some((g) => /not a well-formed GSTIN/.test(g)), true);
});

/** Comments and block comments removed, so a guard about CODE is given code.
 *  The module's own explanation quotes the defective sentence verbatim — as it
 *  should, it is the history — and a bare search finds it there and passes
 *  whether or not the code came back. Strip first. */
function codeOf(path: string): string {
  return readFileSync(path, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

test("the panel no longer decides Rule 48(4)'s scope by itself", () => {
  const SRC = codeOf("lib/invoices/compliance.ts");
  // The defect as CODE: irnEligibility used to derive the scope inline from
  // `t.registered` and `t.treatment !== "regular"`. If that comes back the
  // vectors above would still pass — they exercise assessIrnScope, and
  // irnEligibility could simply stop calling it.
  assert.doesNotMatch(SRC, /isExportOrSez/,
    "irnEligibility is deriving the Rule 48(4) supply limb inline again");
  assert.match(SRC, /fromServedIrn\(inv\.irn_assessment\)\s*\?\?\s*assessIrnScope/,
    "irnEligibility must prefer the served assessment and fall back to the " +
    "mirror, not the other way round");
});

test("the fixed turnover sentence is gone — the server answers that limb now", () => {
  const SRC = codeOf("lib/invoices/compliance.ts");
  assert.doesNotMatch(SRC,
    /E-invoicing applies only above your firm's turnover threshold/,
    "the person-side limb is being declined with a fixed sentence again; " +
    "client_gst_turnover (migration 401) holds the figure");
});

test("the served answer wins over the mirror on the same invoice", () => {
  // Behavioural, not textual: give the two DIFFERENT inputs and check which
  // one the answer came from. A source-shaped guard alone passes if
  // `fromServedIrn` returns null for a perfectly good payload.
  const served: ServedIrnScope = {
    verdict: "not_required", supply_in_scope: false,
    supply_reason: "the server says this one is out of scope",
    threshold_paise: 5_00_00_000_00, threshold_citation: "Notification 10/2023-Central Tax",
    turnover_paise: null, turnover_exceeds: null, turnover_unknown: false,
    reason: "the server says this one is out of scope", gaps: [],
  };
  const out = irnEligibility({
    status: "issued", is_interstate: false, supply_state_code: "27",
    // A GSTIN the mirror would read as B2B and therefore IN scope.
    recipient_gstin: "27ABCDE1234F1Z5",
    taxable_amount_paise: 100, invoice_date: "2026-06-01",
    irn_assessment: served,
  }, false);
  assert.equal(out.blockers.includes("the server says this one is out of scope"), true,
    "the browser mirror overrode the server's answer");
});

test("fromServedIrn tolerates a payload with no gaps key", () => {
  const got = fromServedIrn({
    verdict: "required", supply_in_scope: true, supply_reason: "r",
    threshold_paise: 1, threshold_citation: "c", turnover_paise: 2,
    turnover_exceeds: true, turnover_unknown: false, reason: "r",
  } as unknown as ServedIrnScope);
  assert.deepEqual(got?.gaps, []);
});

test("the supply limb BLOCKS and the person limb only WARNS", () => {
  const base = {
    status: "issued" as const, is_interstate: false, supply_state_code: "27",
    taxable_amount_paise: 100, invoice_date: "2026-06-01",
  };
  // B2C — the supply limb fails, and preparing an IRN record for it is
  // meaningless, so it blocks.
  const b2c = irnEligibility({ ...base, recipient_gstin: null }, false);
  assert.equal(b2c.eligible, false);

  // B2B with no turnover recorded — the person limb cannot be answered, and
  // refusing on a figure a CA has not recorded would stop them doing the one
  // thing the screen is for. Warns, does not block.
  const b2b = irnEligibility({ ...base, recipient_gstin: "27ABCDE1234F1Z5" }, false);
  assert.equal(b2b.eligible, true);
  assert.equal(b2b.warnings.some((w) => /threshold/.test(w)), true);
});

test("the CompliancePanel passes the server's assessment and the invoice date through", () => {
  const PANEL = codeOf("components/invoices/CompliancePanel.tsx");
  assert.match(PANEL, /irn_assessment:\s*invoice\.irn_assessment/,
    "the panel must pass the server's Rule 48(4) assessment through");
  assert.match(PANEL, /invoice_date:\s*invoice\.invoice_date/,
    "the browser fallback resolves the threshold from the invoice's own date");
});
