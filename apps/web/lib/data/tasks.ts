import { getFirmId } from "./getFirmId";
import { getSupabaseClient } from "@/lib/supabase/client";
import type { Task, KanbanBoard, FirmUser } from "@/lib/types";
import { todayLocalISO, toLocalISO } from "@/lib/dateMath";

// ---------------------------------------------------------------------------
// Dev-mode query timing — logs to console in development, silent in production.
// ---------------------------------------------------------------------------
function devTime(label: string, startMs: number) {
  if (process.env.NODE_ENV === "development") {
    // eslint-disable-next-line no-console
    console.debug(`[PracticeSync/query] ${label}: ${Date.now() - startMs}ms`);
  }
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TaskQueryOptions {
  /** Filter by client UUID. */
  clientId?: string;
  /** Matches the assigned_to column (auth_user_id or email). */
  assignedTo?: string;
  /** Matches the assignee_id column (users table UUID). Combined with assignedTo via OR. */
  assigneeId?: string;
  /** Exact status match. */
  status?: string;
  /** Exclude this status (e.g. "completed"). */
  excludeStatus?: string;
  /** due_date = YYYY-MM-DD (exact). */
  dueDate?: string;
  /** due_date < X — pass today's date for overdue. */
  dueBefore?: string;
  /** due_date >= X. */
  dueAfter?: string;
  /** due_date <= X (combine with dueAfter for a week range). */
  dueOnOrBefore?: string;
  /** Maximum rows to return. Default 50. */
  limit?: number;
  /** Row offset for pagination. Default 0. */
  offset?: number;
}

export interface TaskCounts {
  /** Non-completed tasks assigned to the user. */
  active: number;
  /** Non-completed tasks whose due_date = today. */
  due_today: number;
  /** Non-completed tasks whose due_date < today. */
  overdue: number;
  /** Tasks completed in the last 7 days. */
  completed_recent: number;
}

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

// ---------------------------------------------------------------------------
// Queries
// ---------------------------------------------------------------------------

/**
 * Returns aggregate counts for a user's tasks using COUNT(*) queries so the
 * dashboard can show accurate totals without fetching full task records.
 * Four lightweight queries run in parallel; the slowest one determines latency.
 */
export async function getTaskCounts(assignedTo?: string, assigneeId?: string): Promise<TaskCounts> {
  const t0 = Date.now();
  const sb = getSupabaseClient();
  const firmId = await getFirmId();
  const today = todayLocalISO();
  const sevenDaysAgo = toLocalISO(new Date(Date.now() - 7 * 24 * 60 * 60 * 1000));

  // Factory: base query with firm isolation and optional assignee filter.
  // Returns a fresh builder each call so each COUNT is independent.
  function base() {
    let q = sb
      .from("tasks")
      .select("*", { count: "exact", head: true })
      .eq("firm_id", firmId)
      .is("deleted_at", null);
    if (assignedTo || assigneeId) {
      const parts: string[] = [];
      if (assignedTo) parts.push(`assigned_to.eq.${assignedTo}`);
      if (assigneeId) parts.push(`assignee_id.eq.${assigneeId}`);
      q = q.or(parts.join(","));
    }
    return q;
  }

  const [activeRes, todayRes, overdueRes, completedRes] = await Promise.all([
    base().neq("status", "completed"),
    base().neq("status", "completed").eq("due_date", today),
    base().neq("status", "completed").lt("due_date", today),
    base().eq("status", "completed").gte("updated_at", sevenDaysAgo),
  ]);

  devTime("getTaskCounts (4× COUNT parallel)", t0);

  return {
    active: activeRes.count ?? 0,
    due_today: todayRes.count ?? 0,
    overdue: overdueRes.count ?? 0,
    completed_recent: completedRes.count ?? 0,
  };
}

/**
 * Fetches tasks with server-side filtering and pagination.
 *
 * client_name is resolved via a single FK join (clients!client_id) so no
 * separate getClients() call is needed at the call site.
 */
export async function getTasks(options: TaskQueryOptions = {}): Promise<Task[]> {
  const {
    clientId, assignedTo, assigneeId, status, excludeStatus,
    dueDate, dueBefore, dueAfter, dueOnOrBefore,
    limit = 50, offset = 0,
  } = options;

  const t0 = Date.now();
  const sb = getSupabaseClient();
  const firmId = await getFirmId();

  // Fetch task columns + client name in one join.
  // Ordered by due_date ASC NULLS LAST so urgent tasks surface first.
  let q = sb
    .from("tasks")
    .select(`
      id, title, status, priority, assigned_to, assignee_id,
      due_date, client_id, task_type, description, created_at, updated_at,
      client:clients!client_id ( client_name )
    `)
    .eq("firm_id", firmId)
    .is("deleted_at", null)
    .order("due_date", { ascending: true, nullsFirst: false })
    .order("created_at", { ascending: false })
    .range(offset, offset + limit - 1);

  if (clientId) q = q.eq("client_id", clientId);
  if (assignedTo || assigneeId) {
    const parts: string[] = [];
    if (assignedTo) parts.push(`assigned_to.eq.${assignedTo}`);
    if (assigneeId) parts.push(`assignee_id.eq.${assigneeId}`);
    q = q.or(parts.join(","));
  }
  if (status) q = q.eq("status", status);
  if (excludeStatus) q = q.neq("status", excludeStatus);
  if (dueDate) q = q.eq("due_date", dueDate);
  if (dueBefore) q = q.lt("due_date", dueBefore);
  if (dueAfter) q = q.gte("due_date", dueAfter);
  if (dueOnOrBefore) q = q.lte("due_date", dueOnOrBefore);

  const { data, error } = await q;
  if (error) throw new Error(error.message);

  devTime(
    `getTasks (limit=${limit} offset=${offset} assigned=${!!assignedTo} client=${!!clientId})`,
    t0,
  );

  // Flatten the nested FK join: { client: { client_name } } → client_name at top level.
  return (data ?? []).map((row) => {
    const { client, ...rest } = row as Record<string, unknown>;
    const base = rest as unknown as Task;
    return {
      ...base,
      client_name: (client as { client_name?: string } | null)?.client_name ?? base.client_name,
    };
  });
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

export async function updateTaskStatus(id: string, status: string): Promise<void> {
  const sb = getSupabaseClient();
  await sb.from("tasks").update({ status, updated_at: new Date().toISOString() }).eq("id", id);
}

export async function deleteTask(id: string): Promise<void> {
  const sb = getSupabaseClient();
  await sb.from("tasks").delete().eq("id", id);
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

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

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
