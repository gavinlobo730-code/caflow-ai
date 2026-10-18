/**
 * Deleting one row from the browser, and saying what actually happened (POST-A-247).
 *
 * WHAT WAS WRONG
 *   Four screens deleted a row over PostgREST and read nothing back: the document-request line and the shared-report line
 *   on the client portal preview, an income-tax notice, and a scheduled-report schedule. The delete policies on those tables
 *   are role-aware (migration 261: Manager for shared and scheduled reports, Executive for document requests, Manager for
 *   notices), so for a Reviewer the delete is hidden by row security and answers NO ERROR AND NO ROWS. The screens dropped
 *   the line, or toasted "Schedule deleted", for a row that was still there on the next load. It is the defect POST-A-151
 *   fixed for stored documents, found again on the neighbours.
 *
 * WHAT IT DOES
 *   Asks for the deleted row back (`.select("id")`) and trusts nothing else: the screen says "deleted" only when the
 *   server returned the row. An error is passed through in the database's words; an empty answer is the one sentence below.
 *
 * It reads a result. WHO may delete stays in the database policies.
 */

export const ROW_NOT_DELETED =
  "Nothing was deleted. Your role may not delete this, or someone else already removed it. Reload to see what is there now.";

interface Outcome {
  data: unknown[] | null;
  error: { message: string } | null;
}

/** The slice of the Supabase client this uses, so a test can stand a fake in its place. */
export interface RowDeleteClient {
  from(table: string): {
    delete(): { eq(column: string, value: string): { select(columns: string): PromiseLike<Outcome> } };
  };
}

export type RowDeleteOutcome = { deleted: true } | { deleted: false; message: string };

export async function deleteRowAndConfirm(sb: RowDeleteClient, table: string, id: string): Promise<RowDeleteOutcome> {
  const row = await sb.from(table).delete().eq("id", id).select("id");
  if (row.error) return { deleted: false, message: row.error.message };
  // A null or empty payload is "no row came back", never success: the line stays until the server says it is gone.
  if ((row.data ?? []).length === 0) return { deleted: false, message: ROW_NOT_DELETED };
  return { deleted: true };
}
