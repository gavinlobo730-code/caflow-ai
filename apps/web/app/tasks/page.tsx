"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import {
  Plus, Clock, AlertTriangle, RefreshCw, Trash2,
  ChevronRight, X, CheckSquare,
} from "lucide-react";
import type { Task, TaskStatus, TaskPriority, Client, FirmUser } from "@/lib/types";
import { TaskFormModal } from "@/components/TaskFormModal";
import {
  getTasks, updateTaskStatus, deleteTask, updateTask, getTeamMembers,
} from "@/lib/data/tasks";
import { api } from "@/lib/api";
import { getClients } from "@/lib/data/clients";
import { DataTable } from "@/components/ui/data-table";
import type { BulkAction, Column, FilterDef } from "@/lib/table/types";
import { todayLocalISO } from "@/lib/dateMath";
import { formatDate } from "@/lib/services/formatting";

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

// ── Helpers ────────────────────────────────────────────────────────────────

function isOverdue(due?: string, status?: string) {
  if (!due || status === "completed") return false;
  return due < todayLocalISO();
}

function fmt(date?: string) {
  if (!date) return "—";
  return formatDate(date);
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
                <Row label="Created" value={fmt(task.created_at)} />
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

export default function TasksPage() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [teamMembers, setTeamMembers] = useState<FirmUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  // Detail panel
  const [detailTask, setDetailTask] = useState<Task | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [taskList, clientList, memberList] = await Promise.all([
        // Raised from 200 → 1000: the DataTable paginates client-side, so the old
        // 200-row ceiling silently hid tasks. Fetch the full working set and let
        // the table handle search/sort/filter/pagination in-browser.
        getTasks({ limit: 1000 }),
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
    return {
      total: tasks.length,
      pending: tasks.filter(t => t.status === "todo").length,
      in_progress: tasks.filter(t => t.status === "in_progress").length,
      completed: tasks.filter(t => t.status === "completed").length,
      overdue: tasks.filter(t => isOverdue(t.due_date, t.status)).length,
    };
  }, [tasks]);

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

  const handleDelete = useCallback(async (id: string) => {
    setTasks(prev => prev.filter(t => t.id !== id));
    setDetailTask(prev => (prev?.id === id ? null : prev));
    try { await deleteTask(id); } catch { load(); }
  }, [load]);

  async function handleMove(id: string, status: TaskStatus) {
    setTasks(prev => prev.map(t => t.id === id ? { ...t, status } : t));
    try { await updateTaskStatus(id, status); } catch { load(); }
  }

  // Bulk "mark complete" over the DataTable's selected rows (reuses updateTaskStatus).
  const handleBulkComplete = useCallback(async (rows: Task[]) => {
    const ids = rows.map(r => r.id);
    setTasks(prev => prev.map(t => ids.includes(t.id) ? { ...t, status: "completed" as TaskStatus } : t));
    await Promise.all(ids.map(id => updateTaskStatus(id, "completed").catch(() => null)));
  }, []);

  // Bulk delete over the DataTable's selected rows (reuses deleteTask; confirm handled by DataTable).
  const handleBulkDelete = useCallback(async (rows: Task[]) => {
    const ids = rows.map(r => r.id);
    setTasks(prev => prev.filter(t => !ids.includes(t.id)));
    setDetailTask(prev => (prev && ids.includes(prev.id) ? null : prev));
    await Promise.all(ids.map(id => deleteTask(id).catch(() => null)));
  }, []);

  // ── DataTable columns ──────────────────────────────────────────────────────
  const columns: Column<Task>[] = useMemo(() => [
    {
      key: "title", header: "Task", accessor: (t) => t.title,
      searchable: true, sortable: true, sticky: true, hideable: false,
      render: (t) => (
        <div>
          <span className="font-medium text-[#0F172A] line-clamp-1">{t.title}</span>
          {t.description && (
            <span className="block text-xs text-[#94A3B8] mt-0.5 line-clamp-1">{t.description}</span>
          )}
        </div>
      ),
    },
    // Description is searchable + exportable but hidden as its own column by default
    // (it already appears as a subtitle under the task title).
    {
      key: "description", header: "Description", accessor: (t) => t.description ?? "",
      searchable: true, defaultHidden: true,
      render: (t) => <span className="text-xs text-[#64748B]">{t.description || "—"}</span>,
    },
    {
      key: "client_name", header: "Client", accessor: (t) => t.client_name ?? "",
      searchable: true, sortable: true,
      render: (t) => <span className="whitespace-nowrap text-[#475569]">{t.client_name ?? "—"}</span>,
    },
    {
      key: "assignee", header: "Assignee", accessor: (t) => t.assignee_name ?? "",
      searchable: true, sortable: true,
      render: (t) => (
        <span className="whitespace-nowrap text-[#475569]">
          {t.assignee_name ?? <span className="text-[#CBD5E1]">Unassigned</span>}
        </span>
      ),
    },
    {
      key: "priority", header: "Priority",
      // Numeric accessor so sorting orders by severity (critical→low), not alphabetically.
      accessor: (t) => PRIORITY_ORDER[t.priority] ?? 0, sortable: true,
      exportValue: (t) => t.priority,
      render: (t) => (
        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${PRIORITY_BADGE[t.priority]}`}>
          {t.priority.charAt(0).toUpperCase() + t.priority.slice(1)}
        </span>
      ),
    },
    {
      key: "status", header: "Status", accessor: (t) => t.status, sortable: true,
      exportValue: (t) => STATUS_LABEL[t.status],
      render: (t) => (
        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_BADGE[t.status]}`}>
          {STATUS_LABEL[t.status]}
        </span>
      ),
    },
    {
      key: "due_date", header: "Due Date", accessor: (t) => t.due_date ?? "", sortable: true,
      exportValue: (t) => t.due_date ?? "",
      render: (t) => {
        const overdue = isOverdue(t.due_date, t.status);
        return t.due_date ? (
          <span className={`flex items-center gap-1 whitespace-nowrap text-xs ${overdue ? "text-red-600 font-medium" : "text-[#64748B]"}`}>
            {overdue ? <AlertTriangle size={11} /> : <Clock size={11} />}
            {fmt(t.due_date)}
          </span>
        ) : <span className="text-[#CBD5E1]">—</span>;
      },
    },
    {
      key: "created_at", header: "Created", accessor: (t) => t.created_at, sortable: true, defaultHidden: true,
      exportValue: (t) => t.created_at,
      render: (t) => <span className="whitespace-nowrap text-xs text-[#64748B]">{fmt(t.created_at)}</span>,
    },
  ], []);

  // ── DataTable filters (preserve status / priority / assignee / client) ───────
  const filters: FilterDef<Task>[] = useMemo(() => {
    const defs: FilterDef<Task>[] = [
      {
        key: "status", label: "Status", type: "select", accessor: (t) => t.status,
        options: (Object.keys(STATUS_LABEL) as TaskStatus[]).map(s => ({ value: s, label: STATUS_LABEL[s] })),
      },
      {
        key: "priority", label: "Priority", type: "select", accessor: (t) => t.priority,
        options: (["critical","high","medium","low"] as TaskPriority[]).map(p => ({
          value: p, label: p.charAt(0).toUpperCase() + p.slice(1),
        })),
      },
    ];
    // Assignee filter only when the firm has team members (matches prior behaviour).
    if (teamMembers.length > 0) {
      defs.push({
        key: "assignee_id", label: "Assignee", type: "select", accessor: (t) => t.assignee_id ?? "",
        options: teamMembers.map(m => ({ value: m.id, label: m.full_name ?? m.email ?? m.id })),
      });
    }
    defs.push({
      key: "client_id", label: "Client", type: "select", accessor: (t) => t.client_id,
      options: clients.map(c => ({ value: c.id, label: c.client_name })),
    });
    return defs;
  }, [teamMembers, clients]);

  // ── DataTable bulk actions ───────────────────────────────────────────────────
  const bulkActions: BulkAction<Task>[] = useMemo(() => [
    {
      id: "complete", label: "Mark complete", icon: <CheckSquare size={13} />,
      run: handleBulkComplete,
    },
    {
      id: "delete", label: "Delete", icon: <Trash2 size={13} />, variant: "danger",
      confirm: "Delete the selected tasks? This cannot be undone.",
      run: handleBulkDelete,
    },
  ], [handleBulkComplete, handleBulkDelete]);

  return (
    <div className="p-6 h-full flex flex-col min-h-0">
      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-2xl font-bold text-[#0F172A]">Tasks</h1>
          <p className="text-[#64748B] text-sm mt-0.5">
            {loading ? "Loading…" : `${tasks.length} task${tasks.length !== 1 ? "s" : ""}`}
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

      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-5">
        <SummaryCard label="Total" value={stats.total} color="bg-[#F8FAFC] border-[#E2E8F0] text-[#334155]" />
        <SummaryCard label="Pending" value={stats.pending} color="bg-slate-50 border-slate-200 text-slate-700" />
        <SummaryCard label="In Progress" value={stats.in_progress} color="bg-blue-50 border-blue-200 text-blue-700" />
        <SummaryCard label="Completed" value={stats.completed} color="bg-green-50 border-green-200 text-green-700" />
        <SummaryCard label="Overdue" value={stats.overdue} color="bg-red-50 border-red-200 text-red-700" />
      </div>

      {/* Task list — shared DataTable (global search, sort, filters, pagination, export, prefs) */}
      <DataTable
        data={tasks}
        columns={columns}
        filters={filters}
        getRowId={(t) => t.id}
        loading={loading}
        error={error}
        onRetry={load}
        onRefresh={load}
        searchPlaceholder="Search by title, description, client, or assignee…"
        initialSort={{ key: "due_date", dir: "asc" }}
        bulkActions={bulkActions}
        exportFilename="tasks"
        persistKey="tasks.list"
        emptyTitle="No tasks found"
        emptyDescription="Create a task or adjust your filters."
        onRowClick={(t) => setDetailTask(t)}
        rowActions={(t) => (
          <div className="flex items-center justify-end gap-1">
            <button
              onClick={() => setDetailTask(t)}
              className="p-1 rounded text-[#94A3B8] hover:text-blue-500"
              title="View details"
            >
              <ChevronRight size={14} />
            </button>
            <button
              onClick={() => handleDelete(t.id)}
              className="p-1 rounded text-[#94A3B8] hover:text-red-500"
              title="Delete"
            >
              <Trash2 size={13} />
            </button>
          </div>
        )}
      />

      {/* Move quick-action row (for the currently-open task) */}
      {detailTask && (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-[#64748B]">
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
