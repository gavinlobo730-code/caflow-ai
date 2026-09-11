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

test("ewayEligibility: the threshold is the CONSIGNMENT value, and it is advisory", () => {
  // SALES-17. This test used to read
  //     ewayEligibility(inv({ taxable_amount_paise: EWAY_THRESHOLD_PAISE - 1 }))
  // and assert a "₹50,000" warning — asserting the defect, which is why it
  // survived. Rule 138(1) Explanation 2 measures the consignment value
  // INCLUDING the tax charged in the document, so the input is the LINES.
  // scripts/eway-parity.test.ts holds the arithmetic against the backend's own
  // vectors; what is asserted here is that ewayEligibility carries it.
  const goods = (taxable: number, tax: number) => [{
    hsn_sac: "7306", taxable_amount_paise: taxable, igst_paise: tax,
    gst_rate_bps: 1800,
  }];

  // ₹48,000 taxable is below the limit; ₹56,640 of consignment is not.
  const over = ewayEligibility(inv({ lines: goods(4_800_000, 864_000) }), false);
  assert.equal(over.eligible, true, "it stays advisory — the CA decides");
  assert.equal(over.warnings.some((w) => /required/.test(w)), true,
    "a ₹56,640 consignment must not be advised as below ₹50,000");

  const under = ewayEligibility(inv({ lines: goods(2_000_000, 360_000) }), false);
  assert.equal(under.warnings.some((w) => /does not\s+exceed/.test(w)), true);

  // Rule 138 governs the movement of GOODS. A fee invoice is not a small
  // consignment — the rule does not arise, which is a different sentence.
  const services = ewayEligibility(inv({
    lines: [{ hsn_sac: "998221", taxable_amount_paise: 9_000_000,
              igst_paise: 1_620_000, gst_rate_bps: 1800 }],
  }), false);
  assert.equal(services.warnings.some((w) => /movement of goods/.test(w)), true);

  assert.equal(EWAY_THRESHOLD_PAISE, 5_000_000);
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
