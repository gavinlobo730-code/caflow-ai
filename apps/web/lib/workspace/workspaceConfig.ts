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
  /**
   * The label as the 64px RAIL draws it, where `label` is too wide.
   *
   * ⚠️ IT IS THE SAME WORD WITH A ZERO-WIDTH SPACE IN IT, not an abbreviation.
   * The 24-09 smoke shots caught "Relationships" rendering as "elationship"
   * and "Engagements" as "ngagement" on every firm screen — clipped mid-word
   * by a 52px rail with no truncation. Widening to 64px fixed ten of the
   * twelve and left these two ellipsised ("Relationsh…"), and the width that
   * would fit them whole is about 84px, which is not an icon rail any more.
   *
   * U+200B lets the browser break the word where a person would, so the rail
   * shows "Relation / ships" over two lines — the WHOLE word, rather than a
   * shortening somebody has to learn. `title` still carries the description,
   * and nothing else in the product reads this field: the panels and the
   * palette use `label`.
   */
  railLabel?: string;
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
    railLabel: "Relation\u200Bships",
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
    railLabel: "Engage\u200Bments",
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

