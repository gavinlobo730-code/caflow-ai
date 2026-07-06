// Batch 7 — GST compliance derivation & validation. Run with:
//   node --experimental-strip-types --test lib/invoices/compliance.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  gstTreatment, treatmentLabel, validatePlaceOfSupply, validateMandatoryGstFields,
  irnEligibility, ewayEligibility, irnStatus, ewayStatus, complianceTimelineItems,
  EWAY_THRESHOLD_PAISE, type ComplianceInvoice, type EInvoiceRecord, type EWayRecord,
} from "./compliance.ts";

const B2B_GSTIN = "27ABCDE1234F1Z5"; // Maharashtra (27)

const inv = (over: Partial<ComplianceInvoice> = {}): ComplianceInvoice => ({
  status: "issued", is_interstate: false, supply_state_code: "27",
  recipient_gstin: B2B_GSTIN, is_reverse_charge: false, gst_treatment: null,
  taxable_amount_paise: 6_000_000, line_hsn_codes: ["998221"], ...over,
});

test("gstTreatment: B2B/B2C + interstate, explicit export wins", () => {
  assert.equal(gstTreatment(inv()).registered, true);
  assert.match(gstTreatment(inv()).label, /B2B · Intra-state/);
  assert.equal(gstTreatment(inv({ recipient_gstin: null })).registered, false);
  assert.match(gstTreatment(inv({ recipient_gstin: null })).label, /B2C/);
  assert.match(gstTreatment(inv({ is_interstate: true })).label, /Inter-state/);
  assert.equal(gstTreatment(inv({ gst_treatment: "export_without_payment" })).treatment, "export_without_payment");
  assert.equal(treatmentLabel("sez_with_payment"), "SEZ with payment (IGST)");
});

test("validatePlaceOfSupply: missing, invalid, GSTIN mismatch", () => {
  assert.equal(validatePlaceOfSupply(inv({ supply_state_code: null }))[0].severity, "error");
  assert.equal(validatePlaceOfSupply(inv({ supply_state_code: "99" }))[0].message.includes("not a valid"), true);
  // Intra-state but recipient GSTIN is a different state → warning.
  const warn = validatePlaceOfSupply(inv({ supply_state_code: "29", is_interstate: false }));
  assert.equal(warn.some((i) => i.severity === "warning"), true);
  assert.deepEqual(validatePlaceOfSupply(inv()), []); // 27 matches GSTIN 27
});

test("validateMandatoryGstFields flags bad GSTIN and missing HSN", () => {
  assert.equal(validateMandatoryGstFields(inv({ recipient_gstin: "BADGSTIN" })).some((i) => i.field === "recipient_gstin"), true);
  assert.equal(validateMandatoryGstFields(inv({ line_hsn_codes: ["998221", ""] })).some((i) => i.field === "hsn"), true);
});

test("irnEligibility: draft blocks, B2C blocks, already-generated blocks, B2B ok", () => {
  assert.equal(irnEligibility(inv({ status: "draft" }), false).eligible, false);
  assert.equal(irnEligibility(inv({ recipient_gstin: null }), false).eligible, false); // B2C
  assert.equal(irnEligibility(inv(), true).eligible, false);                            // already generated
  const ok = irnEligibility(inv(), false);
  assert.equal(ok.eligible, true);
  assert.equal(ok.warnings.some((w) => /threshold/.test(w)), true);
  // Export invoice with no recipient GSTIN is still eligible (not B2C).
  assert.equal(irnEligibility(inv({ recipient_gstin: null, gst_treatment: "export_with_payment" }), false).eligible, true);
});

test("ewayEligibility: below threshold + services are advisory, not blockers", () => {
  const low = ewayEligibility(inv({ taxable_amount_paise: EWAY_THRESHOLD_PAISE - 1 }), false);
  assert.equal(low.eligible, true);
  assert.equal(low.warnings.some((w) => /₹50,000/.test(w)), true);
  assert.equal(ewayEligibility(inv({ line_hsn_codes: ["998221", "998314"] }), false).warnings.some((w) => /services/.test(w)), true);
  assert.equal(ewayEligibility(inv({ status: "draft" }), false).eligible, false);
  assert.equal(ewayEligibility(inv(), true).eligible, false);
});

test("irnStatus / ewayStatus: prefer generated, else newest; none when absent", () => {
  const recs: EInvoiceRecord[] = [
    { id: "a", sales_invoice_id: "INV-1", status: "cancelled", created_at: "2026-07-01", irn: "OLD" },
    { id: "b", sales_invoice_id: "INV-1", status: "generated", created_at: "2026-07-02", irn: "NEW", qr_data: "QR" },
  ];
  const s = irnStatus("INV-1", recs);
  assert.equal(s.state, "generated");
  assert.equal(s.irn, "NEW");
  assert.equal(s.qrData, "QR");
  assert.equal(irnStatus("OTHER", recs).state, "none");

  const ew: EWayRecord[] = [{ id: "e", sales_invoice_id: "INV-1", status: "generated", ewb_number: "EWB1", ewb_valid_upto: "2026-07-10" }];
  assert.equal(ewayStatus("INV-1", ew).ewbNumber, "EWB1");
});

test("complianceTimelineItems: generation + cancellation for this invoice only", () => {
  const items = complianceTimelineItems(
    "INV-1",
    [
      { id: "a", sales_invoice_id: "INV-1", status: "generated", ack_date: "2026-07-02T10:00:00Z", irn: "IRN9" },
      { id: "b", sales_invoice_id: "OTHER", status: "generated", ack_date: "2026-07-02T11:00:00Z", irn: "X" },
    ],
    [{ id: "e", sales_invoice_id: "INV-1", status: "cancelled", cancelled_at: "2026-07-03T09:00:00Z", cancellation_reason: "duplicate" }],
  );
  assert.equal(items.length, 2);
  assert.equal(items.some((i) => i.title === "IRN generated" && i.detail === "IRN9"), true);
  assert.equal(items.some((i) => i.title === "E-Way Bill cancelled"), true);
});
