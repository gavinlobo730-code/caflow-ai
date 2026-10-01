// GST-17 — choosing which of a client's registrations a return is for.
//
// Run with:
//   node --experimental-strip-types --test lib/gst/registrationChoice.test.ts
//
// The finding's own verify line: "a UI test with a two-registration client
// shows the picker, and the compute request payload carries the selected
// gstin". The picker's RENDERING is held by the source guard beside this; what
// can be asserted behaviourally, without a DOM, is the part that decides
// something — whether there is a choice to make, what the request carries, and
// what is refused.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  caveatFor, defaultGstin, fileable, needsPicker, optionLabel,
  resolveChoice, withRegistration, type RegistrationOption,
} from "./registrationChoice.ts";

const PRIMARY = "27AAAAA0000A1Z2";
const SECOND = "29AAAAA0000A1ZY";

const primary: RegistrationOption = {
  gstin: PRIMARY, label: `${PRIMARY} (Maharashtra)`, is_primary: true,
  files_gstr1_and_3b: true, other_return_form: null,
  documents_not_split_caveat: `This client holds 2 registrations ... for ${PRIMARY}`,
};
const second: RegistrationOption = {
  gstin: SECOND, label: `${SECOND} (Karnataka)`, is_primary: false,
  files_gstr1_and_3b: true, other_return_form: null,
  documents_not_split_caveat: `This client holds 2 registrations ... for ${SECOND}`,
};
const composition: RegistrationOption = {
  gstin: "33AAAAA0000A1ZX", label: "33AAAAA0000A1ZX (Tamil Nadu)", is_primary: false,
  files_gstr1_and_3b: false,
  other_return_form: "A composition dealer files CMP-08 and GSTR-4, not GSTR-1 and GSTR-3B.",
  documents_not_split_caveat: null,
};

test("a client with two ordinary registrations has a choice to make", () => {
  assert.equal(needsPicker([primary, second]), true);
});

test("a client with one registration has none", () => {
  assert.equal(needsPicker([primary]), false);
  assert.equal(needsPicker([]), false);
});

test("a registration that files a different return is not a choice", () => {
  // The composition dealer is listed but is not one of the TWO the picker
  // offers: one registration files GSTR-1 and GSTR-3B.
  assert.equal(needsPicker([primary, composition]), false);
  assert.deepEqual(fileable([primary, composition]).map((r) => r.gstin), [PRIMARY]);
});

test("the screen opens on the first registration, which is the primary", () => {
  assert.equal(defaultGstin([primary, second]), PRIMARY);
  // Even where the primary is not the first filer, the SERVER's order is kept
  // and the first that files the ordinary pair is the default.
  assert.equal(defaultGstin([composition, second]), SECOND);
  assert.equal(defaultGstin([composition]), null);
});

test("THE compute request carries the selected GSTIN", () => {
  const choice = resolveChoice([primary, second], SECOND);
  assert.equal(choice.refused, undefined);
  assert.equal(choice.gstin, SECOND);

  const body = withRegistration(
    { client_id: "CLI", period: "062025", include_amendments: false }, choice);
  assert.deepEqual(body, {
    client_id: "CLI", period: "062025", include_amendments: false, gstin: SECOND,
  });
});

test("the primary is sent when the primary is chosen — not left to a default", () => {
  const body = withRegistration({ client_id: "CLI", period: "062025" },
                                resolveChoice([primary, second], PRIMARY));
  assert.equal((body as { gstin?: string }).gstin, PRIMARY);
});

test("nothing is sent where there is nothing chosen, and never an empty string", () => {
  const body = withRegistration({ client_id: "CLI", period: "062025" }, {});
  assert.equal("gstin" in body, false,
    "an empty `gstin` is a different request from an absent one");
  // An empty list (not read, or no GSTIN recorded) sends nothing: the server
  // answers with the primary or refuses in words.
  assert.deepEqual(resolveChoice([], null), {});
});

test("a GSTIN the client does not hold is REFUSED and never defaulted to the primary", () => {
  const choice = resolveChoice([primary, second], "07AAAAA0000A1Z5");
  assert.equal(choice.gstin, undefined,
    "defaulting to the primary would build one registration's return under another's number");
  assert.match(choice.refused ?? "", /not a registration this client holds/);
});

test("the comparison is case-blind and whitespace-blind, as the server's is", () => {
  assert.equal(resolveChoice([primary, second], ` ${SECOND.toLowerCase()} `).gstin, SECOND);
});

test("a registration that files a different return is refused with the server's sentence", () => {
  const choice = resolveChoice([primary, composition], composition.gstin);
  assert.equal(choice.gstin, undefined);
  assert.ok(choice.refused?.includes(composition.other_return_form as string),
    "the sentence naming what it files instead is the server's, not ours");
});

test("with no selection the first registration that files the ordinary pair is used", () => {
  assert.equal(resolveChoice([composition, second], null).gstin, SECOND);
  assert.match(resolveChoice([composition], null).refused ?? "", /None of this client's registrations/);
});

test("the caveat shown is the server's, for the registration chosen", () => {
  assert.equal(caveatFor([primary, second], SECOND), second.documents_not_split_caveat);
  assert.equal(caveatFor([primary, second], PRIMARY), primary.documents_not_split_caveat);
  // null is the truth for a client with one registration — not "unknown".
  assert.equal(caveatFor([{ ...primary, documents_not_split_caveat: null }], PRIMARY), null);
  assert.equal(caveatFor([primary], null), null);
});

test("an option says what it is", () => {
  assert.match(optionLabel(primary), /primary/);
  assert.doesNotMatch(optionLabel(second), /primary/);
  assert.match(optionLabel({ ...second, effective_to: "2026-03-31" }), /closed 2026-03-31/);
  assert.match(optionLabel(composition), /files a different return/);
});
