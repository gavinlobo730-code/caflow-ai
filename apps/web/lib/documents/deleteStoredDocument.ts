/**
 * Deleting a stored client document from the browser, and saying what actually happened (POST-A-151).
 *
 * WHAT WAS WRONG
 *   Only a Partner may delete a stored file or the `client_documents` row that describes it (migrations 261 and 469).
 *   For anyone else both deletes are DENIED SILENTLY: Storage answers a denied `remove` with an empty list and no error,
 *   and PostgREST answers a delete that row security hid with no error and no rows. The three delete handlers read
 *   neither, so a Manager pressing Delete saw the line vanish from the page and the document was still there on the
 *   next load. A screen that says "deleted" about something it did not delete is the false statement this product exists
 *   not to make.
 *
 * WHAT IT DOES
 *   Asks for the deleted row back (`.select("id")`) and trusts nothing else: the line leaves the page only when the
 *   server says the record is gone. The file is removed first (a record whose file failed to go can be retried, and a
 *   deleted record never leaves the document's content behind in storage, which matters when the person asked for it to
 *   be erased), and an EMPTY removal list is not an error by itself because the file may already be absent; what decides
 *   is whether the record went. The cost of that order is the case the record is then refused (a later version of the
 *   document, or a tax claim, still points at it): the file is gone and the entry will not open, and the person is told
 *   so, with the database's reason, rather than shown a list that looks untouched.
 *
 * This reads a result. The rule (who may delete) stays in the database policies, and moving the delete behind the API
 * with a retention decision beside it is the larger piece of work this does not replace.
 */

export const DOCUMENT_NOT_DELETED =
  "This document was not deleted. Only a Partner can delete a document, or it was already removed by someone else. Reload to see what is there now.";
export const FILE_REMOVED_RECORD_REMAINS =
  "The file was removed but its record could not be, so this entry will not open. Reload to see what is there now.";

interface Outcome {
  data: unknown[] | null;
  error: { message: string } | null;
}

/** The slice of the Supabase client this uses, so a test can stand a fake in its place. */
export interface StoredDocumentClient {
  storage: { from(bucket: string): { remove(paths: string[]): PromiseLike<Outcome> } };
  from(table: string): {
    delete(): { eq(column: string, value: string): { select(columns: string): PromiseLike<Outcome> } };
  };
}

export type DeleteOutcome = { deleted: true } | { deleted: false; message: string };

export async function deleteStoredDocument(
  sb: StoredDocumentClient,
  doc: { id: string; file_path: string },
  bucket: string,
): Promise<DeleteOutcome> {
  const file = await sb.storage.from(bucket).remove([doc.file_path]);
  if (file.error) return { deleted: false, message: file.error.message };

  const row = await sb.from("client_documents").delete().eq("id", doc.id).select("id");
  // Whether the file actually went is a fact about this call: Storage returns the objects it removed, and an empty list
  // means it removed none (denied, or already absent). A refusal of the record AFTER the file went has to say so, or the
  // list keeps a document whose download is broken and nothing on the screen says why (a versioned document's original
  // and a document a tax claim cites are refused by a foreign key, 23503, after the file has already gone).
  const fileWent = (file.data ?? []).length > 0;
  if (row.error) {
    return {
      deleted: false,
      message: fileWent ? `${FILE_REMOVED_RECORD_REMAINS} Reason given: ${row.error.message}` : row.error.message,
    };
  }

  if ((row.data ?? []).length > 0) return { deleted: true };
  return { deleted: false, message: fileWent ? FILE_REMOVED_RECORD_REMAINS : DOCUMENT_NOT_DELETED };
}
