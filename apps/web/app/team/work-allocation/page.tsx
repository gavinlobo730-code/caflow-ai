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
import { Skeleton, SkeletonText } from "@/components/ui/skeleton";

import { todayLocalISO } from "@/lib/dateMath";
import { Callout } from "@/components/ui/callout";
// Module 9.0 / M1 — canonical staff roles (single source of truth = backend Role enum).
type Role = "Partner" | "Manager" | "Executive" | "Reviewer";

// Capacity by role (task count)
const CAPACITY: Record<Role, number> = {
  Partner: 20,
  Manager: 30,
  Executive: 40,
  Reviewer: 20,
};

const ROLE_COLORS: Record<Role, string> = {
  Partner: "bg-purple-100 text-purple-700",
  Manager: "bg-blue-100 text-blue-700",
  Executive: "bg-state-attention-surface text-state-attention",
  Reviewer: "bg-ps-muted text-ps-label",
};

const PRIORITY_BADGE: Record<string, string> = {
  critical: "bg-sev-critical-surface text-sev-critical",
  high: "bg-sev-high-surface text-sev-high",
  medium: "bg-sev-medium-surface text-sev-medium",
  low: "bg-sev-low-surface text-sev-low",
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
      <div className="flex-1 h-2 bg-ps-muted rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
      <span className="text-xs text-ps-label w-8 text-right">{pct}%</span>
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
    <div className="fixed inset-0 bg-brand-dark/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-ps-ink">Reassign Task</h3>
          <button onClick={onClose} className="text-ps-hint hover:text-ps-label"><X size={16} /></button>
        </div>
        <p className="text-sm text-ps-label">{task.title}</p>
        {error && <Callout tone="problem">{error}</Callout>}
        <div>
          <label className="text-xs font-medium text-ps-body block mb-1">Reassign to:</label>
          <select value={targetId} onChange={e => setTargetId(e.target.value)}
            className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500">
            {members.map(m => (
              <option key={m.id} value={m.id}>{m.full_name} ({m.role})</option>
            ))}
          </select>
        </div>
        <div className="flex gap-2">
          <button onClick={onClose}
            className="flex-1 border border-ps-border text-ps-body rounded-lg py-2 text-sm hover:bg-ps-bg">
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
  const [clientNamesError, setClientNamesError] = useState<string | null>(null);
  const [roleFilter, setRoleFilter] = useState<Role | "all">("all");
  const [overdueOnly, setOverdueOnly] = useState(false);
  const [reassignTask, setReassignTask] = useState<TaskItem | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const firmId = await getFirmId();
      const sb = getSupabaseClient();

      let clientsFailed = false;
      const [membersRes, tasksRes, clientList] = await Promise.all([
        sb.from("users").select("id, full_name, email, role").eq("firm_id", firmId).eq("is_active", true),
        sb.from("tasks").select("id, title, client_id, due_date, priority, status, assignee_id").eq("firm_id", firmId).neq("status", "completed"),
        getClients().catch((e) => {
          clientsFailed = true;
          setClientNamesError(e instanceof Error ? e.message : "Couldn't load client names.");
          return [] as Client[];
        }),
      ]);
      if (!clientsFailed) setClientNamesError(null);

      const memberList: Member[] = (membersRes.data ?? []).map((m: Member) => ({
        id: m.id,
        full_name: m.full_name ?? m.email ?? "—",
        email: m.email ?? "",
        role: (m.role as Role) ?? "Reviewer",
      }));

      const clientMap = new Map((clientList).map(c => [c.id, c.client_name]));
      const today = todayLocalISO();

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

  const today = todayLocalISO();

  return (
    <div className="p-4 md:p-6 max-w-7xl mx-auto space-y-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/team" className="p-2 rounded-lg border border-ps-border hover:bg-ps-bg text-ps-label">
            <ArrowLeft size={15} />
          </Link>
          <div>
            <h1 className="text-lg md:text-xl font-semibold text-ps-ink">Work Allocation</h1>
            <p className="text-sm text-ps-label mt-0.5">Team capacity and task distribution</p>
          </div>
        </div>
        <button onClick={load} className="p-2 rounded-lg border border-ps-border hover:bg-ps-bg text-ps-label">
          <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {error && <Callout tone="problem">{error}</Callout>}
      {!error && clientNamesError && (
        <div className="rounded-lg bg-state-attention-surface border border-state-attention-border px-4 py-3 text-sm text-state-attention">
          Client names couldn&apos;t be loaded ({clientNamesError}) — tasks below may be missing their client name.
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-center">
        <select value={roleFilter} onChange={e => setRoleFilter(e.target.value as Role | "all")}
          className="border border-ps-border rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500">
          <option value="all">All Roles</option>
          {(["Partner","Manager","Executive","Reviewer"] as Role[]).map(r => (
            <option key={r} value={r}>{r}</option>
          ))}
        </select>
        <label className="flex items-center gap-2 text-sm text-ps-body cursor-pointer">
          <input type="checkbox" checked={overdueOnly} onChange={e => setOverdueOnly(e.target.checked)} />
          Overdue only
        </label>
        <span className="text-xs text-ps-hint ml-auto">{filtered.length} member{filtered.length !== 1 ? "s" : ""}</span>
      </div>

      {loading && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="bg-white rounded-xl border border-ps-border p-4 space-y-3">
              <div className="flex items-start justify-between">
                <div className="space-y-1.5">
                  <Skeleton className="h-3 w-28" />
                  <Skeleton className="h-2.5 w-36" />
                </div>
                <Skeleton className="h-4 w-16 rounded-full" />
              </div>
              <div className="flex gap-3">
                <Skeleton className="h-2.5 w-12" />
                <Skeleton className="h-2.5 w-14" />
              </div>
              <Skeleton className="h-1.5 w-full rounded-full" />
              <SkeletonText lines={3} />
            </div>
          ))}
        </div>
      )}

      {!loading && filtered.length === 0 && (
        <div className="text-center py-12 text-ps-hint">No team members match the filter</div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {!loading && filtered.map(({ member, tasks, total, inProgress, overdue, capacity, pct }) => (
          <div key={member.id} className="bg-white rounded-xl border border-ps-border p-4 space-y-3">
            {/* Header */}
            <div className="flex items-start justify-between">
              <div>
                <p className="font-semibold text-ps-ink text-sm">{member.full_name}</p>
                <p className="text-xs text-ps-hint">{member.email}</p>
              </div>
              <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${ROLE_COLORS[member.role]}`}>
                {member.role}
              </span>
            </div>

            {/* Stats */}
            <div className="flex gap-3 text-xs">
              <span className="text-ps-label">{total} tasks</span>
              <span className="text-blue-600">{inProgress} active</span>
              {overdue > 0 && (
                <span className="text-red-600 flex items-center gap-1">
                  <AlertTriangle size={11} /> {overdue} overdue
                </span>
              )}
              <span className="text-ps-hint ml-auto">cap: {capacity}</span>
            </div>

            {/* Workload bar */}
            <WorkloadBar pct={pct} />

            {/* Task list */}
            <div className="space-y-1 max-h-40 overflow-y-auto">
              {tasks.slice(0, 8).map(t => {
                const isOverdue = t.due_date && t.due_date < today;
                return (
                  <button key={t.id} onClick={() => setReassignTask(t)}
                    className="w-full flex items-center justify-between gap-2 text-left px-2 py-1.5 rounded-lg hover:bg-ps-bg group">
                    <div className="min-w-0">
                      <p className="text-xs text-gray-800 truncate">{t.title}</p>
                      {t.client_name && <p className="text-xs text-ps-hint truncate">{t.client_name}</p>}
                    </div>
                    <div className="shrink-0 flex items-center gap-1">
                      <span className={`text-xs ${isOverdue ? "text-red-500" : "text-ps-hint"}`}>
                        {fmtDate(t.due_date)}
                      </span>
                      <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${PRIORITY_BADGE[t.priority] ?? "bg-ps-muted text-ps-label"}`}>
                        {t.priority?.[0]?.toUpperCase()}
                      </span>
                    </div>
                  </button>
                );
              })}
              {tasks.length > 8 && (
                <p className="text-xs text-ps-hint text-center py-1">+{tasks.length - 8} more</p>
              )}
              {tasks.length === 0 && (
                <p className="text-xs text-ps-hint text-center py-2">No active tasks</p>
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
