"use client";

/**
 * Work Allocation & Capacity — Team workload management
 * Shows per-member task load vs capacity, with reassign flow
 */

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { ArrowLeft, RefreshCw, X, AlertTriangle } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";
import { getClients } from "@/lib/data/clients";
import type { Client } from "@/lib/types";

type Role = "Partner" | "Manager" | "Article" | "Staff";

// Capacity by role (task count)
const CAPACITY: Record<Role, number> = {
  Partner: 20,
  Manager: 30,
  Article: 40,
  Staff: 20,
};

const ROLE_COLORS: Record<Role, string> = {
  Partner: "bg-purple-100 text-purple-700",
  Manager: "bg-blue-100 text-blue-700",
  Article: "bg-amber-100 text-amber-700",
  Staff: "bg-gray-100 text-gray-600",
};

const PRIORITY_BADGE: Record<string, string> = {
  critical: "bg-red-100 text-red-700",
  high: "bg-orange-100 text-orange-700",
  medium: "bg-amber-100 text-amber-700",
  low: "bg-gray-100 text-gray-600",
};

interface Member {
  id: string;
  full_name: string;
  email: string;
  role: Role;
}

interface TaskItem {
  id: string;
  title: string;
  client_id: string | null;
  due_date: string | null;
  priority: string;
  status: string;
  assignee_id: string | null;
  client_name?: string;
}

interface MemberWorkload {
  member: Member;
  tasks: TaskItem[];
  total: number;
  inProgress: number;
  overdue: number;
  capacity: number;
  pct: number;
}

function fmtDate(d: string | null): string {
  if (!d) return "—";
  const [y, m, dd] = d.split("-");
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return `${dd} ${months[parseInt(m) - 1]} ${y}`;
}

function WorkloadBar({ pct }: { pct: number }) {
  const color = pct >= 90 ? "bg-red-500" : pct >= 70 ? "bg-amber-500" : "bg-green-500";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
      <span className="text-xs text-gray-500 w-8 text-right">{pct}%</span>
    </div>
  );
}

interface ReassignModalProps {
  task: TaskItem;
  members: Member[];
  onClose: () => void;
  onReassigned: () => void;
}

function ReassignModal({ task, members, onClose, onReassigned }: ReassignModalProps) {
  const [targetId, setTargetId] = useState(members[0]?.id ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleConfirm() {
    setSaving(true);
    try {
      const sb = getSupabaseClient();
      const { error: err } = await sb.from("tasks").update({ assignee_id: targetId }).eq("id", task.id);
      if (err) throw new Error(err.message);
      onReassigned();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to reassign");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-900">Reassign Task</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={16} /></button>
        </div>
        <p className="text-sm text-gray-600">{task.title}</p>
        {error && <div className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</div>}
        <div>
          <label className="text-xs font-medium text-gray-700 block mb-1">Reassign to:</label>
          <select value={targetId} onChange={e => setTargetId(e.target.value)}
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500">
            {members.map(m => (
              <option key={m.id} value={m.id}>{m.full_name} ({m.role})</option>
            ))}
          </select>
        </div>
        <div className="flex gap-2">
          <button onClick={onClose}
            className="flex-1 border border-gray-200 text-gray-700 rounded-lg py-2 text-sm hover:bg-gray-50">
            Cancel
          </button>
          <button onClick={handleConfirm} disabled={saving}
            className="flex-1 bg-blue-600 text-white rounded-lg py-2 text-sm hover:bg-blue-700 disabled:opacity-60">
            {saving ? "Saving…" : "Confirm"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function WorkAllocationPage() {
  const [workloads, setWorkloads] = useState<MemberWorkload[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [roleFilter, setRoleFilter] = useState<Role | "all">("all");
  const [overdueOnly, setOverdueOnly] = useState(false);
  const [reassignTask, setReassignTask] = useState<TaskItem | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const firmId = await getFirmId();
      const sb = getSupabaseClient();

      const [membersRes, tasksRes, clientList] = await Promise.all([
        sb.from("users").select("id, full_name, email, role").eq("firm_id", firmId).eq("is_active", true),
        sb.from("tasks").select("id, title, client_id, due_date, priority, status, assignee_id").eq("firm_id", firmId).neq("status", "completed"),
        getClients().catch(() => [] as Client[]),
      ]);

      const memberList: Member[] = (membersRes.data ?? []).map((m: Member) => ({
        id: m.id,
        full_name: m.full_name ?? m.email ?? "—",
        email: m.email ?? "",
        role: (m.role as Role) ?? "Staff",
      }));

      const clientMap = new Map((clientList).map(c => [c.id, c.client_name]));
      const today = new Date().toISOString().split("T")[0];

      const taskList: TaskItem[] = (tasksRes.data ?? []).map((t: TaskItem) => ({
        ...t,
        client_name: t.client_id ? clientMap.get(t.client_id) : undefined,
      }));

      const wl: MemberWorkload[] = memberList.map(member => {
        const tasks = taskList.filter(t => t.assignee_id === member.id);
        const inProgress = tasks.filter(t => t.status === "in_progress").length;
        const overdue = tasks.filter(t => t.due_date && t.due_date < today).length;
        const cap = CAPACITY[member.role] ?? 20;
        const pct = Math.round((tasks.length / cap) * 100);
        return { member, tasks, total: tasks.length, inProgress, overdue, capacity: cap, pct };
      });

      setMembers(memberList);
      setWorkloads(wl);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const filtered = workloads.filter(w => {
    if (roleFilter !== "all" && w.member.role !== roleFilter) return false;
    if (overdueOnly && w.overdue === 0) return false;
    return true;
  });

  const today = new Date().toISOString().split("T")[0];

  return (
    <div className="p-4 md:p-6 max-w-7xl mx-auto space-y-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/team" className="p-2 rounded-lg border border-gray-200 hover:bg-gray-50 text-gray-500">
            <ArrowLeft size={15} />
          </Link>
          <div>
            <h1 className="text-lg md:text-xl font-semibold text-gray-900">Work Allocation</h1>
            <p className="text-sm text-gray-500 mt-0.5">Team capacity and task distribution</p>
          </div>
        </div>
        <button onClick={load} className="p-2 rounded-lg border border-gray-200 hover:bg-gray-50 text-gray-500">
          <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {error && (
        <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">{error}</div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-center">
        <select value={roleFilter} onChange={e => setRoleFilter(e.target.value as Role | "all")}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500">
          <option value="all">All Roles</option>
          {(["Partner","Manager","Article","Staff"] as Role[]).map(r => (
            <option key={r} value={r}>{r}</option>
          ))}
        </select>
        <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
          <input type="checkbox" checked={overdueOnly} onChange={e => setOverdueOnly(e.target.checked)} />
          Overdue only
        </label>
        <span className="text-xs text-gray-400 ml-auto">{filtered.length} member{filtered.length !== 1 ? "s" : ""}</span>
      </div>

      {loading && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="bg-white rounded-xl border border-gray-200 p-4 animate-pulse h-48" />
          ))}
        </div>
      )}

      {!loading && filtered.length === 0 && (
        <div className="text-center py-12 text-gray-400">No team members match the filter</div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {!loading && filtered.map(({ member, tasks, total, inProgress, overdue, capacity, pct }) => (
          <div key={member.id} className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
            {/* Header */}
            <div className="flex items-start justify-between">
              <div>
                <p className="font-semibold text-gray-900 text-sm">{member.full_name}</p>
                <p className="text-xs text-gray-400">{member.email}</p>
              </div>
              <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${ROLE_COLORS[member.role]}`}>
                {member.role}
              </span>
            </div>

            {/* Stats */}
            <div className="flex gap-3 text-xs">
              <span className="text-gray-600">{total} tasks</span>
              <span className="text-blue-600">{inProgress} active</span>
              {overdue > 0 && (
                <span className="text-red-600 flex items-center gap-1">
                  <AlertTriangle size={11} /> {overdue} overdue
                </span>
              )}
              <span className="text-gray-400 ml-auto">cap: {capacity}</span>
            </div>

            {/* Workload bar */}
            <WorkloadBar pct={pct} />

            {/* Task list */}
            <div className="space-y-1 max-h-40 overflow-y-auto">
              {tasks.slice(0, 8).map(t => {
                const isOverdue = t.due_date && t.due_date < today;
                return (
                  <button key={t.id} onClick={() => setReassignTask(t)}
                    className="w-full flex items-center justify-between gap-2 text-left px-2 py-1.5 rounded-lg hover:bg-gray-50 group">
                    <div className="min-w-0">
                      <p className="text-xs text-gray-800 truncate">{t.title}</p>
                      {t.client_name && <p className="text-xs text-gray-400 truncate">{t.client_name}</p>}
                    </div>
                    <div className="shrink-0 flex items-center gap-1">
                      <span className={`text-xs ${isOverdue ? "text-red-500" : "text-gray-400"}`}>
                        {fmtDate(t.due_date)}
                      </span>
                      <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${PRIORITY_BADGE[t.priority] ?? "bg-gray-100 text-gray-600"}`}>
                        {t.priority?.[0]?.toUpperCase()}
                      </span>
                    </div>
                  </button>
                );
              })}
              {tasks.length > 8 && (
                <p className="text-xs text-gray-400 text-center py-1">+{tasks.length - 8} more</p>
              )}
              {tasks.length === 0 && (
                <p className="text-xs text-gray-400 text-center py-2">No active tasks</p>
              )}
            </div>
          </div>
        ))}
      </div>

      {reassignTask && (
        <ReassignModal
          task={reassignTask}
          members={members.filter(m => m.id !== reassignTask.assignee_id)}
          onClose={() => setReassignTask(null)}
          onReassigned={() => { setReassignTask(null); load(); }}
        />
      )}
    </div>
  );
}
