// A person's bulk pass of bank lines states the GST of the lines they coded. Run with:
//   node --experimental-strip-types --test scripts/a-bulk-pass-states-the-gst-of-the-lines-the-ca-coded.test.ts
//
// WHAT WAS WRONG (POST-A-489; a tester's report of 18-11-2026)
//   "When allocating 4 or 5 transactions together, the system does not ask for the GST percentage, unlike a single one."
//   The single line's screen shows a GST control for a line that can carry GST and sends the answer with the pass. "Book
//   under…" and every bulk pass sent nothing, so a line the CA coded to an expense ledger was posted with the WHOLE debit on
//   the expense and the input credit (CGST Act s.16) lost without a word.
//
// THE RULE, as the source states it: every bulk pass of a person's lines goes through `passLoop`, which sends the chunk's
// GST answer and the lines it left (`exclude_ids`); a pass that left lines opens the question once; the row-level Pass of
// a line that can carry GST opens that line's own screen. The server half is tests/test_bank_entry_service.py.
// What it cannot see is a pass made through some other door; the server skips such a line in a person's bulk pass.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const WEB = join(import.meta.dirname, "..");
const read = (rel: string) => readFileSync(join(WEB, rel), "utf8");

test("the api client can send the answer and no longer carries a list of lines to leave", () => {
  const s = read("lib/api/index.ts");
  const at = s.indexOf("passReady: (data:");
  assert.ok(at > 0);
  const sig = s.slice(at, at + 1100);
  assert.match(sig, /gst_rate_bps\?: number; is_interstate\?: boolean \}\) =>/);
  assert.doesNotMatch(sig, /exclude_ids/, "the lines a pass leaves are held on their rows, not sent back and forth in an address");
});

test("passLoop sends the answer and takes the held lines from the pass's last chunk", () => {
  const s = read("components/banking/EntriesTab.tsx");
  assert.match(s, /gst_rate_bps: opts\.gst\?\.rate, is_interstate: opts\.gst\?\.interstate/);
  assert.match(s, /if \(r\.data\.gst_unanswered\) unanswered = r\.data\.gst_unanswered;/);
  assert.match(s, /return \{ passed, failed, skipped, withGst, unanswered \}/);
});

test("every bulk pass reports through one function that opens the question, and none posts around it", () => {
  const s = read("components/banking/EntriesTab.tsx");
  assert.match(s, /function reportPass\(/);
  assert.match(s, /if \(n\.unanswered\.length\) \{ setGstChoices\(\{\}\); setGstAsk\(n\.unanswered\); \}/);
  assert.equal((s.match(/reportPass\(/g) ?? []).length, 4, "its definition, Pass selected, Pass all ready and the answered pass");
  // the trusted-rule sweep is not a person's pass and is never asked
  assert.match(s, /passLoop\(\{ only_trusted: true,/);
});

test("the answer is asked once per KIND of line, never one for all, with no preselected choice, and 'no GST' is a choice", () => {
  const s = read("components/banking/EntriesTab.tsx");
  assert.match(s, /const heldKey = \(l: HeldLine\) => `\$\{l\.category \?\? "Other"\}\|\$\{l\.money_in \? "in" : "out"\}`/);
  assert.match(s, /groups\.map\(\(g\) => \{/);
  assert.match(s, /<option value="">Choose…<\/option>/);
  assert.match(s, /disabled=\{!anyAnswered \|\| progress !== null\}/);
  assert.match(s, /A kind you leave alone stays held/);
  // each kind is passed with its OWN answer, in requests of a bounded number of ids
  assert.match(s, /gst: \{ rate, interstate: rate > 0 && gstChoices\[k\]\.interstate \}/);
  assert.match(s, /const IDS_PER_REQUEST = 100;/);
  const shared = read("components/banking/shared.ts");
  assert.match(shared, /\{ value: 0, label: "0% — no GST" \}/);
});

test("the Pass button on a row of a line that can carry GST opens that line's own screen, where the control is", () => {
  const s = read("components/banking/EntriesTab.tsx");
  assert.match(s, /async function passOne\(t: Entry\) \{[\s\S]{0,400}if \(t\.gst_allowed\) \{ setDetailId\(t\.id\); return; \}/);
});
