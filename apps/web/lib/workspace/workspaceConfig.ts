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

// The workspace vocabulary and the pathname→workspace chain both live in
// `routeOwnership.ts`, which has NO imports so a node --test guard can load it
// (see its header). Re-exported here so every existing importer is untouched.
export type { WorkspaceId } from "./routeOwnership";
export { getActiveWorkspaceForPathname } from "./routeOwnership";
import type { WorkspaceId } from "./routeOwnership";

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

