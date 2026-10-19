/**
 * What the GST workspace says when it records a return as filed and the compliance obligation it stands for was NOT
 * closed by the same click (POST-A-254).
 *
 * The server closes the obligation itself and answers `compliance_obligation: { state, closed, message }`; this reads
 * that answer and decides nothing. A note appears only when the calendar was left open for a reason the CA should know
 * (no obligation on the calendar, another registration still to file, no Compliance access, a failure), never when it
 * closed and never for an obligation that was already filed, which is the state the CA wanted.
 */
export function obligationNote(data: unknown): string | null {
  if (typeof data !== "object" || data === null) return null;
  const answer = (data as { compliance_obligation?: unknown }).compliance_obligation;
  if (typeof answer !== "object" || answer === null) return null;
  const { closed, state, message } = answer as { closed?: unknown; state?: unknown; message?: unknown };
  if (closed === true || state === "already_filed") return null;
  return typeof message === "string" && message.trim() ? message : null;
}
