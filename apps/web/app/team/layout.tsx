import type { ReactNode } from "react";
import PeopleAccessGate from "@/components/team/PeopleAccessGate";

// Every screen under /team reads something the server shows only to a person who holds that screen's permission pair.
// See PeopleAccessGate for why a person without it is told so, and not shown the screen drawn around a refusal.
export default function TeamLayout({ children }: { children: ReactNode }) {
  return <PeopleAccessGate>{children}</PeopleAccessGate>;
}
