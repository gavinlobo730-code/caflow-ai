/**
 * Bank Statement layer — reads and mutations, through the backend banking API.
 *
 * NO PARSING HERE, AND THAT IS THE POINT. This file used to export `parseCSV`:
 * a second bank-statement parser, with its own bank-format detector, its own
 * date reader and its own paise parser, and an `importBankStatement` that
 * POSTed the result to /statements/import. `domain/banking/normalizer.py` is
 * the parser — seven column adapters, the CA's saved mapping, dedup, and the
 * tie-out against the statement's own printed totals — and none of that can
 * reach a file the browser has already turned into rows.
 *
 * Neither export had a caller. They were deleted rather than repaired when
 * BANK-22 made the bank account required on an import, because
 * `importBankStatement` had no parameter for one: two implementations drift,
 * and this one had drifted into being the one that could not be made right.
 *
 * Every mutation and read goes through api.banking.* — the browser writes no
 * bank statement, transaction or journal entry to Supabase directly (Phase B.0;
 * CLAUDE.md: zero business logic in the frontend).
 */
import { api, type ApiResp } from "@/lib/api";

export interface BankStatement {
  id: string;
  client_id: string;
  bank_name: string;
  account_number?: string;
  statement_from: string;
  statement_to: string;
  opening_balance_paise: number;
  closing_balance_paise: number;
  total_credits_paise: number;
  total_debits_paise: number;
  row_count: number;
  import_status: string;
  created_at: string;
}

export interface BankTransaction {
  id: string;
  statement_id: string;
  transaction_date: string;
  description: string;
  debit_paise: number;
  credit_paise: number;
  balance_paise?: number;
  reference_no?: string;
  match_status: string;
  account_id?: string;
}


export async function getBankStatements(clientId: string): Promise<BankStatement[]> {
  const res = (await api.banking.listStatements({ client_id: clientId })) as ApiResp<BankStatement[]>;
  if (!res.success) throw new Error(res.error ?? "Failed to load statements");
  return res.data ?? [];
}

export async function getBankTransactions(statementId: string): Promise<BankTransaction[]> {
  const res = (await api.banking.listTransactions({ statement_id: statementId })) as ApiResp<BankTransaction[]>;
  if (!res.success) throw new Error(res.error ?? "Failed to load transactions");
  return res.data ?? [];
}

export async function updateTransactionAccount(id: string, accountId: string): Promise<void> {
  const res = (await api.banking.setTransactionAccount(id, { account_id: accountId })) as ApiResp<unknown>;
  if (!res.success) throw new Error(res.error ?? "Failed to update transaction");
}

/**
 * Post a single bank transaction to the accounting ledger (double-entry).
 *
 * The double-entry generation now lives in the backend banking service (which
 * reuses the shared journal engine and enforces FY locks) — the browser only
 * triggers it. bankAccountId is the bank's GL (chart_of_accounts) account;
 * accountId is the mapped counter-account.
 * Double-entry rules (IT Act §145): money out of bank → Dr counter / Cr bank;
 * money into bank → Dr bank / Cr counter.
 */
export async function postBankTransaction(
  transactionId: string,
  accountId: string,
  bankAccountId: string,
): Promise<void> {
  const res = (await api.banking.postTransaction(transactionId, {
    account_id: accountId, bank_account_id: bankAccountId,
  })) as ApiResp<unknown>;
  if (!res.success) throw new Error(res.error ?? "Failed to post transaction");
}

/** Mark a bank transaction as ignored (no ledger impact). */
export async function ignoreBankTransaction(transactionId: string): Promise<void> {
  const res = (await api.banking.ignoreTransaction(transactionId)) as ApiResp<unknown>;
  if (!res.success) throw new Error(res.error ?? "Failed to ignore transaction");
}

export async function getAllBankStatements(): Promise<BankStatement[]> {
  const res = (await api.banking.listStatements()) as ApiResp<BankStatement[]>;
  if (!res.success) throw new Error(res.error ?? "Failed to load statements");
  return res.data ?? [];
}
