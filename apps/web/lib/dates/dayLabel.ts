/**
 * A calendar DATE as a label: "2026-08-22" -> "22 Aug 2026".
 *
 * Done by splitting the string, never through `new Date(...)`: a date-only string
 * handed to the Date constructor is UTC midnight, which is the previous evening
 * in any time zone west of Greenwich, so a due date of the 22nd would be shown as
 * the 21st. `lib/dates/formatIst` is the sibling for an INSTANT (a timestamp);
 * this is for a date that has no time in it.
 *
 * Anything that is not a date reads "—" rather than "Invalid Date".
 */
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function dayLabel(iso: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? "");
  if (!m) return "—";
  const month = MONTHS[Number(m[2]) - 1];
  return month ? `${m[3]} ${month} ${m[1]}` : "—";
}
