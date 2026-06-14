"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Library, FileText, Building, Search, Tag, Clock } from "lucide-react";
import { cn } from "@/lib/utils";

// Amendment v1.1 — Knowledge workspace (all staff). Firm/department articles.
const NAV_ITEMS = [
  { label: "All Articles",        href: "/knowledge",                     icon: FileText },
  { label: "Firm Articles",       href: "/knowledge?scope=firm",          icon: Building },
  { label: "Department Articles", href: "/knowledge?scope=department",     icon: Building },
  { label: "Search",              href: "/knowledge?focus=search",        icon: Search },
  { label: "Tags",                href: "/knowledge?focus=tags",           icon: Tag },
  { label: "Recent Updates",      href: "/knowledge?sort=recent",          icon: Clock },
];

export function KnowledgePanel() {
  const pathname = usePathname();
  const params = useSearchParams();
  const current = `${pathname}${params.toString() ? "?" + params.toString() : ""}`;
  return (
    <div className="flex flex-col h-full text-[#182350]">
      <div className="flex items-center gap-2 px-4 py-4 border-b border-gray-200 shrink-0">
        <div className="w-6 h-6 rounded-md bg-[#182350]/10 flex items-center justify-center">
          <Library size={12} className="text-[#182350]" />
        </div>
        <div>
          <p className="text-[12px] font-semibold text-[#182350] leading-none">Knowledge</p>
          <p className="text-[10px] text-gray-500 mt-0.5 leading-none">Firm SOPs &amp; policies</p>
        </div>
      </div>
      <nav className="flex-1 overflow-y-auto py-2 px-2">
        {NAV_ITEMS.map(({ label, href, icon: Icon }) => {
          const isActive = current === href || (href === "/knowledge" && pathname === "/knowledge" && !params.toString());
          return (
            <Link
              key={label}
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
