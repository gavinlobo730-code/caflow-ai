"use client";

import { useState, useEffect, useCallback } from "react";
import {
  AlertTriangle, TrendingDown, Activity, Users,
  Loader2, RefreshCw, Pencil, X,
} from "lucide-react";
import { api } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getTeamWorkload } from "@/lib/data/analytics";
import type { TeamWorkload, WorkloadMember } from "@/lib/types";
import { Callout } from "@/components/ui/callout";

function UtilisationBar({ pct }: { pct: number }) {
  const clamped = Math.min(100, Math.max(0, pct));
  const color =
    clamped > 90 ? "bg-red-500" :
    clamped > 70 ? "bg-amber-400" :
    clamped < 20 ? "bg-gray-300" :
    "bg-green-500";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-ps-muted rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${clamped}%` }} />
      </div>
      <span className="text-2xs text-ps-label w-8 text-right">{clamped}%</span>
    </div>
  );
}

function fmtHours(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

function CapacityModal({ member, onClose, onSaved }: {
  member: WorkloadMember;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [weeklyHours, setWeeklyHours] = useState(String(member.weekly_capacity_hours));
  const [maxTasks, setMaxTasks] = useState(String(member.max_concurrent_tasks));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSave() {
    const hours = parseInt(weeklyHours);
    const tasks = parseInt(maxTasks);
    if (!hours || hours < 1 || !tasks || tasks < 1) {
      setError("Enter valid values (minimum 1)");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.workload.setCapacity({
        user_id: member.user_id,
        weekly_capacity_hours: hours,
        max_concurrent_tasks: tasks,
      });
      onSaved();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to save capacity");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-brand-dark/60 p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-sm p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold text-ps-ink">Edit Capacity — {member.user_name}</h2>
          <button onClick={onClose} className="text-ps-hint hover:text-ps-label">
            <X size={18} />
          </button>
        </div>
        {error && <Callout tone="problem">{error}</Callout>}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium text-ps-body mb-1">Weekly Hours</label>
            <input
              type="number" min="1" max="100"
              value={weeklyHours}
              onChange={e => setWeeklyHours(e.target.value)}
              className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/30"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-ps-body mb-1">Max Concurrent Tasks</label>
            <input
              type="number" min="1" max="100"
              value={maxTasks}
              onChange={e => setMaxTasks(e.target.value)}
              className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/30"
            />
          </div>
        </div>
        <div className="flex gap-2 justify-end pt-1">
          <Button variant="outline" size="sm" onClick={onClose}>Cancel</Button>
          <Button size="sm" onClick={handleSave} disabled={saving}>
            {saving ? <Loader2 className="animate-spin mr-1" size={13} /> : null}
            Save
          </Button>
        </div>
      </div>
    </div>
  );
}

function MemberCard({ member, onEditCapacity }: { member: WorkloadMember; onEditCapacity: (m: WorkloadMember) => void }) {
  const initials = member.user_name.split(" ").map(n => n[0]).join("").slice(0, 2).toUpperCase();
  return (
    <Card className={`transition-shadow hover:shadow-md ${
      member.is_overloaded ? "border-red-200 bg-red-50/30" :
      member.is_underutilised ? "border-amber-200 bg-amber-50/20" :
      ""
    }`}>
      <CardContent className="py-4 px-5 space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-600 to-blue-400 text-white flex items-center justify-center text-2xs font-bold shrink-0">
              {initials}
            </div>
            <div className="min-w-0">
              <p className="text-sm font-semibold text-ps-ink truncate">{member.user_name}</p>
              <p className="text-2xs text-ps-label">{member.role}</p>
            </div>
          </div>
          <div className="flex gap-1 shrink-0">
            {member.is_overloaded && (
              <Badge className="text-3xs px-1.5 py-0 bg-red-100 text-red-700 gap-0.5">
                <AlertTriangle size={9} /> Overloaded
              </Badge>
            )}
            {member.is_underutilised && !member.is_overloaded && (
              <Badge className="text-3xs px-1.5 py-0 bg-amber-100 text-amber-700 gap-0.5">
                <TrendingDown size={9} /> Underutilised
              </Badge>
            )}
            <button
              onClick={() => onEditCapacity(member)}
              title="Edit capacity"
              className="p-1 rounded text-ps-disabled hover:text-blue-600 hover:bg-blue-50 transition-colors"
            >
              <Pencil size={12} />
            </button>
          </div>
        </div>

        <UtilisationBar pct={member.utilisation_pct} />
        <p className="text-2xs text-ps-label">
          {fmtHours(member.minutes_logged_this_week)} logged of {member.weekly_capacity_hours}h weekly capacity
          · max {member.max_concurrent_tasks} tasks
        </p>

        <div className="grid grid-cols-4 gap-2 text-center">
          <div>
            <p className="text-[18px] font-bold text-ps-ink">{member.active_tasks}</p>
            <p className="text-3xs text-ps-hint">Active</p>
          </div>
          <div>
            <p className={`text-[18px] font-bold ${member.overdue_tasks > 0 ? "text-red-600" : "text-ps-ink"}`}>
              {member.overdue_tasks}
            </p>
            <p className="text-3xs text-ps-hint">Overdue</p>
          </div>
          <div>
            <p className="text-[18px] font-bold text-ps-ink">{member.due_this_week}</p>
            <p className="text-3xs text-ps-hint">This Week</p>
          </div>
          <div>
            <p className="text-[18px] font-bold text-green-600">{member.completed_this_week}</p>
            <p className="text-3xs text-ps-hint">Completed</p>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export default function WorkloadPage() {
  const [workload, setWorkload] = useState<TeamWorkload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingMember, setEditingMember] = useState<WorkloadMember | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getTeamWorkload();
      setWorkload(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load workload data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const overloaded = workload?.members?.filter(m => m.is_overloaded) ?? [];
  const underutilised = workload?.members?.filter(m => m.is_underutilised) ?? [];
  const healthy = workload?.members?.filter(m => !m.is_overloaded && !m.is_underutilised) ?? [];

  return (
    <div className="p-6 space-y-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-ps-ink">Team Workload</h1>
          <p className="text-sm text-ps-label mt-0.5">Capacity and task distribution across the team</p>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading} className="gap-1.5">
          <RefreshCw size={13} className={loading ? "animate-spin" : ""} /> Refresh
        </Button>
      </div>

      {error && <Callout tone="problem">{error}</Callout>}

      {loading && !workload ? (
        <div className="flex items-center justify-center py-20 text-ps-hint">
          <Loader2 className="animate-spin mr-2" size={18} /> Loading workload data…
        </div>
      ) : workload ? (
        <>
          {/* Summary stats */}
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <Card>
              <CardContent className="py-4">
                <p className="text-xs text-ps-label">Team Members</p>
                <p className="text-2xl font-bold text-ps-ink mt-1">{workload.members?.length ?? 0}</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="py-4">
                <p className="text-xs text-ps-label">Active Tasks</p>
                <p className="text-2xl font-bold text-ps-ink mt-1">{workload.total_active_tasks}</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="py-4">
                <p className="text-xs text-ps-label">Overdue Tasks</p>
                <p className={`text-2xl font-bold mt-1 ${workload.total_overdue_tasks > 0 ? "text-red-600" : "text-ps-ink"}`}>
                  {workload.total_overdue_tasks}
                </p>
              </CardContent>
            </Card>
            <Card className={workload.overloaded_count > 0 ? "border-red-200" : ""}>
              <CardContent className="py-4">
                <p className="text-xs text-ps-label">Overloaded</p>
                <p className={`text-2xl font-bold mt-1 ${workload.overloaded_count > 0 ? "text-red-600" : "text-ps-ink"}`}>
                  {workload.overloaded_count}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="py-4">
                <p className="text-xs text-ps-label">Avg Utilisation</p>
                <p className="text-2xl font-bold text-ps-ink mt-1">{workload.avg_utilisation_pct}%</p>
              </CardContent>
            </Card>
          </div>

          {/* Alerts */}
          {(overloaded.length > 0 || underutilised.length > 0) && (
            <div className="space-y-2">
              {overloaded.length > 0 && (
                <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
                  <AlertTriangle size={14} className="text-red-500 mt-0.5 shrink-0" />
                  <p className="text-sm text-red-700">
                    <strong>{overloaded.map(m => m.user_name).join(", ")}</strong>
                    {overloaded.length === 1 ? " is" : " are"} overloaded. Consider redistributing tasks.
                  </p>
                </div>
              )}
              {underutilised.length > 0 && (
                <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
                  <TrendingDown size={14} className="text-amber-500 mt-0.5 shrink-0" />
                  <p className="text-sm text-amber-700">
                    <strong>{underutilised.map(m => m.user_name).join(", ")}</strong>
                    {underutilised.length === 1 ? " has" : " have"} low workload and can take on more tasks.
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Member cards — grouped */}
          {overloaded.length > 0 && (
            <div className="space-y-3">
              <h2 className="text-sm font-semibold text-red-700 flex items-center gap-1.5">
                <AlertTriangle size={13} /> Overloaded ({overloaded.length})
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {overloaded.map(m => <MemberCard key={m.user_id} member={m} onEditCapacity={setEditingMember} />)}
              </div>
            </div>
          )}

          {healthy.length > 0 && (
            <div className="space-y-3">
              <h2 className="text-sm font-semibold text-ps-body flex items-center gap-1.5">
                <Activity size={13} /> Healthy Workload ({healthy.length})
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {healthy.map(m => <MemberCard key={m.user_id} member={m} onEditCapacity={setEditingMember} />)}
              </div>
            </div>
          )}

          {underutilised.length > 0 && (
            <div className="space-y-3">
              <h2 className="text-sm font-semibold text-amber-700 flex items-center gap-1.5">
                <TrendingDown size={13} /> Underutilised ({underutilised.length})
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {underutilised.map(m => <MemberCard key={m.user_id} member={m} onEditCapacity={setEditingMember} />)}
              </div>
            </div>
          )}

          {workload.members?.length === 0 && (
            <Card>
              <CardContent className="py-16 text-center text-ps-hint">
                <Users size={32} className="mx-auto mb-3 opacity-30" />
                <p>No team members found. Add team members to see workload data.</p>
              </CardContent>
            </Card>
          )}
        </>
      ) : null}

      {editingMember && (
        <CapacityModal
          member={editingMember}
          onClose={() => setEditingMember(null)}
          onSaved={() => { setEditingMember(null); load(); }}
        />
      )}
    </div>
  );
}
