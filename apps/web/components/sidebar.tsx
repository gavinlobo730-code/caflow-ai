"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard, Users, CheckSquare, UserCheck,
  BookOpen, FileText, Receipt, Calculator, Building2,
  Calendar, MessageSquare, BarChart3, Settings,
  ChevronLeft, ChevronRight, Landmark, Shield,
} from "lucide-react";
import { cn } from "@/lib/utils";

const NAV_GROUPS = [
  {
    label: "Operations",
    items: [
      { href: "/", label: "Dashboard", icon: LayoutDashboard },
      { href: "/clients", label: "Clients", icon: Users },
      { href: "/tasks", label: "Tasks", icon: CheckSquare },
      { href: "/team", label: "Team", icon: UserCheck },
    ],
  },
  {
    label: "Tax Modules",
    items: [
      { href: "/accounting", label: "Accounting", icon: BookOpen },
      { href: "/compliance", label: "Compliance", icon: Shield },
      { href: "/gst", label: "GST", icon: Receipt },
      { href: "/income-tax", label: "Income Tax", icon: Calculator },
      { href: "/tds", label: "TDS", icon: Landmark },
      { href: "/mca", label: "MCA", icon: Building2 },
    ],
  },
  {
    label: "Tools",
    items: [
      { href: "/parser", label: "Documents", icon: FileText },
      { href: "/calendar", label: "Calendar", icon: Calendar },
      { href: "/assistant", label: "AI Assistant", icon: MessageSquare },
      { href: "/reports", label: "Reports", icon: BarChart3 },
      { href: "/settings", label: "Settings", icon: Settings },
    ],
  },
];

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const pathname = usePathname();

  return (
    <aside
      className={cn(
        "flex flex-col bg-white border-r border-gray-100 transition-all duration-200 shrink-0",
        collapsed ? "w-14" : "w-56"
      )}
    >
      {/* Logo */}
      <div className="flex items-center justify-between px-3 py-4 border-b border-gray-100">
        {!collapsed && (
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-md bg-blue-600 flex items-center justify-center">
              <span className="text-white text-xs font-bold">CA</span>
            </div>
            <span className="font-semibold text-gray-900 text-sm tracking-tight">CAflow AI</span>
          </div>
        )}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className={cn(
            "p-1 rounded-md hover:bg-gray-100 text-gray-400 transition-colors",
            collapsed && "mx-auto"
          )}
        >
          {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
        </button>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-4">
        {NAV_GROUPS.map((group) => (
          <div key={group.label}>
            {!collapsed && (
              <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest px-2 mb-1">
                {group.label}
              </p>
            )}
            <div className="space-y-0.5">
              {group.items.map(({ href, label, icon: Icon }) => {
                const active = pathname === href;
                return (
                  <Link
                    key={href}
                    href={href}
                    title={collapsed ? label : undefined}
                    className={cn(
                      "flex items-center gap-2.5 px-2 py-1.5 rounded-md text-[13px] font-medium transition-colors",
                      active
                        ? "bg-blue-50 text-blue-700"
                        : "text-gray-600 hover:bg-gray-50 hover:text-gray-900"
                    )}
                  >
                    <Icon size={15} className="shrink-0" />
                    {!collapsed && <span>{label}</span>}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* User */}
      <div className={cn(
        "border-t border-gray-100 p-3 flex items-center gap-2.5",
        collapsed && "justify-center"
      )}>
        <div className="w-7 h-7 rounded-full bg-blue-600 text-white flex items-center justify-center text-xs font-semibold shrink-0">
          GL
        </div>
        {!collapsed && (
          <div className="min-w-0">
            <p className="text-xs font-semibold text-gray-900 truncate">Gavin Lobo, CA</p>
            <p className="text-[11px] text-gray-400 truncate">Partner</p>
          </div>
        )}
      </div>
    </aside>
  );
}
