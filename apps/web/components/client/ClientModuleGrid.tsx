"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  LayoutGrid, BookOpen, ShoppingCart, Package, Boxes, Shield, Users, Landmark,
  CalendarCheck, FileText, FolderOpen, CheckSquare, BarChart3, Globe, Sparkles,
  RefreshCw, Network, Activity, BookMarked, ClipboardList, Banknote,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import type { HubTile } from "@/lib/api";
import { arrayOrEmpty } from "@/lib/api/shape";
import { NO_FIGURE, formatPaise } from "@/lib/money/format";
import { CLIENT_SECTIONS } from "@/lib/workspace/ClientNavContext";

/**
 * The client workspace's front door AND its switcher — one grid, used twice.
 *
 * WHAT IT REPLACED. `components/shell/ClientSections.tsx`: a 272px column of
 * twenty-one identical text links, present on every screen of every client,
 * carrying no information beyond its own labels. A CA arriving at a client saw
 * a list of places rather than a picture of the work, and reaching Bank from
 * Sales meant scanning twenty-one rows. `/clients/{id}` was not even a page —
 * it was a spinner and a `router.replace` to `/overview/`, so there was no
 * front door to arrive AT.
 *
 * ── THE VOCABULARY IS `CLIENT_SECTIONS` AND THE FIGURES ARE THE SERVER'S ────
 *
 * `CLIENT_SECTIONS` already is the one list of what a client workspace holds,
 * and this renders exactly it. The numbers come from `GET /api/hub`, which has
 * answered at client scope since D1 and was rendered at line 133 of the
 * overview page, below the fold, where nobody scrolled to it.
 *
 * ⚠️ WHICH SECTION A TILE BELONGS TO IS READ OFF THE TILE'S OWN `href`, never
 * from a map kept here. `domain/hub/tiles.py` derives that href from its own
 * `client_section`, so reading the segment back out means the SERVER decides
 * the join and the browser cannot disagree with it — the Schedule III caption
 * lesson. Two consequences fall out rather than being coded:
 *
 *   · GST and TDS both answer for `compliance`, so that card carries TWO
 *     figures. Nothing here says "compliance is special".
 *   · The twelve sections that have a figure and the nine that do not are the
 *     server's split, not an editorial one — and they come out as the same
 *     twelve and nine a reader would draw by hand.
 *
 * ── NAVIGATION DOES NOT DEPEND ON THE FIGURES ───────────────────────────────
 *
 * The grid renders from `CLIENT_SECTIONS` on the first frame and the figures
 * arrive over it. A hub that is slow, refused or down costs a CA the numbers
 * and never the way in — which the list it replaces got right by accident and
 * a naive rewrite would lose. `lib/api` aborts at 45s and never retries, and
 * Render's free tier cold-starts, so this is the ordinary case rather than the
 * unlucky one.
 *
 * ── A NIL MEANS ONE OF THREE THINGS AND THE SCREEN SAYS WHICH ───────────────
 *
 * `Hub.tsx` states the rule and it is unchanged here: signal 0 with
 * `answerable` is the FINISHED state and is drawn calm; signal null with
 * `answerable` false is a reason, rendered in place of a figure; signal null
 * with `answerable` true is one tile that could not be read. A section with no
 * tile at all is a fourth thing — nobody asks a question about it — and it
 * belongs in the quiet band rather than showing a zero that claims there is
 * nothing to do.
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

/** The section a tile lands on, taken from the href the SERVER built. */
export function sectionOfHref(href: string | null): string | null {
  if (!href) return null;
  const m = href.match(/^\/clients\/[^/]+\/([^/]+)\//);
  return m ? m[1] : null;
}

function figureOf(tile: HubTile): string {
  if (tile.signal === null) return NO_FIGURE;
  // `formatPaise` already carries the ₹ — a template that adds one renders
  // "₹₹4,23,517", which is exactly what the hub's first draft did.
  return tile.unit === "paise" ? formatPaise(tile.signal) : String(tile.signal);
}

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
  const [tiles, setTiles] = useState<HubTile[]>([]);
  const [figuresFailed, setFiguresFailed] = useState(false);

  useEffect(() => {
    if (!clientId || clientId === "_placeholder") return;
    let live = true;
    setFiguresFailed(false);
    api.hub
      .get(clientId)
      .then((res) => {
        if (!live) return;
        // The GST workspace router answers refusals as HTTP 200, so the
        // envelope is checked before the payload — and the payload before it
        // is treated as a list (lib/api/shape.ts).
        if (!res?.success) {
          setFiguresFailed(true);
          return;
        }
        setTiles(arrayOrEmpty<HubTile>(res.data?.tiles));
      })
      .catch(() => {
        if (live) setFiguresFailed(true);
      });
    return () => { live = false; };
  }, [clientId]);

  const bySection = useMemo(() => {
    const m = new Map<string, HubTile[]>();
    for (const t of tiles) {
      const s = sectionOfHref(t.href);
      if (!s) continue;
      const list = m.get(s);
      if (list) list.push(t);
      else m.set(s, [t]);
    }
    return m;
  }, [tiles]);

  // The WORK band's ORDER is the server's — `domain/hub/tiles.TILES` calls it
  // "the reading order of a CA's day" — taken as each section's first
  // appearance. Whether a section is work at all is likewise the server's: it
  // is work if somebody asks a question about it.
  const workOrder = useMemo(() => {
    const seen: string[] = [];
    for (const t of tiles) {
      const s = sectionOfHref(t.href);
      if (s && !seen.includes(s)) seen.push(s);
    }
    return seen;
  }, [tiles]);

  const work = workOrder
    .map((id) => CLIENT_SECTIONS.find((s) => s.id === id))
    .filter((s): s is (typeof CLIENT_SECTIONS)[number] => Boolean(s));
  const workIds = new Set(work.map((s) => s.id));
  const rest = CLIENT_SECTIONS.filter((s) => !workIds.has(s.id));

  // Before the figures land — and for ever, if they never do — every section
  // is in one band and every one of them is a link.
  const unsplit = work.length === 0;

  const compact = variant === "overlay";

  return (
    <div className={cn(compact ? "p-4" : "px-4 py-6 md:px-8 md:py-8")}>
      {!unsplit && <BandLabel compact={compact}>Work</BandLabel>}

      <div
        className={cn(
          "grid gap-2.5",
          compact
            ? "grid-cols-2 sm:grid-cols-3 lg:grid-cols-4"
            : "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
        )}
      >
        {(unsplit ? CLIENT_SECTIONS : work).map((section) => (
          <ModuleCard
            key={section.id}
            href={section.href(clientId)}
            label={section.label}
            icon={SECTION_ICONS[section.id] ?? FileText}
            tiles={bySection.get(section.id) ?? []}
            active={section.id === activeSection}
            compact={compact}
            onNavigate={onNavigate}
          />
        ))}
      </div>

      {!unsplit && rest.length > 0 && (
        <>
          <BandLabel compact={compact}>The client</BandLabel>
          <div className="flex flex-wrap gap-2">
            {rest.map((section) => {
              const Icon = SECTION_ICONS[section.id] ?? FileText;
              return (
                <Link
                  key={section.id}
                  href={section.href(clientId)}
                  prefetch={false}
                  onClick={onNavigate}
                  className={cn(
                    "flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
                    section.id === activeSection
                      ? "border-brand bg-brand text-white"
                      : "border-ps-border bg-white text-ps-label hover:border-brand hover:text-brand"
                  )}
                >
                  <Icon size={13} className="shrink-0" />
                  {section.label}
                </Link>
              );
            })}
          </div>
        </>
      )}

      {figuresFailed && (
        <p className="mt-5 text-2xs text-ps-hint">
          The figures could not be loaded just now. Every module is still open below.
        </p>
      )}
    </div>
  );
}

function BandLabel({ compact, children }: { compact: boolean; children: React.ReactNode }) {
  return (
    <h2
      className={cn(
        "text-3xs font-semibold uppercase tracking-widest text-ps-hint",
        compact ? "mb-2 [&:not(:first-child)]:mt-5" : "mb-3 [&:not(:first-child)]:mt-8"
      )}
    >
      {children}
    </h2>
  );
}

function ModuleCard({
  href, label, icon: Icon, tiles, active, compact, onNavigate,
}: {
  href: string;
  label: string;
  icon: React.ElementType;
  tiles: HubTile[];
  active?: boolean;
  compact: boolean;
  onNavigate?: () => void;
}) {
  return (
    <Link
      href={href}
      prefetch={false}
      onClick={onNavigate}
      className={cn(
        "module-card group flex flex-col rounded-xl border bg-white p-3.5 min-w-0",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-brand",
        active ? "border-brand ring-1 ring-brand" : "border-ps-border hover:border-brand"
      )}
    >
      <div className="flex items-center gap-2 min-w-0">
        <Icon size={14} className={cn("shrink-0", active ? "text-brand" : "text-ps-hint group-hover:text-brand")} />
        <span className="text-sm font-semibold text-ps-ink truncate">{label}</span>
      </div>

      {tiles.length > 0 && (
        <div className={cn("mt-2.5 grid gap-3", tiles.length > 1 ? "grid-cols-2" : "grid-cols-1")}>
          {tiles.map((t) => (
            <Figure key={t.id} tile={t} compact={compact} />
          ))}
        </div>
      )}
    </Link>
  );
}

function Figure({ tile, compact }: { tile: HubTile; compact: boolean }) {
  const nothingToDo = tile.answerable && tile.signal === 0;
  const unreadable = tile.answerable && tile.signal === null;

  return (
    <div className="min-w-0">
      <div
        className={cn(
          "font-semibold tabular-nums truncate",
          compact ? "text-lg" : "text-2xl",
          nothingToDo ? "text-state-ready" : "text-ps-ink",
          !tile.answerable || unreadable ? "text-ps-hint" : null
        )}
      >
        {tile.answerable ? figureOf(tile) : NO_FIGURE}
      </div>
      <p className="mt-0.5 text-3xs leading-snug text-ps-label">{tile.question}</p>
      {!tile.answerable && tile.no_signal_because && (
        <p className="mt-1 text-3xs leading-snug text-ps-hint">{tile.no_signal_because}</p>
      )}
      {unreadable && (
        <p className="mt-1 text-3xs leading-snug text-state-attention">
          This figure could not be read just now.
        </p>
      )}
    </div>
  );
}
