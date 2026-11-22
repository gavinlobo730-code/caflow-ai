// AN EDIT SCREEN DOES NOT SAY IT SAVED OVER EVIDENCE IT WAS ASKED TO REMOVE, AND A DRAFT'S EMPTIED LINK IS SENT AS A CLEAR (POST-A-399, the sixth slice).
// Run with: node --experimental-strip-types --test scripts/an-edit-screen-does-not-say-saved-over-evidence-or-a-draft-link-it-was-asked-to-remove.test.ts
//
// THE DEFECT, in its last two shapes.
//  1. EVIDENCE IN TEXT. The invoice editor sent the shipping bill number and the port code, and the bill editor the supplier's own invoice number, the Form 15CA acknowledgement number and the
//     Form 15CB UDIN, as `text || undefined`. The server reads a missing key (and a null) for each as "not sent", on purpose: evidence is corrected and not removed. So a box the person emptied
//     changed nothing and the screen said the document was saved. The dates among them were POST-A-388's; these are the texts, and the screens refuse the same way, beside the button.
//  2. WHAT ONLY A DRAFT MAY TAKE AWAY. The four note editors sent the document a note is raised against as `id || undefined` and its reason as `text || undefined`, and the invoice editor its
//     place of supply the same way. On a DRAFT each of those may be absent, and the server now clears them on a draft when the request says null, so the screens say it: an emptied box that had a
//     value on file is `null` (`editedChoice` / `editedText`), an untouched empty one is nothing.
//
// THE RULE, per screen:
//  - an evidence sentence comes from `removedEvidenceProblem(what, <the snapshot's value>, <the box>, noun)`, is latched (`useDateRefusal`), refuses the Save before a request is built, is drawn, and
//    is never copied into the form's error;
//  - the draft edit (the PATCH) of a note sends its link and its reason through `editedChoice` / `editedText` against what the note opened with, and the CREATE (the POST) still sends a blank as
//    nothing, because a new document has nothing to clear.
//
// WHAT THIS CANNOT SEE. Another editor with the same shape is not found by it: the population is the six document editors, named. What each does in a browser is held by the weekly drive
// (`scripts/drive/weekly/evidenceAndDraftLinks.mjs`), and the sentence's words by `lib/forms/removedEvidence.test.ts`.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./an-edit-screen-does-not-say-saved-over-a-date-it-was-asked-to-remove.test.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));
const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

interface Evidence { what: string; snapshot: string; box: string; noun: string }
const SCREENS: { name: string; file: string; derived: string; latch: string; evidence: Evidence[] }[] = [
  { name: "the sales invoice", file: "components/invoices/InvoiceEditor.tsx", derived: "shippingEvidenceCleared", latch: "shippingEvidenceRefusal", evidence: [
    { what: "The shipping bill number", snapshot: "shippingBillNo", box: "shippingBillNo", noun: "number" },
    { what: "The port code", snapshot: "portCode", box: "portCode", noun: "code" },
  ] },
  { name: "the purchase bill", file: "components/purchases/PurchaseBillEditor.tsx", derived: "billEvidenceCleared", latch: "billEvidenceRefusal", evidence: [
    { what: "The vendor invoice number", snapshot: "billNo", box: "billNo", noun: "number" },
    { what: "The Form 15CA acknowledgement number", snapshot: "form15caAckNo", box: "form15caAckNo", noun: "number" },
    { what: "The Form 15CB UDIN", snapshot: "form15cbUdin", box: "form15cbUdin", noun: "UDIN" },
  ] },
];

for (const s of SCREENS) {
  test(`${s.name}: each evidence text is judged against what is on file, by the one rule`, () => {
    const src = read(s.file);
    for (const e of s.evidence) {
      const call = new RegExp(`removedEvidenceProblem\\(\\s*"${esc(e.what)}"\\s*,\\s*initialSnapshot\\.current\\.${e.snapshot}\\s*,\\s*${e.box}\\s*,\\s*"${e.noun}"\\s*\\)`);
      assert.match(src, call, `${s.name} does not judge ${e.what.toLowerCase()} against the snapshot of what is on file`);
    }
  });

  test(`${s.name}: the sentence is derived, latched, refuses the Save before a request is built, and is drawn`, () => {
    const src = read(s.file);
    assert.match(src, new RegExp(`const ${s.derived}\\s*=`), "the sentence is not derived");
    assert.match(src, new RegExp(`const ${s.latch} = useDateRefusal\\(${s.derived}\\)`), "the sentence is not latched");
    const refuse = src.indexOf(`if (${s.derived}) { setError(null); ${s.latch}.refuse(); return; }`);
    assert.ok(refuse > 0, "the Save does not refuse over emptied evidence");
    const firstRequest = src.indexOf("apiCall(", refuse);
    assert.ok(firstRequest > refuse, "the refusal is not before the request");
    const save = src.lastIndexOf("async function save(", refuse);
    assert.ok(save > 0 && !src.slice(save, refuse).includes("await apiCall("), "a request is sent before the refusal");
    assert.match(src, new RegExp(`\\{${s.latch}\\.shown && <div[^>]*data-removed-evidence[^>]*><Callout tone="problem">\\{${s.latch}\\.shown\\}</Callout></div>\\}`), "the sentence is not drawn");
  });

  test(`${s.name}: the sentence is never copied into the form's error, where it would stay after the value was put back`, () => {
    const src = read(s.file);
    for (const setter of ["setError", "setFormError", "setMsg"]) {
      assert.doesNotMatch(src, new RegExp(`${setter}\\(\\s*${s.derived}`), `${setter} is handed the derived sentence`);
      assert.doesNotMatch(src, new RegExp(`${setter}\\(\\s*${s.latch}\\.shown`), `${setter} is handed the latched sentence`);
    }
  });
}

test("the evidence boxes are still sent as text or nothing: the screen refuses, it does not clear", () => {
  const invoice = read("components/invoices/InvoiceEditor.tsx");
  assert.match(invoice, /shipping_bill_no: shippingBillNo\.trim\(\) \|\| undefined/);
  assert.match(invoice, /port_code: portCode\.trim\(\)\.toUpperCase\(\) \|\| undefined/);
  const bill = read("components/purchases/PurchaseBillEditor.tsx");
  assert.match(bill, /bill_no: billNo\.trim\(\) \|\| undefined/);
  assert.doesNotMatch(invoice + bill, /(shipping_bill_no|port_code|bill_no|form_15ca_ack_no|form_15cb_udin): edited(Text|Choice)\(/, "evidence is sent as a clear");
});

const NOTES: { name: string; file: string; key: string; box: string }[] = [
  { name: "the sales credit note", file: "components/sales/SalesCreditNoteEditor.tsx", key: "sales_invoice_id", box: "invoiceId" },
  { name: "the sales debit note", file: "components/sales/SalesDebitNoteEditor.tsx", key: "sales_invoice_id", box: "invoiceId" },
  { name: "the purchase debit note", file: "components/purchases/DebitNoteEditor.tsx", key: "purchase_bill_id", box: "billId" },
  { name: "the purchase credit note", file: "components/purchases/PurchaseCreditNoteEditor.tsx", key: "purchase_bill_id", box: "billId" },
];

for (const n of NOTES) {
  test(`${n.name}: a draft's edit says when the document it was raised against, or its reason, was taken away; a new note says nothing for a blank`, () => {
    const src = read(n.file);
    const patch = src.indexOf('"PATCH"');
    const post = src.indexOf('"POST"');
    assert.ok(patch > 0 && post > patch, "the edit and the create are not where this test reads them");
    // The PATCH's payload is built just above its call, and the create's just below its own.
    const edit = src.slice(src.lastIndexOf("patchPayload", patch) - 1500, patch);
    assert.match(edit, new RegExp(`${n.key}: editedChoice\\(${n.box}, existing\\.${n.key}\\)`), "the draft edit does not send an emptied link as a clear");
    assert.match(edit, /reason: editedText\(reason, existing\.reason\)/, "the draft edit does not send an emptied reason as a clear");
    assert.doesNotMatch(edit, new RegExp(`${n.key}: ${n.box} \\|\\| undefined`), "the draft edit still sends an emptied link as nothing");
    const create = src.slice(post, post + 1500);
    assert.match(create, new RegExp(`${n.key}: ${n.box} \\|\\| undefined`), "a new note sends a clear for a box nobody filled");
    assert.match(create, /reason: reason\.trim\(\) \|\| undefined/);
  });
}

test("the sales invoice: a draft's emptied place of supply is sent as a clear, and a new invoice's blank one as nothing", () => {
  const src = read("components/invoices/InvoiceEditor.tsx");
  assert.equal((src.match(/supply_state_code: editedChoice\(supplyStateCode, initialSnapshot\.current\.supplyStateCode\)/g) ?? []).length, 1);
  assert.equal((src.match(/supply_state_code: supplyStateCode \|\| undefined/g) ?? []).length, 1, "the create no longer sends a blank as nothing");
  const cleared = src.indexOf("supply_state_code: editedChoice(");
  assert.ok(src.lastIndexOf('"PATCH"', cleared) > src.lastIndexOf('"POST"', cleared), "the clear is on the create and not on the draft's edit");
});
