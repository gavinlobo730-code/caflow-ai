// What a half-typed journal entry keeps (frontend_ux-23). Run with:
//   node --experimental-strip-types --test lib/journal/journalDraft.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  MAX_DRAFT_LINES, applyJournalDraft, validateJournalDraft, type JournalDraftFields,
} from "./journalDraft.ts";

const GOOD: JournalDraftFields = {
  entryDate: "2026-09-30",
  entryType: "Journal",
  referenceNo: "JNL-014",
  narration: "Being rent for September",
  lines: [
    { account_id: "acc-rent", debit: "25,000.00", credit: "", narration: "" },
    { account_id: "acc-bank", debit: "", credit: "25000", narration: "NEFT" },
  ],
  attachments: [{ name: "Rent receipt", url: "https://example.com/r.pdf" }],
};

test("a well-formed draft is rebuilt field for field", () => {
  assert.deepEqual(validateJournalDraft(JSON.parse(JSON.stringify(GOOD))), GOOD);
});

test("amounts stay the TYPED STRING — a half-typed '12.' is kept as typed", () => {
  const draft = { ...GOOD, lines: [{ account_id: "a", debit: "12.", credit: "", narration: "" }, GOOD.lines[1]] };
  assert.equal(validateJournalDraft(draft)?.lines[0].debit, "12.");
});

test("nothing derived is kept: extra keys — totals, a balance verdict, names — are not carried back", () => {
  const dirty = {
    ...GOOD, totalDebit: 2_500_000, isBalanced: true,
    lines: GOOD.lines.map((l) => ({ ...l, account_name: "Rent", debit_paise: 2_500_000 })),
  };
  const back = validateJournalDraft(dirty) as JournalDraftFields;
  assert.deepEqual(Object.keys(back).sort(), ["attachments", "entryDate", "entryType", "lines", "narration", "referenceNo"]);
  assert.deepEqual(Object.keys(back.lines[0]).sort(), ["account_id", "credit", "debit", "narration"],
    "the server recomputes everything from what is sent; a draft that carried a figure would be a figure to trust");
});

test("a draft with a wrong type anywhere is dropped whole", () => {
  assert.equal(validateJournalDraft(null), null);
  assert.equal(validateJournalDraft("x"), null);
  assert.equal(validateJournalDraft({ ...GOOD, narration: 7 }), null);
  assert.equal(validateJournalDraft({ ...GOOD, lines: "none" }), null);
  assert.equal(validateJournalDraft({ ...GOOD, attachments: undefined }), null);
});

test("ONE bad line discards the draft rather than quietly dropping a leg of the voucher", () => {
  // Restoring an entry with the balancing leg missing could still read
  // "balanced" if the missing leg were the one being checked, and the CA might
  // post it without noticing.
  const bad = { ...GOOD, lines: [GOOD.lines[0], { account_id: "acc-bank", debit: 5, credit: "", narration: "" }] };
  assert.equal(validateJournalDraft(bad), null);
  assert.equal(validateJournalDraft({ ...GOOD, lines: [GOOD.lines[0], null] }), null);
});

test("a voucher beyond any plausible hand-typed size is refused", () => {
  const many = Array.from({ length: MAX_DRAFT_LINES + 1 }, () => GOOD.lines[0]);
  assert.equal(validateJournalDraft({ ...GOOD, lines: many }), null);
  assert.notEqual(validateJournalDraft({ ...GOOD, lines: many.slice(0, MAX_DRAFT_LINES) }), null);
});

test("an attachment without a name or link is not half-restored", () => {
  assert.equal(validateJournalDraft({ ...GOOD, attachments: [{ name: "x" }] }), null);
});

test("a restore clears an account the chart no longer holds, and counts it", () => {
  const { fields, accountsDropped } = applyJournalDraft(GOOD, new Set(["acc-bank"]), ["Journal", "Sales"]);
  assert.equal(fields.lines[0].account_id, "", "the id is not left selected where the picker shows blank");
  assert.equal(fields.lines[0].debit, "25,000.00", "the amount stays, so the CA re-picks the account and carries on");
  assert.equal(fields.lines[1].account_id, "acc-bank");
  assert.equal(accountsDropped, 1);
});

test("a restore keeps every account the chart still holds", () => {
  const { fields, accountsDropped } = applyJournalDraft(GOOD, new Set(["acc-rent", "acc-bank"]), ["Journal"]);
  assert.deepEqual(fields.lines, GOOD.lines);
  assert.equal(accountsDropped, 0);
});

test("a blank account on a line is not 'dropped'", () => {
  const draft = { ...GOOD, lines: [{ account_id: "", debit: "1", credit: "", narration: "" }, GOOD.lines[1]] };
  assert.equal(applyJournalDraft(draft, new Set(["acc-bank"]), ["Journal"]).accountsDropped, 0);
});

test("an entry type the editor does not offer falls back to the first it does", () => {
  const { fields } = applyJournalDraft({ ...GOOD, entryType: "Imaginary" }, new Set(["acc-rent", "acc-bank"]),
    ["Journal", "Sales"]);
  assert.equal(fields.entryType, "Journal");
});
