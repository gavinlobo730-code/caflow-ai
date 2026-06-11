"use client";

import { useState } from "react";
import Link from "next/link";
import { Search, Settings, LogOut } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth/AuthContext";
import { useWorkspace } from "@/lib/workspace/WorkspaceContext";
import { WORKSPACE_CONFIGS } from "@/lib/workspace/workspaceConfig";
import { canAccessWorkspace } from "@/lib/auth/permissions";

interface ActivityRailProps {
  onOpenSearch: () => void;
}

export function ActivityRail({ onOpenSearch }: ActivityRailProps) {
  const { activeWorkspace, setWorkspace } = useWorkspace();
  const { user, userRole, signOut } = useAuth();
  const [avatarMenuOpen, setAvatarMenuOpen] = useState(false);

  const initials = user?.email?.slice(0, 2).toUpperCase() ?? "CA";

  const visibleWorkspaces = WORKSPACE_CONFIGS.filter((ws) =>
    canAccessWorkspace(ws.id, userRole)
  );

  return (
    <aside className="relative flex flex-col h-full w-[52px] shrink-0 bg-white border-r border-[#BFDBFE] z-10">
      {/* Logo */}
      <div className="flex items-center justify-center h-14 border-b border-[#BFDBFE] shrink-0">
        <div className="w-7 h-7 rounded-[8px] bg-blue-600 flex items-center justify-center text-[11px] font-bold text-white shadow-[0_0_16px_rgba(59,130,246,0.35)]">
          P
        </div>
      </div>

      {/* Workspace icons */}
      <nav className="flex flex-col items-center gap-1.5 py-3 flex-1 overflow-hidden">
        {visibleWorkspaces.map((ws) => {
          const Icon = ws.icon;
          const isActive = ws.id === activeWorkspace;
          return (
            <div key={ws.id} className="flex flex-col items-center gap-0.5 w-full">
              <button
                onClick={() => setWorkspace(ws.id)}
                title={ws.description}
                className={cn(
                  "relative flex items-center justify-center w-9 h-9 rounded-[9px] transition-all duration-100 mx-auto",
                  isActive
                    ? "bg-[#DBEAFE]"
                    : "hover:bg-[#DBEAFE]"
                )}
              >
                {isActive && (
                  <span className="absolute left-[-1px] h-5 w-[3px] rounded-r-[2px] bg-blue-600 shadow-[0_0_8px_rgba(59,130,246,0.5)]" />
                )}
                <Icon
                  size={16}
                  className={cn(
                    "shrink-0 transition-colors duration-100",
                    isActive ? "text-blue-600" : "text-[#94A3B8]"
                  )}
                />
              </button>
              <span
                className={cn(
                  "text-[9px] font-medium leading-none select-none",
                  isActive ? "text-blue-600" : "text-[#94A3B8]"
                )}
              >
                {ws.label}
              </span>
            </div>
          );
        })}
      </nav>

      {/* Bottom utilities */}
      <div className="flex flex-col items-center gap-2 pb-3 shrink-0 border-t border-[#BFDBFE] pt-3">
        <button
          onClick={onOpenSearch}
          title="Search (⌘K)"
          className="flex items-center justify-center w-9 h-9 rounded-[9px] text-[#94A3B8] hover:text-[#64748B] hover:bg-[#DBEAFE] transition-all duration-100"
        >
          <Search size={15} />
        </button>
        <Link
          href="/settings"
          title="Settings"
          className="flex items-center justify-center w-9 h-9 rounded-[9px] text-[#94A3B8] hover:text-[#64748B] hover:bg-[#DBEAFE] transition-all duration-100"
        >
          <Settings size={15} />
        </Link>

        {/* Avatar with sign-out popover */}
        <div className="relative">
          <button
            onClick={() => setAvatarMenuOpen((v) => !v)}
            title={user?.email ?? "Account"}
            className="w-7 h-7 rounded-full bg-blue-600 flex items-center justify-center text-[10px] font-bold text-white hover:opacity-80 transition-opacity shrink-0"
          >
            {initials}
          </button>
          {avatarMenuOpen && (
            <>
              {/* Backdrop */}
              <div
                className="fixed inset-0 z-20"
                onClick={() => setAvatarMenuOpen(false)}
              />
              {/* Popover */}
              <div className="absolute left-full bottom-0 ml-2 z-30 w-48 bg-white border border-[#BFDBFE] rounded-xl shadow-[0_8px_24px_rgba(0,0,0,0.5)] p-1.5">
                <div className="px-3 py-2 border-b border-[#BFDBFE] mb-1">
                  <p className="text-[12px] font-semibold text-[#1E293B] truncate">
                    {user?.email ?? "user@firm.com"}
                  </p>
                  <p className="text-[10px] text-[#94A3B8] truncate mt-0.5">
                    {userRole ?? "Partner"}
                  </p>
                </div>
                <button
                  onClick={() => {
                    setAvatarMenuOpen(false);
                    signOut();
                  }}
                  className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-[12.5px] text-[#64748B] hover:text-red-600 hover:bg-[#DBEAFE] transition-colors"
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
