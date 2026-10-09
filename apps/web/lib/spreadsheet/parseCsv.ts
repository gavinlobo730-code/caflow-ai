/**
 * Reading the CSV text the import dialog works from (moved out of
 * `components/CsvImportModal.tsx`, PRE-A-001, so it can be tested without a
 * browser and so a workbook's text and a CSV file's go through ONE reader).
 *
 * A chosen workbook is turned into CSV text by `sheetToCsvWithIsoDates` and read
 * by `parseCsv` exactly as a CSV file is, so a template, a workbook and a CSV
 * behave identically in the preview.
 *
 * ── A NOTE LINE IS NOT DATA ─────────────────────────────────────────────────
 * Both templates carry a second line that explains each column, begins with `#`
 * and is skipped here. In a CSV that line is written whole, so it starts with
 * `#`. In a WORKBOOK the same note is a cell, and `sheet_to_csv` wraps a cell
 * that contains a comma, a quote or a line break in double quotes, so the note
 * arrives as `"# ..."` — a hint such as `e.g. 1,25,000.00` is enough. Both
 * spellings are notes. (Until PRE-A-001 the workbook template carried its hints
 * in an unmarked row, so uploading the template as downloaded reported two valid
 * rows: the hint row and a copy of it.)
 */

export interface CsvColumnShape {
  key: string;
  label: string;
  required: boolean;
}

export interface ParsedCsvRow {
  /** The row's number in the file, counted after the header (the preview's own). */
  index: number;
  data: Record<string, string>;
  /** Field-level problems the file itself shows (a required cell that is blank). */
  errors: string[];
}

/** True for a line the reader skips: a note, not data. */
export function isNoteLine(line: string): boolean {
  // The template note is always `# ` (hash, space); the library quotes it as `"# `
  // when a hint holds a comma. A quoted DATA cell that merely begins with a hash
  // (a customer called "#12, MG Road Traders") is a row, not a note.
  return line.startsWith("#") || line.startsWith('"# ');
}

export function parseCsvLine(line: string): string[] {
  const result: string[] = [];
  let cur = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (inQuotes && line[i + 1] === '"') { cur += '"'; i++; }
      else inQuotes = !inQuotes;
    } else if (ch === "," && !inQuotes) {
      result.push(cur.trim());
      cur = "";
    } else {
      cur += ch;
    }
  }
  result.push(cur.trim());
  return result;
}

export function parseCsv(text: string, columns: CsvColumnShape[]): ParsedCsvRow[] {
  // Strip a leading UTF-8 BOM: our own downloadCsvTemplate() now prepends one
  // (so Excel doesn't mangle non-ASCII chars), and Excel's own "CSV UTF-8"
  // Save As does the same — without stripping it, the first header would
  // parse as U+FEFF followed by the key and never match a column.
  const stripped = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
  const lines = stripped.split(/\r?\n/).filter(l => l.trim());
  if (lines.length < 2) return [];

  // First non-note line is the header
  const headerLine = lines.find(l => !isNoteLine(l)) ?? lines[0];
  const headerIdx = lines.indexOf(headerLine);
  const headers = parseCsvLine(headerLine).map(h => h.toLowerCase().trim());

  const rows: ParsedCsvRow[] = [];
  for (let i = headerIdx + 1; i < lines.length; i++) {
    const line = lines[i];
    if (!line.trim() || isNoteLine(line)) continue;
    const values = parseCsvLine(line);
    const data: Record<string, string> = {};
    headers.forEach((h, idx) => { data[h] = values[idx] ?? ""; });

    const errors: string[] = [];
    for (const col of columns) {
      if (col.required && !data[col.key.toLowerCase()]) {
        errors.push(`"${col.label}" is required`);
      }
    }

    rows.push({ index: i - headerIdx, data, errors });
  }
  return rows;
}
