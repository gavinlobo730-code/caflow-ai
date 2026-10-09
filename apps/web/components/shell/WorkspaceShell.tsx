"use client";

import { WorkspaceTopBar } from "@/components/shell/WorkspaceTopBar";
import { MAIN_CONTENT_ID } from "@/components/shell/SkipToContent";

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
 *
 * ⚠️ ON PAPER IT IS NOT A SCREEN (PRE-A-016) — the same `print:` reset as
 * `ClientShell`, for the same reason: `h-screen overflow-hidden` clips a
 * printed page to one viewport. See that file for the whole account.
 */
export function WorkspaceShell({
  onOpenSearch,
  children,
}: {
  onOpenSearch: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="flex h-screen flex-col overflow-hidden bg-ps-bg print:block print:h-auto print:overflow-visible">
      <WorkspaceTopBar onOpenSearch={onOpenSearch} />
      {/* The skip link's target. `tabIndex={-1}` so a jump to it moves focus
          here, `outline-none` because it is a landmark and not a control —
          both explained at SkipToContent. */}
      <main id={MAIN_CONTENT_ID} tabIndex={-1} className="min-h-0 flex-1 overflow-y-auto outline-none print:overflow-visible">{children}</main>
    </div>
  );
}
