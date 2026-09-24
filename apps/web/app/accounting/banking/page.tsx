import { ModuleWorklist } from "@/components/hub/ModuleWorklist";

/** The Banking tile's firm-level destination (D22, G3): which clients have
 *  statement lines still needing a person. A thin page over the one worklist
 *  component — the figure and its meaning belong to `domain/hub/tiles.py`. */
export default function Page() {
  return <ModuleWorklist tile="banking" heading="Banking" />;
}
