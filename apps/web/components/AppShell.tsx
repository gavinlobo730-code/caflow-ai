"use client";

import { useState, useEffect } from "react";
import { usePathname } from "next/navigation";
import { Menu, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { WorkspaceProvider } from "@/lib/workspace/WorkspaceContext";
import { ActivityRail } from "@/components/ActivityRail";
import { ContextPanel } from "@/components/ContextPanel";
import { SearchModal } from "@/components/SearchModal";

const NO_SHELL_PREFIXES = [
  "/login",
  "/signup",
  "/onboarding",
  "/join",
  "/auth",
  "/portal",
];

// Matches /clients/[UUID] and any sub-path — client layout owns its own rails
const CLIENT_UUID_RE =
  /^\/clients\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(\/|$)/i;

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [searchOpen, setSearchOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  const showShell = !NO_SHELL_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(prefix + "/")
  );
  const isClientWorkspace = CLIENT_UUID_RE.test(pathname);

  // Global ⌘K / Ctrl+K listener — opens the command palette from anywhere
  useEffect(() => {
    if (!showShell) return;
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setSearchOpen(true);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [showShell]);

  // Close mobile drawer on navigation
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  if (!showShell) {
    return <>{children}</>;
  }

  return (
    <WorkspaceProvider>
      {/* Global command palette */}
      <SearchModal open={searchOpen} onClose={() => setSearchOpen(false)} />

      {/* Mobile hamburger */}
      <button
        onClick={() => setMobileOpen(true)}
        className="md:hidden fixed top-3 left-3 z-40 p-2 rounded-lg bg-white text-[#64748B] hover:text-[#1E293B] border border-[#E2E8F0] shadow-sm"
        aria-label="Open menu"
      >
        <Menu size={18} />
      </button>

      {/* Mobile backdrop */}
      {mobileOpen && (
        <div
          className="md:hidden fixed inset-0 z-40 bg-[#0F172A]/75 backdrop-blur-sm"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Mobile slide-in drawer */}
      <div
        className={cn(
          "md:hidden fixed inset-y-0 left-0 z-50 flex transition-transform duration-200",
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        )}
      >
        <button
          onClick={() => setMobileOpen(false)}
          className="absolute top-3 right-[-40px] z-10 p-1.5 rounded-md bg-white text-[#94A3B8] hover:text-[#475569]"
          aria-label="Close menu"
        >
          <X size={15} />
        </button>
        <ActivityRail onOpenSearch={() => { setMobileOpen(false); setSearchOpen(true); }} />
        <ContextPanel onOpenSearch={() => { setMobileOpen(false); setSearchOpen(true); }} />
      </div>

      {/* Main layout */}
      <div className="flex h-screen overflow-hidden bg-[#F8FAFC]">
        {/* Desktop: ActivityRail + ContextPanel — hidden when inside client workspace */}
        {!isClientWorkspace && (
          <div className="hidden md:flex h-full">
            <ActivityRail onOpenSearch={() => setSearchOpen(true)} />
            <ContextPanel onOpenSearch={() => setSearchOpen(true)} />
          </div>
        )}

        {/* Work area — full height when in client workspace (client layout owns its rails) */}
        <main className={cn(
          "flex-1 min-w-0 overflow-hidden",
          isClientWorkspace ? "h-screen" : "overflow-auto pt-12 md:pt-0"
        )}>
          {children}
        </main>
      </div>
    </WorkspaceProvider>
  );
}
