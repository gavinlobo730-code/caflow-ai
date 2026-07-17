"use client";

/**
 * Data loading for the Purchase Credit Note editor route — mirrors
 * lib/purchases/debitNoteEditorContext.ts.
 */
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import type { VendorLike } from "@/components/lookups/VendorLookup";
import type { PurchaseCreditNoteDetail } from "@/components/purchases/PurchaseCreditNoteEditor";
import { apiGet, getAuthToken } from "@/lib/invoices/shared";

export interface PurchaseCreditNoteEditorContext {
  vendors: VendorLike[];
  clientName: string;
}

export async function loadPurchaseCreditNoteEditorContext(clientId: string): Promise<PurchaseCreditNoteEditorContext> {
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

/** Load a single purchase credit note's full detail (Edit route). Returns null when not found. */
export async function loadPurchaseCreditNoteDetail(pcnId: string): Promise<PurchaseCreditNoteDetail | null> {
  const token = await getAuthToken();
  const r = await apiGet(`/api/purchase-credit-notes/${pcnId}`, token);
  return r.success && r.data ? (r.data as PurchaseCreditNoteDetail) : null;
}
