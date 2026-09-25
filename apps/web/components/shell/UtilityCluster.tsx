"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Search, Settings, LogOut } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth/AuthContext";

/**
 * Search, Settings and the account menu — the three things a signed-in CA must
 * be able to reach from ANY screen.
 *
 * ⚠️ THIS EXISTS BECAUSE 2.6's FIX IS EASY TO UNDO BY ACCIDENT, and this change
 * is exactly the change that would have undone it. `WorkspaceRail`'s own header
 * records what was wrong before it became constant: `signOut` appeared in ONE
 * navigation surface in this product and the only `href="/settings"` outside
 * the settings screens themselves was in the same one — so inside a client
 * workspace a CA could not sign out and could not reach Settings without first
 * leaving the client, and ⌘K worked with nothing on screen saying so.
 *
 * 2.6 fixed that by making the rail constant. This redesign REMOVES the rail
 * inside a client (owner decision, 25-09: "when inside a client they should see
 * only the client stuff"), which would re-open all three the moment the rail
 * stopped rendering. So the cluster moved OUT of the rail into one component
 * that both shells render — the firm rail vertically, the client top bar
 * horizontally. A copy in each would be two, and the second would drift.
 *
 * THE TWO ORIENTATIONS ARE A SURFACE, NOT A LAYOUT TWEAK. The rail is navy and
 * the bar is white, so the ink, the hover and the popover's own chrome differ;
 * what does not differ is WHICH three controls exist, which is the part the
 * guard asserts.
 */
export type UtilityOrientation = "rail" | "bar";

export function UtilityCluster({
  orientation,
  onOpenSearch,
}: {
  orientation: UtilityOrientation;
  onOpenSearch: () => void;
}) {
  const { user, userRole, signOut, fullName } = useAuth();
  const [avatarMenuOpen, setAvatarMenuOpen] = useState(false);
  const pathname = usePathname();
  const isSettingsRoute = pathname.startsWith("/settings");
  const onRail = orientation === "rail";

  const initials = fullName
    ? fullName.trim().split(" ").filter(Boolean).slice(0, 2).map((n) => n[0].toUpperCase()).join("")
    : user?.email?.slice(0, 2).toUpperCase() ?? "CA";

  const button = onRail
    ? "flex items-center justify-center w-9 h-9 rounded-[9px] text-slate-500 hover:text-white hover:bg-white/10 transition-all duration-100"
    : "flex items-center justify-center w-8 h-8 rounded-lg text-ps-hint hover:text-ps-ink hover:bg-ps-bg transition-colors";

  return (
    <div
      className={cn(
        onRail
          ? "flex flex-col items-center gap-2 pb-3 shrink-0 border-t border-white/10 pt-3"
          : "flex items-center gap-1 shrink-0"
      )}
    >
      <button onClick={onOpenSearch} title="Search (⌘K)" aria-label="Search" className={button}>
        <Search size={15} />
      </button>

      <Link
        href="/settings"
        title="Settings"
        aria-label="Settings"
        className={cn(
          button,
          isSettingsRoute && (onRail ? "relative bg-brand text-white" : "bg-ps-bg text-ps-ink")
        )}
      >
        {isSettingsRoute && onRail && (
          <span className="absolute left-[-1px] h-5 w-[3px] rounded-r-[2px] bg-brand" />
        )}
        <Settings size={15} />
      </Link>

      <div className="relative">
        <button
          onClick={() => setAvatarMenuOpen((v) => !v)}
          title={user?.email ?? "Account"}
          aria-label="Account"
          className="w-7 h-7 rounded-full bg-brand flex items-center justify-center text-3xs font-bold text-white hover:opacity-80 transition-opacity shrink-0"
        >
          {initials}
        </button>
        {avatarMenuOpen && (
          <>
            <div className="fixed inset-0 z-20" onClick={() => setAvatarMenuOpen(false)} />
            <div
              className={cn(
                "absolute z-30 w-48 rounded-xl p-1.5",
                onRail
                  ? "left-full bottom-0 ml-2 bg-[#1e2d5e] border border-white/10 shadow-[0_8px_24px_rgba(0,0,0,0.5)]"
                  : "right-0 top-full mt-2 bg-white border border-ps-border shadow-lg"
              )}
            >
              <div className={cn("px-3 py-2 mb-1 border-b", onRail ? "border-white/10" : "border-ps-border")}>
                <p className={cn("text-xs font-semibold truncate", onRail ? "text-white" : "text-ps-ink")}>
                  {user?.email ?? "user@firm.com"}
                </p>
                <p className={cn("text-3xs truncate mt-0.5", onRail ? "text-slate-500" : "text-ps-hint")}>
                  {userRole ?? "Partner"}
                </p>
              </div>
              <button
                onClick={() => {
                  setAvatarMenuOpen(false);
                  signOut();
                }}
                className={cn(
                  "w-full flex items-center gap-2 px-3 py-2 rounded-lg text-xs transition-colors",
                  onRail
                    ? "text-slate-400 hover:text-red-400 hover:bg-white/10"
                    : "text-ps-label hover:text-state-problem hover:bg-ps-bg"
                )}
              >
                <LogOut size={13} />
                Sign out
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
