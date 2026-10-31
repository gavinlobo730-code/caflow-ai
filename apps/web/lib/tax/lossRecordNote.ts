/**
 * What the ITR workspace says about the brought-forward loss records when it records a return as filed (POST-A-073).
 *
 * The server writes what the filed return used of each loss back to the loss records and answers
 * `brought_forward_losses: { state, message, losses }`; this reads that answer and decides nothing. A note appears when records
 * were updated (the CA should know the next year's figures moved) and when they could not be (the CA has to record the use by
 * hand), never when the return set off no loss or the records already showed it.
 */
export function lossRecordNote(data: unknown): string | null {
  if (typeof data !== "object" || data === null) return null;
  const answer = (data as { brought_forward_losses?: unknown }).brought_forward_losses;
  if (typeof answer !== "object" || answer === null) return null;
  const { state, message } = answer as { state?: unknown; message?: unknown };
  if (state !== "written" && state !== "not_written") return null;
  return typeof message === "string" && message.trim() ? message : null;
}

/**
 * The same answer when a person ASKED for it (a button that updates the loss records of a return already filed): whatever state it is in, the
 * server's sentence is shown, because a click that is answered with silence reads as a click that did nothing.
 */
export function lossRecordAnswer(data: unknown): string | null {
  if (typeof data !== "object" || data === null) return null;
  const answer = (data as { brought_forward_losses?: unknown }).brought_forward_losses;
  if (typeof answer !== "object" || answer === null) return null;
  const { message } = answer as { message?: unknown };
  return typeof message === "string" && message.trim() ? message : null;
}
