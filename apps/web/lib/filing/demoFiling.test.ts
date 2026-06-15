// DEMO MODE filing-simulation tests. Run with:
//   node --experimental-strip-types --test lib/filing/demoFiling.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  generateDemoReference,
  isDemoReference,
  isSimulatable,
  demoScheme,
  validateForDemo,
  DEMO_STATUS_LABEL,
} from "./demoFiling.ts";

// Deterministic pseudo-random for reproducible references.
function seeded(seed: number) {
  let s = seed;
  return () => { s = (s * 1103515245 + 12345) & 0x7fffffff; return s / 0x7fffffff; };
}

test("GST returns get a SIM-GST- demo reference", () => {
  const ref = generateDemoReference("GSTR1", seeded(1));
  assert.match(ref, /^SIM-GST-[A-Z0-9]{8}$/);
  assert.ok(isDemoReference(ref));
});

test("ITR and TDS get a DEMO-ARN- reference", () => {
  assert.match(generateDemoReference("ITR", seeded(2)), /^DEMO-ARN-[A-Z0-9]{8}$/);
  assert.match(generateDemoReference("TDS24Q", seeded(3)), /^DEMO-ARN-[A-Z0-9]{8}$/);
});

test("MCA forms get a DEMO-SRN- reference", () => {
  assert.match(generateDemoReference("MCA_AOC4", seeded(4)), /^DEMO-SRN-[A-Z0-9]{8}$/);
});

test("demo references never look like a real government reference", () => {
  for (const t of ["GSTR1", "ITR", "TDS26Q", "MCA_MGT7"]) {
    const ref = generateDemoReference(t, seeded(t.length + 5));
    // A real GST ARN / ITR ack is a 15-digit run; ours always carries a DEMO/SIM prefix.
    assert.ok(/^(SIM|DEMO)-/.test(ref), `${ref} must carry a demo prefix`);
    assert.ok(!/^\d{15}$/.test(ref), `${ref} must not be a 15-digit run`);
  }
});

test("simulatability: GST/ITR/TDS/MCA yes; advance tax and unknown no", () => {
  assert.equal(isSimulatable("GSTR3B"), true);
  assert.equal(isSimulatable("MCA_AOC4"), true);
  assert.equal(isSimulatable("ADVANCE_TAX"), false); // payment, not a return
  assert.equal(isSimulatable("SOMETHING_ELSE"), false);
  assert.equal(demoScheme("GSTR9"), "gst");
  assert.equal(demoScheme("ADVANCE_TAX"), null);
});

test("status label is 'Demo Filed', never the bare word 'Filed'", () => {
  assert.equal(DEMO_STATUS_LABEL, "Demo Filed");
  assert.notEqual(DEMO_STATUS_LABEL, "Filed");
});

test("validation blocks unsimulatable types and missing due date", () => {
  const v1 = validateForDemo({ compliance_type: "ADVANCE_TAX", due_date: "2026-06-15" });
  assert.ok(v1.errors.length > 0);
  const v2 = validateForDemo({ compliance_type: "GSTR1" });
  assert.match(v2.errors.join(" "), /due date/i);
});

test("validation warns (not errors) when the real return is already filed", () => {
  const v = validateForDemo({
    compliance_type: "GSTR1", due_date: "2999-01-01",
    period_start: "2026-04-01", period_end: "2026-04-30", filing_status: "filed",
  });
  assert.equal(v.errors.length, 0);
  assert.match(v.warnings.join(" "), /already.*filed/i);
});
