"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard, Users, CheckSquare, UserCheck,
  BookOpen, FileText, Receipt, Calculator, Building2,
  Calendar, BarChart3, Settings,
  ChevronLeft, ChevronRight, Landmark, Shield,
  FileStack, ShieldAlert, Sparkles, Bell, LogOut, ExternalLink,
  Menu, X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth/AuthContext";

const NAV_GROUPS = [
  {
    label: "Operations",
    items: [
      { href: "/", label: "Dashboard", icon: LayoutDashboard },
      { href: "/clients", label: "Clients", icon: Users },
      { href: "/clients/portal", label: "Client Portal", icon: ExternalLink },
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
      { href: "/reports", label: "Reports", icon: BarChart3 },
      { href: "/documents", label: "Doc Intelligence", icon: FileStack },
      { href: "/risks", label: "Risk Intelligence", icon: ShieldAlert },
      { href: "/ai-assistant", label: "AI Assistant", icon: Sparkles },
      { href: "/notifications", label: "Notifications", icon: Bell },
      { href: "/settings", label: "Settings", icon: Settings },
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
  const { user, signOut } = useAuth();

  return (
    <aside
      className={cn(
        "flex flex-col bg-white border-r border-gray-100 transition-all duration-200 shrink-0 h-full",
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
            "p-1 rounded-md hover:bg-gray-100 text-gray-400 transition-colors hidden md:flex",
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
                    onClick={onNavClick}
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
        collapsed ? "justify-center flex-col" : ""
      )}>
        <div className="w-7 h-7 rounded-full bg-blue-600 text-white flex items-center justify-center text-xs font-semibold shrink-0">
          {user?.email?.slice(0, 2).toUpperCase() ?? "CA"}
        </div>
        {!collapsed && (
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold text-gray-900 truncate">
              {user?.email ?? "User"}
            </p>
            <p className="text-[11px] text-gray-400 truncate">Partner</p>
          </div>
        )}
        <button
          onClick={signOut}
          title="Sign out"
          className="p-1 rounded-md hover:bg-gray-100 text-gray-400 hover:text-red-500 transition-colors shrink-0"
        >
          <LogOut size={14} />
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
      {/* Hamburger button — mobile only */}
      <button
        onClick={() => setMobileOpen(true)}
        className="md:hidden fixed top-3 left-3 z-40 p-2 rounded-lg bg-white border border-gray-200 shadow-sm text-gray-600 hover:bg-gray-50"
        aria-label="Open menu"
      >
        <Menu size={18} />
      </button>

      {/* Mobile overlay backdrop */}
      {mobileOpen && (
        <div
          className="md:hidden fixed inset-0 z-40 bg-black/40"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Mobile slide-in sidebar */}
      <div
        className={cn(
          "md:hidden fixed inset-y-0 left-0 z-50 transition-transform duration-200",
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        )}
      >
        <div className="relative h-full">
          <button
            onClick={() => setMobileOpen(false)}
            className="absolute top-3 right-3 z-10 p-1 rounded-md hover:bg-gray-100 text-gray-400"
            aria-label="Close menu"
          >
            <X size={16} />
          </button>
          <SidebarContent
            collapsed={false}
            setCollapsed={() => {}}
            onNavClick={() => setMobileOpen(false)}
          />
        </div>
      </div>

      {/* Desktop sidebar — hidden on mobile */}
      <div className="hidden md:flex h-screen">
        <SidebarContent
          collapsed={collapsed}
          setCollapsed={setCollapsed}
        />
      </div>
    </>
  );
}
