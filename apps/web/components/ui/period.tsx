/**
 * The financial-year and assessment-year picker.
 *
 * ── WHY ─────────────────────────────────────────────────────────────────────
 * 21 of these across 24 files, in **14 distinct class strings** and FOUR
 * different focus treatments — `focus:border-blue-500`, `focus:ring-2
 * focus:ring-blue-500`, `focus:border-blue-400`, and four with none at all —
 * one of them on a raw `border-gray-300`. Every one of them is the same
 * control asking the same question.
 *
 * The CHOICES were already right: `scripts/a-financial-year-choice-comes-from-
 * the-clock.test.ts` has forced them through `lib/dates/periods` since the
 * twelve screens that hard-coded `FY_OPTIONS` were found, eight of them ending
 * at a year already past. What stayed hand-rolled was the markup.
 *
 * ── AN ASSESSMENT YEAR IS NOT A FINANCIAL YEAR, AND `kind` SAYS SO ──────────
 * IT Act §2(9) with §3: AY = FY + 1, so AY 2026-27 IS FY 2025-26. CLAUDE.md
 * records why `FYLabel` and `AYLabel` validate identically and are still two
 * types — *"only the NAME keeps them apart, and a route that muddles them
 * reconciles the wrong statement against the wrong return"*. The same argument
 * applies to the control: `kind="ay"` is visible in the JSX, where
 * `assessmentYearChoicesAround()` buried inside a `useState` initialiser is
 * not.
 *
 * ── IT STAYS PER-PAGE ───────────────────────────────────────────────────────
 * A single global FY control was built and REMOVED on purpose: a CA looking at
 * a 2024-25 GSTR-1 and a 2025-26 payroll run in two tabs is doing something
 * ordinary, and a shared control makes one of the two silently wrong. This is
 * a shared APPEARANCE, never shared STATE — it holds no context, no store and
 * no `localStorage`, and takes its value and its setter from the page.
 *
 * ── IT DERIVES NOTHING ABOUT TAX ────────────────────────────────────────────
 * The choices come from `lib/dates/periods`, which reads the clock. This file
 * contains no year literal at all, which is the property the guard checks: a
 * component that hard-codes "2025-26" is the defect, not the fix.
 */
"use client";

import * as React from "react";
import { Select, Field, type ControlSize } from "@/components/ui/field";
import {
  financialYearChoicesAround,
  assessmentYearChoicesAround,
} from "@/lib/dates/periods";

export type PeriodKind = "fy" | "ay";

export interface PeriodPickerProps {
  /** Which year this is. `fy` is April–March; `ay` is the year after it. */
  kind?: PeriodKind;
  value: string;
  onChange: (value: string) => void;
  /** Anchors the list so a screen already showing an older year keeps it in
   *  range — the `month` argument `financialYearChoicesAround` takes. */
  anchorMonth?: string | null;
  /** Wraps the control in a `<Field>` with this label, wired for `aria`.
   *  Omitted, the bare control is rendered for a caller that has its own. */
  label?: React.ReactNode;
  id?: string;
  size?: ControlSize;
  className?: string;
  disabled?: boolean;
  /** Extra choices to keep selectable — a year the server sent that falls
   *  outside the window. A value the list does not contain would otherwise
   *  render as no selection at all, which reads as "this screen has no year". */
  include?: string[];
  /** A leading empty option, for a form field where no year is chosen yet.
   *  Omitted, there is none: a FILTER always has a year, and offering a blank
   *  one there invites a request for every year the firm has ever had. */
  placeholder?: string;
  /** How many years to offer. `lib/dates/periods` sets the default. */
  count?: number;
}

/** The option text. **The prefix is deliberate and is not decoration**: the 25
 *  controls this replaced wrote the year three ways — `2025-26`, `FY 2025-26`
 *  and `FY 2025–26` with an en dash — and an ASSESSMENT year is spelled
 *  exactly like a financial year, so `2026-27` alone does not say which it is.
 *  IT Act §2(9) with §3 makes AY 2026-27 the same period as FY 2025-26, and a
 *  CA reading two dropdowns on one screen has no other way to tell them
 *  apart. The stored VALUE is the bare year, unchanged. */
function optionLabel(kind: PeriodKind, year: string): string {
  return `${kind === "ay" ? "AY" : "FY"} ${year}`;
}

export function periodChoices(
  kind: PeriodKind,
  anchorMonth?: string | null,
  include?: string[],
  count?: number,
): string[] {
  const base =
    kind === "ay"
      ? assessmentYearChoicesAround(anchorMonth ?? null, count)
      : financialYearChoicesAround(anchorMonth ?? null, count);
  const extra = (include ?? []).filter((y) => y && !base.includes(y));
  return extra.length ? [...base, ...extra].sort().reverse() : base;
}

export function PeriodPicker({
  kind = "fy",
  value,
  onChange,
  anchorMonth,
  label,
  id,
  size,
  className,
  disabled,
  include,
  placeholder,
  count,
}: PeriodPickerProps) {
  // The CURRENT value is always selectable, whatever the window says. A
  // `<select>` whose value matches no option shows its first option instead,
  // so a screen restored to an old year would silently read as a new one.
  const years = periodChoices(kind, anchorMonth, [...(include ?? []), value].filter(Boolean), count);
  const control = (
    <Select
      id={id}
      size={size}
      className={className}
      disabled={disabled}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-label={label ? undefined : kind === "ay" ? "Assessment year" : "Financial year"}
    >
      {placeholder !== undefined && <option value="">{placeholder}</option>}
      {years.map((y) => (
        <option key={y} value={y}>
          {optionLabel(kind, y)}
        </option>
      ))}
    </Select>
  );
  if (!label) return control;
  return (
    <Field label={label} htmlFor={id} size={size}>
      {control}
    </Field>
  );
}
