"use client";

/**
 * Data loading for the invoice editor routes (Batch 2). Focused reads that mirror the
 * Sales list's queries (customers + the selling client's GST state), plus the single
 * invoice-detail fetch used by the Edit route. Reuses the shared REST client and
 * Supabase reader — no new endpoints, no duplicated business logic.
 */
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import { apiGet, getAuthToken, type Customer, type InvoiceDetail } from "@/lib/invoices/shared";

export interface InvoiceEditorContext {
  customers: Customer[];
  /** The selling client's own GST state code (drives IGST vs CGST+SGST). */
  clientStateCode: string;
  /** The client's display name (for the workspace breadcrumb). */
  clientName: string;
}

export async function loadInvoiceEditorContext(clientId: string): Promise<InvoiceEditorContext> {
  const supabase = getSupabaseClient();
  const [{ data: custData }, { data: clientData }] = await Promise.all([
    selectAll(() => supabase
      .from("customers")
      .select("id, name, gstin, state_code, pan, email, phone, city, state, opening_balance_paise, credit_days, is_active")
      .eq("client_id", clientId)
      .eq("is_active", true)
      .order("name")
      .order("id")),
    supabase.from("clients").select("client_name, gstin, state_code").eq("id", clientId).maybeSingle(),
  ]);
  const c = clientData as { client_name: string | null; gstin: string | null; state_code: string | null } | null;
  // THE GSTIN FIRST, matching `domain/gst/place_of_supply.supplier_state_code`.
  // This read `state_code || gstin.slice(0,2)` — the OPPOSITE precedence to the
  // server that actually decides the tax — so for a client with both recorded
  // and disagreeing, the preview and the saved document could differ by the
  // whole of it: IGST on screen, central + State tax in the ledger. CGST §25
  // makes the first two characters of a GSTIN the registration's state, so for
  // a registered person it is the authority and `clients.state_code` may be a
  // stale postal address.
  const clientStateCode = ((c?.gstin ? c.gstin.slice(0, 2) : "") || c?.state_code) ?? "";
  return { customers: (custData as Customer[]) ?? [], clientStateCode, clientName: c?.client_name ?? "" };
}

/** Load a single invoice's full detail (Edit route). Returns null when not found. */
export async function loadInvoiceDetail(invoiceId: string): Promise<InvoiceDetail | null> {
  const token = await getAuthToken();
  const r = await apiGet(`/api/sales-invoices/${invoiceId}`, token);
  return r.success && r.data ? (r.data as InvoiceDetail) : null;
}
