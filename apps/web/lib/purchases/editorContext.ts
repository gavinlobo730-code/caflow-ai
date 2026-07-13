"use client";

/**
 * Data loading for the Purchase Bill editor route — mirrors
 * lib/invoices/editorContext.ts. Focused reads: active vendors, expense/
 * asset accounts, and the buying client's own GST state (drives the
 * CGST+SGST vs IGST preview split). No new endpoints, no duplicated
 * business logic — the backend independently recomputes is_interstate
 * from the live vendor/client rows on save.
 */
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import type { PurchaseVendor } from "@/components/purchases/PurchaseBillEditor";
import type { AccountLike } from "@/components/lookups/AccountLookup";

export interface PurchaseBillEditorContext {
  vendors: PurchaseVendor[];
  accounts: AccountLike[];
  clientStateCode: string;
  clientName: string;
}

export async function loadPurchaseBillEditorContext(clientId: string): Promise<PurchaseBillEditorContext> {
  const supabase = getSupabaseClient();
  const [{ data: vendorData }, { data: accData }, { data: clientData }] = await Promise.all([
    selectAll(() => supabase
      .from("vendors")
      .select("id, name, gstin, pan, email, phone, state_code, tds_applicable, tds_section, tds_rate_bps, credit_days, is_active")
      .eq("client_id", clientId)
      .eq("is_active", true)
      .order("name")
      .order("id")),
    selectAll(() => supabase
      .from("chart_of_accounts")
      .select("id, account_code, account_name")
      .or(`client_id.eq.${clientId},client_id.is.null`)
      .in("account_type", ["Expense", "Asset"])
      .eq("is_active", true)
      .order("account_code")
      .order("id")),
    supabase.from("clients").select("client_name, gstin, state_code").eq("id", clientId).maybeSingle(),
  ]);
  const c = clientData as { client_name: string | null; gstin: string | null; state_code: string | null } | null;
  const clientStateCode = (c?.state_code || (c?.gstin ? c.gstin.slice(0, 2) : "")) ?? "";
  return {
    vendors: (vendorData as PurchaseVendor[]) ?? [],
    accounts: (accData as AccountLike[]) ?? [],
    clientStateCode,
    clientName: c?.client_name ?? "",
  };
}
