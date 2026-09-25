"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowLeft, SearchX } from "lucide-react";
import { CLIENT_SECTIONS, useClientNav } from "@/lib/workspace/ClientNavContext";
import {
  clientSectionSegment,
  gateVerdict,
  refusalAddress,
} from "@/lib/workspace/clientGate";
import { EmptyState, ErrorState } from "@/components/ui/states";

/**
 * WHAT A CLIENT SCREEN RENDERS WHEN THE ADDRESS NAMES NO CLIENT.
 *
 * Until this, it rendered navigation and nothing else, for ever. Every screen
 * under `/clients/[id]/**` opens its loader with some spelling of
 *
 *     if (!clientId || clientId === "_placeholder") return;
 *
 * inside a `useEffect`, so `setLoading(false)` never runs and the page holds
 * its skeleton — and a CA arriving from a stale bookmark or a deleted client
 * gets exactly that: a spinner that is never going to stop. Forty routes, one
 * shape, which is why the answer is one gate in the layout they all share
 * rather than forty empty states.
 *
 * ── IT IS A GATE, NOT A LOADER ────────────────────────────────────────────
 *
 * The screens keep their own loading and error states; this decides only
 * whether there is a subject for them to load. `resolving` renders the
 * children, so a real client's screens behave exactly as they did — the gate
 * is inert on the path every CA actually walks, and only a client that cannot
 * be resolved sees anything new.
 *
 * ── STILL LOADING IS NOT NOT-FOUND, AND NEITHER IS A FAILED LOOKUP ────────
 *
 * `ClientResolution` keeps those three apart on purpose (see its own comment).
 * Saying "no such client" over a network blip would be a worse wrong answer
 * than the spinner this replaces, because it reads as a fact about the firm's
 * data rather than about the request — so `unavailable` gets the retryable
 * error state and never the not-found one.
 *
 * ── THE BODY NAMES THE MODULE AND THE ADDRESS ─────────────────────────────
 *
 * The module comes from `CLIENT_SECTIONS`, the one client-section vocabulary.
 * The address, the section segment and the verdict itself all come from
 * `clientGate.ts`, which has NO imports so a `node --test` guard can exercise
 * the decision as behaviour rather than assert a shape of source. This file
 * renders and decides nothing.
 *
 * BOTH refusals state the address, because the module alone does not identify
 * the screen: Reports is five routes and Sales is four, so "Sales — no client
 * selected" four times over says less than the thing the visitor actually
 * asked for. The first draft named only the module, and turned six identical
 * bodies into five smaller groups of identical bodies — which passes `pnpm
 * smoke`'s duplicate-body check with no headroom left, and that is the
 * exemption this approach was chosen OVER rather than a fix. Naming the screen
 * is what makes each refusal its own; the check having room again is the
 * consequence.
 */
function BackToClients() {
  return (
    <Link
      href="/clients"
      className="inline-flex items-center gap-1.5 rounded-lg border border-ps-border bg-white px-4 py-2 text-sm font-medium text-ps-body transition-colors hover:bg-ps-hover"
    >
      <ArrowLeft size={14} />
      All clients
    </Link>
  );
}

export function ClientResolutionGate({ children }: { children: React.ReactNode }) {
  const { clientId, resolution, reloadClient } = useClientNav();
  const pathname = usePathname();

  const verdict = gateVerdict(resolution, pathname);
  if (verdict === "render") return <>{children}</>;

  const address = refusalAddress(clientId, pathname);
  const segment = clientSectionSegment(pathname);
  const where =
    CLIENT_SECTIONS.find((s) => s.id === segment)?.label ?? "Client workspace";

  if (verdict === "unavailable") {
    return (
      <div className="p-6">
        <ErrorState
          title={`${where} — could not check this client`}
          message={`The lookup for ${address} failed, so whether this client exists is not known. This is a problem with the request, not with your data.`}
          onRetry={reloadClient}
        />
      </div>
    );
  }

  return (
    <div className="p-6">
      <EmptyState
        icon={<SearchX size={32} />}
        title={
          verdict === "unnamed"
            ? `${where} — no client selected`
            : `${where} — no such client`
        }
        description={
          verdict === "unnamed"
            ? `${address} names no client, so there is nothing to show here. Choose one from the client list.`
            : `${address} names a client this firm does not have. It may have been deleted, or the link may be out of date.`
        }
        action={<BackToClients />}
      />
    </div>
  );
}
