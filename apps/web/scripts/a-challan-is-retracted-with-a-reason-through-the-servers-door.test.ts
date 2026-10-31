// A TDS challan recorded in error is retracted through the server's door, with a written reason, by a person the server allows
// (POST-A-362).
//
// WHAT WAS MISSING
//   The challan register could list and record and nothing else, so a challan keyed under the wrong quarter, amount or date stayed
//   in the register for good: it counted toward the deposit worksheet, Form 3CD clause 34 and the quarter's statement, and could
//   close a monthly deposit again after a person reopened it. The server now has `POST /api/tds-workspace/challans/{id}/retract`
//   (tds.write, a written reason kept with the whole challan in the audit log BEFORE the row goes). The backend half is
//   `apps/api/tests/test_a_tds_challan_recorded_in_error_can_be_retracted_with_a_reason.py`.
//
// WHAT THIS HOLDS FROM THE BROWSER'S SIDE
//   * the data layer calls that route and sends the reason; a refusal the server raised as an HTTP error (a locked year, a missing
//     row) arrives as `{ detail: "<sentence>" }` with no `success` or `error`, so the shared fetch passes the sentence on as the
//     error instead of leaving every caller to show its own generic line;
//   * the Challans tab offers Retract only to a person who holds tds.write, and the browser deletes nothing itself;
//   * the prompt asks for a reason, will not send a blank one, ignores a second click while busy, shows the server's refusal and
//     holds no limit of its own on the reason;
//   * after a retraction the screen RELOADS the register and the deposit position (everything drawn from the register has
//     changed) and shows the server's sentences about what it did not change: any month still reading filed on the compliance
//     calendar, and a TDS statement for the quarter already recorded as filed;
//   * the screen says what retracting does NOT do (it does not reopen a calendar month), which is what the server does.
//
// Run with: node --experimental-strip-types --test scripts/a-challan-is-retracted-with-a-reason-through-the-servers-door.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));

const DATA = read("lib/data/tds.ts");
const PAGE = read("app/tds/page.tsx");
const MODAL = read("components/tds/RetractChallanModal.tsx");

/** The body of the function or block that starts at `marker`, up to the first line that closes it at the same indent. */
function bodyFrom(src: string, marker: string, indent: string): string {
  const at = src.indexOf(marker);
  assert.ok(at >= 0, `${marker} was not found`);
  const rest = src.slice(at);
  const end = rest.indexOf(`\n${indent}}\n`);
  return rest.slice(0, end > 0 ? end + indent.length + 3 : rest.length);
}

test("the files are where this guard thinks they are", () => {
  assert.ok(DATA.length > 10000 && PAGE.length > 40000 && MODAL.length > 1200, "a file read as nearly empty");
});

test("the data layer calls the retract door with the reason and throws the server's refusal as written", () => {
  const fn = bodyFrom(DATA, "export async function retractTdsChallan", "");
  assert.ok(/`\/api\/tds-workspace\/challans\/\$\{encodeURIComponent\(id\)\}\/retract`/.test(fn), "the retract route is not called");
  assert.ok(/method: "POST"/.test(fn) && /JSON\.stringify\(\{ reason \}\)/.test(fn), "the reason is not sent in a POST");
  assert.ok(/if \(!resp\.success\) throw new Error\(resp\.error \?\? /.test(fn), "a refusal is not thrown with the server's sentence");
});

test("a refusal raised as an HTTP error reaches the caller as its sentence", () => {
  const fetchFn = bodyFrom(DATA, "async function authedFetch<T>", "");
  assert.ok(/!\("success" in body\) && typeof body\.detail === "string"/.test(fetchFn),
    "a body with only a detail sentence is not passed on as the error");
  assert.ok(/error: body\.detail/.test(fetchFn), "the sentence is not what the error becomes");
  assert.ok(/return body;/.test(fetchFn), "a body that is an ordinary answer is not returned as it came");
});

test("the Challans tab offers Retract only to tds.write, and the browser deletes nothing itself", () => {
  assert.ok(/const canRetract = can\("tds", "write"\)/.test(PAGE), "the permission is not asked");
  assert.equal((PAGE.match(/\{canRetract && /g) ?? []).length, 2, "both the column heading and the row's button must sit behind the permission");
  assert.ok(!/from\("tds_challans"\)/.test(PAGE + DATA), "the browser reads or writes the challan table itself");
  assert.ok(!/\.delete\(\)/.test(PAGE), "the page deletes a row itself");
});

test("a retraction reloads the register and the deposit position and shows the server's sentence about the calendar", () => {
  const handler = bodyFrom(PAGE, "async function confirmRetract", "  ");
  assert.ok(handler.length > 300, "the handler could not be found");
  assert.ok(/await retractTdsChallan\(retracting\.id, reason\)/.test(handler), "the door is not called with the reason");
  assert.ok(/loadLists\(clientAtClick, false\)/.test(handler), "the register is not read again");
  assert.ok(/refreshDepositState\(clientAtClick, true\)/.test(handler), "the deposit position is not read again");
  assert.ok(/setRetractionNotes\(\[done\.calendar_note, done\.statement_note\]/.test(handler), "the server's two sentences are not kept");
  assert.ok(/setRetractError\(/.test(handler), "a refusal is not shown");
  assert.ok(/clientAtClick !== openClient\.current\) return/.test(handler), "an answer that lands after a client switch is not dropped");
  assert.ok(!/setChallans\(/.test(handler), "the handler patches the list by hand");
  assert.ok(/retractionNotes\.length > 0/.test(PAGE) && /retractionNotes\.map\(\(n, i\) => <li key=\{i\}>\{n\}<\/li>\)/.test(PAGE),
    "the server's sentences are not shown as it wrote them");
});

test("the prompt asks for a reason, sends none blank, ignores a second click while busy and holds no limit of its own", () => {
  assert.ok(/disabled=\{busy \|\| trimmed === ""\}/.test(MODAL), "the button is not disabled when busy or blank");
  // A `busy` flag lags the click by a render, so two clicks made back to back both get through it: the confirm button is the shared
  // one, which holds a synchronous guard until the promise it is handed settles, and the page hands it the request's promise.
  assert.ok(/<Button[\s\S]{0,200}onClick=\{\(\) => onConfirm\(trimmed\)\}/.test(MODAL), "the confirm button is not the shared single-click Button");
  assert.ok(!/<button[^>]*onConfirm/.test(MODAL), "a raw button confirms the retraction");
  assert.ok(/onConfirm=\{confirmRetract\}/.test(PAGE) && /async function confirmRetract\(/.test(PAGE), "the page does not hand the button the request's promise");
  assert.ok(/onConfirm\(trimmed\)/.test(MODAL), "the trimmed reason is not what is sent");
  assert.ok(!/maxLength/.test(MODAL), "the prompt holds a limit of its own: the server's refusal says it");
  assert.ok(/role="alert"/.test(MODAL), "a refusal is not announced");
  assert.ok(/audit log/.test(MODAL), "the prompt does not say the reason is kept in the audit log");
});

test("the screen says what retracting does not do", () => {
  assert.ok(/is not reopened by this/.test(MODAL), "the prompt does not say a calendar month is not reopened");
  assert.ok(/Challan retracted\. What it did not change:/.test(PAGE), "the note after a retraction does not say what was not changed");
});
