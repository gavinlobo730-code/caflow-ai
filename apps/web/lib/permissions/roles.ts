// Role definitions — mirrors backend core/permissions.py exactly

export const ROLES = {
  PARTNER:   "Partner",
  MANAGER:   "Manager",
  EXECUTIVE: "Executive",
  REVIEWER:  "Reviewer",
  CLIENT:    "Client",
} as const;

export type Role = typeof ROLES[keyof typeof ROLES];

// Role hierarchy — index 0 = least privileged
export const ROLE_HIERARCHY: Role[] = [
  ROLES.CLIENT,
  ROLES.REVIEWER,
  ROLES.EXECUTIVE,
  ROLES.MANAGER,
  ROLES.PARTNER,
];

type Action = "read" | "write" | "approve" | "delete" | "export" | "admin";

export const PERMISSIONS: Record<string, Partial<Record<Action, Role[]>>> = {
  firm:               { read: [ROLES.PARTNER, ROLES.MANAGER], write: [ROLES.PARTNER], admin: [ROLES.PARTNER] },
  client:             { read: [ROLES.PARTNER, ROLES.MANAGER, ROLES.EXECUTIVE, ROLES.REVIEWER], write: [ROLES.PARTNER, ROLES.MANAGER], delete: [ROLES.PARTNER] },
  compliance_record:  { read: [ROLES.PARTNER, ROLES.MANAGER, ROLES.EXECUTIVE, ROLES.REVIEWER], write: [ROLES.PARTNER, ROLES.MANAGER, ROLES.EXECUTIVE], approve: [ROLES.PARTNER, ROLES.MANAGER] },
  task:               { read: [ROLES.PARTNER, ROLES.MANAGER, ROLES.EXECUTIVE, ROLES.REVIEWER], write: [ROLES.PARTNER, ROLES.MANAGER, ROLES.EXECUTIVE] },
  document:           { read: [ROLES.PARTNER, ROLES.MANAGER, ROLES.EXECUTIVE, ROLES.REVIEWER], write: [ROLES.PARTNER, ROLES.MANAGER, ROLES.EXECUTIVE], approve: [ROLES.PARTNER, ROLES.MANAGER, ROLES.REVIEWER] },
  team:               { read: [ROLES.PARTNER, ROLES.MANAGER], write: [ROLES.PARTNER] },
  report:             { read: [ROLES.PARTNER, ROLES.MANAGER, ROLES.REVIEWER], export: [ROLES.PARTNER, ROLES.MANAGER] },
  settings:           { read: [ROLES.PARTNER, ROLES.MANAGER], write: [ROLES.PARTNER] },
  accounting:         { read: [ROLES.PARTNER, ROLES.MANAGER, ROLES.EXECUTIVE], write: [ROLES.PARTNER, ROLES.MANAGER], approve: [ROLES.PARTNER] },
};

export function can(role: Role, resource: string, action: Action): boolean {
  return PERMISSIONS[resource]?.[action]?.includes(role) ?? false;
}

export function isAtLeast(role: Role, minimum: Role): boolean {
  return ROLE_HIERARCHY.indexOf(role) >= ROLE_HIERARCHY.indexOf(minimum);
}
