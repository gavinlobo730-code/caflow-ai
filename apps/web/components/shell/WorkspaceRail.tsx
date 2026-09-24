"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Search, Settings, LogOut, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth/AuthContext";
import { useWorkspace } from "@/lib/workspace/WorkspaceContext";
import { WORKSPACE_CONFIGS } from "@/lib/workspace/workspaceConfig";
import { canAccessWorkspace } from "@/lib/auth/permissions";
import { useNavShellCollapse } from "@/components/shell/NavShell";

/**
 * The product's spine: the workspaces, search, Settings and the account menu.
 *
 * It was `components/ActivityRail.tsx` and rendered at FIRM LEVEL ONLY, which
 * is the defect `NavShell`'s header records — inside a client workspace there
 * was no way to sign out, no way to reach Settings and nothing saying ⌘K
 * existed. It is now on every screen a signed-in CA sees.
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
  const { user, userRole, signOut, fullName } = useAuth();
  const [avatarMenuOpen, setAvatarMenuOpen] = useState(false);
  const pathname = usePathname();
  const isSettingsRoute = pathname.startsWith("/settings");
  // Null inside the mobile drawer, which renders the rail outside the shell's
  // desktop branch: there is nothing to collapse there, so no control is shown.
  const collapse = useNavShellCollapse();

  const initials = fullName
    ? fullName.trim().split(" ").filter(Boolean).slice(0, 2).map((n) => n[0].toUpperCase()).join("")
    : user?.email?.slice(0, 2).toUpperCase() ?? "CA";

  const visibleWorkspaces = WORKSPACE_CONFIGS.filter((ws) =>
    canAccessWorkspace(ws.id, userRole)
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
          this flex child shrink; scrollbar hidden to keep the rail clean) */}
      <nav className="flex flex-col items-center gap-1.5 py-3 flex-1 min-h-0 overflow-y-auto overflow-x-hidden [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {visibleWorkspaces.map((ws) => {
          const Icon = ws.icon;
          const isActive = ws.id === activeWorkspace;
          return (
            <div key={ws.id} className="flex flex-col items-center gap-0.5 w-full px-0.5">
              <button
                onClick={() => setWorkspace(ws.id)}
                title={ws.description}
                className={cn(
                  "relative flex items-center justify-center w-9 h-9 rounded-[9px] transition-all duration-100 mx-auto",
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

      {/* Bottom utilities. These are the three that did not exist inside a
          client workspace before this rail became constant. */}
      <div className="flex flex-col items-center gap-2 pb-3 shrink-0 border-t border-white/10 pt-3">
        <button
          onClick={onOpenSearch}
          title="Search (⌘K)"
          className="flex items-center justify-center w-9 h-9 rounded-[9px] text-slate-500 hover:text-white hover:bg-white/10 transition-all duration-100"
        >
          <Search size={15} />
        </button>
        <Link
          href="/settings"
          title="Settings"
          className={cn(
            "relative flex items-center justify-center w-9 h-9 rounded-[9px] transition-all duration-100",
            isSettingsRoute
              ? "bg-brand text-white"
              : "text-slate-500 hover:text-white hover:bg-white/10"
          )}
        >
          {isSettingsRoute && (
            <span className="absolute left-[-1px] h-5 w-[3px] rounded-r-[2px] bg-brand" />
          )}
          <Settings size={15} />
        </Link>

        {/* Avatar with sign-out popover */}
        <div className="relative">
          <button
            onClick={() => setAvatarMenuOpen((v) => !v)}
            title={user?.email ?? "Account"}
            className="w-7 h-7 rounded-full bg-brand flex items-center justify-center text-3xs font-bold text-white hover:opacity-80 transition-opacity shrink-0"
          >
            {initials}
          </button>
          {avatarMenuOpen && (
            <>
              <div
                className="fixed inset-0 z-20"
                onClick={() => setAvatarMenuOpen(false)}
              />
              <div className="absolute left-full bottom-0 ml-2 z-30 w-48 bg-[#1e2d5e] border border-white/10 rounded-xl shadow-[0_8px_24px_rgba(0,0,0,0.5)] p-1.5">
                <div className="px-3 py-2 border-b border-white/10 mb-1">
                  <p className="text-xs font-semibold text-white truncate">
                    {user?.email ?? "user@firm.com"}
                  </p>
                  <p className="text-3xs text-slate-500 truncate mt-0.5">
                    {userRole ?? "Partner"}
                  </p>
                </div>
                <button
                  onClick={() => {
                    setAvatarMenuOpen(false);
                    signOut();
                  }}
                  className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-xs text-slate-400 hover:text-red-400 hover:bg-white/10 transition-colors"
                >
                  <LogOut size={13} />
                  Sign out
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </aside>
  );
}
