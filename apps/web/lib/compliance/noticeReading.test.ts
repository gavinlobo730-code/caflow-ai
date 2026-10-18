// Correcting a staged notice reading: the form and the patch. Run with:
//   node --experimental-strip-types --test lib/compliance/noticeReading.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { buildCorrection, NOTICE_TYPE_OPTIONS, readingFormFrom } from "./noticeReading.ts";

const ROW = {
  id: "n1", authority: "GSTN", notice_type: "gst_scrutiny", reference_no: "ASMT-10/42",
  issue_date: "2026-09-20", response_due_date: "2026-10-15T00:00:00+00:00", description: "Reply to the scrutiny notice.",
};

test("a stored row reads into form text, a timestamp is cut to its day and an absent value is empty", () => {
  assert.deepEqual(readingFormFrom(ROW), {
    authority: "GSTN", notice_type: "gst_scrutiny", reference_no: "ASMT-10/42", issue_date: "2026-09-20",
    response_due_date: "2026-10-15", description: "Reply to the scrutiny notice.",
  });
  assert.deepEqual(readingFormFrom({ authority: "MCA21", reference_no: null, issue_date: undefined }), {
    authority: "MCA21", notice_type: "", reference_no: "", issue_date: "", response_due_date: "", description: "",
  });
});

test("an unchanged form is an empty patch", () => {
  assert.deepEqual(buildCorrection(ROW, readingFormFrom(ROW)), {});
});

test("only what changed is sent, trimmed", () => {
  const form = { ...readingFormFrom(ROW), response_due_date: " 2026-10-20 ", reference_no: "ASMT-10/43" };
  assert.deepEqual(buildCorrection(ROW, form), { response_due_date: "2026-10-20", reference_no: "ASMT-10/43" });
});

test("clearing a field sends the empty string, which the server reads as the notice stating none", () => {
  const form = { ...readingFormFrom(ROW), reference_no: "", response_due_date: "" };
  assert.deepEqual(buildCorrection(ROW, form), { reference_no: "", response_due_date: "" });
});

test("whitespace around an unchanged value is not a change, and an absent stored value equals an empty field", () => {
  const form = { ...readingFormFrom({ ...ROW, reference_no: null }), authority: "  GSTN  " };
  assert.deepEqual(buildCorrection({ ...ROW, reference_no: null }, form), {});
});

test("the type list is the seven the server knows", () => {
  assert.deepEqual(NOTICE_TYPE_OPTIONS.map((o) => o.value),
    ["gst_scrutiny", "income_tax_demand", "income_tax_notice", "mca_show_cause", "tds_default", "customs", "other"]);
});
