"use client";

import { useEffect, useState, useCallback } from "react";
import {
  BookOpen, Shield, Users, FileText, FolderOpen,
  Briefcase, Sparkles, Globe, UserCheck, Pin, RefreshCw,
  ChevronDown,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  getClientTimeline,
  type TimelineEvent, type EventCategory,
} from "@/lib/services/timeline";
import { getSupabaseClient } from "@/lib/supabase/client";
import { TimelineSkeleton } from "@/components/ui/skeleton";

const CATEGORY_ICONS: Record<EventCategory, React.ElementType> = {
  accounting:  BookOpen,
  compliance:  Shield,
  payroll:     Users,
  tax:         FileText,
  document:    FolderOpen,
  work:        Briefcase,
  ai:          Sparkles,
  portal:      Globe,
  team:        UserCheck,
};

const SEVERITY_STYLES = {
  info:     "border-l-ps-border bg-ps-bg",
  success:  "border-l-state-ready-border bg-state-ready-surface/50",
  warning:  "border-l-state-attention-border bg-state-attention-surface/50",
  critical: "border-l-state-problem-border bg-state-problem-surface/50",
};

const SEVERITY_DOT = {
  info:     "bg-ps-border-strong",
  success:  "bg-emerald-400",
  warning:  "bg-amber-400",
  critical: "bg-red-400",
};

const CATEGORY_OPTIONS: { value: EventCategory | "all"; label: string }[] = [
  { value: "all",        label: "All" },
  { value: "accounting", label: "Accounting" },
  { value: "compliance", label: "Compliance" },
  { value: "document",   label: "Documents" },
  { value: "work",       label: "Work" },
  { value: "portal",     label: "Portal" },
  { value: "ai",         label: "AI" },
];

const SEVERITY_OPTIONS: { value: string; label: string }[] = [
  { value: "all",      label: "All" },
  { value: "critical", label: "Critical" },
  { value: "warning",  label: "Warnings" },
  { value: "success",  label: "Success" },
  { value: "info",     label: "Info" },
];

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

const PAGE_SIZE = 20;

interface ClientTimelineProps {
  clientId: string;
  financialYear: string;
  limit?: number;
}

export function ClientTimeline({ clientId, financialYear }: ClientTimelineProps) {
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState("");
  const [catFilter, setCatFilter] = useState<EventCategory | "all">("all");
  const [sevFilter, setSevFilter] = useState("all");
  const [page, setPage] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [pinning, setPinning] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async (silent = false, resetPage = true) => {
    if (!silent) setLoading(true); else setRefreshing(true);
    const offset = resetPage ? 0 : page * PAGE_SIZE;
    if (resetPage) setPage(0);

    try {
      const result = await getClientTimeline({
        clientId,
        financialYear,
        category: catFilter !== "all" ? catFilter : undefined,
        limit: PAGE_SIZE + 1,
        offset,
      });

      if (!result.success) {
        setLoadError(result.error ?? "Couldn't load timeline events.");
        setEvents([]);
        setHasMore(false);
      } else {
        const data = result.data;
        setLoadError(null);
        setHasMore(data.length > PAGE_SIZE);
        setEvents(data.slice(0, PAGE_SIZE));
      }
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Couldn't load timeline events.");
      setEvents([]);
      setHasMore(false);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [clientId, financialYear, catFilter, page]);

  useEffect(() => { load(false, true); }, [clientId, financialYear, catFilter, load]);

  async function togglePin(event: TimelineEvent) {
    setPinning(event.id);
    try {
      const supabase = getSupabaseClient();
      await supabase
        .from("client_timeline_events")
        .update({ is_pinned: !event.is_pinned })
        .eq("id", event.id);
      setEvents((prev) =>
        prev.map((e) => e.id === event.id ? { ...e, is_pinned: !e.is_pinned } : e)
      );
    } finally {
      setPinning(null);
    }
  }

  // Client-side search + severity filter (applied to loaded page)
  const filtered = events.filter((e) => {
    if (sevFilter !== "all" && e.severity !== sevFilter) return false;
    if (search.trim()) {
      const q = search.toLowerCase();
      return (
        e.title.toLowerCase().includes(q) ||
        (e.description ?? "").toLowerCase().includes(q)
      );
    }
    return true;
  });

  const pinned = filtered.filter((e) => e.is_pinned);
  const feed = filtered.filter((e) => !e.is_pinned);

  if (loading) {
    return (
      <div className="space-y-2">
        <TimelineSkeleton rows={4} />
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {/* Toolbar */}
      <div className="flex items-center gap-2 flex-wrap">
        {/* Search */}
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search events…"
          className="flex-1 min-w-[120px] bg-ps-bg border border-ps-border rounded-lg px-2.5 py-1 text-2xs text-ps-label placeholder:text-ps-disabled outline-none focus:border-blue-300"
        />
        {/* Category filter */}
        <div className="relative">
          <select
            value={catFilter}
            onChange={(e) => setCatFilter(e.target.value as EventCategory | "all")}
            className="appearance-none bg-ps-bg border border-ps-border rounded-lg pl-2.5 pr-6 py-1 text-2xs text-ps-label outline-none focus:border-blue-300 cursor-pointer"
          >
            {CATEGORY_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <ChevronDown size={9} className="absolute right-1.5 top-1/2 -translate-y-1/2 text-ps-hint pointer-events-none" />
        </div>
        {/* Severity filter */}
        <div className="relative">
          <select
            value={sevFilter}
            onChange={(e) => setSevFilter(e.target.value)}
            className="appearance-none bg-ps-bg border border-ps-border rounded-lg pl-2.5 pr-6 py-1 text-2xs text-ps-label outline-none focus:border-blue-300 cursor-pointer"
          >
            {SEVERITY_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <ChevronDown size={9} className="absolute right-1.5 top-1/2 -translate-y-1/2 text-ps-hint pointer-events-none" />
        </div>
        {/* Refresh */}
        <button
          onClick={() => load(true)}
          className="text-ps-hint hover:text-ps-label transition-colors p-1"
          title="Refresh"
        >
          <RefreshCw size={11} className={cn(refreshing && "animate-spin")} />
        </button>
      </div>

      {loadError && (
        <div className="flex flex-col items-center justify-center py-10 text-center space-y-2">
          <div className="w-10 h-10 rounded-full bg-state-problem-surface flex items-center justify-center">
            <Shield size={18} className="text-red-400" />
          </div>
          <p className="text-sm text-red-600 font-medium">{loadError}</p>
          <button
            onClick={() => load(false, true)}
            className="text-2xs text-ps-label px-3 py-1 rounded border border-ps-border hover:border-blue-300"
          >
            Retry
          </button>
        </div>
      )}

      {!loadError && filtered.length === 0 && (
        <div className="flex flex-col items-center justify-center py-10 text-center space-y-2">
          <div className="w-10 h-10 rounded-full bg-ps-muted flex items-center justify-center">
            <Shield size={18} className="text-ps-hint" />
          </div>
          <p className="text-sm text-ps-hint">
            {search || catFilter !== "all" || sevFilter !== "all"
              ? "No events match the current filters"
              : `No activity yet for FY ${financialYear}`}
          </p>
        </div>
      )}

      {/* Pinned events */}
      {pinned.length > 0 && (
        <div className="mb-1 space-y-1">
          <p className="text-3xs font-semibold uppercase tracking-widest text-ps-hint px-1 flex items-center gap-1">
            <Pin size={9} /> Pinned
          </p>
          {pinned.map((e) => (
            <TimelineEventRow key={e.id} event={e} onPin={togglePin} pinning={pinning === e.id} />
          ))}
        </div>
      )}

      {/* Feed */}
      {feed.length > 0 && (
        <div className="space-y-1">
          {pinned.length > 0 && (
            <p className="text-3xs font-semibold uppercase tracking-widest text-ps-hint px-1">Activity</p>
          )}
          {feed.map((e) => (
            <TimelineEventRow key={e.id} event={e} onPin={togglePin} pinning={pinning === e.id} />
          ))}
        </div>
      )}

      {/* Pagination */}
      {(hasMore || page > 0) && (
        <div className="flex items-center gap-2 justify-center pt-1">
          {page > 0 && (
            <button
              onClick={() => { setPage((p) => p - 1); load(false, false); }}
              className="text-2xs text-ps-hint hover:text-ps-label px-3 py-1 rounded border border-ps-border hover:border-blue-300"
            >
              ← Previous
            </button>
          )}
          {hasMore && (
            <button
              onClick={() => { setPage((p) => p + 1); load(false, false); }}
              className="text-2xs text-ps-hint hover:text-ps-label px-3 py-1 rounded border border-ps-border hover:border-blue-300"
            >
              Load more →
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function TimelineEventRow({
  event,
  onPin,
  pinning,
}: {
  event: TimelineEvent;
  onPin: (e: TimelineEvent) => void;
  pinning: boolean;
}) {
  const Icon = CATEGORY_ICONS[event.category as EventCategory] ?? FileText;
  const [hover, setHover] = useState(false);

  return (
    <div
      className={cn(
        "group flex items-start gap-3 px-3 py-2.5 rounded-lg border-l-2 transition-colors hover:opacity-80",
        SEVERITY_STYLES[event.severity ?? "info"]
      )}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <div className="flex items-center gap-2 shrink-0 pt-0.5">
        <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", SEVERITY_DOT[event.severity ?? "info"])} />
        <Icon size={13} className="text-ps-hint shrink-0" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium text-ps-ink leading-snug">{event.title}</p>
        {event.description && (
          <p className="text-2xs text-ps-hint mt-0.5 leading-snug">{event.description}</p>
        )}
      </div>
      <div className="shrink-0 text-right flex flex-col items-end gap-0.5">
        <p className="text-3xs text-ps-hint whitespace-nowrap">{timeAgo(event.created_at)}</p>
        {event.action_label && event.action_url && (
          <a
            href={event.action_url}
            className="text-3xs text-blue-600 hover:text-blue-800 underline underline-offset-2"
          >
            {event.action_label}
          </a>
        )}
        {/* Pin toggle — visible on hover */}
        {(hover || event.is_pinned) && (
          <button
            onClick={() => onPin(event)}
            disabled={pinning}
            className={cn(
              "mt-0.5 transition-colors",
              event.is_pinned ? "text-amber-500" : "text-ps-disabled hover:text-ps-label"
            )}
            title={event.is_pinned ? "Unpin" : "Pin to top"}
          >
            <Pin size={10} />
          </button>
        )}
      </div>
    </div>
  );
}
