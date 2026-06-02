/**
 * Role-Based Access Control permissions for CAflow AI.
 *
 * Roles: Partner | Manager | Article | Staff
 *
 * Partner  — full access to everything
 * Manager  — no access to /reports, /settings billing section, cannot see firm financials
 * Article  — only /tasks, /clients (read-only), /calendar, /ai-assistant
 * Staff    — same as Article
 */

export type UserRole = "Partner" | "Manager" | "Article" | "Staff";

/** Routes that are always visible regardless of role */
const ALWAYS_VISIBLE = ["/", "/notifications", "/ai-assistant", "/tasks", "/calendar", "/clients", "/clients/portal"];

/** Routes completely hidden from Article / Staff */
const ARTICLE_STAFF_HIDDEN_HREFS = new Set([
  "/accounting",
  "/compliance",
  "/gst",
  "/income-tax",
  "/tds",
  "/mca",
  "/reports",
  "/settings",
  "/team",
  "/parser",
  "/documents",
  "/risks",
]);

/** Routes hidden from Manager */
const MANAGER_HIDDEN_HREFS = new Set([
  "/settings",
  "/reports",
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

export { ALWAYS_VISIBLE };
