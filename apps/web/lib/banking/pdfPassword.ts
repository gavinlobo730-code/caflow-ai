/**
 * What the server's two PDF-password refusals look like to a screen (accounting-23).
 *
 * A bank-emailed statement is often locked with a password the CA has to type.
 * The server answers an upload of such a file with a 422 whose detail carries a
 * CODE beside its sentence — `{message, code}`, the same shape the
 * statement-totals refusal uses — and the import dialog asks for the password
 * on the CODE, never on the wording of the sentence, which is written for a
 * human and may be reworded.
 *
 * THE TWO CODES ARE THE BACKEND'S VOCABULARY, not this file's: they are
 * `PdfPasswordRequired.code` and `PdfPasswordIncorrect.code` in
 * `apps/api/domain/banking/normalizer.py`, and
 * `tests/test_a_password_protected_statement_can_be_opened.py` reads this file
 * from the Python side and fails if either string drifts. A guard written here
 * would assert the browser against a copy of itself.
 *
 * NOTHING HERE STORES A PASSWORD. It only classifies an error. The dialog that
 * uses it keeps the typed value in component state for one request and drops it
 * when the file changes or the import succeeds — see BankImportModal.
 */

export const PDF_PASSWORD_REQUIRED = "pdf_password_required";
export const PDF_PASSWORD_INCORRECT = "pdf_password_incorrect";

export type PdfPasswordAsk = "required" | "incorrect";

/**
 * Whether `err` is one of the two password refusals, and which.
 *
 * Duck-typed on `code` rather than `instanceof ApiRefusal`, so this stays
 * importable by a plain node test (lib/api pulls in the Supabase client) and
 * works for any refusal carrier that exposes the server's code.
 */
export function pdfPasswordAsk(err: unknown): PdfPasswordAsk | null {
  if (typeof err !== "object" || err === null) return null;
  const code = (err as { code?: unknown }).code;
  if (code === PDF_PASSWORD_REQUIRED) return "required";
  if (code === PDF_PASSWORD_INCORRECT) return "incorrect";
  return null;
}
