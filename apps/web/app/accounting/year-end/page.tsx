import { ModuleWorklist } from "@/components/hub/ModuleWorklist";

/** The Year-End tile's firm-level destination (D22, G3): which clients have
 *  engagements not yet finalised. */
export default function Page() {
  return <ModuleWorklist tile="year_end" heading="Year-End" />;
}
