"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Building2, BookOpen, LayoutDashboard, IndianRupee, Receipt, Wallet, ClipboardList,
  StickyNote, ShieldCheck, Gauge, TrendingUp, BarChart3, History,
} from "lucide-react";
import { cn, isExactPath } from "@/lib/utils";
import { usePracticeClient } from "@/lib/workspace/usePracticeClient";

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

export function PracticePanel() {
  const pathname = usePathname();
  // The firm's own books are a client workspace whose id only the server knows (POST-A-532). The link is drawn once the id
  // is; a practice that is not set up, or a read that failed, draws no link here, and Overview below says which it is.
  const practice = usePracticeClient(true);
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
        {practice.state === "ready" && (
          <Link
            href={`/clients/${practice.practiceId}/`}
           
            className="flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-colors mb-0.5 text-gray-600 hover:text-brand hover:bg-ps-bg"
          >
            <BookOpen size={13} className="shrink-0" />
            Your firm&apos;s books
          </Link>
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
                "flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-colors mb-0.5",
                isActive ? "bg-brand text-white" : "text-gray-600 hover:text-brand hover:bg-ps-bg"
              )}
            >
              <Icon size={13} className="shrink-0" />
              {label}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
