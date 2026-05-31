"use client";

import { useState } from "react";
import { Plus, Clock, AlertTriangle } from "lucide-react";
import type { Task, KanbanBoard, TaskStatus } from "@/lib/types";
import { formatDate } from "@/lib/services/formatting";

const MOCK_KANBAN: KanbanBoard = {
  todo: [
    { id: "task-002", client_id: "c-001", client_name: "Sharma Enterprises", title: "Classify Supplies — GSTR-1", status: "todo", priority: "critical", due_date: new Date(Date.now() + 2 * 86400000).toISOString().split("T")[0], created_at: "", updated_at: "" },
    { id: "task-004", client_id: "c-002", client_name: "Patel & Sons", title: "Compute Tax Liability — GSTR-3B", status: "todo", priority: "high", due_date: new Date(Date.now() + 8 * 86400000).toISOString().split("T")[0], created_at: "", updated_at: "" },
  ],
  in_progress: [
    { id: "task-001", client_id: "c-001", client_name: "Sharma Enterprises", title: "Collect Sales Data — GSTR-1", status: "in_progress", priority: "critical", due_date: new Date(Date.now() + 2 * 86400000).toISOString().split("T")[0], created_at: "", updated_at: "" },
    { id: "task-005", client_id: "c-005", client_name: "Joshi Textiles", title: "Collect Documents — ITR", status: "in_progress", priority: "high", due_date: new Date(Date.now() + 10 * 86400000).toISOString().split("T")[0], created_at: "", updated_at: "" },
  ],
  waiting_client: [
    { id: "task-003", client_id: "c-003", client_name: "Mehta Consulting", title: "Compute Tax Liability — GSTR-3B", status: "waiting_client", priority: "critical", due_date: new Date(Date.now() - 10 * 86400000).toISOString().split("T")[0], created_at: "", updated_at: "" },
  ],
  review_required: [
    { id: "task-007", client_id: "c-001", client_name: "Sharma Enterprises", title: "CA Review — GSTR-1", status: "review_required", priority: "critical", due_date: new Date(Date.now() + 2 * 86400000).toISOString().split("T")[0], created_at: "", updated_at: "" },
  ],
  completed: [
    { id: "task-006", client_id: "c-004", client_name: "Desai Traders", title: "File GSTR-3B — Desai Traders", status: "completed", priority: "medium", due_date: new Date(Date.now() - 10 * 86400000).toISOString().split("T")[0], completed_at: new Date(Date.now() - 11 * 86400000).toISOString(), created_at: "", updated_at: "" },
  ],
};

const COLUMNS: { key: TaskStatus; label: string; color: string; headerColor: string }[] = [
  { key: "todo", label: "To Do", color: "bg-gray-50 border-gray-200", headerColor: "bg-gray-100 text-gray-700" },
  { key: "in_progress", label: "In Progress", color: "bg-blue-50 border-blue-200", headerColor: "bg-blue-100 text-blue-700" },
  { key: "waiting_client", label: "Waiting Client", color: "bg-purple-50 border-purple-200", headerColor: "bg-purple-100 text-purple-700" },
  { key: "review_required", label: "Review Required", color: "bg-amber-50 border-amber-200", headerColor: "bg-amber-100 text-amber-700" },
  { key: "completed", label: "Completed", color: "bg-green-50 border-green-200", headerColor: "bg-green-100 text-green-700" },
];

const priorityColor: Record<string, string> = {
  critical: "bg-red-100 text-red-700",
  high: "bg-orange-100 text-orange-700",
  medium: "bg-amber-100 text-amber-700",
  low: "bg-gray-100 text-gray-600",
};

function isOverdue(dueDateStr?: string, status?: string): boolean {
  if (!dueDateStr || status === "completed") return false;
  return dueDateStr < new Date().toISOString().split("T")[0];
}

function TaskCard({ task, onMove }: { task: Task; onMove: (id: string, status: TaskStatus) => void }) {
  const overdue = isOverdue(task.due_date, task.status);
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-3 shadow-sm hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between gap-2 mb-2">
        <p className="text-sm font-medium text-gray-900 leading-tight flex-1">{task.title}</p>
        <span className={`text-xs px-1.5 py-0.5 rounded shrink-0 ${priorityColor[task.priority]}`}>
          {task.priority}
        </span>
      </div>
      <p className="text-xs text-gray-500 mb-2">{task.client_name}</p>
      {task.due_date && (
        <div className={`flex items-center gap-1 text-xs ${overdue ? "text-red-600 font-medium" : "text-gray-400"}`}>
          {overdue ? <AlertTriangle size={11} /> : <Clock size={11} />}
          <span>{overdue ? "Overdue — " : ""}{formatDate(task.due_date)}</span>
        </div>
      )}
      {task.status !== "completed" && (
        <div className="mt-2 flex gap-1 flex-wrap">
          {task.status !== "in_progress" && (
            <button onClick={() => onMove(task.id, "in_progress")} className="text-xs px-2 py-0.5 bg-blue-50 text-blue-600 rounded hover:bg-blue-100">
              → In Progress
            </button>
          )}
          {task.status === "in_progress" && (
            <button onClick={() => onMove(task.id, "review_required")} className="text-xs px-2 py-0.5 bg-amber-50 text-amber-600 rounded hover:bg-amber-100">
              → Review
            </button>
          )}
          {task.status === "review_required" && (
            <button onClick={() => onMove(task.id, "completed")} className="text-xs px-2 py-0.5 bg-green-50 text-green-600 rounded hover:bg-green-100">
              → Complete
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default function TasksPage() {
  const [board, setBoard] = useState<KanbanBoard>(MOCK_KANBAN);

  const moveTask = (taskId: string, newStatus: TaskStatus) => {
    setBoard((prev) => {
      const allTasks = Object.values(prev).flat();
      const task = allTasks.find((t) => t.id === taskId);
      if (!task) return prev;
      const updated = { ...task, status: newStatus };
      const next = { ...prev };
      (Object.keys(next) as TaskStatus[]).forEach((col) => {
        next[col] = next[col].filter((t) => t.id !== taskId);
      });
      next[newStatus] = [...next[newStatus], updated];
      return next;
    });
  };

  const totalOpen = Object.entries(board)
    .filter(([k]) => k !== "completed")
    .reduce((sum, [, tasks]) => sum + tasks.length, 0);

  return (
    <div className="p-6 h-full flex flex-col">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Task Board</h1>
          <p className="text-gray-500 text-sm mt-1">{totalOpen} open tasks across all clients</p>
        </div>
        <button className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 transition-colors">
          <Plus size={16} />
          New Task
        </button>
      </div>

      <div className="flex gap-4 overflow-x-auto pb-4 flex-1">
        {COLUMNS.map((col) => {
          const tasks = board[col.key];
          return (
            <div key={col.key} className={`flex-shrink-0 w-72 rounded-xl border ${col.color} flex flex-col`}>
              <div className={`flex items-center justify-between px-3 py-2.5 rounded-t-xl ${col.headerColor}`}>
                <span className="text-xs font-semibold uppercase tracking-wide">{col.label}</span>
                <span className="text-xs font-bold bg-white bg-opacity-60 rounded-full px-2 py-0.5">{tasks.length}</span>
              </div>
              <div className="flex-1 p-3 space-y-2 overflow-y-auto">
                {tasks.length === 0 && (
                  <p className="text-xs text-gray-400 text-center py-6">No tasks</p>
                )}
                {tasks.map((task) => (
                  <TaskCard key={task.id} task={task} onMove={moveTask} />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
