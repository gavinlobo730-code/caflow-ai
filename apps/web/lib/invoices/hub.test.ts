// Batch 4 — Invoice Hub logic. Run with:
//   node --experimental-strip-types --test lib/invoices/hub.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  availableActions, deliverySummary, complianceSummary, buildActivity,
} from "./hub.ts";
import type { InvoiceDelivery } from "./gst.ts";

const delivery = (over: Partial<InvoiceDelivery> = {}): InvoiceDelivery => ({
  id: "d1", invoice_id: "INV-1", sent_to: "a@x.com", sent_by_email: null,
  status: "sent", provider_message_id: null, error_message: null,
  sent_at: "2026-07-06T10:00:00Z", created_at: "2026-07-06T10:00:00Z", ...over,
});

test("draft actions: edit/delete/issue only", () => {
  const a = availableActions("draft");
  assert.deepEqual(
    { edit: a.edit, delete: a.delete, issue: a.issue },
    { edit: true, delete: true, issue: true },
  );
  assert.equal(a.recordPayment, false);
  assert.equal(a.creditNote, false);
  assert.equal(a.viewJournal, false);
  assert.equal(a.duplicate, false);
  assert.equal(a.pdf, false);
  // A draft is edited in place via the full editor (`edit`), not the
  // posted-only soft-field patch.
  assert.equal(a.editDetails, false);
});

test("issued actions: record payment, send, duplicate, credit note, journal, pdf, editDetails", () => {
  const a = availableActions("issued");
  for (const k of ["recordPayment", "paymentLink", "send", "duplicate", "creditNote", "viewJournal", "pdf", "editDetails"] as const) {
    assert.equal(a[k], true, `issued should allow ${k}`);
  }
  assert.equal(a.edit, false);
  assert.equal(a.issue, false);
});

test("paid: no record payment / pay link; still duplicate, credit note, journal, pdf, send, editDetails", () => {
  const a = availableActions("paid");
  assert.equal(a.recordPayment, false);
  assert.equal(a.paymentLink, false);
  assert.equal(a.duplicate, true);
  assert.equal(a.creditNote, true);
  assert.equal(a.viewJournal, true);
  assert.equal(a.pdf, true);
  assert.equal(a.send, true);
  assert.equal(a.editDetails, true);
});

test("cancelled: read-only-ish (duplicate + pdf + journal), no payment/credit/send/editDetails", () => {
  const a = availableActions("cancelled");
  assert.equal(a.recordPayment, false);
  assert.equal(a.creditNote, false);
  assert.equal(a.send, false);
  assert.equal(a.duplicate, true);
  assert.equal(a.pdf, true);
  assert.equal(a.viewJournal, false);
  assert.equal(a.editDetails, false);
});

test("deliverySummary reflects sent state (viewed not tracked)", () => {
  assert.deepEqual(deliverySummary([]), { sent: false, viewed: false, lastSentTo: null, lastSentAt: null, lastStatus: null, attempts: 0 });
  const s = deliverySummary([delivery(), delivery({ id: "d2", status: "failed" })]);
  assert.equal(s.sent, true);
  assert.equal(s.viewed, false);
  assert.equal(s.lastSentTo, "a@x.com");
  assert.equal(s.attempts, 2);
});

test("complianceSummary matches records by sales_invoice_id", () => {
  const einv = [{ sales_invoice_id: "INV-1", irn: "IRN123" }, { sales_invoice_id: "INV-2", irn: "IRNX" }];
  const eway = [{ sales_invoice_id: "INV-1", ewb_number: "EWB999" }];
  assert.deepEqual(complianceSummary("INV-1", einv, eway), { irn: "IRN123", ewayBill: "EWB999" });
  assert.deepEqual(complianceSummary("INV-9", einv, eway), { irn: null, ewayBill: null });
});

test("buildActivity merges invoice lifecycle + deliveries, newest first", () => {
  const events = [
    { entity_type: "sales_invoice", entity_id: "INV-1", title: "Issued", created_at: "2026-07-06T09:00:00Z" },
    { entity_type: "sales_invoice", entity_id: "OTHER", title: "Not mine", created_at: "2026-07-06T11:00:00Z" },
    { entity_type: "receipt", entity_id: "INV-1", title: "Wrong type", created_at: "2026-07-06T12:00:00Z" },
  ];
  const items = buildActivity("INV-1", events, [delivery({ sent_at: "2026-07-06T10:00:00Z" })]);
  assert.equal(items.length, 2, "only this invoice's lifecycle + its deliveries");
  assert.equal(items[0].title, "Emailed to customer"); // 10:00 newest
  assert.equal(items[1].title, "Issued");               // 09:00
});

test("buildActivity merges extra (compliance) items newest-first", () => {
  const items = buildActivity(
    "INV-1",
    [{ entity_type: "sales_invoice", entity_id: "INV-1", title: "Issued", created_at: "2026-07-06T09:00:00Z" }],
    [],
    [{ at: "2026-07-06T12:00:00Z", title: "IRN generated", detail: "IRN9", kind: "compliance" }],
  );
  assert.equal(items.length, 2);
  assert.equal(items[0].title, "IRN generated"); // 12:00 newest
  assert.equal(items[1].title, "Issued");        // 09:00
});
