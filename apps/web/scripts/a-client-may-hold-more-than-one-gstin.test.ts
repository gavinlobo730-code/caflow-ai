/**
 * GST-20 — the browser must not decide which registrations a client holds.
 *
 * CGST Act s.25(1) makes registration state-wise and s.25(2) allows one per
 * place of business, so one legal person may hold several GSTINs and each owes
 * its own GSTR-1 and GSTR-3B. `domain/gst/registrations.py` decides which
 * number is well formed, which state it belongs to, whether the client already
 * holds it, and which registration types file the ordinary pair at all.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const TAB = "components/gst/RegistrationsTab.tsx";
const PAGE = "app/clients/[id]/compliance/gst/page.tsx";
const API = "lib/api/index.ts";

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

test("the tab validates no GSTIN of its own", () => {
  /* `apps/web/lib/gst/gstin.ts` is the keystroke mirror and is pinned to the
     backend by a fixture. A THIRD check here — a regex, a length test, a state
     lookup — would be the one that drifts, and it decides which registration a
     return is filed under. */
  const src = code(TAB);
  assert.doesNotMatch(src, /\[0-9\]\{2\}\[A-Z\]\{5\}/, "no GSTIN pattern here");
  assert.doesNotMatch(src, /checkDigit|check_digit/i);
  // The state comes off the number, server-side. Asking for it separately is
  // what lets the two disagree.
  assert.doesNotMatch(src, /state_code:/, "the state is derived, never sent");
});

test("the registration types and frequencies come off the wire", () => {
  const src = code(TAB);
  assert.match(src, /api\.clientGstRegistrations\.kinds\(\)/);
  assert.match(src, /kinds\?\.registration_types/);
  assert.match(src, /kinds\?\.filing_frequencies/);
  // A hardcoded list is a second vocabulary, and the one that decides whether
  // a composition dealer is offered a GSTR-3B.
  assert.doesNotMatch(src, /"composition"/);
  assert.doesNotMatch(src, /"input_service_distributor"/);
});

test("a registration that owes a DIFFERENT return says which", () => {
  /* Offering a composition dealer, an ISD or a s.51 deductor a GSTR-3B screen
     offers a return they must not file. The sentence is the server's. */
  const src = code(TAB);
  assert.match(src, /other_return_form/);
  assert.doesNotMatch(src, /CMP-08/, "the form name is the server's to say");
  assert.doesNotMatch(src, /GSTR-6/);
});

test("which registration owes CMP-08 is a boolean off the wire, GST-25", () => {
  /* files_cmp08 is the same shape as files_gstr1_and_3b — a screen must not
     hardcode the word "composition" to decide whether to offer the CMP-08
     panel or the s.10 category picker, or a second vocabulary of registration
     types grows here the day a third one needs its own screen. */
  const src = code(TAB);
  assert.match(src, /files_cmp08/);
  assert.doesNotMatch(src, /"composition"/);
});

test("the primary is shown and never editable here", () => {
  /* It is `clients.gstin`, written on the client record. Offering a Remove
     button on it would either fail or delete the wrong thing. */
  const src = code(TAB);
  assert.match(src, /r\.is_primary/);
  assert.match(src, /\{!r\.is_primary && \(/,
    "the row actions must be gated on the registration not being the primary");
});

test("cancelling is not deleting, and the screen says so", () => {
  /* s.29: the returns for every period the registration was live are still
     owed. A CA who reaches for Remove on a cancelled registration has to be
     told what to do instead. */
  const src = code(TAB);
  assert.match(src, /clientGstRegistrations\.close/);
  assert.match(src, /still owed/);
  assert.match(src, /recorded in error/,
    "Remove has to say what it is for, or it becomes the cancel button");
});

test("the tab is reachable from the client GST screen", () => {
  const src = code(PAGE);
  assert.match(src, /\{ id: "registrations", label: "Registrations" \}/);
  assert.match(src, /tab === "registrations" && <RegistrationsTab/);
});

test("CMP-08 is offered on the row that owes it, GST-25", () => {
  /* The panel lives on this tab, not on a return screen — a composition
     registration never files GSTR-1/3B, so its own return has to be reached
     from the row that says so, gated on the server's own boolean and on the
     registration not being cancelled (s.29 does not reopen the quarter). */
  const src = code(TAB);
  assert.match(src, /import \{ Cmp08Panel \} from "@\/components\/gst\/Cmp08Panel"/);
  assert.match(src, /r\.files_cmp08 && !r\.effective_to/);
  assert.match(src, /<Cmp08Panel clientId=\{clientId\} gstin=\{r\.gstin\} \/>/);
});

test("the api layer carries shapes and no statute", () => {
  const src = code(API);
  const start = src.indexOf("clientGstRegistrations: {");
  assert.ok(start > 0, "the namespace exists");
  const ns = src.slice(start, start + 1800);
  assert.match(ns, /\/api\/client-gst-registrations\/kinds/);
  // Close is a POST that records a date; remove is a DELETE. Collapsing the
  // two would make a cancellation look like a mistake.
  assert.match(ns, /\/close[\s\S]{0,160}method: "POST"/);
  assert.match(ns, /method: "DELETE"/);
});

test("cmp08 is its own namespace and never GSTR-1/3B's", () => {
  const src = code(API);
  const start = src.indexOf("cmp08: {");
  assert.ok(start > 0, "the cmp08 namespace exists");
  const ns = src.slice(start, start + 500);
  assert.match(ns, /\/api\/gst-workspace\/cmp08\/compute/);
});
