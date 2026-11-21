import type { ReactNode } from "react";
import TickGate from "@/components/auth/TickGate";

// Engagement letters carry the practice's fees, and the server reads them with `engagement:read`: a Partner's and a
// Manager's by default, and anybody's a Partner ticks it for (POST-A-543).
export default function EngagementsLayout({ children }: { children: ReactNode }) {
  return (
    <TickGate
      requires={["engagement", "read"]}
      what="Engagements"
      why="Engagement letters carry the practice's fees, so they are shown to Partners and Managers, and to anybody a Partner has given them to."
    >
      {children}
    </TickGate>
  );
}
