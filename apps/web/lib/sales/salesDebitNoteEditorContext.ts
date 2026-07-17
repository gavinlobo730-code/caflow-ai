"use client";

/**
 * Data loading for the Sales Debit Note editor route — mirrors
 * lib/purchases/debitNoteEditorContext.ts. Focused read: active customers.
 * No new endpoints, no duplicated business logic.
 */
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import type { Customer } from "@/lib/invoices/gst";
import type { SalesDebitNoteDetail } from "@/components/sales/SalesDebitNoteEditor";
import { apiGet, getAuthToken } from "@/lib/invoices/shared";

export interface SalesDebitNoteEditorContext {
  customers: Customer[];
  clientName: string;
}

export async function loadSalesDebitNoteEditorContext(clientId: string): Promise<SalesDebitNoteEditorContext> {
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

/** Load a single sales debit note's full detail (Edit route). Returns null when not found. */
export async function loadSalesDebitNoteDetail(sdnId: string): Promise<SalesDebitNoteDetail | null> {
  const token = await getAuthToken();
  const r = await apiGet(`/api/sales-debit-notes/${sdnId}`, token);
  return r.success && r.data ? (r.data as SalesDebitNoteDetail) : null;
}
