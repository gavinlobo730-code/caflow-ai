"use client";

import { ClientTopBar } from "@/components/shell/ClientTopBar";

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
 */
export function ClientShell({
  onOpenSearch,
  children,
}: {
  onOpenSearch: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col h-screen overflow-hidden bg-ps-bg">
      <ClientTopBar onOpenSearch={onOpenSearch} />
      <main className="flex-1 min-h-0 overflow-y-auto">{children}</main>
    </div>
  );
}
