import { getSupabaseClient } from "@/lib/supabase/client";
import type { Task, KanbanBoard, FirmUser } from "@/lib/types";

export interface CreateTaskInput {
  client_id: string;
  title: string;
  description?: string;
  status?: string;
  priority: string;
  assigned_to?: string;
  assignee_id?: string;
  due_date?: string;
  task_type?: string;
}

async function getFirmId(): Promise<string> {
  const sb = getSupabaseClient();
  const { data: { session } } = await sb.auth.getSession();
  if (!session) throw new Error("Not authenticated");
  const { data } = await sb.from("users").select("firm_id").eq("auth_user_id", session.user.id).maybeSingle();
  if (!data?.firm_id) throw new Error("No firm found for this user");
  return data.firm_id;
}

export async function getTasks(clientId?: string): Promise<Task[]> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();
  let q = sb.from("tasks").select("*").eq("firm_id", firmId).order("created_at", { ascending: false });
  if (clientId) q = q.eq("client_id", clientId);
  const { data, error } = await q;
  if (error) throw new Error(error.message);
  return (data ?? []) as Task[];
}

export async function updateTaskStatus(id: string, status: string): Promise<void> {
  const sb = getSupabaseClient();
  await sb.from("tasks").update({ status, updated_at: new Date().toISOString() }).eq("id", id);
}

export async function deleteTask(id: string): Promise<void> {
  const sb = getSupabaseClient();
  await sb.from("tasks").delete().eq("id", id);
}

export function groupByStatus(tasks: Task[]): KanbanBoard {
  const board: KanbanBoard = { todo: [], in_progress: [], waiting_client: [], review_required: [], completed: [] };
  for (const t of tasks) {
    const col = t.status as keyof KanbanBoard;
    if (col in board) board[col].push(t);
  }
  return board;
}

export async function getTeamMembers(): Promise<FirmUser[]> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();
  const { data, error } = await sb
    .from("users")
    .select("id, auth_user_id, firm_id, full_name, email, role, is_active")
    .eq("firm_id", firmId)
    .order("full_name");
  if (error) throw new Error(error.message);
  return (data ?? []) as FirmUser[];
}

export async function updateTask(id: string, input: Partial<CreateTaskInput>): Promise<void> {
  const sb = getSupabaseClient();
  await sb.from("tasks").update({ ...input, updated_at: new Date().toISOString() }).eq("id", id);
}

export async function createTask(input: CreateTaskInput): Promise<Task> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();
  const { data, error } = await sb.from("tasks").insert({
    ...input,
    firm_id: firmId,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  }).select().single();
  if (error || !data) throw new Error(error?.message ?? "Failed to create task");
  return data as Task;
}
