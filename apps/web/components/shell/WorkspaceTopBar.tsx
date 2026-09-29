"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { ChevronDown, LayoutGrid } from "lucide-react";
import { cn } from "@/lib/utils";
import { useWorkspace } from "@/lib/workspace/WorkspaceContext";
import { WORKSPACE_CONFIGS } from "@/lib/workspace/workspaceConfig";
import { UtilityCluster } from "@/components/shell/UtilityCluster";
import { WorkspaceMegaMenu } from "@/components/shell/WorkspaceMegaMenu";

/**
 * The firm-level shell's whole chrome, in one bar — `WorkspaceRail` (64px)
 * plus `ContextPanel` (220px) collapsed into the single-bar shape `ClientTopBar`
 * already proved for the client workspace, so the product reads as one
 * navigation idiom rather than two (a sidebar outside a client, a bar inside
 * one). See WorkspaceMegaMenu's own header for what happened to the panel's
 * content: reused unchanged, inside the overlay this bar opens.
 *
 * NAVY WHERE THE CLIENT BAR IS WHITE, AND THAT IS DELIBERATE, NOT DRIFT. The
 * rail this replaces was always `bg-brand` — the firm's OWN chrome, on screen
 * whichever client (or no client) a CA is looking at — while `ClientTopBar`
 * is white because it sits inside one client's own books. Keeping that colour
 * split means the surface itself still tells a CA which of the two they are
 * in, at a glance, which a redesign that made both bars identical would lose.
 */
export function WorkspaceTopBar({ onOpenSearch }: { onOpenSearch: () => void }) {
  const { activeWorkspace } = useWorkspace();
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => { setMenuOpen(false); }, [pathname]);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setMenuOpen(false);
    }
    if (menuOpen) window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [menuOpen]);

  const activeConfig = WORKSPACE_CONFIGS.find((ws) => ws.id === activeWorkspace) ?? null;
  const ActiveIcon = activeConfig?.icon ?? LayoutGrid;

  return (
    <div className="relative shrink-0">
      <header className="flex h-12 items-center gap-2 bg-brand px-2 md:gap-3 md:px-4">
        <div className="flex shrink-0 items-center gap-2 border-r border-white/10 pr-2.5 md:pr-3.5">
          <div className="flex h-7 w-7 items-center justify-center rounded-[8px] bg-white/10 text-sm font-bold text-white">
            P
          </div>
          <span className="hidden text-sm font-bold tracking-tight text-white sm:inline">
            PracticeSync
          </span>
        </div>

        <button
          onClick={() => setMenuOpen((v) => !v)}
          aria-expanded={menuOpen}
          aria-haspopup="menu"
          className={cn(
            "flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-2.5 text-xs font-semibold text-white transition-colors",
            menuOpen ? "bg-white/20" : "bg-white/10 hover:bg-white/15",
          )}
        >
          <ActiveIcon size={14} className="shrink-0" />
          <span className="max-w-[9rem] truncate">{activeConfig?.label ?? "Menu"}</span>
          <ChevronDown size={13} className={cn("shrink-0 transition-transform", menuOpen && "rotate-180")} />
        </button>

        <div className="min-w-0 flex-1" />

        <UtilityCluster orientation="bar-dark" onOpenSearch={onOpenSearch} />
      </header>

      {menuOpen && (
        <>
          <div
            className="fixed inset-0 top-12 z-30 bg-brand/20 backdrop-blur-[2px]"
            onClick={() => setMenuOpen(false)}
          />
          <div
            role="menu"
            aria-label="Workspaces"
            className="absolute inset-x-0 top-full z-40 max-h-[calc(100vh-3rem)] overflow-hidden border-b border-ps-border bg-white shadow-xl"
          >
            <WorkspaceMegaMenu onOpenSearch={() => { setMenuOpen(false); onOpenSearch(); }} />
          </div>
        </>
      )}
    </div>
  );
}
