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
  FileText,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

export type WorkspaceId =
  | "home" | "clients" | "deadlines" | "work" | "team" | "ai"
  | "accounting" | "relationships" | "health"
  | "practice" | "knowledge" | "engagements";

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
    defaultRoute: "/accounting",
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
  {
    id: "engagements",
    label: "Engagements",
    description: "Engagement letters & agreements",
    defaultRoute: "/engagements",
    icon: FileText,
  },
];

export const DEFAULT_WORKSPACE_ROUTES: Record<WorkspaceId, string> = {
  home: "/",
  clients: "/clients",
  deadlines: "/deadlines",
  work: "/work",
  team: "/team",
  ai: "/ai-assistant",
  accounting: "/accounting",
  relationships: "/relationships",
  health: "/health",
  practice: "/practice",
  knowledge: "/knowledge",
  engagements: "/engagements",
};

/**
 * Maps the current pathname to the workspace whose rail icon should be lit
 * and whose lastRoute should be updated. Returns null for routes that are
 * NOT part of any workspace — /settings (its own gear icon lights instead,
 * see ActivityRail), /platform (the super-admin console, which sits above
 * the firm workspace model entirely and is never linked from any panel),
 * and /search (the global command-palette's results page, a cross-cutting
 * utility owned by no single workspace) — plus any route this mapping
 * doesn't yet recognize. null must NEVER be coerced to "home" here; the
 * "home" panel is a separate, deliberate content fallback applied only by
 * consumers that need to render *something* (see ContextPanel).
 */
export function getActiveWorkspaceForPathname(pathname: string): WorkspaceId | null {
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
    pathname.startsWith("/mca") ||
    pathname.startsWith("/einvoice")
  )
    return "deadlines";

  if (
    pathname.startsWith("/accounting") ||
    pathname.startsWith("/billing") ||
    pathname.startsWith("/payroll") ||
    pathname.startsWith("/migration")
  )
    return "accounting";

  if (pathname.startsWith("/relationships"))
    return "relationships";

  if (pathname.startsWith("/health"))
    return "health";

  if (pathname.startsWith("/practice") || pathname.startsWith("/executive-dashboard"))
    return "practice";

  if (pathname.startsWith("/knowledge"))
    return "knowledge";

  if (pathname.startsWith("/engagements"))
    return "engagements";

  if (
    pathname.startsWith("/work") ||
    pathname.startsWith("/tasks") ||
    pathname.startsWith("/time")
  )
    return "work";

  if (pathname.startsWith("/team") || pathname.startsWith("/approvals"))
    return "team";

  if (
    pathname.startsWith("/ai-assistant") ||
    pathname.startsWith("/assistant") ||
    pathname.startsWith("/risks") ||
    pathname.startsWith("/reports") ||
    pathname.startsWith("/copilot") ||
    pathname.startsWith("/memory")
  )
    return "ai";

  // /settings, /platform, /search, and anything else unrecognized: no
  // workspace owns this route.
  return null;
}
