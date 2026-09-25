"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowLeft, Building2, ChevronDown, LayoutGrid } from "lucide-react";
import { cn } from "@/lib/utils";
import { useClientNav, CLIENT_SECTIONS } from "@/lib/workspace/ClientNavContext";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getLatestHealthScore } from "@/lib/services/health-score-compute";
import { HealthBadge } from "@/components/HealthBadge";
import { ClientSwitcher } from "@/components/ClientSwitcher";
import { UtilityCluster } from "@/components/shell/UtilityCluster";
import { ClientModuleGrid } from "@/components/client/ClientModuleGrid";

/**
 * The client workspace's whole chrome, in one 48px bar.
 *
 * It absorbed `ClientHeader` (the client's name, entity type, GSTIN and health
 * badge) and replaced two vertical surfaces at once: the 64px firm rail and
 * the 272px, twenty-one-item `ClientSections` list. Owner decision, 25-09 —
 * *"when inside a client they should see only the client stuff and we will
 * give the exit the client workspace button"*.
 *
 * ── FOUR THINGS HAVE TO BE ON IT, AND THREE OF THEM ARE 2.6's ──────────────
 *
 * `WorkspaceRail`'s header records what was missing inside a client before the
 * rail became constant: sign-out, Settings and any sign that ⌘K exists. Taking
 * the rail away again puts all three back at risk, so they are here —
 * `UtilityCluster`, the same component the rail renders, not a copy. The
 * fourth is the way OUT, which is the control the owner asked for and which
 * nothing in the old arrangement had: the rail's Clients icon was the exit,
 * and it was a workspace switcher that happened to work as one.
 *
 * ── THE MODULE NAME IS THE SWITCHER, AND IT OPENS THE SAME GRID ────────────
 *
 * `ClientModuleGrid` is rendered twice — as the page at `/clients/{id}` and as
 * this overlay — so the door and the switcher are one object. Two components
 * would be two vocabularies, which is the mistake this codebase keeps having
 * to delete. It also means the switcher carries the same live figures the door
 * does: a CA in Sales can see that Bank has 487 lines waiting without leaving
 * Sales.
 *
 * The overlay is the one place in this shell that animates, and deliberately:
 * it is something a person just asked for, so it may arrive. The grid itself
 * does not animate in — the front door must be readable in its first frame.
 */
interface ClientData {
  id: string;
  client_name: string;
  entity_type?: string;
  gstin?: string;
}

export function ClientTopBar({ onOpenSearch }: { onOpenSearch: () => void }) {
  const { clientId } = useClientNav();
  const pathname = usePathname();
  const [client, setClient] = useState<ClientData | null>(null);
  const [clientLoadFailed, setClientLoadFailed] = useState(false);
  const [health, setHealth] = useState<{ overall_score: number; trend: "improving" | "stable" | "declining" | null } | null>(null);
  const [gridOpen, setGridOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);

  // `usePathname()` is anchored to the "_placeholder" build param for the ID
  // segment under Cloudflare's rewrite — see ClientNavContext — but the
  // SECTION segment is static, so reading position 3 is safe. Deliberately not
  // `getSectionForPathname`, which defaults to "overview": on the front door
  // there is no active module, and saying Overview is active there would light
  // a card the CA is not standing on.
  const seg = pathname.split("/")[3] ?? "";
  const activeSection = CLIENT_SECTIONS.find((s) => s.id === seg)?.id ?? null;
  const activeLabel = CLIENT_SECTIONS.find((s) => s.id === activeSection)?.label ?? "All modules";

  useEffect(() => { setGridOpen(false); }, [pathname]);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setGridOpen(false);
    }
    if (gridOpen) window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [gridOpen]);

  useEffect(() => {
    setClient(null);
    setClientLoadFailed(false);
    // clientId is empty on the first render after a route change and is the
    // literal "_placeholder" on the statically-exported shell. Either sent to
    // PostgREST produces `id=eq.` against a uuid column — SQLSTATE 22P02, which
    // was logged in production on every client page load before this guard.
    if (!clientId || clientId === "_placeholder") return;
    const supabase = getSupabaseClient();
    supabase
      .from("clients")
      .select("id, client_name, entity_type, gstin")
      .eq("id", clientId)
      .single()
      .then(({ data, error }) => {
        // "Still loading" and "failed to load" must look different, or a failed
        // fetch leaves the bar saying "Loading…" for ever.
        if (data) setClient(data as ClientData);
        else {
          setClientLoadFailed(true);
          if (error) console.error("ClientTopBar: failed to load client", error);
        }
      });
    getLatestHealthScore(clientId)
      .then((h) => { if (h) setHealth({ overall_score: h.overall_score, trend: h.trend }); })
      .catch((e) => console.error("ClientTopBar: failed to load health score", e));
  }, [clientId]);

  return (
    <div className="relative shrink-0">
      <header className="flex items-center gap-2 md:gap-3 h-12 px-2 md:px-4 bg-white border-b border-gray-200">
        {/* The way out. First control on the bar, because with the rail gone it
            is the only one, and a CA must never have to hunt for it. */}
        <Link
          href="/clients"
          title="Exit client workspace"
          className="flex items-center gap-1.5 h-8 px-2 rounded-lg text-xs font-medium text-ps-hint hover:text-ps-ink hover:bg-ps-bg transition-colors shrink-0"
        >
          <ArrowLeft size={14} />
          <span className="hidden sm:inline">All clients</span>
        </Link>

        <span className="h-5 w-px bg-ps-border shrink-0" aria-hidden />

        <Building2 size={15} className="text-gray-400 shrink-0 hidden sm:block" />

        <div className="flex items-center gap-2 md:gap-3 min-w-0">
          {/* The client's name IS the switcher — but only once we know the
              name. Offering a picker over "Couldn't load client" invites a CA
              to navigate from a header that does not know where it is. */}
          {client ? (
            <ClientSwitcher
              clientId={clientId}
              clientName={client.client_name}
              className="min-w-0 flex-shrink"
            />
          ) : (
            <span className={cn("text-sm font-semibold truncate",
                                clientLoadFailed ? "text-state-problem" : "text-ps-hint")}>
              {clientLoadFailed ? "Couldn't load client" : "Loading…"}
            </span>
          )}
          {client?.entity_type && (
            <span className="text-3xs font-medium px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 shrink-0 hidden md:inline">
              {client.entity_type}
            </span>
          )}
          {client?.gstin && (
            <span className="text-3xs font-mono text-gray-500 shrink-0 hidden xl:inline">
              {client.gstin}
            </span>
          )}
        </div>

        {/* The module switcher. A chevron rather than a label change when open:
            the button is the anchor the grid flies from, so it stays put. */}
        <button
          ref={triggerRef}
          onClick={() => setGridOpen((v) => !v)}
          aria-expanded={gridOpen}
          aria-haspopup="menu"
          className={cn(
            "flex items-center gap-1.5 h-8 px-2.5 rounded-lg text-xs font-semibold transition-colors shrink-0",
            gridOpen ? "bg-brand text-white" : "text-ps-ink hover:bg-ps-bg"
          )}
        >
          <LayoutGrid size={13} className="shrink-0" />
          <span className="truncate max-w-[9rem]">{activeLabel}</span>
          <ChevronDown size={13} className={cn("shrink-0 transition-transform", gridOpen && "rotate-180")} />
        </button>

        <div className="flex-1 min-w-0" />

        {health && (
          <HealthBadge score={health.overall_score} size="sm" showLabel trend={health.trend}
                       href={`/clients/${clientId}/health/`} />
        )}

        {/* The search MODAL is AppShell's — one instance, one open state, one
            ⌘K listener — so the handler is threaded down rather than a second
            copy being held here. */}
        <UtilityCluster orientation="bar" onOpenSearch={onOpenSearch} />
      </header>

      {gridOpen && (
        <>
          <div
            className="fixed inset-0 top-12 z-30 bg-brand/20 backdrop-blur-[2px]"
            onClick={() => setGridOpen(false)}
          />
          <div
            role="menu"
            aria-label="Modules"
            className="module-grid-overlay absolute inset-x-0 top-full z-40 max-h-[calc(100vh-3rem)] overflow-y-auto border-b border-ps-border bg-white shadow-xl"
          >
            <ClientModuleGrid
              clientId={clientId}
              variant="overlay"
              activeSection={activeSection}
              onNavigate={() => setGridOpen(false)}
            />
          </div>
        </>
      )}
    </div>
  );
}
