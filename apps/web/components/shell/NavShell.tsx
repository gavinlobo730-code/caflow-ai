"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { Menu, X } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * ONE shell — at firm level and inside a client alike.
 *
 * WHAT WAS WRONG. There were two, sharing nothing. `AppShell` rendered
 * `ActivityRail` (52px, navy, the workspaces) beside `ContextPanel` (220px,
 * white, the module's screens) and HID BOTH inside the client workspace, where
 * `ClientWorkspaceShell` rendered `ClientContextPanel` instead — 200px, navy,
 * with its own collapse, its own storage key, its own mobile drawer, its own
 * close-on-navigate effect and its own reading of the URL. Item 2.8 existed
 * because the two mobile hamburgers rendered on top of one another.
 *
 * ⚠️ AND THREE THINGS SIMPLY DID NOT EXIST INSIDE A CLIENT, which is where a CA
 * spends the day. `signOut` appears in exactly ONE navigation surface in this
 * product, and the only `href="/settings"` outside the settings screens
 * themselves is in the same one: the rail. So a CA inside a client workspace
 * could not sign out and could not reach Settings without first leaving the
 * client. ⌘K worked — AppShell's listener is mounted there — and nothing on
 * the screen said so, because the search button is on the rail too.
 *
 * SO THE RAIL IS CONSTANT. It is the product's spine: the workspaces, search,
 * Settings and the account menu, on every screen a signed-in CA sees. What
 * changes beside it is the PANEL — the module's screens at firm level, the
 * client's sections inside a client. Nothing is lost: the client panel keeps
 * its collapse and the firm panel gains one.
 *
 * WHAT THIS COMPONENT OWNS, once each: the desktop layout, the collapse and
 * its one storage key, the mobile trigger, backdrop, drawer and
 * close-on-navigate, and the main scroll area. Its callers own only CONTENT,
 * which is what stops a second set of any of it appearing.
 */

const STORAGE_KEY = "practicesync_sidebar_collapsed";

interface NavShellProps {
  /** The icon column. Always the firm workspaces — see the header. */
  rail: React.ReactNode;
  /** Beside it: the module's screens, or the client's sections. */
  panel: React.ReactNode;
  /** Announced on the mobile drawer, so it says which list it is showing. */
  panelLabel: string;
  /**
   * True where the CHILD owns the vertical layout — the client workspace,
   * whose `ClientHeader` must stay put while the body under it scrolls. The
   * shell then neither scrolls nor pads: it hands over a fixed-height box.
   *
   * ⚠️ NOT COSMETIC, AND THE OLD `AppShell` HAD IT. Its main was
   * `isClientWorkspace ? "h-screen overflow-hidden" : "h-full overflow-y-auto
   * pt-12 md:pt-0"`, and losing the distinction gives a client screen TWO
   * nested scrollers and 48px of dead space above a header that already clears
   * the mobile trigger horizontally with `pl-12`.
   */
  childOwnsScroll?: boolean;
  children: React.ReactNode;
}

export function NavShell({ rail, panel, panelLabel, childOwnsScroll = false, children }: NavShellProps) {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    try {
      return localStorage.getItem(STORAGE_KEY) === "true";
    } catch {
      return false;   // a private window and blocked site data both throw
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, String(collapsed));
    } catch {
      // A remembered collapse is a per-viewer convenience; losing it is fine.
    }
  }, [collapsed]);

  // ONE close-on-navigate effect, where there were two — and the two watched
  // different copies of the path, so they could disagree.
  useEffect(() => { setMobileOpen(false); }, [pathname]);

  return (
    <>
      {/* ── ONE mobile trigger, which is what 2.8 had to fix by hiding the
          other: at /clients/:id both rendered, 2px apart and differing in
          size, so the white one showed as a rim around two edges of the navy
          one and tapping that rim opened the FIRM drawer over the client
          workspace. With one shell the collision cannot recur. `ClientHeader`
          reserves the space with `pl-12 md:px-4`, sized for exactly one. ── */}
      <button
        onClick={() => setMobileOpen(true)}
        aria-label="Open navigation"
        className="md:hidden fixed top-2.5 left-2.5 z-50 flex items-center justify-center w-8 h-8 rounded-lg bg-brand text-slate-300 shadow-md"
      >
        <Menu size={16} />
      </button>

      {mobileOpen && (
        <>
          <div
            className="md:hidden fixed inset-0 z-40 bg-brand/70 backdrop-blur-sm"
            onClick={() => setMobileOpen(false)}
          />
          <div className="md:hidden fixed inset-y-0 left-0 z-50 flex">
            <button
              onClick={() => setMobileOpen(false)}
              aria-label="Close navigation"
              className="absolute top-3 right-[-40px] z-10 p-1.5 rounded-md bg-white text-ps-hint hover:text-ps-label"
            >
              <X size={15} />
            </button>
            {rail}
            <div className="w-[220px] bg-white border-r border-gray-200 flex flex-col overflow-hidden">
              <span className="sr-only">{panelLabel}</span>
              {panel}
            </div>
          </div>
        </>
      )}

      <div className="flex h-screen overflow-hidden bg-ps-bg">
        <div className="hidden md:flex h-full">
          {/* The rail carries the collapse control, so it has to survive the
              collapse — which is why the control is not inside the panel it
              hides. `ClientContextPanel` put it in the header and had to
              render a SECOND expand button for the collapsed state. */}
          <NavShellCollapseContext.Provider value={{ collapsed, toggle: () => setCollapsed((v) => !v) }}>
            {rail}
          </NavShellCollapseContext.Provider>
          <div
            className={cn(
              "flex flex-col h-full shrink-0 bg-white transition-[width] duration-200 ease-in-out overflow-hidden",
              collapsed ? "w-0 border-r-0" : "w-[220px] border-r border-gray-200"
            )}
          >
            {panel}
          </div>
        </div>

        {/* min-h-0 lets this flex child shrink below its content height so
            overflow-y-auto produces a scrollbar — the flexbox gotcha AppShell's
            own comment recorded. pt-12 on mobile clears the fixed trigger,
            except where the child's own header already does (see
            `childOwnsScroll`). */}
        <main
          className={cn(
            "flex-1 min-w-0 min-h-0",
            childOwnsScroll
              ? "h-screen overflow-hidden"
              : "h-full overflow-y-auto pt-12 md:pt-0"
          )}
        >
          {children}
        </main>
      </div>
    </>
  );
}

/** The rail renders the collapse control, and the shell owns the state. A
 *  context rather than a prop because the rail is passed in as a NODE — the
 *  alternative is for every caller to thread the pair through, which is how a
 *  second copy of the state gets written.
 *
 *  It wraps the DESKTOP rail only. The same element is rendered again inside
 *  the mobile drawer, where there is nothing to collapse, so `useContext`
 *  answers null there and no control is drawn. */
const NavShellCollapseContext = createContext<{ collapsed: boolean; toggle: () => void } | null>(null);

export function useNavShellCollapse() {
  return useContext(NavShellCollapseContext);
}
