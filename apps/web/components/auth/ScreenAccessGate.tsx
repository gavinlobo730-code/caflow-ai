"use client";

import type { ReactNode } from "react";
import { PageHeader } from "@/components/ui/page-header";
import { useScreenAccess } from "@/lib/access/useScreenAccess";
import { ALL_SCREENS } from "@/lib/navigation/screens";
import { AREA_NAMES } from "@/lib/guide/whereIs";
import RequestAccess from "@/components/auth/RequestAccess";

/**
 * THE ONE GATE ON EVERY FIRM SCREEN (POST-A-543): an address a person holds no tick for says so, in words, instead of
 * drawing the screen around the server's refusal.
 *
 * It is mounted once, in the shell, around whatever page the address is, and asks the one table (`screenAccess.ts`) the
 * menus and the guide ask. So a screen cannot be offered by a menu and refused here, or hidden from a menu and open here: an
 * address typed, bookmarked or arriving in a link gets the same answer the menu gave.
 *
 * WHAT IT SAYS. The area's name when it is the area the person does not hold ("Accounting is not part of your access"),
 * the screen's own name when the area is theirs and this screen asks something more. It says that nothing is shown and that
 * this is not the same as there being nothing, because an empty list would be a statement about the firm and this is a
 * statement about the person looking.
 *
 * IT OFFERS A WAY ON. Under the notice is "Request access" (`RequestAccess`): the person asks the firm's Partners for the one
 * permission the notice named, and an approval switches it on. My practice is not offered it: no permission opens it.
 *
 * WHAT IT LEAVES ALONE. My practice: its pages carry the Partner guard, which sends a non-Partner home with its own notice.
 * Settings and the inside of a client: their own rules (`screenAccess.ts` says why). And everything, until the permissions
 * are known. This is what is SHOWN; the server's `rbac()` is the control.
 */
export default function ScreenAccessGate({ pathname, children }: { pathname: string; children: ReactNode }) {
  const { verdict } = useScreenAccess();
  const answer = verdict(pathname);
  if (!answer || answer.allowed || answer.partnerOnly || !answer.ask) return <>{children}</>;

  const bare = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
  const screen = ALL_SCREENS.find((s) => s.scope === "firm" && s.href === bare);
  const areaName = answer.area ? AREA_NAMES[answer.area] : undefined;
  const what = answer.byArea ? (areaName ?? "This area") : (screen?.name ?? areaName ?? "This screen");
  return (
    <div className="mx-auto max-w-2xl p-6" role="status" data-tick-gate={`${answer.ask[0]}:${answer.ask[1]}`}>
      <PageHeader
        title={`${what} is not part of your access`}
        subtitle="Your Partner decides which parts of PracticeSync each person can open."
      />
      <p className="mt-4 text-sm text-ps-body">
        Nothing is shown to you here, and that is not the same as there being nothing. If you need this screen, ask for
        it below: a Partner can switch it on for you.
      </p>
      {/* `key`: moving from one refused address to another starts the request afresh, for that address's permission. */}
      <RequestAccess key={`${answer.ask[0]}:${answer.ask[1]}`} resource={answer.ask[0]} action={answer.ask[1]} askedFrom={what} />
    </div>
  );
}
