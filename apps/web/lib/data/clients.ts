/**
 * Client data layer — reads/writes directly to Supabase from the frontend.
 * Firm isolation is enforced by RLS (firm_id = get_my_firm_id()).
 * Lifecycle mutations (archive/restore/delete) go through the FastAPI backend
 * so audit logging and dependency checks are enforced server-side.
 */
import { getSupabaseClient } from "@/lib/supabase/client";
import { api } from "@/lib/api";
import type { Client } from "@/lib/types";

export type ClientFilter = "active" | "archived" | "all";

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

/** Thrown by permanentDeleteClient when the server returns 409 (historical records exist). */
export class DeleteBlockedError extends Error {
  constructor(public readonly blockers: string[]) {
    super("Client cannot be permanently deleted — archive instead");
  }
}

export async function getClients(filter: ClientFilter = "active"): Promise<Client[]> {
  const sb = getSupabaseClient();
  let q = sb
    .from("clients")
    .select("*")
    .is("deleted_at", null)
    .eq("is_internal", false);   // Guardrail G2: exclude the firm-as-internal-client

  if (filter === "active") q = q.neq("status", "archived");
  else if (filter === "archived") q = q.eq("status", "archived");
  // filter === "all": no additional status constraint

  const { data, error } = await q.order("client_name");
  if (error) throw new Error(error.message);
  return (data ?? []) as Client[];
}

export async function createClient(input: CreateClientInput): Promise<Client> {
  const sb = getSupabaseClient();

  const { data: { session } } = await sb.auth.getSession();
  if (!session) throw new Error("Not authenticated");

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

/** Archive a client — goes through the backend for audit logging (Manager+). */
export async function archiveClient(id: string): Promise<void> {
  await api.clients.archive(id);
}

/** Restore an archived client to active status (Manager+). */
export async function restoreClient(id: string): Promise<void> {
  await api.clients.restore(id);
}

/**
 * Permanently soft-delete a client (Partner only).
 * Throws DeleteBlockedError if the client has linked records that prevent deletion.
 * The server returns 409 with { detail: { message, blockers } } in that case.
 */
export async function permanentDeleteClient(id: string): Promise<void> {
  try {
    await api.clients.permanentDelete(id);
  } catch (e) {
    if (e instanceof Error && e.message.startsWith("API error 409:")) {
      const jsonStr = e.message.slice("API error 409: ".length);
      try {
        const body = JSON.parse(jsonStr);
        if (Array.isArray(body?.detail?.blockers)) {
          throw new DeleteBlockedError(body.detail.blockers);
        }
      } catch (inner) {
        if (inner instanceof DeleteBlockedError) throw inner;
      }
    }
    throw e;
  }
}
