"use client";

import { useState, useEffect } from "react";
import { complianceRepository } from "@/lib/repositories/compliance.repository";
import type { ComplianceTask } from "@/lib/types";

export function useComplianceCalendar() {
  const [events, setEvents] = useState<ComplianceTask[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    complianceRepository.calendar()
      .then(setEvents)
      .finally(() => setLoading(false));
  }, []);

  return { events, loading };
}

export function useComplianceTasks(clientId?: string) {
  const [tasks, setTasks] = useState<ComplianceTask[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    complianceRepository.list(clientId ? { client_id: clientId } : undefined)
      .then(setTasks)
      .finally(() => setLoading(false));
  }, [clientId]);

  return { tasks, loading };
}
