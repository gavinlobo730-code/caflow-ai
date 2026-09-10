// The gap sentences the backend actually sends, fed through the renderer.
//
// Run with:
//   node --experimental-strip-types --test lib/purchases/registerNotes.test.ts
//
// WHY THIS EXISTS
//     scripts/tds-register-gaps-reach-the-screen.test.ts scans SOURCE: it
//     proves the response is read and rendered. It cannot see the shape of what
//     is in it, and the shape was wrong — `gap_details` was typed `string[]`
//     while domain/tds/residency.describe_gaps has always returned
//     `[{code, message}]`. TypeScript believed the declaration, so the objects
//     reached `{n.text}` and React throws on a plain object child. Every gap the
//     register reported took the purchases page down.
//
//     The payloads below are copied from describe_gaps' own return expression,
//     not invented, so this fails if either side changes shape again.
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  registerNotesFrom, paymentNotesFrom, dedupeRegisterNotes,
} from "./registerNotes.ts";

// domain/tds/residency.describe_gaps: [{"code": c, "message": GAP_MESSAGES...}]
const REAL_GAP_DETAILS = [
  { code: "vendor_residency_not_classified",
    message: "Nobody has recorded whether this vendor is a resident." },
  { code: "form_15ca_not_recorded",
    message: "No Form 15CA acknowledgement is recorded against this remittance." },
];

test("a bill's gap details render as sentences, not as objects", () => {
  const notes = registerNotesFrom({
    id: "b1",
    tds_register: {
      synced: true, vendor_name: "Acme GmbH",
      statutory_gaps: REAL_GAP_DETAILS.map((g) => g.code),
      gap_details: REAL_GAP_DETAILS,
    },
  });
  assert.equal(notes.length, 2);
  for (const n of notes) {
    assert.equal(typeof n.text, "string",
      "an object here is what React refuses to render");
    assert.ok(n.text.length > 0);
    assert.equal(n.vendor, "Acme GmbH");
  }
  assert.match(notes[0].text, /whether this vendor is a resident/);
});

test("an advance's gaps come off the top level of the payment", () => {
  // services/tds_register_service.sync_for_payment reports the same vocabulary,
  // but a payment has no second document to nest it under.
  const notes = paymentNotesFrom({
    id: "p1", tds_paise: 1000000, vendor_name: "Bharat Constructions",
    statutory_gaps: ["vendor_residency_not_classified"],
    gap_details: [REAL_GAP_DETAILS[0]],
  });
  assert.equal(notes.length, 1);
  assert.equal(notes[0].text, REAL_GAP_DETAILS[0].message);
  assert.equal(notes[0].vendor, "Bharat Constructions");
});

test("a payment with nothing to report renders nothing", () => {
  assert.deepEqual(paymentNotesFrom({ id: "p1", tds_paise: 0 }), []);
  assert.deepEqual(paymentNotesFrom(null), []);
  assert.deepEqual(paymentNotesFrom("not an object"), []);
});

test("a code with no wording still reaches the screen", () => {
  // describe_gaps keeps an unknown code with an empty message rather than
  // dropping it. An empty note reads as no gap, so the code stands in.
  const notes = paymentNotesFrom({
    statutory_gaps: ["something_new"],
    gap_details: [{ code: "something_new", message: "" }],
  });
  assert.deepEqual(notes.map((n) => n.text), ["something_new"]);
});

test("a failed sync is louder than any gap", () => {
  const notes = registerNotesFrom({
    tds_register: { synced: false, reason: "connection reset", vendor_name: "X",
                    gap_details: REAL_GAP_DETAILS },
  });
  assert.equal(notes.length, 1);
  assert.match(notes[0].text, /26Q will be short/);
});

test("one sentence per vendor per gap", () => {
  const one = { vendor: "X", text: "same" };
  assert.deepEqual(dedupeRegisterNotes([one, { ...one }, { vendor: "Y", text: "same" }]),
                   [one, { vendor: "Y", text: "same" }]);
});
