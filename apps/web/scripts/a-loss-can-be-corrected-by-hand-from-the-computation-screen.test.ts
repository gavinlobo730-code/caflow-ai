// A person corrects a brought-forward loss record by hand from the Tax Computation screen (POST-A-368, items 2 and 3).
//
// WHAT WAS MISSING
//   The server records each filed return's use of a loss per filing and per year (POST-A-073). A return filed before PracticeSync, or one whose
//   saved computation was never pinned, left no entry, and a wrong write-back could be corrected only by a database edit. The server now takes
//   a year's use recorded by hand and a take-back of any entry, each with a reason
//   (`apps/api/tests/test_a_years_use_of_a_loss_can_be_recorded_by_hand_and_any_entry_taken_back.py`).
//
// WHAT THIS HOLDS FROM THE BROWSER'S SIDE
//   * the controls are offered only to a person who may change loss records, and only once the uses were READ (a correction made on a list that
//     was not seen is made blind);
//   * the two calls go to the server's two routes, with the reason, through the page's own fetch (which words a refusal as the server wrote it),
//     and the screen reads the uses again afterwards instead of working out what the record now holds;
//   * the dialog asks for the reason and refuses to send without one, converts the amount with the one rupee parser, takes its years from the
//     clock, and its confirm button is the shared single-click button;
//   * a use recorded by hand is drawn as its own kind: it names no return, which is not the same as a return that is gone or unreadable;
//   * the browser decides no refusal and adds nothing up.
//
// Run with: node --experimental-strip-types --test scripts/a-loss-can-be-corrected-by-hand-from-the-computation-screen.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";
import { lossUsesOf } from "../lib/tax/lossUses.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));

const PAGE = read("app/clients/[id]/tax/computation/page.tsx");
const LIST = read("components/tax/LossUses.tsx");
const MODAL = read("components/tax/LossHandEntryModal.tsx");

test("the files are where this guard thinks they are", () => {
  assert.ok(PAGE.length > 50000 && LIST.length > 1500 && MODAL.length > 2500, "a file read as nearly empty");
});

test("the controls are offered to a person who may change loss records, once the uses were read", () => {
  assert.ok(/canEdit=\{can\("income_tax", "compute"\)\}/.test(PAGE), "the screen does not ask for the compute tier the server asks for");
  assert.ok(/if \(state === "loading"\) return null;/.test(LIST) && /state === "failed"[\s\S]{0,200}could not be read just now/.test(LIST),
    "the loading or failed state draws something");
  const failed = LIST.slice(LIST.indexOf('state === "failed"'), LIST.indexOf("if (!view) return null;"));
  assert.ok(!/onRecord|onTakeBack|record/.test(failed), "a correction is offered on a list that could not be read");
  assert.ok(/const record = canEdit && onRecord \?/.test(LIST) && /canEdit && onTakeBack/.test(LIST), "a person who may not change records is offered the controls");
});

test("the two calls go to the server's routes with the reason, and the uses are read again afterwards", () => {
  assert.ok(/`\/api\/itr\/bf-losses\/\$\{encodeURIComponent\(handEdit\.loss\.id\)\}\/year-use`/.test(PAGE), "the record call does not go to the year-use route");
  assert.ok(/\/uses\/\$\{encodeURIComponent\(handEdit\.take\.entry_id\)\}\/take-back`/.test(PAGE), "the take-back call does not go to the take-back route");
  assert.ok(/\{ financial_year: financialYear, amount_paise: amountPaise, reason \}/.test(PAGE), "the record call does not send the year, the paise and the reason");
  assert.ok(/\{ reason \}\)/.test(PAGE), "the take-back call does not send the reason");
  const send = PAGE.slice(PAGE.indexOf("async function sendHandEdit"), PAGE.indexOf("const recordYearUse"));
  assert.ok(/apiFetch\(path, \{ method: "POST", body: JSON\.stringify\(body\) \}\)/.test(send), "the call is not made through the page's own fetch");
  assert.ok(/setHandError\(res\?\.detail \?\? res\?\.error \?\? /.test(send), "a refusal is not shown as the server wrote it");
  assert.ok(/await load\(\);\s*void loadLossUses\(\);/.test(send), "the uses are not read again after a write");
  assert.ok(!/utilisations|utilized_amount_paise|remaining_amount_paise/.test(send), "the screen works out what the record now holds");
});

test("the dialog needs a reason, converts the amount with the one parser, takes its years from the clock and uses the shared single-click button", () => {
  assert.ok(/import \{ paiseFromRupeeInput \} from "@\/lib\/money\/rupeeInput";/.test(MODAL) && /paiseFromRupeeInput\(amount\)/.test(MODAL), "the amount is not read by the one parser");
  assert.ok(!/parseFloat|Number\(|\* 100|Math\.round/.test(MODAL), "the amount is converted by hand");
  assert.ok(/<YearPicker kind="fy"/.test(MODAL) && !/"20\d\d-\d\d"/.test(MODAL), "the years are not the clock's");
  assert.ok(/const ready = recording\s*\? year !== "" && paise !== null && paise > 0 && why !== ""\s*: why !== "";/.test(MODAL), "the dialog can send without a reason");
  assert.ok(/<Button\s+type="button"\s+variant="plain"\s+size="none"\s+onClick=\{\(\) => \(recording \? onRecord\(year, paise \?\? 0, why\) : onTakeBack\(why\)\)\}/.test(MODAL),
    "the confirm button is not the shared single-click button returning the request's promise");
  assert.ok(/disabled=\{busy \|\| !ready\}/.test(MODAL), "the button can be pressed while busy or not ready");
  assert.ok(!/<button[^>]*onClick=\{\(\) => \(recording/.test(MODAL), "a raw button sends the request");
});

test("the dialog says before the click that a return's entry comes back when that return's records are written again", () => {
  assert.ok(/mode\.byAReturn[\s\S]{0,260}comes back the next time that return's loss records are written/.test(MODAL), "a take-back of a return's entry does not say it comes back");
  assert.ok(/byAReturn: handEdit\.take\.return_type !== "manual"/.test(PAGE), "a hand entry is told it comes back, or a return's entry is not");
});

test("a use recorded by hand is its own kind and names no return", () => {
  assert.ok(/u\.return_type === "manual"\) return `FY \$\{u\.financial_year\}, recorded by hand: /.test(LIST), "a hand entry is not drawn as recorded by hand");
  const made = lossUsesOf([{
    id: "L1", hand_recorded_paise: 0,
    uses: [
      { entry_id: "manual:2024-25", filing_id: "manual:2024-25", financial_year: "2024-25", return_type: "manual", amount_paise: 300, filing_found: null, acknowledgement_number: null },
      { entry_id: "F-1", filing_id: "F-1", financial_year: "2023-24", return_type: "revised", amount_paise: 100, filing_found: true, acknowledgement_number: "A1" },
      { filing_id: "F-2", financial_year: "2022-23", return_type: "original", amount_paise: 50, filing_found: false, acknowledgement_number: null },
    ],
  }]);
  assert.ok(made, "the payload was not read");
  const [hand, revised, older] = made!.L1.uses;
  assert.deepEqual([hand.return_type, hand.entry_id, hand.filing_found, hand.acknowledgement_number], ["manual", "manual:2024-25", null, null]);
  assert.deepEqual([revised.return_type, revised.entry_id], ["revised", "F-1"]);
  assert.equal(older.entry_id, "F-2", "an older server's answer has no entry id: it is the filing's id");
  assert.equal(older.return_type, "original");
});

test("the page shows the dialog for a record or a take-back and closes it only when nothing is being sent", () => {
  assert.ok(/<LossHandEntryModal[\s\S]{0,900}onRecord=\{recordYearUse\}[\s\S]{0,60}onTakeBack=\{takeBackUse\}/.test(PAGE), "the dialog is not wired to both calls");
  assert.ok(/onClose=\{\(\) => \{ if \(!handBusy\) \{ setHandEdit\(null\); setHandError\(null\); \} \}\}/.test(PAGE), "the dialog can be closed while a request is out");
});
