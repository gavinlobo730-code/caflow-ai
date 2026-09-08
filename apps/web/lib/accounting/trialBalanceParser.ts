import { paiseFromRupeeInput } from "../money/rupeeInput.ts";
/**
 * Trial Balance CSV parsing — extracted from the importer page so the
 * parse/type-detection/amount logic is testable independent of Supabase
 * availability (C4). Behavior is unchanged from the original inline code.
 */

export function parseCSV(text: string): string[][] {
  const rows: string[][] = [];
  let i = 0;
  while (i < text.length) {
    const row: string[] = [];
    while (i < text.length && text[i] !== "\n" && text[i] !== "\r") {
      let field = "";
      if (text[i] === '"') {
        i++; // skip opening quote
        while (i < text.length) {
          if (text[i] === '"' && text[i + 1] === '"') { field += '"'; i += 2; }
          else if (text[i] === '"') { i++; break; }
          else { field += text[i++]; }
        }
      } else {
        while (i < text.length && text[i] !== "," && text[i] !== "\n" && text[i] !== "\r") {
          field += text[i++];
        }
      }
      row.push(field.trim());
      if (i < text.length && text[i] === ",") i++;
    }
    if (text[i] === "\r") i++;
    if (text[i] === "\n") i++;
    if (row.length > 0 && !(row.length === 1 && row[0] === "")) rows.push(row);
  }
  return rows;
}

export function detectType(name: string): string {
  const n = name.toLowerCase();
  if (/sales|revenue|income|turnover/.test(n)) return "revenue";
  if (/purchase|cogs|cost of/.test(n)) return "expense";
  if (/expense|depreciation|salary|rent|utilities/.test(n)) return "expense";
  if (/cash|bank|receivable|debtor|advances paid/.test(n)) return "asset";
  if (/fixed asset|plant|machinery|building|vehicle|furniture/.test(n)) return "asset";
  if (/payable|creditor|loan payable|advances received/.test(n)) return "liability";
  if (/capital|reserve|retained earnings|equity/.test(n)) return "equity";
  return "asset";
}

/**
 * One trial-balance cell → integer paise, or null when the cell is not an
 * amount. Always positive: the Dr/Cr column decides the sign, so accounting
 * parentheses are stripped rather than negated here.
 *
 * It was `Math.round(Math.abs(parseFloat(clean) || 0) * 100)`. `|| 0` made
 * every unreadable cell a zero, and a zero in a trial balance is not a missing
 * figure — it is a claim that the account has no balance. The import posts ONE
 * balanced opening journal from these rows, so a silently-zeroed cell either
 * unbalances the entry (and the backend refuses it, with nothing on screen
 * saying which row) or, where the same account had a figure in the other
 * column, balances it at the WRONG opening position.
 */
export function parseAmount(s: string): number | null {
  // Strip the currency and thousands marks, and the accounting parentheses.
  const clean = s.replace(/[,\s₹]/g, "").replace(/^Rs\.?/i, "").replace(/^\((.+)\)$/, "$1");
  const paise = paiseFromRupeeInput(clean);
  return paise === null ? null : Math.abs(paise); // paise, always positive
}

export type ParsedAccount = {
  account_name: string;
  account_code: string;
  account_type: string;
  dr_balance: string;
  cr_balance: string;
  dr_paise: number;
  cr_paise: number;
  /** The cell held text that is not an amount. dr_paise/cr_paise is 0 for it,
   *  which is why the flag has to travel with the row: 0 and "unreadable" are
   *  the same number meaning opposite things. */
  dr_unreadable: boolean;
  cr_unreadable: boolean;
  typeOverride?: string;
};

export type ColumnMap = {
  nameCol: number;
  codeCol: number;
  drCol: number;
  crCol: number;
  typeCol: number;
};

export function buildParsedAccounts(rawRows: string[][], colMap: ColumnMap): ParsedAccount[] {
  return rawRows
    .map((row) => {
      const name = row[colMap.nameCol] ?? "";
      const code = colMap.codeCol >= 0 ? (row[colMap.codeCol] ?? "") : "";
      const drRaw = colMap.drCol >= 0 ? (row[colMap.drCol] ?? "0") : "0";
      const crRaw = colMap.crCol >= 0 ? (row[colMap.crCol] ?? "0") : "0";
      const typeRaw = colMap.typeCol >= 0 ? (row[colMap.typeCol] ?? "") : "";
      const dr = parseAmount(drRaw);
      const cr = parseAmount(crRaw);
      return {
        account_name: name,
        account_code: code,
        account_type: typeRaw ? typeRaw.toLowerCase() : detectType(name),
        dr_balance: drRaw,
        cr_balance: crRaw,
        dr_paise: dr ?? 0,
        cr_paise: cr ?? 0,
        dr_unreadable: dr === null,
        cr_unreadable: cr === null,
      };
    })
    .filter((a) => a.account_name.trim() !== "");
}
