import { ModuleWorklist } from "@/components/hub/ModuleWorklist";

/** The Purchases tile's firm-level destination (D22, G3): which clients are
 *  overdue to their suppliers, and by how much. */
export default function Page() {
  return <ModuleWorklist tile="purchases" heading="Purchases" />;
}
