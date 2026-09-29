"use client";

import { WorkspaceTopBar } from "@/components/shell/WorkspaceTopBar";

/**
 * The firm-level shell: a bar across the top, and the page below it at full
 * width. Mirrors `ClientShell` exactly — same layout, same contract — because
 * the whole point of this redesign is that the two are now one idiom rather
 * than two (see WorkspaceTopBar's own header).
 *
 * ⚠️ THE SAFETY PROPERTY IS THAT THIS IS ONE OF EXACTLY TWO, NEVER NEITHER.
 * `AppShell` reads the path to decide which shell a screen gets; a wrong
 * answer must never leave a page with no navigation at all. So the branch
 * returns a shell either way — this or `ClientShell` — and both carry
 * `UtilityCluster`, so search, Settings and sign-out survive a wrong answer.
 * `scripts/a-client-workspace-still-has-a-way-out.test.ts` asserts it on the
 * structure rather than on a spelling.
 */
export function WorkspaceShell({
  onOpenSearch,
  children,
}: {
  onOpenSearch: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="flex h-screen flex-col overflow-hidden bg-ps-bg">
      <WorkspaceTopBar onOpenSearch={onOpenSearch} />
      <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>
    </div>
  );
}
