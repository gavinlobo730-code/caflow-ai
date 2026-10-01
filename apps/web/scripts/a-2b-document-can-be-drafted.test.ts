// gst-13 — a GSTR-2B document the books have no bill for can be drafted into one.
// Run with:
//   node --experimental-strip-types --test scripts/a-2b-document-can-be-drafted.test.ts
//
// WHAT WAS MISSING
//   For a `missing_in_books` row the screen said "chase the document" and
//   stopped, although it held every figure a bill needs.
//
// THE RULES ARE THE SERVER'S — `domain/gst/draft_bill_from_2b` decides which
// documents may be drafted and what the draft is, and
// `apps/api/tests/test_a_draft_bill_can_be_created_from_a_2b_document.py` pins
// it. This holds what only the screen can get wrong: the request carries an
// ADDRESS and no figure, the button cannot be pressed twice, and nothing here
// receives a bill.
//
// This reads source, because the web suite has no DOM. It is the floor, not the
// ceiling: a click-through in a browser is what checks the rest.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));

const PAGE = read("app/clients/[id]/compliance/gst/page.tsx");
const DRAFT = read("components/gst/CreateDraftBillFrom2B.tsx");
const API = read("lib/api/index.ts");

function tab(): string {
  const at = PAGE.indexOf("function GSTR2BTab(");
  assert.ok(at >= 0, "GSTR2BTab is gone — move this assertion with it");
  const next = PAGE.indexOf("\nfunction ", at + 1);
  return PAGE.slice(at, next === -1 ? undefined : next);
}

test("the draft request carries the document's ADDRESS and no figure", () => {
  const call = DRAFT.slice(DRAFT.indexOf("createDraftBillFrom2b({"),
                           DRAFT.indexOf("});", DRAFT.indexOf("createDraftBillFrom2b({")));
  for (const key of ["client_id", "period", "section", "document_type",
                     "supplier_gstin", "document_number"]) {
    assert.match(call, new RegExp(`\\b${key}\\b`), `the address names ${key}`);
  }
  for (const forbidden of ["amount", "taxable", "paise", "rate", "bill_date", "bill_no",
                           "lines", "total", "cgst", "sgst", "igst", "cess"]) {
    assert.doesNotMatch(call, new RegExp(forbidden, "i"),
      `the screen must not send ${forbidden}: the server reads it off the stored row, ` +
      "so a bill the portal never carried cannot be asked for");
  }
});

test("the API method posts to the one drafting route and to nothing that receives", () => {
  assert.match(API, /createDraftBillFrom2b: \(body: Gstr2bDraftBillRequest\) =>/);
  assert.match(API, /"\/api\/purchase-bills\/from-2b"/);
  assert.doesNotMatch(DRAFT, /\/receive|\.receive\(|receivePurchase/,
    "creating a draft never receives it — receiving is what posts and claims");
});

test("the button is disabled while the request is in flight and after it has succeeded", () => {
  assert.match(DRAFT, /if \(busy \|\| done /);
  assert.match(DRAFT, /disabled=\{busy\}/);
  // once done, the button is replaced by the result — there is no second click.
  assert.match(DRAFT, /if \(done\) \{[\s\S]*?return \(/);
});

test("the draft is said to be a draft, linked, and the server's disagreement is shown unchanged", () => {
  assert.match(DRAFT, /Draft bill created — not received\./);
  assert.match(DRAFT, /documentHref\(clientId, "purchases", "bills", done\.bill\.id\)/);
  // The pair is rendered by the ONE component that decides its tones (what
  // disagrees is actionable, the caveats are read once) — not a hand-rolled list.
  assert.match(DRAFT, /<StatutoryNotes\s+gaps=\{done\.agrees_with_2b \? \[\] : done\.differences\}\s+caveats=\{done\.caveats\}/);
  assert.doesNotMatch(DRAFT, /\.caveats\.map\(|\.differences\.map\(/);
  assert.match(DRAFT, /objectWithLists<Gstr2bDraftBill>\(resp\.data, "differences", "caveats"\)/);
});

test("a refusal is shown in words, in an alert, beside the row", () => {
  assert.match(DRAFT, /role="alert"/);
  assert.match(DRAFT, /resp\.error \?\? /);
  assert.match(DRAFT, /e instanceof Error \? e\.message/);
});

test("the tab offers the draft only where the SERVER said it may, and only in the one bucket", () => {
  const t = tab();
  assert.match(t, /m\.draft_bill_offered \?/);
  assert.match(t, /bucket === "missing_in_books" && \(/);
  assert.match(t, /<CreateDraftBillFrom2B clientId=\{clientId\} period=\{result\.period\}/);
  assert.match(t, /m\.draft_bill_refusal \?\? ""/);
  // the screen holds no list of which kinds of document are draftable
  assert.doesNotMatch(t, /document_type === "invoice"|section === "b2b"|credit_note|cdnr|impg/);
});

