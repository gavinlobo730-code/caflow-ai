/**
 * The client's ACTIVE bank accounts, asked of the server.
 *
 * Four screens (the Bank Book, the payment-account picker, the sales receipt
 * and the fixed-asset purchase) used to read `bank_accounts` straight from the
 * browser over PostgREST, so the only control on what a person could list was
 * the database's row security, and the per-person Banking permission the Team
 * screen sets was asked nowhere on that path (POST-A-010). They ask
 * `GET /api/banking/accounts` now, which asks `rbac("banking", "read")`, the
 * caller's assignment to the client and the firm, once.
 *
 * It THROWS when the server refuses or fails. Returning an empty list there
 * would show a person without Banking access the same "no bank accounts" that
 * a client with none gets, and the empty option of the payment picker says it
 * posts to the general Bank ledger, which is a statement about what will
 * happen to a payment.
 *
 * The rows are the server's, so `opening_balance_paise` is in the statement
 * sign the bank screens use (a credit card's balance is the amount OWED).
 * Nothing here reads that figure, and a caller that needs it should read it
 * from the same response and not from this module.
 */
import { api } from "@/lib/api";

export interface ActiveBankAccountRow {
  id: string;
  bank_name: string;
  account_no: string;
}

export async function fetchActiveBankAccounts<T extends ActiveBankAccountRow = ActiveBankAccountRow>(
  clientId: string,
): Promise<T[]> {
  const res = (await api.banking.listBankAccounts({ client_id: clientId })) as {
    success?: boolean;
    data?: unknown;
    error?: string | null;
  };
  if (!res || res.success === false) {
    throw new Error(res?.error || "Bank accounts could not be loaded.");
  }
  return Array.isArray(res.data) ? (res.data as T[]) : [];
}
