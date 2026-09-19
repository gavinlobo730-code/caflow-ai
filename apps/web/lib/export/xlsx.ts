/**
 * A money cell in a spreadsheet is a NUMBER.
 *
 * ── THE DEFECT ──────────────────────────────────────────────────────────────
 * Every browser export built its money as a string:
 *
 *     "Budget (₹)": (r.budget_paise / 100).toFixed(2)
 *
 * `json_to_sheet` types a cell from the JavaScript value, so a string becomes
 * `t: "s"` — a TEXT cell. Excel's `=SUM()` skips text, so a CA who selects the
 * amount column of an exported trial balance and asks for a total gets **0**,
 * with nothing to explain why: SheetJS writes no `ignoredErrors`, so the little
 * green "number stored as text" triangle that would at least hint at it never
 * appears either.
 *
 * That is a correctness defect on an output that LEAVES THE BUILDING. The
 * figures are right; the file cannot be used as a spreadsheet.
 *
 * ── THE RULES ───────────────────────────────────────────────────────────────
 * **THE VALUE IS RUPEES AS A NUMBER, THE FORMAT IS THE FILE'S.** `paise / 100`
 * is exact for every figure this product holds: paise are integers and an IEEE
 * double carries 2^53, which is ₹90,07,19,92,54,740.99 — larger than any
 * balance a practice will meet. Nothing is rounded here; a value is written
 * once and Excel is told how to DISPLAY it.
 *
 * **INDIAN GROUPING IN THE FORMAT STRING** (D6). Excel has no locale-free way
 * to say "Indian grouping", so it is spelled as the three-condition format the
 * Indian Excel community uses: above a crore, above a lakh, and below.
 * `[>=10000000]##\,##\,##\,##0.00;[>=100000]##\,##\,##0.00;##,##0.00` — the
 * escaped commas are literal separators, the unescaped one is the grouping.
 *
 * **A FIGURE NOBODY HOLDS IS AN EMPTY CELL, NOT A ZERO.** `null` writes
 * nothing. The distinction is load-bearing everywhere else in this product —
 * a nil that means "we cannot see this" is not a nil that means "there was
 * none" — and a spreadsheet is exactly where a reader adds the column up.
 *
 * **THE HEADER ROW FREEZES AND THE COLUMNS ARE WIDE ENOUGH.** A statement
 * whose account names are clipped to eight characters is not a statement.
 */
import type { WorkBook, WorkSheet } from "xlsx";

/** Excel's number format for Indian grouping with two decimals. */
export const INR_FORMAT =
  '[>=10000000]##\\,##\\,##\\,##0.00;[>=100000]##\\,##\\,##0.00;##,##0.00';

/** A money value for a sheet cell: rupees as a NUMBER, or null for no figure.
 *
 *  Takes integer paise — the unit money crosses the API in — so no caller has
 *  to remember the divisor, and so the one place it happens is here. */
export function moneyCell(paise: number | string | null | undefined): number | null {
  if (paise === null || paise === undefined) return null;
  const n = typeof paise === "number" ? paise : Number(String(paise).trim());
  if (!Number.isFinite(n)) return null;
  return n / 100;
}

export interface SheetSpec {
  /** The rows, already keyed by their column headers. */
  rows: Record<string, unknown>[];
  /** Which headers hold money. Those cells get `INR_FORMAT` and are right-aligned
   *  by Excel because they are numbers. */
  moneyColumns: string[];
  sheetName: string;
}

/**
 * Build a workbook whose money columns are numbers Excel can add up.
 *
 * `XLSX` is passed in rather than imported: every caller already
 * `await import("xlsx")`s it lazily so the parser is not in the first load,
 * and importing it here would undo that on every screen that exports.
 */
export function buildWorkbook(
  XLSX: typeof import("xlsx"),
  specs: SheetSpec | SheetSpec[],
): WorkBook {
  const wb = XLSX.utils.book_new();
  for (const spec of Array.isArray(specs) ? specs : [specs]) {
    const ws: WorkSheet = XLSX.utils.json_to_sheet(spec.rows);
    const headers = Object.keys(spec.rows[0] ?? {});
    const money = new Set(spec.moneyColumns);

    // Stamp the format on every money cell. The column index comes from the
    // header row rather than from the order `moneyColumns` was given in, so a
    // caller cannot silently format the wrong column by listing them wrong.
    const range = XLSX.utils.decode_range(ws["!ref"] ?? "A1");
    for (let c = range.s.c; c <= range.e.c; c++) {
      if (!money.has(headers[c])) continue;
      for (let r = range.s.r + 1; r <= range.e.r; r++) {
        const cell = ws[XLSX.utils.encode_cell({ r, c })];
        if (cell && cell.t === "n") cell.z = INR_FORMAT;
      }
    }

    // Column widths from the longest value, bounded — an account name is long
    // and a date is not, and one width for both wastes half the page.
    ws["!cols"] = headers.map((h) => {
      const longest = spec.rows.reduce((w, row) => {
        const v = row[h];
        return Math.max(w, v === null || v === undefined ? 0 : String(v).length);
      }, h.length);
      return { wch: Math.min(Math.max(longest + 2, 10), 42) };
    });
    ws["!freeze"] = { xSplit: "0", ySplit: "1", topLeftCell: "A2", activePane: "bottomLeft" };

    XLSX.utils.book_append_sheet(wb, ws, spec.sheetName.slice(0, 31));
  }
  return wb;
}
