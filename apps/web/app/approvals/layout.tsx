import type { ReactNode } from "react";
import PeopleAccessGate from "@/components/team/PeopleAccessGate";

// The approvals list is read with approval:read. See PeopleAccessGate for why a person without it is told so, and not
// shown the screen drawn around a refusal.
export default function ApprovalsLayout({ children }: { children: ReactNode }) {
  return <PeopleAccessGate>{children}</PeopleAccessGate>;
}
