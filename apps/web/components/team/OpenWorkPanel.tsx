"use client";

/**
 * Who has which open task, and the work nobody has — with the reassign flow
 * (practice_management-24).
 *
 * THIS IS WHAT THE RETIRED `/team/work-allocation` SCREEN WAS FOR, ON THE ONE
 * CAPACITY MODEL. That screen divided a count of open tasks by a per-role
 * constant held in the browser (Partner 20, Manager 30, ...) and wrote the
 * reassignment straight over PostgREST — so `rbac()` never saw it, the assignee
 * was told nothing, and only one of the task's two assignee columns moved.
 * Everything here comes from `GET /api/workload` — the same payload as the
 * member cards above it, so the two cannot disagree — and a reassignment goes
 * through `PATCH /api/tasks/{id}`.
 *
 * NOTHING IS WORKED OUT HERE. The counts, each person's estimated hours and the
 * tasks that carry no estimate are the server's; the lists are what it chose to
 * send (earliest due first), and a person with more open tasks than fit says how
 * many are not shown rather than implying the list is the whole of their work.
 */
import { useState } from "react";
import { UserX, X } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Callout } from "@/components/ui/callout";
import { arrayOrEmpty, objectOrNull } from "@/lib/api/shape";
import { formatDuration } from "@/lib/data/timeTracking";
import { todayLocalISO } from "@/lib/dateMath";
import { formatDate } from "@/lib/services/formatting";
import type { Client, UnassignedWork, WorkloadMember, WorkloadTask } from "@/lib/types";

const PRIORITY_BADGE: Record<string, string> = {
  critical: "bg-sev-critical-surface text-sev-critical",
  high: "bg-sev-high-surface text-sev-high",
  medium: "bg-sev-medium-surface text-sev-medium",
  low: "bg-sev-low-surface text-sev-low",
};

function Estimate({ minutes, without }: { minutes: number; without: number }) {
  if (minutes === 0 && without === 0) return null;
  return (
    <span className="text-2xs text-ps-label">
      {minutes > 0 ? `${formatDuration(minutes)} estimated` : "no estimates recorded"}
      {without > 0 && minutes > 0 ? ` · ${without} with none` : ""}
    </span>
  );
}

function ReassignModal({ task, members, onClose, onReassigned }: {
  task: WorkloadTask;
  members: WorkloadMember[];
  onClose: () => void;
  onReassigned: () => void;
}) {
  const [targetId, setTargetId] = useState(members[0]?.user_id ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirm() {
    if (!targetId) return;
    setSaving(true);
    setError(null);
    try {
      // The API door: it checks the assignee is in this firm, moves both of the
      // task's assignee columns, writes the timeline and tells the new assignee.
      const res = await api.tasks.update(task.id, { assigned_to: targetId });
      const answer = objectOrNull<{ success?: boolean; error?: string }>(res);
      if (answer?.success === false) {
        throw new Error(answer.error || "The task was not reassigned.");
      }
      onReassigned();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "The task was not reassigned.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-brand-dark/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-ps-ink">Reassign task</h3>
          <button onClick={onClose} aria-label="Close" className="text-ps-hint hover:text-ps-label"><X size={16} /></button>
        </div>
        <p className="text-sm text-ps-label">{task.title ?? "Untitled task"}</p>
        {error && <Callout tone="problem">{error}</Callout>}
        <div>
          <label htmlFor="reassign-to" className="text-xs font-medium text-ps-body block mb-1">Reassign to:</label>
          <select id="reassign-to" value={targetId} onChange={(e) => setTargetId(e.target.value)}
            className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm outline-none focus:border-brand">
            {members.map((m) => <option key={m.user_id} value={m.user_id}>{m.user_name} ({m.role})</option>)}
          </select>
        </div>
        <div className="flex gap-2 justify-end">
          <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
          <Button size="sm" onClick={confirm} disabled={saving || !targetId}>{saving ? "Saving…" : "Confirm"}</Button>
        </div>
      </div>
    </div>
  );
}

function TaskRow({ task, clientName, today, onPick }: {
  task: WorkloadTask;
  clientName: string | undefined;
  today: string;
  onPick: (t: WorkloadTask) => void;
}) {
  const overdue = !!task.due_date && task.due_date < today;
  return (
    <button onClick={() => onPick(task)}
      className="w-full flex items-center justify-between gap-2 text-left px-2 py-1.5 rounded-lg hover:bg-ps-bg">
      <div className="min-w-0">
        <p className="text-xs text-ps-ink truncate">{task.title ?? "Untitled task"}</p>
        {clientName && <p className="text-xs text-ps-hint truncate">{clientName}</p>}
      </div>
      <div className="shrink-0 flex items-center gap-2">
        {task.estimated_minutes ? (
          <span className="text-xs text-ps-hint">{formatDuration(task.estimated_minutes)}</span>
        ) : null}
        <span className={`text-xs ${overdue ? "text-state-problem" : "text-ps-hint"}`}>
          {task.due_date ? formatDate(task.due_date) : "no date"}
        </span>
        <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${PRIORITY_BADGE[task.priority ?? ""] ?? "bg-ps-muted text-ps-label"}`}>
          {task.priority?.[0]?.toUpperCase() ?? "–"}
        </span>
      </div>
    </button>
  );
}

export function OpenWorkPanel({ members, unassigned, clients, onChanged }: {
  members: WorkloadMember[];
  unassigned: UnassignedWork | undefined;
  clients: Client[];
  onChanged: () => void;
}) {
  const [picked, setPicked] = useState<{ task: WorkloadTask; from: string | null } | null>(null);
  const clientName = new Map(clients.map((c) => [c.id, c.client_name]));
  const today = todayLocalISO();
  const shownUnassigned = arrayOrEmpty<WorkloadTask>(unassigned?.tasks);
  const withWork = members.filter((m) => m.active_tasks > 0);

  return (
    <>
      {/* ALWAYS in the DOM, so a link that scrolls here before the fetch resolves
          still finds something to scroll to. */}
      <div id="unassigned-tasks">
        {unassigned && unassigned.count > 0 && (
          <Card className="border-state-attention-border">
            <CardContent className="py-4 px-5 space-y-3">
              <div className="flex items-center justify-between gap-3 flex-wrap">
                <div className="flex items-center gap-2">
                  <UserX size={15} className="text-state-attention" />
                  <p className="font-semibold text-ps-ink text-sm">Unassigned ({unassigned.count})</p>
                </div>
                <span className="text-xs text-ps-hint">
                  No assignee — in no one&apos;s count above.{" "}
                  <Estimate minutes={unassigned.estimated_minutes} without={unassigned.without_estimate} />
                </span>
              </div>
              <div className="space-y-1 max-h-64 overflow-y-auto">
                {shownUnassigned.map((t) => (
                  <TaskRow key={t.id} task={t} today={today}
                    clientName={t.client_id ? clientName.get(t.client_id) : undefined}
                    onPick={(task) => setPicked({ task, from: null })} />
                ))}
                {unassigned.count > shownUnassigned.length && (
                  <p className="text-xs text-ps-hint text-center py-1">
                    Showing the {shownUnassigned.length} due soonest of {unassigned.count}.
                  </p>
                )}
              </div>
            </CardContent>
          </Card>
        )}
      </div>

      <div id="open-tasks" className="space-y-3">
        {withWork.length > 0 && (
          <h2 className="text-sm font-semibold text-ps-body">Open work by person</h2>
        )}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {withWork.map((m) => {
            const shown = arrayOrEmpty<WorkloadTask>(m.open_tasks);
            return (
              <Card key={m.user_id}>
                <CardContent className="py-4 px-5 space-y-2">
                  <div className="flex items-baseline justify-between gap-2">
                    <p className="text-sm font-semibold text-ps-ink truncate">{m.user_name}</p>
                    <span className="text-2xs text-ps-hint shrink-0">{m.active_tasks} open</span>
                  </div>
                  <Estimate minutes={m.estimated_open_minutes ?? 0} without={m.open_tasks_without_estimate ?? 0} />
                  <div className="space-y-1 max-h-48 overflow-y-auto">
                    {shown.map((t) => (
                      <TaskRow key={t.id} task={t} today={today}
                        clientName={t.client_id ? clientName.get(t.client_id) : undefined}
                        onPick={(task) => setPicked({ task, from: m.user_id })} />
                    ))}
                    {m.active_tasks > shown.length && (
                      <p className="text-xs text-ps-hint text-center py-1">
                        +{m.active_tasks - shown.length} more, later due
                      </p>
                    )}
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>

      {picked && (
        <ReassignModal
          task={picked.task}
          members={members.filter((m) => m.user_id !== picked.from)}
          onClose={() => setPicked(null)}
          onReassigned={() => { setPicked(null); onChanged(); }}
        />
      )}
    </>
  );
}
