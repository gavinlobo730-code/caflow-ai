"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard, Users, CheckSquare, UserCheck,
  Receipt, Calculator, Building2,
  Calendar, BarChart3, Settings,
  ChevronLeft, ChevronRight, Landmark, Shield,
  ShieldAlert, Sparkles, Bell, LogOut,
  ExternalLink, Menu, X, KanbanSquare, MessageSquare, KeyRound,
  Search, Briefcase, Clock, LayoutList, Activity,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth/AuthContext";
import { canAccessHref } from "@/lib/auth/permissions";
import { SearchModal } from "@/components/SearchModal";
import { LogoIcon, LogoWordmark } from "@/components/LogoIcon";

const NAV_GROUPS = [
  {
    label: "Operations",
    items: [
      { href: "/", label: "Dashboard", icon: LayoutDashboard },
      { href: "/work", label: "My Work", icon: LayoutList },
      { href: "/clients", label: "Clients", icon: Users },
      { href: "/pipeline", label: "Pipeline", icon: KanbanSquare },
      { href: "/client-portal", label: "Client Portal", icon: ExternalLink },
      { href: "/tasks", label: "Tasks", icon: CheckSquare },
      { href: "/tasks/templates", label: "Task Templates", icon: CheckSquare },
      { href: "/time", label: "Time Tracking", icon: Clock },
      { href: "/team", label: "Team", icon: UserCheck },
      { href: "/team/workload", label: "Workload", icon: Activity },
    ],
  },
  {
    label: "Tax & Compliance",
    items: [
      { href: "/compliance", label: "Compliance", icon: Shield },
      { href: "/gst", label: "GST", icon: Receipt },
      { href: "/gst/gstr3b", label: "GSTR-3B", icon: Receipt },
      { href: "/gst/gstr1", label: "GSTR-1", icon: Receipt },
      { href: "/income-tax", label: "Income Tax", icon: Calculator },
      { href: "/tds", label: "TDS", icon: Landmark },
      { href: "/tds/returns", label: "TDS Returns", icon: Landmark },
      { href: "/mca", label: "MCA", icon: Building2 },
    ],
  },
  {
    label: "Payroll & Billing",
    items: [
      { href: "/payroll", label: "Payroll", icon: Briefcase },
      { href: "/billing", label: "Fee Billing", icon: Receipt },
    ],
  },
  {
    label: "Tools & AI",
    items: [
      { href: "/ai-assistant", label: "AI Assistant", icon: Sparkles },
      { href: "/risks", label: "Risk Intelligence", icon: ShieldAlert },
      { href: "/calendar", label: "Calendar", icon: Calendar },
      { href: "/reports", label: "Reports", icon: BarChart3 },
      { href: "/reports/analytics", label: "Analytics", icon: BarChart3 },
      { href: "/notifications/whatsapp", label: "WhatsApp", icon: MessageSquare },
      { href: "/notifications", label: "Notifications", icon: Bell },
      { href: "/settings", label: "Settings", icon: Settings },
      { href: "/settings/dsc-tracker", label: "DSC Tracker", icon: KeyRound },
    ],
  },
];

function SidebarContent({
  collapsed,
  setCollapsed,
  onNavClick,
}: {
  collapsed: boolean;
  setCollapsed: (v: boolean) => void;
  onNavClick?: () => void;
}) {
  const pathname = usePathname();
  const { user, userRole, signOut } = useAuth();
  const [searchOpen, setSearchOpen] = useState(false);

  const initials = user?.email?.slice(0, 2).toUpperCase() ?? "CA";
  const displayEmail = user?.email ?? "user@firm.com";

  return (
    <aside
      className={cn(
        "flex flex-col h-full transition-all duration-200 shrink-0",
        "bg-[#F0F7FF]",
        collapsed ? "w-[60px]" : "w-[220px]"
      )}
    >
      <SearchModal open={searchOpen} onClose={() => setSearchOpen(false)} />
      {/* Logo */}
      <div className={cn(
        "flex items-center border-b border-[#BFDBFE] shrink-0",
        collapsed ? "justify-center px-0 py-4 h-14" : "justify-between px-4 py-4 h-14"
      )}>
        {!collapsed && <LogoWordmark size="sm" />}
        {collapsed && (
          <LogoIcon size="sm" />
        )}
        {!collapsed && (
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="p-1 rounded-md text-[#94A3B8] hover:text-[#475569] hover:bg-[#DBEAFE] transition-colors hidden md:flex"
          >
            <ChevronLeft size={14} />
          </button>
        )}
      </div>

      {/* Search button */}
      <div className={cn("px-2 py-2 border-b border-[#BFDBFE]", collapsed ? "flex justify-center" : "")}>
        <button
          onClick={() => setSearchOpen(true)}
          title="Search (⌘K)"
          className={cn(
            "flex items-center gap-2 rounded-lg text-[12.5px] font-medium transition-colors text-[#64748B] hover:text-[#1E293B] hover:bg-[#DBEAFE]",
            collapsed ? "p-2" : "px-2.5 py-1.5 w-full"
          )}
        >
          <Search size={14} className="shrink-0" />
          {!collapsed && <span className="flex-1 text-left">Search</span>}
          {!collapsed && <kbd className="text-[10px] text-[#CBD5E1] font-mono">⌘K</kbd>}
        </button>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-5">
        {NAV_GROUPS.map((group) => (
          <div key={group.label}>
            {!collapsed && (
              <p className="text-[10px] font-semibold uppercase tracking-widest px-2 mb-1.5 text-[#94A3B8]">
                {group.label}
              </p>
            )}
            {collapsed && <div className="border-t border-[#BFDBFE] mb-2" />}
            <div className="space-y-0.5">
              {group.items
                .filter(({ href }) => canAccessHref(href, userRole))
                .map(({ href, label, icon: Icon }) => {
                  const active = pathname === href || (href !== "/" && pathname.startsWith(href));
                  return (
                    <Link
                      key={href}
                      href={href}
                      title={collapsed ? label : undefined}
                      onClick={onNavClick}
                      className={cn(
                        "flex items-center gap-2.5 rounded-lg text-[12.5px] font-medium transition-all duration-100",
                        collapsed ? "justify-center px-0 py-2.5 mx-0" : "px-2.5 py-2",
                        active
                          ? "bg-[#DBEAFE] text-blue-600"
                          : "text-[#64748B] hover:text-[#1E293B] hover:bg-[#DBEAFE]"
                      )}
                    >
                      <Icon size={15} className={cn("shrink-0", active ? "text-blue-600" : "text-[#64748B]")} />
                      {!collapsed && <span className="truncate">{label}</span>}
                    </Link>
                  );
                })}
            </div>
          </div>
        ))}
      </nav>

      {/* Expand button when collapsed */}
      {collapsed && (
        <button
          onClick={() => setCollapsed(false)}
          className="mx-auto mb-2 p-1.5 rounded-md text-[#94A3B8] hover:text-[#475569] hover:bg-[#DBEAFE] transition-colors hidden md:flex"
        >
          <ChevronRight size={14} />
        </button>
      )}

      {/* User footer */}
      <div className={cn(
        "border-t border-[#BFDBFE] p-3 flex items-center gap-2.5",
        collapsed ? "justify-center flex-col" : ""
      )}>
        <div className="w-7 h-7 rounded-full bg-blue-600 text-white flex items-center justify-center text-[11px] font-bold shrink-0">
          {initials}
        </div>
        {!collapsed && (
          <div className="min-w-0 flex-1">
            <p className="text-[12px] font-semibold text-[#1E293B] truncate">{displayEmail}</p>
            <p className="text-[10px] text-[#94A3B8] truncate">{userRole ?? "Partner"}</p>
          </div>
        )}
        <button
          onClick={signOut}
          title="Sign out"
          className="p-1.5 rounded-md text-[#94A3B8] hover:text-red-600 hover:bg-[#DBEAFE] transition-colors shrink-0"
        >
          <LogOut size={13} />
        </button>
      </div>
    </aside>
  );
}

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <>
      {/* Hamburger — mobile */}
      <button
        onClick={() => setMobileOpen(true)}
        className="md:hidden fixed top-3 left-3 z-40 p-2 rounded-lg bg-white text-[#475569] hover:text-white shadow-lg"
        aria-label="Open menu"
      >
        <Menu size={18} />
      </button>

      {/* Mobile backdrop */}
      {mobileOpen && (
        <div
          className="md:hidden fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Mobile slide-in */}
      <div
        className={cn(
          "md:hidden fixed inset-y-0 left-0 z-50 transition-transform duration-200",
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        )}
      >
        <div className="relative h-full">
          <button
            onClick={() => setMobileOpen(false)}
            className="absolute top-3 right-3 z-10 p-1.5 rounded-md text-[#94A3B8] hover:text-[#475569] hover:bg-[#DBEAFE]"
            aria-label="Close menu"
          >
            <X size={15} />
          </button>
          <SidebarContent
            collapsed={false}
            setCollapsed={() => {}}
            onNavClick={() => setMobileOpen(false)}
          />
        </div>
      </div>

      {/* Desktop sidebar */}
      <div className="hidden md:flex h-screen">
        <SidebarContent collapsed={collapsed} setCollapsed={setCollapsed} />
      </div>
    </>
  );
}
