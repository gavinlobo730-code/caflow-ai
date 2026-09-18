"use client";

import { useState, useEffect, useCallback } from "react";
import {
  CheckSquare, Clock, AlertTriangle, CheckCircle2,
  Calendar, Loader2, AlertCircle, ExternalLink, Activity, InboxIcon,
} from "lucide-react";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getTasks, getTaskCounts } from "@/lib/data/tasks";
import { getTeamWorkload } from "@/lib/data/analytics";
import { getUserProfile } from "@/lib/data/getFirmId";
import type { Task, TaskStatus, TeamWorkload } from "@/lib/types";
import type { TaskCounts } from "@/lib/data/tasks";
import { todayLocalISO, daysBetweenLocalISO } from "@/lib/dateMath";

const STATUS_COLORS: Record<TaskStatus, string> = {
  todo: "bg-ps-muted text-ps-label",
  in_progress: "bg-blue-100 text-blue-700",
  waiting_client: "bg-purple-100 text-purple-700",
  review_required: "bg-amber-100 text-amber-700",
  completed: "bg-green-100 text-green-700",
};

const STATUS_LABEL: Record<TaskStatus, string> = {
  todo: "To Do",
  in_progress: "In Progress",
  waiting_client: "Waiting Client",
  review_required: "Review",
  completed: "Completed",
};

const PRIORITY_COLORS: Record<string, string> = {
  critical: "bg-red-100 text-red-700",
  high: "bg-amber-100 text-amber-700",
  medium: "bg-blue-100 text-blue-700",
  low: "bg-ps-muted text-ps-label",
};

function fmt(date?: string) {
  if (!date) return "—";
  const [, m, d] = date.split("-");
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return `${d} ${months[parseInt(m) - 1]}`;
}

function isToday(dateStr?: string) {
  if (!dateStr) return false;
  return dateStr === todayLocalISO();
}

function isThisWeek(dateStr?: string) {
  if (!dateStr) return false;
  const diff = daysBetweenLocalISO(todayLocalISO(), dateStr);
  return diff !== null && diff >= 0 && diff <= 7;
}

function isOverdue(dateStr?: string) {
  if (!dateStr) return false;
  return dateStr < todayLocalISO();
}

function TaskRow({ task }: { task: Task }) {
  return (
    <div className="flex items-center gap-3 px-4 py-2.5 hover:bg-ps-bg rounded-lg transition-colors">
      <Badge className={`text-3xs px-1.5 py-0 shrink-0 ${STATUS_COLORS[task.status]}`}>
        {STATUS_LABEL[task.status]}
      </Badge>
      <div className="flex-1 min-w-0">
        <p className="text-sm text-ps-ink truncate font-medium">{task.title}</p>
        {task.client_name && (
          <p className="text-2xs text-ps-hint truncate">{task.client_name}</p>
        )}
      </div>
      <div className="shrink-0 text-right">
        {task.priority && (
          <Badge className={`text-3xs px-1.5 py-0 ${PRIORITY_COLORS[task.priority]}`}>
            {task.priority}
          </Badge>
        )}
        {task.due_date && (
          <p className={`text-2xs mt-0.5 ${isOverdue(task.due_date) ? "text-red-500 font-medium" : "text-ps-hint"}`}>
            {fmt(task.due_date)}
          </p>
        )}
      </div>
    </div>
  );
}

export default function WorkPage() {
  const [counts, setCounts] = useState<TaskCounts | null>(null);
  const [activeTasks, setActiveTasks] = useState<Task[]>([]);
  const [recentDone, setRecentDone] = useState<Task[]>([]);
  const [workload, setWorkload] = useState<TeamWorkload | null>(null);
  const [loadingTasks, setLoadingTasks] = useState(true);
  const [loadingWorkload, setLoadingWorkload] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isManager, setIsManager] = useState(false);

  const load = useCallback(async () => {
    setLoadingTasks(true);
    setLoadingWorkload(true);
    setError(null);

    const t0 = Date.now();

    // Workload fires immediately — runs in parallel, may 403 for non-managers.
    const workloadPromise = getTeamWorkload()
      .then((wl) => { setWorkload(wl); setIsManager(true); })
      .catch(() => { setIsManager(false); })
      .finally(() => setLoadingWorkload(false));

    try {
      const { authUserId, userId } = await getUserProfile();

      // Three server-side queries in parallel: aggregate counts + active tasks + recently done.
      const [taskCounts, active, done] = await Promise.all([
        getTaskCounts(authUserId, userId),
        getTasks({ assignedTo: authUserId, assigneeId: userId, excludeStatus: "completed", limit: 50 }),
        getTasks({ assignedTo: authUserId, assigneeId: userId, status: "completed", limit: 5 }),
      ]);

      setCounts(taskCounts);
      setActiveTasks(active);
      setRecentDone(done);

      if (process.env.NODE_ENV === "development") {
        // eslint-disable-next-line no-console
        console.debug(`[PracticeSync/work-page] total load: ${Date.now() - t0}ms`);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load tasks");
    } finally {
      setLoadingTasks(false);
      void workloadPromise;
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Client-side splits of the 50-row active window for the display sections.
  const todayTasks = activeTasks.filter(t => isToday(t.due_date));
  const thisWeekTasks = activeTasks.filter(t => !isToday(t.due_date) && isThisWeek(t.due_date));
  const overdueTasks = activeTasks.filter(t => isOverdue(t.due_date));

  const isEmpty = !loadingTasks && counts !== null && counts.active === 0;

  return (
    <div className="p-6 space-y-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-ps-ink">My Work</h1>
          <p className="text-sm text-ps-label mt-0.5">Your personal task view</p>
        </div>
        <Link href="/tasks">
          <Button variant="outline" size="sm" className="gap-1.5 text-xs">
            <ExternalLink size={12} /> All Tasks
          </Button>
        </Link>
      </div>

      {error && (
        <div className="flex items-center gap-2 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
          <AlertCircle size={14} /> {error}
        </div>
      )}

      {loadingTasks ? (
        <div className="flex items-center justify-center py-20 text-ps-hint">
          <Loader2 className="animate-spin mr-2" size={18} /> Loading your work…
        </div>
      ) : isEmpty ? (
        <div className="flex flex-col items-center justify-center py-20 gap-3 text-center">
          <div className="w-12 h-12 rounded-full bg-ps-muted flex items-center justify-center">
            <InboxIcon size={20} className="text-ps-hint" />
          </div>
          <div>
            <p className="text-[14px] font-medium text-ps-body">No tasks assigned to you</p>
            <p className="text-[12px] text-ps-hint mt-1">Tasks assigned to you will appear here.</p>
          </div>
          <Link href="/tasks">
            <Button variant="outline" size="sm" className="gap-1.5 text-xs mt-1">
              <ExternalLink size={12} /> Browse All Tasks
            </Button>
          </Link>
        </div>
      ) : (
        <>
          {/* Stat cards — sourced from COUNT(*) queries, accurate even beyond the 50-row fetch window */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Card>
              <CardContent className="py-4">
                <div className="flex items-center gap-1.5 text-xs text-ps-label mb-1">
                  <CheckSquare size={11} /> My Tasks
                </div>
                <p className="text-2xl font-bold text-ps-ink">{counts?.active ?? 0}</p>
                <p className="text-2xs text-ps-hint">active</p>
              </CardContent>
            </Card>
            <Card className={(counts?.due_today ?? 0) > 0 ? "border-amber-200 bg-amber-50/30" : ""}>
              <CardContent className="py-4">
                <div className="flex items-center gap-1.5 text-xs text-ps-label mb-1">
                  <Clock size={11} /> Due Today
                </div>
                <p className={`text-2xl font-bold ${(counts?.due_today ?? 0) > 0 ? "text-amber-700" : "text-ps-ink"}`}>
                  {counts?.due_today ?? 0}
                </p>
                <p className="text-2xs text-ps-hint">tasks</p>
              </CardContent>
            </Card>
            <Card className={(counts?.overdue ?? 0) > 0 ? "border-red-200 bg-red-50/20" : ""}>
              <CardContent className="py-4">
                <div className="flex items-center gap-1.5 text-xs text-ps-label mb-1">
                  <AlertTriangle size={11} /> Overdue
                </div>
                <p className={`text-2xl font-bold ${(counts?.overdue ?? 0) > 0 ? "text-red-600" : "text-ps-ink"}`}>
                  {counts?.overdue ?? 0}
                </p>
                <p className="text-2xs text-ps-hint">tasks</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="py-4">
                <div className="flex items-center gap-1.5 text-xs text-ps-label mb-1">
                  <CheckCircle2 size={11} /> Done
                </div>
                <p className="text-2xl font-bold text-green-600">{counts?.completed_recent ?? 0}</p>
                <p className="text-2xs text-ps-hint">last 7 days</p>
              </CardContent>
            </Card>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {/* Due Today */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-1.5">
                  <Clock size={13} className="text-amber-500" /> Due Today
                  {todayTasks.length > 0 && (
                    <Badge className="ml-1 text-3xs px-1.5 py-0 bg-amber-100 text-amber-700">{todayTasks.length}</Badge>
                  )}
                </CardTitle>
              </CardHeader>
              <CardContent className="px-2">
                {todayTasks.length === 0 ? (
                  <p className="text-sm text-ps-hint text-center py-4">Nothing due today</p>
                ) : (
                  todayTasks.map(t => <TaskRow key={t.id} task={t} />)
                )}
              </CardContent>
            </Card>

            {/* Overdue */}
            <Card className={overdueTasks.length > 0 ? "border-red-100" : ""}>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-1.5">
                  <AlertTriangle size={13} className="text-red-500" /> Overdue
                  {overdueTasks.length > 0 && (
                    <Badge className="ml-1 text-3xs px-1.5 py-0 bg-red-100 text-red-700">{overdueTasks.length}</Badge>
                  )}
                </CardTitle>
              </CardHeader>
              <CardContent className="px-2">
                {overdueTasks.length === 0 ? (
                  <p className="text-sm text-ps-hint text-center py-4">No overdue tasks</p>
                ) : (
                  overdueTasks.map(t => <TaskRow key={t.id} task={t} />)
                )}
              </CardContent>
            </Card>

            {/* Due This Week */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-1.5">
                  <Calendar size={13} className="text-blue-600" /> Due This Week
                  {thisWeekTasks.length > 0 && (
                    <Badge className="ml-1 text-3xs px-1.5 py-0 bg-blue-50 text-blue-600">{thisWeekTasks.length}</Badge>
                  )}
                </CardTitle>
              </CardHeader>
              <CardContent className="px-2">
                {thisWeekTasks.length === 0 ? (
                  <p className="text-sm text-ps-hint text-center py-4">Nothing else due this week</p>
                ) : (
                  thisWeekTasks.slice(0, 8).map(t => <TaskRow key={t.id} task={t} />)
                )}
              </CardContent>
            </Card>

            {/* Recently Completed */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-1.5">
                  <CheckCircle2 size={13} className="text-green-500" /> Recently Completed
                </CardTitle>
              </CardHeader>
              <CardContent className="px-2">
                {recentDone.length === 0 ? (
                  <p className="text-sm text-ps-hint text-center py-4">No completed tasks yet</p>
                ) : (
                  recentDone.map(t => <TaskRow key={t.id} task={t} />)
                )}
              </CardContent>
            </Card>
          </div>

          {/* Team Overview — managers only; independent loading state */}
          {loadingWorkload ? null : isManager && workload ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-ps-body flex items-center gap-1.5">
                  <Activity size={13} /> Team Overview
                </h2>
                <Link href="/team/workload">
                  <Button variant="ghost" size="sm" className="text-xs gap-1.5">
                    Full Workload <ExternalLink size={11} />
                  </Button>
                </Link>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <Card>
                  <CardContent className="py-3">
                    <p className="text-xs text-ps-label">Team Members</p>
                    <p className="text-xl font-bold text-ps-ink mt-0.5">{workload.members.length}</p>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="py-3">
                    <p className="text-xs text-ps-label">Active Tasks</p>
                    <p className="text-xl font-bold text-ps-ink mt-0.5">{workload.total_active_tasks}</p>
                  </CardContent>
                </Card>
                <Card className={workload.overloaded_count > 0 ? "border-red-100" : ""}>
                  <CardContent className="py-3">
                    <p className="text-xs text-ps-label">Overloaded</p>
                    <p className={`text-xl font-bold mt-0.5 ${workload.overloaded_count > 0 ? "text-red-600" : "text-ps-ink"}`}>
                      {workload.overloaded_count}
                    </p>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="py-3">
                    <p className="text-xs text-ps-label">Avg Utilisation</p>
                    <p className="text-xl font-bold text-ps-ink mt-0.5">{workload.avg_utilisation_pct}%</p>
                  </CardContent>
                </Card>
              </div>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
