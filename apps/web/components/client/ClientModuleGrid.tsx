"use client";

import Link from "next/link";
import {
  LayoutGrid, BookOpen, ShoppingCart, Package, Boxes, Shield, Users, Landmark,
  CalendarCheck, FileText, FolderOpen, CheckSquare, BarChart3, Globe, Sparkles,
  RefreshCw, Network, Activity, BookMarked, ClipboardList, Banknote,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { CLIENT_SECTIONS } from "@/lib/workspace/ClientNavContext";

/**
 * The client workspace's front door AND its switcher — one grid, used twice.
 *
 * WHAT IT REPLACED. `components/shell/ClientSections.tsx`: a 272px column of
 * twenty-one identical text links, present on every screen of every client.
 * `/clients/{id}` was not even a page — it was a spinner and a
 * `router.replace` to `/overview/`, so there was no front door to arrive AT.
 *
 * ⚠️ IT CARRIED A LIVE FIGURE PER MODULE FOR ONE DAY, AND THE OWNER REMOVED
 * THEM ON SIGHT (25-09). The figures were real and the fetch was correct; what
 * was wrong was what the CA actually experienced. `GET /api/hub` takes about
 * ten seconds on a cold Render instance, and the grid was built to render from
 * `CLIENT_SECTIONS` first so navigation never waited on it — which was the
 * right instinct and produced the wrong result: the door opened as twenty-one
 * plain cards in four columns, and ten seconds later **re-sorted itself, split
 * into two bands and re-flowed every card to a new position**. A CA reaching
 * for Bank found Payroll under the pointer.
 *
 * THE LESSON IS NOT "PROGRESSIVE LOADING IS BAD" — it is that progressive
 * loading must not move anything already on screen. Figures could come back
 * one day as a fixed-height slot inside a card that never re-orders. What
 * cannot come back is a layout that decides its own shape from a payload.
 *
 * So there is no fetch here at all now, and that is worth more than the
 * numbers were: the front door is instant, costs no Singapore-to-Mumbai round
 * trip, and looks identical on its first frame and its last. The same figures
 * are still one click away on Overview, where the hub has always rendered
 * them and where nothing re-orders under the reader.
 *
 * ONE VOCABULARY. `CLIENT_SECTIONS` already is the list of what a client
 * workspace holds, in the order it holds it, and this renders exactly it.
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

export type GridVariant = "page" | "overlay";

export function ClientModuleGrid({
  clientId,
  variant = "page",
  activeSection,
  onNavigate,
}: {
  clientId: string;
  variant?: GridVariant;
  activeSection?: string | null;
  onNavigate?: () => void;
}) {
  const compact = variant === "overlay";

  return (
    <div
      className={cn(
        "grid gap-2.5",
        compact ? "p-4" : "px-4 py-6 md:px-8 md:py-8",
        compact
          ? "grid-cols-2 sm:grid-cols-3 lg:grid-cols-4"
          : "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
      )}
    >
      {CLIENT_SECTIONS.map((section) => {
        const Icon = SECTION_ICONS[section.id] ?? FileText;
        const active = section.id === activeSection;
        return (
          <Link
            key={section.id}
            href={section.href(clientId)}
            prefetch={false}
            onClick={onNavigate}
            className={cn(
              "module-card group flex items-center gap-2.5 rounded-xl border bg-white px-3.5 py-3 min-w-0",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-brand",
              active ? "border-brand ring-1 ring-brand" : "border-ps-border hover:border-brand"
            )}
          >
            <Icon
              size={15}
              className={cn(
                "shrink-0",
                active ? "text-brand" : "text-ps-hint group-hover:text-brand"
              )}
            />
            <span className="text-sm font-semibold text-ps-ink truncate">{section.label}</span>
          </Link>
        );
      })}
    </div>
  );
}
