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
  Briefcase,
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
  /**
   * The backend permission EVERY screen in this workspace needs, read off the
   * endpoints — the same `requires` convention the panels use, at workspace
   * granularity. Set only where one `rbac(...)` pair governs the whole module,
   * so a rail tile for it would open a panel with every entry filtered out.
   *
   * ⚠️ IT IS NOT A SECURITY BOUNDARY — `rbac()` is, on the server. This stops
   * the rail offering a destination that can only be empty.
   *
   * Used once, on Payroll: `core/permissions.PERMISSIONS["payroll"]["read"]`
   * is Partner and Manager, and all six payroll screens call
   * `routers/payroll.py`. Before PAY-28 those screens lived under Accounting,
   * whose panel has fourteen other entries, so an Executive simply saw the
   * panel without them; a workspace of their own has nothing else to show.
   *
   * It is resolved against the map the BACKEND serves
   * (`GET /api/identity/permissions`) rather than a role list here, because a
   * second copy of the matrix in TypeScript drifts silently and already had —
   * see `lib/auth/permissions.ts`. `canAccessWorkspace`'s role sets stay as
   * they are: they answer a different question (Practice exposes fee
   * economics; Deadlines and Work are hidden from delivery staff by product
   * decision, not by an rbac pair).
   */
  requires?: [resource: string, action: string];
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
    // PAY-28 / plan item 2.9 — payroll is ONE place. It was a link inside the
    // Accounting rail with its screens spread over three top-level areas;
    // `docs/architecture/10-payroll.md` specifies it as the 13th top-level
    // workspace, which is what a bureau selling payroll as a service needs.
    id: "payroll",
    label: "Payroll",
    description: "Payroll across every client",
    defaultRoute: "/payroll",
    icon: Briefcase,
    // payroll.py: every endpoint every payroll screen calls is rbac("payroll", …).
    requires: ["payroll", "read"],
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
  payroll: "/payroll",
  relationships: "/relationships",
  health: "/health",
  practice: "/practice",
  knowledge: "/knowledge",
  engagements: "/engagements",
};

