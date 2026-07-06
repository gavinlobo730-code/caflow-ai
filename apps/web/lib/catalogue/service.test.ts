// Batch 6 — Service Catalogue pure helpers. Run with:
//   node --experimental-strip-types --test lib/catalogue/service.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  serviceToLine, formatServiceRate, formatServicePrice, serviceSecondaryLine,
  validateServiceForm, serviceFormToPayload, serviceToForm,
  type ServiceCatalogueItem, type ServiceFormInput,
} from "./service.ts";

const item = (over: Partial<ServiceCatalogueItem> = {}): ServiceCatalogueItem => ({
  id: "s1", name: "Statutory Audit", description: "Statutory audit FY 2025-26",
  hsn_sac: "998221", gst_rate_bps: 1800, default_rate_paise: 5000000,
  unit: "OTH", notes: null, is_active: true, ...over,
});

const form = (over: Partial<ServiceFormInput> = {}): ServiceFormInput => ({
  name: "Statutory Audit", description: "", hsn_sac: "998221",
  gstRate: 18, rate: "50000", unit: "OTH", notes: "", ...over,
});

test("serviceToLine drops a fully pre-priced line (description falls back to name)", () => {
  assert.deepEqual(serviceToLine(item()), {
    description: "Statutory audit FY 2025-26", hsn_sac: "998221", rate: "50000", gst_rate: 18, unit: "OTH",
  });
  assert.equal(serviceToLine(item({ description: "  " })).description, "Statutory Audit");
  assert.equal(serviceToLine(item({ default_rate_paise: 0 })).rate, "");
  assert.equal(serviceToLine(item({ gst_rate_bps: null })).gst_rate, 0);
});

test("formatting helpers", () => {
  assert.equal(formatServiceRate(1800), "18% GST");
  assert.equal(formatServiceRate(null), "");
  assert.equal(formatServicePrice(5000000), "₹50,000");
  assert.equal(formatServicePrice(12345), "₹123.45"); // paise never truncated
  assert.equal(formatServicePrice(0), "");
  assert.equal(serviceSecondaryLine(item()), "SAC 998221 · 18% GST · ₹50,000");
  assert.equal(serviceSecondaryLine(item({ hsn_sac: null, gst_rate_bps: null })), "₹50,000");
});

test("validateServiceForm: name required, non-negative price, gst range", () => {
  assert.equal(validateServiceForm(form()).ok, true);
  assert.equal(validateServiceForm(form({ name: "  " })).errors.name !== undefined, true);
  assert.equal(validateServiceForm(form({ rate: "-5" })).errors.rate !== undefined, true);
  assert.equal(validateServiceForm(form({ rate: "" })).ok, true); // price optional
  assert.equal(validateServiceForm(form({ gstRate: 120 })).errors.gstRate !== undefined, true);
});

test("serviceFormToPayload maps rupees → integer paise, blanks → undefined", () => {
  const p = serviceFormToPayload(form({ rate: "50000.50", description: " audit ", unit: "" }));
  assert.equal(p.default_rate_paise, 5000050);
  assert.equal(p.gst_rate_bps, 1800);
  assert.equal(p.description, "audit");
  assert.equal(p.unit, undefined);
  assert.equal(serviceFormToPayload(form({ rate: "" })).default_rate_paise, 0);
});

test("serviceToForm round-trips an item into editable strings", () => {
  const f = serviceToForm(item());
  assert.equal(f.rate, "50000");
  assert.equal(f.gstRate, 18);
  assert.equal(f.hsn_sac, "998221");
  assert.equal(serviceToForm(item({ gst_rate_bps: null })).gstRate, 18); // sensible default
});
