"use client";

import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth, usePermissions } from "@/lib/auth/AuthContext";
import { useWorkspace } from "@/lib/workspace/WorkspaceContext";
import { WORKSPACE_CONFIGS } from "@/lib/workspace/workspaceConfig";
import { canAccessWorkspace } from "@/lib/auth/permissions";
import { useNavShellCollapse } from "@/components/shell/NavShell";
import { UtilityCluster } from "@/components/shell/UtilityCluster";

/**
 * The product's spine: the workspaces, search, Settings and the account menu.
 *
 * It was `components/ActivityRail.tsx` and rendered at FIRM LEVEL ONLY, which
 * is the defect `NavShell`'s header records — inside a client workspace there
 * was no way to sign out, no way to reach Settings and nothing saying ⌘K
 * existed. 2.6 made it constant to close that.
 *
 * ⚠️ IT IS FIRM-LEVEL AGAIN, AND THE FIX IT CARRIED IS NOT (owner decision,
 * 25-09: inside a client a CA should see only the client's own things, with
 * one control out). What 2.6 actually fixed was the ABSENCE of search,
 * Settings and sign-out, not the presence of the rail — so those three moved
 * into `UtilityCluster`, which this rail renders vertically and
 * `ClientTopBar` renders horizontally. Neither shell can exist without it:
 * `AppShell` returns exactly one of the two and never neither, which is what
 * a guard asserts.
 *
 * ⚠️ IT IS 64px WIDE AND WAS 52px, AND THAT IS A MEASUREMENT. At 52px with
 * this label size, "Relationships" (~60px) and "Engagements" (~51px) did not
 * fit and were cut off mid-word — they rendered as "elationship" and
 * "ngagement" on every firm screen, which the 24-09 smoke shots show. 64px
 * fits ten of the twelve outright. The last two carry a `railLabel` — the
 * SAME WORD with a U+200B in it, so the browser breaks it where a person
 * would ("Relation / ships") rather than showing an abbreviation somebody has
 * to learn; the width that would fit them on one line is about 84px, which is
 * not an icon rail any more. `overflow-x-hidden` on the aside is the backstop
 * for a label that still cannot fit.
 */
export function WorkspaceRail({ onOpenSearch }: { onOpenSearch: () => void }) {
  const { activeWorkspace, setWorkspace } = useWorkspace();
  const { userRole } = useAuth();
  const { can, resolved } = usePermissions();
  // Null inside the mobile drawer, which renders the rail outside the shell's
  // desktop branch: there is nothing to collapse there, so no control is shown.
  const collapse = useNavShellCollapse();

  // Two gates, and they answer different questions. `canAccessWorkspace` is the
  // product's own role rule (Practice exposes fee economics; Deadlines and Work
  // are hidden from delivery staff). `requires` is the backend's rbac pair, set
  // only on a workspace whose every screen is governed by one — today just
  // Payroll — so the rail does not offer a tile that opens an empty panel.
  //
  // ⚠️ IT HIDES ONLY ONCE `resolved`, which is deliberate and is the one place
  // in this product that reads that flag. `can()` fails CLOSED while the
  // permission map is still in flight, so gating on it alone would leave the
  // Payroll tile absent on first paint for EVERYONE and pop it in a moment
  // later — on the rail, which is the product's spine. Showing it until we
  // know costs an Executive one frame of a tile they cannot use, and this is
  // not a security boundary: `rbac()` is, on the server, and the screens
  // behind it answer 403 either way.
  const visibleWorkspaces = WORKSPACE_CONFIGS.filter(
    (ws) =>
      canAccessWorkspace(ws.id, userRole) &&
      (!ws.requires || !resolved || can(ws.requires[0], ws.requires[1])),
  );

  return (
    <aside className="relative flex flex-col h-full w-[64px] shrink-0 bg-brand border-r border-white/10 z-10 overflow-x-hidden">
      {/* Logo, and the one collapse control. It lives here rather than in the
          panel because a control inside the thing it hides has to be drawn
          twice — which is exactly what ClientContextPanel did. */}
      <div className="flex items-center justify-center gap-1 h-14 border-b border-white/10 shrink-0">
        <div className="w-7 h-7 rounded-[8px] bg-brand flex items-center justify-center text-2xs font-bold text-white shadow-[0_0_16px_rgba(59,130,246,0.35)]">
          P
        </div>
        {collapse && (
          <button
            onClick={collapse.toggle}
            title={collapse.collapsed ? "Show navigation" : "Hide navigation"}
            aria-label={collapse.collapsed ? "Show navigation" : "Hide navigation"}
            className="flex items-center justify-center w-6 h-6 rounded-md text-slate-500 hover:text-white hover:bg-white/10 transition-colors"
          >
            {collapse.collapsed ? <PanelLeftOpen size={13} /> : <PanelLeftClose size={13} />}
          </button>
        )}
      </div>

      {/* Workspace icons — scroll when they exceed the rail height (min-h-0 lets
          this flex child shrink; scrollbar hidden to keep the rail clean).
          ⚠️ THE PITCH IS 52px AND WAS 56, AND THAT IS A MEASUREMENT, the same
          kind 2.6 took on the label width. Payroll made this a THIRTEENTH tile
          and the first smoke walk of it showed twelve: at 56px the column is
          13×56 + 56 header + 24 padding + 130 of bottom utilities = 938 against
          a 900px viewport, so Engagements fell off the end — scrollable, with
          the scrollbar hidden, so nothing on screen said it was there. `gap-1`
          and a 32px hit area buy back 76px and put all thirteen inside 880.
          Thirteen is what D1's fifteen hub tiles and twelve workspaces have
          converged on; a fourteenth needs the rail rethought, not another 4px.
          A short viewport still scrolls, as it did at twelve. */}
      <nav className="flex flex-col items-center gap-1 py-3 flex-1 min-h-0 overflow-y-auto overflow-x-hidden [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {visibleWorkspaces.map((ws) => {
          const Icon = ws.icon;
          const isActive = ws.id === activeWorkspace;
          return (
            <div key={ws.id} className="flex flex-col items-center gap-0.5 w-full px-0.5">
              <button
                onClick={() => setWorkspace(ws.id)}
                title={ws.description}
                className={cn(
                  "relative flex items-center justify-center w-8 h-8 rounded-[9px] transition-all duration-100 mx-auto",
                  isActive ? "bg-brand" : "hover:bg-white/10"
                )}
              >
                {isActive && (
                  <span className="absolute left-[-1px] h-5 w-[3px] rounded-r-[2px] bg-brand" />
                )}
                <Icon
                  size={16}
                  className={cn(
                    "shrink-0 transition-colors duration-100",
                    isActive ? "text-white" : "text-slate-500"
                  )}
                />
              </button>
              {/* `break-words`, NOT `truncate`: truncate sets white-space:nowrap,
                  which would block the U+200B break `railLabel` exists for and
                  put the ellipsis back. `overflow-x-hidden` on the aside is the
                  backstop for a label that still cannot fit. */}
              <span
                className={cn(
                  "w-full text-center break-words text-3xs font-medium leading-tight select-none",
                  isActive ? "text-white" : "text-slate-500"
                )}
              >
                {ws.railLabel ?? ws.label}
              </span>
            </div>
          );
        })}
      </nav>

      <UtilityCluster orientation="rail" onOpenSearch={onOpenSearch} />
    </aside>
  );
}
