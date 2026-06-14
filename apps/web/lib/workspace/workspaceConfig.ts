import {
  LayoutDashboard,
  Users,
  Calendar,
  CheckSquare,
  UserCheck,
  Sparkles,
  BookOpen,
  Network,
  Activity,
  Building2,
  Library,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

export type WorkspaceId =
  | "home" | "clients" | "deadlines" | "work" | "team" | "ai"
  | "accounting" | "relationships" | "health"
  | "practice" | "knowledge";

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
  {
    // Amendment v1.1 — firm-as-internal-client + Revenue Operations (Partner-only).
    id: "practice",
    label: "Practice",
    description: "Firm revenue & practice operations",
    defaultRoute: "/practice",
    icon: Building2,
  },
  {
    // Amendment v1.1 — Knowledge Base (all staff).
    id: "knowledge",
    label: "Knowledge",
    description: "Firm SOPs & knowledge base",
    defaultRoute: "/knowledge",
    icon: Library,
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
  relationships: "/relationships",
  health: "/health",
  practice: "/practice",
  knowledge: "/knowledge",
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

  if (pathname.startsWith("/relationships"))
    return "relationships";

  if (pathname.startsWith("/health"))
    return "health";

  if (pathname.startsWith("/practice"))
    return "practice";

  if (pathname.startsWith("/knowledge"))
    return "knowledge";

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
