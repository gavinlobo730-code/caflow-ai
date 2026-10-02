"use client";

import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { createSingleFlight, type SingleFlight } from "@/lib/async/singleFlight";
import { useFlightState } from "@/lib/async/useSingleFlight";

/** The frame every STYLED variant shares. `plain` deliberately has none of it
 *  (see below), so it is spelled once here and prefixed onto each variant
 *  rather than sitting in cva's `base`, which cannot be switched off. */
const FRAME =
  "inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50";

const buttonVariants = cva("", {
  variants: {
    variant: {
      default: `${FRAME} bg-primary text-primary-foreground hover:bg-primary/90`,
      destructive: `${FRAME} bg-destructive text-destructive-foreground hover:bg-destructive/90`,
      outline: `${FRAME} border border-input bg-background hover:bg-accent hover:text-accent-foreground`,
      secondary: `${FRAME} bg-secondary text-secondary-foreground hover:bg-secondary/80`,
      ghost: `${FRAME} hover:bg-accent hover:text-accent-foreground`,
      link: `${FRAME} text-primary underline-offset-4 hover:underline`,
      /**
       * No classes at all — the caller's own `className` is the whole look.
       *
       * It exists so a raw `<button className="…">` can take the repeat-click
       * guard below WITHOUT being restyled: this product has hundreds of
       * hand-styled buttons (the brand, the token palette) and moving one to
       * the shadcn `default` would change its colour, height and weight in the
       * same commit that was meant to change only what a second click does.
       */
      plain: "",
    },
    size: {
      default: "h-10 px-4 py-2",
      sm: "h-9 rounded-md px-3",
      lg: "h-11 rounded-md px-8",
      icon: "h-10 w-10",
      /** Pairs with `variant="plain"`: the caller sizes it. */
      none: "",
    },
  },
  defaultVariants: {
    variant: "default",
    size: "default",
  },
});

export interface ButtonProps
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "onClick">,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  /**
   * May return a promise, and that is the point (frontend_ux-09).
   *
   * While the promise is unresolved a second click is IGNORED — not queued —
   * the button is `disabled`, `aria-busy`, and shows a spinner; when it settles,
   * by resolving OR rejecting, the guard is released so a failed save can be
   * retried. The guard is a REF set before the handler's first `await`, not
   * React state, because `disabled={saving}` takes a render to reach the DOM
   * and two clicks dispatched back to back both run before that render.
   * A handler that returns nothing is an ordinary synchronous click and is
   * never held.
   *
   * `() => save("draft")` returns `save`'s promise and is held; `() => { save(); }`
   * discards it and is NOT — return the promise.
   */
  onClick?: (event: React.MouseEvent<HTMLButtonElement>) => unknown;
  /**
   * Driven from outside — a page whose own `saving` flag is the truth. Disables
   * the button, sets `aria-busy`, shows the spinner and ignores clicks, without
   * the button having started anything itself. Needed where the promise is not
   * returned to the click (a parent owns the save) or where the work must stay
   * "in progress" past the promise: a create that navigates away keeps the
   * flag up so the click that lands between "saved" and "gone" cannot save twice.
   */
  loading?: boolean;
  /**
   * One guard shared by sibling buttons over one action — Save Draft and Post
   * Entry — from `useSingleFlight()`. A click on either while the other is in
   * flight is ignored on the same tick, and both are disabled; only the one
   * that was pressed is `aria-busy` and spinning. Without it each Button holds
   * its own guard, which protects against a double-click on ONE control and
   * not against two controls pressed together.
   */
  flight?: SingleFlight;
  /** Show the spinner while pending. Default true. Turn off for an icon-only
   *  button, or one whose own children already show progress. */
  spinner?: boolean;
  /** Leading icon, swapped for the spinner while pending instead of sitting
   *  beside it. */
  icon?: React.ReactNode;
}

function assignRef<T>(ref: React.ForwardedRef<T>, value: T | null): void {
  if (typeof ref === "function") ref(value);
  else if (ref) (ref as React.MutableRefObject<T | null>).current = value;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className, variant, size, asChild = false, onClick, loading = false, flight: sharedFlight,
      spinner = true, icon, disabled, children, ...props
    },
    ref,
  ) => {
    // An id per control, so a SHARED flight can say which one started it.
    const owner = React.useId();
    const [ownFlight] = React.useState(createSingleFlight);
    const flight = sharedFlight ?? ownFlight;
    const state = useFlightState(flight);

    const mine = state.busy && state.owner === owner;
    const pending = loading || mine;
    // Disabled while ANY control on this flight is working, not only this one.
    const blocked = loading || state.busy;

    const node = React.useRef<HTMLButtonElement | null>(null);
    const setNode = React.useCallback((el: HTMLButtonElement | null) => {
      node.current = el;
      assignRef(ref, el);
    }, [ref]);

    // Disabling the button the keyboard is on drops focus to <body>, which
    // leaves a CA who pressed Enter on Post and got an error with nowhere to
    // Tab from. Put it back when the work this button started has settled.
    const hadFocus = React.useRef(false);
    const wasMine = React.useRef(false);
    React.useEffect(() => {
      if (wasMine.current && !mine && hadFocus.current) {
        hadFocus.current = false;
        const el = node.current;
        if (el && typeof document !== "undefined" &&
            (document.activeElement === document.body || document.activeElement === null)) {
          try { el.focus(); } catch { /* a focus that cannot be restored is not a failure */ }
        }
      }
      wasMine.current = mine;
    }, [mine]);

    const handleClick = (event: React.MouseEvent<HTMLButtonElement>) => {
      if (!onClick) return;
      // The guard. `flight.busy()` is a synchronous read of a variable the first
      // click set before it did anything else — not the `blocked` above, which
      // is what the LAST render saw.
      if (loading || flight.busy()) {
        // A submit button would otherwise still submit its form, and a button
        // in a clickable row would otherwise hand the repeat to the ROW: the
        // first click's handler usually stopped propagation, and the ignored
        // one never runs that handler, so without this the second click of a
        // double-click on a row's Delete would open the row. A repeat click is
        // not new intent, so it is swallowed whole.
        event.preventDefault();
        event.stopPropagation();
        return;
      }
      hadFocus.current =
        typeof document !== "undefined" && document.activeElement === event.currentTarget;
      flight.run(() => onClick(event), owner);
    };

    const classes = cn(buttonVariants({ variant, size, className }), "aria-busy:cursor-progress");

    if (asChild) {
      return (
        <Slot
          className={classes}
          ref={ref as React.Ref<HTMLElement>}
          aria-busy={pending || undefined}
          {...props}
        >
          {children}
        </Slot>
      );
    }

    return (
      <button
        className={classes}
        ref={setNode}
        disabled={disabled || blocked}
        aria-busy={pending || undefined}
        onClick={onClick ? handleClick : undefined}
        {...props}
      >
        {pending && spinner ? (
          <Loader2 aria-hidden="true" size={12} className="mr-1.5 inline-block shrink-0 animate-spin" />
        ) : icon}
        {children}
      </button>
    );
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
