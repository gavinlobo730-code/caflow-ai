"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Bell, CheckCheck, Archive, AlertCircle, Loader2,
  ChevronDown, Clock, CheckCircle2, AlertTriangle, Info,
  ExternalLink, X, Filter,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { getSupabaseClient } from "@/lib/supabase/client";
import type { Notification, InsightSeverity } from "@/lib/types";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<{ success: boolean; data: T; error: string | null }> {
  const { data: { session } } = await getSupabaseClient().auth.getSession();
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {}),
      ...(init?.headers ?? {}),
    },
  });
  return res.json();
}

const SEVERITY_ICONS: Record<InsightSeverity, React.ReactNode> = {
  critical: <AlertTriangle size={14} className="text-red-500" />,
  high: <AlertTriangle size={14} className="text-orange-500" />,
  medium: <Clock size={14} className="text-amber-500" />,
  low: <Info size={14} className="text-blue-500" />,
  info: <Info size={14} className="text-gray-400" />,
};

const SEVERITY_COLORS: Record<InsightSeverity, string> = {
  critical: "border-l-red-500",
  high: "border-l-orange-400",
  medium: "border-l-amber-400",
  low: "border-l-blue-400",
  info: "border-l-gray-300",
};

type FilterTab = "all" | "unread" | "archived";
type TypeFilter = "all" | string;

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

export default function NotificationsPage() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<FilterTab>("all");
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [markingAll, setMarkingAll] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (tab === "unread") params.set("unread_only", "true");
      if (tab === "archived") params.set("archived", "true");
      if (typeFilter !== "all") params.set("type", typeFilter);
      params.set("limit", "100");
      const resp = await apiFetch<{
        notifications: Notification[];
        unread_count: number;
        total: number;
      }>(`/api/notifications?${params}`);
      if (!resp.success) throw new Error(resp.error ?? "Failed to load");
      setNotifications(resp.data.notifications);
      setUnreadCount(resp.data.unread_count);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load notifications");
    } finally {
      setLoading(false);
    }
  }, [tab, typeFilter]);

  useEffect(() => { load(); }, [load]);

  const markRead = async (id: string) => {
    try {
      await apiFetch(`/api/notifications/${id}/read`, { method: "PATCH" });
      setNotifications(prev =>
        prev.map(n => n.id === id ? { ...n, is_read: true } : n)
      );
      setUnreadCount(c => Math.max(0, c - 1));
    } catch {
      /* non-fatal */
    }
  };

  const archiveOne = async (id: string) => {
    try {
      await apiFetch(`/api/notifications/${id}/archive`, { method: "PATCH" });
      setNotifications(prev => prev.filter(n => n.id !== id));
      const wasUnread = notifications.find(n => n.id === id && !n.is_read);
      if (wasUnread) setUnreadCount(c => Math.max(0, c - 1));
    } catch {
      /* non-fatal */
    }
  };

  const markAllRead = async () => {
    setMarkingAll(true);
    try {
      await apiFetch("/api/notifications/read-all", { method: "PATCH" });
      setNotifications(prev => prev.map(n => ({ ...n, is_read: true })));
      setUnreadCount(0);
    } catch {
      /* non-fatal */
    } finally {
      setMarkingAll(false);
    }
  };

  const typeOptions = ["all", ...Array.from(new Set(notifications.map(n => n.type)))];

  const tabs: { id: FilterTab; label: string }[] = [
    { id: "all", label: "All" },
    { id: "unread", label: `Unread${unreadCount > 0 ? ` (${unreadCount})` : ""}` },
    { id: "archived", label: "Archived" },
  ];

  return (
    <div className="p-6 space-y-5 max-w-3xl mx-auto">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <Bell size={18} className="text-gray-700" />
          <div>
            <h1 className="text-xl font-semibold text-gray-900">Notifications</h1>
            {unreadCount > 0 && (
              <p className="text-sm text-gray-500">{unreadCount} unread</p>
            )}
          </div>
        </div>
        {unreadCount > 0 && tab !== "archived" && (
          <Button
            variant="outline"
            size="sm"
            onClick={markAllRead}
            disabled={markingAll}
            className="gap-1.5 text-xs"
          >
            {markingAll ? <Loader2 className="animate-spin" size={12} /> : <CheckCheck size={13} />}
            Mark all read
          </Button>
        )}
      </div>

      {error && (
        <div className="flex items-center gap-2 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
          <AlertCircle size={14} /> {error}
        </div>
      )}

      {/* Tabs + type filter */}
      <div className="flex items-center justify-between gap-4">
        <div className="flex gap-1 border-b flex-1">
          {tabs.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                tab === t.id
                  ? "border-indigo-600 text-indigo-700"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1.5">
          <Filter size={12} className="text-gray-400" />
          <select
            value={typeFilter}
            onChange={e => setTypeFilter(e.target.value)}
            className="text-xs border rounded-lg px-2 py-1.5 text-gray-600 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            {typeOptions.map(o => (
              <option key={o} value={o}>
                {o === "all" ? "All types" : o.replace(/_/g, " ")}
              </option>
            ))}
          </select>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16 text-gray-400">
          <Loader2 className="animate-spin mr-2" size={16} /> Loading…
        </div>
      ) : notifications.length === 0 ? (
        <div className="py-16 text-center text-gray-400">
          <Bell size={32} className="mx-auto mb-3 opacity-20" />
          <p className="font-medium text-gray-500">
            {tab === "unread" ? "No unread notifications" :
             tab === "archived" ? "No archived notifications" :
             "No notifications"}
          </p>
          <p className="text-sm mt-1">
            {tab === "all" ? "You're all caught up!" : ""}
          </p>
        </div>
      ) : (
        <div className="space-y-1">
          {notifications.map((n) => (
            <div
              key={n.id}
              onClick={() => !n.is_read && markRead(n.id)}
              className={`group flex gap-3 px-4 py-3.5 rounded-xl border-l-[3px] transition-colors cursor-pointer ${
                SEVERITY_COLORS[n.severity as InsightSeverity ?? "info"]
              } ${
                n.is_read
                  ? "bg-white border border-gray-100 hover:bg-gray-50/60"
                  : "bg-indigo-50/40 border border-indigo-100 hover:bg-indigo-50/60"
              }`}
            >
              <div className="pt-0.5 shrink-0">
                {SEVERITY_ICONS[n.severity as InsightSeverity ?? "info"]}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className={`text-sm leading-snug ${n.is_read ? "text-gray-700" : "text-gray-900 font-semibold"}`}>
                      {n.title}
                    </p>
                    <p className="text-[12px] text-gray-500 mt-0.5 line-clamp-2">{n.body}</p>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    {!n.is_read && (
                      <span className="w-2 h-2 rounded-full bg-indigo-500 shrink-0" />
                    )}
                    <span className="text-[11px] text-gray-400 whitespace-nowrap">{timeAgo(n.created_at)}</span>
                  </div>
                </div>
                <div className="flex items-center gap-2 mt-1.5">
                  <Badge className="text-[10px] px-1.5 py-0 bg-gray-100 text-gray-500">
                    {n.type.replace(/_/g, " ")}
                  </Badge>
                  {n.action_url && (
                    <a
                      href={n.action_url}
                      onClick={e => e.stopPropagation()}
                      className="flex items-center gap-0.5 text-[11px] text-indigo-600 hover:text-indigo-700"
                    >
                      View <ExternalLink size={9} />
                    </a>
                  )}
                </div>
              </div>
              {tab !== "archived" && (
                <button
                  onClick={e => { e.stopPropagation(); archiveOne(n.id); }}
                  title="Archive"
                  className="p-1.5 rounded opacity-0 group-hover:opacity-100 text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-all shrink-0"
                >
                  <Archive size={13} />
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
