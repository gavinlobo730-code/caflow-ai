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
 *     if (dates.first) { dates.refuseWith(setError); return; }
 *
 * `refuseWith` says the first problem through the form's own message and TAKES IT BACK the moment that problem is gone (POST-A-381):
 * the form copied the sentence into its error, where it stayed after the date was put right, so a person who had fixed the date was
 * still shown the red sentence and pressed Save again for nothing. What it said is compared by identity, so a later answer the form
 * shows in the same place (the server's refusal) is never taken back. `scripts/a-date-sentence-is-taken-back-when-the-date-is-right.test.ts`
 * fails a form that copies a date hook's sentence into a setter itself.
 *
 * It judges only whether text is a calendar date. A period lock, a filed
 * return, a date outside the financial year — those are the server's, and its
 * refusal is shown the way it always was.
 */
import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from "react";
import type { DateFieldState, DateStateListener } from "./typedDate.ts";

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

/** What `refuseWith` said, and how to take it back. */
interface Said {
  sentence: string;
  takeBack: () => void;
}

/** The entries of `said` whose sentence is no longer a problem are taken back and dropped; the rest are kept. Pure but for the calls,
 *  so the rule is testable without a render. */
export function takeBackFixed(said: readonly Said[], problems: Readonly<Record<string, string>>): Said[] {
  const current = new Set(Object.values(problems));
  return said.filter((s) => {
    if (current.has(s.sentence)) return true;
    s.takeBack();
    return false;
  });
}

export function useDateProblems() {
  const [problems, setProblems] = useState<Record<string, string>>({});
  const first = Object.values(problems)[0] ?? null;
  const firstRef = useRef<string | null>(first);
  firstRef.current = first;
  const said = useRef<Said[]>([]);
  useEffect(() => {
    if (said.current.length) said.current = takeBackFixed(said.current, problems);
  }, [problems]);
  /**
   * Say the first problem through a form's own message, and take it back when that problem is gone. `wrap` builds the message from
   * the sentence (`(text) => ({ type: "err", text })`) and `empty` is what the message holds when there is none (null unless given).
   * It does nothing when no date is wrong.
   */
  const refuseWith = useCallback(<T,>(set: Dispatch<SetStateAction<T>>, wrap?: (sentence: string) => NoInfer<T>, empty?: NoInfer<T>) => {
    const sentence = firstRef.current;
    if (!sentence) return;
    const value = wrap ? wrap(sentence) : (sentence as unknown as T);
    const cleared = (empty === undefined ? null : empty) as T;
    set(value);
    said.current.push({ sentence, takeBack: () => set((prev) => (Object.is(prev, value) ? cleared : prev)) });
  }, []);
  /** The `onStateChange` for one field. A field that refuses a later day says so on the listener (see `refusesAfterMax`). */
  const watch = useCallback(
    (key: string, label: string, refuse?: DateRefusals): DateStateListener => {
      const listener: DateStateListener = (state: DateFieldState) =>
        setProblems((prev) => reportDateState(prev, key, label, state, refuse));
      if (refuse?.afterMax === true) listener.refusesAfterMax = true;
      return listener;
    },
    [],
  );
  return {
    watch,
    /** One sentence per unreadable date, `Bill date: Feb 2026 has only 28 days.` */
    problems,
    /** The first of them, or null when every date in the form is a date or blank. */
    first,
    refuseWith,
  };
}

/**
 * Take back a sentence a form said about its own dates (an end before its start) the moment it stops being true: the form's error is cleared
 * by its next attempt and nothing else, so a window put right still said it was wrong (POST-A-381). `said` is compared by identity, so an
 * answer the form showed afterwards is never taken back.
 *
 *     const ORDER = "The end date cannot be before the start date.";
 *     useTakenBackWhenFixed(setErr, ORDER, !!endDate && endDate < startDate);
 */
export function useTakenBackWhenFixed<T>(set: Dispatch<SetStateAction<T>>, said: NoInfer<T>, stillTrue: boolean, empty: NoInfer<T> = null as NoInfer<T>) {
  useEffect(() => {
    if (!stillTrue) set((prev) => (Object.is(prev, said) ? empty : prev));
  }, [set, said, stillTrue, empty]);
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
