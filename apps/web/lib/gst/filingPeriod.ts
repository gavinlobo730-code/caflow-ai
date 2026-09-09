/**
 * The filing PERIOD a CA picks in the GST tracker: its option list, and the one
 * place its value is taken apart.
 *
 * WHY THIS IS A MODULE AND NOT TWO HELPERS ON A PAGE
 *     The Add GST Filing modal threw a RangeError on every save. The option's
 *     `value` and its `label` were the SAME string — "May 2026" — and two
 *     readers then disagreed about what that string was: the due-date filler
 *     took it apart with `split(" ")` and the save with `split("-")`. The save
 *     got `[NaN, undefined]`, built "NaN-undefined-01", and
 *     `new Date(NaN, NaN, 0).toISOString()` threw, which the surrounding
 *     try/catch turned into an unexplained error message in the modal.
 *
 *     A <select> option already has two fields for exactly this: a machine
 *     value and a human label. So the value is "YYYY-MM", the label is
 *     "MMM YYYY", and there is one parser.
 *
 * WHAT IS NOT HERE
 *     Due dates. CLAUDE.md: services/compliance_engine.py is the single source
 *     for every due date, and there is zero business logic in the frontend.
 *     The page asks GET /api/compliance/due-dates/calculate.
 */
// Relative, not "@/…": this module is pure and must stay importable under
// `node --experimental-strip-types --test`, which does not resolve the alias.
import { todayLocalISO, toLocalISO } from "../dateMath.ts";

export const MONTH_NAMES = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
] as const;

export interface PeriodOption {
  /** "YYYY-MM" — what the code reads. */
  value: string;
  /** "MMM YYYY" — what the CA reads. */
  label: string;
}

/**
 * The last 12 months, oldest first, ending with the month containing `today`.
 *
 * Built from LOCAL calendar components. `new Date()` plus getFullYear/getMonth
 * is local; the earlier form went through todayLocalISO() for the same reason
 * and it is kept — in IST, a UTC-derived "today" is yesterday between midnight
 * and 05:30, which would drop the current month from the list on the 1st.
 */
export function buildMonthOptions(today: Date = new Date(todayLocalISO() + "T00:00:00")): PeriodOption[] {
  const options: PeriodOption[] = [];
  for (let i = 11; i >= 0; i--) {
    const d = new Date(today.getFullYear(), today.getMonth() - i, 1);
    options.push({
      value: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`,
      label: `${MONTH_NAMES[d.getMonth()]} ${d.getFullYear()}`,
    });
  }
  return options;
}

/** "YYYY-MM" -> { year, month } with month 1-12. Null for anything else —
 *  including "May 2026", which is what this used to be handed. */
export function parsePeriodOption(period: string): { year: number; month: number } | null {
  const m = /^(\d{4})-(0[1-9]|1[0-2])$/.exec(period ?? "");
  if (!m) return null;
  return { year: Number(m[1]), month: Number(m[2]) };
}

/** The first and last calendar dates of a period, as YYYY-MM-DD.
 *
 *  The month end is `new Date(year, month, 0)` — day zero of the FOLLOWING
 *  month, which JavaScript resolves to the last day of this one, leap years
 *  included — read back with toLocalISO. It used to be read back with
 *  `.toISOString().slice(0, 10)`, which converts a local midnight through UTC
 *  and in IST lands at 18:30 on the previous day: every period ended a day
 *  early, on the rows that drive the filing tracker. */
export function periodBounds(period: string): { start: string; end: string } | null {
  const p = parsePeriodOption(period);
  if (!p) return null;
  return {
    start: `${p.year}-${String(p.month).padStart(2, "0")}-01`,
    end: toLocalISO(new Date(p.year, p.month, 0)),
  };
}
