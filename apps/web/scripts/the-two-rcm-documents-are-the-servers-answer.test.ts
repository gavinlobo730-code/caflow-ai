/**
 * PUR-19 — the browser must not learn that the two sections differ.
 *
 * CGST Act s.31(3)(f) reaches only a supply from an UNREGISTERED supplier;
 * s.31(3)(g) reaches every reverse-charge payment. That distinction is the
 * whole feature, and `domain/gst/rcm_documents.py` is where it lives. A copy of
 * it in the browser is a second place for it to be wrong — and the browser's
 * copy is the one that decides what the CA is shown.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const PANEL = "components/purchases/RcmDocumentPanel.tsx";
const PAGE = "app/clients/[id]/purchases/page.tsx";
const API = "lib/api/index.ts";

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

test("the panel decides nothing about either section", () => {
  const src = code(PANEL);
  // The three facts the server owns. Any of them here is a second rule.
  assert.doesNotMatch(src, /gst_registration_status/,
    "whether the supplier is registered is the server's question");
  assert.doesNotMatch(src, /is_reverse_charge/,
    "whether the bill carries a reverse-charge liability is the server's");
  assert.doesNotMatch(src, /unregistered\s*[=?]==/,
    "the s.31(3)(f) limb must not be re-tested here");
});

test("the section and the rule come off the wire, never spelled here", () => {
  const src = code(PANEL);
  assert.match(src, /preview\?\.section/, "the section is the server's answer");
  assert.match(src, /preview\?\.rule/, "and so is the rule");
  // The panel may NAME the two kinds (it is a label), but it must not assert
  // which provision each is issued under — that pairing is the statute.
  assert.doesNotMatch(src, /"CGST Act s\.31\(3\)\(f\)"/);
  assert.doesNotMatch(src, /"CGST Act s\.31\(3\)\(g\)"/);
});

test("a reason and a gap are rendered as different things", () => {
  /* `reasons` means the Act does not ask for the document — settled.
     `gaps` means nobody can yet tell — actionable. A screen that renders the
     two the same way turns a named gap into a refusal, which is the defect the
     third registration state exists to prevent. */
  const src = code(PANEL);
  assert.match(src, /preview\.reasons\.map/);
  assert.match(src, /preview\.gaps\.map/);
  assert.match(src, /Not decided yet/,
    "the gap block must say that it is undecided rather than refused");
});

test("every caveat and gap on the particulars is rendered", () => {
  const src = code(PANEL);
  assert.match(src, /p\.caveats\.map/,
    "a document shown without the sentence saying its bill contradicts itself " +
    "is exactly the disclosure a reader would rely on");
  assert.match(src, /p\.gaps\.map/);
});

test("the supplier block shows an absent GSTIN as a fact, not a blank", () => {
  const src = code(PANEL);
  assert.match(src, /Not registered/,
    "on a self-invoice the missing GSTIN is WHY the document exists");
});

test("the issue button cannot be pressed twice or on a document already issued", () => {
  const src = code(PANEL);
  const button = src.match(/<button onClick=\{issue\}[\s\S]*?<\/button>/);
  assert.ok(button, "the issue control exists");
  assert.match(button![0], /disabled=\{[^}]*issuing/,
    "issuing is a server write, so a double-click must be stopped");
  assert.match(button![0], /issued/,
    "a second document for one parent is a duplicate statutory record");
});

test("both entry points exist and neither gates on the statute", () => {
  const src = code(PAGE);
  assert.match(src, /setRcmDoc\(\{ kind: "self_invoice"/,
    "a bill can be taken to its s.31(3)(f) self-invoice");
  assert.match(src, /setVoucherFor\(p\.id\)/,
    "a payment can be taken to its s.31(3)(g) payment voucher");
  // Offered on every row: gating in the browser would need the registration
  // question here, which is the thing this whole file forbids.
  assert.doesNotMatch(src, /is_reverse_charge\s*&&\s*setRcmDoc/);
});

test("the api layer carries shapes and no statute", () => {
  const src = code(API);
  const start = src.indexOf("rcmDocuments: {");
  assert.ok(start > 0, "the namespace exists");
  const namespace = src.slice(start, start + 2000);
  assert.match(namespace, /preview\/self-invoice/);
  assert.match(namespace, /preview\/payment-voucher/);
  // The preview is a GET and the issue a POST. A preview that wrote would make
  // "show me what this would say" a statutory act.
  assert.doesNotMatch(namespace,
    /previewSelfInvoice[\s\S]{0,200}method: "POST"/);
});

/* ── the one fact the two documents turn on ────────────────────────────────
   `vendors.gst_registration_status` decides whether a s.31(3)(f) self-invoice
   is due at all. Both doors that record it must OFFER the server's own list:
   a hardcoded pair in the browser is a second vocabulary, and it silently
   drops the third state — `unrecorded` — which is what the self-invoice names
   as a gap instead of guessing. */

const SUPPLIERS = "app/accounting/suppliers/page.tsx";

for (const [rel, state] of [
  [PAGE, "gstRegistrationOptions"],
  [SUPPLIERS, "registrationStates"],
] as const) {
  test(`${rel} offers the server's registration states, not its own`, () => {
    const src = code(rel);
    assert.match(src, /api\.rcmDocuments\.registrationStates\(\)/,
      "the list is fetched from /api/rcm-documents/registration-states");
    assert.match(src, new RegExp(`${state}\\s*\\.filter\\(`),
      "and the options are built from what came back");
    // A literal option would survive the server saying something different.
    assert.doesNotMatch(src, /<option value="registered"/);
    assert.doesNotMatch(src, /<option value="unregistered"/);
  });
}

test("neither door can store the third state as a value", () => {
  /* `unrecorded` is the ABSENCE of an answer. Offering it as an option would
     make NULL and the string 'unrecorded' two spellings of one thing — and the
     column's CHECK refuses the string, so the save would simply fail. */
  for (const rel of [PAGE, SUPPLIERS]) {
    assert.match(code(rel), /!==\s*"unrecorded"/,
      `${rel} must filter the third state out of the picker`);
  }
});
