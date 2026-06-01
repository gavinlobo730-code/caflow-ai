import { can, isAtLeast, type Role } from "./roles";

export function requirePermission(role: Role, resource: string, action: "read" | "write" | "approve" | "delete" | "export" | "admin"): void {
  if (!can(role, resource, action)) {
    throw new Error(`Permission denied: ${role} cannot ${action} ${resource}`);
  }
}

export function withPermission<T>(
  role: Role,
  resource: string,
  action: "read" | "write" | "approve" | "delete" | "export" | "admin",
  fn: () => T,
  fallback: T,
): T {
  return can(role, resource, action) ? fn() : fallback;
}

export function getNavItemsForRole(role: Role): string[] {
  const routes: string[] = ["/", "/clients", "/tasks"];
  if (can(role, "team", "read")) routes.push("/team");
  if (can(role, "accounting", "read")) routes.push("/accounting");
  if (can(role, "compliance_record", "read")) {
    routes.push("/gst", "/income-tax", "/tds", "/mca", "/calendar");
  }
  if (can(role, "document", "read")) routes.push("/parser");
  routes.push("/assistant");
  if (can(role, "report", "read")) routes.push("/reports");
  if (can(role, "settings", "read")) routes.push("/settings");
  return routes;
}

export { isAtLeast };
