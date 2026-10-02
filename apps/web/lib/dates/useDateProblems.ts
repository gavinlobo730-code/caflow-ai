/**
 * What stops a form saving because a date in it is not a date (frontend_ux-19).
 *
 * A `DateInput` whose text cannot be read hands its parent `""`, which for an
 * OPTIONAL date (a due date, a Form 15CA date) is exactly what a blank box
 * hands up — so a form that saves anyway drops what the person typed, with no
 * word. The parent has to be told the difference and refuse, and this is the
 * smallest thing that tells it: one `watch(key, label)` per field, one
 * `first` to read where the save begins.
 *
 *     const dates = useDateProblems();
 *     <DateInput value={billDate} onChange={setBillDate}
 *                onStateChange={dates.watch("billDate", "Bill date")} />
 *     ...
 *     if (dates.first) { setError(dates.first); return; }
 *
 * It judges only whether text is a calendar date. A period lock, a filed
 * return, a date outside the financial year — those are the server's, and its
 * refusal is shown the way it always was.
 */
import { useCallback, useState } from "react";
import type { DateFieldState } from "./typedDate.ts";

/** The problems map after `state` is reported for `key`: a field that is
 *  `invalid` carries its sentence, anything else carries nothing. Pure, so the
 *  rule is testable without a render. */
export function reportDateState(
  prev: Readonly<Record<string, string>>,
  key: string,
  label: string,
  state: DateFieldState,
): Record<string, string> {
  const next = state.status === "invalid" && state.message ? `${label}: ${state.message}` : null;
  if ((prev[key] ?? null) === next) return prev as Record<string, string>;
  const rest = { ...prev };
  delete rest[key];
  return next === null ? rest : { ...rest, [key]: next };
}

export function useDateProblems() {
  const [problems, setProblems] = useState<Record<string, string>>({});
  /** The `onStateChange` for one field. */
  const watch = useCallback(
    (key: string, label: string) => (state: DateFieldState) =>
      setProblems((prev) => reportDateState(prev, key, label, state)),
    [],
  );
  return {
    watch,
    /** One sentence per unreadable date, `Bill date: Feb 2026 has only 28 days.` */
    problems,
    /** The first of them, or null when every date in the form is a date or blank. */
    first: Object.values(problems)[0] ?? null,
  };
}
