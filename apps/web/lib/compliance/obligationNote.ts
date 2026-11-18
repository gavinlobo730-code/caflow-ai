/**
 * What a workspace says when it records a return as filed and the compliance obligation it stands for was NOT closed by
 * the same click: the GST workspace (POST-A-264), the ITR workspace and the TDS workspace.
 *
 * The server closes the obligation itself and answers `compliance_obligation: { state, closed, message }`; this reads
 * that answer and decides nothing. A note appears only when the calendar was left open for a reason the CA should know
 * (no obligation on the calendar, another registration still to file, no Compliance access, a correction rather than
 * the original, a failure), never when it closed and never for an obligation that was already filed, which is the state
 * the CA wanted.
 */
export function obligationNote(data: unknown): string | null {
  if (typeof data !== "object" || data === null) return null;
  const answer = (data as { compliance_obligation?: unknown }).compliance_obligation;
  if (typeof answer !== "object" || answer === null) return null;
  const { closed, state, message } = answer as { closed?: unknown; state?: unknown; message?: unknown };
  if (closed === true || state === "already_filed") return null;
  return typeof message === "string" && message.trim() ? message : null;
}

/**
 * What became of the compliance obligation when a workspace filing was taken back out of Filed (POST-A-267, item 3): the server's own
 * sentence, whatever happened (reopened, left filed, not allowed), or null when the answer carries no obligation (an event form).
 */
export function reopeningNote(data: unknown): string | null {
  if (typeof data !== "object" || data === null) return null;
  const answer = (data as { compliance_obligation?: unknown }).compliance_obligation;
  if (typeof answer !== "object" || answer === null) return null;
  const { message } = answer as { message?: unknown };
  return typeof message === "string" && message.trim() ? message : null;
}
