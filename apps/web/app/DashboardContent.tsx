"use client";

import { useState, useEffect } from "react";
import {
  Users, Clock, AlertTriangle, FileCheck,
  Calendar, Sparkles, CheckCircle2,
  ChevronRight,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { getSupabaseClient } from "@/lib/supabase/client";
import { useAuth } from "@/lib/auth/AuthContext";
import { cn } from "@/lib/utils";

// ─── Types ───────────────────────────────────────────────────────────────────

interface KPIs {
  totalClients: number;
  pendingTasks: number;
  filingsDueThisMonth: number;
  overdueFilings: number;
}

interface RecentClient {
  id: string;
  client_name: string;
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
  date: string;
  daysLeft: number;
}

// ─── Deadline generator ───────────────────────────────────────────────────────
// CGST Act §39 — GSTR-1 due 11th; GSTR-3B due 20th of following month
// IT Act §139 — ITR due 31st July; §208 — advance tax instalments
// CGST Act §44 — GSTR-9 annual 31st December
// IT Act §200 — TDS return 31st of month following quarter end
function getUpcomingDeadlines(today: Date): UpcomingDeadline[] {
  const year = today.getFullYear();
  const month = today.getMonth();
  const deadlines: { name: string; date: Date }[] = [];

  for (let offset = -1; offset <= 2; offset++) {
    let m = month + offset;
    let y = year;
    while (m < 0) { m += 12; y--; }
    while (m > 11) { m -= 12; y++; }
    const gstr1Month = m + 1 > 11 ? 0 : m + 1;
    const gstr1Year = m + 1 > 11 ? y + 1 : y;
    const monthLabel = new Date(y, m, 1).toLocaleString("default", { month: "short" });
    deadlines.push({ name: `GSTR-1 (${monthLabel} ${y})`, date: new Date(gstr1Year, gstr1Month, 11) });
    deadlines.push({ name: `GSTR-3B (${monthLabel} ${y})`, date: new Date(gstr1Year, gstr1Month, 20) });
  }

  const fyStart = month >= 3 ? year : year - 1;
  deadlines.push({ name: "Advance Tax — 1st (15%)", date: new Date(fyStart, 5, 15) });
  deadlines.push({ name: "Advance Tax — 2nd (45%)", date: new Date(fyStart, 8, 15) });
  deadlines.push({ name: "Advance Tax — 3rd (75%)", date: new Date(fyStart, 11, 15) });
  deadlines.push({ name: "Advance Tax — Final (100%)", date: new Date(fyStart + 1, 2, 15) });
  deadlines.push({ name: "GSTR-9 Annual Return", date: new Date(year, 11, 31) });
  const fyYear = month >= 3 ? year : year - 1;
  deadlines.push({ name: "TDS Return Q1", date: new Date(fyYear, 6, 31) });
  deadlines.push({ name: "TDS Return Q2", date: new Date(fyYear, 9, 31) });
  deadlines.push({ name: "TDS Return Q3", date: new Date(fyYear + 1, 0, 31) });
  deadlines.push({ name: "TDS Return Q4", date: new Date(fyYear + 1, 4, 31) });
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
    .slice(0, 6);
}

function getGreeting(email: string): string {
  const hour = new Date().getHours();
  const name = email.split("@")[0].replace(/[._]/g, " ").replace(/\b\w/g, c => c.toUpperCase());
  const greeting = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  return `${greeting}, ${name}`;
}

function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton-shimmer rounded-md", className)} />;
}

function DeadlineBadge({ daysLeft }: { daysLeft: number }) {
  if (daysLeft === 0) return (
    <span className="text-[11px] px-2 py-0.5 rounded-full bg-red-500/15 text-red-400 font-bold ring-1 ring-red-500/20">Today</span>
  );
  if (daysLeft <= 3) return (
    <span className="text-[11px] px-2 py-0.5 rounded-full bg-red-500/10 text-red-400 font-semibold">{daysLeft}d</span>
  );
  if (daysLeft <= 7) return (
    <span className="text-[11px] px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400 font-semibold">{daysLeft}d</span>
  );
  if (daysLeft <= 14) return (
    <span className="text-[11px] px-2 py-0.5 rounded-full bg-yellow-500/10 text-yellow-400 font-medium">{daysLeft}d</span>
  );
  return (
    <span className="text-[11px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 font-medium">{daysLeft}d</span>
  );
}

const STATUS_CONFIG: Record<string, { label: string; color: string }> = {
  completed:       { label: "Done",        color: "text-emerald-400 bg-emerald-500/10" },
  in_progress:     { label: "In Progress", color: "text-blue-400 bg-blue-500/10" },
  todo:            { label: "To Do",       color: "text-white/40 bg-white/[0.06]" },
  review_required: { label: "Review",      color: "text-amber-400 bg-amber-500/10" },
  waiting_client:  { label: "Waiting",     color: "text-purple-400 bg-purple-500/10" },
};

function StatusBadge({ status }: { status: string | null }) {
  const s = status ?? "todo";
  const cfg = STATUS_CONFIG[s] ?? STATUS_CONFIG.todo;
  return (
    <span className={cn("text-[11px] px-2 py-0.5 rounded-full font-medium", cfg.color)}>
      {cfg.label}
    </span>
  );
}

// ─── Main ─────────────────────────────────────────────────────────────────────
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
        const { data: userData } = await supabase
          .from("users").select("firm_id").eq("auth_user_id", user!.id).maybeSingle();
        const firmId: string | null = userData?.firm_id ?? null;
        if (!firmId) {
          setKpis({ totalClients: 0, pendingTasks: 0, filingsDueThisMonth: 0, overdueFilings: 0 });
          setRecentClients([]); setRecentTasks([]); setLoading(false); return;
        }

        const [{ data: firmMeta }, { count: coaCount }] = await Promise.all([
          supabase.from("firms").select("name").eq("id", firmId).maybeSingle(),
          supabase.from("chart_of_accounts").select("id", { count: "exact", head: true }).eq("firm_id", firmId),
        ]);
        if (!firmMeta?.name && (coaCount ?? 0) === 0) { router.replace("/onboarding"); return; }

        const todayStr = today.toISOString().split("T")[0];
        const monthStart = todayStr.slice(0, 7) + "-01";
        const monthEnd = new Date(today.getFullYear(), today.getMonth() + 1, 0).toISOString().split("T")[0];

        const [
          { count: totalClients },
          { count: pendingCount },
          { count: filingsDue },
          { count: overdueCount },
          { data: clientsData },
          { data: tasksRaw },
        ] = await Promise.all([
          supabase.from("clients").select("id", { count: "exact", head: true }).eq("firm_id", firmId),
          supabase.from("tasks").select("id", { count: "exact", head: true }).eq("firm_id", firmId).neq("status", "completed"),
          supabase.from("compliance_entries").select("id", { count: "exact", head: true }).eq("firm_id", firmId).gte("due_date", monthStart).lte("due_date", monthEnd).neq("status", "filed"),
          supabase.from("compliance_entries").select("id", { count: "exact", head: true }).eq("firm_id", firmId).lt("due_date", todayStr).neq("status", "filed"),
          supabase.from("clients").select("id, client_name, gstin, entity_type").eq("firm_id", firmId).order("created_at", { ascending: false }).limit(5),
          supabase.from("tasks").select("id, title, due_date, status, client_name").eq("firm_id", firmId).order("created_at", { ascending: false }).limit(6),
        ]);

        setKpis({
          totalClients: totalClients ?? 0,
          pendingTasks: pendingCount ?? 0,
          filingsDueThisMonth: filingsDue ?? 0,
          overdueFilings: overdueCount ?? 0,
        });
        setRecentClients((clientsData as RecentClient[]) ?? []);
        setRecentTasks((tasksRaw as RecentTask[]) ?? []);
      } catch {
        setKpis({ totalClients: 0, pendingTasks: 0, filingsDueThisMonth: 0, overdueFilings: 0 });
        setRecentClients([]); setRecentTasks([]);
      } finally {
        setLoading(false);
      }
    }
    load();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  const greeting = user?.email ? getGreeting(user.email) : "Good day";
  const dateLabel = today.toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric" });

  return (
    <div className="p-6 lg:p-8 max-w-7xl mx-auto space-y-6">

      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-[22px] font-semibold text-white/90 tracking-tight">{greeting}</h1>
          <p className="text-[13px] text-white/35 mt-1">{dateLabel}</p>
        </div>
        <Link href="/ai-assistant">
          <div className="hidden sm:flex items-center gap-2 bg-blue-500 hover:bg-blue-600 text-white text-[13px] font-medium px-3.5 py-2 rounded-lg shadow-[0_4px_12px_rgba(59,130,246,0.2)] transition-colors">
            <Sparkles size={14} />
            Ask AI
          </div>
        </Link>
      </div>

      {/* ── Stats Strip ─────────────────────────────────────────────────── */}
      <div className="flex items-center gap-6 py-3 px-5 bg-[#131620] rounded-xl border border-white/[0.07] flex-wrap">
        <Link href="/clients" className="flex items-center gap-2.5 group">
          <div className="w-7 h-7 rounded-lg bg-blue-500/10 flex items-center justify-center">
            <Users size={13} className="text-blue-400" />
          </div>
          {loading ? <Skeleton className="h-5 w-10" /> : (
            <div>
              <span className="text-xl font-bold text-white/85 group-hover:text-blue-400 transition-colors">{kpis?.totalClients ?? 0}</span>
              <span className="text-xs text-white/30 ml-1.5">Clients</span>
            </div>
          )}
        </Link>
        <div className="w-px h-8 bg-[#131620]/[0.06]" />
        <Link href="/work" className="flex items-center gap-2.5 group">
          <div className="w-7 h-7 rounded-lg bg-amber-500/10 flex items-center justify-center">
            <Clock size={13} className="text-amber-400" />
          </div>
          {loading ? <Skeleton className="h-5 w-10" /> : (
            <div>
              <span className="text-xl font-bold text-white/85 group-hover:text-amber-400 transition-colors">{kpis?.pendingTasks ?? 0}</span>
              <span className="text-xs text-white/30 ml-1.5">Pending Tasks</span>
            </div>
          )}
        </Link>
        <div className="w-px h-8 bg-[#131620]/[0.06]" />
        <Link href="/deadlines" className="flex items-center gap-2.5 group">
          <div className="w-7 h-7 rounded-lg bg-violet-500/10 flex items-center justify-center">
            <FileCheck size={13} className="text-violet-400" />
          </div>
          {loading ? <Skeleton className="h-5 w-10" /> : (
            <div>
              <span className="text-xl font-bold text-white/85 group-hover:text-violet-400 transition-colors">{kpis?.filingsDueThisMonth ?? 0}</span>
              <span className="text-xs text-white/30 ml-1.5">Filings This Month</span>
            </div>
          )}
        </Link>
        <div className="w-px h-8 bg-[#131620]/[0.06]" />
        <Link href="/deadlines" className="flex items-center gap-2.5 group">
          <div className={cn("w-7 h-7 rounded-lg flex items-center justify-center", (kpis?.overdueFilings ?? 0) > 0 ? "bg-red-500/10" : "bg-[#131620]/[0.04]")}>
            <AlertTriangle size={13} className={(kpis?.overdueFilings ?? 0) > 0 ? "text-red-400" : "text-white/25"} />
          </div>
          {loading ? <Skeleton className="h-5 w-10" /> : (
            <div>
              <span className={cn("text-xl font-bold transition-colors", (kpis?.overdueFilings ?? 0) > 0 ? "text-red-400" : "text-white/85")}>{kpis?.overdueFilings ?? 0}</span>
              <span className="text-xs text-white/30 ml-1.5">Overdue</span>
            </div>
          )}
        </Link>
      </div>

      {/* ── Three-column Briefing Grid ──────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">

        {/* Column 1: Upcoming Deadlines */}
        <div className="bg-[#131620] rounded-xl border border-white/[0.07] overflow-hidden">
          <div className="flex items-center justify-between px-5 py-4 border-b border-white/[0.05]">
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded-lg bg-amber-500/10 flex items-center justify-center">
                <Calendar size={14} className="text-amber-400" />
              </div>
              <h2 className="text-[13px] font-semibold text-white/80">Upcoming Deadlines</h2>
            </div>
            <Link href="/deadlines" className="text-[12px] text-blue-400 hover:text-blue-300 font-medium flex items-center gap-1 transition-colors">
              View all <ChevronRight size={12} />
            </Link>
          </div>
          <div className="divide-y divide-white/[0.04]">
            {upcomingDeadlines.map((d) => (
              <Link key={d.name + d.date} href="/deadlines">
                <div className="flex items-center justify-between px-5 py-3.5 hover:bg-[#131620]/[0.025] transition-colors">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className={cn(
                      "w-1.5 h-1.5 rounded-full shrink-0",
                      d.daysLeft === 0 ? "bg-red-400" :
                      d.daysLeft <= 3 ? "bg-red-400" :
                      d.daysLeft <= 7 ? "bg-amber-400" :
                      "bg-emerald-400"
                    )} />
                    <div className="min-w-0">
                      <p className="text-[13px] text-white/75 font-medium truncate">{d.name}</p>
                      <p className="text-[11px] text-white/30 mt-0.5">
                        {new Date(d.date + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
                      </p>
                    </div>
                  </div>
                  <DeadlineBadge daysLeft={d.daysLeft} />
                </div>
              </Link>
            ))}
          </div>
        </div>

        {/* Column 2: Recent Clients */}
        <div className="bg-[#131620] rounded-xl border border-white/[0.07] overflow-hidden">
          <div className="flex items-center justify-between px-5 py-4 border-b border-white/[0.05]">
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded-lg bg-blue-500/10 flex items-center justify-center">
                <Users size={14} className="text-blue-400" />
              </div>
              <h2 className="text-[13px] font-semibold text-white/80">Recent Clients</h2>
            </div>
            <Link href="/clients" className="text-[12px] text-blue-400 hover:text-blue-300 font-medium flex items-center gap-1 transition-colors">
              View all <ChevronRight size={12} />
            </Link>
          </div>
          <div className="divide-y divide-white/[0.04]">
            {loading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="flex items-center gap-3 px-5 py-3.5">
                  <Skeleton className="h-8 w-8 rounded-full" />
                  <div className="flex-1 space-y-1.5">
                    <Skeleton className="h-3.5 w-36" />
                    <Skeleton className="h-3 w-24" />
                  </div>
                </div>
              ))
            ) : recentClients && recentClients.length > 0 ? (
              recentClients.map((c) => (
                <Link key={c.id} href={`/clients/${c.id}`}>
                  <div className="flex items-center gap-3 px-5 py-3.5 hover:bg-[#131620]/[0.025] transition-colors">
                    <div className="w-8 h-8 rounded-full bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400 text-[11px] font-bold shrink-0">
                      {c.client_name.slice(0, 2).toUpperCase()}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-[13px] font-semibold text-white/80 truncate">{c.client_name}</p>
                      {c.gstin && <p className="text-[11px] text-white/30 font-mono">{c.gstin}</p>}
                    </div>
                    {c.entity_type && (
                      <span className="text-[11px] px-2 py-0.5 rounded-full bg-[#131620]/[0.06] text-white/40 font-medium shrink-0">
                        {c.entity_type}
                      </span>
                    )}
                  </div>
                </Link>
              ))
            ) : (
              <div className="px-5 py-10 text-center">
                <Users size={24} className="text-white/10 mx-auto mb-2" />
                <p className="text-[13px] text-white/35">No clients yet</p>
                <Link href="/clients" className="text-[12px] text-blue-400 font-medium mt-1 inline-block">Add your first client →</Link>
              </div>
            )}
          </div>
        </div>

        {/* Column 3: Pending Tasks */}
        <div className="bg-[#131620] rounded-xl border border-white/[0.07] overflow-hidden">
          <div className="flex items-center justify-between px-5 py-4 border-b border-white/[0.05]">
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded-lg bg-amber-500/10 flex items-center justify-center">
                <Clock size={14} className="text-amber-400" />
              </div>
              <h2 className="text-[13px] font-semibold text-white/80">Pending Tasks</h2>
            </div>
            <Link href="/work" className="text-[12px] text-blue-400 hover:text-blue-300 font-medium flex items-center gap-1 transition-colors">
              View all <ChevronRight size={12} />
            </Link>
          </div>
          <div className="divide-y divide-white/[0.04]">
            {loading ? (
              Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="flex items-center gap-3 px-5 py-3.5">
                  <Skeleton className="h-4 w-4 rounded-full" />
                  <div className="flex-1 space-y-1.5">
                    <Skeleton className="h-3.5 w-48" />
                    <Skeleton className="h-3 w-28" />
                  </div>
                  <Skeleton className="h-5 w-16 rounded-full" />
                </div>
              ))
            ) : recentTasks && recentTasks.length > 0 ? (
              recentTasks.filter(t => t.status !== "completed").map((t) => (
                <div key={t.id} className="flex items-center gap-3 px-5 py-3.5 hover:bg-[#131620]/[0.025] transition-colors">
                  <div className={cn(
                    "w-1.5 h-1.5 rounded-full shrink-0 mt-0.5",
                    t.status === "in_progress" ? "bg-blue-400" :
                    t.status === "review_required" ? "bg-amber-400" :
                    t.status === "waiting_client" ? "bg-purple-400" :
                    "bg-white/20"
                  )} />
                  <div className="min-w-0 flex-1">
                    <p className="text-[13px] font-medium text-white/75 truncate">{t.title}</p>
                    <div className="flex items-center gap-1.5 mt-0.5">
                      {t.client_name && <span className="text-[11px] text-white/30 truncate">{t.client_name}</span>}
                      {t.due_date && (
                        <span className="text-[11px] text-white/25">
                          · {new Date(t.due_date + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short" })}
                        </span>
                      )}
                    </div>
                  </div>
                  <StatusBadge status={t.status} />
                </div>
              ))
            ) : (
              <div className="px-5 py-10 text-center">
                <CheckCircle2 size={24} className="text-white/10 mx-auto mb-2" />
                <p className="text-[13px] text-white/35">All caught up</p>
                <Link href="/work" className="text-[12px] text-blue-400 font-medium mt-1 inline-block">View work queue →</Link>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
