"use client";

/**
 * Data loading for the Purchase Debit Note editor route — mirrors
 * lib/purchases/editorContext.ts. Focused read: active vendors. No new
 * endpoints, no duplicated business logic.
 */
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import type { VendorLike } from "@/components/lookups/VendorLookup";
import type { DebitNoteDetail } from "@/components/purchases/DebitNoteEditor";
import { apiGet, getAuthToken } from "@/lib/invoices/shared";

export interface DebitNoteEditorContext {
  vendors: VendorLike[];
  clientName: string;
}

export async function loadDebitNoteEditorContext(clientId: string): Promise<DebitNoteEditorContext> {
  const supabase = getSupabaseClient();
  const [{ data: vendorData }, { data: clientData }] = await Promise.all([
    selectAll(() => supabase
      .from("vendors")
      .select("id, name, gstin, pan, email, phone, state_code, is_active")
      .eq("client_id", clientId)
      .eq("is_active", true)
      .order("name")
      .order("id")),
    supabase.from("clients").select("client_name").eq("id", clientId).maybeSingle(),
  ]);
  const c = clientData as { client_name: string | null } | null;
  return {
    vendors: (vendorData as VendorLike[]) ?? [],
    clientName: c?.client_name ?? "",
  };
}

/** Load a single debit note's full detail (Edit route). Returns null when not found. */
export async function loadDebitNoteDetail(dnId: string): Promise<DebitNoteDetail | null> {
  const token = await getAuthToken();
  const r = await apiGet(`/api/debit-notes/${dnId}`, token);
  return r.success && r.data ? (r.data as DebitNoteDetail) : null;
}
