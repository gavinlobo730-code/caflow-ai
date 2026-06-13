"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutGrid,
  BookOpen,
  Shield,
  Users,
  CalendarCheck,
  FileText,
  FolderOpen,
  CheckSquare,
  BarChart3,
  Globe,
  Sparkles,
  ArrowLeft,
  ShoppingCart,
  Package,
  Landmark,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { ClientSection } from "@/lib/workspace/ClientNavContext";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

interface RailItem {
  section: ClientSection | "__back__";
  label: string;
  icon: React.ElementType;
  href: (clientId: string) => string;
}

const RAIL_ITEMS: RailItem[] = [
  { section: "overview",    label: "Overview",    icon: LayoutGrid,    href: (id) => `/clients/${id}/overview/` },
  { section: "accounting",  label: "Accounting",  icon: BookOpen,      href: (id) => `/clients/${id}/accounting/` },
  { section: "sales",       label: "Sales",       icon: ShoppingCart,  href: (id) => `/clients/${id}/sales/` },
  { section: "purchases",   label: "Purchases",   icon: Package,       href: (id) => `/clients/${id}/purchases/` },
  { section: "compliance",  label: "Compliance",  icon: Shield,        href: (id) => `/clients/${id}/compliance/` },
  { section: "payroll",      label: "Payroll",       icon: Users,     href: (id) => `/clients/${id}/payroll/` },
  { section: "fixed-assets", label: "Fixed Assets",  icon: Landmark,  href: (id) => `/clients/${id}/fixed-assets/` },
  { section: "year-end",    label: "Year End",    icon: CalendarCheck, href: (id) => `/clients/${id}/year-end/` },
  { section: "tax",         label: "Tax",         icon: FileText,      href: (id) => `/clients/${id}/tax/` },
  { section: "documents",   label: "Documents",   icon: FolderOpen,    href: (id) => `/clients/${id}/documents/` },
  { section: "tasks",       label: "Tasks",       icon: CheckSquare,   href: (id) => `/clients/${id}/tasks/` },
  { section: "reports",     label: "Reports",     icon: BarChart3,     href: (id) => `/clients/${id}/reports/` },
  { section: "portal",      label: "Portal",      icon: Globe,         href: (id) => `/clients/${id}/portal/` },
  { section: "ai-insights", label: "AI Insights", icon: Sparkles,      href: (id) => `/clients/${id}/ai-insights/` },
];

export function ClientRail() {
  const pathname = usePathname();
  const { clientId } = useClientNav();

  return (
    <div className="flex flex-col h-full w-[52px] shrink-0 bg-[#182350] border-r border-white/10">
      {/* Back to Firm */}
      <Link
        href="/clients"
        title="Back to Clients"
        className="flex items-center justify-center h-12 w-full text-slate-500 hover:text-white hover:bg-white/10 transition-colors border-b border-white/10"
      >
        <ArrowLeft size={16} />
      </Link>

      {/* Section icons */}
      <nav className="flex-1 flex flex-col items-center py-2 gap-0.5 overflow-y-auto">
        {RAIL_ITEMS.map(({ section, label, icon: Icon, href }) => {
          const target = href(clientId);
          const active = pathname.startsWith(target);
          return (
            <Link
              key={section}
              href={target}
              title={label}
              className={cn(
                "relative flex items-center justify-center w-9 h-9 rounded-lg transition-all duration-100",
                active
                  ? "bg-blue-600 text-white"
                  : "text-slate-500 hover:text-white hover:bg-white/10"
              )}
            >
              {active && (
                <span className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-5 bg-blue-400 rounded-r" />
              )}
              <Icon size={16} className="shrink-0" />
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
