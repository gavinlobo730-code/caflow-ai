// What a half-typed purchase bill keeps (frontend_ux-23). Run with:
//   node --experimental-strip-types --test lib/purchases/billDraft.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  MAX_DRAFT_BILL_LINES, applyBillDraft, billRestoreNote, draftLineOf, editorLineOf,
  linkCatalogue, validateBillDraft, withoutDocument,
  type BillDraftContext, type BillDraftFields,
} from "./billDraft.ts";
import { lineFromExtraction } from "./extractedLine.ts";
import { buildLinePayload, isValidBillLine, type PurchaseBillLine } from "./billEditor.ts";

const GOOD: BillDraftFields = {
  vendorId: "v-landlord",
  billNo: "RENT/09",
  ourReference: "PB-2026-114",
  form15caAckNo: "",
  form15caFiledOn: "",
  form15cbUdin: "",
  notes: "September rent",
  billDate: "2026-09-30",
  dueDate: "2026-10-10",
  isReverseCharge: false,
  currency: "",
  exchangeRate: "",
  documentAttached: false,
  lines: [
    {
      description: "Office rent", hsn_sac: "997212", qty: "1", rate: "1,25,000.00", gst_rate: 18,
      unit: "NOS", expense_account_id: "acc-rent", service_catalogue_id: "cat-rent",
    },
    {
      description: "Maintenance", hsn_sac: "998533", qty: "1", rate: "8000", gst_rate: 18,
      unit: "NOS", expense_account_id: "acc-maint", service_catalogue_id: "cat-maint",
      itc_eligible: false, blocked_credit_reason: "§17(5)(d)",
    },
  ],
};

const ctx = (over: Partial<BillDraftContext> = {}): BillDraftContext => ({
  isEdit: false,
  current: { vendorId: "", currency: "", exchangeRate: "", isReverseCharge: false },
  vendorIds: new Set(["v-landlord"]),
  accountIds: new Set(["acc-rent", "acc-maint"]),
  currencyCodes: new Set(["USD", "EUR"]),
  ...over,
});

const roundTrip = (d: unknown) => JSON.parse(JSON.stringify(d));

test("a well-formed draft is rebuilt field for field", () => {
  assert.deepEqual(validateBillDraft(roundTrip(GOOD)), GOOD);
});

test("an amount stays the TYPED STRING, in the Indian grouping the CA typed it", () => {
  assert.equal(validateBillDraft(roundTrip(GOOD))?.lines[0].rate, "1,25,000.00");
});

test("nothing derived is carried back: totals, a TDS figure, a catalogue row, the uploaded file's path", () => {
  const dirty = {
    ...GOOD, totalPaise: 14_75_000, tdsPaise: 12_500, document_url: "other-firm/secret.pdf",
    lines: GOOD.lines.map((l) => ({
      ...l, product: { id: "cat-rent", name: "Rent" }, hsnMatches: [], _k: 4, line_total_paise: 1,
    })),
  };
  const back = validateBillDraft(roundTrip(dirty)) as BillDraftFields;
  assert.deepEqual(Object.keys(back).sort(), Object.keys(GOOD).sort());
  assert.deepEqual(Object.keys(back.lines[0]).sort(),
    ["description", "expense_account_id", "gst_rate", "hsn_sac", "qty", "rate", "service_catalogue_id", "unit"],
    "the save recomputes every figure from what it is sent; a draft carrying one would be a figure to trust");
  assert.equal(JSON.stringify(back).includes("secret.pdf"), false,
    "a draft edited by hand must not be able to point a bill at somebody else's stored file");
});

test("a wrong type anywhere discards the whole draft", () => {
  assert.equal(validateBillDraft(null), null);
  assert.equal(validateBillDraft("x"), null);
  assert.equal(validateBillDraft({ ...GOOD, notes: 7 }), null);
  assert.equal(validateBillDraft({ ...GOOD, isReverseCharge: "yes" }), null);
  assert.equal(validateBillDraft({ ...GOOD, lines: "none" }), null);
  assert.equal(validateBillDraft({ ...GOOD, documentAttached: undefined }), null);
});

test("a date that is not a date discards the draft; an empty one is fine", () => {
  assert.equal(validateBillDraft({ ...GOOD, billDate: "30/09/2026" }), null);
  assert.equal(validateBillDraft({ ...GOOD, dueDate: "soon" }), null);
  assert.equal(validateBillDraft({ ...GOOD, form15caFiledOn: "2026-9-1" }), null);
  assert.notEqual(validateBillDraft({ ...GOOD, dueDate: "" }), null);
});

test("ONE bad line discards the draft rather than quietly dropping a line of the bill", () => {
  const bad = { ...GOOD, lines: [GOOD.lines[0], { ...GOOD.lines[1], gst_rate: "18" }] };
  assert.equal(validateBillDraft(bad), null);
  assert.equal(validateBillDraft({ ...GOOD, lines: [GOOD.lines[0], null] }), null);
  assert.equal(validateBillDraft({ ...GOOD, lines: [{ ...GOOD.lines[0], qty: 1 }] }), null);
});

test("a GST rate that is not a plausible percentage discards the draft", () => {
  assert.equal(validateBillDraft({ ...GOOD, lines: [{ ...GOOD.lines[0], gst_rate: -1 }] }), null);
  assert.equal(validateBillDraft({ ...GOOD, lines: [{ ...GOOD.lines[0], gst_rate: 1800 }] }), null);
  // JSON turns NaN into null, so a NaN rate comes back as a type error, not a rate.
  assert.equal(validateBillDraft(roundTrip({ ...GOOD, lines: [{ ...GOOD.lines[0], gst_rate: NaN }] })), null);
  assert.notEqual(validateBillDraft({ ...GOOD, lines: [{ ...GOOD.lines[0], gst_rate: 0 }] }), null,
    "0% is a real rate and not an absent one");
});

test("an optional field that is present and wrong discards the draft; one that is absent is fine", () => {
  assert.equal(validateBillDraft({ ...GOOD, lines: [{ ...GOOD.lines[0], itc_eligible: "no" }] }), null);
  assert.equal(validateBillDraft({ ...GOOD, lines: [{ ...GOOD.lines[0], cessPercent: 12 }] }), null);
  assert.equal(validateBillDraft({ ...GOOD, lines: [{ ...GOOD.lines[0], blocked_credit_reason: {} }] }), null);
  assert.notEqual(validateBillDraft({ ...GOOD, lines: [{ ...GOOD.lines[0], itc_eligible: true }] }), null);
});

test("a bill beyond any plausible hand-typed size is refused", () => {
  const many = Array.from({ length: MAX_DRAFT_BILL_LINES + 1 }, () => GOOD.lines[0]);
  assert.equal(validateBillDraft({ ...GOOD, lines: many }), null);
  assert.notEqual(validateBillDraft({ ...GOOD, lines: many.slice(1) }), null);
});

// ── AI-01: the flags travel, and a flag nobody recognises discards the draft ──

test("AI-01: a line the document did not state its GST rate for keeps its flag across a draft", () => {
  const extracted = lineFromExtraction({
    description: "Widgets", hsn_sac: "8481", quantity: 3, unit: "PCS", rate_paise: 50_000,
    gst_rate_bps: null, not_read: ["gst_rate"],
  });
  const line: PurchaseBillLine = { ...extracted, expense_account_id: "acc-rent", service_catalogue_id: "cat-w" };
  assert.equal(isValidBillLine(line), false, "premise: an unconfirmed GST rate stops the line saving");
  assert.deepEqual(line.unread, ["gst_rate"]);

  const back = validateBillDraft(roundTrip({ ...GOOD, lines: [draftLineOf(line)] })) as BillDraftFields;
  const restored = editorLineOf(back.lines[0]);
  assert.deepEqual(restored.unread, ["gst_rate"]);
  assert.equal(isValidBillLine(restored), false,
    "a restore that dropped the flag would turn the 0 placeholder into a rate the CA appears to have chosen");
  assert.equal(buildLinePayload([restored]).length, 0, "and the line must still not reach the save");
});

test("a flag that is not one of the four discards the draft", () => {
  assert.equal(validateBillDraft({ ...GOOD, lines: [{ ...GOOD.lines[0], unread: ["colour"] }] }), null);
  assert.equal(validateBillDraft({ ...GOOD, lines: [{ ...GOOD.lines[0], unread: "gst_rate" }] }), null);
  assert.equal(validateBillDraft({ ...GOOD, lines: [{ ...GOOD.lines[0], unread: [3] }] }), null);
  assert.deepEqual(
    validateBillDraft({ ...GOOD, lines: [{ ...GOOD.lines[0], unread: ["rate", "rate"] }] })?.lines[0].unread,
    ["rate"], "a repeated flag is one flag");
});

// ── the editor's line <-> the draft's line ──

test("draftLineOf takes the raw fields and leaves the editor's own working state behind", () => {
  const editor = {
    ...GOOD.lines[1], _k: 7, product: { id: "cat-maint" }, hsnMatches: [{ id: "x" }],
  } as unknown as PurchaseBillLine;
  const kept = draftLineOf(editor);
  assert.deepEqual(kept, GOOD.lines[1]);
  assert.equal("_k" in kept, false);
  assert.equal("product" in kept, false);
  assert.equal("hsnMatches" in kept, false);
});

test("a line with nothing optional set round-trips to an identical object, so 'unchanged' compares equal", () => {
  const plain: PurchaseBillLine = {
    description: "x", hsn_sac: "", qty: "1", rate: "", gst_rate: 18, unit: "NOS",
    expense_account_id: "", service_catalogue_id: "",
  };
  assert.deepEqual(draftLineOf(editorLineOf(draftLineOf(plain))), draftLineOf(plain));
  assert.deepEqual(Object.keys(draftLineOf(plain)).sort(),
    ["description", "expense_account_id", "gst_rate", "hsn_sac", "qty", "rate", "service_catalogue_id", "unit"]);
});

test("the cess boxes and the §17(5) decision survive", () => {
  const l: PurchaseBillLine = {
    ...GOOD.lines[0], cessPercent: "12", cessPerUnit: "4.5", itc_eligible: false,
    blocked_credit_reason: "§17(5)(b)",
  };
  const back = validateBillDraft(roundTrip({ ...GOOD, lines: [draftLineOf(l)] })) as BillDraftFields;
  assert.equal(back.lines[0].cessPercent, "12");
  assert.equal(back.lines[0].cessPerUnit, "4.5");
  assert.equal(back.lines[0].itc_eligible, false);
  assert.equal(back.lines[0].blocked_credit_reason, "§17(5)(b)");
});

// ── what counts as typing ──

test("attaching an invoice file is not typing", () => {
  const withFile = { ...GOOD, documentAttached: true };
  assert.deepEqual(withoutDocument(withFile), withoutDocument(GOOD));
  assert.equal(withoutDocument(withFile).documentAttached, false);
});

// ── applying one ──

test("a draft applied to the same client comes back unchanged", () => {
  const applied = applyBillDraft(GOOD, ctx());
  assert.deepEqual(applied.fields, GOOD);
  assert.equal(applied.vendorDropped, false);
  assert.equal(applied.accountsDropped, 0);
  assert.deepEqual(applied.catalogueIds, ["cat-rent", "cat-maint"]);
});

test("a supplier that is no longer usable is not left selected", () => {
  const applied = applyBillDraft(GOOD, ctx({ vendorIds: new Set(["someone-else"]) }));
  assert.equal(applied.fields.vendorId, "");
  assert.equal(applied.vendorDropped, true);
  assert.equal(applied.fields.billNo, "RENT/09", "everything else the person typed is kept");
});

test("an account since removed from the chart is cleared on that line and the amounts stay", () => {
  const applied = applyBillDraft(GOOD, ctx({ accountIds: new Set(["acc-rent"]) }));
  assert.equal(applied.fields.lines[0].expense_account_id, "acc-rent");
  assert.equal(applied.fields.lines[1].expense_account_id, "");
  assert.equal(applied.fields.lines[1].rate, "8000");
  assert.equal(applied.accountsDropped, 1);
});

test("a foreign currency the picker no longer offers falls back to INR with its rate, and says so", () => {
  const usd = { ...GOOD, currency: "USD", exchangeRate: "83.25" };
  const kept = applyBillDraft(usd, ctx());
  assert.equal(kept.fields.currency, "USD");
  assert.equal(kept.fields.exchangeRate, "83.25");
  assert.equal(kept.currencyDropped, false);

  // multi-currency switched off, or the list not loaded: a currency with no
  // control to see or change it would be a bill nobody can read the rate of.
  const gone = applyBillDraft(usd, ctx({ currencyCodes: new Set() }));
  assert.equal(gone.fields.currency, "");
  assert.equal(gone.fields.exchangeRate, "", "a rate for a currency that was dropped is dropped with it");
  assert.equal(gone.currencyDropped, true);
  assert.match(billRestoreNote(gone, { catalogueMissing: 0, documentAttached: false }) as string, /INR/);
  assert.equal(applyBillDraft(GOOD, ctx({ currencyCodes: new Set() })).currencyDropped, false,
    "an INR bill is never a dropped currency");
});

test("a line that named no account is not counted as a dropped one", () => {
  const blank = { ...GOOD, lines: [{ ...GOOD.lines[0], expense_account_id: "" }] };
  assert.equal(applyBillDraft(blank, ctx({ accountIds: new Set() })).accountsDropped, 0);
});

test("restoring into an EXISTING draft bill never changes its supplier, currency or reverse-charge flag", () => {
  // PurchaseBillUpdateIn has no vendor_id, currency, exchange_rate or
  // is_reverse_charge: they were frozen at creation, and the editor shows each
  // read-only.
  const draft = { ...GOOD, vendorId: "v-other", currency: "USD", exchangeRate: "83.1", isReverseCharge: true };
  const applied = applyBillDraft(draft, ctx({
    isEdit: true,
    current: { vendorId: "v-landlord", currency: "", exchangeRate: "", isReverseCharge: false },
    vendorIds: new Set(["v-landlord"]),
  }));
  assert.equal(applied.fields.vendorId, "v-landlord");
  assert.equal(applied.fields.currency, "");
  assert.equal(applied.fields.exchangeRate, "");
  assert.equal(applied.fields.isReverseCharge, false);
  assert.equal(applied.vendorDropped, false, "no question about the supplier is asked of an existing bill");
  assert.equal(applied.fields.notes, "September rent", "the editable fields are restored");
});

test("the catalogue lookup links the rows that came back and unlinks the ones that did not", () => {
  const found = new Map([["cat-rent", { id: "cat-rent", name: "Rent" }]]);
  // The editor's line carries `product`; the fixture's lines are the raw fields, so the row type is spelled out
  // here rather than inferred from a fixture that predates it.
  type Row = (typeof GOOD.lines)[number] & { product?: { id: string; name: string } | null };
  const { lines, missing } = linkCatalogue<{ id: string; name: string }, Row>(GOOD.lines.map((l) => ({ ...l })), found);
  assert.equal(missing, 1);
  assert.deepEqual(lines[0].product, { id: "cat-rent", name: "Rent" });
  assert.equal(lines[0].service_catalogue_id, "cat-rent");
  assert.equal(lines[1].service_catalogue_id, "", "a line cannot be saved linked to something nobody can see");
  assert.equal(lines[1].product, null);
});

test("a line with no catalogue link is not a missing one", () => {
  const { lines, missing } = linkCatalogue(
    [{ service_catalogue_id: "" }], new Map<string, { id: string }>());
  assert.equal(missing, 0);
  assert.equal(lines[0].service_catalogue_id, "");
});

// ── the sentence ──

test("the restore note names each thing the draft could not carry, and is null when there is none", () => {
  const clean = applyBillDraft(GOOD, ctx());
  assert.equal(billRestoreNote(clean, { catalogueMissing: 0, documentAttached: false }), null);

  const messy = applyBillDraft(GOOD, ctx({ vendorIds: new Set(), accountIds: new Set() }));
  const note = billRestoreNote(messy, { catalogueMissing: 2, documentAttached: true }) as string;
  assert.match(note, /supplier/i);
  assert.match(note, /2 accounts/);
  assert.match(note, /2 lines lost their product/);
  assert.match(note, /upload it again/);
  assert.match(billRestoreNote(clean, { catalogueMissing: 1, documentAttached: false }) as string,
    /1 line lost its product/);
});
