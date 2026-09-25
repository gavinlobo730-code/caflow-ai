/**
 * Which workspace owns a route — the ONE copy of that mapping.
 *
 * It used to live in `workspaceConfig.ts`, which imports lucide-react and so
 * cannot be loaded by `node --experimental-strip-types --test`. That made the
 * rule unguardable: `scripts/a-module-shows-all-of-itself.test.ts` has to ask
 * "which panel serves this screen" for all 104 named firm screens, and its
 * only options were to re-implement this chain (a second copy, which is the
 * defect this repository records over and over) or to parse the source with a
 * regex (a spelling of the rule, which is the other one).
 *
 * So the chain MOVED here, with no imports at all, and `workspaceConfig.ts`
 * re-exports it — the same discipline `domain/sales/line_tax.py` took when
 * `compute_line_gst` moved out from under a router, and for the same reason.
 * Nothing that imports it today changes.
 *
 * Returns null for routes NO workspace owns — /settings (the rail's own gear
 * icon lights instead, and `ContextPanel` renders `SettingsPanel` off the path
 * rather than off a workspace), /platform (the super-admin console, which sits
 * above the firm workspace model entirely), /search (the palette's results
 * page, a cross-cutting utility) and /onboarding (the firm signup wizard,
 * which deliberately renders with no shell at all). null must NEVER be coerced
 * to "home" here; the "home" panel is a separate, deliberate CONTENT fallback
 * applied only by consumers that need to render *something* (see ContextPanel).
 */

export type WorkspaceId =
  | "home" | "clients" | "deadlines" | "work" | "team" | "ai"
  | "accounting" | "payroll" | "relationships" | "health"
  | "practice" | "knowledge" | "engagements";

export function getActiveWorkspaceForPathname(pathname: string): WorkspaceId | null {
  // ⚠️ ASKED BEFORE THE PREFIX CHAIN, and it is the one route here that needs
  // to be. `/onboarding/checklist` is the CLIENT-onboarding workflow tracker
  // ("Client Onboarding" is its own heading), not a step of the firm signup
  // wizard it shares a path prefix with — it reads `api.onboarding.listActive`
  // and walks a client through engagement setup. Sharing the prefix is what
  // made `AppShell`'s NO_SHELL list strip its sidebar, so the one screen that
  // tracks client onboarding rendered with no navigation and no ⌘K, and
  // nothing in the product linked to it. It belongs to Clients.
  if (pathname.startsWith("/onboarding/checklist")) return "clients";

  if (
    pathname === "/" ||
    pathname.startsWith("/calendar") ||
    pathname.startsWith("/notifications") ||
    // D1's `insights` hub tile lands here (Phase 3a-5). It belongs to Home
    // rather than to Health: the tile asks about health, RISK and
    // profitability across every client, which is the morning question the
    // Home workspace is for, while `/health` is one module's monitor.
    pathname.startsWith("/insights")
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

  // ⚠️ ASKED BEFORE ACCOUNTING, because `/payroll` used to fall into that
  // branch and this is the change (PAY-28 / plan item 2.9). Payroll was a
  // LINK inside the Accounting rail and its six screens sat across three
  // top-level areas — `/payroll` and `/payroll/statutory` under Accounting,
  // `/payroll/attendance` under Team, and `/payroll/people`, `/declarations`
  // and `/reports` in no panel at all until 2.5. A bureau running payroll for
  // a dozen clients had no home for the service it sells.
  // `docs/architecture/10-payroll.md` specifies the 13th top-level workspace
  // and this is it. Order is the whole mechanism: a prefix chain answers with
  // the first branch that matches, so a narrower prefix has to be asked first
  // or it is unreachable — the same reason `/onboarding/checklist` is at the
  // top of this function.
  if (pathname.startsWith("/payroll")) return "payroll";

  if (
    pathname.startsWith("/accounting") ||
    pathname.startsWith("/billing") ||
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

  // /settings, /platform, /search, /onboarding, and anything else
  // unrecognized: no workspace owns this route.
  return null;
}
