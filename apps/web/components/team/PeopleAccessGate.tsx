"use client";

import type { ReactNode } from "react";
import { usePathname } from "next/navigation";
import { PageHeader } from "@/components/ui/page-header";
import { usePermissions } from "@/lib/auth/AuthContext";
import { peopleSectionAt } from "@/lib/workspace/practiceWorkspace";

/**
 * Says so when the signed-in person may not read a People screen (Team, Assignments, Approvals, Workload, Login History),
 * instead of drawing the screen around a refusal (POST-A-542, found by the role walk of 21-11-2026).
 *
 * WHAT WAS WRONG. These screens are on no menu of an Executive or a Reviewer, but an address can be typed, bookmarked or
 * arrive in a link. The server refused the list, rightly, and the screen drew everything else anyway: the heading, four
 * summary tiles reading 0, "No team members yet" and an "Invite Member" button beside an error. Each of those is a
 * statement about the firm, and here each was false, because it was a statement about the person looking.
 *
 * THE PAIR IS THE SCREEN'S OWN, READ FROM THE ONE LIST. `PRACTICE_PEOPLE_SECTIONS` names, for each People screen, the
 * permission pair its reads need, and the menus and the My practice tiles already read it. This gate asks the same list
 * for the address it is on, so a screen cannot be offered by a menu and refused by its gate, or the other way round. The
 * pair is exactly what the server asks for the screen's list (`team:read`, `assignment:read`, `approval:read`,
 * `workload:read`), resolved per person, so a grant or a block a Partner made on the Team screen moves this with it.
 *
 * Until the permission map has loaded NOTHING is known about the person, so the page renders as it always did (the same
 * choice as PayrollAccessGate and FeeAccessGate). This is what is SHOWN; the server's `rbac()` is the control.
 */
export default function PeopleAccessGate({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { can, resolved } = usePermissions();
  const section = peopleSectionAt(pathname ?? "");
  if (resolved && section && !can(section.requires[0], section.requires[1])) {
    return (
      <div className="mx-auto max-w-2xl p-6" role="status" data-people-gate={section.id}>
        <PageHeader
          title={`You do not have access to ${section.label}`}
          subtitle="The firm's staff, who is assigned to which client, approvals and workload are shown to the people who run the team: a Partner, a Manager, or somebody a Partner has given this access."
        />
        <p className="mt-4 text-sm text-ps-body">
          Nothing is shown to you here, and that is not the same as there being nothing or nobody. Ask your Partner if
          you need this screen.
        </p>
      </div>
    );
  }
  return <>{children}</>;
}
