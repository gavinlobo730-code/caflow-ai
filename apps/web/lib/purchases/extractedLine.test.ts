// AI-01 — an AI-extracted line shows what the document said, and nothing more.
//   node --experimental-strip-types --test lib/purchases/extractedLine.test.ts
//
// The editor used to build an extracted line as
//   qty: String(li.quantity ?? 1), unit: "NOS", gst_rate: (li.gst_rate_bps ?? 1800) / 100
// so a quantity, a unit and a rate nobody read were rendered exactly as ones
// the document carried, and (server side) a real 0% had already become 1800.
import test from "node:test";
import assert from "node:assert/strict";
import {
  lineFromExtraction, unreadAfterEdit, blockingUnread, type ExtractedLine,
} from "./extractedLine.ts";
import {
  isValidBillLine, validateBillEditor, buildLinePayload, type PurchaseBillLine,
} from "./billEditor.ts";

const READ: ExtractedLine = {
  description: "Widget", hsn_sac: "1234", quantity: 2, unit: "NOS",
  rate_paise: 10000, gst_rate_bps: 1800, not_read: [],
};

function editorLine(li: ExtractedLine, over: Partial<PurchaseBillLine> = {}): PurchaseBillLine {
  return { ...lineFromExtraction(li), expense_account_id: "", service_catalogue_id: "SVC-1", ...over };
}

// ── the premise: a fully-read line is an ordinary line ───────────────────────

test("a fully read line carries nothing unread and the figures as read", () => {
  const l = lineFromExtraction(READ);
  assert.equal(l.unread, undefined);
  assert.equal(l.qty, "2");
  assert.equal(l.unit, "NOS");
  assert.equal(l.rate, "100");
  assert.equal(l.gst_rate, 18);
  assert.equal(isValidBillLine(editorLine(READ)), true);
});

// ── a real 0% is a reading ───────────────────────────────────────────────────

test("a line the document prints at 0% stays 0% and is not flagged", () => {
  const l = lineFromExtraction({ ...READ, gst_rate_bps: 0 });
  assert.equal(l.gst_rate, 0);
  assert.equal(l.unread, undefined);
  assert.equal(isValidBillLine(editorLine({ ...READ, gst_rate_bps: 0 })), true);
});

test("a stated rate off the standard list is carried as it is", () => {
  assert.equal(lineFromExtraction({ ...READ, gst_rate_bps: 150 }).gst_rate, 1.5);
  assert.equal(lineFromExtraction({ ...READ, gst_rate_bps: 750 }).gst_rate, 7.5);
});

// ── an absent value is unknown — empty and flagged, never a default ──────────

test("a null GST rate is unread and is NOT 18%", () => {
  const l = lineFromExtraction({ ...READ, gst_rate_bps: null, not_read: ["gst_rate"] });
  assert.deepEqual(l.unread, ["gst_rate"]);
  assert.notEqual(l.gst_rate, 18);
});

test("a missing quantity is empty, not 1", () => {
  const l = lineFromExtraction({ ...READ, quantity: null, not_read: ["quantity"] });
  assert.equal(l.qty, "");
  assert.deepEqual(l.unread, ["quantity"]);
});

test("a missing unit is empty, not NOS", () => {
  const l = lineFromExtraction({ ...READ, unit: null, not_read: ["unit"] });
  assert.equal(l.unit, "");
  assert.deepEqual(l.unread, ["unit"]);
});

test("a missing rate is empty, not nil", () => {
  const l = lineFromExtraction({ ...READ, rate_paise: null, not_read: ["rate"] });
  assert.equal(l.rate, "");
  assert.deepEqual(l.unread, ["rate"]);
});

test("a unit the document printed that is not a code is kept as printed, and unread", () => {
  const l = lineFromExtraction({ ...READ, unit: null, unit_as_printed: "Kg", not_read: ["unit"] });
  assert.equal(l.unit, "");
  assert.equal(l.unitAsPrinted, "Kg");
});

// ── a backend one deploy behind sends no flags, and must not read as "all read" ─

test("with no not_read flags at all, a null still cannot become a default", () => {
  const l = lineFromExtraction({
    description: "x", quantity: null, unit: null, rate_paise: null, gst_rate_bps: null,
  });
  assert.deepEqual(l.unread, ["quantity", "unit", "gst_rate", "rate"]);
  assert.equal(l.qty, "");
  assert.equal(l.unit, "");
  assert.equal(l.rate, "");
});

test("a line with every key missing is entirely unread", () => {
  assert.deepEqual(lineFromExtraction({}).unread, ["quantity", "unit", "gst_rate", "rate"]);
});

test("unknown names in not_read are ignored rather than trusted", () => {
  const l = lineFromExtraction({ ...READ, not_read: ["colour", "gst_rate"] });
  assert.deepEqual(l.unread, ["gst_rate"]);
});

// ── typing into a field is stating it ────────────────────────────────────────

test("typing into a flagged field confirms it, and only it", () => {
  assert.deepEqual(unreadAfterEdit(["quantity", "gst_rate"], { qty: "3" }), ["gst_rate"]);
  assert.deepEqual(unreadAfterEdit(["quantity", "gst_rate"], { gst_rate: 0 }), ["quantity"]);
});

test("choosing a 0% rate confirms it — 0 is an answer", () => {
  assert.equal(unreadAfterEdit(["gst_rate"], { gst_rate: 0 }), undefined);
});

test("editing a field that was never flagged changes nothing", () => {
  const u = ["gst_rate"] as const;
  assert.deepEqual(unreadAfterEdit([...u], { description: "renamed" }), ["gst_rate"]);
});

test("a fully confirmed line is indistinguishable from one typed by hand", () => {
  assert.equal(unreadAfterEdit(["unit"], { unit: "KGS" }), undefined);
  assert.equal(unreadAfterEdit(undefined, { qty: "1" }), undefined);
});

// ── what stops a save ────────────────────────────────────────────────────────

test("an unconfirmed GST rate stops the line being valid; an unread unit does not", () => {
  const noRate = editorLine({ ...READ, gst_rate_bps: null });
  const noUnit = editorLine({ ...READ, unit: null });
  assert.deepEqual(blockingUnread(noRate), ["gst_rate"]);
  assert.equal(isValidBillLine(noRate), false);
  assert.deepEqual(blockingUnread(noUnit), []);
  assert.equal(isValidBillLine(noUnit), true);
});

test("the CA choosing the rate makes the line valid", () => {
  const l = editorLine({ ...READ, gst_rate_bps: null });
  const after = { ...l, gst_rate: 5, unread: unreadAfterEdit(l.unread, { gst_rate: 5 }) };
  assert.equal(isValidBillLine(after), true);
});

test("the editor refuses to save an unconfirmed line, naming it, instead of dropping it", () => {
  const good = editorLine(READ);
  const unconfirmed = editorLine({ ...READ, description: "Mystery", gst_rate_bps: null });
  const v = validateBillEditor({
    vendorId: "V", billDate: "2026-06-01", lines: [good, unconfirmed],
    isForeign: false, exchangeRate: "",
  });
  assert.equal(v.ok, false);
  assert.match(v.errors.unread ?? "", /Line 2/);
  assert.match(v.errors.unread ?? "", /GST rate/);
  // The premise: without the flag the same two lines are saveable, and the
  // payload would have silently dropped the second.
  assert.equal(buildLinePayload([good, unconfirmed]).length, 1);
});

test("a fully read extraction validates clean", () => {
  const v = validateBillEditor({
    vendorId: "V", billDate: "2026-06-01", lines: [editorLine(READ)],
    isForeign: false, exchangeRate: "",
  });
  assert.equal(v.ok, true);
  assert.equal(v.errors.unread, undefined);
});

test("an unread unit is never sent as a unit", () => {
  const p = buildLinePayload([editorLine({ ...READ, unit: null })]);
  assert.equal(p[0].unit, undefined);
});
