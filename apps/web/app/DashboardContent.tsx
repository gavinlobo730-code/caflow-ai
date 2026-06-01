"use client";

import { useState, useEffect } from "react";
import {
  Users,
  Clock,
  AlertTriangle,
  FileCheck,
  Plus,
  BookOpen,
  Receipt,
  Bot,
  Calendar,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { getSupabaseClient } from "@/lib/supabase/client";
import { useAuth } from "@/lib/auth/AuthContext";

// ─── Types ──────────────────────────────────────────────────────────────────

interface KPIs {
  totalClients: number;
  pendingTasks: number;
  filingsDueThisMonth: number;
  overdueFilings: number;
}

interface RecentClient {
  id: string;
  name: string;
  gstin: string | null;
  entity_type: string | null;
}

interface RecentTask {
  id: string;
  title: string;
  due_date: string | null;
  status: string | null;
  client_name: string | null;
}

interface UpcomingDeadline {
  name: string;
  date: string; // YYYY-MM-DD
  daysLeft: number;
}

// ─── Indian tax deadline generator ─────────────────────────────────────────
// CGST Act §39 — GSTR-1 due 11th of following month
// CGST Act §39 — GSTR-3B due 20th of following month
// IT Act §139 — ITR due 31st July
// Finance Act — Advance tax: 15 Jun (15%), 15 Sep (45%), 15 Dec (75%), 15 Mar (100%)
// CGST Act §44 — GSTR-9 annual: 31st December
// IT Act §200 — TDS return: 31st of month following quarter end
function getUpcomingDeadlines(today: Date): UpcomingDeadline[] {
  const year = today.getFullYear();
  const month = today.getMonth(); // 0-based

  const deadlines: { name: string; date: Date }[] = [];

  // Generate GSTR-1 and GSTR-3B for current month and next 2 months
  for (let offset = -1; offset <= 2; offset++) {
    let m = month + offset;
    let y = year;
    while (m < 0) { m += 12; y--; }
    while (m > 11) { m -= 12; y++; }

    // GSTR-1: 11th of the following month (for filings of month m)
    const gstr1Month = m + 1 > 11 ? 0 : m + 1;
    const gstr1Year = m + 1 > 11 ? y + 1 : y;
    deadlines.push({ name: `GSTR-1 (${new Date(y, m, 1).toLocaleString("default", { month: "short" })} ${y})`, date: new Date(gstr1Year, gstr1Month, 11) });

    // GSTR-3B: 20th of the following month
    deadlines.push({ name: `GSTR-3B (${new Date(y, m, 1).toLocaleString("default", { month: "short" })} ${y})`, date: new Date(gstr1Year, gstr1Month, 20) });
  }

  // Advance tax dates for current FY
  // Indian FY: April 1 to March 31
  const fyStart = month >= 3 ? year : year - 1;
  deadlines.push({ name: "Advance Tax — 1st Instalment (15%)", date: new Date(fyStart, 5, 15) });     // 15 Jun
  deadlines.push({ name: "Advance Tax — 2nd Instalment (45%)", date: new Date(fyStart, 8, 15) });     // 15 Sep
  deadlines.push({ name: "Advance Tax — 3rd Instalment (75%)", date: new Date(fyStart, 11, 15) });    // 15 Dec
  deadlines.push({ name: "Advance Tax — Final Instalment (100%)", date: new Date(fyStart + 1, 2, 15) }); // 15 Mar

  // GSTR-9 annual (31 Dec)
  deadlines.push({ name: "GSTR-9 Annual Return", date: new Date(year, 11, 31) });

  // TDS returns — 31st of month following each quarter end
  // Q1: Apr–Jun → 31 Jul | Q2: Jul–Sep → 31 Oct | Q3: Oct–Dec → 31 Jan | Q4: Jan–Mar → 31 May
  const fyYear = month >= 3 ? year : year - 1;
  deadlines.push({ name: "TDS Return Q1 (24Q/26Q)", date: new Date(fyYear, 6, 31) });
  deadlines.push({ name: "TDS Return Q2 (24Q/26Q)", date: new Date(fyYear, 9, 31) });
  deadlines.push({ name: "TDS Return Q3 (24Q/26Q)", date: new Date(fyYear + 1, 0, 31) });
  deadlines.push({ name: "TDS Return Q4 (24Q/26Q)", date: new Date(fyYear + 1, 4, 31) });

  // ITR due date: 31 July
  deadlines.push({ name: "ITR Filing Deadline", date: new Date(fyYear + 1, 6, 31) });

  const todayMs = today.getTime();
  return deadlines
    .map((d) => ({
      name: d.name,
      date: d.date.toISOString().split("T")[0],
      daysLeft: Math.ceil((d.date.getTime() - todayMs) / 86400000),
    }))
    .filter((d) => d.daysLeft >= 0)
    .sort((a, b) => a.daysLeft - b.daysLeft)
    .slice(0, 7);
}

// ─── Greeting ────────────────────────────────────────────────────────────────
function getGreeting(email: string): string {
  const hour = new Date().getHours();
  const name = email.split("@")[0];
  const greeting = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  return `${greeting}, ${name}`;
}

// ─── Badge colors ────────────────────────────────────────────────────────────
const STATUS_COLORS: Record<string, string> = {
  completed: "bg-green-100 text-green-700",
  in_progress: "bg-blue-100 text-blue-700",
  todo: "bg-gray-100 text-gray-600",
  review_required: "bg-amber-100 text-amber-700",
  waiting_client: "bg-purple-100 text-purple-700",
};

function statusBadge(status: string | null) {
  const s = status ?? "todo";
  const cls = STATUS_COLORS[s] ?? "bg-gray-100 text-gray-600";
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${cls}`}>
      {s.replace(/_/g, " ")}
    </span>
  );
}

function deadlineBadge(daysLeft: number) {
  if (daysLeft === 0) return <span className="text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-700 font-semibold">Today</span>;
  if (daysLeft <= 3) return <span className="text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-700">{daysLeft}d</span>;
  if (daysLeft <= 7) return <span className="text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-700">{daysLeft}d</span>;
  if (daysLeft <= 14) return <span className="text-xs px-2 py-0.5 rounded-full bg-yellow-100 text-yellow-700">{daysLeft}d</span>;
  return <span className="text-xs px-2 py-0.5 rounded-full bg-green-100 text-green-700">{daysLeft}d</span>;
}

// ─── Skeleton ─────────────────────────────────────────────────────────────────
function Skeleton({ className }: { className?: string }) {
  return <div className={`animate-pulse bg-gray-200 rounded ${className ?? ""}`} />;
}

// ─── Main component ──────────────────────────────────────────────────────────
export default function DashboardContent() {
  const { user } = useAuth();
  const supabase = getSupabaseClient();
  const router = useRouter();

  const [kpis, setKpis] = useState<KPIs | null>(null);
  const [recentClients, setRecentClients] = useState<RecentClient[] | null>(null);
  const [recentTasks, setRecentTasks] = useState<RecentTask[] | null>(null);
  const [loading, setLoading] = useState(true);

  const today = new Date();
  const upcomingDeadlines = getUpcomingDeadlines(today);

  useEffect(() => {
    if (!user) return;

    async function load() {
      try {
        // Get firm_id from users table
        const { data: userData } = await supabase
          .from("users")
          .select("firm_id")
          .eq("auth_user_id", user!.id)
          .maybeSingle();

        const firmId: string | null = userData?.firm_id ?? null;
        if (!firmId) {
          setKpis({ totalClients: 0, pendingTasks: 0, filingsDueThisMonth: 0, overdueFilings: 0 });
          setRecentClients([]);
          setRecentTasks([]);
          setLoading(false);
          return;
        }

        // ── Onboarding check: redirect new firms that haven't set up yet ──
        const [{ data: firmMeta }, { count: coaCount }] = await Promise.all([
          supabase.from("firms").select("name").eq("id", firmId).maybeSingle(),
          supabase.from("chart_of_accounts").select("id", { count: "exact", head: true }).eq("firm_id", firmId),
        ]);
        if (!firmMeta?.name && (coaCount ?? 0) === 0) {
          router.replace("/onboarding");
          return;
        }

        const todayStr = today.toISOString().split("T")[0];
        const monthStart = todayStr.slice(0, 7) + "-01";
        const monthEnd = new Date(today.getFullYear(), today.getMonth() + 1, 0).toISOString().split("T")[0];

        // ── KPI: Total clients ────────────────────────────────────────────
        const { count: totalClients } = await supabase
          .from("clients")
          .select("id", { count: "exact", head: true })
          .eq("firm_id", firmId);

        // ── KPI: Pending tasks ────────────────────────────────────────────
        let pendingTasks = 0;
        try {
          const { count } = await supabase
            .from("tasks")
            .select("id", { count: "exact", head: true })
            .eq("firm_id", firmId)
            .neq("status", "completed");
          pendingTasks = count ?? 0;
        } catch { pendingTasks = 0; }

        // ── KPI: Filings due this month ────────────────────────────────────
        let filingsDueThisMonth = 0;
        try {
          const { count } = await supabase
            .from("compliance_entries")
            .select("id", { count: "exact", head: true })
            .eq("firm_id", firmId)
            .gte("due_date", monthStart)
            .lte("due_date", monthEnd)
            .neq("status", "filed");
          filingsDueThisMonth = count ?? 0;
        } catch { filingsDueThisMonth = 0; }

        // ── KPI: Overdue filings ──────────────────────────────────────────
        let overdueFilings = 0;
        try {
          const { count } = await supabase
            .from("compliance_entries")
            .select("id", { count: "exact", head: true })
            .eq("firm_id", firmId)
            .lt("due_date", todayStr)
            .neq("status", "filed");
          overdueFilings = count ?? 0;
        } catch { overdueFilings = 0; }

        // ── Recent clients ────────────────────────────────────────────────
        const { data: clientsData } = await supabase
          .from("clients")
          .select("id, name, gstin, entity_type")
          .eq("firm_id", firmId)
          .order("created_at", { ascending: false })
          .limit(5);

        // ── Recent tasks ──────────────────────────────────────────────────
        let tasksData: RecentTask[] = [];
        try {
          const { data } = await supabase
            .from("tasks")
            .select("id, title, due_date, status, client_name")
            .eq("firm_id", firmId)
            .order("created_at", { ascending: false })
            .limit(5);
          tasksData = (data as RecentTask[]) ?? [];
        } catch { tasksData = []; }

        setKpis({
          totalClients: totalClients ?? 0,
          pendingTasks: pendingTasks ?? 0,
          filingsDueThisMonth: filingsDueThisMonth ?? 0,
          overdueFilings: overdueFilings ?? 0,
        });
        setRecentClients((clientsData as RecentClient[]) ?? []);
        setRecentTasks(tasksData);
      } catch {
        setKpis({ totalClients: 0, pendingTasks: 0, filingsDueThisMonth: 0, overdueFilings: 0 });
        setRecentClients([]);
        setRecentTasks([]);
      } finally {
        setLoading(false);
      }
    }

    load();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  const greeting = user?.email ? getGreeting(user.email) : "Good day";

  // ── KPI card definitions ──────────────────────────────────────────────────
  const KPI_CARDS = [
    {
      label: "Total Clients",
      value: kpis?.totalClients ?? 0,
      icon: Users,
      iconBg: "bg-blue-50",
      iconColor: "text-blue-600",
      href: "/clients",
    },
    {
      label: "Pending Tasks",
      value: kpis?.pendingTasks ?? 0,
      icon: Clock,
      iconBg: "bg-amber-50",
      iconColor: "text-amber-600",
      href: "/tasks",
    },
    {
      label: "Filings Due This Month",
      value: kpis?.filingsDueThisMonth ?? 0,
      icon: FileCheck,
      iconBg: "bg-indigo-50",
      iconColor: "text-indigo-600",
      href: "/compliance",
    },
    {
      label: "Overdue Filings",
      value: kpis?.overdueFilings ?? 0,
      icon: AlertTriangle,
      iconBg: "bg-red-50",
      iconColor: "text-red-600",
      href: "/compliance",
    },
  ];

  const QUICK_ACTIONS = [
    { label: "+ New Client", href: "/clients", color: "bg-blue-600 hover:bg-blue-700 text-white" },
    { label: "+ Journal Entry", href: "/accounting", color: "bg-emerald-600 hover:bg-emerald-700 text-white" },
    { label: "View GST", href: "/gst", color: "bg-orange-500 hover:bg-orange-600 text-white" },
    { label: "AI Assistant", href: "/ai-assistant", color: "bg-violet-600 hover:bg-violet-700 text-white" },
  ];

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div>
        <h1 className="text-xl font-semibold text-gray-900">{greeting}</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Here&apos;s your practice overview for today, {today.toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric" })}.
        </p>
      </div>

      {/* ── KPI Cards ──────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {KPI_CARDS.map((card) => (
          <Link key={card.label} href={card.href}>
            <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5 hover:shadow-md transition-shadow cursor-pointer h-full">
              <div className={`w-9 h-9 rounded-lg ${card.iconBg} flex items-center justify-center mb-3`}>
                <card.icon size={17} className={card.iconColor} />
              </div>
              {loading ? (
                <Skeleton className="h-8 w-12 mb-1" />
              ) : (
                <p className="text-3xl font-bold text-gray-900">{card.value}</p>
              )}
              <p className="text-xs text-gray-500 mt-1 leading-tight">{card.label}</p>
            </div>
          </Link>
        ))}
      </div>

      {/* ── Middle row: Deadlines + Recent Clients ─────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* Upcoming Deadlines */}
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <div className="flex items-center gap-2.5 px-5 py-4 border-b border-gray-50">
            <Calendar size={15} className="text-gray-500" />
            <h2 className="text-sm font-semibold text-gray-900">Upcoming Tax Deadlines</h2>
          </div>
          <div className="divide-y divide-gray-50">
            {upcomingDeadlines.map((d) => (
              <div key={d.name + d.date} className="flex items-center justify-between px-5 py-3">
                <div>
                  <p className="text-sm text-gray-800 font-medium leading-tight">{d.name}</p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    {new Date(d.date + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}
                  </p>
                </div>
                {deadlineBadge(d.daysLeft)}
              </div>
            ))}
          </div>
        </div>

        {/* Recent Clients */}
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <div className="flex items-center justify-between px-5 py-4 border-b border-gray-50">
            <div className="flex items-center gap-2.5">
              <Users size={15} className="text-gray-500" />
              <h2 className="text-sm font-semibold text-gray-900">Recent Clients</h2>
            </div>
            <Link href="/clients" className="text-xs text-blue-600 hover:underline">View all →</Link>
          </div>
          <div className="divide-y divide-gray-50">
            {loading ? (
              Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="flex items-center gap-3 px-5 py-3">
                  <Skeleton className="h-4 w-32" />
                  <Skeleton className="h-4 w-24 ml-auto" />
                </div>
              ))
            ) : recentClients && recentClients.length > 0 ? (
              recentClients.map((c) => (
                <Link key={c.id} href="/clients">
                  <div className="flex items-center justify-between px-5 py-3 hover:bg-gray-50 transition-colors">
                    <div>
                      <p className="text-sm font-medium text-gray-900">{c.name}</p>
                      {c.gstin && (
                        <p className="text-xs text-gray-400 font-mono mt-0.5">{c.gstin}</p>
                      )}
                    </div>
                    {c.entity_type && (
                      <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600">
                        {c.entity_type}
                      </span>
                    )}
                  </div>
                </Link>
              ))
            ) : (
              <div className="px-5 py-8 text-center text-sm text-gray-400">No clients yet</div>
            )}
          </div>
        </div>
      </div>

      {/* ── Bottom row: Recent Tasks + Quick Actions ────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

        {/* Recent Tasks */}
        <div className="lg:col-span-2 bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <div className="flex items-center justify-between px-5 py-4 border-b border-gray-50">
            <div className="flex items-center gap-2.5">
              <BookOpen size={15} className="text-gray-500" />
              <h2 className="text-sm font-semibold text-gray-900">Recent Tasks</h2>
            </div>
            <Link href="/tasks" className="text-xs text-blue-600 hover:underline">View all →</Link>
          </div>
          <div className="divide-y divide-gray-50">
            {loading ? (
              Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="flex items-center gap-3 px-5 py-3">
                  <Skeleton className="h-4 w-40" />
                  <Skeleton className="h-4 w-16 ml-auto" />
                </div>
              ))
            ) : recentTasks && recentTasks.length > 0 ? (
              recentTasks.map((t) => (
                <div key={t.id} className="flex items-center justify-between px-5 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-gray-900 truncate">{t.title}</p>
                    <div className="flex items-center gap-2 mt-0.5">
                      {t.client_name && (
                        <span className="text-xs text-gray-400 truncate">{t.client_name}</span>
                      )}
                      {t.due_date && (
                        <span className="text-xs text-gray-400">
                          · Due {new Date(t.due_date + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="ml-3 shrink-0">{statusBadge(t.status)}</div>
                </div>
              ))
            ) : (
              <div className="px-5 py-8 text-center text-sm text-gray-400">No tasks yet</div>
            )}
          </div>
        </div>

        {/* Quick Actions */}
        <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <div className="flex items-center gap-2.5 px-5 py-4 border-b border-gray-50">
            <Receipt size={15} className="text-gray-500" />
            <h2 className="text-sm font-semibold text-gray-900">Quick Actions</h2>
          </div>
          <div className="p-5 space-y-3">
            {QUICK_ACTIONS.map((action) => (
              <Link key={action.label} href={action.href}>
                <button className={`w-full text-left px-4 py-2.5 rounded-lg text-sm font-medium transition-colors ${action.color}`}>
                  {action.label}
                </button>
              </Link>
            ))}

            <div className="pt-3 border-t border-gray-50">
              <p className="text-xs text-gray-400 mb-2">Shortcuts</p>
              <div className="grid grid-cols-2 gap-2">
                <Link href="/compliance">
                  <div className="flex flex-col items-center gap-1 p-3 rounded-lg bg-gray-50 hover:bg-gray-100 transition-colors cursor-pointer">
                    <FileCheck size={16} className="text-indigo-600" />
                    <span className="text-xs text-gray-600 text-center leading-tight">Compliance</span>
                  </div>
                </Link>
                <Link href="/ai-assistant">
                  <div className="flex flex-col items-center gap-1 p-3 rounded-lg bg-gray-50 hover:bg-gray-100 transition-colors cursor-pointer">
                    <Bot size={16} className="text-violet-600" />
                    <span className="text-xs text-gray-600 text-center leading-tight">AI Help</span>
                  </div>
                </Link>
                <Link href="/tasks">
                  <div className="flex flex-col items-center gap-1 p-3 rounded-lg bg-gray-50 hover:bg-gray-100 transition-colors cursor-pointer">
                    <Clock size={16} className="text-amber-600" />
                    <span className="text-xs text-gray-600 text-center leading-tight">All Tasks</span>
                  </div>
                </Link>
                <Link href="/clients">
                  <div className="flex flex-col items-center gap-1 p-3 rounded-lg bg-gray-50 hover:bg-gray-100 transition-colors cursor-pointer">
                    <Plus size={16} className="text-blue-600" />
                    <span className="text-xs text-gray-600 text-center leading-tight">New Client</span>
                  </div>
                </Link>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
