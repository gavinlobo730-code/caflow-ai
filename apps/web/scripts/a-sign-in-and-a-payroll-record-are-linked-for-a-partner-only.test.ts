/**
 * A TEAM SIGN-IN AND A RECORD IN THE FIRM'S OWN PAYROLL ARE SHOWN LINKED, TO A PARTNER ONLY (POST-A-540).
 *
 * The firm's own payroll is a Partner's alone (guardrail G4), and the Team list is a Manager's too. So the two screens that
 * show who is on that payroll must ASK for it only for a Partner, and the list of sign-ins a Manager reads must never be the
 * thing that carries it. The server refuses anybody else whatever a screen does; this holds the screens to not asking.
 *
 * What is held is the RULE each screen follows, read off its own source:
 *
 *   1. both hosts hand the hook a condition that names the Partner, and the practice's Payroll page also names the practice;
 *   2. the panel writes a link through the one call, asks before it removes one, and reads the server's answer;
 *   3. the employee form names the member only when it was opened for one, so an ordinary create sends what it always sent;
 *   4. the link is found by the server's id and never by comparing names.
 *
 * `scripts/drive/weekly/staffLinks.mjs` drives the same in a browser, a Manager's screen included.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const WEB = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const read = (rel: string) => readFileSync(resolve(WEB, rel), "utf8");
const team = read("app/team/page.tsx");
const payroll = read("app/clients/[id]/payroll/page.tsx");
const panel = read("components/payroll/StaffLinksPanel.tsx");
const form = read("components/payroll/AddEmployeeModal.tsx");
const hook = read("lib/payroll/useStaffLinks.ts");
const pairing = read("lib/payroll/staffLinks.ts");

test("each host asks for the firm's payroll only for a Partner, and the Payroll page only on the practice", () => {
  const calls = [...team.matchAll(/useStaffLinks\(([^)]*)\)/g)].map((m) => m[1]);
  assert.deepEqual(calls, ['userRole === "Partner"'], "the Team screen asks for the firm's payroll for somebody who is not a Partner");
  const onPayroll = [...payroll.matchAll(/useStaffLinks\(([^)]*)\)/g)].map((m) => m[1]);
  assert.deepEqual(onPayroll, ['openClient?.is_internal === true && userRole === "Partner"'],
    "a client's Payroll page asks for the firm's payroll, or asks for somebody who is not a Partner");
});

test("the hook asks nothing until it is told to, and never draws an unread payroll as an empty one", () => {
  assert.match(hook, /if \(!enabled\) \{ setLinks\(\{ state: "idle" \}\); return; \}/, "the hook reads before it is enabled");
  assert.ok(hook.indexOf("if (!enabled)") < hook.indexOf("api.payroll.practiceStaff()"), "the read is made before the condition is asked");
  assert.match(hook, /if \(!roster \|\| !Array\.isArray\(users\)\) \{ setLinks\(\{ state: "unread"/, "an answer that is not a roster is not said to be unread");
  assert.match(panel, /links\.state === "unread"[\s\S]{0,400}role="alert"/, "an unread payroll is not said as an alert");
});

test("the Team list's own mark is found by the link and by nothing else", () => {
  assert.match(team, /employeeOfMember\(staffRoster, member\.id\)/, "the Team row's mark is not read off the link");
  const fn = pairing.slice(pairing.indexOf("export function employeeOfMember("));
  assert.match(fn.slice(0, 300), /e\.staff_user_id === memberId/, "the mark is found by something other than the server's link");
  assert.doesNotMatch(fn.slice(0, 300), /sameName|full_name|\.name\b/, "the mark is found by comparing names");
});

test("the panel writes a link through the one call, asks before it removes one, and reads the answer", () => {
  const writes = [...panel.matchAll(/api\.(\w+)\.(\w+)\(/g)].map((m) => `${m[1]}.${m[2]}`);
  assert.deepEqual([...new Set(writes)].sort(), ["identity.createUser", "payroll.linkStaff"], "the panel calls something else on the server");
  const remove = panel.slice(panel.indexOf("async function removeLink("), panel.indexOf("const linkTo ="));
  assert.ok(remove.indexOf("confirmDialog(") >= 0 && remove.indexOf("confirmDialog(") < remove.indexOf("api.payroll.linkStaff("),
    "a link is removed before the question is answered");
  assert.match(remove, /Neither record is changed or removed/, "the question does not say that neither record is touched");
  assert.match(panel, /if \(body && body\.success === false\) \{ setNotice\(\{ tone: "problem"/, "a refusal answered as success false is not read");
  assert.match(panel, /catch \(e\) \{\s*setNotice\(\{ tone: "problem", text: failureSentence\(e, failed, "write"\) \}\);/, "a failed request is not said");
  assert.match(panel, /if \(busy\) return;/, "a second press while a link is being written is not ignored");
});

test("an invitation made from the payroll side is sent before the link, and a link that fails is said as that", () => {
  const invite = panel.slice(panel.indexOf("function InviteEmployeeModal("));
  assert.ok(invite.indexOf("api.identity.createUser(") < invite.indexOf("api.payroll.linkStaff("), "the link is written before the sign-in exists");
  assert.match(invite, /The link to the payroll record was not recorded/, "a link that failed after the invitation went is not said");
});

test("the employee form names the member only when it was opened for one", () => {
  assert.match(form, /\.\.\.\(teamMember \? \{ staff_user_id: teamMember\.id \} : \{\}\)/, "an ordinary create names the link, or a linked one does not");
  assert.match(form, /name: employee\?\.name \?\? teamMember\?\.name \?\? ""/, "the name does not start from the sign-in");
  assert.match(form, /\{teamMember && !isEdit && \(/, "the form does not say it is making a linked employee, or says so on an edit");
  const update = form.slice(form.indexOf("api.payroll.updateEmployee("), form.indexOf("api.payroll.updateEmployee(") + 120);
  assert.doesNotMatch(update, /staff_user_id/, "an edit sends the link: it has a door of its own");
});
