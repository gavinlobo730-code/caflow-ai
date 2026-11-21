"use client";

import type { ReactNode } from "react";
import { PageHeader } from "@/components/ui/page-header";
import { usePermissions } from "@/lib/auth/AuthContext";

/**
 * Says so when the signed-in person does not hold the permission a screen's reads need, instead of drawing the screen
 * around the server's refusal (POST-A-543, the owner's decision of 21-11-2026: what the Partner ticked is what a person
 * sees and can open).
 *
 * `requires` is the pair THE SERVER ASKS for the screen's main read, named where the gate is mounted, so the screen and the
 * server cannot disagree about who is let in. `what` names the screen in the product's words and `why` says, in a
 * sentence, who it is shown to by default.
 *
 * Until the permission map has loaded NOTHING is known about the person, so the page renders as it always did: a gate that
 * hid the page until then would turn a slow identity call into a screen that never opens (the same choice as the payroll,
 * fee and People gates). This is what is SHOWN; the server's `rbac()` is the control.
 */
export default function TickGate({
  requires, what, why, children,
}: {
  requires: readonly [resource: string, action: string];
  what: string;
  why: string;
  children: ReactNode;
}) {
  const { can, resolved } = usePermissions();
  if (resolved && !can(requires[0], requires[1])) {
    return (
      <div className="mx-auto max-w-2xl p-6" role="status" data-tick-gate={`${requires[0]}:${requires[1]}`}>
        <PageHeader title={`${what} is not part of your access`} subtitle={why} />
        <p className="mt-4 text-sm text-ps-body">
          Nothing is shown to you here, and that is not the same as there being nothing. Ask your Partner if you need
          this screen: they can switch it on for you from Team, under Permissions.
        </p>
      </div>
    );
  }
  return <>{children}</>;
}
