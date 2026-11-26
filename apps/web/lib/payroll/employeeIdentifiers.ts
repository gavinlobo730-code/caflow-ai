/**
 * AN EMPLOYEE'S IDENTIFIERS ARE CORRECTED AND NOT REMOVED BY AN EDIT, AND THE BOX SAYS SO BEFORE ANYTHING IS SENT (POST-A-465).
 *
 * Since POST-A-399's third slice the server refuses an edit that empties a PAN, UAN, ESI number, bank account number or IFSC on file
 * (`models.payroll.EMPLOYEE_IDENTIFIERS` with `EMPLOYEE_IDENTIFIER_WHY`, asked by `models.clearable.removed_identifier_problem`), and the
 * person used to learn it only after pressing Save. This is the same list and the same words, held to the server's from the Python side
 * (`tests/test_an_emptied_box_on_an_employees_edit_clears_or_is_refused.py`), so a box emptied over a value on file is marked where it is and
 * the Save says the server's sentence without sending. The server stays the authority: it refuses the same edit whatever a screen sends.
 */
import { removedIdentifierProblem } from "../forms/editedValue.ts";

/** Each identifier an edit keeps, with the words a person reads: the server's `EMPLOYEE_IDENTIFIERS`, in its order. */
export const EMPLOYEE_IDENTIFIERS = {
  pan: "PAN",
  uan: "UAN",
  esi_number: "ESI number",
  bank_account_no: "bank account number",
  bank_ifsc: "IFSC",
} as const;

export type EmployeeIdentifier = keyof typeof EMPLOYEE_IDENTIFIERS;

/** The server's `EMPLOYEE_IDENTIFIER_WHY`, word for word. */
export const EMPLOYEE_IDENTIFIER_WHY =
  "The salary TDS statement, the PF and ESI returns and the salary payment read it, so an employee who has none any more is recorded as left or corrected, not left blank.";

export type IdentifierValues = Partial<Record<EmployeeIdentifier, string | null | undefined>>;

/** The sentence for one box emptied over a value on file, or null. */
export function removedEmployeeIdentifier(field: EmployeeIdentifier, onFile: string | null | undefined,
                                          now: string | null | undefined): string | null {
  return removedIdentifierProblem(EMPLOYEE_IDENTIFIERS[field], onFile, now, EMPLOYEE_IDENTIFIER_WHY);
}

/** Every box emptied over a value on file, in the server's order, each with its sentence (the first is the one the server would say). */
export function removedEmployeeIdentifiers(onFile: IdentifierValues, now: IdentifierValues): { field: EmployeeIdentifier; sentence: string }[] {
  const out: { field: EmployeeIdentifier; sentence: string }[] = [];
  for (const field of Object.keys(EMPLOYEE_IDENTIFIERS) as EmployeeIdentifier[]) {
    const sentence = removedEmployeeIdentifier(field, onFile[field], now[field]);
    if (sentence) out.push({ field, sentence });
  }
  return out;
}
