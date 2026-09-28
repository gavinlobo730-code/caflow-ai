"use client";

/**
 * Lets a stage tell the workspace header to re-fetch the engagement after an
 * action changes its status.
 *
 * WHY THIS EXISTS (sweep-client-inventory-docs-reports-05)
 *   _workspace.tsx fetches the engagement for the header badge exactly once,
 *   when engagementId changes — it has no reason to fetch it again, because
 *   nothing told it the status underneath had moved. The Review tab's
 *   doAction() and the Checklist tab's handleSubmitForReview() both call the
 *   backend, which really does flip draft -> in_review (or in_review ->
 *   approved, or approved -> locked, or locked -> draft on Reopen) and log it
 *   in Review History — so the action succeeds and the page's OWN tab
 *   re-renders correctly, while the "Draft" / "In Review" / … chip next to
 *   the FY label keeps showing whatever it showed when the workspace first
 *   loaded, for the rest of that session. A full reload fixes it, because
 *   that re-runs the one-time fetch.
 *
 * THE FIX
 *   The workspace exposes its own engagement fetch through this context, so a
 *   stage can ask for a re-fetch after a mutation succeeds without the header
 *   and the stage needing to share any other state.
 */

import { createContext, useContext } from "react";

type RefreshEngagement = () => void;

const EngagementRefreshContext = createContext<RefreshEngagement | null>(null);

export const EngagementRefreshProvider = EngagementRefreshContext.Provider;

/** A stage calls this after an action that may have changed the engagement's
 *  status, to keep the header badge in step. Outside the workspace (there is
 *  none today) this is a no-op rather than a thrown error — a stage's own
 *  action must not fail because the header happens not to be mounted. */
export function useRefreshEngagement(): RefreshEngagement {
  return useContext(EngagementRefreshContext) ?? (() => {});
}
