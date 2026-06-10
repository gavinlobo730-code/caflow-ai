/**
 * Role-Based Access Control permissions for PracticeSync AI.
 *
 * Roles: Partner | Manager | Article | Staff
 *
 * Partner  — full access to everything
 * Manager  — no access to /reports, /settings billing section, cannot see firm financials
 * Article  — only /tasks, /clients (read-only), /calendar, /ai-assistant
 * Staff    — same as Article
 */

import type { WorkspaceId } from "@/lib/workspace/workspaceConfig";

export type UserRole = "Partner" | "Manager" | "Article" | "Staff";

/** Routes that are always visible regardless of role */
const ALWAYS_VISIBLE = ["/", "/notifications", "/ai-assistant", "/tasks", "/calendar", "/clients", "/clients/portal"];

/** Routes completely hidden from Article / Staff */
const ARTICLE_STAFF_HIDDEN_HREFS = new Set([
  "/accounting",
  "/compliance",
  "/deadlines",
  "/gst",
  "/income-tax",
  "/tds",
  "/mca",
  "/reports",
  "/reports/analytics",
  "/settings",
  "/team",
  "/team/workload",
  "/parser",
  "/documents",
  "/risks",
  "/billing",
]);

/** Routes hidden from Manager */
const MANAGER_HIDDEN_HREFS = new Set([
  "/settings",
]);

/**
 * Returns true if a nav item href should be shown for the given role.
 */
export function canAccessHref(href: string, role: UserRole | null): boolean {
  // Default to Partner when role is unknown so existing users aren't locked out.
  const effectiveRole: UserRole = role ?? "Partner";

  switch (effectiveRole) {
    case "Partner":
      return true;
    case "Manager":
      return !MANAGER_HIDDEN_HREFS.has(href);
    case "Article":
    case "Staff":
      return !ARTICLE_STAFF_HIDDEN_HREFS.has(href);
    default:
      return true;
  }
}

/**
 * Returns true if the given role is in the allowed list.
 * Defaults to "Partner" when role is null to avoid locking out existing users.
 */
export function hasRole(role: UserRole | null, allowed: UserRole[]): boolean {
  const effectiveRole: UserRole = role ?? "Partner";
  return allowed.includes(effectiveRole);
}

/** Workspaces hidden from Article / Staff roles */
const ARTICLE_STAFF_HIDDEN_WORKSPACES = new Set<WorkspaceId>([
  "deadlines",
  "work",
]);

/**
 * Returns true if the given workspace should be visible for the given role.
 * Mirrors the same role logic as canAccessHref but at workspace granularity.
 */
export function canAccessWorkspace(
  workspaceId: WorkspaceId,
  role: UserRole | null
): boolean {
  const effectiveRole: UserRole = role ?? "Partner";
  switch (effectiveRole) {
    case "Partner":
    case "Manager":
      return true;
    case "Article":
    case "Staff":
      return !ARTICLE_STAFF_HIDDEN_WORKSPACES.has(workspaceId);
    default:
      return true;
  }
}

export { ALWAYS_VISIBLE };
