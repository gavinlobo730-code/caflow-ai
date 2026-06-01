"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import type { DashboardSummary, ApiResponse } from "@/lib/types";

const FALLBACK: DashboardSummary = {
  active_clients: 24,
  tasks_due_today: 3,
  overdue_tasks: 4,
  waiting_client: 2,
  review_required: 1,
  total_open_tasks: 10,
};

export function useDashboard() {
  const [summary, setSummary] = useState<DashboardSummary>(FALLBACK);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    (api.tasks.dashboardSummary() as Promise<ApiResponse<DashboardSummary>>)
      .then((res) => { if (res.success) setSummary(res.data); })
      .catch(() => { /* use fallback */ })
      .finally(() => setLoading(false));
  }, []);

  return { summary, loading };
}
