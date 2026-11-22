/**
 * THE ROWS OF A BANK STATEMENT THAT WERE NOT READ (POST-A-551).
 *
 * A row with a narration and a figure whose date or amount could not be read used to be left out of an import with nothing to say
 * which one: an amount printed as "12x4.00" read as nil, exactly like a blank cell. The server now names each such row, with the
 * cell as the bank printed it, in the preview and in the import's answer (`unread_rows`, and one sentence in `unread_note`).
 *
 * This reads that part of an answer, and reads it defensively: an answer from a server that has not been deployed yet carries
 * neither key, and that is "nothing to show", never a crash and never a row invented from a shape this screen does not know.
 */
export interface UnreadRow {
  /** Which cell stopped the row: "date", "amount", "debit" or "credit". */
  column: string;
  /** That cell as the bank printed it. */
  cell: string;
  /** The row's date where that much was read; null when the date is what could not be read. */
  date: string | null;
  description: string;
}

const COLUMN_WORDS: Readonly<Record<string, string>> = { date: "date", amount: "amount", debit: "debit", credit: "credit" };

/** The unread rows of an answer: only entries of the shape above, in the order sent. */
export function unreadRowsOf(answer: unknown): UnreadRow[] {
  const list = (answer as { unread_rows?: unknown } | null | undefined)?.unread_rows;
  if (!Array.isArray(list)) return [];
  const rows: UnreadRow[] = [];
  for (const item of list) {
    if (!item || typeof item !== "object") continue;
    const r = item as Record<string, unknown>;
    if (typeof r.column !== "string" || typeof r.cell !== "string") continue;
    rows.push({
      column: r.column, cell: r.cell,
      date: typeof r.date === "string" && r.date ? r.date : null,
      description: typeof r.description === "string" ? r.description : "",
    });
  }
  return rows;
}

/** What the screen says above the list: how many, and that they are in none of the figures. */
export function unreadHeading(count: number): string {
  return count === 1
    ? "1 row of the file could not be read and is not in these figures."
    : `${count} rows of the file could not be read and are not in these figures.`;
}

/** What stopped one row, in words: `the amount is printed as "12x4.00"`. */
export function whatStopped(row: UnreadRow): string {
  return `the ${COLUMN_WORDS[row.column] ?? row.column} is printed as "${row.cell}"`;
}
