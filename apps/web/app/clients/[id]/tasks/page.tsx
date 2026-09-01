"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus, Loader2, Check } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TransactionListSkeleton } from "@/components/ui/skeleton";
import { TaskFormModal } from "@/components/TaskFormModal";
import { getTasks, getTeamMembers, updateTaskStatus } from "@/lib/data/tasks";
import { getClient } from "@/lib/data/clients";
import type { Task, Client, FirmUser } from "@/lib/types";
import { formatDate } from "@/lib/services/formatting";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

/**
 * A client's tasks — and, since this change, a place to create and close them.
 *
 * This tab was read-only. Every task in the practice could be created, assigned
 * and closed from /tasks at the firm level, and a CA standing on a client's
 * page who wanted to note "chase for October bank statements" had to leave the
 * client, open the firm task screen, and pick the client back out of a
 * dropdown. The work happens here; the record of it belongs here.
 *
 * TaskFormModal is the SAME component /tasks uses, given defaultClientId — not
 * a second form. Two task forms drift, and the one that ends up missing a field
 * is whichever is edited less.
 */

const TASK_STATUS_COLORS: Record<string, string> = {
  todo: "bg-[#F1F5F9] text-[#475569]",
  in_progress: "bg-blue-100 text-blue-700",
  waiting_client: "bg-purple-100 text-purple-700",
  review_required: "bg-amber-100 text-amber-700",
  completed: "bg-green-100 text-green-700",
};

/** Where a task can go next. Closing is one click; the rest of the lifecycle
 *  stays on the firm screen, which has the detail panel for it. */
const NEXT_STATUS: Record<string, { to: string; label: string }> = {
  todo: { to: "in_progress", label: "Start" },
  in_progress: { to: "completed", label: "Done" },
  waiting_client: { to: "in_progress", label: "Resume" },
  review_required: { to: "completed", label: "Done" },
};

export default function TasksPage() {
  const { clientId } = useClientNav();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [client, setClient] = useState<Client | null>(null);
  const [teamMembers, setTeamMembers] = useState<FirmUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const today = new Date().toISOString().split("T")[0];

  const load = useCallback(() => {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true);
    Promise.all([
      getTasks({ clientId, limit: 100 }),
      // The modal needs the client record (it lists clients) and the team (to
      // assign). Both are small and independent, so they load beside the tasks
      // rather than on first open, where the CA would wait for them.
      getClient(clientId).catch(() => null),
      getTeamMembers().catch(() => [] as FirmUser[]),
    ])
      .then(([t, c, m]) => { setTasks(t); setClient(c); setTeamMembers(m); setLoadError(null); })
      .catch((e) => { setTasks([]); setLoadError(e instanceof Error ? e.message : "Couldn't load tasks."); })
      .finally(() => setLoading(false));
  }, [clientId]);

  useEffect(load, [load]);

  const advance = useCallback(async (task: Task) => {
    const next = NEXT_STATUS[task.status];
    if (!next) return;
    setBusy(task.id);
    setLoadError(null);
    try {
      await updateTaskStatus(task.id, next.to);
      // Optimism would be wrong here: a status change that RLS refused would
      // stay on screen looking done. Re-read instead.
      const fresh = await getTasks({ clientId, limit: 100 });
      setTasks(fresh);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Couldn't update the task.");
    } finally {
      setBusy(null);
    }
  }, [clientId]);

  const open = tasks.filter((t) => t.status !== "completed").length;

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <Card>
        <CardHeader className="pb-3 flex flex-row items-center justify-between space-y-0">
          <CardTitle className="text-sm">
            Tasks {loading ? "…" : `(${open} open of ${tasks.length})`}
          </CardTitle>
          <button
            onClick={() => setModalOpen(true)}
            className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
          >
            <Plus size={13} /> New task
          </button>
        </CardHeader>
        <CardContent>
          {loading ? (
            <TransactionListSkeleton rows={4} />
          ) : (
            <>
              {loadError && (
                <div className="mb-3 text-center py-3">
                  <p className="text-sm text-red-600 font-medium">{loadError}</p>
                  <button onClick={load} className="mt-2 text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]">
                    Retry
                  </button>
                </div>
              )}
              {tasks.length === 0 && !loadError ? (
                <p className="text-sm text-[#94A3B8] text-center py-8">No tasks for this client</p>
              ) : (
                <div className="divide-y divide-[#F8FAFC]">
                  {tasks.map((t) => {
                    const next = NEXT_STATUS[t.status];
                    return (
                      <div key={t.id} className="flex items-center gap-4 py-3">
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-[#0F172A]">{t.title}</p>
                          {t.description && (
                            <p className="text-xs text-[#64748B] mt-0.5">{t.description}</p>
                          )}
                        </div>
                        {t.due_date && (
                          <p
                            className={`text-xs shrink-0 ${
                              t.due_date < today && t.status !== "completed"
                                ? "text-red-600 font-medium"
                                : "text-[#64748B]"
                            }`}
                          >
                            {formatDate(t.due_date)}
                          </p>
                        )}
                        <Badge
                          className={`text-xs shrink-0 ${TASK_STATUS_COLORS[t.status] ?? "bg-[#F1F5F9] text-[#475569]"}`}
                        >
                          {t.status.replace(/_/g, " ")}
                        </Badge>
                        {next && (
                          <button
                            onClick={() => advance(t)}
                            disabled={busy === t.id}
                            className="shrink-0 flex items-center gap-1 text-[11px] border border-[#E2E8F0] rounded-md px-2 py-1 text-[#64748B] hover:bg-[#F1F5F9] disabled:opacity-50"
                          >
                            {busy === t.id
                              ? <Loader2 size={11} className="animate-spin" />
                              : <Check size={11} />}
                            {next.label}
                          </button>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <TaskFormModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        onSaved={(t) => { setTasks((prev) => [t, ...prev]); setModalOpen(false); }}
        clients={client ? [client] : []}
        teamMembers={teamMembers}
        defaultClientId={clientId}
      />
    </div>
  );
}
