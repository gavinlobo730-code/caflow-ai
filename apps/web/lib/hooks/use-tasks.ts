"use client";

import { useState, useEffect, useCallback } from "react";
import { taskRepository } from "@/lib/repositories/task.repository";
import type { Task, KanbanBoard } from "@/lib/types";

export function useTasks(params?: { client_id?: string; status?: string }) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const clientId = params?.client_id;
  const status = params?.status;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setTasks(await taskRepository.list(clientId || status ? { client_id: clientId, status } : undefined));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load tasks");
    } finally {
      setLoading(false);
    }
  }, [clientId, status]);

  useEffect(() => { load(); }, [load]);

  return { tasks, loading, error, reload: load };
}

export function useKanban() {
  const [board, setBoard] = useState<KanbanBoard>({
    todo: [], in_progress: [], waiting_client: [], review_required: [], completed: []
  });
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    taskRepository.kanban()
      .then(setBoard)
      .finally(() => setLoading(false));
  }, []);

  const moveTask = useCallback(async (taskId: string, newStatus: string) => {
    await taskRepository.updateStatus(taskId, newStatus);
    const updated = await taskRepository.kanban();
    setBoard(updated);
  }, []);

  return { board, setBoard, loading, moveTask };
}
