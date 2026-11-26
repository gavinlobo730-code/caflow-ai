/**
 * Roles and action-level permissions for PracticeSync AI.
 *
 * Canonical roles (single source of truth = backend core/permissions.py Role enum):
 *   Partner | Manager | Executive | Reviewer | Client
 *
 * WHAT A ROLE DECIDES HERE, SINCE POST-A-543 (the owner's decision of 21-11-2026): very little. What a member of staff
 * sees on the firm menu and what opens at an address is decided by the permission pairs a Partner ticked for them, asked of
 * one table (`lib/access/screenAccess.ts`); a role only sets the pairs a person starts with, on the server. The lists that
 * used to live in this file and hide areas and addresses by role (the hidden addresses for staff and for a Manager, the
 * hidden areas, the always-visible list) are gone with the two functions that read them.
 *
 * What still asks the role: My practice (a Partner's alone, decided by the role on the server as well). The Settings pages
 * asked a role too, through a guard on each page, until they joined the one table (POST-A-545).
 *
 * NOTE: this is what is OFFERED. Real authorization is enforced server-side (FastAPI rbac()/permissions). These helpers
 * fail CLOSED (default to least privilege) for unknown roles rather than fail open.
 */

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

/** True only for Partner (route-level guard for Practice / Revenue Operations). */
export function isPartnerOnlyAllowed(role: UserRole | null): boolean {
  return role === "Partner";
}

// ─── Action-level permissions ────────────────────────────────────────────────
//
// This gates ACTIONS and, through `lib/access/screenAccess.ts`, pages. It does not
// hold a role list of its own: the map comes from the backend
// (GET /api/identity/permissions), which serves core/permissions.py verbatim.
//
// The reason it is fetched rather than mirrored here: a second copy of the
// matrix in TypeScript drifts silently, and it already had. `accounting:read`
// admits Executive while `accounting:write` does not, so screens that showed
// write buttons to anyone who could read the page were offering an Executive
// actions the backend answers with 403 — a button that only fails after being
// pressed. There is now exactly one copy of the matrix, in Python.
//
// Still UX only. rbac() on each endpoint is what actually authorises; hiding a
// button no more protects an endpoint than not drawing a door locks a room.

/** resource → the actions the caller may perform on it. Mirrors the backend's
 *  `get_accessible_resources()` response shape exactly. */
export type PermissionMap = Record<string, string[]>;

/**
 * Can the caller perform `action` on `resource`?
 *
 * Fails CLOSED on a null map — the same doctrine as the role helpers above.
 * null means "not resolved yet" (the fetch is in flight) or "the fetch failed";
 * in both cases the honest answer is "don't offer it", not "assume yes".
 */
export function can(
  permissions: PermissionMap | null,
  resource: string,
  action: string
): boolean {
  if (!permissions) return false;
  return permissions[resource]?.includes(action) ?? false;
}

/**
 * True if the caller may perform EVERY one of the given resource:action pairs.
 * For a control whose handler makes more than one call — "Post" both writes the
 * journal and approves it — where showing it on the weaker of the two would put
 * the user through a half-completed action.
 */
export function canAll(
  permissions: PermissionMap | null,
  pairs: Array<[resource: string, action: string]>
): boolean {
  return pairs.every(([resource, action]) => can(permissions, resource, action));
}

/**
 * Narrow an unknown JSON body into a PermissionMap, or null if it is not one.
 *
 * The backend response is parsed, not trusted: a partial outage that returns
 * HTML, or an older backend without this endpoint, must land on null (fail
 * closed) rather than on a truthy object that answers `can()` with undefined.
 */
export function parsePermissionMap(raw: unknown): PermissionMap | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const out: PermissionMap = {};
  for (const [resource, actions] of Object.entries(raw as Record<string, unknown>)) {
    if (!Array.isArray(actions)) return null;
    if (!actions.every((a) => typeof a === "string")) return null;
    out[resource] = actions as string[];
  }
  return out;
}
