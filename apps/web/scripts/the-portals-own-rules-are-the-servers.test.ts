/**
 * GST-32 — the browser renders what the IRP would refuse and decides none of it.
 *
 * CGST Rule 48(4) says WHICH supplies need an IRN; the portal's own published
 * expressions say whether it would ACCEPT the values one carries, and they are
 * stricter than the Act. `apps/api/domain/gst/irp_validations.py` is that second
 * authority and there is deliberately NO mirror here: SALES-18's whole lesson
 * was that the browser holding a statutory rule is how the rule drifts, and
 * this one is not even about the invoice — it is a fact about a portal.
 *
 * So the panel's job is to render a served list, and the guard's job is to stop
 * a mirror appearing.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const read = (rel: string) =>
  fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");

const PANEL = read("components/invoices/CompliancePanel.tsx");
const COMPLIANCE = read("lib/invoices/compliance.ts");

test("the strip leaves the code behind", () => {
  assert.ok(PANEL.includes("IrpFindings"));
  assert.ok(COMPLIANCE.includes("ServedIrpFinding"));
});

test("the panel renders the SERVED findings", () => {
  assert.match(PANEL, /irn_assessment\?\.irp_findings/,
    "the panel does not read the server's answer, so nothing reaches the CA");
  assert.match(PANEL, /findings\.map\(/);
});

test("no expression from the portal is mirrored in the browser", () => {
  // The two that matter. A copy here passes its own test for ever while the
  // Python authority moves, which is the Schedule III caption mistake.
  for (const src of [PANEL, COMPLIANCE, read("lib/invoices/gst.ts")]) {
    assert.doesNotMatch(src, /a-zA-Z1-9/,
      "the IRP's Document_Num expression is mirrored in the browser");
    assert.doesNotMatch(src, /HsnCd/,
      "the browser is composing the portal's own field names");
  }
});

test("the fallback assessor claims NOTHING about the portal", () => {
  // `assessIrnScope` runs when the frontend is ahead of the backend. It must
  // answer an empty list rather than inventing findings, and an absent key
  // must read as empty rather than as a gap.
  assert.match(COMPLIANCE, /irpFindings: \[\],/);
  assert.match(COMPLIANCE, /irpFindings: served\.irp_findings \?\? \[\],/);
});

test("it WARNS and never blocks", () => {
  // The invoice is lawful whatever the portal thinks of its number, so the
  // Prepare button must not be gated on this.
  const block = PANEL.slice(PANEL.indexOf("function IrpFindings"));
  assert.doesNotMatch(block, /disabled/);
  assert.doesNotMatch(block, /PrimaryBtn/);
  assert.match(block, /amber/, "a warning, not an error");
});

test("nothing is shown once the portal has actually answered", () => {
  const block = PANEL.slice(PANEL.indexOf("function IrpFindings"));
  assert.match(block, /state === "generated"/);
  assert.match(block, /state === "cancelled"/);
  assert.match(block, /return null/);
});
