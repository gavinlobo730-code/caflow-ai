// What the TDS register could not establish must reach a CA. Run with:
//   node --experimental-strip-types --test scripts/tds-register-gaps-reach-the-screen.test.ts
//
// WHY THIS EXISTS
//     Receiving a purchase bill writes its deduction into tds_deductions, and
//     services/tds_register_service.py names what it could not settle — an
//     unclassified residency, missing 27Q identifiers (country, TIN), an
//     unverified §195 rate, an undated no-PE declaration, a Form 15CA not
//     recorded, and a deduction that is a catch-up on the year's aggregate.
//
//     Every one of those has been computed on every foreign-supplier bill since
//     the register was written. routers/purchase_bills.py returns them —
//     `{...bill, tds_register: {...}}` — and this page read `result.success`
//     and nothing else. Five gap codes, computed and thrown away, on every
//     bill (PUR-14).
//
//     It is the same failure payroll had, and scripts/payroll-gaps-reach-the-
//     screen.test.ts is the same test for the same reason: the whole
//     refuse-rather-than-guess discipline in apps/api is worth nothing if the
//     refusal is silent by the time it reaches a CA.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.join(import.meta.dirname, "..");
const PAGE = path.join(WEB, "app/clients/[id]/purchases/page.tsx");
const NOTES = path.join(WEB, "lib/purchases/registerNotes.ts");

/** With comments blanked, because the note left where the discarded response
 *  used to be describes what it discarded. */
function code(file: string): string {
  return fs.readFileSync(file, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

test("the receive response is read, not discarded", () => {
  const s = code(PAGE);
  assert.match(s, /setRegisterNotes\(registerNotesFrom\(result\.data\)\)/,
    "the single-bill receive must capture what the register reported");
  assert.match(s, /notes: registerNotesFrom\(result\.data\)/,
    "and so must the bulk receive — a batch is where an unclassified supplier " +
    "is most likely to appear, twenty bills at a time");
});

test("the notes are rendered, every sentence and not a count", () => {
  const s = code(PAGE);
  assert.match(s, /registerNotes\.length > 0 &&/,
    "the block must be conditional on there being something to say");
  assert.match(s, /registerNotes\.map\(/,
    "every sentence must be shown — a count tells a CA nothing to act on");
  assert.match(s, /could not establish/,
    "and framed as what the register could not establish");
});

test("a received bill is not presented as a failure", () => {
  // The bill received, the journal POSTED and the register row was written.
  // Styling this as an error would tell a CA the posting failed, and the next
  // thing they would do is try to receive it again.
  const s = code(PAGE);
  assert.match(s, /Nothing is blocked/,
    "the CA must be told the bill and its journal are posted");
  assert.doesNotMatch(s, /registerNotes[\s\S]{0,400}?bg-red-50/,
    "amber, not red — this is a gap, not a rejection");
});

test("the sentences are the server's, not the browser's", () => {
  // CLAUDE.md: zero business logic in the frontend. Deciding what counts as a
  // gap — and how to word it — is a statutory judgement that lives in apps/api
  // beside the rules it is judging against. domain/tds/gaps.py::describe_gaps
  // is the one place they are worded, so two screens cannot describe one gap
  // two ways.
  const s = code(PAGE) + code(NOTES);
  assert.doesNotMatch(s, /residential status is not classified/i,
    "the sentence belongs to describe_gaps()");
  assert.doesNotMatch(s, /Form 15CA has not been recorded/i,
    "the browser must not restate the rule it is reporting");
});

test("the gap the register raises can actually be answered", () => {
  // TDS-25, and the reason it belongs in THIS file. Making the gaps reach the
  // CA (PUR-14) made the product tell them, on every foreign remittance, to
  // record a Form 15CA acknowledgement — and `grep -i 15ca` across apps/web
  // then found no input and no display anywhere. A refusal a user cannot act
  // on is worse than a silent one: it is a dead end with the CA's name on it.
  //
  // The panel is on the BILL, because 15CA is per remittance under Rule 37BB —
  // a vendor paid four times in a year needs four of them.
  const editor = fs.readFileSync(
    path.join(WEB, "components/purchases/PurchaseBillEditor.tsx"), "utf8");
  for (const field of ["form_15ca_ack_no", "form_15ca_filed_on", "form_15cb_udin"]) {
    assert.ok(editor.includes(field),
      `${field} is not sent by the bill editor — the register asks for it on ` +
      "every §195 bill and nothing can supply it");
  }
  // Shown on the SERVER's answer about the section, not on a browser reading
  // of the vendor's residency: the same preview that computes the tax decides
  // it, so the panel and the deduction cannot disagree about who the payee is.
  assert.match(editor, /tds\.data\?\.tds_section === "195"/,
    "the panel must key on the server's resolved section");
  // And the panel is INPUTS ONLY. 15CA is filed on incometax.gov.in under the
  // remitter's own login; a control here that appeared to do it would be the
  // credential-capture surface scripts/no-screen-takes-a-portal-credential
  // exists to forbid, whatever it was labelled. Checked as "no button in the
  // panel" rather than by forbidding a WORD — the panel's own copy has to say
  // "file on incometax.gov.in", which is the instruction, not an offer.
  const panelStart = editor.indexOf("Foreign remittance — Form 15CA");
  assert.ok(panelStart > 0, "the panel is gone");
  const panel = editor.slice(panelStart, editor.indexOf("</section>", panelStart));
  assert.doesNotMatch(panel, /<button|onClick=/,
    "the Rule 37BB panel takes values and does nothing with them. A control " +
    "here that appeared to file the 15CA would be a portal-submission " +
    "surface whatever it was labelled.");
});

test("a failed register sync is the loudest case, not a silent one", () => {
  // _sync_tds_register deliberately never raises: a bill that received and
  // posted its journal correctly must not be rolled back because its register
  // row could not be written. That is exactly why the frontend has to say so —
  // otherwise a bill is in the books and missing from 26Q with nothing
  // anywhere to show for it.
  const s = code(NOTES);
  assert.match(s, /synced === false/,
    "the synced:false result must produce a note of its own");
  assert.match(s, /26Q will be short/,
    "and say what the consequence is, not just that something failed");
});

test("one sentence per vendor per gap, however many bills raised it", () => {
  const s = code(NOTES);
  assert.match(s, /export function dedupeRegisterNotes/,
    "a bulk receive of twenty bills to one unclassified supplier raises the " +
    "same gap twenty times, and twenty copies of one sentence is how a real " +
    "warning gets scrolled past");
});
