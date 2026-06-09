import {
  LayoutDashboard,
  Users,
  Shield,
  Calculator,
  UserCheck,
  Sparkles,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

export type WorkspaceId = "home" | "clients" | "compliance" | "accounts" | "team" | "ai";

export interface WorkspaceConfig {
  id: WorkspaceId;
  label: string;
  description: string;
  defaultRoute: string;
  icon: LucideIcon;
}

export const WORKSPACE_CONFIGS: WorkspaceConfig[] = [
  {
    id: "home",
    label: "Home",
    description: "Today's priorities",
    defaultRoute: "/",
    icon: LayoutDashboard,
  },
  {
    id: "clients",
    label: "Clients",
    description: "Client management",
    defaultRoute: "/clients",
    icon: Users,
  },
  {
    id: "compliance",
    label: "Comply",
    description: "Filing deadlines (read-only)",
    defaultRoute: "/compliance",
    icon: Shield,
  },
  {
    id: "accounts",
    label: "Accounts",
    description: "Accounting & payroll",
    defaultRoute: "/accounting",
    icon: Calculator,
  },
  {
    id: "team",
    label: "Team",
    description: "Staff & tasks",
    defaultRoute: "/team",
    icon: UserCheck,
  },
  {
    id: "ai",
    label: "AI",
    description: "Intelligence & reports",
    defaultRoute: "/ai-assistant",
    icon: Sparkles,
  },
];

export const DEFAULT_WORKSPACE_ROUTES: Record<WorkspaceId, string> = {
  home: "/",
  clients: "/clients",
  compliance: "/compliance",
  accounts: "/accounting",
  team: "/team",
  ai: "/ai-assistant",
};

/**
 * Maps the current pathname to the most appropriate workspace.
 * Used to sync active workspace when navigating directly via URL.
 */
export function getWorkspaceForPathname(pathname: string): WorkspaceId {
  if (
    pathname === "/" ||
    pathname.startsWith("/calendar") ||
    pathname.startsWith("/notifications")
  )
    return "home";

  if (
    pathname.startsWith("/clients") ||
    pathname.startsWith("/pipeline") ||
    pathname.startsWith("/client-portal") ||
    pathname.startsWith("/documents")
  )
    return "clients";

  if (
    pathname.startsWith("/compliance") ||
    pathname.startsWith("/gst") ||
    pathname.startsWith("/income-tax") ||
    pathname.startsWith("/tds") ||
    pathname.startsWith("/mca")
  )
    return "compliance";

  if (
    pathname.startsWith("/accounting") ||
    pathname.startsWith("/billing") ||
    pathname.startsWith("/payroll")
  )
    return "accounts";

  if (pathname.startsWith("/team") || pathname.startsWith("/tasks"))
    return "team";

  if (
    pathname.startsWith("/ai-assistant") ||
    pathname.startsWith("/assistant") ||
    pathname.startsWith("/risks") ||
    pathname.startsWith("/reports")
  )
    return "ai";

  return "home";
}
