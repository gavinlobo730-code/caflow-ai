/**
 * Transaction feed for /reports and /client-portal.
 *
 * These functions used to query a `transactions` table directly. Migration 139
 * dropped it as an abandoned parallel model — correctly, the live double-entry
 * books are journal_entries + journal_lines — but recorded that "no code reads
 * or writes it", which was true of the backend and false of this file. Both
 * screens have been failing on a missing relation ever since.
 *
 * There is no single live table to swap in: a sale is a client_sales_invoices
 * row and a purchase is a purchase_bills row, with different column names and
 * different parties. Deciding what "a transaction" means is therefore a real
 * decision, and it lives in the backend (services/report_transactions_service.py)
 * rather than here — CLAUDE.md, zero business logic in the frontend. This file
 * is now just the typed client for those two endpoints.
 *
 * All amounts remain integer paise. Nothing here divides by 100.
 */
import { api } from "@/lib/api";

export interface Transaction {
  id: string;
  client_id: string;
  /** "sales_invoice" | "purchase_invoice" — the vocabulary the reports split on. */
  transaction_type: string;
  transaction_date: string;
  reference_no?: string;
  party_name: string;
  taxable_amount_paise: number;
  cgst_paise: number;
  sgst_paise: number;
  igst_paise: number;
  tds_paise: number;
  tds_section?: string | null;
  total_paise: number;
  paid_paise: number;
  /** total − paid, floored at zero. Computed server-side so every caller that
   *  asks "what is still owed" gets the same answer. */
  outstanding_paise: number;
  is_interstate: boolean;
  place_of_supply?: string | null;
  status: string;
}

export interface GSTSummary {
  period: string;
  gstr1: {
    taxable: number; cgst: number; sgst: number; igst: number;
    total: number; lines: Transaction[];
  };
  gstr3b: {
    output_cgst: number; output_sgst: number; output_igst: number;
    itc_cgst: number; itc_sgst: number; itc_igst: number;
    net_cgst: number; net_sgst: number; net_igst: number;
  };
  tds_deducted: number;
  ca_review_required: true;
}

/**
 * Issued sales invoices and received purchase bills, newest first.
 *
 * Omitting `clientId` returns every client the caller is assigned to — the
 * backend resolves that from the token, so this cannot be widened from here.
 * The `type` parameter the old signature accepted is gone: both callers filtered
 * on `transaction_type` themselves afterwards, and a server-side filter nobody
 * used was one more thing to keep in step.
 */
export async function getTransactions(clientId?: string): Promise<Transaction[]> {
  const res = await api.reports.transactions(clientId);
  if (!res.success) throw new Error(res.error ?? "Failed to load transactions");
  return res.data.transactions;
}

/** GSTR-1 / GSTR-3B working figures for one client-month (month: "YYYY-MM"). */
export async function getGSTSummary(clientId: string, month: string): Promise<GSTSummary> {
  const res = await api.reports.gstSummary(clientId, month);
  if (!res.success) throw new Error(res.error ?? "Failed to load GST summary");
  return res.data;
}
