"use client";

import { ReactNode } from "react";
import { usePermissions } from "@/lib/auth/AuthContext";

interface CanProps {
  /** Permission resource, e.g. "accounting" — the backend's PERMISSIONS key. */
  resource: string;
  /** Action on that resource, e.g. "write" | "approve" | "delete". */
  action: string;
  /** Rendered only when the caller holds resource:action. */
  children: ReactNode;
  /**
   * Rendered instead when they don't. Default is nothing — a control the user
   * cannot use is usually best absent. Pass a disabled control plus an
   * explanation where the absence would be confusing (a step in a visible
   * workflow, a tab that would otherwise look broken).
   */
  fallback?: ReactNode;
}

/**
 * Renders its children only if the signed-in user may perform the action.
 *
 *   <Can resource="accounting" action="approve">
 *     <Button onClick={post}>Post to ledger</Button>
 *   </Can>
 *
 * The counterpart to RoleGuard: RoleGuard gates PAGES by role, this gates
 * ACTIONS by permission. It holds no role list — the map comes from
 * GET /api/identity/permissions, which serves core/permissions.py verbatim, so
 * the button and the endpoint behind it can never disagree.
 *
 * UX only. rbac() on the endpoint is the actual authorisation; this stops the
 * user being offered an action that would come back 403 after they pressed it.
 * Fails closed while the permission map is still resolving.
 */
export function Can({ resource, action, children, fallback = null }: CanProps) {
  const { can } = usePermissions();
  return <>{can(resource, action) ? children : fallback}</>;
}
