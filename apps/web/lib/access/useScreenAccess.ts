"use client";

import { useMemo } from "react";
import { useAuth, usePermissions } from "@/lib/auth/AuthContext";
import { AREA_RULES, areaOffered, mayOpen, type Asker, type Verdict } from "./screenAccess";

/**
 * The signed-in person, asked of the one table (`screenAccess.ts`): which areas are on their menu and which addresses open.
 *
 * UNTIL THE PERMISSIONS ARE KNOWN NOTHING IS WITHHELD ON A PAIR, the choice every gate here makes: a menu that hid an area
 * until the identity call answered would flash it in on the second frame, and a page that hid itself would turn a slow call
 * into a screen that never opens. The Partner-only rule is the exception: it is asked of the role, which is known sooner,
 * and it fails closed, so My practice is never offered to somebody the server would refuse.
 */
export function useScreenAccess(): {
  resolved: boolean;
  who: Asker;
  /** Whether a menu should list this address. */
  offered: (href: string) => boolean;
  /** Whether the firm menu should list this area. */
  areaOn: (areaId: string) => boolean;
  /** The full answer for an address, for the page gate. Null until the permissions are known. */
  verdict: (href: string) => Verdict | null;
} {
  const { can, resolved } = usePermissions();
  const { userRole } = useAuth();
  return useMemo(() => {
    const who: Asker = { can, isPartner: userRole === "Partner" };
    const partnerOnly = (href: string) => {
      const v = mayOpen(href, { can: () => true, isPartner: who.isPartner });
      return !v.allowed && v.partnerOnly;
    };
    return {
      resolved,
      who,
      offered: (href) => (resolved ? mayOpen(href, who).allowed : !partnerOnly(href)),
      areaOn: (areaId) => (AREA_RULES[areaId]?.partnerOnly ? who.isPartner : !resolved || areaOffered(areaId, who)),
      verdict: (href) => (resolved ? mayOpen(href, who) : null),
    };
  }, [can, resolved, userRole]);
}
