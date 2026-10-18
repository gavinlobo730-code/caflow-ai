/**
 * The bound an imported GST % cell is asked in the preview (POST-A-214).
 *
 * The SERVER is the authority: `domain/gst/rate_bounds.py` refuses a rate outside 0 to 100 per cent on every line model
 * (SALES-35), because a figure typed in basis points ("1800" for 18%) is a plausible-looking number that would charge a
 * hundredfold. An importer that only refused a NEGATIVE cell let that row through the preview as ready, and the server
 * refused it later with its own sentence. This asks the same question where the CA is looking at the preview, so the row
 * is named before the file is posted. It holds the number, not a rule of its own: `tests/test_a_gst_rate_a_ca_typed_is_
 * bounded.py` reads this file and fails the day the two disagree.
 */
export const MAX_GST_RATE_BPS = 10000;

/**
 * Why a typed GST % (already converted to basis points, or NaN for an unreadable cell) is not a rate, or null when it is.
 * `rowNo` is the spreadsheet row, so the sentence can say which one.
 */
export function gstRateCellProblem(bps: number, rowNo: number, raw: string): string | null {
  if (!Number.isFinite(bps) || bps < 0) {
    return `Row ${rowNo}: GST % must be a non-negative number (or give a Product/Service with a default rate)`;
  }
  if (bps > MAX_GST_RATE_BPS) {
    return `Row ${rowNo}: GST % "${raw}" is more than 100 — type the percentage (18 for 18%), not basis points (1800)`;
  }
  return null;
}
