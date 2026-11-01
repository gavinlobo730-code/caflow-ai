// A TDS challan is tied to the ledger entry that paid it through the server's door, by a person the server allows (POST-A-272).
//
// WHAT WAS MISSING
//   A recorded challan pointed at nothing in the ledger. After the tax was deposited and the challan recorded, TDS Payable kept its
//   whole credit until somebody passed a bank line to it by hand, and nothing said whether a challan had an entry behind it. The server
//   now has `GET /api/tds-workspace/challans/{id}/ledger-candidates`, `POST .../link-payment` and `POST .../unlink-payment` (tds.compute
//   for the two writes, the tier of editing a register row). The backend half is `apps/api/tests/test_a_tds_challan_is_tied_to_the_ledger_entry_that_paid_it.py`.
//
// WHAT THIS HOLDS FROM THE BROWSER'S SIDE
//   * the data layer calls those routes with the right methods, throws the server's refusal as written and checks the shape of the list;
//   * the Challans tab has a Ledger column for everybody who can read, and offers the tie / take-back only to tds.compute;
//   * the browser decides nothing: it ranks nothing, computes no amount, writes no ledger row and touches no table itself;
//   * the dialog is the shared Modal, its two writing buttons are the shared single-click Button, it says it posts nothing, shows the
//     server's own sentence for each entry and never a score;
//   * after a write the screen READS the register again (it does not patch the row), and an answer that lands after a client switch or
//     after another challan was opened is dropped.
//
// Run with: node --experimental-strip-types --test scripts/a-challan-is-tied-to-the-ledger-through-the-servers-door.test.ts
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
const MODAL = read("components/tds/MatchChallanToLedgerModal.tsx");

function bodyFrom(src: string, marker: string, indent: string): string {
  const at = src.indexOf(marker);
  assert.ok(at >= 0, `${marker} was not found`);
  const rest = src.slice(at);
  const end = rest.indexOf(`\n${indent}}\n`);
  return rest.slice(0, end > 0 ? end + indent.length + 3 : rest.length);
}

test("the files are where this guard thinks they are", () => {
  assert.ok(DATA.length > 10000 && PAGE.length > 40000 && MODAL.length > 2500, "a file read as nearly empty");
});

test("the data layer calls the three doors with the right methods and throws the server's refusal as written", () => {
  const read1 = bodyFrom(DATA, "export async function fetchChallanLedgerCandidates", "");
  assert.ok(/challans\/\$\{encodeURIComponent\(id\)\}\/ledger-candidates/.test(read1), "the candidates route is not called");
  assert.ok(!/method:/.test(read1), "reading the candidates must be a GET");
  assert.ok(/objectWithLists<ChallanLedgerCandidates>\(resp\.data, "candidates"\)/.test(read1), "the list is not checked before it is mapped");
  assert.ok(/if \(!resp\.success\) throw new Error\(resp\.error \?\? /.test(read1), "a refusal is not thrown with the server's sentence");

  const link = bodyFrom(DATA, "export async function linkChallanPayment", "");
  assert.ok(/challans\/\$\{encodeURIComponent\(id\)\}\/link-payment/.test(link) && /method: "POST"/.test(link), "the link route is not a POST");
  assert.ok(/JSON\.stringify\(\{ journal_entry_id: journalEntryId \}\)/.test(link), "the entry chosen is not what is sent");
  assert.ok(/if \(!resp\.success\) throw new Error\(resp\.error \?\? /.test(link), "a refusal is not thrown with the server's sentence");

  const unlink = bodyFrom(DATA, "export async function unlinkChallanPayment", "");
  assert.ok(/challans\/\$\{encodeURIComponent\(id\)\}\/unlink-payment/.test(unlink) && /method: "POST"/.test(unlink), "the unlink route is not a POST");
  assert.ok(/if \(!resp\.success\) throw new Error\(resp\.error \?\? /.test(unlink), "a refusal is not thrown with the server's sentence");
});

test("the Challans tab shows the Ledger column to everybody and offers the tie only to tds.compute", () => {
  assert.ok(/"Minor head", "Ledger"\]/.test(PAGE), "the Ledger column heading is missing");
  assert.ok(/const canTie = can\("tds", "compute"\)/.test(PAGE), "the permission is not asked");
  assert.ok(/canTie=\{canTie\}/.test(PAGE), "the dialog is not told whether the person may tie");
  assert.ok(/canTie && \(/.test(MODAL), "the dialog offers its writing buttons without the permission");
  assert.equal((MODAL.match(/\{canTie && \(/g) ?? []).length, 2, "both the tie button and the take-back button must sit behind the permission");
});

test("the browser decides nothing about the ledger and writes nothing itself", () => {
  assert.ok(!/from\("tds_challans"\)|from\("journal_entries"\)|from\("journal_lines"\)/.test(PAGE + DATA + MODAL), "the browser reads or writes a ledger table itself");
  assert.ok(!/sort\(|score|rank/i.test(MODAL), "the dialog ranks or scores the entries itself");
  assert.ok(!/\* 100|\/ 100|Math\./.test(MODAL), "the dialog computes an amount");
  assert.ok(/\{c\.reason\}/.test(MODAL), "the server's sentence for each entry is not shown as it wrote it");
  assert.ok(/\{answer\.gap\}/.test(MODAL), "the server's sentence when it could not look is not shown");
});

test("the dialog says it posts nothing, and its two writing buttons are the shared single-click Button", () => {
  assert.ok(/It posts nothing/.test(MODAL), "the dialog does not say it posts nothing");
  assert.ok(/<Button[\s\S]{0,200}onClick=\{\(\) => onUnlink\(\)\}/.test(MODAL), "the take-back button is not the shared single-click Button");
  assert.ok(/<Button[\s\S]{0,200}onClick=\{\(\) => onLink\(c\.journal_entry_id\)\}/.test(MODAL), "the tie button is not the shared single-click Button");
  assert.ok(!/<button[^>]*(onLink|onUnlink)/.test(MODAL), "a raw button ties or unties");
  assert.ok(/async function confirmLink\(/.test(PAGE) && /async function confirmUnlink\(/.test(PAGE), "the page does not hand the buttons the request's promise");
  assert.ok(/onLink=\{confirmLink\}/.test(PAGE) && /onUnlink=\{confirmUnlink\}/.test(PAGE), "the page does not wire the two handlers");
  assert.ok(/role="alert"/.test(MODAL), "a refusal is not announced");
});

test("a write reads the register again, shows the server's refusal and drops an answer that lands after a switch", () => {
  for (const name of ["confirmLink", "confirmUnlink"]) {
    const handler = bodyFrom(PAGE, `async function ${name}`, "  ");
    assert.ok(handler.length > 300, `${name} could not be found`);
    assert.ok(/loadLists\(clientAtClick, false\)/.test(handler), `${name}: the register is not read again`);
    assert.ok(/clientAtClick !== openClient\.current\) return/.test(handler), `${name}: an answer after a client switch is not dropped`);
    assert.ok(/setMatchError\(/.test(handler), `${name}: a refusal is not shown`);
    assert.ok(!/setChallans\(/.test(handler), `${name}: the handler patches the list by hand`);
  }
  const open = bodyFrom(PAGE, "async function openMatch", "  ");
  assert.ok(/seq !== matchSeq\.current\) return/.test(open), "an answer for a challan opened earlier is not dropped");
});

test("a link to an entry that was reversed or deleted is worded by the server, in the column and in the dialog", () => {
  assert.ok(/c\.ledger_link\?\.label \?\? "Tied to an entry"/.test(PAGE), "the column does not show the server's label");
  assert.ok(/c\.ledger_link && c\.ledger_link\.state !== "live" \? "text-state-attention" : "text-state-ready"/.test(PAGE),
    "a link that is not live is drawn as a plain tie");
  assert.ok(/answer\?\.ledger_link\?\.note &&/.test(MODAL) && /\{answer\.ledger_link\.note\}/.test(MODAL), "the dialog does not show the server's note");
  assert.ok(/ledger_link: ChallanLedgerLink \| null;/.test(DATA), "the candidates answer does not carry the link");
  assert.ok(!/is_reversed|deleted_at/.test(PAGE + MODAL + DATA), "the browser decides for itself whether an entry was reversed or deleted");
});
