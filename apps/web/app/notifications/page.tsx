"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Bell,
  AlertTriangle,
  Clock,
  CheckCircle,
  Users,
  X,
  MessageSquare,
} from "lucide-react";
import Link from "next/link";
import { getSupabaseClient } from "@/lib/supabase/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type NotifType = "deadline" | "overdue" | "new_client" | "task";

interface Notification {
  id: string;
  type: NotifType;
  title: string;
  description: string;
  timestamp: Date;
}

type FilterTab = "All" | "Unread" | "Deadlines" | "Tasks";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function timeAgo(date: Date): string {
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHour = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHour / 24);

  if (diffDay >= 1) return `${diffDay} day${diffDay > 1 ? "s" : ""} ago`;
  if (diffHour >= 1) return `${diffHour} hour${diffHour > 1 ? "s" : ""} ago`;
  if (diffMin >= 1) return `${diffMin} minute${diffMin > 1 ? "s" : ""} ago`;
  return "just now";
}

function notifIconConfig(type: NotifType): {
  Icon: React.ElementType;
  bg: string;
  color: string;
} {
  switch (type) {
    case "deadline":
      return { Icon: Clock, bg: "bg-orange-50", color: "text-orange-500" };
    case "overdue":
      return { Icon: AlertTriangle, bg: "bg-red-50", color: "text-red-500" };
    case "new_client":
      return { Icon: Users, bg: "bg-blue-50", color: "text-blue-500" };
    case "task":
      return { Icon: Bell, bg: "bg-yellow-50", color: "text-yellow-500" };
  }
}

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

async function getFirmId(): Promise<string> {
  const sb = getSupabaseClient();
  const {
    data: { session },
  } = await sb.auth.getSession();
  if (!session) throw new Error("Not authenticated");
  const { data } = await sb
    .from("users")
    .select("firm_id")
    .eq("auth_user_id", session.user.id)
    .single();
  if (!data) throw new Error("User not found");
  return data.firm_id as string;
}

async function fetchNotifications(): Promise<Notification[]> {
  const sb = getSupabaseClient();
  const today = new Date();
  const todayStr = today.toISOString().split("T")[0];
  const in7Days = new Date(today.getTime() + 7 * 86400000)
    .toISOString()
    .split("T")[0];
  const in3Days = new Date(today.getTime() + 3 * 86400000)
    .toISOString()
    .split("T")[0];

  let firmId: string;
  try {
    firmId = await getFirmId();
  } catch {
    return [];
  }

  const notifications: Notification[] = [];

  // -------------------------------------------------------------------------
  // Deadline approaching — CGST Act Section 37 (GSTR-1), Section 39 (GSTR-3B)
  // compliance_entries where due_date within 7 days and status != 'filed'
  // -------------------------------------------------------------------------
  try {
    const { data: approaching } = await sb
      .from("compliance_entries")
      .select("id, compliance_type, due_date, clients(client_name)")
      .eq("firm_id", firmId)
      .neq("status", "filed")
      .gte("due_date", todayStr)
      .lte("due_date", in7Days);

    if (approaching) {
      for (const entry of approaching) {
        const daysLeft = Math.ceil(
          (new Date(entry.due_date).getTime() - today.getTime()) / 86400000
        );
        const clientsRaw1 = entry.clients as unknown as
          | { client_name: string }
          | { client_name: string }[]
          | null;
        const clientName = clientsRaw1
          ? Array.isArray(clientsRaw1)
            ? (clientsRaw1[0]?.client_name ?? "Unknown Client")
            : clientsRaw1.client_name
          : "Unknown Client";
        notifications.push({
          id: `deadline-${entry.id}`,
          type: "deadline",
          title: `${entry.compliance_type} due for ${clientName}`,
          description: `Filing is due in ${daysLeft} day${daysLeft !== 1 ? "s" : ""} (${entry.due_date})`,
          timestamp: new Date(),
        });
      }
    }
  } catch {
    // Table may not exist — skip gracefully
  }

  // -------------------------------------------------------------------------
  // Overdue filings — CGST Act Section 37/39
  // compliance_entries where due_date < today and status != 'filed'
  // -------------------------------------------------------------------------
  try {
    const { data: overdue } = await sb
      .from("compliance_entries")
      .select("id, compliance_type, due_date, clients(client_name)")
      .eq("firm_id", firmId)
      .neq("status", "filed")
      .lt("due_date", todayStr);

    if (overdue) {
      for (const entry of overdue) {
        const daysOverdue = Math.ceil(
          (today.getTime() - new Date(entry.due_date).getTime()) / 86400000
        );
        const clientsRaw2 = entry.clients as
          | { client_name: string }
          | { client_name: string }[]
          | null;
        const clientName = clientsRaw2
          ? Array.isArray(clientsRaw2)
            ? (clientsRaw2[0]?.client_name ?? "Unknown Client")
            : clientsRaw2.client_name
          : "Unknown Client";
        notifications.push({
          id: `overdue-${entry.id}`,
          type: "overdue",
          title: `${entry.compliance_type} for ${clientName} is overdue`,
          description: `Overdue by ${daysOverdue} day${daysOverdue !== 1 ? "s" : ""} (due ${entry.due_date})`,
          timestamp: new Date(entry.due_date),
        });
      }
    }
  } catch {
    // Table may not exist — skip gracefully
  }

  // -------------------------------------------------------------------------
  // New clients — latest 3 ordered by created_at desc
  // -------------------------------------------------------------------------
  try {
    const { data: newClients } = await sb
      .from("clients")
      .select("id, client_name, created_at")
      .eq("firm_id", firmId)
      .order("created_at", { ascending: false })
      .limit(3);

    if (newClients) {
      for (const client of newClients) {
        notifications.push({
          id: `client-${client.id}`,
          type: "new_client",
          title: `New client added`,
          description: `${client.client_name} has been added to your practice`,
          timestamp: new Date(client.created_at as string),
        });
      }
    }
  } catch {
    // Table may not exist — skip gracefully
  }

  // -------------------------------------------------------------------------
  // Tasks due soon — within 3 days and status != 'completed'
  // -------------------------------------------------------------------------
  try {
    const { data: tasks } = await sb
      .from("tasks")
      .select("id, title, due_date, created_at")
      .eq("firm_id", firmId)
      .neq("status", "completed")
      .gte("due_date", todayStr)
      .lte("due_date", in3Days);

    if (tasks) {
      for (const task of tasks) {
        const daysLeft = Math.ceil(
          (new Date(task.due_date as string).getTime() - today.getTime()) /
            86400000
        );
        notifications.push({
          id: `task-${task.id}`,
          type: "task",
          title: `Task due soon: ${task.title as string}`,
          description: `Due in ${daysLeft} day${daysLeft !== 1 ? "s" : ""} (${task.due_date as string})`,
          timestamp: new Date(task.created_at as string),
        });
      }
    }
  } catch {
    // Table may not exist — skip gracefully
  }

  // Sort: overdue first, then by timestamp desc
  notifications.sort((a, b) => {
    if (a.type === "overdue" && b.type !== "overdue") return -1;
    if (b.type === "overdue" && a.type !== "overdue") return 1;
    return b.timestamp.getTime() - a.timestamp.getTime();
  });

  return notifications;
}

// ---------------------------------------------------------------------------
// localStorage read-state helpers
// ---------------------------------------------------------------------------

const LS_KEY = "caflow_read_notifs";

function getReadSet(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return new Set();
    return new Set(JSON.parse(raw) as string[]);
  } catch {
    return new Set();
  }
}

function saveReadSet(set: Set<string>): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(LS_KEY, JSON.stringify(Array.from(set)));
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const FILTER_TABS: FilterTab[] = ["All", "Unread", "Deadlines", "Tasks"];

export default function NotificationsPage() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [readIds, setReadIds] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<FilterTab>("All");

  // Load notifications + read state
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const notifs = await fetchNotifications();
      setNotifications(notifs);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setReadIds(getReadSet());
    void load();
  }, [load]);

  // -------------------------------------------------------------------------
  // Mark as read
  // -------------------------------------------------------------------------

  function markRead(id: string) {
    setReadIds((prev) => {
      const next = new Set(prev);
      next.add(id);
      saveReadSet(next);
      return next;
    });
  }

  function markAllRead() {
    setReadIds((prev) => {
      const next = new Set(prev);
      for (const n of notifications) next.add(n.id);
      saveReadSet(next);
      return next;
    });
  }

  // -------------------------------------------------------------------------
  // Filtering
  // -------------------------------------------------------------------------

  const filtered = notifications.filter((n) => {
    if (activeTab === "Unread") return !readIds.has(n.id);
    if (activeTab === "Deadlines")
      return n.type === "deadline" || n.type === "overdue";
    if (activeTab === "Tasks") return n.type === "task";
    return true;
  });

  const unreadCount = notifications.filter((n) => !readIds.has(n.id)).length;

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold text-gray-900">
              Notifications
            </h1>
            {unreadCount > 0 && (
              <span className="inline-flex items-center justify-center min-w-[22px] h-[22px] px-1.5 bg-red-500 text-white text-xs font-bold rounded-full">
                {unreadCount}
              </span>
            )}
          </div>
          <p className="text-sm text-gray-500 mt-0.5">
            Deadline alerts, task reminders, and client updates
          </p>
        </div>
        {unreadCount > 0 && (
          <button
            onClick={markAllRead}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-blue-600 bg-blue-50 rounded-lg hover:bg-blue-100 transition-colors"
          >
            <CheckCircle className="w-3.5 h-3.5" />
            Mark all as read
          </button>
        )}
      </div>

      {/* WhatsApp shortcut */}
      <Link
        href="/notifications/whatsapp"
        className="flex items-center gap-3 bg-green-50 border border-green-200 rounded-lg px-4 py-3 hover:bg-green-100 transition-colors"
      >
        <MessageSquare size={16} className="text-green-600 shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-green-800">WhatsApp Reminder Templates</p>
          <p className="text-xs text-green-600">Compose and send GSTR, ITR, and fee reminders via WhatsApp Web</p>
        </div>
        <span className="text-green-500 text-xs font-medium shrink-0">Open →</span>
      </Link>

      {/* Filter tabs */}
      <div className="flex gap-1 border-b border-gray-100">
        {FILTER_TABS.map((tab) => {
          const count =
            tab === "Unread"
              ? unreadCount
              : tab === "Deadlines"
              ? notifications.filter(
                  (n) => n.type === "deadline" || n.type === "overdue"
                ).length
              : tab === "Tasks"
              ? notifications.filter((n) => n.type === "task").length
              : notifications.length;

          return (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors flex items-center gap-1.5 ${
                activeTab === tab
                  ? "border-blue-600 text-blue-700"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              {tab}
              {count > 0 && (
                <span
                  className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${
                    activeTab === tab
                      ? "bg-blue-100 text-blue-700"
                      : "bg-gray-100 text-gray-500"
                  }`}
                >
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Content */}
      {loading ? (
        <div className="bg-white rounded-xl border border-gray-100 px-5 py-16 text-center text-sm text-gray-400">
          Loading notifications…
        </div>
      ) : filtered.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-100 px-5 py-16 text-center space-y-3">
          <CheckCircle className="w-10 h-10 text-green-300 mx-auto" />
          <p className="text-sm font-medium text-gray-600">
            {activeTab === "Unread"
              ? "No unread notifications"
              : "You're all caught up!"}
          </p>
          <p className="text-xs text-gray-400">
            {activeTab === "Unread"
              ? "All notifications have been read."
              : "No notifications in this category right now."}
          </p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-100 overflow-hidden divide-y divide-gray-50">
          {filtered.map((notif) => {
            const isUnread = !readIds.has(notif.id);
            const { Icon, bg, color } = notifIconConfig(notif.type);
            return (
              <div
                key={notif.id}
                onClick={() => markRead(notif.id)}
                className={`flex items-start gap-4 px-5 py-4 cursor-pointer transition-colors ${
                  isUnread
                    ? "bg-blue-50/30 hover:bg-blue-50/50"
                    : "hover:bg-gray-50/50"
                }`}
              >
                {/* Icon */}
                <div
                  className={`flex items-center justify-center w-10 h-10 rounded-full shrink-0 ${bg}`}
                >
                  <Icon className={`w-5 h-5 ${color}`} />
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-start justify-between gap-2">
                    <p
                      className={`text-sm font-medium leading-snug ${
                        isUnread ? "text-gray-900" : "text-gray-600"
                      }`}
                    >
                      {notif.title}
                    </p>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="text-xs text-gray-400 whitespace-nowrap">
                        {timeAgo(notif.timestamp)}
                      </span>
                      {isUnread && (
                        <span className="w-2 h-2 rounded-full bg-blue-500 shrink-0" />
                      )}
                    </div>
                  </div>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {notif.description}
                  </p>
                </div>

                {/* Dismiss (mark read) */}
                {isUnread && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      markRead(notif.id);
                    }}
                    className="text-gray-300 hover:text-gray-500 transition-colors shrink-0 mt-0.5"
                    aria-label="Mark as read"
                  >
                    <X className="w-4 h-4" />
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
