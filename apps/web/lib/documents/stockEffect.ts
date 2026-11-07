/**
 * What a document did to stock, read off the response that issued it (POST-A-092).
 *
 * A sales invoice, a purchase bill, a credit note and a purchase debit note move stock AFTER they are committed, and that step
 * swallows its own failures so a refused ledger row can never un-issue a document that is already in the books. The response
 * now carries `stock_effect` (`domain/inventory/stock_effect`): absent when the document has no goods line, and present with
 * `recorded` and the server's own sentence otherwise. This module is the browser's whole decision about that field.
 *
 *   * The sentence is the server's, word for word. Nothing here words a failure or knows which failures there are.
 *   * ABSENT means stock is not involved and says nothing. PRESENT with `recorded: true` also says nothing.
 *   * Anything else that is present is a problem, including a payload in the wrong shape: a field that cannot be read is not
 *     "all recorded", so it reads as a problem with a fallback sentence and never as silence.
 */

export const UNREADABLE_STOCK_EFFECT =
  "The stock effect of this document could not be confirmed. Check the stock report before relying on it.";

/** The sentence to show for one response, or null when there is nothing to say. */
export function stockEffectProblem(data: unknown): string | null {
  if (!data || typeof data !== "object") return null;
  const effect = (data as { stock_effect?: unknown }).stock_effect;
  if (effect === undefined || effect === null) return null;
  if (typeof effect !== "object" || Array.isArray(effect)) return UNREADABLE_STOCK_EFFECT;
  const { recorded, problem } = effect as { recorded?: unknown; problem?: unknown };
  if (recorded === true) return null;
  return typeof problem === "string" && problem.trim() !== "" ? problem.trim() : UNREADABLE_STOCK_EFFECT;
}

/** A run of responses (a bulk issue): how many carried a problem, and the first sentence as the example. */
export function stockEffectSummary(responses: readonly unknown[]): { count: number; first: string | null } {
  const problems = responses.map(stockEffectProblem).filter((p): p is string => p !== null);
  return { count: problems.length, first: problems[0] ?? null };
}

/**
 * The server's sentence when it left stock alone ON PURPOSE, because the note said no goods came back (`stock_not_moved`, POST-A-371). It is not a problem and is not part of `stock_effect`:
 * a CA who chose "No goods returned" is told, in the server's words, that nothing moved and how to record it if goods did. Absent means the question did not arise (no goods line, or the
 * answer was yes). Nothing here words it.
 */
export function stockNotMovedSentence(data: unknown): string | null {
  if (!data || typeof data !== "object") return null;
  const said = (data as { stock_not_moved?: unknown }).stock_not_moved;
  return typeof said === "string" && said.trim() !== "" ? said.trim() : null;
}

/**
 * The sentence for a bulk run: how many notes were issued with stock left alone on purpose, and the first of the server's sentences as the example. Null for none. A credit note's goods
 * "came back"; a purchase debit note's "went back to the supplier" (the server's own words for each, `domain/inventory/note_goods`), so the kind says which.
 */
export function bulkStockNotMovedSentence(responses: readonly unknown[], kind: "credit_note" | "debit_note"): string | null {
  const said = responses.map(stockNotMovedSentence).filter((p): p is string => p !== null);
  if (said.length === 0) return null;
  const which = said.length === 1 ? "One of them said" : `${said.length} of them said`;
  const what = kind === "credit_note" ? "no goods came back" : "no goods went back to the supplier";
  return `${which} ${what}, so stock was left alone. For example: ${said[0]}`;
}

/** Sentences joined into one message: each but the last loses its full stop so the join never reads "issued.. Credit note". */
export function joinSentences(parts: readonly (string | null | undefined)[]): string {
  const said = parts.filter((p): p is string => Boolean(p && p.trim() !== ""));
  return said.map((p, i) => (i < said.length - 1 ? p.replace(/\.+$/, "") : p)).join(". ");
}

/** The toast for one issued document: the usual message, with the server's sentence after it when stock was not all recorded. */
export function issuedMessage(message: string, data: unknown): { text: string; type: "success" | "warning" } {
  const problem = stockEffectProblem(data);
  return problem ? { text: `${message}. ${problem}`, type: "warning" } : { text: message, type: "success" };
}

/** The sentence for a bulk run, or null. Names the count, because one sentence cannot say which documents it was. */
export function bulkStockSentence(summary: { count: number; first: string | null }): string | null {
  if (summary.count === 0 || summary.first === null) return null;
  const which = summary.count === 1 ? "One of them did not record all of its" : `${summary.count} of them did not record all of their`;
  return `${which} stock effect. For example: ${summary.first}`;
}

/** The sentences already shown plus the new ones, each once: a panel that keeps a first document's problem when a second arrives. */
export function withMoreStockSentences(shown: readonly string[], added: readonly (string | null)[]): string[] {
  const next = [...shown];
  for (const sentence of added) if (sentence && !next.includes(sentence)) next.push(sentence);
  return next;
}
