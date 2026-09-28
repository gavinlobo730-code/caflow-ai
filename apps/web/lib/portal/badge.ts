/**
 * The client-portal header badge, derived from contact counts rather than a
 * single boolean.
 *
 * The page used to compute one `enabled` flag (`active.length > 0 ||
 * invited.length > 0`) and render a green "Active" badge whenever it was
 * true — so a client with zero signed-in contacts and only a pending invite
 * showed a green "Active" badge sitting directly beside a caption reading
 * "0 active, 1 pending", which reads as contradictory. Three states, not
 * two, and the middle one is never green.
 */
export type PortalBadgeTone = "active" | "invited" | "disabled";

export interface PortalBadge {
  label: string;
  tone: PortalBadgeTone;
}

export function portalStatusBadge(activeCount: number, invitedCount: number): PortalBadge {
  if (activeCount > 0) return { label: "Active", tone: "active" };
  if (invitedCount > 0) return { label: "Invited, not yet signed in", tone: "invited" };
  return { label: "Not enabled", tone: "disabled" };
}
