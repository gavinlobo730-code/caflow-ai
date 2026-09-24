/**
 * Input, Select, Textarea, Label and the field that ties them together.
 *
 * ── WHY THESE AND NOT THE SHADCN ONES ───────────────────────────────────────
 * `components/ui/` already holds Button, Card, Badge, Tabs, Modal, Drawer and
 * DataTable, all vendored from shadcn and all built on the shadcn colour
 * tokens — `bg-primary`, `border-input`, `text-muted-foreground`. Measured
 * across `app/`, `components/` and `lib/`, those tokens are used SEVEN times
 * between them. The product does not speak that vocabulary; it speaks `ps.*`.
 *
 * So these are built from what the product ACTUALLY writes, which is the only
 * way adoption can be a DELETION rather than a redesign. The commonest raw
 * spelling, counted:
 *
 *     <input>     w-full border border-ps-border rounded-lg px-3 py-2 text-sm
 *                 focus:outline-none focus:ring-2 focus:ring-brand     (29)
 *     <select>    the same string                                          (17)
 *     <label>     block text-xs font-medium text-ps-label mb-1            (180)
 *
 * against 594 raw `<input>`, 194 `<select>`, 28 `<textarea>` and 927
 * `<label>` in the tree. Those defaults are reproduced here, with two
 * deliberate changes named below.
 *
 * ── THE TWO DELIBERATE CHANGES ──────────────────────────────────────────────
 * 1. THE FOCUS RING IS THE BRAND, NOT A STRAY TAILWIND BLUE. `ring-blue-500`
 *    is the fourth primary in a product that already had three (brand navy,
 *    indigo #4338CA in banking, blue-700 on the Team screen). A design system
 *    whose focus ring is a colour from no palette is not one.
 * 2. `focus-visible:` RATHER THAN `focus:`. A ring on mouse click is noise; a
 *    keyboard user needs it. Text inputs match `:focus-visible` whenever they
 *    are focused, per the selector's own definition, so nothing is lost for
 *    the controls here — only a clicked `<select>` stops flashing a ring.
 *
 * ── WHAT IS NOT HERE, AND WHY ───────────────────────────────────────────────
 * TABLE and PAGINATION are not new components: `components/ui/data-table.tsx`
 * already renders a table with sorting, selection, bulk actions, CSV export
 * and both client and server paging. The 242 raw `<table>` in the tree are an
 * ADOPTION problem, not a missing primitive, and building a second table shell
 * beside DataTable is the second-implementation mistake this codebase keeps
 * recording.
 *
 * TOOLTIP is not here either. 292 sites use the native `title=` attribute,
 * which is keyboard- and screen-reader-accessible for free; a custom tooltip
 * is a real gap but it is a behaviour decision (hover delay, touch, focus
 * trap) that belongs with the reference screens rather than a class string.
 */
import * as React from "react";
import { cn } from "@/lib/utils";

/** The one control surface. Input, Select and Textarea all wear it. */
const CONTROL =
  "w-full rounded-lg border border-ps-border bg-white " +
  "text-ps-ink placeholder:text-ps-hint " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:border-brand " +
  "disabled:cursor-not-allowed disabled:bg-ps-muted disabled:text-ps-label " +
  "transition-[border-color,box-shadow] duration-150";

/** TWO SIZES, BECAUSE THE PRODUCT HAS TWO. `md` is the form default the 29
 *  most common raw inputs write (`px-3 py-2 text-sm`); `sm` is the one a dense
 *  inline control writes (`px-2.5 py-[7px] text-xs`), which is what a filter
 *  bar, a register header or a settings row inside a panel uses. Reproduced
 *  rather than chosen, so adopting either is a deletion. A third size would
 *  be a decision for the reference screens. */
const SIZE = {
  md: "px-3 py-2 text-sm",
  sm: "px-2.5 py-[7px] text-xs",
} as const;

export type ControlSize = keyof typeof SIZE;

/** An invalid control says so in colour AND in `aria-invalid`, because a
 *  red border alone is invisible to a screen reader and to a colour-blind
 *  reader — the two populations this product's dense screens are worst for. */
const INVALID =
  "border-state-problem focus-visible:ring-state-problem focus-visible:border-state-problem";

export interface InputProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "size"> {
  /** Renders the error styling and sets `aria-invalid`. */
  invalid?: boolean;
  size?: ControlSize;
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, invalid, size = "md", ...props }, ref) => (
    <input
      ref={ref}
      aria-invalid={invalid || undefined}
      className={cn(CONTROL, SIZE[size], invalid && INVALID, className)}
      {...props}
    />
  ),
);
Input.displayName = "Input";

export interface TextareaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  invalid?: boolean;
  size?: ControlSize;
}

export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, invalid, size = "md", ...props }, ref) => (
    <textarea
      ref={ref}
      aria-invalid={invalid || undefined}
      className={cn(CONTROL, SIZE[size], "min-h-[72px] resize-y", invalid && INVALID, className)}
      {...props}
    />
  ),
);
Textarea.displayName = "Textarea";

export interface SelectProps
  extends Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "size"> {
  invalid?: boolean;
  size?: ControlSize;
}

/** A NATIVE select, deliberately. `components/ui/combobox.tsx` is the rich one
 *  and already handles search, async loading and keyboard navigation; this is
 *  for the twenty-odd short fixed lists where a native control is better on a
 *  phone and free for a screen reader. Two primitives, two jobs. */
export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, invalid, size = "md", ...props }, ref) => (
    <select
      ref={ref}
      aria-invalid={invalid || undefined}
      className={cn(CONTROL, SIZE[size], "appearance-none bg-no-repeat pr-8", invalid && INVALID, className)}
      style={{
        // The chevron is inlined rather than an icon element because a
        // `<select>` may contain only `<option>`; there is nowhere to put one.
        backgroundImage:
          "url(\"data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%2364748B' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E\")",
        backgroundPosition: "right 0.625rem center",
        ...props.style,
      }}
      {...props}
    />
  ),
);
Select.displayName = "Select";

export interface LabelProps
  extends React.LabelHTMLAttributes<HTMLLabelElement> {
  /** Renders the required marker. It is `aria-hidden` and paired with the
   *  control's own `required`, so a screen reader hears the requirement once
   *  from the control rather than reading a bare asterisk. */
  required?: boolean;
}

export const Label = React.forwardRef<HTMLLabelElement, LabelProps>(
  ({ className, required, children, ...props }, ref) => (
    <label
      ref={ref}
      className={cn("mb-1 block text-xs font-medium text-ps-label", className)}
      {...props}
    >
      {children}
      {required && (
        <span aria-hidden className="ml-0.5 text-state-problem">*</span>
      )}
    </label>
  ),
);
Label.displayName = "Label";

let autoId = 0;

export interface FieldProps {
  label: React.ReactNode;
  /** Quiet help under the control. Hidden when `error` is set — two messages
   *  under one box is one message too many, and the error is the one to read. */
  hint?: React.ReactNode;
  error?: React.ReactNode;
  required?: boolean;
  htmlFor?: string;
  className?: string;
  /** A compact field also shrinks its own label and hint — otherwise a `sm`
   *  control sits under a label a size too big for it and the row stops
   *  looking dense, which is the whole reason `sm` exists. */
  size?: ControlSize;
  children: React.ReactElement;
}

/**
 * Label + control + hint or error, wired together.
 *
 * THE POINT IS THE WIRING, NOT THE LAYOUT. 927 raw `<label>` in the tree and
 * `aria-describedby` appears ONCE — so a hint or an error sitting under a box
 * is, to a screen reader, unrelated text somewhere on the page. This clones
 * the child to give it an `id`, points the label at it, and hangs the hint or
 * error off `aria-describedby`; a control that already carries its own `id`
 * keeps it.
 */
export function Field({
  label, hint, error, required, htmlFor, className, size = "md", children,
}: FieldProps) {
  const generated = React.useMemo(() => `fld-${++autoId}`, []);
  const id = htmlFor ?? (children.props as { id?: string }).id ?? generated;
  const describedBy = error ? `${id}-err` : hint ? `${id}-hint` : undefined;
  return (
    <div className={cn("min-w-0", className)}>
      <Label htmlFor={id} required={required} className={size === "sm" ? "text-3xs" : undefined}>
        {label}
      </Label>
      {React.cloneElement(children, {
        id,
        "aria-describedby": describedBy,
        ...(error ? { invalid: true } : {}),
      } as Record<string, unknown>)}
      {error ? (
        <p id={`${id}-err`} role="alert" className="mt-1 text-2xs text-state-problem">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="mt-1 text-2xs text-ps-hint">{hint}</p>
      ) : null}
    </div>
  );
}
