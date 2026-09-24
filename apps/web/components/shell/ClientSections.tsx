"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutGrid, BookOpen, ShoppingCart, Package, Boxes, Shield, Users, Landmark,
  CalendarCheck, FileText, FolderOpen, CheckSquare, BarChart3, Globe, Sparkles,
  RefreshCw, Network, Activity, BookMarked, ClipboardList, Banknote, ArrowLeft,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { CLIENT_SECTIONS, getSectionForPathname, useClientNav } from "@/lib/workspace/ClientNavContext";

/**
 * The client workspace's 21 sections, as the shell's PANEL.
 *
 * It was `components/ClientContextPanel.tsx`, which was a whole second shell:
 * its own 200px navy box, its own collapse with its own storage key, its own
 * mobile trigger and drawer, its own close-on-navigate effect and its own back
 * link — all of which `NavShell` now owns once, for both scopes. What is left
 * here is the list, which is the only part that was ever this file's business.
 *
 * WHITE, WHERE IT WAS NAVY, and that is the point rather than a side effect.
 * The two halves of the product looked like two products: a navy rail and a
 * white panel at firm level, one navy panel inside a client. The rail is the
 * constant now and the panel is the thing that changes CONTENT, so it keeps
 * one appearance.
 *
 * ⚠️ THE ACTIVE TEST IS AN IDENTITY MATCH ON THE SECTION SEGMENT, not a URL
 * prefix — immune to Next stripping the trailing slash on a client-side
 * navigation (hrefs here are always slash-terminated; `usePathname()` after a
 * transition is not) and to nested sub-routes, so `compliance/gst` still
 * resolves to "compliance". That was already right and is kept exactly.
 */
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

export function ClientSections() {
  const pathname = usePathname();
  const { clientId } = useClientNav();
  const activeSection = getSectionForPathname(pathname);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-3 h-12 border-b border-gray-200 shrink-0">
        <Link
          href="/clients"
          title="Back to Clients"
          className="flex items-center justify-center w-7 h-7 rounded-lg text-ps-hint hover:text-ps-ink hover:bg-ps-bg transition-colors shrink-0"
        >
          <ArrowLeft size={14} />
        </Link>
        <span className="text-3xs font-semibold uppercase tracking-widest text-ps-hint truncate">
          Client Workspace
        </span>
      </div>

      <nav className="flex-1 overflow-y-auto py-2 px-2 space-y-0.5">
        {CLIENT_SECTIONS.map(({ id, label, href }) => {
          const active = id === activeSection;
          const Icon = SECTION_ICONS[id] ?? FileText;
          return (
            <Link
              key={id}
              href={href(clientId)}
              prefetch={false}
              className={cn(
                "flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-colors",
                active
                  ? "bg-brand text-white"
                  : "text-gray-600 hover:text-brand hover:bg-ps-bg"
              )}
            >
              <Icon size={13} className="shrink-0" />
              <span className="truncate">{label}</span>
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
