"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { getTasks } from "@/lib/data/tasks";
import type { Task } from "@/lib/types";
import { formatDate } from "@/lib/services/formatting";
import { useClientNav } from "@/lib/workspace/ClientNavContext";

const TASK_STATUS_COLORS: Record<string, string> = {
  todo: "bg-white/[0.06] text-white/55",
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
    getTasks(clientId)
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
            <div className="h-32 animate-pulse bg-[#0e1017] rounded" />
          ) : tasks.length === 0 ? (
            <p className="text-sm text-white/30 text-center py-8">No tasks for this client</p>
          ) : (
            <div className="divide-y divide-white/[0.03]">
              {tasks.map((t) => (
                <div key={t.id} className="flex items-center gap-4 py-3">
                  <div className="flex-1">
                    <p className="text-sm font-medium text-white/85">{t.title}</p>
                    {t.description && (
                      <p className="text-xs text-white/40 mt-0.5">{t.description}</p>
                    )}
                  </div>
                  {t.due_date && (
                    <p
                      className={`text-xs shrink-0 ${
                        t.due_date < today && t.status !== "completed"
                          ? "text-red-600 font-medium"
                          : "text-white/40"
                      }`}
                    >
                      {formatDate(t.due_date)}
                    </p>
                  )}
                  <Badge
                    className={`text-xs shrink-0 ${TASK_STATUS_COLORS[t.status] ?? "bg-white/[0.06] text-white/55"}`}
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
