"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutGrid,
  BookOpen,
  ShoppingCart,
  Package,
  Boxes,
  Shield,
  Users,
  Landmark,
  CalendarCheck,
  FileText,
  FolderOpen,
  CheckSquare,
  BarChart3,
  Globe,
  Sparkles,
  RefreshCw,
  Network,
  Activity,
  BookMarked,
  ClipboardList,
  Banknote,
  ArrowLeft,
  PanelLeftClose,
  PanelLeftOpen,
  Menu,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { CLIENT_SECTIONS, getSectionForPathname, useClientNav } from "@/lib/workspace/ClientNavContext";

const SECTION_ICONS: Record<string, React.ElementType> = {
  overview:        LayoutGrid,
  accounting:      BookOpen,
  sales:           ShoppingCart,
  purchases:       Package,
  bank:            Banknote,
  inventory:       Boxes,
  compliance:      Shield,
  payroll:         Users,
  "fixed-assets":  Landmark,
  "year-end":      CalendarCheck,
  tax:             FileText,
  documents:       FolderOpen,
  tasks:           CheckSquare,
  reports:         BarChart3,
  portal:          Globe,
  "ai-insights":   Sparkles,
  lifecycle:       RefreshCw,
  relationships:   Network,
  health:          Activity,
  knowledge:       BookMarked,
  instructions:    ClipboardList,
};

const STORAGE_KEY = "practicesync_sidebar_collapsed";

function NavItems({
  collapsed,
  onLinkClick,
  pathname,
  clientId,
}: {
  collapsed: boolean;
  onLinkClick?: () => void;
  pathname: string;
  clientId: string;
}) {
  // Identity match on the section segment, not a URL-string prefix check —
  // immune to Next stripping the trailing slash on client-side navigations
  // (hrefs are always slash-terminated; usePathname() after a client
  // transition is not) and to nested sub-routes (e.g. compliance/gst still
  // resolves to "compliance").
  const activeSection = getSectionForPathname(pathname);

  return (
    <nav className="flex-1 overflow-y-auto py-2 px-1.5 space-y-0.5">
      {CLIENT_SECTIONS.map(({ id, label, href }) => {
        const target = href(clientId);
        const active = id === activeSection;
        const Icon = SECTION_ICONS[id] ?? FileText;
        return (
          <Link
            key={id}
            href={target}
            prefetch={false}
            onClick={onLinkClick}
            title={collapsed ? label : undefined}
            className={cn(
              "relative flex items-center gap-2.5 rounded-lg transition-all duration-100",
              collapsed ? "justify-center w-9 h-9 mx-auto" : "px-2 py-2",
              active
                ? "bg-blue-600 text-white"
                : "text-slate-400 hover:text-white hover:bg-white/10"
            )}
          >
            {active && (
              <span className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-5 bg-blue-400 rounded-r" />
            )}
            <Icon size={15} className="shrink-0" />
            {!collapsed && (
              <span className="text-[12.5px] font-medium">{label}</span>
            )}
          </Link>
        );
      })}
    </nav>
  );
}

export function ClientContextPanel() {
  const pathname = usePathname();
  const { clientId } = useClientNav();

  const [collapsed, setCollapsed] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    try {
      return localStorage.getItem(STORAGE_KEY) === "true";
    } catch {
      return false;
    }
  });
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, String(collapsed));
    } catch {
      // localStorage unavailable in some environments
    }
  }, [collapsed]);

  // Close mobile drawer on route change
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  return (
    <>
      {/* ── Desktop sidebar ── */}
      <div
        className={cn(
          "hidden md:flex flex-col h-full shrink-0 bg-[#182350] border-r border-white/10 transition-[width] duration-200 ease-in-out overflow-hidden",
          collapsed ? "w-[52px]" : "w-[200px]"
        )}
      >
        {/* Expanded header: back + label + collapse */}
        {!collapsed && (
          <div className="flex items-center h-12 border-b border-white/10 px-2 gap-1">
            <Link
              href="/clients"
              title="Back to Clients"
              className="flex items-center justify-center w-8 h-8 rounded-lg text-slate-400 hover:text-white hover:bg-white/10 transition-colors shrink-0"
            >
              <ArrowLeft size={15} />
            </Link>
            <span className="flex-1 text-[10px] font-semibold uppercase tracking-widest text-slate-500 truncate px-1">
              Client Workspace
            </span>
            <button
              onClick={() => setCollapsed(true)}
              title="Collapse sidebar"
              className="flex items-center justify-center w-8 h-8 rounded-lg text-slate-400 hover:text-white hover:bg-white/10 transition-colors shrink-0"
            >
              <PanelLeftClose size={15} />
            </button>
          </div>
        )}

        {/* Collapsed header: back button */}
        {collapsed && (
          <div className="flex justify-center border-b border-white/10 py-2">
            <Link
              href="/clients"
              title="Back to Clients"
              className="flex items-center justify-center w-8 h-8 rounded-lg text-slate-400 hover:text-white hover:bg-white/10 transition-colors"
            >
              <ArrowLeft size={15} />
            </Link>
          </div>
        )}

        {/* Expand button — only in collapsed state */}
        {collapsed && (
          <div className="flex justify-center py-1 border-b border-white/10">
            <button
              onClick={() => setCollapsed(false)}
              title="Expand sidebar"
              className="flex items-center justify-center w-8 h-8 rounded-lg text-slate-400 hover:text-white hover:bg-white/10 transition-colors"
            >
              <PanelLeftOpen size={15} />
            </button>
          </div>
        )}

        <NavItems
          collapsed={collapsed}
          pathname={pathname}
          clientId={clientId}
        />
      </div>

      {/* ── Mobile: hamburger trigger (always visible on small screens) ── */}
      <button
        aria-label="Open navigation"
        onClick={() => setMobileOpen(true)}
        className="md:hidden fixed top-2.5 left-2.5 z-50 flex items-center justify-center w-8 h-8 rounded-lg bg-[#182350] text-slate-300 shadow-md"
      >
        <Menu size={16} />
      </button>

      {/* ── Mobile drawer ── */}
      {mobileOpen && (
        <>
          {/* Backdrop */}
          <div
            className="md:hidden fixed inset-0 bg-black/50 z-40"
            onClick={() => setMobileOpen(false)}
          />

          {/* Drawer panel */}
          <div className="md:hidden fixed left-0 top-0 h-full z-50 flex flex-col w-[220px] bg-[#182350] shadow-2xl">
            <div className="flex items-center justify-between h-12 border-b border-white/10 px-3 shrink-0">
              <Link
                href="/clients"
                className="flex items-center gap-2 text-slate-300 hover:text-white transition-colors"
                onClick={() => setMobileOpen(false)}
              >
                <ArrowLeft size={15} />
                <span className="text-[10px] font-semibold uppercase tracking-widest">
                  Client Workspace
                </span>
              </Link>
              <button
                onClick={() => setMobileOpen(false)}
                className="flex items-center justify-center w-7 h-7 rounded-lg text-slate-400 hover:text-white hover:bg-white/10 transition-colors"
              >
                <X size={15} />
              </button>
            </div>

            <NavItems
              collapsed={false}
              onLinkClick={() => setMobileOpen(false)}
              pathname={pathname}
              clientId={clientId}
            />
          </div>
        </>
      )}
    </>
  );
}
