"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getTasks } from "@/lib/data/tasks";
import type { Task } from "@/lib/types";
import { formatDate } from "@/lib/services/formatting";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

const TASK_STATUS_COLORS: Record<string, string> = {
  todo: "bg-[#F1F5F9] text-[#475569]",
  in_progress: "bg-blue-100 text-blue-700",
  waiting_client: "bg-purple-100 text-purple-700",
  review_required: "bg-amber-100 text-amber-700",
  completed: "bg-green-100 text-green-700",
};

export default function TasksPage() {
  const { clientId } = useClientNav();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const today = new Date().toISOString().split("T")[0];

  const load = () => {
    if (!clientId || clientId === "_placeholder") return;
    setLoading(true);
    getTasks({ clientId, limit: 100 })
      .then((t) => { setTasks(t); setLoadError(null); })
      .catch((e) => { setTasks([]); setLoadError(e instanceof Error ? e.message : "Couldn't load tasks."); })
      .finally(() => setLoading(false));
  };

  useEffect(load, [clientId]);

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Tasks ({loading ? "…" : tasks.length})</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="h-32 animate-pulse bg-[#F8FAFC] rounded" />
          ) : loadError ? (
            <div className="text-center py-8">
              <p className="text-sm text-red-600 font-medium">{loadError}</p>
              <button onClick={load} className="mt-2 text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]">
                Retry
              </button>
            </div>
          ) : tasks.length === 0 ? (
            <p className="text-sm text-[#94A3B8] text-center py-8">No tasks for this client</p>
          ) : (
            <div className="divide-y divide-[#F8FAFC]">
              {tasks.map((t) => (
                <div key={t.id} className="flex items-center gap-4 py-3">
                  <div className="flex-1">
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
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
