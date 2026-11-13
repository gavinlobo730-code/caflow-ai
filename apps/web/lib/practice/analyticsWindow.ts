/**
 * The windows the practice's analytics screens can be asked for (POST-A-427).
 *
 * The screen used to offer this week, this month and this quarter to date, each ending today, so last financial year's
 * figures could not be opened at all and the seeded FY 2025-26 firm showed an empty screen from 1 April 2026. A window
 * is now also one whole financial year, which the server resolves (`routers/analytics._period_range`, from `fy_bounds`), or any two days
 * (`period=custom`, `date_from` and `date_to`); this module only names the choices and turns the one a person picked into the query
 * values the server reads.
 *
 * PURE, AND WITH NO IMPORT BUT A TYPE, so a test can run it as it is. THE YEARS ARE GIVEN TO IT, derived from the clock
 * by the caller (`financialYearChoices` in `lib/dates/periods`, called with India's day, because the server decides which
 * year is running by India's day and a browser in another zone is on another day for five and a half hours or more
 * around 1 April): a list typed in goes stale on 1 April and ends at a year already past. Nothing here decides which days
 * a year has, what is in a window or what a figure is: the server does, and says it in `period`.
 */
import type { AnalyticsWindow } from "@/lib/api";

/** How many financial years the picker offers: the running one and the two before it. */
export const ANALYTICS_FY_COUNT = 3;

/** The picker's last choice: any two days (a half year, a quarter of last year, the month before last). It is asked for only once the
 *  screen holds both days, and the server refuses what it cannot answer (POST-A-427). */
export const CUSTOM_WINDOW_ID = "custom";

/** The two days of a custom window, `YYYY-MM-DD` each, or `""` for a box that holds no readable day. */
export interface CustomDays {
  from: string;
  to: string;
}

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

export interface AnalyticsWindowChoice {
  /** The select's value: `week`, `month`, `quarter`, `fy:<label>` or `custom`. */
  id: string;
  label: string;
}

const FY_PREFIX = "fy:";

/** The choices, the years newest first: the first is the year that is running; "a range of days" comes last. */
export function analyticsWindowChoices(years: readonly string[]): AnalyticsWindowChoice[] {
  return [
    { id: "month", label: "This month" },
    { id: "quarter", label: "This quarter" },
    { id: "week", label: "This week" },
    ...years.map((fy, i) => ({
      id: `${FY_PREFIX}${fy}`,
      label: i === 0 ? `This financial year (${fy}), to date` : `Financial year ${fy}`,
    })),
    { id: CUSTOM_WINDOW_ID, label: "A range of days…" },
  ];
}

/**
 * What stops a custom window from being asked for yet, in a sentence, or `null` when the two days can be asked for. The screen shows the
 * sentence in place of the figures and makes no request, so a window that cannot exist is never answered ("nothing was billed") as if it
 * did. This is the screen's courtesy and not the rule: the server refuses the same windows in words of its own (a start after the end, an end
 * after today in India, either day missing) and is what holds. `today` is India's day, given by the caller.
 */
export function customWindowProblem(from: string, to: string, today: string): string | null {
  // A text that is not a day is no day, here as in `analyticsWindowOf`: the two helpers must agree on what a day is.
  const haveFrom = ISO_DAY.test(from);
  const haveTo = ISO_DAY.test(to);
  if (!haveFrom && !haveTo) return "Choose the first and the last day of the window to see its figures.";
  if (!haveFrom) return "Choose the first day of the window.";
  if (!haveTo) return "Choose the last day of the window.";
  if (to < from) return "The To day is before the From day, so there is nothing to show. Put the two days in order.";
  if (to > today) return "The To day is after today in India. Nothing has happened after today, so choose today or an earlier day.";
  return null;
}

/** The query values for a picked choice. An id this module did not offer is the month, the screen's own default, and so is a custom
 *  window that was not given two readable days: a guess at a day is never made. */
export function analyticsWindowOf(id: string, days?: CustomDays): AnalyticsWindow {
  if (id === CUSTOM_WINDOW_ID) {
    return days && ISO_DAY.test(days.from) && ISO_DAY.test(days.to)
      ? { period: "custom", dateFrom: days.from, dateTo: days.to }
      : { period: "month" };
  }
  if (id.startsWith(FY_PREFIX)) return { period: "fy", financialYear: id.slice(FY_PREFIX.length) };
  if (id === "week" || id === "quarter" || id === "month") return { period: id };
  return { period: "month" };
}
