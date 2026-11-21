/**
 * A TEAM SIGN-IN AND A RECORD IN THE FIRM'S OWN PAYROLL, PAIRED FOR A SCREEN (POST-A-540).
 *
 * A member of the firm's staff is two records: a sign-in on the Team screen and, if the firm pays them here, an employee in
 * the firm's own payroll (My practice, Payroll). The server holds a link between them (`payroll_employees.staff_user_id`)
 * and answers the firm's payroll roster to a Partner (`GET /api/payroll/practice-staff`). This module only PAIRS what the two
 * reads returned, for a table. It decides nothing: who may be linked to whom is the server's rule.
 *
 * A LINK, NEVER A MERGE, so a name can differ on the two records and the screen says so instead of choosing one.
 *
 * FOUR KINDS OF ROW, none standing in for another:
 *   linked         a sign-in and a payroll record the server says are one person;
 *   member-only    a sign-in with no payroll record;
 *   employee-only  a payroll record with no sign-in;
 *   member-gone    a payroll record linked to somebody who is no longer on the Team list (removed, or the list was cut).
 */

export interface RosterEmployee {
  id: string;
  name: string;
  employee_code?: string | null;
  designation?: string | null;
  status?: string | null;
  staff_user_id?: string | null;
}

export interface StaffMember {
  id: string;
  full_name: string;
  email: string;
  role?: string;
  member_state?: string;
}

export interface StaffRoster {
  /** The practice's own client, or null where the firm has none yet. */
  practice_client_id: string | null;
  /** true / false, or null when the server could not read the switch (never shown as "off"). */
  payroll_enabled: boolean | null;
  employees: RosterEmployee[];
}

export type StaffRow =
  | { kind: "linked"; member: StaffMember; employee: RosterEmployee; namesDiffer: boolean }
  | { kind: "member-only"; member: StaffMember }
  | { kind: "employee-only"; employee: RosterEmployee }
  | { kind: "member-gone"; employee: RosterEmployee };

function isObject(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === "object" && !Array.isArray(v);
}

/** The roster out of the server's answer, or null when the answer is not one (refused, failed, or another shape). */
export function readStaffRoster(res: unknown): StaffRoster | null {
  if (!isObject(res) || res.success !== true || !isObject(res.data)) return null;
  const d = res.data;
  if (!Array.isArray(d.employees)) return null;
  const employees: RosterEmployee[] = [];
  for (const e of d.employees) {
    if (!isObject(e) || typeof e.id !== "string" || typeof e.name !== "string") return null;
    employees.push({
      id: e.id,
      name: e.name,
      employee_code: typeof e.employee_code === "string" ? e.employee_code : null,
      designation: typeof e.designation === "string" ? e.designation : null,
      status: typeof e.status === "string" ? e.status : null,
      staff_user_id: typeof e.staff_user_id === "string" && e.staff_user_id ? e.staff_user_id : null,
    });
  }
  return {
    practice_client_id: typeof d.practice_client_id === "string" && d.practice_client_id ? d.practice_client_id : null,
    payroll_enabled: typeof d.payroll_enabled === "boolean" ? d.payroll_enabled : null,
    employees,
  };
}

/** Two spellings of one name: case and spacing aside. "Asha  Rao" and "asha rao" are the same; "Asha R" is not. */
export function sameName(a: string, b: string): boolean {
  const fold = (s: string) => s.trim().replace(/\s+/g, " ").toLocaleLowerCase("en-IN");
  return fold(a) === fold(b);
}

const byText = (a: string, b: string) => a.localeCompare(b, "en-IN", { sensitivity: "base" });

/** The table: linked pairs first, then sign-ins with no payroll record, then payroll records with no sign-in. */
export function staffRows(roster: StaffRoster, members: StaffMember[]): StaffRow[] {
  const memberById = new Map(members.map((m) => [m.id, m]));
  const linked: Extract<StaffRow, { kind: "linked" }>[] = [];
  const gone: Extract<StaffRow, { kind: "member-gone" }>[] = [];
  const employeeOnly: Extract<StaffRow, { kind: "employee-only" }>[] = [];
  const taken = new Set<string>();
  for (const employee of roster.employees) {
    if (!employee.staff_user_id) { employeeOnly.push({ kind: "employee-only", employee }); continue; }
    const member = memberById.get(employee.staff_user_id);
    if (!member) { gone.push({ kind: "member-gone", employee }); continue; }
    taken.add(member.id);
    linked.push({ kind: "linked", member, employee, namesDiffer: !sameName(member.full_name, employee.name) });
  }
  const memberOnly: Extract<StaffRow, { kind: "member-only" }>[] =
    members.filter((m) => !taken.has(m.id)).map((member) => ({ kind: "member-only", member }));
  linked.sort((a, b) => byText(a.member.full_name, b.member.full_name));
  memberOnly.sort((a, b) => byText(a.member.full_name, b.member.full_name));
  employeeOnly.sort((a, b) => byText(a.employee.name, b.employee.name));
  gone.sort((a, b) => byText(a.employee.name, b.employee.name));
  return [...linked, ...memberOnly, ...employeeOnly, ...gone];
}

/** The payroll record a sign-in is linked to, for the mark on the Team list. */
export function employeeOfMember(roster: StaffRoster | null, memberId: string): RosterEmployee | null {
  return (roster?.employees ?? []).find((e) => e.staff_user_id === memberId) ?? null;
}

/** Sign-ins with no payroll record, and payroll records with no sign-in: what each "Link to…" box may offer. */
export function unlinked(roster: StaffRoster, members: StaffMember[]): { members: StaffMember[]; employees: RosterEmployee[] } {
  const taken = new Set(roster.employees.map((e) => e.staff_user_id).filter((id): id is string => !!id));
  return {
    members: members.filter((m) => !taken.has(m.id)).sort((a, b) => byText(a.full_name, b.full_name)),
    employees: roster.employees.filter((e) => !e.staff_user_id).sort((a, b) => byText(a.name, b.name)),
  };
}
