"use client";

import { useState, useEffect, useCallback } from "react";
import {
  CheckSquare, Clock, AlertTriangle, CheckCircle2,
  Calendar, Loader2, AlertCircle, ExternalLink, Activity,
} from "lucide-react";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getTasks } from "@/lib/data/tasks";
import { getClients } from "@/lib/data/clients";
import { getTeamWorkload } from "@/lib/data/analytics";
import { getSupabaseClient } from "@/lib/supabase/client";
import type { Task, TaskStatus, Client, TeamWorkload } from "@/lib/types";

const STATUS_COLORS: Record<TaskStatus, string> = {
  todo: "bg-gray-100 text-gray-600",
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
  low: "bg-gray-100 text-gray-500",
};

function fmt(date?: string) {
  if (!date) return "—";
  const [, m, d] = date.split("-");
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return `${d} ${months[parseInt(m) - 1]}`;
}

function isToday(dateStr?: string) {
  if (!dateStr) return false;
  const today = new Date();
  const d = new Date(dateStr);
  return d.toDateString() === today.toDateString();
}

function isThisWeek(dateStr?: string) {
  if (!dateStr) return false;
  const d = new Date(dateStr);
  const now = new Date();
  const weekEnd = new Date(now);
  weekEnd.setDate(weekEnd.getDate() + 7);
  return d >= now && d <= weekEnd;
}

function isOverdue(dateStr?: string) {
  if (!dateStr) return false;
  return new Date(dateStr) < new Date(new Date().toDateString());
}

function TaskRow({ task }: { task: Task }) {
  return (
    <div className="flex items-center gap-3 px-4 py-2.5 hover:bg-gray-50 rounded-lg transition-colors">
      <Badge className={`text-[10px] px-1.5 py-0 shrink-0 ${STATUS_COLORS[task.status]}`}>
        {STATUS_LABEL[task.status]}
      </Badge>
      <div className="flex-1 min-w-0">
        <p className="text-sm text-gray-800 truncate font-medium">{task.title}</p>
        {task.client_name && (
          <p className="text-[11px] text-gray-400 truncate">{task.client_name}</p>
        )}
      </div>
      <div className="shrink-0 text-right">
        {task.priority && (
          <Badge className={`text-[10px] px-1.5 py-0 ${PRIORITY_COLORS[task.priority]}`}>
            {task.priority}
          </Badge>
        )}
        {task.due_date && (
          <p className={`text-[11px] mt-0.5 ${isOverdue(task.due_date) ? "text-red-500 font-medium" : "text-gray-400"}`}>
            {fmt(task.due_date)}
          </p>
        )}
      </div>
    </div>
  );
}

export default function WorkPage() {
  const [myTasks, setMyTasks] = useState<Task[]>([]);
  const [workload, setWorkload] = useState<TeamWorkload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isManager, setIsManager] = useState(false);
  const [, setUserId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data: { session } } = await getSupabaseClient().auth.getSession();
      const uid = session?.user?.id ?? null;
      setUserId(uid);

      const [taskList, clientList] = await Promise.all([
        getTasks(),
        getClients().catch(() => [] as Client[]),
      ]);

      const clientMap = new Map(clientList.map(c => [c.id, c.client_name]));
      const enriched = taskList.map(t => ({
        ...t,
        client_name: clientMap.get(t.client_id) ?? t.client_name,
      }));

      // Filter to user's tasks (by assigned_to matching session user id or email)
      const mine = enriched.filter(t =>
        t.assigned_to === uid ||
        t.assigned_to === session?.user?.email ||
        t.assigned_to === session?.user?.user_metadata?.full_name
      );
      setMyTasks(mine.length > 0 ? mine : enriched.slice(0, 20));

      // Try to load workload for managers
      try {
        const wl = await getTeamWorkload();
        setWorkload(wl);
        setIsManager(true);
      } catch {
        setIsManager(false);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load tasks");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const today = myTasks.filter(t => t.status !== "completed" && isToday(t.due_date));
  const thisWeek = myTasks.filter(t => t.status !== "completed" && !isToday(t.due_date) && isThisWeek(t.due_date));
  const overdue = myTasks.filter(t => t.status !== "completed" && isOverdue(t.due_date));
  const recentDone = myTasks.filter(t => t.status === "completed").slice(0, 5);
  const active = myTasks.filter(t => t.status !== "completed");

  return (
    <div className="p-6 space-y-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">My Work</h1>
          <p className="text-sm text-gray-500 mt-0.5">Your personal task view</p>
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

      {loading ? (
        <div className="flex items-center justify-center py-20 text-gray-400">
          <Loader2 className="animate-spin mr-2" size={18} /> Loading your work…
        </div>
      ) : (
        <>
          {/* Workload summary */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Card>
              <CardContent className="py-4">
                <div className="flex items-center gap-1.5 text-xs text-gray-500 mb-1">
                  <CheckSquare size={11} /> My Tasks
                </div>
                <p className="text-2xl font-bold text-gray-900">{active.length}</p>
                <p className="text-[11px] text-gray-400">active</p>
              </CardContent>
            </Card>
            <Card className={today.length > 0 ? "border-amber-200 bg-amber-50/30" : ""}>
              <CardContent className="py-4">
                <div className="flex items-center gap-1.5 text-xs text-gray-500 mb-1">
                  <Clock size={11} /> Due Today
                </div>
                <p className={`text-2xl font-bold ${today.length > 0 ? "text-amber-700" : "text-gray-900"}`}>
                  {today.length}
                </p>
                <p className="text-[11px] text-gray-400">tasks</p>
              </CardContent>
            </Card>
            <Card className={overdue.length > 0 ? "border-red-200 bg-red-50/20" : ""}>
              <CardContent className="py-4">
                <div className="flex items-center gap-1.5 text-xs text-gray-500 mb-1">
                  <AlertTriangle size={11} /> Overdue
                </div>
                <p className={`text-2xl font-bold ${overdue.length > 0 ? "text-red-600" : "text-gray-900"}`}>
                  {overdue.length}
                </p>
                <p className="text-[11px] text-gray-400">tasks</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="py-4">
                <div className="flex items-center gap-1.5 text-xs text-gray-500 mb-1">
                  <CheckCircle2 size={11} /> Done
                </div>
                <p className="text-2xl font-bold text-green-600">{recentDone.length}</p>
                <p className="text-[11px] text-gray-400">recent</p>
              </CardContent>
            </Card>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {/* Due Today */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-1.5">
                  <Clock size={13} className="text-amber-500" /> Due Today
                  {today.length > 0 && (
                    <Badge className="ml-1 text-[10px] px-1.5 py-0 bg-amber-100 text-amber-700">{today.length}</Badge>
                  )}
                </CardTitle>
              </CardHeader>
              <CardContent className="px-2">
                {today.length === 0 ? (
                  <p className="text-sm text-gray-400 text-center py-4">Nothing due today</p>
                ) : (
                  today.map(t => <TaskRow key={t.id} task={t} />)
                )}
              </CardContent>
            </Card>

            {/* Overdue */}
            <Card className={overdue.length > 0 ? "border-red-100" : ""}>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-1.5">
                  <AlertTriangle size={13} className="text-red-500" /> Overdue
                  {overdue.length > 0 && (
                    <Badge className="ml-1 text-[10px] px-1.5 py-0 bg-red-100 text-red-700">{overdue.length}</Badge>
                  )}
                </CardTitle>
              </CardHeader>
              <CardContent className="px-2">
                {overdue.length === 0 ? (
                  <p className="text-sm text-gray-400 text-center py-4">No overdue tasks</p>
                ) : (
                  overdue.map(t => <TaskRow key={t.id} task={t} />)
                )}
              </CardContent>
            </Card>

            {/* Due This Week */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-1.5">
                  <Calendar size={13} className="text-indigo-500" /> Due This Week
                  {thisWeek.length > 0 && (
                    <Badge className="ml-1 text-[10px] px-1.5 py-0 bg-indigo-100 text-indigo-700">{thisWeek.length}</Badge>
                  )}
                </CardTitle>
              </CardHeader>
              <CardContent className="px-2">
                {thisWeek.length === 0 ? (
                  <p className="text-sm text-gray-400 text-center py-4">Nothing else due this week</p>
                ) : (
                  thisWeek.slice(0, 8).map(t => <TaskRow key={t.id} task={t} />)
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
                  <p className="text-sm text-gray-400 text-center py-4">No completed tasks yet</p>
                ) : (
                  recentDone.map(t => <TaskRow key={t.id} task={t} />)
                )}
              </CardContent>
            </Card>
          </div>

          {/* Team Overview — managers only */}
          {isManager && workload && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-gray-700 flex items-center gap-1.5">
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
                    <p className="text-xs text-gray-500">Team Members</p>
                    <p className="text-xl font-bold text-gray-900 mt-0.5">{workload.members.length}</p>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="py-3">
                    <p className="text-xs text-gray-500">Active Tasks</p>
                    <p className="text-xl font-bold text-gray-900 mt-0.5">{workload.total_active_tasks}</p>
                  </CardContent>
                </Card>
                <Card className={workload.overloaded_count > 0 ? "border-red-100" : ""}>
                  <CardContent className="py-3">
                    <p className="text-xs text-gray-500">Overloaded</p>
                    <p className={`text-xl font-bold mt-0.5 ${workload.overloaded_count > 0 ? "text-red-600" : "text-gray-900"}`}>
                      {workload.overloaded_count}
                    </p>
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="py-3">
                    <p className="text-xs text-gray-500">Avg Utilisation</p>
                    <p className="text-xl font-bold text-gray-900 mt-0.5">{workload.avg_utilisation_pct}%</p>
                  </CardContent>
                </Card>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
