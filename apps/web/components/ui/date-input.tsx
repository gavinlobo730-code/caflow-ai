"use client";

/**
 * DateInput — the one field a person TYPES a date into (frontend_ux-19).
 *
 * It shows and accepts dd/mm/yyyy (and dd-mm-yyyy, dd.mm.yyyy, ddmmyyyy,
 * ddmmyy), expands a bare day or a day and month inside the financial year the
 * way Tally does, says in a sentence what is wrong with a date that is not one,
 * and STORES ISO `YYYY-MM-DD` — the very string `<input type="date">` puts in
 * `.value`, so converting a field is replacing the tag, and the unsent-draft,
 * dirty-field and single-flight code that read that string keep working. The
 * reading rule is `lib/dates/typedDate.ts` and this file wires it; nothing here
 * decides what a date is.
 *
 * ── THE CONTRACT WITH A PARENT ──────────────────────────────────────────────
 *
 *   `onChange(iso, state)` hands up the ISO date, or `""`, WHEN THE FIELD
 *   COMMITS: on blur, on Enter and on an arrow key — not on every keystroke.
 *   Typing `15/07/2026` passes through `1`, `15`, `15/`, `15/0`, `15/07` and
 *   `15/07/20` on the way, and four of those are real dates (the 1st, the 15th,
 *   15 July and 15 July **2020**). A native date input emits only when a segment
 *   is complete; this one emits only when the person has finished, because every
 *   parent that does something when a date changes — an invoice that re-works
 *   its due date and asks the server for the next number in a financial year,
 *   a list that refetches — would otherwise do it for each of them. A parent that
 *   saves on a button gets the committed value anyway: pressing the button moves
 *   focus off the box first, which is a blur.
 *
 *   `""` means TWO things — nothing typed, or text that is not a date — and
 *   `state.status` (`empty` | `valid` | `invalid`) is what tells them apart. An
 *   invalid field hands up `""` and never the date it held before: handing up
 *   the stale one would save a date the person has already typed over.
 *
 *   `onStateChange(state)` is the LIVE half: it fires on every keystroke and on
 *   every change of what the box holds, INCLUDING one the parent caused (a
 *   restored draft, a reset). It is the one to feed `useDateProblems`, because a
 *   save has to be refused while the box holds unreadable text even though the
 *   value has not been committed yet, and the parent that restores a draft over
 *   an invalid box has to be told the box is no longer invalid.
 *
 *   Controlled, and tolerant of being so: while the text is unreadable the
 *   parent's `value` is `""`, and that must not wipe what the person is in the
 *   middle of typing — the field knows which value it last handed up, and a
 *   `value` that is not that one is somebody else's and replaces the text. A
 *   blur that changes nothing hands up nothing, so tabbing through a date does
 *   not re-run the parent's `onChange` (an invoice would re-derive a due date
 *   somebody set by hand).
 *
 * ── WHEN IT SPEAKS ──────────────────────────────────────────────────────────
 *
 *   An error is shown when the box loses focus (or Enter is pressed), never
 *   while the person is still typing `15/0` on the way to `15/07`. A valid date
 *   is rewritten as the full dd/mm/yyyy at that moment, so the person sees what
 *   was understood: `150326` becomes 15/03/2026, and `15` in a July document
 *   becomes 15/07/2026.
 *
 *   ArrowUp and ArrowDown add and subtract a day (and commit). An empty box takes
 *   the anchor's day on either key, as a native date input takes today.
 *
 * ── THE ANCHOR ──────────────────────────────────────────────────────────────
 *
 *   A bare day needs a month. `anchor` names it (`YYYY-MM-DD` or `YYYY-MM`);
 *   absent, it is the box's own value at the moment it took focus, so a bare
 *   `20` in a document dated 10 July is 20 July; and with no value either, today
 *   in IST. It is FROZEN at focus so the date being typed does not move its own
 *   month under the typist. `financialYear` names the year inside which the
 *   month and day are resolved; absent, it is the financial year of the anchor.
 *
 * ── WHAT IT DOES NOT DO ─────────────────────────────────────────────────────
 *
 *   It does not know a period is locked or a return filed. Those are the
 *   server's and a refusal is shown exactly as before. `min`/`max` are an input
 *   hint: a date outside them is reported (`outOfRange`, and a sentence) and is
 *   STILL handed up, as a native input does.
 *
 *   It has no calendar popup. A button beside the box that opens the browser's
 *   picker needs a hidden native date input, which is the thing this component
 *   exists to replace and would have to be an exception in
 *   `scripts/a-date-a-person-types-goes-through-one-field.test.ts` for ever; the
 *   keyboard path is the point. Adding one is a decision, not an accident.
 *
 *   It does not reset itself when a parent sets `value` to `""` while the box
 *   holds unreadable text the parent was already told about — `""` is what the
 *   box last handed up, so nothing differs. A parent that wants a reset remounts
 *   the field with a `key`.
 */
import * as React from "react";
import { cn } from "@/lib/utils";
import {
  TYPED_DATE_PLACEHOLDER,
  dateFieldState,
  isoFromRead,
  parseTypedDate,
  stepTypedDate,
  typedDateText,
  type DateFieldState,
  type TypedDate,
  type TypedDateContext,
} from "@/lib/dates/typedDate";

export type { DateFieldState } from "@/lib/dates/typedDate";

/** The default look. A parent's `className` is merged over it, so a field keeps
 *  the size and colours its screen already gave it; what it cannot lose is the
 *  focus ring (frontend_ux-28: an outline is never removed with nothing drawn in
 *  its place). */
const LOOK =
  "rounded-lg border border-ps-border bg-white px-3 py-1.5 text-sm text-ps-ink " +
  "placeholder:text-ps-hint focus:outline-none focus:ring-2 focus:ring-brand";

/** An unreadable date: the border and the ring both say so, and `aria-invalid`
 *  says it to a reader who cannot see either. */
const PROBLEM_LOOK = "border-state-problem focus:ring-state-problem";

export interface DateInputProps
  extends Omit<
    React.InputHTMLAttributes<HTMLInputElement>,
    "value" | "defaultValue" | "onChange" | "type" | "min" | "max" | "inputMode"
  > {
  /** `YYYY-MM-DD`, or `""`. The value contract of `<input type="date">`. */
  value: string;
  onChange: (iso: string, state: DateFieldState) => void;
  onStateChange?: (state: DateFieldState) => void;
  /** `YYYY-YY`. See the header. */
  financialYear?: string | null;
  /** `YYYY-MM-DD` or `YYYY-MM`. See the header. */
  anchor?: string | null;
  /** `YYYY-MM-DD` bounds, an input hint only. */
  min?: string;
  max?: string;
  /** Marks the box invalid for a reason the PARENT knows (the server refused the
   *  date). The field's own unreadable-text state needs no help. */
  invalid?: boolean;
  /** Classes for the element around the box and its message. */
  wrapperClassName?: string;
}

/**
 * The markup, apart from the state — so the accessibility wiring can be
 * rendered and read without a browser. Both elements around the box are SPANS
 * made blocks, not a div and a paragraph: a field is dropped into a `<label>`
 * wrapper in a dozen drawers, and phrasing content is the only kind a label may
 * hold. `problem` is the sentence to show NOW
 * (the field decides when), `tone` what kind of problem it is.
 */
export interface DateFieldViewProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "type" | "inputMode" | "value"> {
  inputId: string;
  text: string;
  problem: string | null;
  tone: "problem" | "hint";
  invalid?: boolean;
  wrapperClassName?: string;
}

export const DateFieldView = React.forwardRef<HTMLInputElement, DateFieldViewProps>(
  function DateFieldView(
    { inputId, text, problem, tone, invalid, wrapperClassName, className, placeholder,
      "aria-describedby": describedByProp, ...rest },
    ref,
  ) {
    const messageId = `${inputId}-msg`;
    const bad = (problem !== null && tone === "problem") || !!invalid;
    const describedBy = [describedByProp, problem !== null ? messageId : null]
      .filter(Boolean)
      .join(" ");
    return (
      <span className={cn("block min-w-0", wrapperClassName)}>
        <input
          {...rest}
          ref={ref}
          id={inputId}
          type="text"
          inputMode="numeric"
          autoComplete="off"
          spellCheck={false}
          placeholder={placeholder ?? TYPED_DATE_PLACEHOLDER}
          value={text}
          aria-invalid={bad ? true : undefined}
          aria-describedby={describedBy || undefined}
          className={cn(LOOK, className, bad && PROBLEM_LOOK)}
        />
        {problem !== null && (
          <span
            id={messageId}
            role="alert"
            className={cn("mt-1 block text-2xs", tone === "problem" ? "text-state-problem" : "text-state-attention")}
          >
            {problem}
          </span>
        )}
      </span>
    );
  },
);

interface Box {
  text: string;
  read: TypedDate;
}

function boxFor(value: string, min?: string, max?: string): Box {
  const text = typedDateText(value);
  return { text, read: parseTypedDate(text, { min, max }) };
}

export const DateInput = React.forwardRef<HTMLInputElement, DateInputProps>(
  function DateInput(
    { value, onChange, onStateChange, financialYear, anchor, min, max, invalid, wrapperClassName,
      id, onFocus, onBlur, onKeyDown, disabled, readOnly, ...rest },
    ref,
  ) {
    const generated = React.useId();
    const inputId = id ?? `date-${generated.replace(/:/g, "")}`;
    const [box, setBox] = React.useState<Box>(() => boxFor(value, min, max));
    const [focused, setFocused] = React.useState(false);
    const [touched, setTouched] = React.useState(false);
    // The value this field last handed up. A `value` that differs is the
    // parent's own and replaces the text; one that matches is our own echo.
    const handedUp = React.useRef(value);
    const anchorAtFocus = React.useRef<string | null>(null);
    // The parent's latest callback, so a new function every render re-runs nothing.
    const stateCallback = React.useRef(onStateChange);
    stateCallback.current = onStateChange;

    React.useEffect(() => {
      if (value === handedUp.current) return;
      handedUp.current = value;
      const next = boxFor(value, min, max);
      setBox(next);
      setTouched(false);
      stateCallback.current?.(dateFieldState(next.text, next.read));
      // `min`/`max` only colour the hint; a change of either is not a new value.
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [value]);

    // A field that goes away (a section the form hides) takes its problem with
    // it: a save refused over a box nobody can see is the worse defect.
    React.useEffect(() => () => {
      stateCallback.current?.({ status: "empty", text: "", message: null, outOfRange: null });
    }, []);

    function context(): TypedDateContext {
      return { financialYear, anchor: anchorAtFocus.current ?? anchor ?? (value || null), min, max };
    }

    /** What the box holds changed: tell the parent what it IS, not yet its value. */
    function typed(text: string) {
      const read = parseTypedDate(text, context());
      setBox({ text, read });
      stateCallback.current?.(dateFieldState(text, read));
    }

    /** The person has finished: show what was understood, and hand the value up
     *  if — and only if — it is not the one the parent already holds. */
    function commit(next: Box) {
      const text = next.read.kind === "date" ? next.read.display : next.text;
      const state = dateFieldState(text, next.read);
      setBox({ text, read: next.read });
      setTouched(true);
      stateCallback.current?.(state);
      const iso = isoFromRead(next.read);
      if (iso === handedUp.current) return;
      handedUp.current = iso;
      onChange(iso, state);
    }

    // A date outside min/max is re-judged against the CURRENT bounds, which can
    // move after the text was read (a parent that tightens the window).
    const shown: TypedDate = box.read.kind === "date" ? parseTypedDate(box.read.iso, { min, max }) : box.read;
    const message = shown.kind === "empty" ? null : shown.message;
    const showMessage = message !== null && touched && !focused;

    return (
      <DateFieldView
        {...rest}
        ref={ref}
        inputId={inputId}
        text={box.text}
        problem={showMessage ? message : null}
        tone={shown.kind === "error" ? "problem" : "hint"}
        invalid={invalid}
        wrapperClassName={wrapperClassName}
        disabled={disabled}
        readOnly={readOnly}
        onChange={(e) => typed(e.target.value)}
        onFocus={(e) => {
          anchorAtFocus.current = anchor ?? (value || null);
          setFocused(true);
          onFocus?.(e);
        }}
        onBlur={(e) => {
          setFocused(false);
          commit(box);
          anchorAtFocus.current = null;
          onBlur?.(e);
        }}
        onKeyDown={(e) => {
          onKeyDown?.(e);
          if (e.defaultPrevented || disabled || readOnly) return;
          if (e.key === "Enter") {
            // Not prevented: Enter still submits a form. It only makes the box
            // show what it understood, and say so if it did not.
            commit(box);
          } else if (e.key === "ArrowUp" || e.key === "ArrowDown") {
            e.preventDefault();
            const iso = stepTypedDate(box.text, e.key === "ArrowUp" ? 1 : -1, context());
            if (iso) {
              const text = typedDateText(iso);
              commit({ text, read: parseTypedDate(text, context()) });
            }
          }
        }}
      />
    );
  },
);
