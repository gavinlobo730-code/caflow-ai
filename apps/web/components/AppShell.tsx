"use client";

import { useState, useEffect } from "react";
import { usePathname } from "next/navigation";
import { WorkspaceProvider } from "@/lib/workspace/WorkspaceContext";
import { ClientNavProvider } from "@/lib/workspace/ClientNavContext";
import { NavShell } from "@/components/shell/NavShell";
import { WorkspaceRail } from "@/components/shell/WorkspaceRail";
import { ClientSections } from "@/components/shell/ClientSections";
import { ContextPanel } from "@/components/ContextPanel";
import { SearchModal } from "@/components/SearchModal";
import { isClientWorkspacePath } from "@/lib/workspace/clientPath";

// usePathname() reflects the App Router's FlightRouterState, which under
// `output: export` + Cloudflare's rewrite-to-_placeholder hosting is
// permanently anchored to the "_placeholder" build param for any dynamic
// segment — never the real browser URL (see ClientNavContext.tsx's doc
// comment for the same failure mode). Reading it directly here is exactly
// the bug clientPath.ts's own doc comment warns about.
//
// ⚠️ IT NO LONGER DECIDES WHETHER CHROME RENDERS, only WHICH PANEL. Until
// 2.6 a wrong answer here drew the firm rails ALONGSIDE the client's own —
// the "two sidebars" bug — because there were two shells. There is one now,
// so the worst a wrong answer can do is show the wrong list.
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

  if (!showShell) {
    return <>{children}</>;
  }

  // ClientNavProvider is HOISTED here, above the client layout that used to own
  // it, so the one shell can render the client's section list. It derives the
  // id from window.location and answers "" off a client route, so it is inert
  // everywhere else — which is what makes hoisting it safe rather than a
  // widening of its scope.
  return (
    <ClientNavProvider>
      <WorkspaceProvider>
        <SearchModal open={searchOpen} onClose={() => setSearchOpen(false)} />
        <NavShell
          rail={<WorkspaceRail onOpenSearch={() => setSearchOpen(true)} />}
          panel={isClientWorkspace ? <ClientSections /> : <ContextPanel onOpenSearch={() => setSearchOpen(true)} />}
          panelLabel={isClientWorkspace ? "Client workspace" : "Navigation"}
          childOwnsScroll={isClientWorkspace}
        >
          {children}
        </NavShell>
      </WorkspaceProvider>
    </ClientNavProvider>
  );
}
