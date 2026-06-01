import { getSupabaseClient } from "@/lib/supabase/client";
import type { Task } from "@/lib/types";

async function getFirmId(): Promise<string> {
  const sb = getSupabaseClient();
  const { data: { session } } = await sb.auth.getSession();
  if (!session) throw new Error("Not authenticated");
  const { data } = await sb.from("users").select("firm_id").eq("auth_user_id", session.user.id).single();
  if (!data) throw new Error("User not found");
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
