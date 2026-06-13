"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import {
  Plus, Clock, AlertTriangle, RefreshCw, Trash2,
  ChevronRight, X, CheckSquare, Square, Filter, ArrowUpDown,
} from "lucide-react";
import type { Task, TaskStatus, TaskPriority, Client, FirmUser } from "@/lib/types";
import { TaskFormModal } from "@/components/TaskFormModal";
import {
  getTasks, updateTaskStatus, deleteTask, updateTask, getTeamMembers,
} from "@/lib/data/tasks";
import { api } from "@/lib/api";
import { getClients } from "@/lib/data/clients";

// ── Constants ──────────────────────────────────────────────────────────────

const PRIORITY_BADGE: Record<TaskPriority, string> = {
  critical: "bg-red-100 text-red-700 border border-red-200",
  high:     "bg-orange-100 text-orange-700 border border-orange-200",
  medium:   "bg-amber-100 text-amber-700 border border-amber-200",
  low:      "bg-[#F1F5F9] text-[#475569] border border-[#E2E8F0]",
};

const STATUS_BADGE: Record<TaskStatus, string> = {
  todo:            "bg-[#F1F5F9] text-[#334155]",
  in_progress:     "bg-blue-100 text-blue-700",
  waiting_client:  "bg-purple-100 text-purple-700",
  review_required: "bg-amber-100 text-amber-700",
  completed:       "bg-green-100 text-green-700",
};

const STATUS_LABEL: Record<TaskStatus, string> = {
  todo:            "To Do",
  in_progress:     "In Progress",
  waiting_client:  "Waiting Client",
  review_required: "Review Required",
  completed:       "Completed",
};

const PRIORITY_ORDER: Record<TaskPriority, number> = { critical: 4, high: 3, medium: 2, low: 1 };

type SortField = "due_date" | "priority" | "created_at";

// ── Helpers ────────────────────────────────────────────────────────────────

function isOverdue(due?: string, status?: string) {
  if (!due || status === "completed") return false;
  return due < new Date().toISOString().split("T")[0];
}

function fmt(date?: string) {
  if (!date) return "—";
  const [y, m, d] = date.split("-");
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return `${d} ${months[parseInt(m) - 1]} ${y}`;
}

// ── Summary Card ──────────────────────────────────────────────────────────

function SummaryCard({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className={`rounded-xl border px-4 py-3 flex flex-col gap-0.5 ${color}`}>
      <span className="text-2xl font-bold">{value}</span>
      <span className="text-xs font-medium opacity-70">{label}</span>
    </div>
  );
}

// ── Dependencies Section ──────────────────────────────────────────────────

interface TaskDependency {
  id: string;
  depends_on_task_id: string;
  depends_on_title?: string;
}

interface ApiResponse<T> {
  success: boolean;
  data: T | null;
  error: string | null;
}

function DependenciesSection({ taskId, allTasks }: { taskId: string; allTasks: Task[] }) {
  const [deps, setDeps] = useState<TaskDependency[]>([]);
  const [loading, setLoading] = useState(true);
  const [addId, setAddId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const titleMap = new Map(allTasks.map(t => [t.id, t.title]));

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const json = await api.taskExtras.dependencies(taskId) as ApiResponse<{ dependencies: TaskDependency[] }>;
      setDeps(json.data?.dependencies ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load dependencies");
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  useEffect(() => { load(); }, [load]);

  async function handleAdd() {
    if (!addId) return;
    setBusy(true);
    setError(null);
    try {
      await api.taskExtras.addDependency(taskId, addId);
      setAddId("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add dependency");
    } finally {
      setBusy(false);
    }
  }

  async function handleRemove(depId: string) {
    setBusy(true);
    setError(null);
    try {
      await api.taskExtras.removeDependency(taskId, depId);
      setDeps(prev => prev.filter(d => d.id !== depId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove dependency");
    } finally {
      setBusy(false);
    }
  }

  const existingDepIds = new Set(deps.map(d => d.depends_on_task_id));
  const candidates = allTasks.filter(t => t.id !== taskId && !existingDepIds.has(t.id));

  return (
    <div className="space-y-2">
      <h5 className="text-xs font-semibold text-[#475569] uppercase tracking-wide">Blocked By</h5>
      {error && <p className="text-xs text-red-600">{error}</p>}
      {loading ? (
        <p className="text-xs text-[#94A3B8]">Loading dependencies…</p>
      ) : deps.length === 0 ? (
        <p className="text-xs text-[#94A3B8]">No dependencies</p>
      ) : (
        <div className="space-y-1.5">
          {deps.map(d => (
            <div key={d.id} className="flex items-center justify-between gap-2 bg-[#F8FAFC] border border-[#F1F5F9] rounded-lg px-3 py-2">
              <span className="text-xs text-[#334155] line-clamp-1">
                {d.depends_on_title ?? titleMap.get(d.depends_on_task_id) ?? d.depends_on_task_id}
              </span>
              <button
                onClick={() => handleRemove(d.id)}
                disabled={busy}
                className="p-0.5 rounded text-[#94A3B8] hover:text-red-500 shrink-0"
                title="Remove dependency"
              >
                <X size={12} />
              </button>
            </div>
          ))}
        </div>
      )}
      <div className="flex gap-2">
        <select
          value={addId}
          onChange={e => setAddId(e.target.value)}
          className="flex-1 border border-[#E2E8F0] rounded-lg px-2 py-1.5 text-xs outline-none focus:border-blue-500"
        >
          <option value="">Add a blocking task…</option>
          {candidates.map(t => (
            <option key={t.id} value={t.id}>{t.title}</option>
          ))}
        </select>
        <button
          onClick={handleAdd}
          disabled={!addId || busy}
          className="px-3 py-1.5 text-xs bg-blue-50 text-blue-600 rounded-lg hover:bg-blue-100 font-medium disabled:opacity-50"
        >
          Add
        </button>
      </div>
    </div>
  );
}

// ── Detail Side Panel ─────────────────────────────────────────────────────

interface DetailPanelProps {
  task: Task | null;
  clients: Client[];
  teamMembers: FirmUser[];
  allTasks: Task[];
  onClose: () => void;
  onUpdated: (task: Task) => void;
}

function DetailPanel({ task, clients, teamMembers, allTasks, onClose, onUpdated }: DetailPanelProps) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<Partial<Task>>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (task) { setForm(task); setEditing(false); }
  }, [task]);

  if (!task) return null;

  const clientName = clients.find(c => c.id === task.client_id)?.client_name ?? task.client_name ?? "—";
  const assignee = teamMembers.find(m => m.id === task.assignee_id);
  const overdue = isOverdue(task.due_date, task.status);

  async function handleSave() {
    if (!task) return;
    setSaving(true);
    try {
      await updateTask(task.id, {
        title: form.title,
        description: form.description,
        priority: form.priority,
        status: form.status,
        due_date: form.due_date,
        client_id: form.client_id,
        assignee_id: form.assignee_id,
      });
      onUpdated({ ...task, ...form } as Task);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-40 flex justify-end pointer-events-none">
      <div className="absolute inset-0 pointer-events-auto" onClick={onClose} />
      <div className="relative w-96 h-full bg-white border-l border-[#E2E8F0] shadow-2xl pointer-events-auto flex flex-col overflow-hidden">
        {/* Panel header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#F1F5F9]">
          <h3 className="text-sm font-semibold text-[#0F172A]">Task Detail</h3>
          <div className="flex items-center gap-2">
            {!editing && (
              <button
                onClick={() => setEditing(true)}
                className="px-3 py-1.5 text-xs bg-blue-50 text-blue-600 rounded-lg hover:bg-blue-100 font-medium"
              >
                Edit
              </button>
            )}
            <button onClick={onClose} className="p-1 rounded text-[#94A3B8] hover:text-[#475569]">
              <X size={16} />
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {editing ? (
            /* Edit mode */
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-[#475569] mb-1">Title</label>
                <input
                  value={form.title ?? ""}
                  onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-[#475569] mb-1">Client</label>
                <select
                  value={form.client_id ?? ""}
                  onChange={e => setForm(f => ({ ...f, client_id: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500"
                >
                  {clients.map(c => <option key={c.id} value={c.id}>{c.client_name}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-[#475569] mb-1">Assign To</label>
                <select
                  value={form.assignee_id ?? ""}
                  onChange={e => setForm(f => ({ ...f, assignee_id: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500"
                >
                  <option value="">Unassigned</option>
                  {teamMembers.map(m => <option key={m.id} value={m.id}>{m.full_name ?? m.email}</option>)}
                </select>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-[#475569] mb-1">Priority</label>
                  <select
                    value={form.priority ?? "medium"}
                    onChange={e => setForm(f => ({ ...f, priority: e.target.value as TaskPriority }))}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500"
                  >
                    {(["low","medium","high","critical"] as TaskPriority[]).map(p => (
                      <option key={p} value={p}>{p.charAt(0).toUpperCase() + p.slice(1)}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-[#475569] mb-1">Status</label>
                  <select
                    value={form.status ?? "todo"}
                    onChange={e => setForm(f => ({ ...f, status: e.target.value as TaskStatus }))}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500"
                  >
                    {(Object.keys(STATUS_LABEL) as TaskStatus[]).map(s => (
                      <option key={s} value={s}>{STATUS_LABEL[s]}</option>
                    ))}
                  </select>
                </div>
              </div>
              <div>
                <label className="block text-xs font-medium text-[#475569] mb-1">Due Date</label>
                <input
                  type="date"
                  value={form.due_date ?? ""}
                  onChange={e => setForm(f => ({ ...f, due_date: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-[#475569] mb-1">Description</label>
                <textarea
                  rows={3}
                  value={form.description ?? ""}
                  onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500 resize-none"
                />
              </div>
              <div className="flex gap-2 pt-1">
                <button
                  onClick={() => setEditing(false)}
                  className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm text-[#334155] hover:bg-[#F8FAFC]"
                >
                  Cancel
                </button>
                <button
                  onClick={handleSave}
                  disabled={saving}
                  className="flex-1 bg-blue-600 text-white rounded-lg px-3 py-2 text-sm hover:bg-blue-700 disabled:opacity-60"
                >
                  {saving ? "Saving…" : "Save"}
                </button>
              </div>
            </div>
          ) : (
            /* View mode */
            <>
              <div>
                <h4 className="text-base font-semibold text-[#0F172A] leading-tight">{task.title}</h4>
                {task.description && (
                  <p className="text-sm text-[#64748B] mt-2 leading-relaxed">{task.description}</p>
                )}
              </div>

              <div className="flex flex-wrap gap-2">
                <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${PRIORITY_BADGE[task.priority]}`}>
                  {task.priority.charAt(0).toUpperCase() + task.priority.slice(1)} Priority
                </span>
                <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${STATUS_BADGE[task.status]}`}>
                  {STATUS_LABEL[task.status]}
                </span>
                {overdue && (
                  <span className="text-xs px-2.5 py-1 rounded-full font-medium bg-red-100 text-red-700 flex items-center gap-1">
                    <AlertTriangle size={10} /> Overdue
                  </span>
                )}
              </div>

              <div className="space-y-3">
                <Row label="Client" value={clientName} />
                <Row label="Assignee" value={assignee ? (assignee.full_name ?? assignee.email ?? "—") : "Unassigned"} />
                <Row label="Due Date" value={fmt(task.due_date)} highlight={overdue} />
                <Row label="Created" value={fmt(task.created_at.split("T")[0])} />
              </div>

              <DependenciesSection taskId={task.id} allTasks={allTasks} />
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function Row({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <span className="text-xs text-[#64748B] shrink-0 pt-0.5">{label}</span>
      <span className={`text-sm font-medium text-right ${highlight ? "text-red-600" : "text-gray-800"}`}>{value}</span>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────

type StatusFilter = "all" | TaskStatus;
type PriorityFilter = "all" | TaskPriority;

export default function TasksPage() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [teamMembers, setTeamMembers] = useState<FirmUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  // Filters
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [priorityFilter, setPriorityFilter] = useState<PriorityFilter>("all");
  const [assigneeFilter, setAssigneeFilter] = useState<string>("all");
  const [clientFilter, setClientFilter] = useState<string>("all");

  // Sort
  const [sortField, setSortField] = useState<SortField>("due_date");

  // Selection
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  // Detail panel
  const [detailTask, setDetailTask] = useState<Task | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [taskList, clientList, memberList] = await Promise.all([
        getTasks(),
        getClients(),
        getTeamMembers().catch(() => [] as FirmUser[]),
      ]);
      // Enrich tasks with client names and assignee info
      const clientMap = new Map(clientList.map(c => [c.id, c.client_name]));
      const memberMap = new Map(memberList.map(m => [m.id, m]));
      const enriched = taskList.map(t => ({
        ...t,
        client_name: clientMap.get(t.client_id) ?? t.client_name,
        assignee_name: t.assignee_id ? (memberMap.get(t.assignee_id)?.full_name ?? memberMap.get(t.assignee_id)?.email) : undefined,
        assignee_email: t.assignee_id ? memberMap.get(t.assignee_id)?.email : undefined,
      }));
      setTasks(enriched);
      setClients(clientList);
      setTeamMembers(memberList);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load tasks");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Summary stats
  const stats = useMemo(() => {
    const today = new Date().toISOString().split("T")[0];
    return {
      total: tasks.length,
      pending: tasks.filter(t => t.status === "todo").length,
      in_progress: tasks.filter(t => t.status === "in_progress").length,
      completed: tasks.filter(t => t.status === "completed").length,
      overdue: tasks.filter(t => t.due_date && t.due_date < today && t.status !== "completed").length,
    };
  }, [tasks]);

  // Filtered + sorted tasks
  const filtered = useMemo(() => {
    let list = tasks.slice();
    if (statusFilter !== "all") list = list.filter(t => t.status === statusFilter);
    if (priorityFilter !== "all") list = list.filter(t => t.priority === priorityFilter);
    if (assigneeFilter !== "all") list = list.filter(t => t.assignee_id === assigneeFilter);
    if (clientFilter !== "all") list = list.filter(t => t.client_id === clientFilter);

    list.sort((a, b) => {
      if (sortField === "priority") return (PRIORITY_ORDER[b.priority] ?? 0) - (PRIORITY_ORDER[a.priority] ?? 0);
      if (sortField === "due_date") {
        if (!a.due_date) return 1;
        if (!b.due_date) return -1;
        return a.due_date.localeCompare(b.due_date);
      }
      return b.created_at.localeCompare(a.created_at);
    });
    return list;
  }, [tasks, statusFilter, priorityFilter, assigneeFilter, clientFilter, sortField]);

  function handleSaved(task: Task) {
    const client = clients.find(c => c.id === task.client_id);
    const member = teamMembers.find(m => m.id === task.assignee_id);
    setTasks(prev => [{
      ...task,
      client_name: client?.client_name ?? task.client_name,
      assignee_name: member?.full_name ?? member?.email,
    }, ...prev]);
  }

  function handleUpdated(updated: Task) {
    setTasks(prev => prev.map(t => t.id === updated.id ? updated : t));
    setDetailTask(updated);
  }

  async function handleDelete(id: string) {
    setTasks(prev => prev.filter(t => t.id !== id));
    setSelectedIds(prev => { const s = new Set(prev); s.delete(id); return s; });
    if (detailTask?.id === id) setDetailTask(null);
    try { await deleteTask(id); } catch { load(); }
  }

  async function handleMove(id: string, status: TaskStatus) {
    setTasks(prev => prev.map(t => t.id === id ? { ...t, status } : t));
    try { await updateTaskStatus(id, status); } catch { load(); }
  }

  async function handleBulkComplete() {
    const ids = Array.from(selectedIds);
    setTasks(prev => prev.map(t => ids.includes(t.id) ? { ...t, status: "completed" as TaskStatus } : t));
    setSelectedIds(new Set());
    await Promise.all(ids.map(id => updateTaskStatus(id, "completed").catch(() => null)));
  }

  function toggleSelect(id: string) {
    setSelectedIds(prev => {
      const s = new Set(prev);
      if (s.has(id)) s.delete(id); else s.add(id);
      return s;
    });
  }

  function toggleSelectAll() {
    if (selectedIds.size === filtered.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filtered.map(t => t.id)));
    }
  }

  const allSelected = filtered.length > 0 && selectedIds.size === filtered.length;

  return (
    <div className="p-6 h-full flex flex-col min-h-0">
      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-2xl font-bold text-[#0F172A]">Tasks</h1>
          <p className="text-[#64748B] text-sm mt-0.5">
            {loading ? "Loading…" : `${filtered.length} task${filtered.length !== 1 ? "s" : ""} shown`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={load}
            className="p-2 rounded-lg border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#64748B]"
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

      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-5">
        <SummaryCard label="Total" value={stats.total} color="bg-[#F8FAFC] border-[#E2E8F0] text-[#334155]" />
        <SummaryCard label="Pending" value={stats.pending} color="bg-slate-50 border-slate-200 text-slate-700" />
        <SummaryCard label="In Progress" value={stats.in_progress} color="bg-blue-50 border-blue-200 text-blue-700" />
        <SummaryCard label="Completed" value={stats.completed} color="bg-green-50 border-green-200 text-green-700" />
        <SummaryCard label="Overdue" value={stats.overdue} color="bg-red-50 border-red-200 text-red-700" />
      </div>

      {/* Filter + Sort bar */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <Filter size={14} className="text-[#94A3B8] shrink-0" />

        <select
          value={statusFilter}
          onChange={e => setStatusFilter(e.target.value as StatusFilter)}
          className="border border-[#E2E8F0] rounded-lg px-3 py-1.5 text-sm text-[#334155] bg-white outline-none focus:border-blue-400"
        >
          <option value="all">All Statuses</option>
          {(Object.keys(STATUS_LABEL) as TaskStatus[]).map(s => (
            <option key={s} value={s}>{STATUS_LABEL[s]}</option>
          ))}
        </select>

        <select
          value={priorityFilter}
          onChange={e => setPriorityFilter(e.target.value as PriorityFilter)}
          className="border border-[#E2E8F0] rounded-lg px-3 py-1.5 text-sm text-[#334155] bg-white outline-none focus:border-blue-400"
        >
          <option value="all">All Priorities</option>
          {(["critical","high","medium","low"] as TaskPriority[]).map(p => (
            <option key={p} value={p}>{p.charAt(0).toUpperCase() + p.slice(1)}</option>
          ))}
        </select>

        {teamMembers.length > 0 && (
          <select
            value={assigneeFilter}
            onChange={e => setAssigneeFilter(e.target.value)}
            className="border border-[#E2E8F0] rounded-lg px-3 py-1.5 text-sm text-[#334155] bg-white outline-none focus:border-blue-400"
          >
            <option value="all">All Assignees</option>
            {teamMembers.map(m => (
              <option key={m.id} value={m.id}>{m.full_name ?? m.email}</option>
            ))}
          </select>
        )}

        <select
          value={clientFilter}
          onChange={e => setClientFilter(e.target.value)}
          className="border border-[#E2E8F0] rounded-lg px-3 py-1.5 text-sm text-[#334155] bg-white outline-none focus:border-blue-400"
        >
          <option value="all">All Clients</option>
          {clients.map(c => (
            <option key={c.id} value={c.id}>{c.client_name}</option>
          ))}
        </select>

        <div className="ml-auto flex items-center gap-1 text-sm text-[#64748B]">
          <ArrowUpDown size={13} />
          <select
            value={sortField}
            onChange={e => setSortField(e.target.value as SortField)}
            className="border border-[#E2E8F0] rounded-lg px-3 py-1.5 text-sm text-[#334155] bg-white outline-none focus:border-blue-400"
          >
            <option value="due_date">Sort: Due Date</option>
            <option value="priority">Sort: Priority</option>
            <option value="created_at">Sort: Created Date</option>
          </select>
        </div>
      </div>

      {/* Bulk action bar */}
      {selectedIds.size > 0 && (
        <div className="flex items-center gap-3 mb-3 px-4 py-2.5 bg-blue-50 border border-blue-200 rounded-xl text-sm">
          <span className="text-blue-700 font-medium">{selectedIds.size} selected</span>
          <button
            onClick={handleBulkComplete}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600 text-white rounded-lg text-xs hover:bg-green-700"
          >
            <CheckSquare size={13} /> Mark Complete
          </button>
          <button
            onClick={() => setSelectedIds(new Set())}
            className="text-blue-500 hover:text-blue-700 ml-auto"
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* Table */}
      <div className="flex-1 overflow-x-auto rounded-xl border border-[#E2E8F0] bg-white min-h-0">
        <table className="w-full text-sm min-w-[600px]">
          <thead className="bg-[#F8FAFC] border-b border-[#E2E8F0] sticky top-0">
            <tr>
              <th className="w-10 px-3 py-3">
                <button onClick={toggleSelectAll} className="text-[#94A3B8] hover:text-[#475569]">
                  {allSelected ? <CheckSquare size={15} className="text-blue-600" /> : <Square size={15} />}
                </button>
              </th>
              <th className="text-left px-3 py-3 font-medium text-[#475569]">Task</th>
              <th className="text-left px-3 py-3 font-medium text-[#475569]">Client</th>
              <th className="text-left px-3 py-3 font-medium text-[#475569]">Assignee</th>
              <th className="text-left px-3 py-3 font-medium text-[#475569]">Priority</th>
              <th className="text-left px-3 py-3 font-medium text-[#475569]">Status</th>
              <th className="text-left px-3 py-3 font-medium text-[#475569]">Due Date</th>
              <th className="w-12 px-3 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F1F5F9]">
            {loading && (
              [...Array(5)].map((_, i) => (
                <tr key={i}>
                  {[...Array(8)].map((__, j) => (
                    <td key={j} className="px-3 py-3">
                      <div className="h-4 bg-[#F1F5F9] rounded animate-pulse" />
                    </td>
                  ))}
                </tr>
              ))
            )}
            {!loading && filtered.length === 0 && (
              <tr>
                <td colSpan={8} className="text-center py-12 text-[#94A3B8]">
                  No tasks match your filters
                </td>
              </tr>
            )}
            {!loading && filtered.map(task => {
              const overdue = isOverdue(task.due_date, task.status);
              const checked = selectedIds.has(task.id);
              return (
                <tr
                  key={task.id}
                  className={`group hover:bg-[#F8FAFC] cursor-pointer transition-colors ${checked ? "bg-blue-50" : ""}`}
                  onClick={() => setDetailTask(task)}
                >
                  <td className="px-3 py-3" onClick={e => { e.stopPropagation(); toggleSelect(task.id); }}>
                    {checked
                      ? <CheckSquare size={15} className="text-blue-600" />
                      : <Square size={15} className="text-[#CBD5E1] group-hover:text-[#94A3B8]" />
                    }
                  </td>
                  <td className="px-3 py-3">
                    <span className="font-medium text-[#0F172A] line-clamp-1">{task.title}</span>
                    {task.description && (
                      <span className="block text-xs text-[#94A3B8] mt-0.5 line-clamp-1">{task.description}</span>
                    )}
                  </td>
                  <td className="px-3 py-3 text-[#475569] whitespace-nowrap">{task.client_name ?? "—"}</td>
                  <td className="px-3 py-3 text-[#475569] whitespace-nowrap">
                    {task.assignee_name ?? <span className="text-[#CBD5E1]">Unassigned</span>}
                  </td>
                  <td className="px-3 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${PRIORITY_BADGE[task.priority]}`}>
                      {task.priority.charAt(0).toUpperCase() + task.priority.slice(1)}
                    </span>
                  </td>
                  <td className="px-3 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_BADGE[task.status]}`}>
                      {STATUS_LABEL[task.status]}
                    </span>
                  </td>
                  <td className="px-3 py-3 whitespace-nowrap">
                    {task.due_date ? (
                      <span className={`flex items-center gap-1 text-xs ${overdue ? "text-red-600 font-medium" : "text-[#64748B]"}`}>
                        {overdue && <AlertTriangle size={11} />}
                        {!overdue && <Clock size={11} />}
                        {fmt(task.due_date)}
                      </span>
                    ) : <span className="text-[#CBD5E1]">—</span>}
                  </td>
                  <td className="px-3 py-3" onClick={e => e.stopPropagation()}>
                    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        onClick={() => setDetailTask(task)}
                        className="p-1 rounded text-[#94A3B8] hover:text-blue-500"
                        title="View details"
                      >
                        <ChevronRight size={14} />
                      </button>
                      <button
                        onClick={() => handleDelete(task.id)}
                        className="p-1 rounded text-[#94A3B8] hover:text-red-500"
                        title="Delete"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Move quick-action row (below table, for selected task) */}
      {detailTask && !selectedIds.size && (
        <div className="mt-3 flex items-center gap-2 text-xs text-[#64748B]">
          <span>Move {detailTask.title.slice(0, 30)}{detailTask.title.length > 30 ? "…" : ""}:</span>
          {(Object.keys(STATUS_LABEL) as TaskStatus[])
            .filter(s => s !== detailTask.status)
            .map(s => (
              <button
                key={s}
                onClick={() => handleMove(detailTask.id, s)}
                className="px-2 py-1 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#475569] hover:text-[#0F172A]"
              >
                {STATUS_LABEL[s]}
              </button>
            ))
          }
        </div>
      )}

      {/* Modals */}
      <TaskFormModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onSaved={handleSaved}
        clients={clients}
        teamMembers={teamMembers}
      />

      <DetailPanel
        task={detailTask}
        clients={clients}
        teamMembers={teamMembers}
        allTasks={tasks}
        onClose={() => setDetailTask(null)}
        onUpdated={handleUpdated}
      />
    </div>
  );
}
