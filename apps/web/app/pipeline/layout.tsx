import type { ReactNode } from "react";
import TickGate from "@/components/auth/TickGate";

// The pipeline's list is every lead of the firm (a lead has no client, so no assignment narrows it), and the server reads
// it with `pipeline:read`: a Partner's and a Manager's by default, and anybody's a Partner ticks it for (POST-A-543).
export default function PipelineLayout({ children }: { children: ReactNode }) {
  return (
    <TickGate
      requires={["pipeline", "read"]}
      what="Pipeline"
      why="The pipeline lists every lead of the firm, so it is shown to Partners and Managers, and to anybody a Partner has given it to."
    >
      {children}
    </TickGate>
  );
}
