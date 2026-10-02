"use client";

import * as React from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { usePermissions } from "@/lib/auth/AuthContext";

/**
 * THE NEXT STEP ON AN EMPTY LIST (frontend_ux-24).
 *
 * A new practice's first look at a screen is usually an empty one, and 130
 * hand-written paragraphs in 83 files (counted by the detector in
 * scripts/an-empty-list-says-what-to-do-next.test.ts, at the commit before this
 * work) said only "No invoices in this period" or "No suppliers yet." — a wall of
 * nothing, with the one button that would fix it a few centimetres above, in a
 * toolbar the eye had already left. `EmptyState` existed (eleven uses, seven with
 * an action) and `DataTable` already took `emptyAction`; what was missing was an
 * action people could not forget to gate and did not have to restyle each time:
 * the seven that existed were several styles (a blue text link, a brand button, a
 * brand link, an outlined link) and none of them asked who was looking.
 *
 * `requires` IS NOT OPTIONAL, and that is the whole design. An empty list is shown
 * to everybody who can READ it, and the people who can read a list are a wider set
 * than the people who can add to it — an Executive reads accounting and cannot
 * write it, a Manager cannot invite a team member. Offering them the button is the
 * defect `<Can>` exists to stop: it sends them to a 403 after the click. So every
 * action states which permission it needs, as the backend's own `[resource,
 * action]` pair (core/permissions.PERMISSIONS, served by
 * GET /api/identity/permissions) — or says `"anyone"`, which is a statement the
 * reader can see and a reviewer can question, not an omission. An action the
 * caller may not perform renders NOTHING, and `usePermissions().can` fails closed
 * while the permission map is still resolving, so nothing flashes.
 *
 * It does not decide WHETHER the list is empty or WHY (a filter that matched
 * nothing and a client with no invoices are different next steps; the screen
 * knows which and passes different props), and it never submits anything on its
 * own: an action opens the screen's own form, goes to a screen that exists, or
 * runs the screen's own handler.
 *
 * AN ACTION THAT RUNS A HANDLER IS A `<Button>`, AND SO HOLDS A REPEAT CLICK
 * (frontend_ux-09). It was a raw `<button onClick={props.onClick}>` typed
 * `() => void`: the one place a first-time user is told "press this" was the one
 * place a double-click on Raise Invoice or Generate All Notes reached the network
 * twice, and `scripts/a-button-that-writes-ignores-a-second-click.test.ts` could
 * not see it, so a screen that moved its Button onto the guard and its empty state
 * onto this read as fully converted. `onClick` may now return the handler's
 * promise, which is what the primitive holds the click for, and the ratchet reads
 * this tag as a Button: a handler that starts a write and DROPS the promise
 * (`() => void save()`) fails it, because a promise the primitive is never given
 * is a guard released on the same tick. Write `() => save()`.
 */

export type EmptyActionRequires = readonly [resource: string, action: string] | "anyone";

type Common = {
  label: string;
  icon?: React.ReactNode;
  /** The permission the action needs, or `"anyone"` for a link to a screen any
   *  signed-in member may open. Required so that leaving it out is a type error. */
  requires: EmptyActionRequires;
  /** `primary` is the one thing to do; `secondary` is an alternative route to the same place. */
  variant?: "primary" | "secondary";
  className?: string;
};

export type EmptyStateActionProps =
  | (Common & { href: string; onClick?: never })
  | (Common & {
      /** Return the promise of any request it starts: while it is unresolved a second click is
       *  ignored and the action shows it is working. `() => save()` is held; `() => void save()`
       *  is not. A handler that only opens a form returns nothing and is never held. */
      onClick: () => unknown;
      href?: never;
      /** Held from outside while the screen is mid-request, for a screen whose own flag is the
       *  truth (a request the click did not start). The primitive holds the click it started. */
      disabled?: boolean;
    });

const BASE =
  "inline-flex items-center justify-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium transition-colors";
const VARIANT = {
  primary: "bg-brand text-white hover:bg-brand-dark",
  secondary: "border border-ps-border bg-white text-ps-label hover:bg-ps-bg",
} as const;

export function EmptyStateAction(props: EmptyStateActionProps) {
  const { label, icon, requires, variant = "primary", className } = props;
  const { can } = usePermissions();
  if (requires !== "anyone" && !can(requires[0], requires[1])) return null;
  const cls = cn(BASE, VARIANT[variant], className);
  const body = (
    <>
      {icon}
      {label}
    </>
  );
  if (props.href !== undefined) {
    return (
      <Link href={props.href} className={cls}>
        {body}
      </Link>
    );
  }
  // `variant="plain" size="none"`: the Button contributes the repeat-click guard and nothing of its
  // look, so the action keeps the brand and border classes above exactly as they were. The click is
  // forwarded with NO arguments and the promise handed back, so the handler is never given the event
  // and the primitive is given what it needs to hold the click.
  return (
    <Button
      type="button"
      variant="plain"
      size="none"
      icon={icon}
      onClick={() => props.onClick()}
      disabled={props.disabled}
      className={cn(cls, "disabled:opacity-50")}
    >
      {label}
    </Button>
  );
}

/**
 * A row of `EmptyStateAction`s: the primary first, wrapping on a narrow screen.
 * It renders NOTHING when the caller may perform none of them, so a read-only
 * member sees the explanation and no empty row where the buttons would be.
 */
export function EmptyStateActions({ children }: { children: React.ReactNode }) {
  const { can } = usePermissions();
  const offered = React.Children.toArray(children).some((child) => {
    if (!React.isValidElement(child)) return false;
    const requires = (child.props as { requires?: EmptyActionRequires }).requires;
    return requires === "anyone" || (requires !== undefined && can(requires[0], requires[1]));
  });
  if (!offered) return null;
  return <div className="flex flex-wrap items-center justify-center gap-2">{children}</div>;
}
