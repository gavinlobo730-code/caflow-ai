"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Briefcase,
  UserCog,
  CalendarCheck,
  FileSpreadsheet,
  ShieldCheck,
  BarChart3,
  Scale,
  ExternalLink,
} from "lucide-react";
import { cn, isExactPath } from "@/lib/utils";
import { usePermissions } from "@/lib/auth/AuthContext";

/**
 * The Payroll workspace's browse surface (PAY-28, plan item 2.9).
 *
 * ⚠️ PAYROLL USED TO BE A LINK INSIDE ACCOUNTING AND ITS SCREENS SAT ACROSS
 * THREE TOP-LEVEL AREAS. `/payroll` and `/payroll/statutory` were in the
 * Accounting panel, `/payroll/attendance` was in the TEAM panel, and
 * `/payroll/people`, `/payroll/declarations` and `/payroll/reports` were in no
 * panel at all until 2.5 put all six under an Accounting sub-heading. So a
 * bureau running payroll for a dozen clients — which is a service a practice
 * SELLS, priced per employee per month — had no home screen for it, and half
 * its screens were somewhere a CA would have no reason to look.
 *
 * `docs/architecture/10-payroll.md` specifies the fix and specifies it as the
 * THIRTEENTH TOP-LEVEL WORKSPACE rather than a tidier sub-heading, which is
 * what this panel is. Everything a payroll month needs is now one rail click
 * away from everything else in it.
 *
 * ── SETUP IS A POINTER, NOT A SEVENTH SCREEN ────────────────────────────────
 *
 * The architecture doc's sixth section is **Setup**, at `/payroll/setup`,
 * carrying "calendars, statutory identity, pay components, state coverage".
 * That route does not exist and is deliberately NOT built here: the part of it
 * that matters — which states' professional tax and LWF this firm has recorded
 * slabs for, against `domain/payroll/professional_tax.py`'s list of the
 * twenty-two that levy — IS built, at `/settings/statutory-values`, over
 * `GET /api/payroll/statutory-values`. PAY-28's own verification pass
 * established that ("the firm-level PT state-coverage screen IS built ... it
 * lives under Settings rather than under /payroll/setup"). A second screen for
 * one fact is the mistake this codebase records at `/accounting/retainer` and
 * `/gst/reconciliation`, so payroll LINKS to it and Settings keeps owning it.
 *
 * The entry is drawn with an outbound mark, because a sidebar item that leaves
 * the workspace and silently relights a different rail icon is a navigation
 * surprise. `scripts/a-module-shows-all-of-itself.test.ts` still requires that
 * screen in `SettingsPanel`, which owns it; appearing here as well is a
 * cross-module convenience and satisfies nothing on its own.
 *
 * ── `requires`, AND WHY THIS PANEL WAITS FOR `resolved` ─────────────────────
 *
 * Read off the endpoint rather than guessed, as in every other panel. Every
 * screen below calls `routers/payroll.py`, whose endpoints are uniformly
 * `rbac("payroll", …)`, and each page's FIRST call is a read — including
 * Statutory Values, whose `GET /statutory-values` is `rbac("payroll","read")`
 * (only the `PUT`/`DELETE` that record a slab set are `write`), so a Reviewer
 * offered this link can see the coverage they are being asked about.
 *
 * ⚠️ EVERY ENTRY CARRIES ONE, WHICH IS WHAT MAKES THIS PANEL DIFFERENT — and
 * the first smoke walk of it rendered a HEADER OVER NOTHING. `can()` fails
 * closed while `GET /api/identity/permissions` is in flight, so a panel where
 * every item is gated has nothing to draw until it lands. Every other panel
 * has ungated entries (the Chart-of-Accounts screens, Work Allocation) and so
 * degrades to a partial list; this one degrades to a blank column with a
 * heading on it, which reads as a broken screen rather than a loading one.
 *
 * So it filters only once `resolved`, the same rule `WorkspaceRail` applies to
 * the tile that opens it — and that agreement is the point rather than a
 * coincidence. If the rail offers a workspace, its panel has to have something
 * in it; two different readings of the same permission map is how a CA gets a
 * workspace with nothing inside. Neither is a security boundary: `rbac()` is,
 * on the server, and each screen below answers 403 on its own.
 *
 * The resolved-and-empty case is a SENTENCE rather than a blank, because it is
 * reachable by typing the URL even when the rail has hidden the tile.
 */
type NavItem = {
  label: string;
  href: string;
  icon: typeof Briefcase;
  exact?: boolean;
  requires?: [resource: string, action: string];
  /** Renders the outbound mark: this entry leaves the Payroll workspace. */
  external?: boolean;
};

const NAV_GROUPS: Array<{ heading: string | null; items: NavItem[] }> = [
  {
    heading: null,
    items: [
      // The client-month queue — the bureau's screen on the 3rd and the 10th.
      { label: "Month", href: "/payroll", icon: Briefcase, exact: true,
        requires: ["payroll", "read"] },
    ],
  },
  {
    heading: "This month",
    items: [
      { label: "Attendance", href: "/payroll/attendance", icon: CalendarCheck,
        requires: ["payroll", "read"] },
      { label: "Declarations", href: "/payroll/declarations", icon: FileSpreadsheet,
        requires: ["payroll", "read"] },
    ],
  },
  {
    heading: "Roster",
    items: [
      { label: "Employees", href: "/payroll/people", icon: UserCog,
        requires: ["payroll", "read"] },
    ],
  },
  {
    heading: "Statutory",
    items: [
      { label: "Deposits & Filings", href: "/payroll/statutory", icon: ShieldCheck,
        requires: ["payroll", "read"] },
      { label: "Reports", href: "/payroll/reports", icon: BarChart3,
        requires: ["payroll", "read"] },
    ],
  },
  {
    heading: "Setup",
    items: [
      // See the header: this is the architecture doc's Setup section, and it
      // already exists under Settings. Linked, never rebuilt.
      { label: "PT & LWF Coverage", href: "/settings/statutory-values", icon: Scale,
        requires: ["payroll", "read"], external: true },
    ],
  },
];

export function PayrollPanel() {
  const pathname = usePathname();
  const { can, resolved } = usePermissions();

  const groups = NAV_GROUPS.map((g) => ({
    ...g,
    items: g.items.filter(
      (i) => !i.requires || !resolved || can(i.requires[0], i.requires[1]),
    ),
  })).filter((g) => g.items.length > 0);

  return (
    <div className="flex flex-col h-full text-brand">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-4 border-b border-gray-200 shrink-0">
        <div className="w-6 h-6 rounded-md bg-brand/10 flex items-center justify-center">
          <Briefcase size={12} className="text-brand" />
        </div>
        <div>
          <p className="text-xs font-semibold text-brand leading-none">Payroll</p>
          <p className="text-3xs text-gray-500 mt-0.5 leading-none">Across every client</p>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto py-2 px-2">
        {groups.length === 0 && (
          <p className="px-3 py-2 text-2xs text-gray-500 leading-relaxed">
            Payroll is open to Partners and Managers. Ask a Partner to grant
            you payroll access from Settings → Team.
          </p>
        )}
        {groups.map(({ heading, items }) => (
          <div key={heading ?? "_"} className={heading ? "mt-3 first:mt-0" : ""}>
            {heading && (
              <p className="px-3 pb-1 text-3xs font-semibold uppercase tracking-wider text-ps-hint">
                {heading}
              </p>
            )}
            {items.map(({ label, href, icon: Icon, exact, external }) => {
              const isActive = exact
                ? isExactPath(pathname, href)
                : pathname === href || pathname.startsWith(href + "/");
              return (
                <Link
                  key={href}
                  href={href}
                  className={cn(
                    "flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-colors mb-0.5",
                    isActive
                      ? "bg-brand text-white"
                      : "text-gray-600 hover:text-brand hover:bg-ps-bg"
                  )}
                >
                  <Icon size={13} className="shrink-0" />
                  <span className="flex-1 min-w-0">{label}</span>
                  {external && (
                    <ExternalLink
                      size={11}
                      className="shrink-0 opacity-50"
                      aria-label="opens in Settings"
                    />
                  )}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>
    </div>
  );
}
