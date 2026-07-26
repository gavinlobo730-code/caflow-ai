import { getFirmId } from "./getFirmId";
/**
 * Transaction data layer — READ-ONLY access to the legacy `transactions` table.
 *
 * All amounts in paise (integer). Never float.
 *
 * Scope note: this module reads only. The invoice-WRITE path that used to live
 * here (`createInvoice` + `computeInvoiceTotals`, plus the `TransactionLine` /
 * `CreateInvoiceInput` / `SupplyType` / `InvoiceType` types that existed solely
 * to feed it) was deleted — it had zero callers, wrote straight to Supabase
 * from the browser instead of going through the API, and duplicated GST logic
 * that had drifted into being wrong (it halved the tax with Math.round on BOTH
 * legs, so an odd tax amount overstated CGST+SGST by a paise and left the
 * header total disagreeing with the sum of its own lines).
 *
 * Sales invoices are created through POST /api/sales-invoices/ only; the GST
 * arithmetic has exactly one client-side mirror, lib/money/gstLine.ts, which is
 * pinned to the backend by shared/gst-parity-vectors.json. Do not reintroduce a
 * second implementation here.
 */
import { getSupabaseClient } from "@/lib/supabase/client";

export interface Transaction {
  id: string;
  firm_id: string;
  client_id: string;
  transaction_type: string;
  transaction_date: string;
  reference_no?: string;
  party_name: string;
  party_gstin?: string;
  taxable_amount_paise: number;
  cgst_paise: number;
  sgst_paise: number;
  igst_paise: number;
  tds_paise: number;
  total_paise: number;
  gst_rate?: number;
  is_interstate: boolean;
  place_of_supply?: string;
  tds_section?: string;
  status: string;
  notes?: string;
  created_at: string;
}

export async function getTransactions(clientId?: string, type?: string): Promise<Transaction[]> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();
  let q = sb.from("transactions").select("*").eq("firm_id", firmId).is("deleted_at", null).order("transaction_date", { ascending: false });
  if (clientId) q = q.eq("client_id", clientId);
  if (type) q = q.eq("transaction_type", type);
  const { data, error } = await q;
  if (error) throw new Error(error.message);
  return (data ?? []) as Transaction[];
}

export async function getGSTSummary(clientId: string, month: string) {
  // month: "2025-06"
  const sb = getSupabaseClient();
  const firmId = await getFirmId();
  const from = `${month}-01`;
  const to = `${month}-31`;

  const { data } = await sb.from("transactions")
    .select("transaction_type,taxable_amount_paise,cgst_paise,sgst_paise,igst_paise,tds_paise,total_paise,party_name,party_gstin,place_of_supply,is_interstate,transaction_date,reference_no")
    .eq("firm_id", firmId)
    .eq("client_id", clientId)
    .eq("status", "posted")
    .gte("transaction_date", from)
    .lte("transaction_date", to)
    .is("deleted_at", null);

  const sales = (data ?? []).filter(t => t.transaction_type === "sales_invoice");
  const purchases = (data ?? []).filter(t => t.transaction_type === "purchase_invoice");

  const sum = (arr: typeof sales, field: string) =>
    arr.reduce((s, t) => s + ((t as Record<string, number>)[field] ?? 0), 0);

  return {
    // GSTR-1 — Outward supplies
    gstr1: {
      taxable: sum(sales, "taxable_amount_paise"),
      cgst: sum(sales, "cgst_paise"),
      sgst: sum(sales, "sgst_paise"),
      igst: sum(sales, "igst_paise"),
      total: sum(sales, "total_paise"),
      lines: sales,
    },
    // GSTR-3B — Output tax liability and ITC
    gstr3b: {
      output_cgst: sum(sales, "cgst_paise"),
      output_sgst: sum(sales, "sgst_paise"),
      output_igst: sum(sales, "igst_paise"),
      itc_cgst: sum(purchases, "cgst_paise"),
      itc_sgst: sum(purchases, "sgst_paise"),
      itc_igst: sum(purchases, "igst_paise"),
      // Net liability — CGST Act Section 49
      net_cgst: sum(sales, "cgst_paise") - sum(purchases, "cgst_paise"),
      net_sgst: sum(sales, "sgst_paise") - sum(purchases, "sgst_paise"),
      net_igst: sum(sales, "igst_paise") - sum(purchases, "igst_paise"),
    },
    tds_deducted: sum(purchases, "tds_paise"),
  };
}
