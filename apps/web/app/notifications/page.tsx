"use client";

import { useState, useEffect, useCallback } from "react";
import { CheckSquare, AlertTriangle, FileText, Calendar, Bot, RefreshCw, Bell } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { Notification, NotificationType, InsightSeverity } from "@/lib/types";
import { formatRelativeTime } from "@/lib/services/formatting";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const TYPE_ICONS: Record<NotificationType, React.ElementType> = {
  task_assigned: CheckSquare,
  risk_detected: AlertTriangle,
  document_processed: FileText,
  compliance_due: Calendar,
  ai_recommendation: Bot,
  status_changed: RefreshCw,
};

const TYPE_LABELS: Record<NotificationType, string> = {
  task_assigned: "Task Assigned",
  risk_detected: "Risk Detected",
  document_processed: "Document",
  compliance_due: "Compliance Due",
  ai_recommendation: "AI Insight",
  status_changed: "Status Changed",
};

const SEVERITY_DOT: Record<InsightSeverity, string> = {
  critical: "bg-red-500",
  high: "bg-orange-400",
  medium: "bg-amber-400",
  low: "bg-green-500",
  info: "bg-blue-400",
};

const TAB_OPTIONS = [
  { id: "all", label: "All" },
  { id: "unread", label: "Unread" },
  { id: "task_assigned", label: "Tasks" },
  { id: "risk_detected", label: "Risks" },
  { id: "document_processed", label: "Documents" },
  { id: "compliance_due", label: "Compliance" },
  { id: "ai_recommendation", label: "AI" },
];

function LoadingSkeleton() {
  return (
    <div className="p-6 max-w-4xl mx-auto space-y-4 animate-pulse">
      <div className="h-8 bg-gray-200 rounded w-48" />
      <div className="flex gap-2">
        {Array.from({ length: 5 }).map((_, i) => <div key={i} className="h-8 w-20 bg-gray-100 rounded-lg" />)}
      </div>
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="h-16 bg-gray-50 rounded-lg" />
      ))}
    </div>
  );
}

export default function NotificationsPage() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("all");
  const [markingAll, setMarkingAll] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${BASE_URL}/api/notifications`).then((r) => r.json());
      if (res.success) setNotifications(res.data ?? []);
      else setError(res.error ?? "Failed to load notifications");
    } catch {
      setError("Failed to load notifications");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  async function markRead(id: string) {
    await fetch(`${BASE_URL}/api/notifications/${id}/read`, { method: "PATCH" });
    setNotifications((prev) =>
      prev.map((n) => (n.id === id ? { ...n, is_read: true } : n))
    );
  }

  async function markAllRead() {
    setMarkingAll(true);
    try {
      await fetch(`${BASE_URL}/api/notifications/read-all`, { method: "PATCH" });
      setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
    } finally {
      setMarkingAll(false);
    }
  }

  if (loading) return <LoadingSkeleton />;

  if (error) {
    return (
      <div className="p-6 max-w-4xl mx-auto">
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-5 py-4 flex items-center justify-between">
          <span className="text-sm">{error}</span>
          <button onClick={loadData} className="text-xs underline hover:no-underline">Retry</button>
        </div>
      </div>
    );
  }

  const unreadCount = notifications.filter((n) => !n.is_read).length;

  const filtered = notifications.filter((n) => {
    if (activeTab === "all") return true;
    if (activeTab === "unread") return !n.is_read;
    return n.type === activeTab;
  });

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold text-gray-900">Notifications</h1>
          {unreadCount > 0 && (
            <Badge className="bg-blue-600 text-white px-2 py-0.5 text-xs">
              {unreadCount} unread
            </Badge>
          )}
        </div>
        {unreadCount > 0 && (
          <button
            onClick={markAllRead}
            disabled={markingAll}
            className="text-sm text-blue-600 hover:underline disabled:opacity-50"
          >
            {markingAll ? "Marking…" : "Mark all read"}
          </button>
        )}
      </div>

      {/* Tabs */}
      <div className="flex flex-wrap gap-1.5">
        {TAB_OPTIONS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`text-xs px-3 py-1.5 rounded-lg font-medium transition-colors ${
              activeTab === tab.id
                ? "bg-blue-600 text-white"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            }`}
          >
            {tab.label}
            {tab.id === "unread" && unreadCount > 0 && (
              <span className="ml-1.5 bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded-full text-[10px]">
                {unreadCount}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Notification list */}
      <div className="space-y-2">
        {filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <Bell size={32} className="text-gray-300 mb-3" />
            <p className="text-gray-500 text-sm">No notifications</p>
          </div>
        ) : (
          filtered.map((n) => {
            const Icon = TYPE_ICONS[n.type] ?? Bell;
            return (
              <div
                key={n.id}
                onClick={() => { if (!n.is_read) markRead(n.id); }}
                className={`flex items-start gap-4 px-4 py-3 rounded-xl border transition-colors cursor-pointer ${
                  n.is_read
                    ? "bg-white border-gray-100 hover:bg-gray-50"
                    : "bg-blue-50 border-blue-100 hover:bg-blue-100 border-l-4 border-l-blue-500"
                }`}
              >
                <div className="w-8 h-8 rounded-full bg-gray-100 flex items-center justify-center shrink-0 mt-0.5">
                  <Icon size={15} className="text-gray-600" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className={`w-2 h-2 rounded-full shrink-0 ${SEVERITY_DOT[n.severity] ?? "bg-gray-400"}`} />
                    <p className={`text-sm ${n.is_read ? "text-gray-800 font-normal" : "text-gray-900 font-semibold"}`}>
                      {n.title}
                    </p>
                    <Badge variant="outline" className="text-[10px] px-1.5 py-0 ml-auto shrink-0">
                      {TYPE_LABELS[n.type] ?? n.type}
                    </Badge>
                  </div>
                  <p className="text-xs text-gray-500 leading-relaxed">{n.body}</p>
                  <p className="text-[11px] text-gray-400 mt-1">{formatRelativeTime(n.created_at)}</p>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
