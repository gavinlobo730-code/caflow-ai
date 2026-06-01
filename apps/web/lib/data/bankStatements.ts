/**
 * Bank Statement import layer.
 * Parses CSV exports from major Indian banks.
 * Ref: RBI guidelines on bank statement formats
 */
import { getSupabaseClient } from "@/lib/supabase/client";

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

async function getFirmId(): Promise<string> {
  const sb = getSupabaseClient();
  const { data: { session } } = await sb.auth.getSession();
  if (!session) throw new Error("Not authenticated");
  const { data } = await sb.from("users").select("firm_id").eq("auth_user_id", session.user.id).single();
  if (!data) throw new Error("User not found");
  return data.firm_id;
}

export async function importBankStatement(
  clientId: string,
  bankName: string,
  accountNumber: string,
  transactions: ParsedTransaction[],
): Promise<BankStatement> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();

  if (transactions.length === 0) throw new Error("No transactions found in file");

  const dates = transactions.map(t => t.date).sort();
  const totalDebits = transactions.reduce((s, t) => s + t.debit_paise, 0);
  const totalCredits = transactions.reduce((s, t) => s + t.credit_paise, 0);
  const opening = transactions[0]?.balance_paise ?? 0;
  const closing = transactions[transactions.length - 1]?.balance_paise ?? 0;

  const { data: stmt, error: stmtErr } = await sb.from("bank_statements").insert({
    firm_id: firmId,
    client_id: clientId,
    bank_name: bankName,
    account_number: accountNumber,
    statement_from: dates[0],
    statement_to: dates[dates.length - 1],
    opening_balance_paise: opening,
    closing_balance_paise: closing,
    total_debits_paise: totalDebits,
    total_credits_paise: totalCredits,
    row_count: transactions.length,
    import_status: "pending",
  }).select().single();

  if (stmtErr || !stmt) throw new Error(stmtErr?.message ?? "Failed to create statement");

  const rows = transactions.map(t => ({
    statement_id: stmt.id,
    firm_id: firmId,
    client_id: clientId,
    transaction_date: t.date,
    description: t.description,
    debit_paise: t.debit_paise,
    credit_paise: t.credit_paise,
    balance_paise: t.balance_paise,
    reference_no: t.reference_no,
    match_status: "unmatched",
  }));

  await sb.from("bank_transactions").insert(rows);
  return stmt as BankStatement;
}

export async function getBankStatements(clientId: string): Promise<BankStatement[]> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();
  const { data, error } = await sb.from("bank_statements")
    .select("*").eq("firm_id", firmId).eq("client_id", clientId)
    .order("created_at", { ascending: false });
  if (error) throw new Error(error.message);
  return (data ?? []) as BankStatement[];
}

export async function getBankTransactions(statementId: string): Promise<BankTransaction[]> {
  const sb = getSupabaseClient();
  const { data, error } = await sb.from("bank_transactions")
    .select("*").eq("statement_id", statementId)
    .order("transaction_date");
  if (error) throw new Error(error.message);
  return (data ?? []) as BankTransaction[];
}

export async function updateTransactionAccount(id: string, accountId: string): Promise<void> {
  const sb = getSupabaseClient();
  await sb.from("bank_transactions").update({
    account_id: accountId,
    match_status: "matched",
    updated_at: new Date().toISOString(),
  }).eq("id", id);
}

export async function postBankStatement(statementId: string): Promise<void> {
  const sb = getSupabaseClient();
  await sb.from("bank_transactions")
    .update({ match_status: "posted", updated_at: new Date().toISOString() })
    .eq("statement_id", statementId).eq("match_status", "matched");
  await sb.from("bank_statements")
    .update({ import_status: "posted", updated_at: new Date().toISOString() })
    .eq("id", statementId);
}
