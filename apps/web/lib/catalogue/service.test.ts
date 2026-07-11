// Batch 6 — Product & Service pure helpers (client-owned since migration
// 182). Run with:
//   node --experimental-strip-types --test lib/catalogue/service.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  serviceToLine, formatServiceRate, formatServicePrice, formatServiceKind, serviceSecondaryLine,
  validateServiceForm, serviceFormToPayload, serviceToForm,
  type ServiceCatalogueItem, type ServiceFormInput,
} from "./service.ts";

const CLIENT_ID = "client-a-1";

const item = (over: Partial<ServiceCatalogueItem> = {}): ServiceCatalogueItem => ({
  id: "s1", client_id: CLIENT_ID, name: "Statutory Audit", description: "Statutory audit FY 2025-26",
  kind: "service", hsn_sac: "998221", gst_rate_bps: 1800, default_rate_paise: 5000000,
  purchase_price_paise: null, unit: "OTH", category: null, notes: null, is_active: true, ...over,
});

const form = (over: Partial<ServiceFormInput> = {}): ServiceFormInput => ({
  name: "Statutory Audit", description: "", kind: "service", hsn_sac: "998221",
  gstRate: 18, rate: "50000", purchasePrice: "", category: "", notes: "",
  unit: "", openingQty: "", openingCost: "", openingBalanceDate: "", ...over,
});

test("serviceToLine drops a fully pre-priced line (description never falls back to name)", () => {
  assert.deepEqual(serviceToLine(item()), {
    description: "Statutory audit FY 2025-26", hsn_sac: "998221", rate: "50000", gst_rate: 18, unit: "OTH",
  });
  assert.equal(serviceToLine(item({ description: "  " })).description, "");
  assert.equal(serviceToLine(item({ description: null })).description, "");
  assert.equal(serviceToLine(item({ default_rate_paise: 0 })).rate, "");
  assert.equal(serviceToLine(item({ gst_rate_bps: null })).gst_rate, 0);
});

test("formatServiceKind: good reads as Product, matching the modal's own naming", () => {
  assert.equal(formatServiceKind("good"), "Product");
  assert.equal(formatServiceKind("service"), "Service");
  assert.equal(formatServiceKind(null), "Service");
  assert.equal(formatServiceKind(undefined), "Service");
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

test("validateServiceForm: name required, non-negative prices, gst range", () => {
  assert.equal(validateServiceForm(form()).ok, true);
  assert.equal(validateServiceForm(form({ name: "  " })).errors.name !== undefined, true);
  assert.equal(validateServiceForm(form({ rate: "-5" })).errors.rate !== undefined, true);
  assert.equal(validateServiceForm(form({ rate: "" })).ok, true); // price optional
  assert.equal(validateServiceForm(form({ purchasePrice: "-1" })).errors.purchasePrice !== undefined, true);
  assert.equal(validateServiceForm(form({ purchasePrice: "" })).ok, true); // optional
  assert.equal(validateServiceForm(form({ gstRate: 120 })).errors.gstRate !== undefined, true);
});

test("validateServiceForm: opening qty/cost only checked for goods, non-negative", () => {
  assert.equal(validateServiceForm(form({ kind: "good", openingQty: "10", openingCost: "500" })).ok, true);
  assert.equal(validateServiceForm(form({ kind: "good", openingQty: "-1" })).errors.openingQty !== undefined, true);
  assert.equal(validateServiceForm(form({ kind: "good", openingCost: "-1" })).errors.openingCost !== undefined, true);
  assert.equal(validateServiceForm(form({ kind: "good" })).ok, true); // both optional
  // A service can never have an invalid opening qty/cost — the fields are ignored for it.
  assert.equal(validateServiceForm(form({ kind: "service", openingQty: "-1" })).ok, true);
});

test("serviceFormToPayload maps rupees → integer paise, blanks → undefined, carries client_id + kind", () => {
  const p = serviceFormToPayload(
    form({ rate: "50000.50", purchasePrice: "30000", description: " audit ", category: " Compliance " }),
    CLIENT_ID,
  );
  assert.equal(p.client_id, CLIENT_ID);
  assert.equal(p.kind, "service");
  assert.equal(p.default_rate_paise, 5000050);
  assert.equal(p.purchase_price_paise, 3000000);
  assert.equal(p.gst_rate_bps, 1800);
  assert.equal(p.description, "audit");
  assert.equal(p.category, "Compliance");
  assert.equal(serviceFormToPayload(form({ rate: "" }), CLIENT_ID).default_rate_paise, 0);
  assert.equal(serviceFormToPayload(form({ purchasePrice: "" }), CLIENT_ID).purchase_price_paise, undefined);
});

test("serviceFormToPayload only sends unit/opening balance for goods, never services", () => {
  const goodPayload = serviceFormToPayload(
    form({ kind: "good", unit: "kgs", openingQty: "100", openingCost: "5000" }), CLIENT_ID,
  );
  assert.equal(goodPayload.unit, "kgs");
  assert.equal(goodPayload.opening_qty_units, 100);
  assert.equal(goodPayload.opening_cost_paise, 500000);

  // Same field values, but kind=service — none of them may leak onto the payload.
  const servicePayload = serviceFormToPayload(
    form({ kind: "service", unit: "kgs", openingQty: "100", openingCost: "5000" }), CLIENT_ID,
  );
  assert.equal(servicePayload.unit, undefined);
  assert.equal(servicePayload.opening_qty_units, undefined);
  assert.equal(servicePayload.opening_cost_paise, undefined);

  // Opening qty of 0 (nothing on hand yet) must not be sent as a truthy "seed this" signal.
  assert.equal(serviceFormToPayload(form({ kind: "good", openingQty: "0" }), CLIENT_ID).opening_qty_units, undefined);
});

test("serviceFormToPayload only sends opening_balance_date for goods, and only when set", () => {
  const dated = serviceFormToPayload(
    form({ kind: "good", openingQty: "10", openingCost: "500", openingBalanceDate: "2025-04-01" }), CLIENT_ID,
  );
  assert.equal(dated.opening_balance_date, "2025-04-01");

  // Blank date -> undefined, so the backend's own FY-start default applies
  // instead of sending an empty string.
  const blank = serviceFormToPayload(form({ kind: "good", openingQty: "10", openingCost: "500" }), CLIENT_ID);
  assert.equal(blank.opening_balance_date, undefined);

  // A service can never carry an opening_balance_date, same as unit/opening qty/cost.
  const service = serviceFormToPayload(
    form({ kind: "service", openingBalanceDate: "2025-04-01" }), CLIENT_ID,
  );
  assert.equal(service.opening_balance_date, undefined);
});

test("serviceToForm round-trips an item into editable strings", () => {
  const f = serviceToForm(item({ purchase_price_paise: 3000000, category: "Compliance" }));
  assert.equal(f.rate, "50000");
  assert.equal(f.purchasePrice, "30000");
  assert.equal(f.category, "Compliance");
  assert.equal(f.gstRate, 18);
  assert.equal(f.hsn_sac, "998221");
  assert.equal(f.kind, "service");
  assert.equal(serviceToForm(item({ gst_rate_bps: null })).gstRate, 18); // sensible default
  assert.equal(serviceToForm(item({ purchase_price_paise: null })).purchasePrice, "");
});

test("serviceToForm shows opening_balance_date only before stock has started moving", () => {
  const notStarted = serviceToForm(item({
    kind: "good", stock_qty_units: null, opening_qty_units: 10, opening_cost_paise: 50000,
    opening_balance_date: "2025-04-01T00:00:00Z",
  }));
  assert.equal(notStarted.openingBalanceDate, "2025-04-01");

  // Once real stock movements exist, re-showing the original opening date
  // would look editable when it no longer is — same rule as openingQty/openingCost.
  const started = serviceToForm(item({
    kind: "good", stock_qty_units: 7, opening_qty_units: 10, opening_cost_paise: 50000,
    opening_balance_date: "2025-04-01T00:00:00Z",
  }));
  assert.equal(started.openingBalanceDate, "");

  assert.equal(serviceToForm(item({ kind: "good", stock_qty_units: null, opening_balance_date: null })).openingBalanceDate, "");
});
