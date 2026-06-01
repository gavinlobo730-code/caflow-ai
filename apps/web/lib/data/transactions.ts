/**
 * Transaction data layer — Sales Invoices, Expenses, Journal Auto-creation
 * All amounts in paise (integer). Never float.
 * CGST Act Section 31: Tax Invoice requirements
 * IT Act Section 194: TDS deduction thresholds
 */
import { getSupabaseClient } from "@/lib/supabase/client";

export interface TransactionLine {
  description: string;
  hsn_sac_code?: string;
  quantity: number;
  unit: string;
  rate_paise: number;
  taxable_paise: number;
  gst_rate: number;
  cgst_paise: number;
  sgst_paise: number;
  igst_paise: number;
  total_paise: number;
}

export interface CreateInvoiceInput {
  client_id: string;
  transaction_type: "sales_invoice" | "purchase_invoice";
  transaction_date: string;
  reference_no?: string;
  party_name: string;
  party_gstin?: string;
  party_pan?: string;
  place_of_supply: string;
  is_interstate: boolean;
  lines: TransactionLine[];
  tds_section?: string;
  tds_rate?: number;
  notes?: string;
}

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

async function getFirmId(): Promise<string> {
  const sb = getSupabaseClient();
  const { data: { session } } = await sb.auth.getSession();
  if (!session) throw new Error("Not authenticated");
  const { data } = await sb.from("users").select("firm_id").eq("auth_user_id", session.user.id).single();
  if (!data) throw new Error("User not found");
  return data.firm_id;
}

/** Compute totals from lines — all in paise */
export function computeInvoiceTotals(lines: TransactionLine[], isInterstate: boolean) {
  let taxable = 0, cgst = 0, sgst = 0, igst = 0;
  for (const l of lines) {
    // Paise arithmetic — IT Act Section 145A
    const taxableP = Math.round(l.quantity * l.rate_paise);
    const gstAmt = Math.round(taxableP * l.gst_rate / 100);
    taxable += taxableP;
    if (isInterstate) {
      igst += gstAmt;
    } else {
      cgst += Math.round(gstAmt / 2);
      sgst += Math.round(gstAmt / 2);
    }
    l.taxable_paise = taxableP;
    l.cgst_paise = isInterstate ? 0 : Math.round(gstAmt / 2);
    l.sgst_paise = isInterstate ? 0 : Math.round(gstAmt / 2);
    l.igst_paise = isInterstate ? gstAmt : 0;
    l.total_paise = taxableP + gstAmt;
  }
  return { taxable, cgst, sgst, igst, total: taxable + cgst + sgst + igst };
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

export async function createInvoice(input: CreateInvoiceInput): Promise<Transaction> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();

  const { taxable, cgst, sgst, igst, total } = computeInvoiceTotals(input.lines, input.is_interstate);

  // TDS computation — IT Act Section 194
  let tdsPaise = 0;
  if (input.tds_rate && input.transaction_type === "purchase_invoice") {
    tdsPaise = Math.round(taxable * input.tds_rate / 100);
  }

  // Insert transaction
  const { data: txn, error: txnErr } = await sb.from("transactions").insert({
    firm_id: firmId,
    client_id: input.client_id,
    transaction_type: input.transaction_type,
    transaction_date: input.transaction_date,
    reference_no: input.reference_no,
    party_name: input.party_name,
    party_gstin: input.party_gstin,
    party_pan: input.party_pan,
    place_of_supply: input.place_of_supply,
    is_interstate: input.is_interstate,
    taxable_amount_paise: taxable,
    cgst_paise: cgst,
    sgst_paise: sgst,
    igst_paise: igst,
    tds_paise: tdsPaise,
    total_paise: total,
    tds_section: input.tds_section,
    tds_rate: input.tds_rate,
    notes: input.notes,
    status: "posted",
  }).select().single();

  if (txnErr || !txn) throw new Error(txnErr?.message ?? "Failed to create transaction");

  // Insert line items
  if (input.lines.length > 0) {
    const lineRows = input.lines.map(l => ({
      transaction_id: txn.id,
      description: l.description,
      hsn_sac_code: l.hsn_sac_code,
      quantity: l.quantity,
      unit: l.unit,
      rate_paise: l.rate_paise,
      taxable_paise: l.taxable_paise,
      gst_rate: l.gst_rate,
      cgst_paise: l.cgst_paise,
      sgst_paise: l.sgst_paise,
      igst_paise: l.igst_paise,
      total_paise: l.total_paise,
    }));
    await sb.from("transaction_lines").insert(lineRows);
  }

  return txn as Transaction;
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
