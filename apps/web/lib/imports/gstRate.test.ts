// POST-A-214: an imported GST % cell is bounded in the PREVIEW, on the same terms the server refuses it at POST.
//   node --experimental-strip-types --test lib/imports/gstRate.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { gstRateCellProblem, MAX_GST_RATE_BPS } from "./gstRate.ts";
import { buildSalesInvoices, type CustomerRef, type ServiceRef } from "../invoices/importMapping.ts";
import {
  buildPurchaseBills, buildSalesCreditNotes, buildSalesDebitNotes, buildPurchaseCreditNotes, buildPurchaseDebitNotes,
  type NameRef, type OriginalDocRef, type PurchaseServiceRef, type SalesServiceRef,
} from "./mappers.ts";

const row = (o: Record<string, string>) => o;

test("the cell check: a rate from 0 to 100 per cent is a rate, anything else is named", () => {
  assert.equal(gstRateCellProblem(0, 3, "0"), null);
  assert.equal(gstRateCellProblem(1800, 3, "18"), null);
  assert.equal(gstRateCellProblem(MAX_GST_RATE_BPS, 3, "100"), null, "100 is allowed: the bound catches a unit mix-up, it does not police the Council");
  assert.match(gstRateCellProblem(-100, 3, "-1") ?? "", /Row 3: GST % must be a non-negative number/);
  assert.match(gstRateCellProblem(Number.NaN, 3, "abc") ?? "", /non-negative number/);
  const mixUp = gstRateCellProblem(180000, 7, "1800") ?? "";
  assert.match(mixUp, /Row 7: GST % "1800" is more than 100/);
  assert.match(mixUp, /not basis points/, "the sentence names both units, because the reader is confused about which one they are in");
});

// ── every builder that reads a GST % cell asks it ────────────────────────────

const CUSTOMERS: CustomerRef[] = [{ id: "cust-1", name: "Acme Pvt Ltd" }];
const SERVICES: ServiceRef[] = [{ id: "svc-3", name: "General Service", hsn_sac: null, gst_rate_bps: null, default_rate_paise: null, unit: null }];

test("sales invoices: 1800 typed as a percent is refused in the preview; 18 and 100 are not", () => {
  const mk = (gst: string) => buildSalesInvoices(
    [row({ product_service: "General Service", invoice_no: "INV-1", customer: "Acme Pvt Ltd", invoice_date: "2026-04-10", description: "X", quantity: "1", rate: "100", gst_rate: gst })],
    "client-1", CUSTOMERS, SERVICES);
  const bad = mk("1800");
  assert.equal(bad.invoices.length, 0);
  assert.match(bad.errors.join(" "), /GST % "1800" is more than 100/);
  assert.equal(mk("18").errors.length, 0);
  assert.equal(mk("100").errors.length, 0);
});

const VENDORS: NameRef[] = [{ id: "v1", name: "Supplier A" }];
const PSERVICES: PurchaseServiceRef[] = [{ id: "s2", name: "General Purchase", description: null, hsn_sac: null, gst_rate_bps: null, purchase_price_paise: null, unit: null }];

test("purchase bills: 1800 typed as a percent is refused in the preview", () => {
  const { bills, errors } = buildPurchaseBills(
    [row({ vendor: "Supplier A", bill_no: "B-1", bill_date: "2026-04-10", product_service: "General Purchase", description: "X", quantity: "1", rate: "100", gst_rate: "1800" })],
    "c1", VENDORS, PSERVICES);
  assert.equal(bills.length, 0);
  assert.match(errors.join(" "), /GST % "1800" is more than 100/);
});

const INVOICES: OriginalDocRef[] = [{ id: "inv-1", no: "INV-001", partyId: "cust-1", isInterstate: false }];
const BILLS: OriginalDocRef[] = [{ id: "bill-1", no: "BILL-001", partyId: "v1", isInterstate: false }];
const SSERVICES: SalesServiceRef[] = [{ id: "svc-1", name: "Widget", description: "A widget", hsn_sac: "8501", gst_rate_bps: 1800, default_rate_paise: 100000, unit: "NOS" }];
const PSVC: PurchaseServiceRef[] = [{ id: "psvc-1", name: "Steel Rod", description: "TMT", hsn_sac: "7213", gst_rate_bps: 1800, purchase_price_paise: 50000, unit: "KGS" }];

// The credit-note and debit-note builders return different note shapes, so neither is the other's type; this test reads
// only `errors`, which is the one thing they share.
type SalesNoteBuilder = (rows: Record<string, string>[], clientId: string, customers: NameRef[],
  invoices: OriginalDocRef[], services?: SalesServiceRef[]) => { errors: string[] };
type PurchaseNoteBuilder = (rows: Record<string, string>[], clientId: string, vendors: NameRef[],
  bills: OriginalDocRef[], services?: PurchaseServiceRef[]) => { errors: string[] };

test("the four note importers refuse a GST % over 100 in the preview too", () => {
  const sales = (fn: SalesNoteBuilder, dateKey: string) =>
    fn([row({ customer: "Acme Pvt Ltd", [dateKey]: "2026-04-10", product_service: "Widget", quantity: "1", rate: "100", gst_rate: "1800" })],
      "client-1", [{ id: "cust-1", name: "Acme Pvt Ltd" }], INVOICES, SSERVICES);
  const purchase = (fn: PurchaseNoteBuilder, dateKey: string) =>
    fn([row({ vendor: "Supplier A", [dateKey]: "2026-04-10", product_service: "Steel Rod", quantity: "1", rate: "100", gst_rate: "1800" })],
      "client-1", VENDORS, BILLS, PSVC);
  for (const out of [
    sales(buildSalesCreditNotes, "credit_note_date"), sales(buildSalesDebitNotes, "debit_note_date"),
    purchase(buildPurchaseCreditNotes, "credit_note_date"), purchase(buildPurchaseDebitNotes, "debit_note_date"),
  ]) {
    const errors = out.errors;
    assert.match(errors.join(" "), /GST % "1800" is more than 100/);
  }
});
