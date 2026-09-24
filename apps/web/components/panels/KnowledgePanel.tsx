"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Library, FileText, Building, Search, Tag, Clock } from "lucide-react";
import { cn, isExactPath } from "@/lib/utils";

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
  return (
    <div className="flex flex-col h-full text-brand">
      <div className="flex items-center gap-2 px-4 py-4 border-b border-gray-200 shrink-0">
        <div className="w-6 h-6 rounded-md bg-brand/10 flex items-center justify-center">
          <Library size={12} className="text-brand" />
        </div>
        <div>
          <p className="text-xs font-semibold text-brand leading-none">Knowledge</p>
          <p className="text-3xs text-gray-500 mt-0.5 leading-none">Firm SOPs &amp; policies</p>
        </div>
      </div>
      <nav className="flex-1 overflow-y-auto py-2 px-2">
        {NAV_ITEMS.map(({ label, href, icon: Icon }) => {
          const [hrefPath, hrefQuery = ""] = href.split("?");
          const isActive = isExactPath(pathname, hrefPath) && params.toString() === hrefQuery;
          return (
            <Link
              key={label}
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
