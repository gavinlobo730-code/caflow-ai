"use client";

/**
 * THE PART OF A SETTINGS PAGE THAT CHANGES SOMETHING, FOR A PERSON WHO MAY ONLY READ IT (POST-A-545).
 *
 * A Settings page used to be opened by a ROLE (a guard naming Partner, or Partner and Manager), so everybody who reached one
 * could also save on it and no page ever had to say otherwise. Since the pages follow the permissions a Partner ticks, the
 * pair that OPENS a page (the one its read asks) and the pair that CHANGES it (the one its save asks) are two ticks, and a
 * person can hold the first without the second: a Manager holds `branding` `read` and not `branding` `write` from the day
 * they join. Such a person is shown the page with its controls switched off and one sentence saying why, with a way to ask.
 * A button that is offered and then refused by the server is the thing this replaces.
 *
 * `ChangePart` is a `<fieldset>`: the browser itself disables every input, select, textarea and button inside a disabled
 * fieldset, so a control added to a page later is covered without anybody remembering to. A link is not a form control and
 * stays live, which is right: reading is what this person may do.
 *
 * UNTIL THE PERMISSIONS ARE KNOWN NOTHING IS WITHHELD, the choice every gate here makes (`useScreenAccess`): a page that
 * switched its form off until the identity call answered would flash, and a slow call would be a form nobody can type in.
 *
 * NOT A SECURITY BOUNDARY. The server's `rbac()` refuses the save whatever a screen draws.
 */
import type { ReactNode } from "react";
import { usePermissions } from "@/lib/auth/AuthContext";
import RequestAccess from "@/components/auth/RequestAccess";
import { cn } from "@/lib/utils";

/** Whether this person may change what the pair guards. True until the permissions are known. */
export function useMayChange(resource: string, action: string): boolean {
  const { can, resolved } = usePermissions();
  return !resolved || can(resource, action);
}

export function ChangePart({ resource, action, className, children }: {
  resource: string;
  action: string;
  /** The classes the wrapped block had (a fieldset is a block of its own; give it the layout its children need). */
  className?: string;
  children: ReactNode;
}) {
  const may = useMayChange(resource, action);
  return (
    <fieldset disabled={!may} data-change-part={`${resource}:${action}`} data-read-only={may ? undefined : ""}
      className={cn("min-w-0 border-0 p-0 m-0", className)}>
      {children}
    </fieldset>
  );
}

/** One sentence, drawn only for a person who may read the page and not change it, with a way to ask a Partner. */
export function ReadOnlyNotice({ resource, action, page, className }: {
  resource: string;
  action: string;
  /** The page's name, as the request will say where it was asked from. */
  page: string;
  className?: string;
}) {
  const may = useMayChange(resource, action);
  if (may) return null;
  return (
    <div role="status" data-read-only-notice={`${resource}:${action}`}
      className={cn("rounded-xl border border-ps-border bg-ps-bg px-4 py-3", className)}>
      <p className="text-sm text-ps-body">
        You can read this page and cannot change it. Your Partner decides who can change what; if you need to, ask below.
      </p>
      <RequestAccess resource={resource} action={action} askedFrom={page} />
    </div>
  );
}
