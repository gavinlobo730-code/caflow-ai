import { ModuleWorklist } from "@/components/hub/ModuleWorklist";

/** The Fixed Assets tile's firm-level destination (D22, G3): which clients
 *  have assets whose depreciation has not been posted.
 *
 *  ⚠️ THIS PATH WAS A `MovedToClientWorkspace` TOMBSTONE, and replacing it is
 *  the point rather than a coincidence. That page's whole content was "Fixed
 *  Assets moved to the client workspace — choose a client", which renders, so
 *  a hub tile showing a real number and landing here read as a working screen.
 *  A worklist is that same sentence with the clients that need choosing
 *  already listed, and it keeps the retirement decision intact: the register
 *  still lives only in the client workspace, and every row opens it there. */
export default function Page() {
  return <ModuleWorklist tile="fixed_assets" heading="Fixed Assets" />;
}
