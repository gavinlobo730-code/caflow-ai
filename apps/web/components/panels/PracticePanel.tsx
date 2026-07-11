"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Building2, LayoutDashboard, IndianRupee, Receipt, Wallet, ClipboardList,
  StickyNote, ShieldCheck, Gauge,
} from "lucide-react";
import { cn, isExactPath } from "@/lib/utils";

// Amendment v1.1 — Practice workspace (Partner-only). Revenue Operations home.
const NAV_ITEMS = [
  { label: "Overview",     href: "/practice",             icon: LayoutDashboard },
  { label: "Executive Dashboard", href: "/executive-dashboard", icon: Gauge },
  { label: "Revenue",      href: "/practice/revenue",     icon: IndianRupee },
  { label: "Billing",      href: "/practice/billing",     icon: Receipt },
  { label: "Collections",  href: "/practice/collections", icon: Wallet },
  { label: "AR Aging",     href: "/practice/ar",          icon: ClipboardList },
  { label: "Compliance Workload", href: "/practice/compliance", icon: ShieldCheck },
  // Knowledge Base intentionally omitted here — it lives in the dedicated,
  // all-staff Knowledge workspace (/knowledge), not under Partner-only Practice.
  { label: "Instructions", href: "/practice/instructions", icon: StickyNote },
];

export function PracticePanel() {
  const pathname = usePathname();
  return (
    <div className="flex flex-col h-full text-[#182350]">
      <div className="flex items-center gap-2 px-4 py-4 border-b border-gray-200 shrink-0">
        <div className="w-6 h-6 rounded-md bg-[#182350]/10 flex items-center justify-center">
          <Building2 size={12} className="text-[#182350]" />
        </div>
        <div>
          <p className="text-[12px] font-semibold text-[#182350] leading-none">Practice</p>
          <p className="text-[10px] text-gray-500 mt-0.5 leading-none">Firm revenue &amp; operations</p>
        </div>
      </div>
      <nav className="flex-1 overflow-y-auto py-2 px-2">
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
                "flex items-center gap-2.5 px-3 py-2 rounded-lg text-[12px] font-medium transition-colors mb-0.5",
                isActive ? "bg-[#182350] text-white" : "text-gray-600 hover:text-[#182350] hover:bg-[#F8FAFC]"
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
