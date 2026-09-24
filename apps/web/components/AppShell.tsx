"use client";

import { useState, useEffect } from "react";
import { usePathname } from "next/navigation";
import { Menu, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { WorkspaceProvider } from "@/lib/workspace/WorkspaceContext";
import { ActivityRail } from "@/components/ActivityRail";
import { ContextPanel } from "@/components/ContextPanel";
import { SearchModal } from "@/components/SearchModal";
import { isClientWorkspacePath } from "@/lib/workspace/clientPath";

// usePathname() reflects the App Router's FlightRouterState, which under
// `output: export` + Cloudflare's rewrite-to-_placeholder hosting is
// permanently anchored to the "_placeholder" build param for any dynamic
// segment — never the real browser URL (see ClientNavContext.tsx's doc
// comment for the same failure mode). Reading it directly here is exactly
// the bug clientPath.ts's own doc comment warns about: a "_placeholder" path
// makes isClientWorkspacePath() return false, so this shell's global rails
// render ALONGSIDE the client workspace's own rails ("two sidebars"). Mirror
// ClientNavContext's fix: use usePathname() only as a re-run trigger and
// always read the real path from window.location.
function getRealPathname(): string {
  if (typeof window === "undefined") return "";
  return window.location.pathname;
}

// Routes that render with NO shell, and the two kinds are not the same rule.
//
// A PREFIX entry strips the shell from a whole tree — every one of these is a
// signed-out or non-staff surface (the client portal, the employee portal, an
// invitation link), and a sub-route of one is the same kind of thing.
//
// `/onboarding` is EXACT, and that is a fix rather than a tidy-up. It is the
// firm SIGNUP wizard, which legitimately has no sidebar because there is no
// firm yet — but `/onboarding/checklist` is the CLIENT-onboarding workflow
// tracker ("Client Onboarding" is its own heading), a staff screen that walks
// a client through engagement setup. As a prefix it lost the rail, the panel
// and ⌘K, so the one screen that tracks client onboarding had no navigation
// at all and nothing in the product linked to it. It belongs to the Clients
// workspace (see lib/workspace/routeOwnership.ts).
const NO_SHELL_PREFIXES = [
  "/login",
  "/signup",
  "/join",
  "/auth",
  "/portal",
  "/sign",
];

const NO_SHELL_EXACT = ["/onboarding"];

/** `output: export` serves every route with a trailing slash, so an exact
 *  match has to ignore one — `/onboarding/` is `/onboarding`. */
function withoutTrailingSlash(path: string): string {
  return path.length > 1 && path.endsWith("/") ? path.slice(0, -1) : path;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  // usePathname() is only a re-run trigger below — the real path always
  // comes from window.location (see the comment on getRealPathname above).
  const pathname = usePathname();
  const [realPathname, setRealPathname] = useState<string>(() => getRealPathname());
  useEffect(() => { setRealPathname(getRealPathname()); }, [pathname]);
  const [searchOpen, setSearchOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  const showShell =
    !NO_SHELL_PREFIXES.some(
      (prefix) => realPathname === prefix || realPathname.startsWith(prefix + "/")
    ) && !NO_SHELL_EXACT.includes(withoutTrailingSlash(realPathname));
  const isClientWorkspace = isClientWorkspacePath(realPathname);

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

      {/* Mobile hamburger, backdrop and drawer — THE FIRM-LEVEL ONES ONLY.
          The desktop branch below already hides this shell's rails inside the
          client workspace, because that workspace owns its own; the mobile
          half did not, so on a phone at /clients/:id the two triggers rendered
          on top of each other — this one `fixed top-3 left-3 z-40` in white,
          ClientContextPanel's `fixed top-2.5 left-2.5 z-50` in navy — offset
          by 2px and differing in size, so the white one showed as a rim around
          two edges of the navy one. Tapping that rim opened the FIRM drawer
          over the client workspace.

          Hiding it loses nothing: the client drawer's own header carries the
          `/clients` back link (ArrowLeft, "Client Workspace"), which is the
          same way out the desktop panel gives. `ClientHeader` reserves the
          space with `pl-12 md:px-4`, sized for ONE trigger. */}
      {!isClientWorkspace && (
        <>
          <button
            onClick={() => setMobileOpen(true)}
            className="md:hidden fixed top-3 left-3 z-40 p-2 rounded-lg bg-white text-ps-label hover:text-ps-ink border border-ps-border shadow-sm"
            aria-label="Open menu"
          >
            <Menu size={18} />
          </button>

          {/* Mobile backdrop */}
          {mobileOpen && (
            <div
              className="md:hidden fixed inset-0 z-40 bg-brand/70 backdrop-blur-sm"
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
              className="absolute top-3 right-[-40px] z-10 p-1.5 rounded-md bg-white text-ps-hint hover:text-ps-label"
              aria-label="Close menu"
            >
              <X size={15} />
            </button>
            <ActivityRail onOpenSearch={() => { setMobileOpen(false); setSearchOpen(true); }} />
            <ContextPanel onOpenSearch={() => { setMobileOpen(false); setSearchOpen(true); }} />
          </div>
        </>
      )}

      {/* Main layout */}
      <div className="flex h-screen overflow-hidden bg-ps-bg">
        {/* Desktop: ActivityRail + ContextPanel — hidden when inside client workspace */}
        {!isClientWorkspace && (
          <div className="hidden md:flex h-full">
            <ActivityRail onOpenSearch={() => setSearchOpen(true)} />
            <ContextPanel onOpenSearch={() => setSearchOpen(true)} />
          </div>
        )}

        {/* Work area — full height when in client workspace (client layout owns its rails).
            Firm-level pages scroll here: min-h-0 lets this flex child shrink below its
            content height so overflow-y-auto produces a scrollbar (classic flexbox gotcha);
            overflow is set per-branch only — no conflicting overflow-hidden on the base. */}
        <main className={cn(
          "flex-1 min-w-0 min-h-0",
          isClientWorkspace ? "h-screen overflow-hidden" : "h-full overflow-y-auto pt-12 md:pt-0"
        )}>
          {children}
        </main>
      </div>
    </WorkspaceProvider>
  );
}
