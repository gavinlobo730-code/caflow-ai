"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import {
  Bell, CheckCheck, Archive, AlertCircle, Loader2,
  Clock, AlertTriangle, Info,
  ExternalLink,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { getSupabaseClient } from "@/lib/supabase/client";
import { DataTable } from "@/components/ui/data-table";
import type { BulkAction, Column, FilterDef } from "@/lib/table/types";
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
  info: <Info size={14} className="text-[#94A3B8]" />,
};

// Ordering used for the sortable "Severity" column (critical highest).
const SEVERITY_RANK: Record<InsightSeverity, number> = {
  critical: 5,
  high: 4,
  medium: 3,
  low: 2,
  info: 1,
};

type FilterTab = "all" | "unread" | "archived";

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
  const [markingAll, setMarkingAll] = useState(false);

  // The all/unread/archived tab is a SERVER-side filter (drives the API query);
  // the type filter and text search run client-side inside the DataTable.
  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (tab === "unread") params.set("unread_only", "true");
      if (tab === "archived") params.set("archived", "true");
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
  }, [tab]);

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

  const tabs: { id: FilterTab; label: string }[] = [
    { id: "all", label: "All" },
    { id: "unread", label: `Unread${unreadCount > 0 ? ` (${unreadCount})` : ""}` },
    { id: "archived", label: "Archived" },
  ];

  const columns: Column<Notification>[] = useMemo(() => [
    {
      key: "title",
      header: "Notification",
      accessor: (n) => `${n.title} ${n.body}`,
      searchable: true,
      sortable: true,
      sticky: true,
      hideable: false,
      render: (n) => (
        <div className="flex gap-2.5 min-w-0 max-w-xl">
          <span className="pt-0.5 shrink-0">
            {SEVERITY_ICONS[(n.severity as InsightSeverity) ?? "info"]}
          </span>
          <span
            className="min-w-0 cursor-pointer"
            onClick={() => !n.is_read && markRead(n.id)}
          >
            <span className="flex items-center gap-1.5">
              {!n.is_read && <span className="w-2 h-2 rounded-full bg-blue-500 shrink-0" />}
              <span className={`text-sm leading-snug ${n.is_read ? "text-[#334155]" : "text-[#0F172A] font-semibold"}`}>
                {n.title}
              </span>
            </span>
            <span className="block text-[12px] text-[#64748B] mt-0.5 line-clamp-2">{n.body}</span>
            {n.action_url && (
              <a
                href={n.action_url}
                onClick={e => e.stopPropagation()}
                className="mt-1 inline-flex items-center gap-0.5 text-[11px] text-blue-600 hover:text-blue-600"
              >
                View <ExternalLink size={9} />
              </a>
            )}
          </span>
        </div>
      ),
    },
    {
      key: "type",
      header: "Type",
      accessor: (n) => n.type,
      sortable: true,
      render: (n) => (
        <Badge className="text-[10px] px-1.5 py-0 bg-[#F1F5F9] text-[#64748B]">
          {n.type.replace(/_/g, " ")}
        </Badge>
      ),
    },
    {
      key: "severity",
      header: "Severity",
      accessor: (n) => SEVERITY_RANK[(n.severity as InsightSeverity) ?? "info"] ?? 0,
      sortable: true,
      align: "center",
      render: (n) => (
        <span className="inline-flex items-center gap-1 capitalize text-xs text-[#475569]">
          {SEVERITY_ICONS[(n.severity as InsightSeverity) ?? "info"]}
          {n.severity ?? "info"}
        </span>
      ),
    },
    {
      key: "is_read",
      header: "Status",
      accessor: (n) => (n.is_read ? "Read" : "Unread"),
      sortable: true,
      render: (n) =>
        n.is_read
          ? <span className="text-xs text-[#94A3B8]">Read</span>
          : <span className="text-xs font-medium text-blue-600">Unread</span>,
    },
    {
      key: "created_at",
      header: "When",
      accessor: (n) => n.created_at,
      sortable: true,
      align: "right",
      render: (n) => (
        <span className="text-[11px] text-[#94A3B8] whitespace-nowrap" title={n.created_at}>
          {timeAgo(n.created_at)}
        </span>
      ),
    },
  ], []);

  // Type options are derived from the currently loaded notifications.
  const filters: FilterDef<Notification>[] = useMemo(() => {
    const types = Array.from(new Set(notifications.map(n => n.type)));
    return [
      {
        key: "type",
        label: "Type",
        type: "select",
        accessor: (n) => n.type,
        options: types.map(t => ({ value: t, label: t.replace(/_/g, " ") })),
      },
    ];
  }, [notifications]);

  const bulkActions: BulkAction<Notification>[] = useMemo(() => [
    {
      id: "mark-read",
      label: "Mark read",
      icon: <CheckCheck size={13} />,
      run: async (rows) => {
        for (const n of rows) {
          if (!n.is_read) await markRead(n.id);
        }
      },
    },
    ...(tab !== "archived"
      ? [{
          id: "archive",
          label: "Archive",
          icon: <Archive size={13} />,
          confirm: "Archive the selected notifications?",
          run: async (rows: Notification[]) => {
            for (const n of rows) await archiveOne(n.id);
          },
        } as BulkAction<Notification>]
      : []),
  ], [tab]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="p-6 space-y-5 max-w-5xl mx-auto">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <Bell size={18} className="text-[#334155]" />
          <div>
            <h1 className="text-xl font-semibold text-[#0F172A]">Notifications</h1>
            {unreadCount > 0 && (
              <p className="text-sm text-[#64748B]">{unreadCount} unread</p>
            )}
          </div>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
          <AlertCircle size={14} /> {error}
        </div>
      )}

      {/* Tabs (server-side scope: all / unread / archived) */}
      <div className="flex gap-1 border-b">
        {tabs.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              tab === t.id
                ? "border-blue-500/20 text-blue-600"
                : "border-transparent text-[#64748B] hover:text-[#334155]"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <DataTable
        data={notifications}
        columns={columns}
        filters={filters}
        getRowId={(n) => n.id}
        loading={loading}
        error={error}
        onRetry={load}
        onRefresh={load}
        searchPlaceholder="Search notifications…"
        initialSort={{ key: "created_at", dir: "desc" }}
        persistKey="notifications.list"
        bulkActions={bulkActions}
        emptyTitle={
          tab === "unread" ? "No unread notifications" :
          tab === "archived" ? "No archived notifications" :
          "No notifications"
        }
        emptyDescription={tab === "all" ? "You're all caught up!" : undefined}
        toolbarExtra={
          unreadCount > 0 && tab !== "archived" ? (
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
          ) : undefined
        }
        rowActions={(n) =>
          tab !== "archived" ? (
            <button
              onClick={() => archiveOne(n.id)}
              title="Archive"
              className="p-1.5 rounded text-[#94A3B8] hover:text-[#475569] hover:bg-[#F1F5F9] transition-all"
            >
              <Archive size={13} />
            </button>
          ) : null
        }
      />
    </div>
  );
}
