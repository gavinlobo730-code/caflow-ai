"use client";

import { useState, useEffect, useCallback } from "react";
import { CheckSquare, Clock, AlertTriangle, ExternalLink } from "lucide-react";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import Link from "next/link";
import { getTasks } from "@/lib/data/tasks";
import { getClients } from "@/lib/data/clients";
import type { Task, TaskStatus, Client } from "@/lib/types";

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
  review_required: "Review Required",
  completed: "Completed",
};

function fmt(date?: string) {
  if (!date) return "—";
  const [y, m, d] = date.split("-");
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return `${d} ${months[parseInt(m) - 1]} ${y}`;
}

export default function WorkPage() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<"all" | TaskStatus>("all");
  const [clientSearch, setClientSearch] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [taskList, clientList] = await Promise.all([
        getTasks(),
        getClients().catch(() => [] as Client[]),
      ]);
      const clientMap = new Map(clientList.map(c => [c.id, c.client_name]));
      const enriched = taskList.map(t => ({
        ...t,
        client_name: clientMap.get(t.client_id) ?? t.client_name,
      }));
      setTasks(enriched);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load work items");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const today = new Date().toISOString().split("T")[0];

  const stats = {
    open: tasks.filter(t => t.status !== "completed").length,
    dueToday: tasks.filter(t => t.due_date === today && t.status !== "completed").length,
    overdue: tasks.filter(t => t.due_date && t.due_date < today && t.status !== "completed").length,
    inProgress: tasks.filter(t => t.status === "in_progress").length,
  };

  const filtered = tasks.filter(t => {
    if (statusFilter !== "all" && t.status !== statusFilter) return false;
    if (clientSearch) {
      const name = (t.client_name ?? "").toLowerCase();
      if (!name.includes(clientSearch.toLowerCase())) return false;
    }
    return true;
  });

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">Work</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Firm-wide work queue — all tasks across all clients
        </p>
      </div>

      <div className="flex items-center gap-6 py-3 px-4 bg-white rounded-xl border border-gray-100">
        <div className="flex items-center gap-2">
          <span className="text-2xl font-bold text-gray-900">{stats.open}</span>
          <span className="text-xs text-gray-500">Open</span>
        </div>
        <div className="w-px h-8 bg-gray-100" />
        <div className="flex items-center gap-2">
          <span className={`text-2xl font-bold ${stats.dueToday > 0 ? "text-amber-600" : "text-gray-900"}`}>{stats.dueToday}</span>
          <span className="text-xs text-gray-500">Due Today</span>
        </div>
        <div className="w-px h-8 bg-gray-100" />
        <div className="flex items-center gap-2">
          <span className={`text-2xl font-bold ${stats.overdue > 0 ? "text-red-600" : "text-gray-900"}`}>{stats.overdue}</span>
          <span className="text-xs text-gray-500">Overdue</span>
        </div>
        <div className="w-px h-8 bg-gray-100" />
        <div className="flex items-center gap-2">
          <span className="text-2xl font-bold text-blue-600">{stats.inProgress}</span>
          <span className="text-xs text-gray-500">In Progress</span>
        </div>
      </div>

      <div className="flex flex-wrap gap-3">
        <div>
          <label className="text-xs text-gray-500">Status</label>
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value as "all" | TaskStatus)}
            className="block mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="all">All statuses</option>
            {(Object.keys(STATUS_LABEL) as TaskStatus[]).map(s => (
              <option key={s} value={s}>{STATUS_LABEL[s]}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-500">Client</label>
          <input
            value={clientSearch}
            onChange={e => setClientSearch(e.target.value)}
            placeholder="Search client…"
            className="block mt-1 px-3 py-1.5 text-sm border border-gray-200 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 w-48"
          />
        </div>
      </div>

      {error && (
        <div className="bg-red-50 text-red-700 rounded-lg px-4 py-3 text-sm">
          {error} — <button onClick={load} className="underline">retry</button>
        </div>
      )}

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">{filtered.length} work items</CardTitle>
        </CardHeader>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 text-xs text-gray-400">
                <th className="px-5 py-3 text-left font-semibold">Task</th>
                <th className="px-3 py-3 text-left font-semibold">Client</th>
                <th className="px-3 py-3 text-left font-semibold">Status</th>
                <th className="px-3 py-3 text-left font-semibold">Due Date</th>
                <th className="px-5 py-3 text-left font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {loading && (
                [...Array(5)].map((_, i) => (
                  <tr key={i}>
                    {[...Array(5)].map((__, j) => (
                      <td key={j} className="px-3 py-3">
                        <div className="h-4 bg-gray-100 rounded animate-pulse" />
                      </td>
                    ))}
                  </tr>
                ))
              )}
              {!loading && filtered.length === 0 && (
                <tr>
                  <td colSpan={5} className="text-center py-12">
                    <CheckSquare className="w-8 h-8 mx-auto mb-2 text-gray-200" />
                    <p className="text-sm text-gray-400">No work items found</p>
                    <p className="text-xs text-gray-300 mt-1">Tasks from all clients will appear here</p>
                  </td>
                </tr>
              )}
              {!loading && filtered.map(task => {
                const overdue = task.due_date && task.due_date < today && task.status !== "completed";
                return (
                  <tr key={task.id} className="hover:bg-gray-50">
                    <td className="px-5 py-3">
                      <p className="text-sm font-medium text-gray-900">{task.title}</p>
                      {task.description && (
                        <p className="text-xs text-gray-400 mt-0.5 truncate max-w-xs">{task.description}</p>
                      )}
                    </td>
                    <td className="px-3 py-3 text-sm text-gray-600">
                      {task.client_name ?? "—"}
                    </td>
                    <td className="px-3 py-3">
                      <Badge className={`text-xs ${STATUS_COLORS[task.status]}`}>
                        {STATUS_LABEL[task.status]}
                      </Badge>
                    </td>
                    <td className="px-3 py-3">
                      {task.due_date ? (
                        <span className={`text-xs flex items-center gap-1 ${overdue ? "text-red-600 font-medium" : "text-gray-500"}`}>
                          {overdue ? <AlertTriangle size={11} /> : <Clock size={11} />}
                          {fmt(task.due_date)}
                        </span>
                      ) : (
                        <span className="text-xs text-gray-300">—</span>
                      )}
                    </td>
                    <td className="px-5 py-3">
                      {task.client_id && (
                        <Link
                          href={`/clients/${task.client_id}`}
                          className="text-xs text-indigo-600 hover:underline flex items-center gap-1"
                        >
                          <ExternalLink size={11} /> Open Client
                        </Link>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
