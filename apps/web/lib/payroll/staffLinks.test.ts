import { test } from "node:test";
import assert from "node:assert/strict";
import { employeeOfMember, readStaffRoster, sameName, staffRows, unlinked, type StaffMember, type StaffRoster } from "./staffLinks.ts";

const member = (id: string, full_name: string): StaffMember => ({ id, full_name, email: `${id}@firm.test`, role: "Executive" });
const roster = (employees: StaffRoster["employees"], enabled: boolean | null = true): StaffRoster =>
  ({ practice_client_id: "practice", payroll_enabled: enabled, employees });

test("the roster is read only from an answer shaped like one", () => {
  assert.equal(readStaffRoster(null), null);
  assert.equal(readStaffRoster({ success: false, data: null, error: "no" }), null);
  assert.equal(readStaffRoster({ success: true, data: {} }), null, "an answer with no employee list was read as an empty payroll");
  assert.equal(readStaffRoster({ success: true, data: { employees: [{ id: 1, name: "x" }] } }), null, "a row that is not an employee was accepted");
  const read = readStaffRoster({ success: true, data: { practice_client_id: "p", payroll_enabled: true,
    employees: [{ id: "e1", name: "Asha Rao", employee_code: "S001", staff_user_id: "u1", basic_paise: 5 }, { id: "e2", name: "Ravi", staff_user_id: "" }] } });
  assert.deepEqual(read, { practice_client_id: "p", payroll_enabled: true, employees: [
    { id: "e1", name: "Asha Rao", employee_code: "S001", designation: null, status: null, staff_user_id: "u1" },
    { id: "e2", name: "Ravi", employee_code: null, designation: null, status: null, staff_user_id: null }] });
});

test("a switch the server could not read is unknown, never off", () => {
  assert.equal(readStaffRoster({ success: true, data: { practice_client_id: "p", payroll_enabled: null, employees: [] } })?.payroll_enabled, null);
  assert.equal(readStaffRoster({ success: true, data: { practice_client_id: "p", employees: [] } })?.payroll_enabled, null);
  assert.equal(readStaffRoster({ success: true, data: { practice_client_id: null, payroll_enabled: false, employees: [] } })?.payroll_enabled, false);
});

test("two spellings of one name differ by more than case and spacing", () => {
  assert.equal(sameName("Asha  Rao", " asha rao "), true);
  assert.equal(sameName("Asha Rao", "Asha R"), false);
  assert.equal(sameName("Asha Rao", "Asha Rau"), false);
});

test("the rows keep four kinds apart, linked first, each in name order", () => {
  const members = [member("u2", "Ravi K"), member("u1", "Asha Rao"), member("u3", "Meera")];
  const rows = staffRows(roster([
    { id: "e9", name: "Zed, no sign-in" },
    { id: "e1", name: "Asha R.", staff_user_id: "u1" },
    { id: "e2", name: "ravi  k", staff_user_id: "u2" },
    { id: "e7", name: "Left the firm", staff_user_id: "u-removed" },
  ]), members);
  assert.deepEqual(rows.map((r) => [r.kind, "member" in r ? r.member.id : null, "employee" in r ? r.employee.id : null]), [
    ["linked", "u1", "e1"], ["linked", "u2", "e2"], ["member-only", "u3", null], ["employee-only", null, "e9"], ["member-gone", null, "e7"]]);
  assert.equal(rows[0].kind === "linked" && rows[0].namesDiffer, true, "a name spelt two ways is not said");
  assert.equal(rows[1].kind === "linked" && rows[1].namesDiffer, false, "case and spacing were called a different name");
});

test("a sign-in's payroll record is found by the link and by nothing else", () => {
  const r = roster([{ id: "e1", name: "Asha Rao", staff_user_id: "u1" }, { id: "e2", name: "Meera" }]);
  assert.equal(employeeOfMember(r, "u1")?.id, "e1");
  assert.equal(employeeOfMember(r, "u3"), null, "a name match was taken for a link");
  assert.equal(employeeOfMember(null, "u1"), null);
});

test("what a Link box offers is whoever has no link yet", () => {
  const got = unlinked(roster([{ id: "e1", name: "Asha Rao", staff_user_id: "u1" }, { id: "e2", name: "Meera" }, { id: "e3", name: "Anil" }]),
    [member("u1", "Asha Rao"), member("u2", "Ravi K")]);
  assert.deepEqual(got.members.map((m) => m.id), ["u2"]);
  assert.deepEqual(got.employees.map((e) => e.id), ["e3", "e2"]);
});
