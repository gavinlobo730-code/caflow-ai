/**
 * The windows the practice's analytics screens can be asked for (POST-A-427).
 *
 * The screen used to offer this week, this month and this quarter to date, each ending today, so last financial year's
 * figures could not be opened at all and the seeded FY 2025-26 firm showed an empty screen from 1 April 2026. A window
 * is now also one whole financial year, which the server resolves (`routers/analytics._period_range`, from `fy_bounds`);
 * this module only names the choices and turns the one a person picked into the two query values the server reads.
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

export interface AnalyticsWindowChoice {
  /** The select's value: `week`, `month`, `quarter` or `fy:<label>`. */
  id: string;
  label: string;
}

const FY_PREFIX = "fy:";

/** The choices, the years newest first: the first is the year that is running. */
export function analyticsWindowChoices(years: readonly string[]): AnalyticsWindowChoice[] {
  return [
    { id: "month", label: "This month" },
    { id: "quarter", label: "This quarter" },
    { id: "week", label: "This week" },
    ...years.map((fy, i) => ({
      id: `${FY_PREFIX}${fy}`,
      label: i === 0 ? `This financial year (${fy}), to date` : `Financial year ${fy}`,
    })),
  ];
}

/** The two query values for a picked choice. An id this module did not offer is the month, the screen's own default. */
export function analyticsWindowOf(id: string): AnalyticsWindow {
  if (id.startsWith(FY_PREFIX)) return { period: "fy", financialYear: id.slice(FY_PREFIX.length) };
  if (id === "week" || id === "quarter" || id === "month") return { period: id };
  return { period: "month" };
}
