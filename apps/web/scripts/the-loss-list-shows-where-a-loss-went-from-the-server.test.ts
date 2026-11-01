// The list of brought-forward losses on the Tax Computation screen says which return used how much of each, from the server (POST-A-368, item 1).
//
// WHAT WAS MISSING
//   The write-back of a filed return's use of a loss (POST-A-073) stores the use per filing and per year, and the loss list showed "remaining of
//   original" and nothing about why. The server now serves each record with `uses` and `hand_recorded_paise` (`GET /api/itr/bf-losses`,
//   `apps/api/tests/test_a_loss_list_says_which_return_used_how_much_of_each_loss.py`).
//
// WHAT THIS HOLDS FROM THE BROWSER'S SIDE
//   * the screen asks the server for them, apart from the loss list, and an answer that is not a list of records is "could not be read", worded
//     as such and NEVER as "no use";
//   * the browser adds nothing up: the component draws the server's fields, and the screen does not read the stored per-filing column or the
//     stored total itself;
//   * an answer that lands after the CA moved to another client is dropped, and a loss recorded just now refreshes the uses;
//   * a loss the answer does not mention shows nothing (an unknown is not a loss with no use).
//
// Run with: node --experimental-strip-types --test scripts/the-loss-list-shows-where-a-loss-went-from-the-server.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));

const PAGE = read("app/clients/[id]/tax/computation/page.tsx");
const COMPONENT = read("components/tax/LossUses.tsx");
const LIB = read("lib/tax/lossUses.ts");

test("the files are where this guard thinks they are", () => {
  assert.ok(PAGE.length > 50000 && COMPONENT.length > 800 && LIB.length > 800, "a file read as nearly empty");
});

test("the screen asks the server where each loss went, for the client on screen, and words a bad answer as could not be read", () => {
  assert.ok(/apiFetch\(`\/api\/itr\/bf-losses\?client_id=\$\{encodeURIComponent\(asked\)\}`\)/.test(PAGE), "the uses are not read from the server's list");
  assert.ok(/const byId = res\?\.success \? lossUsesOf\(res\.data\) : null;/.test(PAGE), "the answer is not checked before it is used");
  assert.ok(/byId \? \{ state: "ready", byId \} : \{ state: "failed", byId: \{\} \}/.test(PAGE), "a bad answer is not the failed state");
  assert.ok(/catch \{\s*if \(seq === lossUsesSeq\.current && clientShown\.current === asked\) setLossUses\(\{ state: "failed"/.test(PAGE), "a thrown read is not the failed state");
});

test("an answer that lands after a client switch is dropped, a read from an earlier render never starts, and recording a loss refreshes the uses", () => {
  assert.ok(/if \(clientShown\.current !== asked\) return;/.test(PAGE), "a read begun by a closure of an earlier render is not refused");
  assert.ok(/const seq = \+\+lossUsesSeq\.current;/.test(PAGE) && /if \(seq !== lossUsesSeq\.current \|\| clientShown\.current !== asked\) return;/.test(PAGE),
    "a late or out-of-order answer is not dropped");
  assert.ok(!/lossUsesFor/.test(PAGE), "the guard that was set at call time is back");
  assert.ok(/clientShown\.current = clientId; setLossUses\(\{ state: "loading", byId: \{\} \}\); loadLossUses\(\);/.test(PAGE),
    "the client shown is not recorded before the uses are cleared and read again for the new client");
  assert.ok(/await load\(\);\s*void loadLossUses\(\);/.test(PAGE), "a loss recorded just now does not refresh the uses");
});

test("the loss row draws the component with the server's view for that record, and the screen reads no stored arithmetic itself", () => {
  assert.ok(/<LossUses state=\{lossUses\.state\} view=\{lossUses\.byId\[l\.id\]\}/.test(PAGE), "the row does not draw the uses");
  const select = PAGE.slice(PAGE.indexOf('.from("brought_forward_losses")'), PAGE.indexOf('.order("assessment_year")'));
  assert.ok(select.length > 40, "the loss read could not be found");
  assert.ok(!/utilisations|utilized_amount_paise/.test(select), "the screen reads the stored per-filing column or total itself");
});

test("the component says each state in its own words and adds nothing up", () => {
  assert.ok(/state === "failed"[\s\S]{0,200}could not be read just now/.test(COMPONENT), "the failed state is not worded as could not be read");
  assert.ok(/if \(state === "loading"\) return null;/.test(COMPONENT), "the loading state draws something");
  assert.ok(/if \(!view\) return null;/.test(COMPONENT), "a loss the answer does not mention draws something");
  assert.ok(/The record shows no use of it\./.test(COMPONENT), "the empty record is not worded as what the record holds");
  assert.ok(!/\.reduce\(|Math\.|\* 100|\/ 100|\bsum\b/.test(COMPONENT + LIB), "the browser adds something up");
  assert.ok(/u\.filing_found === false \? " \(that return is no longer on file\)"/.test(COMPONENT), "a return that is gone is not said to be");
  assert.ok(!/filing_found !== true|!u\.filing_found/.test(COMPONENT), "an unread list of returns is worded as a return that is gone");
  assert.ok(/Recorded by hand, not linked to a filed return/.test(COMPONENT), "the hand-recorded part is not said to be unlinked to a return");
  assert.ok(!/no return behind it/.test(COMPONENT), "the hand-recorded part is said to have no return, which the record cannot know");
  assert.ok(/u\.filing_found === null \? " \(the return's details could not be read just now\)"/.test(COMPONENT), "an unread list of returns draws like a found return");
});

test("the payload check treats a non-list as null and a malformed use as an unreadable record", () => {
  assert.ok(/if \(!Array\.isArray\(data\)\) return null;/.test(LIB), "a non-list is not null");
  assert.ok(/if \(items\.some\(\(u\) => u === null\)\) continue;/.test(LIB), "a malformed use is dropped quietly");
});
