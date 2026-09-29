"use client";

import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth, usePermissions } from "@/lib/auth/AuthContext";
import { useWorkspace } from "@/lib/workspace/WorkspaceContext";
import { WORKSPACE_CONFIGS, type WorkspaceId } from "@/lib/workspace/workspaceConfig";
import { canAccessWorkspace } from "@/lib/auth/permissions";
import { ContextPanel } from "@/components/ContextPanel";

/**
 * The firm-level "sidebar", as an overlay rather than a permanent column.
 *
 * WHAT THIS REPLACES. `WorkspaceRail` (64px, vertical, always on screen) plus
 * `ContextPanel` (220px, always on screen) — two columns, 284px, on every firm
 * screen. `ClientModuleGrid` proved the shape this wants instead: a switcher
 * that opens on demand and closes on navigate, so the screen underneath it
 * gets the whole width back. This is that shape at firm level, and it is a
 * MEGA MENU rather than a flat grid because — unlike a client's `CLIENT_
 * SECTIONS`, which are all leaves — a firm workspace's own sub-navigation is
 * exactly what `ContextPanel` already renders, and duplicating it as a
 * second, flatter list here is the "two vocabularies" mistake this codebase
 * keeps recording (see ContextPanel's own history). So this reuses it
 * unchanged: the left column picks a workspace, the right column IS that
 * workspace's ordinary panel, rendered wider than its old 220px cage.
 *
 * `ContextPanel`'s `workspaceOverride` prop exists for exactly this — it lets
 * this menu preview a workspace the URL has not navigated to yet, so hovering
 * "Payroll" while standing on a Clients page shows Payroll's own list without
 * a click.
 *
 * SAME VISIBILITY RULE AS THE RAIL IT REPLACES: `canAccessWorkspace` (product
 * role rule) AND, where a workspace's `requires` names one rbac pair, `can()`
 * — asked only once `resolved`, so a permission map still in flight does not
 * flash the tile and then pull it (WorkspaceRail's own comment explains why
 * that one-frame delay is deliberate here, not a bug).
 *
 * CLOSING IS THE CALLER'S JOB, ON NAVIGATION — same as `ClientModuleGrid`:
 * `WorkspaceTopBar` closes this on every pathname change. Unlike that grid,
 * no per-link onClick here also closes it early, because doing that would
 * mean editing all thirteen reused panel components rather than none of
 * them; the gap is at most one route transition's worth of overlay lingering
 * on screen, not a broken link.
 */
export function WorkspaceMegaMenu({ onOpenSearch }: { onOpenSearch: () => void }) {
  const { activeWorkspace } = useWorkspace();
  const { userRole } = useAuth();
  const { can, resolved } = usePermissions();
  const [hovered, setHovered] = useState<WorkspaceId | null>(null);

  const visibleWorkspaces = WORKSPACE_CONFIGS.filter(
    (ws) =>
      canAccessWorkspace(ws.id, userRole) &&
      (!ws.requires || !resolved || can(ws.requires[0], ws.requires[1])),
  );

  const shown = hovered ?? activeWorkspace ?? "home";

  return (
    // Side by side from `sm` up (two independently-scrolling columns, each
    // capped by the shared max-height). Below `sm` the two columns cannot fit
    // a phone's width at once (196px + 260px = 456px), so they stack — the
    // workspace list gets a capped height of its own so the panel underneath,
    // which is what someone actually came here to click, keeps most of the
    // room rather than being pushed below a 13-item list.
    <div className="flex max-h-[75vh] min-h-[22rem] flex-col sm:flex-row">
      <nav
        aria-label="Workspaces"
        className="max-h-40 shrink-0 overflow-y-auto border-b border-ps-border bg-ps-bg/60 py-2 sm:max-h-none sm:w-[196px] sm:border-b-0 sm:border-r"
      >
        {visibleWorkspaces.map((ws) => {
          const Icon = ws.icon;
          const isShown = ws.id === shown;
          return (
            <button
              key={ws.id}
              onMouseEnter={() => setHovered(ws.id)}
              onFocus={() => setHovered(ws.id)}
              onClick={() => setHovered(ws.id)}
              aria-current={isShown ? "true" : undefined}
              className={cn(
                "flex w-full items-center gap-2.5 border-l-2 px-4 py-2.5 text-left text-xs font-semibold transition-colors",
                isShown
                  ? "border-brand bg-white text-brand"
                  : "border-transparent text-ps-label hover:bg-white/60 hover:text-ps-ink",
              )}
            >
              <Icon size={15} className="shrink-0" />
              <span className="flex-1 truncate">{ws.label}</span>
              <ChevronRight
                size={13}
                className={cn("shrink-0 transition-opacity", isShown ? "opacity-100" : "opacity-0")}
              />
            </button>
          );
        })}
      </nav>
      <div className="min-h-0 flex-1 overflow-y-auto bg-white sm:w-[260px] sm:flex-none">
        <ContextPanel onOpenSearch={onOpenSearch} workspaceOverride={shown} />
      </div>
    </div>
  );
}
