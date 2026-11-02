"use client";

/**
 * The financial year of the year-end engagement being worked on, for the stages that ask for a date inside it (POST-A-126).
 *
 * A short date typed in a date box (a bare `15/3`) is read inside a financial year. A box that is not told which one reads it against the
 * year of today, so an adjustment typed into a 2024-25 engagement in 2026 came out as March 2026, a different year of the books. The
 * workspace loads the engagement; this hands its year to the stages, which pass it to the field as `financialYear`.
 */
import { createContext, useContext } from "react";

const EngagementYearContext = createContext<string | undefined>(undefined);

export const EngagementYearProvider = EngagementYearContext.Provider;

/** The engagement's financial year (`2024-25`), or undefined while it is not known. */
export function useEngagementFinancialYear(): string | undefined {
  return useContext(EngagementYearContext);
}
