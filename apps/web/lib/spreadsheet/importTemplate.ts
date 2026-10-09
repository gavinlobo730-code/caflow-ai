/**
 * What the import dialog's downloadable template contains, and what its last step
 * says about the rows it did not send (PRE-A-001, from driving the dialog).
 *
 * ── THE TEMPLATE'S ROWS ─────────────────────────────────────────────────────
 * The Excel template was three rows: the headers, a row of hints, and an
 * "example" that was the hint row again. The reader skips only a `#` line, so
 * uploading the template exactly as downloaded reported TWO VALID ROWS — the
 * hints, read as data — while the Instructions sheet told the CA to delete
 * "Row 2 (hints)" and to enter data from Row 3. The template is now the headers
 * and ONE note row, written the way the CSV template writes its note: a single
 * cell that begins with `# `, which `parseCsv` skips whether or not the library
 * quotes it. Data starts on row 3, as the Instructions say, and uploading the
 * template untouched reports "no data rows" instead of two.
 */

export interface TemplateColumn {
  key: string;
  label: string;
  required: boolean;
  hint?: string;
}

const hintOf = (c: TemplateColumn): string => c.hint ?? (c.required ? "REQUIRED" : "optional");

/** The one note line: `# hint | hint | hint`, a note to the reader and not data.
 *  The CSV template writes this same string as its second line. */
export function templateNote(columns: TemplateColumn[]): string {
  return "# " + columns.map(hintOf).join(" | ");
}

/** The template sheet: the header row, then the note as ONE cell. */
export function templateSheetRows(columns: TemplateColumn[]): string[][] {
  return [columns.map((c) => c.key), [templateNote(columns)]];
}

/** The Instructions sheet. Every sentence here is true of the reader: row 2 is a
 *  note that is skipped, data starts on row 3, and a date cell is read as the
 *  date it holds. */
export function templateInstructions(columns: TemplateColumn[]): string[][] {
  return [
    ["PracticeSync AI — Import Template"],
    [""],
    ["INSTRUCTIONS:"],
    ["1. Do NOT change the header row (Row 1)."],
    ["2. Row 2 is a note about each column. It begins with # and is skipped when you upload, so you can leave it or delete it."],
    ["3. Enter your data from Row 3 onwards."],
    ["4. Dates: a cell Excel holds as a date is read as that date, whatever format it shows. A date typed as text should be dd-mm-yyyy or yyyy-mm-dd."],
    ["5. Upload this file directly (.xlsx) or save it as CSV — both are accepted."],
    [""],
    ["Column Guide:"],
    ...columns.map((c) => [c.key, c.required ? "REQUIRED" : "optional", c.hint ?? c.label]),
  ];
}

// ── the rows the preview held back ───────────────────────────────────────────

export interface HeldRowsNote {
  /** How many rows of the file the preview flagged and the dialog did not send. */
  count: number;
  /** One line per row, "Row 4: "Purchase cost" is required", the first `limit`. */
  lines: string[];
  /** How many more there are beyond `lines`. */
  more: number;
}

/**
 * The done step's account of the rows that never left the browser. The preview
 * says "N rows with errors (will be skipped)"; the done step used to say nothing,
 * so a file of six rows reported "3 new, 2 failed" and the sixth — a blank
 * required cell, held back before anything was sent — was in neither number.
 */
export function heldBackRows(
  rows: { index: number; errors: string[] }[],
  limit = 8,
): HeldRowsNote {
  const held = rows.filter((r) => r.errors.length > 0);
  const shown = held.slice(0, Math.max(0, limit));
  return {
    count: held.length,
    lines: shown.map((r) => `Row ${r.index}: ${r.errors.join("; ")}`),
    more: held.length - shown.length,
  };
}

/** The sentence over those lines. */
export function heldBackHeading(count: number): string {
  return count === 1
    ? "1 row in your file was not sent because the preview flagged it:"
    : `${count} rows in your file were not sent because the preview flagged them:`;
}
