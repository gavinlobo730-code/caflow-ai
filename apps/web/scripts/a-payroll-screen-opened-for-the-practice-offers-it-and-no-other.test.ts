// POST-A-534. The firm's own practice is in no list of the firm's clients, so the firm-level Statutory, Declarations and
// Reports payroll screens, whose pickers are those lists, could not be opened for it. Each takes `?client=` now. The rule of
// what that address may choose is one function, held here; the three screens and the practice's Payroll page are held to it.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { MY_PRACTICE, openedForChoice, openedForHref } from "../lib/payroll/openedFor.ts";

const ROOT = join(import.meta.dirname, "..");
const read = (p: string) => readFileSync(join(ROOT, p), "utf8");
const CLIENTS = [{ id: "c-1", client_name: "Acme Traders" }, { id: "c-2", client_name: "Bharat Mills" }];

test("opened from the menu, the picker is the firm's clients and nothing is chosen", () => {
  const got = openedForChoice(CLIENTS, "", "p-1");
  assert.deepEqual(got, { clients: CLIENTS, choose: null, isPractice: false });
  assert.equal(got.clients.some((c) => c.id === "p-1"), false, "the practice is offered to somebody who did not open the screen for it");
});

test("opened for one of the firm's clients, that client is chosen and the list is unchanged", () => {
  const got = openedForChoice(CLIENTS, "c-2", "p-1");
  assert.equal(got.choose, "c-2");
  assert.equal(got.isPractice, false);
  assert.deepEqual(got.clients, CLIENTS);
});

test("opened for the practice, it is offered first under its own name and chosen", () => {
  const got = openedForChoice(CLIENTS, "p-1", "p-1");
  assert.equal(got.choose, "p-1");
  assert.equal(got.isPractice, true);
  assert.deepEqual(got.clients[0], { id: "p-1", client_name: MY_PRACTICE });
  assert.deepEqual(got.clients.slice(1), CLIENTS);
  assert.equal(MY_PRACTICE, "My practice");
});

test("an id that is neither a listed client nor the practice the server named is ignored, never named My practice", () => {
  // The practice's id is the server's answer. With no answer (not a Partner, a failed read, no practice set up) an id that
  // is missing from the list is NOT the practice: a client list that failed to load would otherwise rename a real client.
  for (const practiceId of [null, "p-1"]) {
    const got = openedForChoice(CLIENTS, "c-unknown", practiceId);
    assert.deepEqual(got, { clients: CLIENTS, choose: null, isPractice: false });
  }
  assert.deepEqual(openedForChoice([], "p-1", null), { clients: [], choose: null, isPractice: false });
});

test("the address is the screen's own with the client in the query, encoded", () => {
  assert.equal(openedForHref("/payroll/reports/", "p-1"), "/payroll/reports/?client=p-1");
  assert.equal(openedForHref("/payroll/statutory/", "a b&c"), "/payroll/statutory/?client=a%20b%26c");
});

test("the three screens take their choice from the one rule, and none asks the practice of anybody but a Partner", () => {
  for (const page of ["app/payroll/statutory/page.tsx", "app/payroll/declarations/page.tsx", "app/payroll/reports/page.tsx"]) {
    const src = read(page);
    assert.match(src, /useOpenedFor\(\)/, `${page} does not read the client it was opened for`);
    assert.match(src, /openedForChoice\(/, `${page} decides for itself what the address may choose`);
    // The firm's own client list still leaves the practice out: it reaches the picker through the rule alone.
    assert.match(src, /\.eq\("is_internal", false\)/, `${page} no longer leaves the practice out of the firm's clients`);
  }
  const hook = read("lib/payroll/useOpenedFor.ts");
  assert.match(hook, /usePracticeClient\(asks\)/);
  assert.match(hook, /const asks = openedFor !== "" && userRole === "Partner"/, "the practice is asked for with nothing named, or of a non-Partner");
});

test("Reports reads one client's rows when it was opened for one, and waits for the practice's answer before its first read", () => {
  const src = read("app/payroll/reports/page.tsx");
  assert.match(src, /api\.payroll\.listEmployees\(only, true\)/);
  assert.match(src, /api\.payroll\.listRuns\(only\)/);
  assert.match(src, /yearEndSummary\(\{ financial_year: selectedFy, \.\.\.\(clientId \? \{ client_id: clientId \} : \{\}\) \}\)/);
  assert.match(src, /useEffect\(\(\) => \{ if \(settled\) load\(\); \}, \[load, settled\]\)/, "the first read does not wait for the practice's answer");
  assert.match(src, /data-reports-for=/, "a narrowed Reports screen does not say it is narrowed");
});

test("the practice's own Payroll page links the four firm-level screens, and only the practice's page does", () => {
  const src = read("app/clients/[id]/payroll/page.tsx");
  const block = src.slice(src.indexOf("data-own-payroll-screens") - 200, src.indexOf("data-own-payroll-screens") + 1200);
  assert.match(block, /openClient\?\.is_internal === true && \(/, "the links are shown on a client's page too");
  for (const path of ["/payroll/attendance/", "/payroll/statutory/", "/payroll/declarations/", "/payroll/reports/"]) {
    assert.ok(block.includes(`openedForHref("${path}", clientId)`), `no link to ${path} for the practice`);
  }
});
