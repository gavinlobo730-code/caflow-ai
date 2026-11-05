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
import { useCallback, useEffect, useState } from "react";
import type { DateFieldState } from "./typedDate.ts";

/** What a box refuses beyond text that is not a date. */
export interface DateRefusals {
  /** A date after the box's `max` is refused too (the hint's own sentence is the refusal's). */
  afterMax?: boolean;
}

/** The problems map after `state` is reported for `key`: a field that is
 *  `invalid` carries its sentence, anything else carries nothing. Pure, so the
 *  rule is testable without a render. */
export function reportDateState(
  prev: Readonly<Record<string, string>>,
  key: string,
  label: string,
  state: DateFieldState,
  refuse: DateRefusals = {},
): Record<string, string> {
  // A date typed in full that is past the box's `max` is `valid` and carries a hint sentence (`outOfRange`): the box hands it up, as a native input
  // does. A box whose date can never be later than today (the day a return was filed) says `{ afterMax: true }`, and the hint becomes a refusal.
  const refused = refuse.afterMax === true && state.status === "valid" && state.outOfRange === "max" && !!state.message;
  const next = (state.status === "invalid" || refused) && state.message ? `${label}: ${state.message}` : null;
  if ((prev[key] ?? null) === next) return prev as Record<string, string>;
  const rest = { ...prev };
  delete rest[key];
  return next === null ? rest : { ...rest, [key]: next };
}

export function useDateProblems() {
  const [problems, setProblems] = useState<Record<string, string>>({});
  /** The `onStateChange` for one field. */
  const watch = useCallback(
    (key: string, label: string, refuse?: DateRefusals) => (state: DateFieldState) =>
      setProblems((prev) => reportDateState(prev, key, label, state, refuse)),
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

/**
 * A sentence for a screen that has nowhere of its own to say a date is wrong (a modal or drawer over a page whose message line is behind
 * the overlay): shown once a save has been TRIED, and withdrawn the moment the date is right.
 *
 *     const dates = useDateProblems();
 *     const refusal = useDateRefusal(dates.first);
 *     ...  if (dates.first) { refusal.refuse(); return; }
 *     ...  {refusal.shown && <p role="alert">{refusal.shown}</p>}
 *
 * It is a latch that RESETS, because a latch that lingered would speak the sentence at every keystroke of the retype (`15/`, `15/0`,
 * `15/07/` are all unreadable on the way to a date) and the box itself deliberately stays quiet until it is left. `clear()` is for opening
 * the form afresh.
 *
 * What is passed in may be any sentence that is a PURE FUNCTION of what the boxes hold, not only a box's own: two dates that must be in
 * order (`dates.first ?? orderProblem`), a date that must be given (`dates.first ?? missing`). Such a sentence is true only while the
 * condition holds, so it is derived and latched here and never copied into the form's error, where it stayed after the cause was fixed.
 * A sentence that ANSWERS an attempt (the server's refusal, an amount that is not an amount) is the form's error and is cleared by the next
 * attempt.
 *
 * `refuse` and `clear` keep their identity from one render to the next, so an effect that opens a form afresh can name `refusal.clear` in
 * its dependencies without running again on every render.
 */
export function useDateRefusal(first: string | null) {
  const [tried, setTried] = useState(false);
  useEffect(() => {
    if (!first) setTried(false);
  }, [first]);
  /** A save was tried over a date that is wrong. */
  const refuse = useCallback(() => setTried(true), []);
  /** The form is opened afresh. */
  const clear = useCallback(() => setTried(false), []);
  return {
    /** The sentence to show now, or null. */
    shown: tried ? first : null,
    refuse,
    clear,
  };
}
