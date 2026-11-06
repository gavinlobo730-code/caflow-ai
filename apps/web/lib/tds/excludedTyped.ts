/**
 * The deductions typed on the TDS screen that a statement built from the books leaves out (POST-A-078).
 *
 * The 26Q built from the books reads posted purchase bills and withholding advances only, so a deduction a CA typed on the TDS screen (a register row that neither a
 * bill nor an advance wrote) is not on it. The server NAMES them (`excluded_typed`: how many, the tax they withheld, its own sentence and each row) and adds nothing to
 * the statement's totals. This module only READS that answer. It sums nothing, words nothing and decides nothing.
 *
 * FOUR states, and they are kept apart because they are not the same fact:
 *   * `some`       a positive count and a tax the server stated: the note is drawn from them.
 *   * `none`       the server said nothing is left out (a count of nothing). The screen is silent, as it is for the payments to a non-resident.
 *   * `absent`     no key at all: a 24Q or a 27Q (the key is a 26Q's), or a server that predates it. A server that did not say is not a server that said none, and a
 *                  screen cannot tell the two apart, so it says nothing either.
 *   * `unreadable` a key that is there and cannot be read whole (a count or a tax that is not a whole number, an object that is not one). The screen says it could not
 *                  read it, because silence there would read as "none".
 * Only what the note DRAWS is required: the count and the tax. The server's sentence is drawn when it sent one and its absence does not hide a note whose figures are
 * whole, and the rows are drawn only when the list is whole (a count the rows do not match, or a row that cannot be read, draws the figures and no list).
 */
export interface ExcludedTypedRow {
  id: string | null;
  deductee_name: string | null;
  deductee_pan: string | null;
  /** The label the period's own Act uses (TDS-17); `section_1961` is the stored routing key beside it. */
  section: string | null;
  section_1961: string | null;
  transaction_date: string;
  payment_amount_paise: number;
  tds_paise: number;
}

export interface ExcludedTyped {
  count: number;
  tds_paise: number;
  /** The server's sentence, drawn as it arrived, or null when it sent none. */
  reason: string | null;
  /** Every row, or null when the list the server sent is not whole. */
  rows: ExcludedTypedRow[] | null;
}

export type ExcludedTypedReading =
  | { kind: "some"; typed: ExcludedTyped }
  | { kind: "none" }
  | { kind: "absent" }
  | { kind: "unreadable" };

function isObject(x: unknown): x is Record<string, unknown> {
  return typeof x === "object" && x !== null && !Array.isArray(x);
}

function wholeNumber(x: unknown): x is number {
  return typeof x === "number" && Number.isFinite(x) && Number.isInteger(x);
}

function textOrNull(x: unknown): string | null | undefined {
  if (x === null || x === undefined) return null;
  return typeof x === "string" ? x : undefined;
}

function readRow(raw: unknown): ExcludedTypedRow | null {
  if (!isObject(raw)) return null;
  const { transaction_date, payment_amount_paise, tds_paise } = raw;
  if (typeof transaction_date !== "string" || !wholeNumber(payment_amount_paise) || !wholeNumber(tds_paise)) return null;
  const id = textOrNull(raw.id);
  const name = textOrNull(raw.deductee_name);
  const pan = textOrNull(raw.deductee_pan);
  const section = textOrNull(raw.section);
  const section1961 = textOrNull(raw.section_1961);
  if (id === undefined || name === undefined || pan === undefined || section === undefined || section1961 === undefined) return null;
  return { id, deductee_name: name, deductee_pan: pan, section, section_1961: section1961, transaction_date, payment_amount_paise, tds_paise };
}

/** What a statement's `excluded_typed` says, in one of four states. */
export function readExcludedTyped(raw: unknown): ExcludedTypedReading {
  if (raw === undefined || raw === null) return { kind: "absent" };
  if (!isObject(raw)) return { kind: "unreadable" };
  const { count, tds_paise, reason, deductions } = raw;
  if (!wholeNumber(count) || count < 0) return { kind: "unreadable" };
  if (count === 0) return { kind: "none" };
  if (!wholeNumber(tds_paise) || tds_paise < 0) return { kind: "unreadable" };
  let rows: ExcludedTypedRow[] | null = null;
  if (Array.isArray(deductions) && deductions.length === count) {
    const read = deductions.map(readRow);
    if (read.every((r): r is ExcludedTypedRow => r !== null)) rows = read as ExcludedTypedRow[];
  }
  return { kind: "some", typed: { count, tds_paise, reason: typeof reason === "string" && reason.trim() !== "" ? reason : null, rows } };
}
