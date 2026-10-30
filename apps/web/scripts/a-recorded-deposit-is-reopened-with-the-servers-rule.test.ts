// Reopening a recorded filing on a statutory deposit is offered by the server's rule, asks for a reason and reloads the row
// (POST-A-267, item 3).
//
// WHAT WAS MISSING
//   A Filed obligation could only go to Completed, so a closure made from a wrong payment record or the wrong month could never
//   be taken back from any screen. The server now has `POST /api/compliance/obligations/{id}/reopen` (compliance.approve, a
//   written reason, deposits only) and `GET /api/compliance/reopenable-types`. The backend half is
//   `apps/api/tests/test_a_recorded_deposit_can_be_reopened_with_a_written_reason.py`.
//
// WHAT THIS HOLDS FROM THE BROWSER'S SIDE
//   * both screens that show a filed obligation (Deadlines and a client's Compliance tab) offer Reopen only to a person who holds
//     compliance.approve and only on the types the SERVER served; neither holds a list of obligation types of its own for it;
//   * the prompt asks for a reason, will not send a blank one and ignores a second click while it is busy;
//   * after a reopen the screen RELOADS the rows rather than patching one by hand, because how an open obligation reads (in
//     progress, overdue) is derived from its status and due date in one place;
//   * a refusal is shown as the server's sentence, and the success toast is the server's sentence (it says a payment record that
//     closed the obligation was not retracted).
//
// Run with: node --experimental-strip-types --test scripts/a-recorded-deposit-is-reopened-with-the-servers-rule.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");
const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));

const DEADLINES = read("app/deadlines/page.tsx");
const CLIENT_TAB = read("app/clients/[id]/compliance/page.tsx");
const MODAL = read("components/compliance/ReopenObligationModal.tsx");
const DATA = read("lib/data/compliance.ts");
const API = read("lib/api/index.ts");

test("the files are where this guard thinks they are", () => {
  assert.ok(DEADLINES.length > 8000 && CLIENT_TAB.length > 8000 && MODAL.length > 1500, "a file read as nearly empty");
});

test("the API client calls the reopen door and the served list, and sends the reason", () => {
  assert.ok(/`\/api\/compliance\/obligations\/\$\{id\}\/reopen`/.test(API), "the reopen route is not called");
  assert.ok(/JSON\.stringify\(\{ reason \}\)/.test(API), "the reason is not sent");
  assert.ok(/`\/api\/compliance\/reopenable-types`/.test(API), "the served list of reopenable types is not read");
});

for (const [name, src] of [["Deadlines", DEADLINES], ["the client Compliance tab", CLIENT_TAB]] as const) {
  test(`${name} offers Reopen only to compliance.approve and only on the types the server served`, () => {
    assert.ok(/can\("compliance", "approve"\)/.test(src), "the permission is not asked");
    assert.ok(/getReopenRule\(\)/.test(src), "the server's rule is not read");
    assert.ok(/filing_status === "filed" && canReopen && reopenRule\.types\.includes\(/.test(src),
      "Reopen is not gated on filed + permission + the served types");
    // The browser holds no list of its own: no line that mentions reopening, and no line of the file at all, names a deposit type
    // (the first version looked only at the 6,000 characters after the first mention, and the row render that decides sits 20,000
    // further on).
    const lines = src.split("\n");
    const near = new Set<number>();
    lines.forEach((l, i) => { if (/reopen/i.test(l)) for (let k = i - 3; k <= i + 3; k++) near.add(k); });
    const named = [...near].filter((i) => /ESI_DEPOSIT|EPF_DEPOSIT|TDS_SALARY_DEPOSIT|TDS_NON_SALARY_DEPOSIT|ADVANCE_TAX/.test(lines[i] ?? ""));
    assert.ok(near.size > 10 && named.length === 0, "the screen holds its own list of reopenable obligation types");
  });

  test(`${name} reloads the rows after a reopen instead of patching one by hand and shows the server's sentence`, () => {
    const handler = src.slice(src.indexOf("async function handleReopen"));
    const body = handler.slice(0, handler.indexOf("\n  }\n") + 5);
    assert.ok(body.length > 300, "the handler could not be found");
    assert.ok(/await (loadData|reloadCompliance)\(\)/.test(body), "the rows are not reloaded after a reopen");
    assert.ok(!/filing_status:/.test(body), "the handler patches a row's status by hand");
    assert.ok(/toast\(\{ title: "Reopened", description: message \}\)/.test(body), "the server's sentence is not shown on success");
    assert.ok(/setReopenError\(/.test(body), "a refusal is not shown");
  });
}

test("the prompt asks for a reason, sends none blank and ignores a second click while busy", () => {
  assert.ok(/disabled=\{busy \|\| trimmed === ""\}/.test(MODAL), "the button is not disabled when busy or blank");
  assert.ok(/onConfirm\(trimmed\)/.test(MODAL), "the trimmed reason is not what is sent");
  assert.ok(/maxLength=\{maxReasonChars\}/.test(MODAL), "the server's limit on the reason is not applied");
  assert.ok(/not touched by this/.test(MODAL), "the prompt does not say that a payment record is not touched");
  assert.ok(/role="alert"/.test(MODAL), "a refusal is not announced");
});

test("the rule is read three times before the screen gives up and offers nothing", () => {
  const rule = DATA.slice(DATA.indexOf("export async function getReopenRule"));
  assert.ok(/REOPEN_RULE_ATTEMPTS = 3/.test(DATA) && /for \(let attempt = 1; attempt <= REOPEN_RULE_ATTEMPTS/.test(rule),
    "a single failed read (a cold API start) hides the Reopen button for the whole visit");
});

test("the data layer reads a failed rule as 'offer nothing' and throws the server's refusal", () => {
  const rule = DATA.slice(DATA.indexOf("export async function getReopenRule"));
  assert.ok(/return \{ types: \[\], maxReasonChars: 500 \};\s*\}/.test(rule), "a failed read of the rule does not fall back to offering nothing");
  assert.ok(/if \(!res\?\.success\) throw new Error\(res\?\.error \?\? "The obligation could not be reopened\."\)/.test(DATA),
    "a refusal is not thrown with the server's sentence");
});
