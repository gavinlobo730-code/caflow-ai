import { getSupabaseClient } from "@/lib/supabase/client";
import type { TaskTemplate, Task, ApiResponse } from "@/lib/types";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<ApiResponse<T>> {
  const { data: { session } } = await getSupabaseClient().auth.getSession();
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {}),
      ...(init?.headers ?? {}),
    },
  });
  return res.json();
}

export async function listTaskTemplates(): Promise<{ templates: TaskTemplate[]; total: number }> {
  const resp = await apiFetch<{ templates: TaskTemplate[]; total: number }>("/api/task-templates");
  if (!resp.success) throw new Error(resp.error ?? "Failed to load templates");
  return resp.data;
}

export async function getTaskTemplate(id: string): Promise<TaskTemplate> {
  const resp = await apiFetch<{ template: TaskTemplate }>(`/api/task-templates/${id}`);
  if (!resp.success) throw new Error(resp.error ?? "Template not found");
  return resp.data.template;
}

export async function createTaskTemplate(payload: {
  name: string;
  description?: string;
  default_priority?: string;
  estimated_hours?: number;
  tags?: string[];
  default_assignee_role?: string;
}): Promise<TaskTemplate> {
  const resp = await apiFetch<{ template: TaskTemplate }>("/api/task-templates", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!resp.success) throw new Error(resp.error ?? "Failed to create template");
  return resp.data.template;
}

export async function updateTaskTemplate(id: string, payload: Partial<{
  name: string;
  description: string;
  default_priority: string;
  estimated_hours: number;
  tags: string[];
  default_assignee_role: string;
}>): Promise<TaskTemplate> {
  const resp = await apiFetch<{ template: TaskTemplate }>(`/api/task-templates/${id}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  if (!resp.success) throw new Error(resp.error ?? "Failed to update template");
  return resp.data.template;
}

export async function deleteTaskTemplate(id: string): Promise<void> {
  const resp = await apiFetch<null>(`/api/task-templates/${id}`, { method: "DELETE" });
  if (!resp.success) throw new Error(resp.error ?? "Failed to delete template");
}

export async function instantiateTemplate(id: string, payload: {
  client_id: string;
  assigned_to?: string;
  due_date?: string;
  title?: string;
}): Promise<Task> {
  const resp = await apiFetch<{ task: Task }>(`/api/task-templates/${id}/instantiate`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!resp.success) throw new Error(resp.error ?? "Failed to instantiate template");
  return resp.data.task;
}
