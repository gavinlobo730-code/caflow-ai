"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Building2, BookOpen, LayoutDashboard, IndianRupee, Receipt, Wallet, ClipboardList,
  StickyNote, ShieldCheck, Gauge, TrendingUp, BarChart3, History, UserCheck, Link2,
} from "lucide-react";
import { cn, isExactPath } from "@/lib/utils";
import { usePracticeClient } from "@/lib/workspace/usePracticeClient";
import { usePermissions } from "@/lib/auth/AuthContext";
import { LoadingRegion, Skeleton } from "@/components/ui/skeleton";

// Amendment v1.1 — Practice workspace (Partner-only). Revenue Operations home.
const NAV_ITEMS = [
  { label: "Overview",     href: "/practice",             icon: LayoutDashboard },
  { label: "Executive Dashboard", href: "/executive-dashboard", icon: Gauge },
  { label: "Revenue",      href: "/practice/revenue",     icon: IndianRupee },
  { label: "Profitability", href: "/practice/profitability", icon: TrendingUp },
  // The TAX half of the same question — where a client sits in the firm's own
  // distribution of effective tax rate, ITC-to-purchases and the rest. Beside
  // Profitability deliberately: the two are the fee and tax halves of "where
  // does this client sit", and a reader who has opened one wants the other.
  { label: "Client benchmark", href: "/practice/benchmark", icon: BarChart3 },
  { label: "Billing Schedules", href: "/practice/billing", icon: Receipt },
  { label: "Collections",  href: "/practice/collections", icon: Wallet },
  { label: "AR Aging",     href: "/practice/ar",          icon: ClipboardList },
  { label: "Compliance Workload", href: "/practice/compliance", icon: ShieldCheck },
  // Knowledge Base intentionally omitted here — it lives in the dedicated,
  // all-staff Knowledge workspace (/knowledge), not under Partner-only Practice.
  { label: "Practice instructions", href: "/practice/instructions", icon: StickyNote },
  // The fee bills raised on the old Fee Billing screen, kept as a read-only record (POST-B-193).
  { label: "Earlier fee bills", href: "/billing", icon: History },
  // What is still owed on them, by age (`fee_invoices`). It was "Fee Receivables" on the Accounting menu.
  { label: "Earlier fee receivables", href: "/accounting/receivables", icon: History },
];

/**
 * THE PEOPLE OF THE FIRM, LISTED HERE FOR WHOEVER HAS MY PRACTICE (the owner's decision of 21-11-2026). These five screens
 * are the Team menu's own (`TeamPanel`, the door of somebody with no My practice), in the same words, with the rbac pair each
 * screen's reads need; `lib/workspace/practiceWorkspace.PRACTICE_PEOPLE_SECTIONS` is the list both are held to, by
 * `practiceWorkspace.test.ts`. They are written out here and not imported so that the rule "a screen is listed in one
 * panel" (`scripts/a-screen-has-one-home.test.ts`) reads this panel as listing them, which it does, and carries the argument.
 */
const PEOPLE_ITEMS: Array<{ label: string; href: string; icon: typeof UserCheck; requires: [resource: string, action: string] }> = [
  { label: "Team", href: "/team", icon: UserCheck, requires: ["team", "read"] },
  { label: "Assignments", href: "/team/assignments", icon: Link2, requires: ["assignment", "read"] },
  { label: "Approvals", href: "/approvals", icon: ShieldCheck, requires: ["approval", "read"] },
  { label: "Workload", href: "/team/workload", icon: Gauge, requires: ["workload", "read"] },
  { label: "Login History", href: "/team/login-history", icon: History, requires: ["team", "read"] },
];

const ROW = "flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-colors mb-0.5";

export function PracticePanel() {
  const pathname = usePathname();
  // The firm's own books are a client workspace whose id only the server knows (POST-A-532), so the row that opens them
  // cannot be a link until the server has answered. THE ROW KEEPS ITS PLACE WHILE IT WAITS: it used to be drawn only once the
  // id arrived, so the eleven rows under it moved down a row a moment after the menu opened, under the pointer (the owner's
  // review of the live Test Firm, 21-11-2026). It is a placeholder while the id is read, a link to the books once it is, a
  // link to Practice home (which sets the books up) when they are not set up, and a plain sentence when the read failed.
  const practice = usePracticeClient(true);
  const { can, resolved } = usePermissions();
  const people = PEOPLE_ITEMS.filter((i) => !resolved || can(i.requires[0], i.requires[1]));
  return (
    <div className="flex flex-col h-full text-brand">
      <div className="flex items-center gap-2 px-4 py-4 border-b border-gray-200 shrink-0">
        <div className="w-6 h-6 rounded-md bg-brand/10 flex items-center justify-center">
          <Building2 size={12} className="text-brand" />
        </div>
        <div>
          <p className="text-xs font-semibold text-brand leading-none">My practice</p>
          <p className="text-3xs text-gray-500 mt-0.5 leading-none">Your own firm: books, billing and revenue</p>
        </div>
      </div>
      <nav className="flex-1 overflow-y-auto py-2 px-2">
        {practice.state === "ready" ? (
          <Link
            href={`/clients/${practice.practiceId}/`}
            data-practice-books="ready"
            className={cn(ROW, "text-gray-600 hover:text-brand hover:bg-ps-bg")}
          >
            <BookOpen size={13} className="shrink-0" />
            Your firm&apos;s books
          </Link>
        ) : practice.state === "not-set-up" ? (
          <Link href="/practice" data-practice-books="not-set-up" className={cn(ROW, "text-gray-600 hover:text-brand hover:bg-ps-bg")}>
            <BookOpen size={13} className="shrink-0" />
            Set up your firm&apos;s books
          </Link>
        ) : practice.state === "unavailable" ? (
          <p role="status" data-practice-books="unavailable" className={cn(ROW, "text-ps-label")}>
            <BookOpen size={13} className="shrink-0" />
            Your firm&apos;s books could not be read
          </p>
        ) : (
          <div data-practice-books="reading">
            <LoadingRegion label="Loading your firm's books" className={ROW}>
              <Skeleton className="h-4 w-full rounded" />
            </LoadingRegion>
          </div>
        )}
        {NAV_ITEMS.map(({ label, href, icon: Icon }) => {
          // Exact match for /practice so it isn't always active for sub-routes.
          const isActive = href === "/practice"
            ? isExactPath(pathname, "/practice")
            : pathname === href || pathname.startsWith(href + "/");
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                ROW,
                isActive ? "bg-brand text-white" : "text-gray-600 hover:text-brand hover:bg-ps-bg"
              )}
            >
              <Icon size={13} className="shrink-0" />
              {label}
            </Link>
          );
        })}
        {people.length > 0 && (
          <div role="group" aria-labelledby="practice-panel-people" data-practice-people>
            <p id="practice-panel-people" className="text-3xs font-semibold uppercase tracking-[0.08em] text-ps-hint px-3 mb-1.5 mt-3">
              People
            </p>
            {people.map(({ label, href, icon: Icon }) => {
              const isActive = href === "/team"
                ? isExactPath(pathname, "/team")
                : pathname === href || pathname.startsWith(href + "/");
              return (
                <Link
                  key={href}
                  href={href}
                  className={cn(ROW, isActive ? "bg-brand text-white" : "text-gray-600 hover:text-brand hover:bg-ps-bg")}
                >
                  <Icon size={13} className="shrink-0" />
                  {label}
                </Link>
              );
            })}
          </div>
        )}
      </nav>
    </div>
  );
}
