"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ChevronsUpDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import type { ClientSummary } from "@/lib/api";
import { arrayOrEmpty } from "@/lib/api/shape";
import { Combobox } from "@/components/ui/combobox";
import { switchClientPath } from "@/lib/workspace/clientPath";

/**
 * Move from one client to the next without going back out to the list.
 *
 * A practice does the same job across its whole book — June's bank
 * reconciliation for four clients, then June's GSTR-1 for the same four — and
 * the only way through was Bank → back to /clients → pick → Bank again, twice
 * per client. Phase 2.3.
 *
 * WHERE IT LANDS IS `switchClientPath`, WHICH CARRIES THE SECTION AND NOT THE
 * DOCUMENT. That rule lives in `lib/workspace/clientPath.ts` with its own
 * tests, and `scripts/a-client-switch-lands-on-the-same-section.test.ts` runs
 * it over the real route tree; the reason it matters is that carrying the whole
 * path would open one client's invoice inside another client's workspace.
 *
 * THE LIST COMES FROM `GET /api/clients`, NOT PostgREST, and that is a
 * permission decision rather than a style one: the endpoint is
 * `rbac("client","read")` and applies `effective_client_ids`, so an Executive
 * sees the clients they are assigned to and nobody else's. Read straight from
 * the browser the SELECT policy is firm-scoped with no assignment test, and
 * the switcher would quietly name every client in the firm.
 *
 * IT DEGRADES TO THE NAME. The header already fetches the current client for
 * its own heading; that value is the `placeholder` here, so a failed or slow
 * list leaves the client's name on screen with nothing to open, rather than
 * blanking the header. A switcher that cannot list is a missing convenience;
 * a header that cannot name the client is a screen you cannot trust.
 */
export function ClientSwitcher({
  clientId,
  clientName,
  className,
}: {
  clientId: string;
  /** What the header already resolved — shown while the list is unavailable. */
  clientName: string;
  className?: string;
}) {
  const router = useRouter();
  const [clients, setClients] = useState<ClientSummary[]>([]);

  useEffect(() => {
    let live = true;
    api.clients
      .list()
      .then((res) => {
        if (!live) return;
        // `success: false` comes back as HTTP 200 from several routers, so the
        // envelope is checked before the payload — and the payload is checked
        // before it is treated as a list (lib/api/shape.ts).
        if (!res?.success) return;
        setClients(
          arrayOrEmpty<ClientSummary>(res.data?.clients).filter(
            (c) => c && typeof c.id === "string",
          ),
        );
      })
      .catch(() => {
        /* the name stays on screen; see the note above */
      });
    return () => {
      live = false;
    };
  }, []);

  const current = clients.find((c) => c.id === clientId) ?? null;

  return (
    <Combobox<ClientSummary>
      chrome="plain"
      panelDensity="spacious"
      ariaLabel="Switch client"
      placeholder={clientName}
      options={clients}
      value={current}
      getOptionId={(c) => c.id}
      getLabel={(c) => c.client_name}
      getSecondary={(c) => c.entity_type ?? undefined}
      emptyText="No other client"
      onChange={(v) => {
        const picked = Array.isArray(v) ? v[0] : v;
        if (!picked || picked.id === clientId) return;
        // `window` is read in the handler, never during render — this app is a
        // static export and touching it while rendering breaks the build.
        router.push(switchClientPath(window.location.pathname, picked.id));
      }}
      renderTrigger={(c) => (
        <span className="inline-flex items-center gap-1.5 min-w-0">
          <span className="truncate text-sm font-semibold text-brand">{c.client_name}</span>
          <ChevronsUpDown size={13} className="shrink-0 text-ps-hint" />
        </span>
      )}
      className={cn("min-w-0 max-w-full", className)}
    />
  );
}
