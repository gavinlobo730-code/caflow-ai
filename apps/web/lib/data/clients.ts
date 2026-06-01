/**
 * Client data layer — reads/writes directly to Supabase from the frontend.
 * Firm isolation is enforced by RLS (firm_id = get_my_firm_id()).
 */
import { getSupabaseClient } from "@/lib/supabase/client";
import type { Client } from "@/lib/types";

export type CreateClientInput = {
  client_name: string;
  entity_type: string;
  pan: string;
  gstin?: string;
  mobile?: string;
  email?: string;
  city?: string;
  state?: string;
  state_code?: string;
  pincode?: string;
  address_line1?: string;
  gst_filing_frequency: string;
  notes?: string;
};

export async function getClients(): Promise<Client[]> {
  const sb = getSupabaseClient();
  const { data, error } = await sb
    .from("clients")
    .select("*")
    .is("deleted_at", null)
    .order("client_name");

  if (error) throw new Error(error.message);
  return (data ?? []) as Client[];
}

export async function createClient(input: CreateClientInput): Promise<Client> {
  const sb = getSupabaseClient();

  // Get firm_id from current user's session
  const { data: { session } } = await sb.auth.getSession();
  if (!session) throw new Error("Not authenticated");

  // Resolve firm_id
  const { data: userData, error: userErr } = await sb
    .from("users")
    .select("firm_id")
    .eq("auth_user_id", session.user.id)
    .single();

  if (userErr || !userData) throw new Error("User not found in firm");

  const { data, error } = await sb
    .from("clients")
    .insert({
      ...input,
      firm_id: userData.firm_id,
      status: "active",
    })
    .select()
    .single();

  if (error) throw new Error(error.message);
  return data as Client;
}

export async function updateClient(id: string, input: Partial<CreateClientInput>): Promise<Client> {
  const sb = getSupabaseClient();
  const { data, error } = await sb
    .from("clients")
    .update({ ...input, updated_at: new Date().toISOString() })
    .eq("id", id)
    .select()
    .single();

  if (error) throw new Error(error.message);
  return data as Client;
}

export async function getClient(id: string): Promise<Client> {
  const sb = getSupabaseClient();
  const { data, error } = await sb
    .from("clients")
    .select("*")
    .eq("id", id)
    .is("deleted_at", null)
    .single();
  if (error) throw new Error(error.message);
  return data as Client;
}

export async function deleteClient(id: string): Promise<void> {
  const sb = getSupabaseClient();
  const { error } = await sb
    .from("clients")
    .update({ deleted_at: new Date().toISOString() })
    .eq("id", id);
  if (error) throw new Error(error.message);
}
