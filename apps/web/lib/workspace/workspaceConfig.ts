import {
  LayoutDashboard,
  Users,
  Calendar,
  CheckSquare,
  UserCheck,
  Sparkles,
  BookOpen,
  Users2,
  Network,
  Activity,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

export type WorkspaceId = "home" | "clients" | "deadlines" | "work" | "team" | "ai" | "accounting" | "pipeline" | "relationships" | "health";

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
    id: "deadlines",
    label: "Deadlines",
    description: "Filing deadlines across clients",
    defaultRoute: "/deadlines",
    icon: Calendar,
  },
  {
    id: "work",
    label: "Work",
    description: "Firm-wide work queue",
    defaultRoute: "/work",
    icon: CheckSquare,
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
  {
    id: "accounting",
    label: "Accounting",
    description: "Chart of Accounts & firm accounting",
    defaultRoute: "/accounting/chart-of-accounts",
    icon: BookOpen,
  },
  {
    id: "pipeline",
    label: "Pipeline",
    description: "Leads & proposals",
    defaultRoute: "/pipeline",
    icon: Users2,
  },
  {
    id: "relationships",
    label: "Relationships",
    description: "Entity intelligence",
    defaultRoute: "/relationships",
    icon: Network,
  },
  {
    id: "health",
    label: "Health",
    description: "Client health monitor",
    defaultRoute: "/health",
    icon: Activity,
  },
];

export const DEFAULT_WORKSPACE_ROUTES: Record<WorkspaceId, string> = {
  home: "/",
  clients: "/clients",
  deadlines: "/deadlines",
  work: "/work",
  team: "/team",
  ai: "/ai-assistant",
  accounting: "/accounting/chart-of-accounts",
  pipeline: "/pipeline",
  relationships: "/relationships",
  health: "/health",
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
    pathname.startsWith("/deadlines") ||
    pathname.startsWith("/gst") ||
    pathname.startsWith("/income-tax") ||
    pathname.startsWith("/tds") ||
    pathname.startsWith("/mca")
  )
    return "deadlines";

  if (
    pathname.startsWith("/accounting") ||
    pathname.startsWith("/billing") ||
    pathname.startsWith("/payroll")
  )
    return "accounting";

  if (pathname.startsWith("/pipeline"))
    return "pipeline";

  if (pathname.startsWith("/relationships"))
    return "relationships";

  if (pathname.startsWith("/health"))
    return "health";

  if (pathname.startsWith("/work") || pathname.startsWith("/tasks"))
    return "work";

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
