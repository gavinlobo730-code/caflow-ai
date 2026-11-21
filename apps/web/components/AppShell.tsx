"use client";

import { useState, useEffect } from "react";
import { usePathname } from "next/navigation";
import { WorkspaceProvider } from "@/lib/workspace/WorkspaceContext";
import { ClientNavProvider } from "@/lib/workspace/ClientNavContext";
import { WorkspaceShell } from "@/components/shell/WorkspaceShell";
import { ClientShell } from "@/components/shell/ClientShell";
import { SearchModal } from "@/components/SearchModal";
import { SecureAccountBanner } from "@/components/shell/SecureAccountBanner";
import { SkipToContent } from "@/components/shell/SkipToContent";
import { NewVersionNotice } from "@/components/shell/NewVersionNotice";
import { isClientWorkspacePath } from "@/lib/workspace/clientPath";
import { wearsThePracticeFrame } from "@/lib/workspace/practiceWorkspace";
import { rememberPracticeAccess, rememberedPracticeAccess } from "@/lib/workspace/practiceAccessMemory";
import { useAuth } from "@/lib/auth/AuthContext";
import { isPartnerOnlyAllowed } from "@/lib/auth/permissions";
import ScreenAccessGate from "@/components/auth/ScreenAccessGate";
import { WhereIsGuide } from "@/components/guide/WhereIsGuide";

// usePathname() reflects the App Router's FlightRouterState, which under
// `output: export` + Cloudflare's rewrite-to-_placeholder hosting is
// permanently anchored to the "_placeholder" build param for any dynamic
// segment — never the real browser URL (see ClientNavContext.tsx's doc
// comment for the same failure mode). Reading it directly here is exactly
// the bug clientPath.ts's own doc comment warns about.
//
// ⚠️ IT DECIDES WHICH SHELL, AND THAT IS A STRONGER JOB THAN IT HAD. Until
// 2.6 a wrong answer drew the firm rails ALONGSIDE the client's own — the "two
// sidebars" bug — because there were two shells; 2.6 left it choosing only
// which PANEL, so the worst it could do was show the wrong list. It now
// chooses between `WorkspaceShell` and `ClientShell` — one top bar each, navy
// at firm level and white inside a client, both full width — because the
// owner's decision of 25-09 is that inside a client a CA sees only the
// client's own things. (`WorkspaceShell` replaced the firm-level rail + 220px
// panel with a bar of its own on 29-09, so the product speaks one navigation
// idiom throughout rather than a sidebar outside a client and a bar inside
// one — see WorkspaceTopBar's own header.)
//
// So a wrong answer is expensive again, and the mitigation is structural
// rather than careful: the branch returns a shell EITHER WAY and never bare
// children, both shells render `UtilityCluster` (search, Settings, sign-out —
// the three 2.6 exists for), and the client one always carries "All clients".
// There is no path through this function that leaves a signed-in CA with no
// navigation. `scripts/a-client-workspace-still-has-a-way-out.test.ts` holds
// that as the rule.
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
// firm yet. `/onboarding/checklist` used to be a DIFFERENT screen entirely —
// the CLIENT-onboarding workflow tracker ("Client Onboarding" is its own
// heading), a staff screen that walks a client through engagement setup — and
// as a PREFIX match this list had lost it the rail, the panel and ⌘K, so it
// had no navigation at all and nothing in the product linked to it. It now
// lives at /clients/onboarding, in the Clients workspace it belongs to (see
// lib/workspace/routeOwnership.ts); /onboarding/checklist is a redirect stub
// kept for bookmarks and needs no entry here, since it renders no content of
// its own to strip a shell from.
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

/** Whether a page at `path` is drawn with no shell: a signed-out or non-staff page. The not-found page asks it too,
 *  so an unknown address under one of these is drawn as a front door (POST-A-446) and one inside the product is
 *  drawn inside the shell, beside the navigation. */
export function isOutsideTheShell(path: string): boolean {
  return (
    NO_SHELL_PREFIXES.some((prefix) => path === prefix || path.startsWith(prefix + "/")) ||
    NO_SHELL_EXACT.includes(withoutTrailingSlash(path))
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  // usePathname() is only a re-run trigger below — the real path always
  // comes from window.location (see the comment on getRealPathname above).
  const pathname = usePathname();
  const [realPathname, setRealPathname] = useState<string>(() => getRealPathname());
  useEffect(() => { setRealPathname(getRealPathname()); }, [pathname]);
  const [searchOpen, setSearchOpen] = useState(false);
  // "Where is…?" (POST-A-538): one dialog, held here like the search box, opened from either shell's bar.
  const [guideOpen, setGuideOpen] = useState(false);

  const showShell = !isOutsideTheShell(realPathname);
  const isClientWorkspace = isClientWorkspacePath(realPathname);
  // My practice (POST-A-532): the firm's own screens at fixed addresses wear the client workspace's shell, because the
  // practice IS a client of itself and its books are that workspace. A wrong answer here still draws a shell with search,
  // Settings and sign-out, as the comment above getRealPathname requires.
  //
  // THE PEOPLE SCREENS FOLLOW THE PERSON (21-11-2026). Team, Assignments, Approvals, Workload and Login History are part of
  // My practice for somebody who may open it and firm screens for everybody else (`practiceWorkspace.ts` has the account), so
  // which shell they wear is asked of the role. Until the role has been read, the last answer this browser saw stands in
  // (`practiceAccessMemory.ts`), so a Partner's reload of the Team screen does not start in one frame and change to the other.
  const { userRole, roleLoading } = useAuth();
  const [remembered] = useState<boolean>(() => rememberedPracticeAccess());
  const mayOpenPractice = roleLoading ? remembered : isPartnerOnlyAllowed(userRole);
  useEffect(() => {
    if (!roleLoading) rememberPracticeAccess(isPartnerOnlyAllowed(userRole));
  }, [roleLoading, userRole]);
  const isPractice = wearsThePracticeFrame(realPathname, mayOpenPractice);

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
  // it, so the shell itself can read the client id — `ClientTopBar` needs it
  // for the name, the switcher, the health badge and the grid. It derives the
  // id from window.location and answers "" off a client route, so it is inert
  // everywhere else, which is what makes hoisting it safe rather than a
  // widening of its scope.
  //
  // The enrolment banner rides inside BOTH shells' content, so it is staff-only
  // by construction: the portals and signed-out pages returned bare above.
  const content = (
    <>
      <SecureAccountBanner pathname={realPathname} />
      {/* The one gate on every firm screen (POST-A-543): an address the person holds no tick for says so in words. */}
      <ScreenAccessGate pathname={realPathname}>{children}</ScreenAccessGate>
    </>
  );
  return (
    <ClientNavProvider>
      <WorkspaceProvider>
        {/* FIRST in the document, ahead of the top bar both shells draw, so it is
            the first stop for a keyboard user. Only here: the no-shell branch
            above has no navigation to skip. */}
        <SkipToContent />
        <SearchModal open={searchOpen} onClose={() => setSearchOpen(false)} />
        <WhereIsGuide open={guideOpen} onClose={() => setGuideOpen(false)} />
        {/* A tab opened before the site was republished is told, and loads the new build at its next move (POST-A-529). */}
        <NewVersionNotice pathname={realPathname} />
        {isClientWorkspace || isPractice ? (
          <ClientShell onOpenSearch={() => setSearchOpen(true)} onOpenGuide={() => setGuideOpen(true)} practicePath={isPractice}>{content}</ClientShell>
        ) : (
          <WorkspaceShell onOpenSearch={() => setSearchOpen(true)} onOpenGuide={() => setGuideOpen(true)}>{content}</WorkspaceShell>
        )}
      </WorkspaceProvider>
    </ClientNavProvider>
  );
}
