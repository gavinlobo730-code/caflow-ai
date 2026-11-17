// POST-A-465. An employee's edit marks a PAN, UAN, ESI number, bank account number or IFSC emptied over a value on file at the box, in the
// server's words, and the Save refuses it without sending. The list and the sentence are held to the server's from the Python side.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { EMPLOYEE_IDENTIFIERS, removedEmployeeIdentifier, removedEmployeeIdentifiers } from "./employeeIdentifiers.ts";

const WEB = join(import.meta.dirname, "..", "..");

test("a box emptied over a value on file is refused in the server's words", () => {
  const said = removedEmployeeIdentifier("uan", "100200300400", "  ");
  assert.equal(said, "The UAN on file can be corrected but not removed: enter the corrected UAN. The salary TDS statement, the PF and ESI "
    + "returns and the salary payment read it, so an employee who has none any more is recorded as left or corrected, not left blank.");
});

test("a corrected value, and an empty box over nothing, are not refused", () => {
  assert.equal(removedEmployeeIdentifier("pan", "ABCPE1234F", "ABCPE1234G"), null);
  assert.equal(removedEmployeeIdentifier("bank_ifsc", null, ""), null);
  assert.equal(removedEmployeeIdentifier("esi_number", "", ""), null);
});

test("every emptied identifier is named, in the server's order", () => {
  const out = removedEmployeeIdentifiers(
    { pan: "ABCPE1234F", uan: "100200300400", esi_number: "31000123450001000", bank_account_no: "001234", bank_ifsc: "HDFC0000123" },
    { pan: "ABCPE1234F", uan: "", esi_number: "31000123450001000", bank_account_no: "", bank_ifsc: "" });
  assert.deepEqual(out.map((r) => r.field), ["uan", "bank_account_no", "bank_ifsc"]);
  assert.match(out[0].sentence, /^The UAN on file/);
  assert.deepEqual(Object.keys(EMPLOYEE_IDENTIFIERS), ["pan", "uan", "esi_number", "bank_account_no", "bank_ifsc"]);
});

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name.startsWith(".")) continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (p.endsWith(".tsx") && !p.includes(".test.")) out.push(p);
  }
  return out;
}

test("every screen that edits an employee's identifiers says it at the box and refuses the Save", () => {
  // The rule, not a list of files: a screen that calls updateEmployee and sends one of the five identifiers.
  const fields = Object.keys(EMPLOYEE_IDENTIFIERS);
  const doors = [...walk(join(WEB, "app")), ...walk(join(WEB, "components"))].filter((f) => {
    const src = readFileSync(f, "utf8");
    return /\.updateEmployee\(/.test(src) && fields.some((k) => new RegExp(`\\b${k}:`).test(src));
  });
  assert.ok(doors.length >= 2, `vacuity floor: the drawer and the add/edit modal, found ${doors.map((f) => relative(WEB, f))}`);
  const bad: string[] = [];
  for (const f of doors) {
    const src = readFileSync(f, "utf8");
    if (!/removedEmployeeIdentifiers\(/.test(src)) bad.push(`${relative(WEB, f)} does not ask removedEmployeeIdentifiers`);
    if (!/if \(removed\.length\) \{[^}]*setErr\(removed\[0\]\.sentence\)/.test(src)) bad.push(`${relative(WEB, f)} does not refuse the Save`);
    for (const k of fields) {
      if (!new RegExp(`aria-invalid=\\{removedAt\\("${k}"\\)`).test(src)) bad.push(`${relative(WEB, f)}: the ${k} box is not marked`);
    }
  }
  assert.deepEqual(bad, []);
});
