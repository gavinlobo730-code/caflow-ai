/**
 * One CSV writer, because the escaping was reimplemented thirteen times and
 * two of the copies were wrong.
 *
 * ── THE DEFECT ─────────────────────────────────────────────────────────────
 * Measured 19 September 2026. Thirteen files built a CSV; seven of them
 * escaped by hand and two of those got it wrong in ways that corrupt the file
 * silently:
 *
 *   app/risks/page.tsx
 *     [r.clientName, r.riskType, `"${r.description}"`, ...].join(",")
 *     The client name and the risk type are not quoted AT ALL. A client called
 *     "Sharma, Gupta & Co" puts a raw comma in the field and every column
 *     after it shifts by one — for that row only, so the file opens, looks
 *     plausible, and has one line of data under the wrong headings.
 *
 *   app/accounting/receivables/page.tsx
 *     row.map(v => `"${v}"`).join(",")
 *     Wraps in quotes and does not double the internal ones, so a narration
 *     carrying a quote ends the field early and every parser disagrees about
 *     where the row ends.
 *
 * The rule was already written and already right — `csvCell` in
 * `lib/table/process.ts`, quoting only when needed and doubling internal
 * quotes — and it was module-private, so the next author who needed it wrote
 * their own. That is the whole mechanism: a correct implementation nobody can
 * reach is the reason there are seven incorrect ones.
 *
 * ── WHAT THIS DECIDES ──────────────────────────────────────────────────────
 * **Quote only when needed**, matching the incumbent rather than quoting every
 * field. Quoting everything is equally valid under RFC 4180 and would rewrite
 * the bytes of every export this product already produces, for no gain to any
 * reader.
 *
 * **Records are separated by LF**, again matching the incumbent. RFC 4180 says
 * CRLF; every consumer this product has — Excel, Numbers, Sheets, Python's
 * `csv` — reads LF, and a newline INSIDE a field is disambiguated by the
 * quotes rather than by the separator, so nothing depends on it. One line to
 * change if a consumer ever turns out to need CRLF.
 *
 * **The BOM belongs to the FILE, not the text.** `downloadCsv` prepends it;
 * `toCsvRows` returns bare text. Without a BOM Excel sniffs Windows-1252 and
 * renders ₹ as "â‚¹" — but a caller posting the text to an API must not send
 * the BOM, and putting it in the string is how that goes wrong.
 *
 * **Null is an EMPTY field, never "null"**, and a number goes out bare — no
 * grouping, no currency mark — because a CSV cell exists to be parsed. That is
 * the same decision `lib/export/xlsx.ts` takes for the same reason, and it is
 * why the two cannot share a formatter: the workbook wants a number carrying
 * an Indian FORMAT, and a CSV wants the digits.
 */

/** One field, escaped per RFC 4180. */
export function csvField(value: unknown): string {
  if (value === null || value === undefined) return "";
  const s = String(value);
  // A leading or trailing space is quoted too, which `csvCell` did not do: an
  // unquoted one is ambiguous and several parsers drop it, so the FILE should
  // say the space was there. Our own importer trims regardless — that is
  // `CsvImportModal.parseCsvLine`'s own choice about user-supplied files, and
  // it is not a reason for the writer to lose the byte on the way out.
  return /[",\r\n]/.test(s) || s !== s.trim() ? `"${s.replace(/"/g, '""')}"` : s;
}

/** A whole file: rows of already-ordered cells, header row included by the caller. */
export function toCsvRows(rows: ReadonlyArray<ReadonlyArray<unknown>>): string {
  return rows.map((r) => r.map(csvField).join(",")).join("\n");
}

/**
 * Hand the browser a .csv file.
 *
 * The argument order is (filename, csv) and there is exactly one of these.
 * `app/payroll/reports/page.tsx` used to declare a private
 * `downloadCsv(content, filename)` — the same name with the arguments the
 * other way round — so a screen importing the shared one and calling it by
 * the local habit would have written a file named after its own contents.
 */
export function downloadCsv(filename: string, csv: string): void {
  // The BOM makes Excel auto-detect UTF-8; without it ₹ (U+20B9) and Indian
  // names are sniffed as Windows-1252 and mangled.
  const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  // The extension is added when the caller forgot it. Kept from the
  // DataTable's own copy, which several call sites rely on — dropping it
  // while merging the two would download "clients" with no suffix.
  a.download = filename.endsWith(".csv") ? filename : `${filename}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}
