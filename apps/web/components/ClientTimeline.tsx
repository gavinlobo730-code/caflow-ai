"use client";

import { useEffect, useState, useCallback } from "react";
import {
  BookOpen, Shield, Users, FileText, FolderOpen,
  Briefcase, Sparkles, Globe, UserCheck, Pin, RefreshCw,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { getClientTimeline, type TimelineEvent, type EventCategory } from "@/lib/services/timeline";

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
  info:     "border-l-white/10 bg-white/[0.02]",
  success:  "border-l-emerald-500/40 bg-emerald-500/[0.04]",
  warning:  "border-l-amber-500/40 bg-amber-500/[0.04]",
  critical: "border-l-red-500/40 bg-red-500/[0.04]",
};

const SEVERITY_DOT = {
  info:     "bg-white/20",
  success:  "bg-emerald-400",
  warning:  "bg-amber-400",
  critical: "bg-red-400",
};

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

interface ClientTimelineProps {
  clientId: string;
  financialYear: string;
  limit?: number;
}

export function ClientTimeline({ clientId, financialYear, limit = 25 }: ClientTimelineProps) {
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true); else setRefreshing(true);
    const result = await getClientTimeline({ clientId, financialYear, limit });
    setEvents(result.data);
    setLoading(false);
    setRefreshing(false);
  }, [clientId, financialYear, limit]);

  useEffect(() => { load(); }, [load]);

  const pinned = events.filter((e) => e.is_pinned);
  const feed = events.filter((e) => !e.is_pinned);

  if (loading) {
    return (
      <div className="space-y-2">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-14 rounded-lg bg-white/[0.03] animate-pulse" />
        ))}
      </div>
    );
  }

  if (events.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center space-y-2">
        <div className="w-10 h-10 rounded-full bg-white/5 flex items-center justify-center">
          <Shield size={18} className="text-white/20" />
        </div>
        <p className="text-sm text-white/30">No activity yet for FY {financialYear}</p>
        <p className="text-xs text-white/15">Actions you take on this client will appear here.</p>
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {/* Pinned events */}
      {pinned.length > 0 && (
        <div className="mb-3 space-y-1">
          <p className="text-[10px] font-semibold uppercase tracking-widest text-white/25 px-1 flex items-center gap-1">
            <Pin size={9} /> Pinned
          </p>
          {pinned.map((e) => <TimelineEventRow key={e.id} event={e} />)}
        </div>
      )}

      {/* Header row */}
      <div className="flex items-center justify-between px-1 mb-2">
        <p className="text-[10px] font-semibold uppercase tracking-widest text-white/25">Activity</p>
        <button
          onClick={() => load(true)}
          className="text-white/20 hover:text-white/50 transition-colors"
          title="Refresh"
        >
          <RefreshCw size={11} className={cn(refreshing && "animate-spin")} />
        </button>
      </div>

      {feed.map((e) => <TimelineEventRow key={e.id} event={e} />)}
    </div>
  );
}

function TimelineEventRow({ event }: { event: TimelineEvent }) {
  const Icon = CATEGORY_ICONS[event.category as EventCategory] ?? FileText;

  return (
    <div
      className={cn(
        "flex items-start gap-3 px-3 py-2.5 rounded-lg border-l-2 transition-colors hover:bg-white/[0.03]",
        SEVERITY_STYLES[event.severity ?? "info"]
      )}
    >
      <div className="flex items-center gap-2 shrink-0 pt-0.5">
        <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", SEVERITY_DOT[event.severity ?? "info"])} />
        <Icon size={13} className="text-white/30 shrink-0" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-[12px] font-medium text-white/80 leading-snug">{event.title}</p>
        {event.description && (
          <p className="text-[11px] text-white/35 mt-0.5 leading-snug">{event.description}</p>
        )}
      </div>
      <div className="shrink-0 text-right">
        <p className="text-[10px] text-white/20 whitespace-nowrap">{timeAgo(event.created_at)}</p>
        {event.action_label && event.action_url && (
          <a
            href={event.action_url}
            className="text-[10px] text-violet-400 hover:text-violet-300 underline underline-offset-2 mt-0.5 block"
          >
            {event.action_label}
          </a>
        )}
      </div>
    </div>
  );
}
