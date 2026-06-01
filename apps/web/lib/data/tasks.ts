import { getSupabaseClient } from "@/lib/supabase/client";
import type { Task, TaskStatus, KanbanBoard } from "@/lib/types";

export type CreateTaskInput = {
  client_id: string;
  title: string;
  description?: string;
  priority: string;
  due_date?: string;
  tags?: string[];
};

async function getFirmId(): Promise<string> {
  const sb = getSupabaseClient();
  const { data: { session } } = await sb.auth.getSession();
  if (!session) throw new Error("Not authenticated");

  const { data, error } = await sb
    .from("users")
    .select("firm_id")
    .eq("auth_user_id", session.user.id)
    .single();

  if (error || !data) throw new Error("User not found in firm");
  return data.firm_id;
}

export async function getTasks(clientId?: string): Promise<Task[]> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();

  let query = sb
    .from("tasks")
    .select("*, clients(client_name)")
    .eq("firm_id", firmId)
    .is("deleted_at", null)
    .order("due_date", { nullsFirst: false });

  if (clientId) query = query.eq("client_id", clientId);

  const { data, error } = await query;
  if (error) throw new Error(error.message);

  return (data ?? []).map((t: Record<string, unknown>) => ({
    ...t,
    client_name: (t.clients as Record<string, string> | null)?.client_name ?? "",
  })) as Task[];
}

export async function createTask(input: CreateTaskInput): Promise<Task> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();

  const { data, error } = await sb
    .from("tasks")
    .insert({
      ...input,
      firm_id: firmId,
      status: "todo",
    })
    .select("*, clients(client_name)")
    .single();

  if (error) throw new Error(error.message);
  const t = data as Record<string, unknown>;
  return {
    ...t,
    client_name: (t.clients as Record<string, string> | null)?.client_name ?? "",
  } as Task;
}

export async function updateTaskStatus(id: string, status: TaskStatus): Promise<void> {
  const sb = getSupabaseClient();
  const updates: Record<string, unknown> = {
    status,
    updated_at: new Date().toISOString(),
  };
  if (status === "completed") updates.completed_at = new Date().toISOString();

  const { error } = await sb.from("tasks").update(updates).eq("id", id);
  if (error) throw new Error(error.message);
}

export async function updateTask(id: string, input: Partial<CreateTaskInput>): Promise<void> {
  const sb = getSupabaseClient();
  const { error } = await sb
    .from("tasks")
    .update({ ...input, updated_at: new Date().toISOString() })
    .eq("id", id);
  if (error) throw new Error(error.message);
}

export async function deleteTask(id: string): Promise<void> {
  const sb = getSupabaseClient();
  const { error } = await sb
    .from("tasks")
    .update({ deleted_at: new Date().toISOString() })
    .eq("id", id);
  if (error) throw new Error(error.message);
}

export function groupByStatus(tasks: Task[]): KanbanBoard {
  const board: KanbanBoard = {
    todo: [], in_progress: [], waiting_client: [], review_required: [], completed: [],
  };
  for (const t of tasks) {
    const col = t.status as TaskStatus;
    if (col in board) board[col].push(t);
  }
  return board;
}
