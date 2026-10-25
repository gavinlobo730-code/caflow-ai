// The employee portal tells a person why in words. Run with:
//   node --experimental-strip-types --test scripts/the-employee-portal-says-why-in-words.test.ts
//
// WHY THIS EXISTS (POST-A-010, last step)
//     The portal asks the server for the employee's record, payslips, leave and declaration. Two sentences the person used to be
//     given by the screen itself would otherwise become the server's raw refusals: "Not logged in. Please sign in ..." (a signed-out
//     visit now reaches the server first, which answers "Missing or invalid Authorization header"), and the limits on the
//     declaration's text boxes (the server refuses a name over 200 characters or an address over 500, naming the box, but a box
//     that stops typing at the limit never has to).
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const code = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/^\s*\/\/.*$/gm, " ");
const read = (rel: string) => code(fs.readFileSync(path.join(WEB, rel), "utf8"));

test("a signed-out visit is told so in words before the server is asked anything", () => {
  const src = read("app/portal/employee/page.tsx");
  const session = src.indexOf("auth.getSession()");
  const first = src.indexOf("api.portalSelf.employeeAccess()");
  assert.ok(session > 0 && first > 0, "the page no longer checks the session or no longer asks the server");
  assert.ok(session < first, "the session is checked after the server was already asked");
  assert.match(src, /Not logged in\. Please sign in to access your portal\./);
});

test("the declaration's text boxes stop at the lengths the server accepts", () => {
  const src = read("components/portal/TaxDeclarationTab.tsx");
  const box = (label: string) => new RegExp(`<Text label="${label.replace(/'/g, "'")}"[^>]*maxLength=\\{(\\d+)\\}`);
  assert.equal(box("Landlord's name").exec(src)?.[1], "200");
  assert.equal(box("Landlord's address").exec(src)?.[1], "500");
  assert.equal(box("Lender's name").exec(src)?.[1], "200");
  assert.equal(box("Landlord's PAN").exec(src)?.[1], "10");
  assert.equal(box("Lender's PAN").exec(src)?.[1], "10");
  assert.match(src, /<input value=\{value\} disabled=\{disabled\} maxLength=\{maxLength\}/);
});

test("the limits are the server's: the model names the same two numbers", () => {
  const model = fs.readFileSync(path.resolve(WEB, "..", "api", "models", "payroll.py"), "utf8");
  assert.match(model, /_NAME_MAX, _ADDRESS_MAX = 200, 500/);
});
