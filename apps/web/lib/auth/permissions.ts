/**
 * Role-Based Access Control permissions for PracticeSync AI.
 *
 * Module 9.0 / M1 — Role Model Unification.
 * Canonical roles (single source of truth = backend core/permissions.py Role enum):
 *   Partner | Manager | Executive | Reviewer | Client
 *
 * Partner   — full access to everything.
 * Manager   — firm-wide staff access; no /settings, no /practice (Partner-only G1).
 * Executive — delivery staff: assigned clients/tasks/knowledge (firm financials hidden).
 * Reviewer  — read/approve-only delivery staff (same nav scope as Executive here).
 * Client    — external; uses the separate /portal surface, not the staff nav.
 *
 * NOTE: this is UX nav-gating only. Real authorization is enforced server-side
 * (FastAPI rbac()/permissions). These helpers therefore fail CLOSED (default to
 * least privilege) for unknown roles rather than fail open.
 */

import type { WorkspaceId } from "@/lib/workspace/workspaceConfig";

export type UserRole = "Partner" | "Manager" | "Executive" | "Reviewer" | "Client";

/** Legacy/foreign role strings → canonical (mirrors LEGACY_ROLE_MAP in the backend). */
const LEGACY_ROLE_MAP: Record<string, UserRole> = {
  owner: "Partner",
  admin: "Manager",
  article: "Executive",
  staff: "Executive",
  viewer: "Reviewer",
};

const CANONICAL = new Set<UserRole>(["Partner", "Manager", "Executive", "Reviewer", "Client"]);

/**
 * Normalize an arbitrary role string (any case, legacy vocabulary) to a canonical
 * UserRole, or null if unrecognized. Used to read roles that may still carry old
 * values from JWT user_metadata or pre-migration rows.
 */
export function normalizeRole(raw: string | null | undefined): UserRole | null {
  if (!raw) return null;
  const titled = (raw.charAt(0).toUpperCase() + raw.slice(1).toLowerCase()) as UserRole;
  if (CANONICAL.has(titled)) return titled;
  return LEGACY_ROLE_MAP[raw.trim().toLowerCase()] ?? null;
}

/** Least-privileged staff role — the fail-closed default for unknown/missing roles. */
const LEAST_PRIVILEGE: UserRole = "Reviewer";

/** Routes that are always visible regardless of role */
const ALWAYS_VISIBLE = ["/", "/notifications", "/ai-assistant", "/tasks", "/calendar", "/clients", "/clients/portal"];

/** Routes hidden from non-management delivery staff (Executive / Reviewer / Client) */
const STAFF_HIDDEN_HREFS = new Set([
  "/accounting",
  "/compliance",
  "/deadlines",
  "/gst",
  "/income-tax",
  "/tds",
  "/mca",
  "/reports",
  "/settings",
  "/team",
  "/team/workload",
  "/parser",
  "/documents",
  "/risks",
  "/billing",
  "/practice",
]);

/** Routes hidden from Manager */
const MANAGER_HIDDEN_HREFS = new Set([
  "/settings",
  "/practice",   // Practice / Revenue Operations is Partner-only (G1)
]);

/**
 * Returns true if a nav item href should be shown for the given role.
 * Unknown/null roles fail CLOSED to least privilege (no longer default to Partner).
 */
export function canAccessHref(href: string, role: UserRole | null): boolean {
  const effectiveRole: UserRole = role ?? LEAST_PRIVILEGE;

  switch (effectiveRole) {
    case "Partner":
      return true;
    case "Manager":
      return !MANAGER_HIDDEN_HREFS.has(href);
    case "Executive":
    case "Reviewer":
    case "Client":
    default:
      return !STAFF_HIDDEN_HREFS.has(href);
  }
}

/**
 * Returns true if the given role is in the allowed list.
 * Unknown/null roles fail CLOSED to least privilege (no longer default to Partner).
 */
export function hasRole(role: UserRole | null, allowed: UserRole[]): boolean {
  const effectiveRole: UserRole = role ?? LEAST_PRIVILEGE;
  return allowed.includes(effectiveRole);
}

/** Workspaces hidden from non-management delivery staff (Executive / Reviewer / Client) */
const STAFF_HIDDEN_WORKSPACES = new Set<WorkspaceId>([
  "deadlines",
  "work",
]);

/**
 * Workspaces restricted to Partner/Owner only (Amendment v1.1 Guardrail G1).
 * The Practice workspace exposes firm revenue / fee economics and the internal
 * client; the nav entry must NOT render for non-partners.
 */
const PARTNER_ONLY_WORKSPACES = new Set<WorkspaceId>(["practice"]);

/**
 * Returns true if the given workspace should be visible for the given role.
 * Mirrors the same role logic as canAccessHref but at workspace granularity.
 */
export function canAccessWorkspace(
  workspaceId: WorkspaceId,
  role: UserRole | null
): boolean {
  const effectiveRole: UserRole = role ?? LEAST_PRIVILEGE;
  // G1: Practice (revenue/fee economics) is Partner-only for every other role.
  if (PARTNER_ONLY_WORKSPACES.has(workspaceId)) {
    return effectiveRole === "Partner";
  }
  switch (effectiveRole) {
    case "Partner":
    case "Manager":
      return true;
    case "Executive":
    case "Reviewer":
    case "Client":
    default:
      // Knowledge Base is visible to all staff; only deadlines/work are hidden.
      return !STAFF_HIDDEN_WORKSPACES.has(workspaceId);
  }
}

/** True only for Partner (route-level guard for Practice / Revenue Operations). */
export function isPartnerOnlyAllowed(role: UserRole | null): boolean {
  return role === "Partner";
}

export { ALWAYS_VISIBLE };
