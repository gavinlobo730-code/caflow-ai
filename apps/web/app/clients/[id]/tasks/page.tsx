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

  const today = new Date().toISOString().split("T")[0];

  useEffect(() => {
    if (!clientId || clientId === "_placeholder") return;
    getTasks({ clientId, limit: 100 })
      .catch(() => [] as Task[])
      .then(setTasks)
      .finally(() => setLoading(false));
  }, [clientId]);

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Tasks ({loading ? "…" : tasks.length})</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="h-32 animate-pulse bg-[#F8FAFC] rounded" />
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
