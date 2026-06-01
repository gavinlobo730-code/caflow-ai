"use client";

import { useEffect, useState, useCallback } from "react";
import { Plus, Clock, AlertTriangle, RefreshCw, Trash2 } from "lucide-react";
import type { Task, TaskStatus, KanbanBoard } from "@/lib/types";
import type { Client } from "@/lib/types";
import { TaskFormModal } from "@/components/TaskFormModal";
import { getTasks, updateTaskStatus, deleteTask, groupByStatus } from "@/lib/data/tasks";
import { getClients } from "@/lib/data/clients";

const COLUMNS: { key: TaskStatus; label: string; color: string; headerColor: string }[] = [
  { key: "todo",            label: "To Do",           color: "bg-gray-50 border-gray-200",     headerColor: "bg-gray-100 text-gray-700" },
  { key: "in_progress",     label: "In Progress",     color: "bg-blue-50 border-blue-200",     headerColor: "bg-blue-100 text-blue-700" },
  { key: "waiting_client",  label: "Waiting Client",  color: "bg-purple-50 border-purple-200", headerColor: "bg-purple-100 text-purple-700" },
  { key: "review_required", label: "Review Required", color: "bg-amber-50 border-amber-200",   headerColor: "bg-amber-100 text-amber-700" },
  { key: "completed",       label: "Completed",       color: "bg-green-50 border-green-200",   headerColor: "bg-green-100 text-green-700" },
];

const PRIORITY_COLOR: Record<string, string> = {
  critical: "bg-red-100 text-red-700",
  high:     "bg-orange-100 text-orange-700",
  medium:   "bg-amber-100 text-amber-700",
  low:      "bg-gray-100 text-gray-600",
};

const NEXT_STATUS: Partial<Record<TaskStatus, { status: TaskStatus; label: string; color: string }>> = {
  todo:            { status: "in_progress",     label: "→ Start",    color: "bg-blue-50 text-blue-600 hover:bg-blue-100" },
  in_progress:     { status: "waiting_client",  label: "→ Waiting",  color: "bg-purple-50 text-purple-600 hover:bg-purple-100" },
  waiting_client:  { status: "review_required", label: "→ Review",   color: "bg-amber-50 text-amber-600 hover:bg-amber-100" },
  review_required: { status: "completed",       label: "→ Complete", color: "bg-green-50 text-green-600 hover:bg-green-100" },
};

function isOverdue(due?: string, status?: string) {
  if (!due || status === "completed") return false;
  return due < new Date().toISOString().split("T")[0];
}

function TaskCard({
  task,
  onMove,
  onDelete,
}: {
  task: Task;
  onMove: (id: string, status: TaskStatus) => void;
  onDelete: (id: string) => void;
}) {
  const overdue = isOverdue(task.due_date, task.status);
  const next = NEXT_STATUS[task.status as TaskStatus];

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-3 shadow-sm hover:shadow-md transition-shadow group">
      <div className="flex items-start justify-between gap-2 mb-1.5">
        <p className="text-sm font-medium text-gray-900 leading-tight flex-1">{task.title}</p>
        <div className="flex items-center gap-1 shrink-0">
          <span className={`text-xs px-1.5 py-0.5 rounded ${PRIORITY_COLOR[task.priority] ?? ""}`}>
            {task.priority}
          </span>
          <button
            onClick={() => onDelete(task.id)}
            className="opacity-0 group-hover:opacity-100 p-0.5 rounded text-gray-400 hover:text-red-500 transition-all"
            title="Delete task"
          >
            <Trash2 size={11} />
          </button>
        </div>
      </div>

      <p className="text-xs text-gray-500 mb-2">{task.client_name}</p>

      {task.due_date && (
        <div className={`flex items-center gap-1 text-xs mb-2 ${overdue ? "text-red-600 font-medium" : "text-gray-400"}`}>
          {overdue ? <AlertTriangle size={11} /> : <Clock size={11} />}
          <span>{overdue ? "Overdue — " : ""}{task.due_date}</span>
        </div>
      )}

      {next && (
        <button
          onClick={() => onMove(task.id, next.status)}
          className={`text-xs px-2 py-0.5 rounded transition-colors ${next.color}`}
        >
          {next.label}
        </button>
      )}
    </div>
  );
}

export default function TasksPage() {
  const [board, setBoard] = useState<KanbanBoard>({
    todo: [], in_progress: [], waiting_client: [], review_required: [], completed: [],
  });
  const [clients, setClients] = useState<Client[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [tasks, clientList] = await Promise.all([getTasks(), getClients()]);
      setBoard(groupByStatus(tasks));
      setClients(clientList);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load tasks");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleMove(id: string, status: TaskStatus) {
    // Optimistic update
    setBoard(prev => {
      const all = Object.values(prev).flat();
      const task = all.find(t => t.id === id);
      if (!task) return prev;
      const updated = { ...task, status };
      const next = { ...prev };
      (Object.keys(next) as TaskStatus[]).forEach(col => {
        next[col] = next[col].filter(t => t.id !== id);
      });
      next[status] = [...next[status], updated];
      return next;
    });
    try {
      await updateTaskStatus(id, status);
    } catch {
      load(); // revert on failure
    }
  }

  async function handleDelete(id: string) {
    setBoard(prev => {
      const next = { ...prev };
      (Object.keys(next) as TaskStatus[]).forEach(col => {
        next[col] = next[col].filter(t => t.id !== id);
      });
      return next;
    });
    try {
      await deleteTask(id);
    } catch {
      load();
    }
  }

  function handleSaved(task: Task) {
    setBoard(prev => ({
      ...prev,
      todo: [task, ...prev.todo],
    }));
  }

  const totalOpen = Object.entries(board)
    .filter(([k]) => k !== "completed")
    .reduce((sum, [, tasks]) => sum + tasks.length, 0);

  return (
    <div className="p-6 h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Task Board</h1>
          <p className="text-gray-500 text-sm mt-1">
            {loading ? "Loading…" : `${totalOpen} open task${totalOpen !== 1 ? "s" : ""} across all clients`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={load}
            className="p-2 rounded-lg border border-gray-200 hover:bg-gray-50 text-gray-500"
            title="Refresh"
          >
            <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
          </button>
          <button
            onClick={() => setModalOpen(true)}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 transition-colors"
          >
            <Plus size={16} /> New Task
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error} — <button onClick={load} className="underline">retry</button>
        </div>
      )}

      {/* Board */}
      <div className="flex gap-4 overflow-x-auto pb-4 flex-1">
        {COLUMNS.map(col => {
          const tasks = board[col.key] ?? [];
          return (
            <div key={col.key} className={`flex-shrink-0 w-72 rounded-xl border ${col.color} flex flex-col`}>
              <div className={`flex items-center justify-between px-3 py-2.5 rounded-t-xl ${col.headerColor}`}>
                <span className="text-xs font-semibold uppercase tracking-wide">{col.label}</span>
                <span className="text-xs font-bold bg-white bg-opacity-60 rounded-full px-2 py-0.5">
                  {tasks.length}
                </span>
              </div>
              <div className="flex-1 p-3 space-y-2 overflow-y-auto min-h-[200px]">
                {loading && tasks.length === 0 && (
                  <div className="space-y-2">
                    {[...Array(2)].map((_, i) => (
                      <div key={i} className="h-20 bg-white rounded-lg border border-gray-200 animate-pulse" />
                    ))}
                  </div>
                )}
                {!loading && tasks.length === 0 && (
                  <p className="text-xs text-gray-400 text-center py-8">No tasks</p>
                )}
                {tasks.map(task => (
                  <TaskCard key={task.id} task={task} onMove={handleMove} onDelete={handleDelete} />
                ))}
              </div>
            </div>
          );
        })}
      </div>

      <TaskFormModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onSaved={handleSaved}
        clients={clients}
      />
    </div>
  );
}
