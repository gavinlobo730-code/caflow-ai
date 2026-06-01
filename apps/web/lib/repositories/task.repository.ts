import { api } from "@/lib/api";
import type { Task, KanbanBoard, ApiResponse } from "@/lib/types";

export const taskRepository = {
  async list(params?: { client_id?: string; status?: string }): Promise<Task[]> {
    const res = await api.tasks.list(params) as ApiResponse<{ tasks: Task[] }>;
    return res.success ? res.data.tasks : [];
  },

  async kanban(): Promise<KanbanBoard> {
    const res = await api.tasks.kanban() as ApiResponse<{ kanban: KanbanBoard }>;
    return res.success
      ? res.data.kanban
      : { todo: [], in_progress: [], waiting_client: [], review_required: [], completed: [] };
  },

  async create(data: Partial<Task>): Promise<Task | null> {
    try {
      const res = await api.tasks.create(data) as ApiResponse<{ task: Task }>;
      return res.success ? res.data.task : null;
    } catch {
      return null;
    }
  },

  async updateStatus(id: string, status: string): Promise<Task | null> {
    try {
      const res = await api.tasks.update(id, { status }) as ApiResponse<{ task: Task }>;
      return res.success ? res.data.task : null;
    } catch {
      return null;
    }
  },
};
