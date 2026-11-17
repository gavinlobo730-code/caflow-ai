/**
 * A purchase note line's CGST Act s.17(5) mark (POST-A-459, migration 685), in the shape the server takes.
 *
 * A purchase bill line says whether its credit is blocked and the note that adjusts it says the same thing: a note against a blocked
 * line moves the credit ledgers by the creditable tax only, as the bill did. The mark is the CA's, never inferred, and a blocked line
 * names its clause (the bill's list, `BLOCKED_CREDIT_REASONS`). No figure is computed here: the server derives every blocked head.
 */

export interface NoteLineBlockedCredit {
  /** false = blocked. Absent or true = eligible, which is the column's default and how every earlier note was posted. */
  itc_eligible?: boolean;
  blocked_credit_reason?: string;
}

export function noteLineIsBlocked(l: NoteLineBlockedCredit): boolean {
  return l.itc_eligible === false;
}

/** The two keys a line sends: nothing for an eligible line (so a note with no blocked line is sent exactly as before), the mark and its
 *  clause for a blocked one. */
export function blockedCreditPayload(l: NoteLineBlockedCredit): { itc_eligible?: false; blocked_credit_reason?: string } {
  return noteLineIsBlocked(l) ? { itc_eligible: false, blocked_credit_reason: (l.blocked_credit_reason ?? "").trim() } : {};
}

/** A stored line's mark, for an edit that re-sends every line (a mark the editor did not carry would be taken off a draft). */
export function blockedCreditFromStored(l: { itc_eligible?: boolean | null; blocked_credit_reason?: string | null }): NoteLineBlockedCredit {
  return l.itc_eligible === false ? { itc_eligible: false, blocked_credit_reason: l.blocked_credit_reason ?? "" } : {};
}

/** The sentence a form shows when a blocked line names no clause, or null. The server refuses it too; this says so before the click. */
export function blockedCreditProblem(lines: NoteLineBlockedCredit[]): string | null {
  const i = lines.findIndex((l) => noteLineIsBlocked(l) && !(l.blocked_credit_reason ?? "").trim());
  return i < 0 ? null : `Line ${i + 1} is marked ITC blocked: choose the section 17(5) clause it is blocked under.`;
}
