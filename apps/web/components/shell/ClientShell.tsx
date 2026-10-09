"use client";

import { ClientTopBar } from "@/components/shell/ClientTopBar";
import { PrintHeader } from "@/components/shell/PrintHeader";
import { MAIN_CONTENT_ID } from "@/components/shell/SkipToContent";

/**
 * The client workspace's shell: a bar across the top, and the module below it
 * at full width.
 *
 * ⚠️ THE SAFETY PROPERTY IS THAT THIS IS ONE OF EXACTLY TWO, NEVER NEITHER.
 * `AppShell` reads the path to decide which shell a screen gets, and
 * `AppShell`'s own comment records why that used to be dangerous: when the
 * same test decided whether chrome rendered at all, a wrong answer drew the
 * firm rails alongside the client's — the "two sidebars" bug. 2.6 defused it
 * by making the answer choose only WHICH PANEL.
 *
 * This change makes it decide again, and the failure mode is worse than two
 * sidebars: a wrong TRUE on a firm route would leave a page with no navigation
 * at all. So the branch returns a SHELL either way — `NavShell` with the rail,
 * or this with the bar — and both carry `UtilityCluster`, so search, Settings
 * and sign-out survive a wrong answer, and this one always carries the way
 * out. `scripts/a-client-workspace-still-has-a-way-out.test.ts` asserts it on
 * the structure rather than on a spelling.
 *
 * The bar does not scroll and the body under it does — which is what
 * `NavShell`'s `childOwnsScroll` used to arrange for the client layout, and is
 * arranged here directly now that this shell owns the vertical layout.
 *
 * ⚠️ ON PAPER IT IS NOT A SCREEN (PRE-A-016). `h-screen overflow-hidden` is
 * what keeps the bar still while the body scrolls, and a printer has no
 * viewport: the frame is one page tall and everything below it is clipped, so a
 * long statement came out as its first screenful. Under `print:` the frame
 * becomes ordinary block flow (`print:block print:h-auto print:overflow-visible`,
 * and `<main>` stops scrolling) and the bar is `print:hidden` in its own file,
 * so what prints is the page, in as many sheets as it takes, headed by
 * `PrintHeader` (whose books these are). Nothing here applies on screen.
 * `globals.css` holds the one print rule, for a screen that prints a single
 * region. `scripts/a-printed-screen-is-not-clipped-or-blanked.test.ts` is the
 * rule, and applies to `WorkspaceShell` too.
 */
export function ClientShell({
  onOpenSearch,
  children,
}: {
  onOpenSearch: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col h-screen overflow-hidden bg-ps-bg print:block print:h-auto print:overflow-visible">
      <ClientTopBar onOpenSearch={onOpenSearch} />
      {/* The skip link's target — see SkipToContent. */}
      <main id={MAIN_CONTENT_ID} tabIndex={-1} className="flex-1 min-h-0 overflow-y-auto outline-none print:overflow-visible"><PrintHeader />{children}</main>
    </div>
  );
}
