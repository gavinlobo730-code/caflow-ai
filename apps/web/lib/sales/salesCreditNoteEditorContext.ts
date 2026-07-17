"use client";

/**
 * Data loading for the Sales Credit Note editor route — mirrors
 * lib/sales/salesDebitNoteEditorContext.ts. Focused read: active customers.
 * No new endpoints, no duplicated business logic.
 */
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import type { Customer } from "@/lib/invoices/gst";
import type { SalesCreditNoteDetail } from "@/components/sales/SalesCreditNoteEditor";
import { apiGet, getAuthToken } from "@/lib/invoices/shared";

export interface SalesCreditNoteEditorContext {
  customers: Customer[];
  clientName: string;
}

export async function loadSalesCreditNoteEditorContext(clientId: string): Promise<SalesCreditNoteEditorContext> {
  const supabase = getSupabaseClient();
  const [{ data: custData }, { data: clientData }] = await Promise.all([
    selectAll(() => supabase
      .from("customers")
      .select("id, name, gstin, state_code, pan, email, phone, city, state, opening_balance_paise, credit_days, is_active")
      .eq("client_id", clientId)
      .eq("is_active", true)
      .order("name")
      .order("id")),
    supabase.from("clients").select("client_name").eq("id", clientId).maybeSingle(),
  ]);
  const c = clientData as { client_name: string | null } | null;
  return {
    customers: (custData as Customer[]) ?? [],
    clientName: c?.client_name ?? "",
  };
}

/** Load a single sales credit note's full detail (Edit route). Returns null when not found. */
export async function loadSalesCreditNoteDetail(cnId: string): Promise<SalesCreditNoteDetail | null> {
  const token = await getAuthToken();
  const r = await apiGet(`/api/credit-notes/${cnId}`, token);
  return r.success && r.data ? (r.data as SalesCreditNoteDetail) : null;
}
