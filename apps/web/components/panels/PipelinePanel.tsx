"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Users2,
  LayoutGrid,
  FileText,
  UserPlus,
  RefreshCw,
} from "lucide-react";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { label: "Pipeline Overview", href: "/pipeline",              icon: LayoutGrid },
  { label: "Leads",             href: "/pipeline/leads",        icon: Users2 },
  { label: "Proposals",         href: "/pipeline/proposals",    icon: FileText },
  { label: "Onboarding",        href: "/pipeline/onboarding",   icon: UserPlus },
  { label: "Renewals",          href: "/pipeline/renewals",     icon: RefreshCw },
];

export function PipelinePanel() {
  const pathname = usePathname();

  return (
    <div className="flex flex-col h-full text-[#182350]">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-4 border-b border-gray-200 shrink-0">
        <div className="w-6 h-6 rounded-md bg-[#182350]/10 flex items-center justify-center">
          <Users2 size={12} className="text-[#182350]" />
        </div>
        <div>
          <p className="text-[12px] font-semibold text-[#182350] leading-none">Pipeline</p>
          <p className="text-[10px] text-gray-500 mt-0.5 leading-none">Leads &amp; proposals</p>
        </div>
      </div>

      {/* Nav items */}
      <nav className="flex-1 overflow-y-auto py-2 px-2">
        {NAV_ITEMS.map(({ label, href, icon: Icon }) => {
          const isActive =
            href === "/pipeline"
              ? pathname === "/pipeline"
              : pathname === href || pathname.startsWith(href + "/");
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-2.5 px-3 py-2 rounded-lg text-[12px] font-medium transition-colors mb-0.5",
                isActive
                  ? "bg-[#182350] text-white"
                  : "text-gray-600 hover:text-[#182350] hover:bg-[#F8FAFC]"
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
