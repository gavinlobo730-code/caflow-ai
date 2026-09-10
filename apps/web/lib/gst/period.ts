/**
 * A GST return period, as GSTN spells it.
 *
 * MMYYYY — "062026" is June 2026. Not YYYY-MM, which is what payroll runs and
 * every other month in this product use, and the two are easy to transpose:
 * "202606" is a well-formed six-digit string that GSTN reads as month 20.
 * Hence the month-range check rather than a bare `^\d{6}$`.
 */

const MONTHS = [
  "", "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

export function isGstPeriod(value: string | null | undefined): boolean {
  const v = String(value ?? "");
  if (!/^\d{6}$/.test(v)) return false;
  const month = Number(v.slice(0, 2));
  return month >= 1 && month <= 12;
}

/** "062026" -> "June 2026". Anything unparseable comes back unchanged, so a
 *  malformed period is visible as itself rather than as a wrong month. */
export function gstPeriodLabel(value: string | null | undefined): string {
  const v = String(value ?? "");
  if (!isGstPeriod(v)) return v;
  return `${MONTHS[Number(v.slice(0, 2))]} ${v.slice(2)}`;
}

/** The financial year a GST period falls in — April to March. */
export function gstPeriodFinancialYear(value: string | null | undefined): string | null {
  const v = String(value ?? "");
  if (!isGstPeriod(v)) return null;
  const month = Number(v.slice(0, 2));
  const year = Number(v.slice(2));
  const start = month >= 4 ? year : year - 1;
  return `${start}-${String(start + 1).slice(-2)}`;
}
