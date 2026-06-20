/**
 * Bank Statement layer.
 *
 * CSV parsing (parseCSV) is pure and runs client-side. Every MUTATION and READ
 * of bank data now goes through the backend banking API (api.banking.*) — the
 * browser no longer writes bank statements, transactions, or journal entries to
 * Supabase directly (Phase B.0; CLAUDE.md: zero business logic in the frontend).
 * Ref: RBI guidelines on bank statement formats.
 */
import { api, type ApiResp } from "@/lib/api";

export interface ParsedTransaction {
  date: string;
  description: string;
  debit_paise: number;
  credit_paise: number;
  balance_paise: number;
  reference_no: string;
}

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

/** Convert rupee string to paise integer — never float */
function parsePaise(val: string): number {
  if (!val || val.trim() === "" || val.trim() === "-") return 0;
  const cleaned = val.replace(/[₹,\s]/g, "").trim();
  const num = parseFloat(cleaned);
  if (isNaN(num)) return 0;
  return Math.round(num * 100);
}

function parseDate(val: string): string {
  val = val.trim();
  // DD/MM/YYYY or DD-MM-YYYY
  const m1 = val.match(/^(\d{2})[\/\-](\d{2})[\/\-](\d{4})$/);
  if (m1) return `${m1[3]}-${m1[2]}-${m1[1]}`;
  // YYYY-MM-DD
  if (/^\d{4}-\d{2}-\d{2}$/.test(val)) return val;
  // DD MMM YYYY
  const months: Record<string, string> = {
    Jan:"01",Feb:"02",Mar:"03",Apr:"04",May:"05",Jun:"06",
    Jul:"07",Aug:"08",Sep:"09",Oct:"10",Nov:"11",Dec:"12"
  };
  const m2 = val.match(/^(\d{2})\s([A-Za-z]{3})\s(\d{4})$/);
  if (m2) return `${m2[3]}-${months[m2[2]] ?? "01"}-${m2[1]}`;
  return val;
}

/** Auto-detect bank format from CSV headers */
function detectFormat(headers: string[]): string {
  const h = headers.map(h => h.toLowerCase().trim());
  if (h.some(x => x.includes("chq") || x.includes("cheque"))) return "hdfc";
  if (h.some(x => x.includes("txn date"))) return "sbi";
  if (h.some(x => x.includes("transaction remarks"))) return "icici";
  if (h.some(x => x.includes("narration"))) return "axis";
  return "generic";
}

export function parseCSV(csvText: string): ParsedTransaction[] {
  const lines = csvText.split("\n").map(l => l.trim()).filter(Boolean);
  if (lines.length < 2) return [];

  // Find header row
  let headerIdx = 0;
  for (let i = 0; i < Math.min(10, lines.length); i++) {
    const lower = lines[i].toLowerCase();
    if (lower.includes("date") && (lower.includes("debit") || lower.includes("amount") || lower.includes("withdrawal"))) {
      headerIdx = i;
      break;
    }
  }

  const headers = lines[headerIdx].split(",").map(h => h.replace(/"/g, "").trim());
  const format = detectFormat(headers);
  const results: ParsedTransaction[] = [];

  for (let i = headerIdx + 1; i < lines.length; i++) {
    const cols = lines[i].split(",").map(c => c.replace(/"/g, "").trim());
    if (cols.length < 3) continue;

    let date = "", desc = "", debit = "0", credit = "0", balance = "0", ref = "";

    if (format === "hdfc") {
      // Date, Narration, Value Dt, Ref No, Debit, Credit, Balance
      date = cols[0]; desc = cols[1]; ref = cols[3] ?? "";
      debit = cols[4] ?? "0"; credit = cols[5] ?? "0"; balance = cols[6] ?? "0";
    } else if (format === "sbi") {
      // Txn Date, Value Date, Description, Ref No/Cheque No, Debit, Credit, Balance
      date = cols[0]; desc = cols[2]; ref = cols[3] ?? "";
      debit = cols[4] ?? "0"; credit = cols[5] ?? "0"; balance = cols[6] ?? "0";
    } else if (format === "icici") {
      // Transaction Date, Value Date, Transaction Remarks, Ref No, Debit Amount, Credit Amount, Balance
      date = cols[0]; desc = cols[2]; ref = cols[3] ?? "";
      debit = cols[4] ?? "0"; credit = cols[5] ?? "0"; balance = cols[6] ?? "0";
    } else if (format === "axis") {
      // Tran Date, CHQNO, Narration, Debit, Credit, Balance
      date = cols[0]; ref = cols[1] ?? ""; desc = cols[2];
      debit = cols[3] ?? "0"; credit = cols[4] ?? "0"; balance = cols[5] ?? "0";
    } else {
      // Generic: try to find date, description, debit, credit
      date = cols[0]; desc = cols[1];
      debit = cols[2] ?? "0"; credit = cols[3] ?? "0"; balance = cols[4] ?? "0";
    }

    const parsedDate = parseDate(date);
    if (!parsedDate || parsedDate === date && !/^\d{4}-\d{2}-\d{2}$/.test(parsedDate)) continue;
    if (!desc.trim()) continue;

    results.push({
      date: parsedDate,
      description: desc.trim(),
      debit_paise: parsePaise(debit),
      credit_paise: parsePaise(credit),
      balance_paise: parsePaise(balance),
      reference_no: ref.trim(),
    });
  }

  return results;
}


export async function importBankStatement(
  clientId: string,
  bankName: string,
  accountNumber: string,
  transactions: ParsedTransaction[],
): Promise<BankStatement> {
  if (transactions.length === 0) throw new Error("No transactions found in file");

  const rows = transactions.map(t => ({
    transaction_date: t.date,
    description: t.description,
    debit_paise: t.debit_paise,
    credit_paise: t.credit_paise,
    balance_paise: t.balance_paise,
    reference_no: t.reference_no,
  }));

  const res = (await api.banking.importStatement({
    client_id: clientId, bank_name: bankName, account_number: accountNumber, rows,
  })) as ApiResp<{ statement_id: string; imported: number }>;
  if (!res.success || !res.data) throw new Error(res.error ?? "Failed to import statement");

  // Header totals are computed authoritatively by the backend; this return is a
  // convenience shape for callers that read .id / .row_count after import.
  const dates = transactions.map(t => t.date).sort();
  return {
    id: res.data.statement_id,
    client_id: clientId,
    bank_name: bankName,
    account_number: accountNumber,
    statement_from: dates[0],
    statement_to: dates[dates.length - 1],
    opening_balance_paise: transactions[0]?.balance_paise ?? 0,
    closing_balance_paise: transactions[transactions.length - 1]?.balance_paise ?? 0,
    total_credits_paise: transactions.reduce((s, t) => s + t.credit_paise, 0),
    total_debits_paise: transactions.reduce((s, t) => s + t.debit_paise, 0),
    row_count: res.data.imported,
    import_status: "pending",
    created_at: new Date().toISOString(),
  };
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
